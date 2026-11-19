"""Deterministic Phase 1 signal invariants and one real-channel smoke run."""
from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

import numpy as np
import pytest

from scripts.research.task023.coherent import Hypotheses, hypotheses, kinematic_path, off_threshold
from scripts.research.task023.common import Channel, Estimate, RawEvaluator, load_channel, run_baselines
from scripts.research.task023.common import verify_baselines
from scripts.research.task023.demod import Anchor, Demodulator, PhaseState, _propagate
from scripts.research.task023.methods import m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod
from scripts.research.task023.pursuit import joint_fit, rail_mask
from scripts.research.task023.waveform import (
    WINDOW_NS, Float, chirp_phase, detrend, offsets, project_steps, quadrature, samples_for_ns,
    split_half_coherence,
)


def test_split_half_coherence_checks_continuation() -> None:
    tau = offsets(1024)/40e9
    phase = chirp_phase(tau, 1.3e9, -13e15)
    y = .2*np.cos(phase+.63) + .4 + 5e6*tau
    assert float(split_half_coherence(y, phase)) > .999999
    half = len(y)//2
    dropout = y.copy()
    dropout[half:] = .4 + 5e6*tau[half:]
    impulse = np.zeros_like(y)
    impulse[241] = 50.
    step = np.where(tau >= 0., 30., 0.)
    for artifact in (dropout, impulse, step):
        assert abs(float(split_half_coherence(artifact, phase))) < .05


@pytest.mark.parametrize("fs", [40e9, 80e9])
def test_step_projection_and_pre_step_center_guard(fs: float) -> None:
    t = np.arange(7168)/fs
    step = 3072
    hz = 1.12e9
    y = np.random.default_rng(23).normal(0., .0007, len(t))
    y[step:] += .9 + .012*np.cos(2*np.pi*hz*(t[step:]-t[step])+.37)
    ch = Channel("synthetic", t, y, fs)
    q = np.array([step-128, step+128], dtype=np.int64)
    width = samples_for_ns(25.6, fs)
    projected, split = project_steps(y, q, width, ch.quiet.steps)
    assert abs(int(ch.quiet.steps.index[0])-step) <= 1
    assert (split >= 0).all()
    # Step and tone differ by 75 times in amplitude.
    post = offsets(width)[split[1]:]/fs
    _, r2 = quadrature(projected[1, split[1]:], chirp_phase(post, hz, 0.))
    assert float(r2) > .96
    ev = RawEvaluator(ch)
    assert not ev.center_supported[ch.q == q[0]].item()
    result = m1_sw_wpd_tbd(ch)
    assert np.isnan(result.accepted_hz[ch.q < step]).all()
    for method in (m2_mc_decomp, m3_ss_demod):
        assert np.isnan(method(ch).accepted_hz[ch.q < step]).all()
    recovered = result.accepted_hz[(ch.q > step+128) & (ch.q < len(y)-512)]
    assert np.isfinite(recovered).mean() > .8
    np.testing.assert_allclose(recovered[np.isfinite(recovered)], hz, atol=25e6, rtol=0.)


def _receiver_noise(count: int, fs: float) -> Float:
    rng = np.random.default_rng(413)
    white = rng.normal(size=count)
    mask = np.fft.rfftfreq(count, 1/fs) <= 8.5e9
    noise = np.fft.irfft(np.fft.rfft(white)*mask)
    return np.asarray(noise / np.std(noise))


@pytest.mark.parametrize("method", [m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod])
def test_weak_narrowband_chirp_and_smooth_onset(method: Callable[[Channel], Estimate]) -> None:
    fs = 40e9
    t = np.arange(16384)/fs
    onset, h0, rate = 139.2e-9, 1.9e9, 5e15
    turn_on = np.clip((t-onset)/10e-9, 0., 1.)
    strong_seed = 2*np.clip((t-275e-9)/20e-9, 0., 1.)
    amplitude = (np.sqrt(2*10**(-.5))+strong_seed)*(.5-.5*np.cos(np.pi*turn_on))
    y = _receiver_noise(len(t), fs) + amplitude*np.cos(chirp_phase(t-onset, h0, rate)+.37)
    ch = Channel("weak_chirp", t, y, fs)
    assert not len(ch.quiet.steps.index)
    time = t[ch.q]
    weak = (time > onset+17e-9) & (time < 270e-9)
    expected = h0 + rate*(time-onset)
    result = method(ch)
    assert np.isnan(result.accepted_hz[time < onset]).all()
    recovered = abs(result.accepted_hz[weak]-expected[weak]) < 45e6
    assert recovered.mean() >= .70, f"{method.__name__}: {recovered.sum()}/{weak.sum()}"
    assert np.any(recovered & ~RawEvaluator(ch).center_supported[weak])


