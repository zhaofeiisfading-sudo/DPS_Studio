"""Tests for TASK-023D smooth wrong-branch discrimination."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidate, RidgeCandidateSet
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.time_frequency import STFTResult
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import (
    EdgeRescueConfig,
    TrustedCore,
    TrustedCoreConfig,
)
from dps_studio.research.task023d_smooth_branch_rescue import (
    BranchAmbiguityConfig,
    BranchAmbiguityDiagnostics,
    BranchCompetitionConfig,
    BranchDecisionStatus,
    CoreTrimConfig,
    SmoothBranchMethod,
    SmoothBranchOptimizationResult,
    branch_ambiguity_diagnostics,
    optimize_smooth_wrong_branches,
    refine_trusted_core_boundaries,
)


def _candidate(
    frame: int,
    time_s: float,
    rank: int,
    frequency_hz: float,
    *,
    amplitude: float | None = None,
    background_db: float = 22.0,
) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame,
        time_s=time_s,
        candidate_rank=rank,
        discrete_bin_index=rank + 5,
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=frequency_hz,
        peak_amplitude=(24.0 if rank == 1 else 13.0) if amplitude is None else amplitude,
        peak_to_background_db=background_db,
        peak_to_competitor_db=7.0 if rank == 1 else -5.0,
        cycles_in_window=4.0,
        is_band_boundary=False,
        refinement_status=RidgeRefinementStatus.REFINED,
    )


def _candidate_set(
    *,
    leading: int = 0,
    trailing: int = 0,
    smooth_wrong: bool = False,
    fast_descent: bool = False,
    count: int = 80,
) -> tuple[RidgeCandidateSet, NDArray[np.float64]]:
    time_s = np.arange(count, dtype=np.float64) * 2.5e-9
    truth = np.full(count, 2.4e9, dtype=np.float64)
    if fast_descent:
        truth[45:] = 3.8e9 - np.arange(count - 45) * 80.0e6
        truth[:45] = 3.8e9
    rng = np.random.default_rng(23004 + leading + 3 * trailing)
    frames: list[tuple[RidgeCandidate, ...]] = []
    for frame in range(count):
        false = frame < leading or frame >= count - trailing
        if false:
            if smooth_wrong:
                wrong = (
                    4.7e9 - frame * 8.0e6
                    if frame < leading
                    else 4.1e9 + (frame - (count - trailing)) * 8.0e6
                )
            else:
                wrong = float(rng.uniform(0.55e9, 5.8e9))
            frames.append(
                (
                    _candidate(frame, float(time_s[frame]), 1, wrong),
                    _candidate(frame, float(time_s[frame]), 2, float(truth[frame])),
                )
            )
        else:
            frames.append(
                (
                    _candidate(frame, float(time_s[frame]), 1, float(truth[frame])),
                    _candidate(frame, float(time_s[frame]), 2, 5.4e9),
                )
            )
    return (
        RidgeCandidateSet(
            time_s=time_s,
            candidates_by_frame=tuple(frames),
            minimum_frequency_hz=0.05e9,
            maximum_frequency_hz=6.0e9,
            effective_candidate_separation_hz=50.0e6,
            effective_background_exclusion_half_width_hz=50.0e6,
            config=GlobalPathConfig(top_k=2),
            source_path=Path("synthetic/task023d.csv"),
        ),
        truth,
    )


def _run(
    candidate_set: RidgeCandidateSet,
    *,
    method: SmoothBranchMethod = SmoothBranchMethod.E3_CORE_TRIM_BRANCH,
    stft_result: STFTResult | None = None,
) -> SmoothBranchOptimizationResult:
    return optimize_smooth_wrong_branches(
        candidate_set,
        method=method,
        core_config=TrustedCoreConfig(trust_threshold=0.64),
        edge_config=EdgeRescueConfig(),
        internal_config=SegmentRescueConfig(
            minimum_rescue_background_db=18.0,
            minimum_rescue_competitor_db=-8.0,
            acceptance_margin=2.0,
        ),
        ambiguity_config=BranchAmbiguityConfig(),
        trim_config=CoreTrimConfig(),
        branch_config=BranchCompetitionConfig(),
        stft_result=stft_result,
    )


def _diagnostics(count: int, *, high_left: int = 0, high_right: int = 0) -> BranchAmbiguityDiagnostics:
    ambiguity = np.zeros(count, dtype=np.float64)
    ambiguity[:high_left] = 0.8
    if high_right:
        ambiguity[-high_right:] = 0.8
    branch_count = np.where(ambiguity > 0.0, 2, 1).astype(np.int64)
    evidence = np.where(ambiguity > 0.0, 2.0, 12.0)
    return BranchAmbiguityDiagnostics(
        ambiguity,
        branch_count,
        np.ones(count),
        np.ones(count),
        np.ones(count),
        evidence,
        np.full(count, 22.0),
        np.full(count, 7.0),
        np.where(ambiguity > 0.0, 2, 0).astype(np.int64),
        np.where(ambiguity > 0.0, 4.0e9, np.nan),
        np.where(ambiguity > 0.0, 1.0, 0.0),
    )


def test_strongest_is_immutable_and_no_silent_nan() -> None:
    candidate_set, _ = _candidate_set(leading=20, smooth_wrong=True)
    result = _run(candidate_set)
    assert result.strongest.frequency_hz.flags.writeable is False
    assert np.all(np.isfinite(result.final_frequency_hz))
    assert np.array_equal(result.strongest.frequency_hz, np.array([frame[0].transition_frequency_hz for frame in candidate_set.candidates_by_frame]))


def test_core_trim_only_shrinks_and_retains_minimum_length() -> None:
    time_s = np.arange(20, dtype=np.float64) * 2.5e-9
    core = TrustedCore("CORE_01", 0, 19, time_s[0], time_s[-1], 20, time_s[-1], 0.8)
    refined, decisions = refine_trusted_core_boundaries(
        (core,), time_s, _diagnostics(20, high_left=4, high_right=5), config=CoreTrimConfig()
    )
    assert refined[0].frame_start >= core.frame_start
    assert refined[0].frame_end <= core.frame_end
    assert refined[0].frame_count >= 8
    assert decisions[0].left_trimmed_frames > 0
    assert decisions[0].right_trimmed_frames > 0


def test_slope_alone_does_not_trigger_core_trim() -> None:
    time_s = np.arange(20, dtype=np.float64) * 2.5e-9
    core = TrustedCore("CORE_01", 0, 19, time_s[0], time_s[-1], 20, time_s[-1], 0.8)
    refined, decisions = refine_trusted_core_boundaries(
        (core,), time_s, _diagnostics(20), config=CoreTrimConfig()
    )
    assert refined == (core,)
    assert decisions[0].left_trimmed_frames == 0
    assert decisions[0].right_trimmed_frames == 0


def test_correct_core_is_locked() -> None:
    candidate_set, _ = _candidate_set()
    result = _run(candidate_set)
    assert result.core_preservation_rate == 1.0
    assert all(
        decision.left_trimmed_frames == 0 and decision.right_trimmed_frames == 0
        for decision in result.trim_decisions
    )
    assert np.array_equal(
        result.final_frequency_hz[result.trimmed_core_mask],
        result.strongest.frequency_hz[result.trimmed_core_mask],
    )


def test_leading_smooth_wrong_branch_is_repaired_beyond_task023c() -> None:
    candidate_set, truth = _candidate_set(leading=20, smooth_wrong=True)
    current = _run(candidate_set, method=SmoothBranchMethod.E1_TASK023C)
    branch = _run(candidate_set)
    assert np.count_nonzero(branch.modified_mask[:20]) > np.count_nonzero(current.modified_mask[:20])
    assert np.count_nonzero(branch.final_frequency_hz[:20] == truth[:20]) >= 12
    assert branch.leading_branch_decision is not None
    assert branch.leading_branch_decision.status is BranchDecisionStatus.ACCEPTED


def test_trailing_smooth_wrong_branch_is_repaired_beyond_task023c() -> None:
    candidate_set, truth = _candidate_set(trailing=20, smooth_wrong=True)
    current = _run(candidate_set, method=SmoothBranchMethod.E1_TASK023C)
    branch = _run(candidate_set)
    assert np.count_nonzero(branch.modified_mask[-20:]) > np.count_nonzero(current.modified_mask[-20:])
    assert np.count_nonzero(branch.final_frequency_hz[-20:] == truth[-20:]) >= 12
    assert branch.trailing_branch_decision is not None
    assert branch.trailing_branch_decision.status is BranchDecisionStatus.ACCEPTED


def test_correct_smooth_edge_is_not_modified() -> None:
    candidate_set, truth = _candidate_set()
    result = _run(candidate_set)
    assert not np.any(result.modified_mask)
    assert np.array_equal(result.final_frequency_hz, truth)


def test_fast_descent_is_preserved() -> None:
    candidate_set, truth = _candidate_set(fast_descent=True)
    result = _run(candidate_set)
    assert not np.any(result.modified_mask)
    assert np.array_equal(result.final_frequency_hz, truth)


def test_broadband_guardrail_preserves_correct_edge() -> None:
    candidate_set, truth = _candidate_set()
    frequency_hz = np.linspace(0.0, 6.0e9, 65)
    spectrum = np.ones((frequency_hz.size, candidate_set.time_s.size), dtype=np.complex128)
    spectrum[:, -20:] *= 12.0
    stft = STFTResult(
        time_s=candidate_set.time_s,
        frequency_hz=frequency_hz,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=64,
        overlap_samples=48,
        hop_samples=16,
        nfft=128,
        sample_rate_hz=12.0e9,
        source_path=Path("synthetic/broadband-task023d.npz"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    result = _run(candidate_set, stft_result=stft)
    assert not np.any(result.modified_mask)
    assert np.array_equal(result.final_frequency_hz, truth)


def test_branch_identity_is_deterministic() -> None:
    candidate_set, _ = _candidate_set(leading=20, smooth_wrong=True)
    first = branch_ambiguity_diagnostics(candidate_set, config=BranchAmbiguityConfig())
    second = branch_ambiguity_diagnostics(candidate_set, config=BranchAmbiguityConfig())
    assert np.array_equal(first.branch_ambiguity, second.branch_ambiguity)
    one = _run(candidate_set)
    two = _run(candidate_set)
    assert one.leading_branch_decision == two.leading_branch_decision
    assert np.array_equal(one.final_frequency_hz, two.final_frequency_hz)


def test_every_rescued_output_is_from_topk() -> None:
    candidate_set, _ = _candidate_set(leading=20, trailing=20, smooth_wrong=True)
    result = _run(candidate_set)
    for frame_index in np.flatnonzero(result.modified_mask):
        available = {item.transition_frequency_hz for item in candidate_set.candidates_by_frame[int(frame_index)]}
        assert result.final_frequency_hz[frame_index] in available


def test_candidate_graph_is_unchanged() -> None:
    candidate_set, _ = _candidate_set(leading=20, smooth_wrong=True)
    before = candidate_set.candidates_by_frame
    _run(candidate_set)
    assert candidate_set.candidates_by_frame == before


def test_random_single_frame_candidate_does_not_create_persistent_ambiguity() -> None:
    candidate_set, _ = _candidate_set()
    frames = list(candidate_set.candidates_by_frame)
    target = 40
    frames[target] = (
        frames[target][0],
        _candidate(target, float(candidate_set.time_s[target]), 2, 4.0e9),
    )
    altered = RidgeCandidateSet(
        time_s=candidate_set.time_s,
        candidates_by_frame=tuple(frames),
        minimum_frequency_hz=candidate_set.minimum_frequency_hz,
        maximum_frequency_hz=candidate_set.maximum_frequency_hz,
        effective_candidate_separation_hz=candidate_set.effective_candidate_separation_hz,
        effective_background_exclusion_half_width_hz=candidate_set.effective_background_exclusion_half_width_hz,
        config=candidate_set.config,
        source_path=candidate_set.source_path,
    )
    diagnostic = branch_ambiguity_diagnostics(altered, config=BranchAmbiguityConfig())
    assert diagnostic.branch_ambiguity[target] == 0.0


def test_e0_is_exact_strongest_and_e1_is_exact_task023c() -> None:
    candidate_set, _ = _candidate_set(leading=18)
    keep = _run(candidate_set, method=SmoothBranchMethod.E0_KEEP_STRONGEST)
    current = _run(candidate_set, method=SmoothBranchMethod.E1_TASK023C)
    assert np.array_equal(keep.final_frequency_hz, keep.strongest.frequency_hz)
    assert np.array_equal(current.final_frequency_hz, current.task023c.final_frequency_hz)


def test_trim_current_comparator_remains_candidate_provenanced() -> None:
    candidate_set, _ = _candidate_set(trailing=18)
    result = _run(candidate_set, method=SmoothBranchMethod.E2_CORE_TRIM_CURRENT)
    assert result.leading_branch_decision is None
    assert result.trailing_branch_decision is None
    for frame_index in np.flatnonzero(result.modified_mask):
        assert result.final_frequency_hz[frame_index] in {
            item.transition_frequency_hz for item in candidate_set.candidates_by_frame[int(frame_index)]
        }
