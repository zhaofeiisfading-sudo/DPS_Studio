"""Physical acceptance and label-free regime checks for TASK-023 Phase 2."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from scripts.research.task023 import phase_coherent
from scripts.research.task023.coherent import Hypotheses, off_threshold
from scripts.research.task023.common import Channel, MatchedEvidence, RawEvaluator
from scripts.research.task023.phase_coherent import (
    BACKGROUND_HZ, _long_supported, _VerificationNoise, _verify, m4_phase_coherent,
)
from scripts.research.task023.pursuit import rail_mask
from scripts.research.task023.regime import Observables, Regime, segment
from scripts.research.task023.waveform import (
    Bool, Float, Int, Steps, chirp_phase, offsets, quadrature_stats, samples_for_ns,
)


def _receiver_noise(size: int, fs: float) -> Float:
    white = np.random.default_rng(413).normal(size=size)
    spectrum = np.fft.rfft(white)
    spectrum[np.fft.rfftfreq(size, 1/fs) > 8.5e9] = 0.
    noise = np.fft.irfft(spectrum)
    return np.asarray(noise / np.std(noise))


def _single_proposal(ch: Channel, hz: float, score: float = 12.) -> Hypotheses:
    shape = (len(ch.q), 1)
    return Hypotheses(np.full(shape, hz), np.zeros(shape), np.full(shape, score),
                      np.ones(shape), np.full(shape, 6.4))


def _matched_fixture(size: int, r2: float, snr_db: float = 18.) -> MatchedEvidence:
    full = np.full(size, snr_db)
    half = full - 4.
    return MatchedEvidence(np.ones(size, dtype=np.complex128), np.full(size, r2),
                           full, half, np.full(size, .90), half, half)


@pytest.mark.parametrize("power_db", [-11.3, -6.])
def test_m4_recovers_phase_coherent_weak_chirp(power_db: float) -> None:
    fs = 40e9
    t = np.arange(16384)/fs
    h0, rate = 1.9e9, 5e15
    tau = t - 95e-9
    u = np.clip(tau/12e-9, 0., 1.)
    amplitude = np.sqrt(2*10**(power_db/10))*(.5-.5*np.cos(np.pi*u))
    y = _receiver_noise(len(t), fs) + amplitude*np.cos(chirp_phase(tau, h0, rate)+.37)
    ch = Channel("weak-chirp", t, y, fs)
    f = h0 + rate*tau[ch.q]
    middle = (t[ch.q] >= 132e-9) & (t[ch.q] < 350e-9)
    raw = RawEvaluator(ch).evaluate(f, np.full(len(f), rate))
    matched = RawEvaluator(ch).matched(np.arange(len(f)), f, np.full(len(f), rate), 25.6)
    if power_db < -10:
        assert .06 < np.median(raw.raw_chirp_r2_256ns[middle]) < .08
        assert 11. <= np.median(matched.snr_db[middle]) <= 14.
    output = m4_phase_coherent(ch)
    recovered = abs(output.accepted_hz - f) < 45e6
    # The raised long-window gate deliberately trades sensitivity near its
    # boundary for broadband false-track rejection.
    assert np.mean(recovered[middle]) >= (.50 if power_db < -10. else .65)
    assert np.isnan(output.accepted_hz[t[ch.q] < 84e-9]).all()
    if power_db < -10:
        assert np.count_nonzero(recovered & middle & (output.raw.raw_chirp_r2_256ns < .10)) >= 25


@pytest.mark.parametrize("fs, seed", [(40e9, 17), (80e9, 71)])
def test_m4_gaussian_null_has_no_isolated_publications(fs: float, seed: int) -> None:
    t = np.arange(32768)/fs
    ch = Channel("gaussian-null", t, np.random.default_rng(seed).normal(size=len(t)), fs)
    output = m4_phase_coherent(ch)
    assert len(output.sample_index) > 240
    assert not np.isfinite(output.accepted_hz).any()


def test_moving_branch_stays_primary_while_cw_is_exposed() -> None:
    fs = 40e9
    t = np.arange(18432)/fs
    tau = t-210e-9
    hz, rate = .28e9, .65e15
    moving = .065*np.clip((t-65e-9)/12e-9, 0., 1.)*np.clip((306e-9-t)/12e-9, 0., 1.)
    cw = .087*np.clip((t-160e-9)/12e-9, 0., 1.)
    y = (.002*_receiver_noise(len(t), fs) + moving*np.cos(chirp_phase(tau, hz, rate)+.67)
         + cw*np.cos(chirp_phase(t, .51e9, 0.)+.12))
    ch = Channel("cw-and-chirp", t, y, fs)
    result = m4_phase_coherent(ch)
    time = t[ch.q]
    coexist = (time > 182e-9) & (time < 280e-9)
    expected = hz + rate*tau[ch.q]
    assert np.mean(abs(result.accepted_hz[coexist]-expected[coexist]) < 30e6) >= .90
    assert np.mean(abs(result.diagnostics["secondary_hz"][coexist]-.51e9) < 30e6) >= .90
    assert np.mean(result.diagnostics["competing_cw_present"][coexist]) >= .90
    late = (time > 325e-9) & (time < 430e-9)
    assert np.mean(abs(result.accepted_hz[late]-.51e9) < 30e6) >= .90
    assert np.mean(result.diagnostics["persistent_cw_overlap"][late]) >= .90


def test_clipped_fundamental_stays_primary_near_tail_cw() -> None:
    fs = 40e9
    t = np.arange(16384)/fs
    fundamental_hz, cw_hz = 550e6, 506e6
    burst = np.clip((t-70e-9)/12e-9, 0., 1.)*np.clip((270e-9-t)/12e-9, 0., 1.)
    tail = np.clip((t-205e-9)/12e-9, 0., 1.)
    y = np.clip(
        .001*np.random.default_rng(219).normal(size=len(t))
        + .22*burst*np.cos(chirp_phase(t, fundamental_hz, 0.)+.2)
        + .05*tail*np.cos(chirp_phase(t, cw_hz, 0.)+.7),
        -.083, .083,
    )
    assert np.mean(rail_mask(y)) > .30
    ch = Channel("clipped-fundamental-and-tail-cw", t, y, fs)
    result = m4_phase_coherent(ch)
    centers = t[ch.q]
    coexist = (centers > 222e-9) & (centers < 253e-9)
    late = (centers > 310e-9) & (centers < 390e-9)
    np.testing.assert_allclose(result.accepted_hz[coexist], fundamental_hz, atol=25e6, rtol=0.)
    np.testing.assert_allclose(result.accepted_hz[late], cw_hz, atol=10e6, rtol=0.)
    assert result.diagnostics["persistent_cw_overlap"][late].all()


@pytest.mark.parametrize("hz, passes", [(304e6, False), (1.12e9, True)])
def test_detected_step_requires_one_observed_post_step_cycle(hz: float, passes: bool) -> None:
    fs = 40e9
    t = np.arange(7168)/fs
    center = 3072
    step = center-1
    tau = t-t[step]
    noise = .0001*np.random.default_rng(17).normal(size=len(t))
    y = noise + np.where(tau >= 0., .9 + .012*np.cos(chirp_phase(tau, hz, 0.)+.37), 0.)
    ch = Channel("voltage-step", t, y, fs)
    assert abs(int(ch.quiet.steps.index[0])-step) <= 1
    row = np.flatnonzero(ch.q == center)
    h = _single_proposal(ch, hz)
    verify = _verify(ch, RawEvaluator(ch), h, row, np.array([0]), ch.quiet.steps,
                     np.zeros(len(t), dtype=np.bool_), _VerificationNoise(ch))
    assert verify.post_step_r2[0] >= .25 and verify.snr_full_db[0] >= 10.
    assert bool(verify.cycles[0] >= 1.) is passes
    assert bool(verify.valid[0]) is passes
    if passes:
        result = m4_phase_coherent(ch)
        assert np.isnan(result.accepted_hz[ch.q < step]).all()
        assert result.accepted_hz[row].item() == pytest.approx(hz, abs=60e6)


def test_island_does_not_block_verified_neighbors_from_filling_its_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs = 40e9
    t = np.arange(16384)/fs
    hz, stray = 1.4e9, 2.6e9
    amplitude = np.clip((t - 95e-9)/14e-9, 0., 1.)
    y = .02*_receiver_noise(len(t), fs) + amplitude*(
        np.cos(chirp_phase(t, hz, 0.)) + .32*np.cos(chirp_phase(t, stray, 0.)))
    ch = Channel("single-frame-island", t, y, fs)
    h = _single_proposal(ch, hz)
    gap = len(ch.q)//2
    h.hz[gap, 0] = stray

    def propose(*_args: object) -> tuple[Hypotheses, Bool]:
        return h, np.zeros_like(h.hz, dtype=np.bool_)

    monkeypatch.setattr(phase_coherent, "_propose", propose)
    output = m4_phase_coherent(ch)
    np.testing.assert_allclose(output.accepted_hz[gap-1:gap+2], hz, atol=10e6, rtol=0.)
    assert not output.diagnostics["island_removed"][gap]


@pytest.mark.parametrize("dc_edge", [False, True])
def test_verified_38ns_r2_can_rescue_a_subthreshold_25ns_fit(
    monkeypatch: pytest.MonkeyPatch, dc_edge: bool,
) -> None:
    fs = 40e9
    t = np.arange(8192)/fs
    row = np.array([len(t)//256-3])
    ch = Channel("long-retry", t, _receiver_noise(len(t), fs), fs)
    if dc_edge:
        steps = Steps(ch.q[row]+700, np.ones(1))
        monkeypatch.setitem(ch.__dict__, "quiet", replace(ch.quiet, steps=steps))

    def matched(
        _self: RawEvaluator, frames: Int, _hz: Float, _rate: Float, duration_ns: float,
        **_kwargs: object,
    ) -> MatchedEvidence:
        r2 = {6.4: .05, 25.6: .039, 38.4: 0. if dc_edge else .08}
        return _matched_fixture(len(frames), r2[duration_ns])

    def raw_r2(_ch: Channel, frames: Int, _hz: Float, _rate: Float, duration: float) -> Float:
        assert dc_edge and duration == 38.4
        return np.full(len(frames), .08)

    monkeypatch.setattr(RawEvaluator, "matched", matched)
    monkeypatch.setattr(phase_coherent, "_raw_r2", raw_r2)
    h = _single_proposal(ch, 1.4e9, score=off_threshold())
    fit = _verify(ch, RawEvaluator(ch), h, row, np.array([0]), ch.quiet.steps,
                  np.zeros(len(t), dtype=np.bool_), _VerificationNoise(ch))
    assert fit.valid.item()
    assert fit.duration_ns.item() == 38.4


def test_local_noise_bed_uses_guarded_quadratic_power_and_penalizes_both_snr_gates() -> None:
    fs = 40e9
    t = np.arange(32768)/fs
    hz = np.array([1.4e9, 2.15e9])
    late = t >= 400e-9
    gaussian = np.random.default_rng(314).normal(size=len(t))
    y = np.where(late, 2.2*gaussian + 8.*np.cos(chirp_phase(t, hz[0], 0.)), gaussian)
    ch = Channel("raised-background", t, y, fs)
    row = np.array([180, 180])
    noise = _VerificationNoise(ch)
    duration = 25.6
    sample = offsets(samples_for_ns(duration, fs))
    phase = chirp_phase(sample/fs, BACKGROUND_HZ[:, None], 0.)
    _, _, power = quadrature_stats(y[ch.q[row[0]] + sample], phase, degree=2)
    guard = abs(BACKGROUND_HZ - hz[:, None]) >= 250e6
    normalized = power/noise.quiet_floor(BACKGROUND_HZ)
    expected = np.array([np.quantile(normalized[keep], .35) for keep in guard])
    loss = noise.background_loss(row, hz, duration)
    np.testing.assert_allclose(loss, 10*np.log10(np.maximum(1., expected/(-2*np.log(.65)))))
    assert 4. < loss[0] < 10.
    assert not _long_supported(_matched_fixture(1, .06, 13.), np.array([.06]), np.array([10.]),
                               np.array([True]), loss[:1]).item()
    half_fails = replace(_matched_fixture(1, .06, 22.), half_snr_db=np.array([5.5]))
    assert not _long_supported(half_fails, np.array([.06]), np.array([10.]),
                               np.array([True]), loss[:1]).item()


def test_empirical_quiet_floor_detects_noise_below_short_window_resolution() -> None:
    fs = 40e9
    t = np.arange(32768)/fs
    y = _receiver_noise(len(t), fs) + .25*np.cos(chirp_phase(t, 105e6, 0.))
    ch = Channel("low-frequency-quiet-floor", t, y, fs)
    loss = _VerificationNoise(ch).low_frequency_loss(np.array([105e6, 300e6]))
    assert loss[0] > 5.
    assert loss[1] == 0.


@pytest.mark.parametrize("hz, long_r2, passes", [
    (100e6, .13, False), (100e6, .25, True), (180e6, .13, True),
])
def test_unanchored_low_frequency_requires_higher_sustained_r2(
    monkeypatch: pytest.MonkeyPatch, hz: float, long_r2: float, passes: bool,
) -> None:
    fs = 40e9
    t = np.arange(8192)/fs
    ch = Channel("low-frequency-anchor", t, _receiver_noise(len(t), fs), fs)

    def matched(
        _self: RawEvaluator, frames: Int, _hz: Float, _rate: Float, duration_ns: float,
        **_kwargs: object,
    ) -> MatchedEvidence:
        return _matched_fixture(len(frames), .30 if duration_ns == 6.4 else long_r2)

    monkeypatch.setattr(RawEvaluator, "matched", matched)
    fit = _verify(ch, RawEvaluator(ch), _single_proposal(ch, hz), np.array([25]), np.array([0]),
                  ch.quiet.steps, np.zeros(len(t), dtype=np.bool_), _VerificationNoise(ch))
    assert fit.valid.item() is passes


def test_unsupervised_regimes_read_only_observables() -> None:
    states = (Regime.STEADY_RIDGE, Regime.CHIRPING_RIDGE, Regime.WEAK_COHERENT_TAIL,
              Regime.PERSISTENT_CW_TAIL, Regime.NOISE_OR_QUIET)
    repeat = 24
    size = len(states)*repeat
    repeat_values = np.repeat
    obs = Observables(
        np.zeros(size, dtype=np.bool_), repeat_values([4., 4., 1.1, 2., 1.], repeat),
        repeat_values([8., 7., 3.4, 7., 2.], repeat),
        repeat_values([.92, .90, .82, .96, .1], repeat),
        repeat_values([6.4, 12.8, 25.6, 38.4, np.nan], repeat),
        repeat_values([.55, .34, .12, .20, .02], repeat),
        repeat_values([0., 12e15, 7e15, 0., 0.], repeat),
        np.zeros(size, dtype=np.bool_), repeat_values([False, False, False, True, False], repeat),
        np.zeros(size, dtype=np.bool_), repeat_values([True, True, True, True, False], repeat),
    )
    result = segment(obs)
    np.testing.assert_array_equal(result.index, repeat_values(states, repeat))
    assert result.diagnostic_window_ns[2*repeat] == 25.6
    assert result.diagnostic_window_ns[3*repeat] == 38.4


def test_short_support_overrides_rms_split_for_steady_and_chirping_ridges() -> None:
    size = 40
    obs = Observables(
        dc_step=np.zeros(size, dtype=np.bool_),
        local_rms_ratio=np.repeat([1.2, 20.], size//2),
        m4_score=np.full(size, 6.),
        split_half_coherence=np.full(size, .90),
        verification_window_ns=np.repeat([12.8, 25.6, 38.4, 6.4], size//4),
        short_r2=np.repeat([.18, .25, .10, .40], size//4),
        abs_chirp_rate=np.repeat([0., 12e15, 0., 12e15], size//4),
        rail_clipped=np.zeros(size, dtype=np.bool_),
        persistent_cw_overlap=np.zeros(size, dtype=np.bool_),
        multi_branch=np.zeros(size, dtype=np.bool_),
        tracked=np.ones(size, dtype=np.bool_),
    )
    segmented = segment(obs)
    assert segmented.rms_split_ratio > 4.
    np.testing.assert_array_equal(segmented.index[:size//2], np.repeat(
        [Regime.STEADY_RIDGE, Regime.CHIRPING_RIDGE], size//4,
    ))