def test_smooth_40ns_dc_ramp_does_not_raise_cutoff_or_publish_low_frequency() -> None:
    fs = 40e9
    t = np.arange(16384)/fs
    u = np.clip((t-130e-9)/40e-9, 0., 1.)
    y = .001*_receiver_noise(len(t), fs) + .15*(6*u**5-15*u**4+10*u**3)
    ch = Channel("smooth_dc_ramp", t, y, fs)
    assert not len(ch.quiet.steps.index)
    for method in (m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod):
        result = method(ch)
        assert not np.any(result.accepted_hz < 250e6)
        if method is m1_sw_wpd_tbd:
            np.testing.assert_array_equal(result.diagnostics["off_threshold"], off_threshold())
    assert 2.75 <= off_threshold() <= 3.10


@pytest.mark.parametrize("fs, seed", [(40e9, 17), (80e9, 71)])
def test_gaussian_noise_bank_extreme_value_rate(fs: float, seed: int) -> None:
    t = np.arange(32768)/fs
    ch = Channel("gaussian_null", t, np.random.default_rng(seed).normal(size=len(t)), fs)
    peaks = hypotheses(ch).score
    assert len(peaks) > 240
    assert np.mean(np.any(peaks >= off_threshold(), axis=1)) <= .01


def test_quadratic_projection_with_censored_samples() -> None:
    tau = np.linspace(-1., 1., 512)
    trend = .3 + .2*tau - .17*tau**2
    weights = np.ones_like(trend)
    weights[255:300] = 0.
    corrupted = trend.copy()
    corrupted[weights == 0.] = 7.
    assert np.linalg.norm(detrend(trend)) > .5
    np.testing.assert_allclose(detrend(trend, degree=2), 0., atol=1e-14)
    np.testing.assert_allclose(detrend(corrupted, weights, 2)[weights > 0.], 0., atol=1e-14)


def test_low_frequency_tone_survives_curvature_check() -> None:
    fs, hz = 40e9, 125e6
    t = np.arange(8192)/fs
    tone = .016*np.cos(chirp_phase(t, hz, 0.)+.3)
    noise = np.random.default_rng(89).normal(0., .0007, len(t))
    ch = Channel("low_frequency", t, noise + np.where(t >= 60e-9, tone, 0.), fs)
    result = m1_sw_wpd_tbd(ch)
    stable = (t[ch.q] > 90e-9) & (t[ch.q] < 175e-9)
    assert np.mean(abs(result.accepted_hz[stable]-hz) < 25e6) >= .80


def test_pursuit_distinguishes_harmonic_from_independent_component() -> None:
    fs = 40e9
    t = np.arange(6144, dtype=np.float64)/fs
    y = np.random.default_rng(15).normal(0., .001, len(t))
    on = slice(2048, 5120)
    y[on] += (
        .12*np.cos(2*np.pi*1.12e9*t[on]+.3)
        + .07*np.cos(2*np.pi*1.81e9*t[on]-.5)
        + .06*np.cos(2*np.pi*2.24e9*t[on]+.7)
    )
    ch = Channel("synthetic_branch", t, y, fs)
    result = m2_mc_decomp(ch)
    central = (ch.q >= 2560) & (ch.q <= 4608)
    assert result.diagnostics["has_harmonic"][central].all()
    assert result.diagnostics["is_competing_multibranch"][central].all()
    np.testing.assert_allclose(result.accepted_hz[central], 1.12e9, atol=30e6, rtol=0.)
    np.testing.assert_allclose(result.diagnostics["secondary_hz"][central],
                               1.81e9, atol=30e6, rtol=0.)


def test_censoring_recovers_fundamental_and_reduces_harmonic_leakage() -> None:
    tau = offsets(1024)/40e9
    hz = np.array([[.83e9, 1.66e9, 2.49e9]])
    clean = 1.25*np.cos(chirp_phase(tau, float(hz[0, 0]), 0.)+.51)
    y = np.clip(clean, -.34, .59)
    mask = rail_mask(y)
    assert .20 < (~mask).mean() < .40
    rates = np.zeros_like(hz)
    split = np.array([-1], dtype=np.int64)
    ordinary, _ = joint_fit(y[None, :], tau, hz, rates, np.ones((1, len(y))), split)
    censored, _ = joint_fit(y[None, :], tau, hz, rates, (~mask)[None, :].astype(float), split)
    a, b = (np.hypot(x[0, :3], x[0, 3:]) for x in (ordinary, censored))
    assert abs(b[0]-1.25) < .01 < abs(a[0]-1.25)
    assert np.linalg.norm(b[1:]) < .01 * np.linalg.norm(a[1:])


@pytest.mark.parametrize("fs, counts", [
    (40e9, (256, 512, 1024, 1536)),
    (80e9, (512, 1024, 2048, 3072)),
])
def test_physical_windows(fs: float, counts: tuple[int, ...]) -> None:
    assert tuple(samples_for_ns(d, fs) for d in WINDOW_NS) == counts
    n = 8192
    t = np.arange(n)/fs
    hz = 1.45e9
    rate = -12e15
    ch = Channel("invariance", t, np.cos(chirp_phase(t, hz, rate)+.3), fs)
    center_hz = hz + rate*t[ch.q]
    raw = RawEvaluator(ch).evaluate(center_hz, np.full(len(ch.q), rate))
    assert np.nanmin(raw.raw_chirp_r2_64ns) > .999999
    assert np.nanmin(raw.raw_chirp_r2_256ns) > .999999
    assert np.nanmin(raw.split_half_coherence_256ns) > .999999
    assert np.isnan(raw.raw_chirp_r2_256ns[0])


