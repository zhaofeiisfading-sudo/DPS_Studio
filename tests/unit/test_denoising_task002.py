"""Independent voltage/truth, grouped sampling and harm-accounting invariants."""
from __future__ import annotations

from inspect import signature

import numpy as np
import pytest

from dps_studio.core.analysis_profiles import BALANCED_PROFILE
from dps_studio.research import denoising_task001 as method
from dps_studio.research import denoising_task002 as bench
from dps_studio.research.task028_consolidation import frontend


@pytest.mark.parametrize("family", bench.FAMILIES)
def test_time_voltage_generation_reproducible_finite_si_and_split_separated(family: str) -> None:
    a = bench.generate(family, 0, "DEVELOPMENT")
    b = bench.generate(family, 0, "DEVELOPMENT")
    held = bench.generate(family, 0, "HELD_OUT")
    np.testing.assert_array_equal(a.record.voltage_v, b.record.voltage_v)
    assert not np.array_equal(a.record.voltage_v, held.record.voltage_v)
    assert a.seed != held.seed
    assert a.record.sample_rate_hz == pytest.approx(40e9)
    assert a.record.time_s[-1] < 800e-9
    assert np.isfinite(a.record.voltage_v).all()
    assert np.array_equal(np.isfinite(a.truth_hz), a.target_present)
    if np.any(a.target_present):
        assert np.nanmin(a.truth_hz) > .05e9
        assert np.nanmax(a.truth_hz) < 6e9
    assert a.parameters["speckle_statistics_validated"] is False


def test_registration_unique_waveform_groups_without_profile_pseudoreplication() -> None:
    rows = bench.registration()
    assert len(rows) == len({r["case_id"] for r in rows}) == len({r["seed"] for r in rows}) == 280
    assert sum(r["split"] == "HELD_OUT" for r in rows) == 160
    assert all("profile" not in row for row in rows)
    for row in rows:
        assert bench.generate(row["family"], row["instance"], row["split"]).seed == row["seed"]


@pytest.mark.parametrize("family,instance,split", [("unknown", 0, "HELD_OUT"),
                                                   ("normal_platform", 8, "HELD_OUT"),
                                                   ("normal_platform", 0, "TRAIN")])
def test_unregistered_generation_rejected(family: str, instance: int, split: str) -> None:
    with pytest.raises(ValueError, match="Unregistered"):
        bench.generate(family, instance, split)


def test_fast_support_truth_labels_include_window_mixing_and_exclude_it_from_normal() -> None:
    case = bench.generate("normal_fast_step", 0, "DEVELOPMENT")
    stft, _ = frontend(case.record, BALANCED_PROFILE)
    labels = bench.frame_labels(case, stft.time_s, stft.window_length_samples)
    centers = np.rint(stft.time_s*bench.FS_HZ).astype(int)
    assert labels["fast"].sum() > case.fast[centers].sum()
    assert not np.any(labels["normal"] & labels["fast"])
    assert len(labels["truth"]) == len(stft.time_s)
    np.testing.assert_array_equal(labels["truth"], case.truth_hz[centers])


def test_metrics_report_inherited_harm_and_absolute_fast_accuracy_separately() -> None:
    truth = np.full(4, 2e9)
    labels = dict(truth=truth, normal=np.array([True, False, False, False]),
                  fast=np.array([False, True, True, False]), focus=np.ones(4, dtype=bool))
    strongest = np.array([2e9, 2e9, 3e9, 2e9])
    p3 = np.array([2e9, 3e9, 3e9, 2e9])
    repaired = np.array([2e9, 3e9, 2e9, 3e9])
    relative_p3 = bench.metrics(repaired, p3, labels)
    relative_m0 = bench.metrics(repaired, strongest, labels)
    assert relative_p3["corrected_frames"] == relative_p3["harmed_frames"] == 1
    assert relative_m0["harmed_frames"] == 2
    assert bench.ratios(relative_p3)["fast_truth_accuracy"] == .5
    assert bench.ratios(relative_p3)["fast_preservation"] is None
    assert bench.ratios(relative_m0)["fast_preservation"] == 0


def test_nan_cannot_earn_coverage_or_be_scored_as_correct() -> None:
    labels = dict(truth=np.array([1e9, 2e9, np.nan]), normal=np.array([True, False, False]),
                  fast=np.array([False, True, False]), focus=np.ones(3, dtype=bool))
    result = bench.metrics(np.array([np.nan, 2e9, 4e9]), np.array([1e9, 3e9, 4e9]), labels)
    assert result["harmed_frames"] == result["corrected_frames"] == result["wrong_frames"] == 1
    assert result["truth_frames"] == 2
    assert bench.ratios(result)["coverage"] == pytest.approx(2/3)


def test_observational_diagnostics_do_not_modify_candidates_or_accept_truth() -> None:
    case = bench.generate("normal_platform", 0, "DEVELOPMENT")
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    baseline = np.array([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    original = baseline.copy()
    flags = bench.observational_flags(peaks, baseline, baseline)
    assert len(flags) == len(stft.time_s)
    assert all("P3_DISAGREES_STRONGEST" not in f for f in flags)
    assert "truth" not in str(signature(bench.observational_flags))
    np.testing.assert_array_equal(baseline, original)


def test_original_candidates_and_explicit_truth_audit_do_not_affect_estimator() -> None:
    case = bench.generate("wrong_burst", 0, "DEVELOPMENT")
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    m0 = np.array([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    proposals = method.propose_repairs(stft, peaks, m0)
    output, _ = method.apply_repairs(peaks, m0, proposals)
    assert proposals
    labels = bench.frame_labels(case, stft.time_s, stft.window_length_samples)
    for proposal in proposals:
        audit = bench.proposal_truth_audit(proposal, peaks, labels,
            int(np.ceil(stft.window_length_samples/stft.hop_samples)), m0)
        assert len(audit["anchors"]) == 8
        assert audit["anchor_identity_observable"] is False
        for i, j in zip(proposal.frame_indices, proposal.candidate_indices, strict=True):
            assert output[i] == peaks.candidates_by_frame[i][j].transition_frequency_hz
    repeated, _ = method.apply_repairs(peaks, m0, proposals)
    np.testing.assert_array_equal(output, repeated)
