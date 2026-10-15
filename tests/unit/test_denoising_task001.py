"""Physical-chain, provenance and grouped-learning invariants for TASK-001."""
from __future__ import annotations

from dataclasses import replace
from inspect import signature

import numpy as np
import pytest

from dps_studio.core.analysis_profiles import BALANCED_PROFILE
from dps_studio.core.models import SignalRecord
from dps_studio.research import denoising_task001 as method
from dps_studio.research import denoising_task001_benchmark as bench
from dps_studio.research.task023e_waveform_benchmark import oscillator_phase
from dps_studio.research.task028_consolidation import frontend


@pytest.mark.parametrize("family", (*bench.FAMILIES, *bench.EXTRA_FAMILIES))
def test_fresh_voltage_reproducible_split_and_si(family: str) -> None:
    a = bench.generate(family, 0, "TRAIN")
    b = bench.generate(family, 0, "TRAIN")
    other = bench.generate(family, 0, "HELD_OUT")
    np.testing.assert_array_equal(a.record.voltage_v, b.record.voltage_v)
    assert a.seed != other.seed
    assert not np.array_equal(a.record.voltage_v, other.record.voltage_v)
    assert a.record.sample_rate_hz == pytest.approx(40e9)
    assert a.record.time_s[-1] < 1e-6
    assert np.array_equal(np.isfinite(a.truth_hz), a.target_present)


@pytest.mark.parametrize("family", ("pure_noise", "normal", "coherent_nontarget"))
def test_quality_separate_from_hypothesis_and_voltage(family: str) -> None:
    case = bench.generate(family, 0, "TRAIN")
    original = case.record.voltage_v.copy()
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    evidence = method.spectral_evidence(stft, peaks)
    assert evidence.signal_supported.shape == stft.time_s.shape
    assert np.isnan(evidence.validated_frequency_hz).all()
    assert all("VALID" not in state for state in evidence.states)
    if family == "pure_noise":
        assert np.mean(evidence.signal_supported) < .03
    else:
        assert np.mean(evidence.signal_supported) > .99
    np.testing.assert_array_equal(original, case.record.voltage_v)


def _excursion() -> tuple[SignalRecord, np.ndarray]:
    t = np.arange(32000) / 40e9
    f = np.full(len(t), 2.8e9)
    f[(t >= 300e-9) & (t < 410e-9)] = 1.6e9
    voltage = np.cos(oscillator_phase(f)) + .35 * np.cos(2 * np.pi * 2.8e9 * t + 1.)
    return SignalRecord(t, voltage), f


