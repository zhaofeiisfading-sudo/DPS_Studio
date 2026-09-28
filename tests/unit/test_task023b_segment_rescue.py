"""Tests for strongest-first local segment rescue and immutable boundaries."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidate, RidgeCandidateSet
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.research.task021e_transition_models import robust_first_order_cost
from dps_studio.research.task023b_segment_rescue import (
    RescueStatus,
    SegmentRescueConfig,
    build_strongest_path,
    detect_suspicious_segments,
    local_robust_transition_cost,
    rescue_suspicious_segments,
)


def _candidate(
    frame: int,
    time_s: float,
    rank: int,
    frequency_hz: float,
    *,
    strong_evidence: bool = True,
) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame,
        time_s=time_s,
        candidate_rank=rank,
        discrete_bin_index=rank + 2,
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=frequency_hz,
        peak_amplitude=10.0 / rank,
        peak_to_background_db=20.0 if strong_evidence else 2.0,
        peak_to_competitor_db=5.0 if strong_evidence else -10.0,
        cycles_in_window=3.0,
        is_band_boundary=False,
        refinement_status=RidgeRefinementStatus.REFINED,
    )


def _set(paths: list[list[float]], *, dt: float = 2.5e-9) -> RidgeCandidateSet:
    count = len(paths[0])
    time_s = np.arange(count, dtype=np.float64) * dt
    frames = tuple(
        tuple(
            _candidate(frame, float(time_s[frame]), rank + 1, path[frame])
            for rank, path in enumerate(paths)
        )
        for frame in range(count)
    )
    return RidgeCandidateSet(
        time_s=time_s,
        candidates_by_frame=frames,
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=6.0e9,
        effective_candidate_separation_hz=50.0e6,
        effective_background_exclusion_half_width_hz=50.0e6,
        config=GlobalPathConfig(top_k=len(paths)),
        source_path=Path("synthetic.csv"),
    )


def _isolated() -> RidgeCandidateSet:
    strongest = [1.0e9, 1.0e9, 1.0e9, 1.0e9, 4.0e9, 1.0e9, 1.0e9, 1.0e9, 1.0e9]
    alternative = [2.0e9, 2.0e9, 2.0e9, 2.0e9, 1.0e9, 2.0e9, 2.0e9, 2.0e9, 2.0e9]
    return _set([strongest, alternative])


def test_segment_outside_final_equals_strongest_and_anchors_are_external() -> None:
    candidate_set = _isolated()
    result = rescue_suspicious_segments(candidate_set, config=SegmentRescueConfig())
    assert result.segments
    for decision in result.decisions:
        segment = decision.segment
        if decision.status in {RescueStatus.ACCEPTED_R1, RescueStatus.ACCEPTED_R2}:
            outside = np.ones(result.time_s.size, dtype=np.bool_)
            outside[segment.frame_start : segment.frame_end + 1] = False
            assert np.array_equal(
                result.final_frequency_hz[outside], result.strongest.frequency_hz[outside]
            )
        assert segment.left_anchor_frame is None or segment.left_anchor_frame < segment.frame_start
        assert segment.right_anchor_frame is None or segment.right_anchor_frame > segment.frame_end


def test_rejected_rescue_does_not_modify_strongest() -> None:
    result = rescue_suspicious_segments(
        _isolated(), config=SegmentRescueConfig(acceptance_margin=1.0e9)
    )
    assert np.array_equal(result.final_frequency_hz, result.strongest.frequency_hz)
    assert all(
        decision.status not in {RescueStatus.ACCEPTED_R1, RescueStatus.ACCEPTED_R2}
        for decision in result.decisions
    )


def test_accepted_isolated_distractor_changes_only_candidate_frames() -> None:
    candidate_set = _isolated()
    result = rescue_suspicious_segments(candidate_set, config=SegmentRescueConfig())
    modified = np.flatnonzero(result.modified_mask)
    assert modified.tolist() == [4]
    assert result.final_frequency_hz[4] == 1.0e9
    assert result.final_rank[4] == 2
    assert any(
        decision.status in {RescueStatus.ACCEPTED_R1, RescueStatus.ACCEPTED_R2}
        for decision in result.decisions
    )
    for frame_index in modified:
        available = {
            candidate.transition_frequency_hz
            for candidate in candidate_set.candidates_by_frame[int(frame_index)]
        }
        assert result.final_frequency_hz[frame_index] in available


def test_detector_and_rescue_are_deterministic() -> None:
    candidate_set = _isolated()
    strongest = build_strongest_path(candidate_set)
    first_detection = detect_suspicious_segments(
        strongest, candidate_set, config=SegmentRescueConfig()
    )
    second_detection = detect_suspicious_segments(
        strongest, candidate_set, config=SegmentRescueConfig()
    )
    assert first_detection == second_detection
    first = rescue_suspicious_segments(candidate_set, config=SegmentRescueConfig())
    second = rescue_suspicious_segments(candidate_set, config=SegmentRescueConfig())
    assert np.array_equal(first.final_frequency_hz, second.final_frequency_hz)
    assert first.decisions == second.decisions


def test_already_correct_and_fast_descent_are_not_modified() -> None:
    clean = _set([np.full(40, 1.5e9).tolist(), np.full(40, 3.0e9).tolist()])
    fast = np.concatenate((np.full(12, 3.8e9), 3.8e9 - np.arange(28) * 90.0e6))
    distractor = np.full(fast.size, 5.2e9)
    clean_result = rescue_suspicious_segments(clean, config=SegmentRescueConfig())
    fast_result = rescue_suspicious_segments(
        _set([fast.tolist(), distractor.tolist()]), config=SegmentRescueConfig()
    )
    assert not np.any(clean_result.modified_mask)
    assert not np.any(fast_result.modified_mask)
    assert np.array_equal(fast_result.final_frequency_hz, fast)


def test_no_silent_nan_and_strongest_reference_is_immutable() -> None:
    candidate_set = _isolated()
    before = tuple(tuple(frame) for frame in candidate_set.candidates_by_frame)
    result = rescue_suspicious_segments(candidate_set, config=SegmentRescueConfig())
    assert np.all(np.isfinite(result.final_frequency_hz))
    assert result.strongest.frequency_hz.flags.writeable is False
    assert candidate_set.candidates_by_frame == before


def test_robust_transition_is_exact_task021e_e2() -> None:
    config = SegmentRescueConfig()
    expected = robust_first_order_cost(
        -725.0e6,
        config=GlobalPathConfig(frequency_step_scale_hz=config.frequency_step_scale_hz),
        weight=1.0,
        huber_delta_normalized=0.25,
    )
    assert math.isclose(
        local_robust_transition_cost(-725.0e6, config),
        expected,
        rel_tol=1.0e-15,
        abs_tol=1.0e-15,
    )
