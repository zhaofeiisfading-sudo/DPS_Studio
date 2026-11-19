"""TASK-024 regression checks. Fixture signals are used only to check behavior."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from scripts.research.task023 import phase_coherent as native
from scripts.research.task023.coherent import Hypotheses, off_threshold
from scripts.research.task023.common import Channel, Estimate, MatchedEvidence, RawEvaluator
from scripts.research.task023.common import RawEvidence
from scripts.research.task023.common import load_channel, run_baselines
from scripts.research.task023.pursuit import rail_mask
from scripts.research.task023.waveform import Bool, Float, Int, Steps
from scripts.research.task024.ablations import (
    FULL, NO_CFAR, NO_CHIRP, NO_CW, NO_LOW, NO_PATH, NO_STEP, _NoCfar, _NoLowFloor,
    _greedy, _tone_gaps, _verify_without_low_gate, _without_cw, assert_exact, run_variant,
)
from scripts.research.task024.controls import B1, BS, MATCHED, estimate, strategy, verify_task020
from scripts.research.task024.replay import verify_phase3
from scripts.research.task024.taxonomy import CATEGORIES, classify


@pytest.fixture(scope="module")
def real() -> Channel:
    return load_channel("20201210m_ch1")


def test_frozen_m4_exact(real: Channel) -> None:
    expected = native.m4_phase_coherent(real)
    full = run_variant(real, FULL)
    assert_exact(full.estimate, expected)
    assert set(full.seconds) >= {"quiet_model", "_select_initial", "RawEvaluator.evaluate"}
    assert full.seconds["cold_total"] >= full.seconds["_propose_total"]


def test_frozen_b1_exact(real: Channel) -> None:
    clean = replace(real, segments=())
    frozen = run_baselines(real)
    b1 = estimate(clean, RawEvaluator(clean), B1)
    bs = replace(b1, accepted_hz=np.where(b1.raw.S_256, b1.candidate_hz, np.nan))
    for name, actual in ((B1, b1), (BS, bs)):
        assert_exact(replace(actual, diagnostics={}), frozen[name])
    assert verify_task020(clean, {B1: b1, BS: bs}) == len(clean.q)
    full = native.m4_phase_coherent(clean)
    assert verify_phase3(clean, {B1: b1, BS: bs, FULL: full}) == len(clean.q)


@pytest.mark.parametrize("fs", [40e9, 80e9])
def test_duration_matched_stft(fs: float) -> None:
    assert strategy(B1, fs).width/fs == 512/fs
    for name, (duration, degree, minimum) in MATCHED.items():
        spec = strategy(name, fs)
        assert spec.width/fs == pytest.approx(duration*1e-9, rel=1e-15)
        assert spec.degree == degree
        assert spec.hop == 128 and spec.boundary == "full"
        assert spec.nfft == max(minimum, 1 << (2*spec.width-1).bit_length())


def _fixture() -> Channel:
    fs = 40e9
    t = np.arange(6144)/fs
    shift = t-30e-9
    rng = np.random.default_rng(24)
    signal = .025*np.cos(2*np.pi*(.6e9*shift+.5*1e16*shift**2))
    voltage = .0005*rng.standard_normal(len(t)) + np.where(shift >= 0, .06+signal, 0)
    voltage = np.minimum(voltage, .071)
    t.flags.writeable = voltage.flags.writeable = False
    return Channel("behavior_fixture", t, voltage, fs)


def test_ablation_entrypoints_preserve_original_signal() -> None:
    ch = _fixture()
    t, y = ch.t.copy(), ch.y.copy()
    full = run_variant(ch, FULL)
    bank, cross = full.initial_bank
    frozen_bank = {key: getattr(bank, key).copy()
                   for key in ("hz", "rate", "score", "rho", "scale_ns")}
    frozen_cross = cross.copy()
    assert ch.quiet.steps.index.size and rail_mask(ch.y).any()
    assert (full.estimate.diagnostics["detected_dc_step"]).any()
    assert (full.estimate.diagnostics["rail_clipped"]).any()

    tone = run_variant(ch, NO_CHIRP)
    for rates in (tone.initial_bank[0].rate, tone.estimate.chirp_hz_s):
        assert np.isfinite(rates).any()
        assert np.all(rates[np.isfinite(rates)] == 0.)
    edge = run_variant(ch, NO_STEP).estimate
    for key in ("detected_dc_step", "rail_entry_edge", "rail_clipped", "near_support_edge"):
        assert not edge.diagnostics[key].any()
    for name in (NO_CFAR, NO_LOW, NO_CW, NO_PATH):
        trial = run_variant(ch, name, full.initial_bank)
        assert trial.initial_bank is full.initial_bank
        assert "_propose_total" not in trial.seconds
        if name == NO_PATH:
            assert not trial.estimate.diagnostics["path_jump"].any()
            np.testing.assert_array_equal(
                np.isfinite(trial.estimate.accepted_hz),
                trial.estimate.diagnostics["verified_hypothesis_count"] > 0,
            )
            assert not trial.estimate.diagnostics["island_removed"].any()
    np.testing.assert_array_equal(t, ch.t)
    np.testing.assert_array_equal(y, ch.y)
    for key, value in frozen_bank.items():
        np.testing.assert_array_equal(value, getattr(bank, key))
    np.testing.assert_array_equal(frozen_cross, cross)
    assert_exact(run_variant(ch, FULL).estimate, full.estimate)


def test_cfar_and_low_frequency_interventions() -> None:
    ch = _fixture()
    hz = np.array([.11e9, .9e9])
    frames = np.array([18, 19], dtype=np.int64)
    native_noise = native._VerificationNoise(ch)
    assert (native_noise.background_loss(frames, hz, 25.6) > 0.).any()
    cfar = _NoCfar(ch)
    np.testing.assert_array_equal(cfar.background_loss(frames, hz, 25.6), 0.)
    np.testing.assert_array_equal(cfar.low_frequency_loss(hz), native_noise.low_frequency_loss(hz))
    low = _NoLowFloor(ch)
    np.testing.assert_array_equal(low.low_frequency_loss(hz), 0.)
    np.testing.assert_array_equal(low.background_loss(frames, hz, 25.6),
                                  native_noise.background_loss(frames, hz, 25.6))
    # Inject equal short and long matches, with a 38.4 ns amplitude inconsistency
    # that only the sustained low-frequency veto can reject.
    empty_steps = Steps(np.empty(0, dtype=np.int64), np.empty(0))
    quiet = replace(ch.quiet, steps=empty_steps)
    ch.__dict__["quiet"] = quiet
    frames = frames[:1]
    hz = np.full((len(ch.q), 1), .12e9)
    scores = np.full_like(hz, 5.)
    bank = Hypotheses(hz, np.zeros_like(hz), scores, scores, scores)

    class ControlledMatch(RawEvaluator):
        def matched(
            self, frames: Int, hz: Float, rate: Float, duration_ns: float, *,
            steps: Steps | None = None, usable_samples: Bool | None = None,
        ) -> MatchedEvidence:
            size = len(frames)
            phasor = np.full(size, 1. if duration_ns < 38. else .1, dtype=np.complex128)
            value = np.full(size, 20.)
            return MatchedEvidence(phasor, np.full(size, .8), value, value,
                                   np.full(size, .9), value, value)

    ev = ControlledMatch(ch)
    cols = np.zeros_like(frames)
    rail = np.zeros(len(ch.y), dtype=np.bool_)
    noise = _NoLowFloor(ch)
    assert not native._verify(ch, ev, bank, frames, cols, empty_steps, rail, noise).valid[0]
    assert _verify_without_low_gate()(ch, ev, bank, frames, cols, empty_steps, rail, noise).valid[0]


def test_zero_rate_gap_nomination() -> None:
    ch = _fixture()
    hz = np.full((len(ch.q), 1), .8e9)
    bank = Hypotheses(hz, np.zeros_like(hz), np.full_like(hz, 5.), hz, hz)
    path = np.zeros(len(ch.q), dtype=np.int64)
    path[10:12] = -1
    near = np.zeros(len(path), dtype=np.bool_)
    tone = _tone_gaps(ch, bank, path, near)
    np.testing.assert_array_equal(tone.rate[np.isfinite(tone.score)], 0.)
    assert tone.hz.shape[1] == 6
    assert len(np.unique(tone.hz[10, np.isfinite(tone.score[10])])) == 3


def test_cw_switch_and_greedy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _fixture()
    hz = np.tile([.5e9, .9e9], (len(ch.q), 1))
    score = np.tile([6., 5.], (len(ch.q), 1))
    valid = np.ones_like(hz, dtype=np.bool_)
    valid[5, 0] = False
    valid[6] = False
    h = Hypotheses(hz, np.zeros_like(hz), score, score, score)
    path, jumps, cw = _greedy(ch, h, valid)
    np.testing.assert_array_equal(path[[4, 5, 6]], [0, 1, -1])
    assert not jumps.any() and cw.any()

    def capture(
        bank: Hypotheses, times: Float, enabled: Bool, cut: float, *,
        entry_penalty: float, persistent_cw: Bool | None, jump_cost: float,
    ) -> tuple[Int, Bool]:
        assert persistent_cw is None
        assert cut == off_threshold() and jump_cost == 3. and entry_penalty == .95
        np.testing.assert_array_equal(bank.score, np.where(valid, score, -np.inf))
        return path, jumps

    monkeypatch.setattr("scripts.research.task023.coherent.kinematic_path", capture)
    path_without, _, observed_cw = _without_cw(ch, h, valid)
    np.testing.assert_array_equal(path_without, path)
    np.testing.assert_array_equal(observed_cw, cw)


def test_taxonomy_exhaustive_at_exact_boundaries() -> None:
    n = len(CATEGORIES)
    q = np.arange(n, dtype=np.int64)
    b1_hz = np.array([500., 500., 500., np.nan, np.nan, np.nan, 500., 500., np.nan])*1e6
    full_hz = np.array([550., 750., 751., 500., 500., 500., np.nan, np.nan, np.nan])*1e6
    z = np.zeros(n)
    raw = RawEvidence(z, z, z.astype(np.bool_), z, z.copy(), z.copy(), z.copy(),
                      np.full(n, 5.))
    b1_raw = replace(raw, raw_chirp_r2_64ns=np.array([0., 0., 0., 0., 0., 0., .149, .15, 0.]))
    full_raw = replace(raw, raw_chirp_r2_64ns=np.array([0., 0., 0., .15, 0., .9, 0., 0., 0.]),
                       raw_chirp_r2_256ns=np.array([0., 0., 0., 0., .04, .8, 0., 0., 0.]),
                       split_half_coherence_256ns=np.array([0., 0., 0., 0., .58, .9, 0., 0., 0.]))
    cw = np.zeros(n, dtype=np.bool_)
    cw[5] = True
    b1 = Estimate(q, b1_hz, b1_hz, z, b1_raw, {})
    full = Estimate(q, full_hz, full_hz, z, full_raw, {"persistent_cw_overlap": cw})
    actual = classify(b1, full)
    np.testing.assert_array_equal(actual.category, CATEGORIES)
    assert sum(np.count_nonzero(actual.category == category) for category in CATEGORIES) == n