def test_amplitude_veto_falsifies_false_bridge_without_changing_normal() -> None:
    record, _ = _excursion()
    stft, peaks = frontend(record, BALANCED_PROFILE)
    baseline = np.asarray([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    strict = method.propose_repairs(stft, peaks, baseline)
    loose = method.propose_repairs(stft, peaks, baseline, replace(method.RepairConfig(),
        minimum_anchor_amplitude_ratio=.05, maximum_anchor_amplitude_ratio=20.))
    assert not strict
    assert loose
    unchanged, _ = method.apply_repairs(peaks, baseline, strict)
    changed, audit = method.apply_repairs(peaks, baseline, loose)
    np.testing.assert_array_equal(unchanged, baseline)
    assert np.sum(changed != baseline) > 5
    for row in audit:
        c = peaks.candidates_by_frame[row["frame"]][row["candidate_rank"] - 1]
        assert row["proposed_hz"] == c.transition_frequency_hz


def test_guard_can_repair_known_spurious_competitor_on_real_processing_chain() -> None:
    case = bench.generate("jump", 0, "TRAIN")
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    baseline = np.asarray([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    proposals = method.propose_repairs(stft, peaks, baseline)
    output, audit = method.apply_repairs(peaks, baseline, proposals)
    labels = bench.frame_labels(case, stft.time_s, stft.window_length_samples)
    assert len(proposals) > 0
    metrics = bench.evaluate(output, baseline, labels, np.ones(len(output), dtype=bool))
    assert metrics["corrected_frames"] >= 5
    assert metrics["harmed_frames"] == 0
    assert np.isfinite(output).all()
    assert audit
    for proposal in proposals:
        for i, j, predicted, features in zip(proposal.frame_indices, proposal.candidate_indices,
                                             proposal.prediction_hz, proposal.features, strict=True):
            np.testing.assert_array_equal(features, method.candidate_features(peaks, int(i), int(j),
                float(predicted), proposal.reference_amplitude_v, proposal.side_disagreement_hz,
                proposal.anchor_residual_hz))
    np.testing.assert_array_equal(peaks.time_s, stft.time_s)


def test_estimator_does_not_accept_truth_or_silently_fill_nan() -> None:
    assert "truth" not in str(signature(method.propose_repairs))
    case = bench.generate("normal", 0, "TRAIN")
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    with pytest.raises(ValueError, match="finite baseline"):
        method.propose_repairs(stft, peaks, np.full(len(stft.time_s), np.nan))


def test_local_floor_reports_signal_without_modifying_spectrum() -> None:
    case = bench.generate("normal", 0, "TRAIN")
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    old = stft.spectrum.copy()
    result = method.spectral_evidence(stft, peaks,
        method.EvidenceConfig(alpha=.001, background_half_width_hz=.6e9))
    assert result.signal_supported.mean() > .99
    np.testing.assert_array_equal(stft.spectrum, old)
    with pytest.raises(ValueError, match="half-width"):
        method.EvidenceConfig(background_half_width_hz=-1.)


def test_model_training_requires_independent_train_split_and_round_trip() -> None:
    rng = np.random.default_rng(0)
    features = rng.normal(size=(80, len(method.FEATURE_NAMES)))
    labels = features[:, 0] > 0
    weights = np.ones(80)
    with pytest.raises(ValueError, match="TRAIN only"):
        method.fit_logistic(features, labels, weights, split="HELD_OUT")
    model, history = method.fit_logistic(features, labels, weights, split="TRAIN")
    assert history[-1] < history[0]
    assert np.mean((model.predict(features) > .5) == labels) > .9
    copy = method.LogisticModel.from_dict(model.to_dict())
    np.testing.assert_array_equal(model.predict(features), copy.predict(features))
    snapshots = []
    replay, replay_history = method.fit_logistic(features, labels, weights, split="TRAIN",
                                                iteration_callback=snapshots.append)
    np.testing.assert_array_equal(model.coefficients, replay.coefficients)
    assert history == replay_history
    assert len(snapshots) == len(history)


def test_additional_negative_control_preserves_registered_seed_offsets() -> None:
    case = bench.generate("core_separated_edges", 0, "TRAIN")
    assert case.seed == 41010000 + 1400
    extra = bench.generate("box_return", 0, "HELD_OUT")
    assert extra.seed == 41040000 + 2200
    assert np.all(np.isfinite(extra.truth_hz))
    assert extra.fast.sum() > 0


def test_metrics_do_not_reward_nan_output_or_mask_weak_truth() -> None:
    truth = np.array([1e9, 2e9, np.nan])
    labels = {"truth": truth, "present": np.isfinite(truth),
              "normal": np.array([True, False, False]), "fast": np.array([False, True, False]),
              "focus": np.ones(3, dtype=bool), "homogeneous": np.ones(3, dtype=bool),
              "fully_absent": np.array([False, False, True]),
              "weak": np.array([False, True, False])}
    reference = np.array([1e9, 3e9, 4e9])
    counts = bench.evaluate(np.array([np.nan, 2e9, 4e9]), reference, labels,
                            np.array([True, False, True]))
    assert counts["corrected_frames"] == counts["harmed_frames"] == 1
    assert counts["wrong_frames"] == 1
    assert counts["weak_rejected"] == counts["false_supported"] == 1
    assert bench.ratios(counts)["coverage"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("config", [dict(jump_hz=-1), dict(anchors_per_side=1),
                                    dict(minimum_bridge_fraction=0)])
def test_invalid_repair_configuration_rejected(config: dict) -> None:
    with pytest.raises(ValueError):
        method.RepairConfig(**config)