def test_low_frequency_quadrature_and_reverse_pll() -> None:
    fs, hz, actual_phase = 80e9, .25e9, .78
    t = np.arange(4096)/fs
    y = .045*np.cos(2*np.pi*hz*t+actual_phase) + .4 + 1e6*t
    # This block contains less than one cycle, making a complex dot product biased.
    tau = t[:192]
    z, r2 = quadrature(y[:192], chirp_phase(tau, hz, 0.))
    assert float(r2) > .999999
    assert complex(z) == pytest.approx(.045*np.exp(1j*actual_phase), rel=1e-10)
    center = 2048
    exact = PhaseState(center, actual_phase+2*np.pi*hz*t[center], hz, 0.)
    demod = Demodulator(y, fs, np.empty(0, dtype=np.int64), .0005)
    for direction in (1, -1):
        state = exact
        for index in range(center+direction*64, center+direction*768, direction*64):
            update = demod.update(state, index)
            assert update is not None
            state = update
            assert state.hz == pytest.approx(hz, abs=10.)


@pytest.mark.parametrize("misses", [2, 3])
def test_demodulation_microstep_fade_limit(monkeypatch: pytest.MonkeyPatch, misses: int) -> None:
    fs, hz = 40e9, 1.0e9
    t = np.arange(4096)/fs
    noise = .001*np.random.default_rng(48).normal(size=len(t))
    y = noise + np.where(t >= 30e-9, .04*np.cos(chirp_phase(t, hz, 0.)), 0.)
    ch = Channel("demod_fade", t, y, fs)
    frame = 10
    start = int(ch.q[frame])
    missing = {start + 32*i for i in range(1, misses+1)}

    def update(demod: Demodulator, state: PhaseState, index: int) -> PhaseState | None:
        return None if index in missing else state.predict(index, demod.fs)

    monkeypatch.setattr(Demodulator, "update", update)
    anchor = Anchor(frame, hz, 0., 2*np.pi*hz*t[start], 1., 6.4)
    estimates, rates = np.full(len(ch.q), np.nan), np.full(len(ch.q), np.nan)
    integration, lost, predicted = np.zeros(len(ch.q)), np.zeros(len(ch.q), dtype=np.bool_), (
        np.zeros(len(ch.q), dtype=np.int64)
    )
    demod = Demodulator(ch.y, ch.fs, ch.quiet.steps.index, ch.quiet.noise_power_v2**.5, ch.quiet)
    _propagate(ch, RawEvaluator(ch), demod, anchor, estimates, rates, lost, integration, predicted, 1)
    if misses == 2:
        assert estimates[frame+1] == hz and predicted[frame+1] == 2
        assert not lost[frame+1]
    else:
        assert np.isnan(estimates[frame+1])
        assert lost[frame+1]


def test_kinematic_path_hard_off_and_jump() -> None:
    hz = np.array([[.8e9], [.8e9], [2.8e9], [2.8e9], [2.8e9]])
    score = np.full_like(hz, 5.)
    score[-1] = .2
    h = Hypotheses(hz, np.zeros_like(hz), score, np.ones_like(hz), np.full_like(hz, 6.4))
    time = np.arange(len(hz), dtype=np.float64)*3.2e-9
    path, jumps = kinematic_path(h, time, np.ones(len(hz), dtype=bool), 2.)
    np.testing.assert_array_equal(path, [0, 0, 0, 0, -1])
    np.testing.assert_array_equal(jumps, [False, False, True, False, False])


def test_real_channel_phase1_smoke() -> None:
    ch = load_channel("20201211m_ch1")
    np.testing.assert_array_equal(ch.q, np.arange(384, len(ch.y)-383, 128, dtype=np.int64))
    verify_baselines(ch, run_baselines(ch))
    for method in (m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod):
        started = perf_counter()
        result = method(ch)
        elapsed = perf_counter()-started
        assert elapsed < 20., f"{method.__name__} took {elapsed:.2f} s"
        np.testing.assert_array_equal(result.sample_index, ch.q)
        assert result.candidate_hz.shape == result.accepted_hz.shape == ch.q.shape
        assert result.raw.raw_chirp_r2_256ns.shape == ch.q.shape
        assert all(value.shape == ch.q.shape for value in result.diagnostics.values())
        valid = np.isfinite(result.accepted_hz)
        assert valid.any(), method.__name__
        assert np.all((result.accepted_hz[valid] >= 50e6) & (result.accepted_hz[valid] <= 6e9))
        np.testing.assert_array_equal(result.accepted_hz[valid], result.candidate_hz[valid])
        ramp = (ch.t[ch.q] >= 107.700e-6) & (ch.t[ch.q] < 107.7382e-6)
        assert not np.any(result.accepted_hz[ramp] < 250e6)
