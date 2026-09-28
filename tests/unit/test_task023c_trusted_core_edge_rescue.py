"""Tests for TASK-023C trusted-core locked single-anchor edge rescue."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidate, RidgeCandidateSet
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.time_frequency import STFTResult
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig, build_strongest_path
from dps_studio.research.task023c_trusted_core_edge_rescue import (
    EdgeDirection,
    EdgeRescueConfig,
    EdgeStatus,
    TrustedCoreConfig,
    TrustedCoreOptimizationResult,
    identify_trusted_cores,
    optimize_trusted_core_trajectory,
)


def _candidate(
    frame: int,
    time_s: float,
    rank: int,
    frequency_hz: float,
    *,
    background_db: float = 22.0,
    competitor_db: float = -3.0,
) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame,
        time_s=time_s,
        candidate_rank=rank,
        discrete_bin_index=rank + 5,
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=frequency_hz,
        peak_amplitude=20.0 / rank,
        peak_to_background_db=background_db,
        peak_to_competitor_db=7.0 if rank == 1 else competitor_db,
        cycles_in_window=4.0,
        is_band_boundary=False,
        refinement_status=RidgeRefinementStatus.REFINED,
    )


def _edge_set(
    *,
    leading: int = 0,
    trailing: int = 0,
    smooth: bool = False,
    count: int = 80,
) -> RidgeCandidateSet:
    time_s = np.arange(count, dtype=np.float64) * 2.5e-9
    truth = np.full(count, 2.4e9)
    frames: list[tuple[RidgeCandidate, ...]] = []
    rng = np.random.default_rng(23003 + leading * 3 + trailing)
    for frame in range(count):
        false_edge = frame < leading or frame >= count - trailing
        if false_edge:
            wrong = (
                4.5e9 + (frame - count / 2) * 8.0e6
                if smooth
                else float(rng.uniform(0.5e9, 5.8e9))
            )
            frames.append(
                (
                    _candidate(frame, float(time_s[frame]), 1, wrong),
                    _candidate(frame, float(time_s[frame]), 2, truth[frame]),
                )
            )
        else:
            frames.append(
                (
                    _candidate(frame, float(time_s[frame]), 1, truth[frame]),
                    _candidate(frame, float(time_s[frame]), 2, 5.2e9),
                )
            )
    return RidgeCandidateSet(
        time_s=time_s,
        candidates_by_frame=tuple(frames),
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=6.0e9,
        effective_candidate_separation_hz=50.0e6,
        effective_background_exclusion_half_width_hz=50.0e6,
        config=GlobalPathConfig(top_k=2),
        source_path=Path("synthetic/task023c.csv"),
    )


def _run(
    candidate_set: RidgeCandidateSet,
    *,
    edge_config: EdgeRescueConfig | None = None,
    stft_result: STFTResult | None = None,
) -> TrustedCoreOptimizationResult:
    return optimize_trusted_core_trajectory(
        candidate_set,
        core_config=TrustedCoreConfig(),
        edge_config=EdgeRescueConfig() if edge_config is None else edge_config,
        internal_config=SegmentRescueConfig(
            minimum_rescue_background_db=18.0,
            minimum_rescue_competitor_db=-8.0,
            acceptance_margin=2.0,
        ),
        stft_result=stft_result,
    )


def test_strongest_immutable_core_deterministic_and_locked() -> None:
    candidate_set = _edge_set(leading=16)
    strongest = build_strongest_path(candidate_set)
    first = identify_trusted_cores(
        strongest, candidate_set, config=TrustedCoreConfig()
    )
    second = identify_trusted_cores(
        strongest, candidate_set, config=TrustedCoreConfig()
    )
    assert first[1] == second[1]
    assert np.array_equal(first[0].trust_score, second[0].trust_score)
    assert np.array_equal(first[0].trusted_frame, second[0].trusted_frame)
    result = _run(candidate_set)
    assert result.strongest.frequency_hz.flags.writeable is False
    assert result.cores
    assert np.array_equal(
        result.final_frequency_hz[result.core_mask],
        result.strongest.frequency_hz[result.core_mask],
    )
    assert result.core_preservation_rate == 1.0


def test_leading_rescue_uses_only_right_anchor_and_topk() -> None:
    candidate_set = _edge_set(leading=18)
    result = _run(candidate_set)
    decision = result.leading_decision
    assert decision is not None and decision.status is EdgeStatus.ACCEPTED
    assert decision.direction is EdgeDirection.LEADING_BACKWARD
    assert decision.anchor_frame == result.cores[0].frame_start
    assert decision.modified_frame_count >= 14
    assert result.trailing_decision is not None
    assert result.trailing_decision.modified_frame_count == 0
    for index in np.flatnonzero(result.modified_mask):
        available = {
            candidate.transition_frequency_hz
            for candidate in candidate_set.candidates_by_frame[int(index)]
        }
        assert result.final_frequency_hz[index] in available


def test_trailing_rescue_uses_only_left_anchor_and_topk() -> None:
    candidate_set = _edge_set(trailing=18)
    result = _run(candidate_set)
    decision = result.trailing_decision
    assert decision is not None and decision.status is EdgeStatus.ACCEPTED
    assert decision.direction is EdgeDirection.TRAILING_FORWARD
    assert decision.anchor_frame == result.cores[-1].frame_end
    assert decision.modified_frame_count >= 14
    assert result.leading_decision is not None
    assert result.leading_decision.modified_frame_count == 0


def test_smooth_wrong_edges_are_rescued() -> None:
    leading = _run(_edge_set(leading=20, smooth=True))
    trailing = _run(_edge_set(trailing=20, smooth=True))
    assert leading.leading_decision is not None
    assert leading.leading_decision.status is EdgeStatus.ACCEPTED
    assert trailing.trailing_decision is not None
    assert trailing.trailing_decision.status is EdgeStatus.ACCEPTED
    assert np.count_nonzero(leading.modified_mask[:20]) >= 3
    assert np.count_nonzero(trailing.modified_mask[-20:]) >= 3


def test_correct_edges_are_not_modified_and_no_nan() -> None:
    result = _run(_edge_set())
    assert not np.any(result.modified_mask)
    assert np.all(np.isfinite(result.final_frequency_hz))
    assert result.core_preservation_rate == 1.0


def test_fast_descent_near_trailing_edge_is_not_flattened() -> None:
    candidate_set = _edge_set()
    time_s = candidate_set.time_s
    truth = np.where(np.arange(time_s.size) < 45, 3.8e9, 3.8e9 - (np.arange(time_s.size) - 45) * 80.0e6)
    frames = tuple(
        (
            _candidate(index, float(time_s[index]), 1, float(truth[index])),
            _candidate(index, float(time_s[index]), 2, 5.2e9),
        )
        for index in range(time_s.size)
    )
    fast = RidgeCandidateSet(
        time_s=time_s,
        candidates_by_frame=frames,
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=6.0e9,
        effective_candidate_separation_hz=50.0e6,
        effective_background_exclusion_half_width_hz=50.0e6,
        config=GlobalPathConfig(top_k=2),
        source_path=Path("synthetic/fast.csv"),
    )
    result = _run(fast)
    assert np.array_equal(result.final_frequency_hz, truth)
    assert not np.any(result.modified_mask)


def test_hysteresis_and_rescue_are_deterministic() -> None:
    candidate_set = _edge_set(leading=22)
    first = _run(candidate_set)
    second = _run(candidate_set)
    assert first.leading_decision == second.leading_decision
    assert np.array_equal(first.final_frequency_hz, second.final_frequency_hz)


def test_candidate_graph_is_not_modified() -> None:
    candidate_set = _edge_set(leading=16, trailing=16)
    before = candidate_set.candidates_by_frame
    _run(candidate_set)
    assert candidate_set.candidates_by_frame == before


def test_broadband_edge_guardrail_keeps_correct_strongest() -> None:
    candidate_set = _edge_set()
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
        source_path=Path("synthetic/broadband.npz"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    result = _run(candidate_set, stft_result=stft)
    assert not np.any(result.modified_mask)
    assert np.array_equal(result.final_frequency_hz, result.strongest.frequency_hz)


def test_stop_rescue_falls_back_to_strongest_after_evidence_loss() -> None:
    candidate_set = _edge_set(leading=20)
    frames = list(candidate_set.candidates_by_frame)
    for frame_index in range(8):
        original = frames[frame_index]
        frames[frame_index] = (
            original[0],
            _candidate(
                frame_index,
                float(candidate_set.time_s[frame_index]),
                2,
                2.4e9,
                background_db=18.0,
            ),
        )
    weakened = RidgeCandidateSet(
        time_s=candidate_set.time_s,
        candidates_by_frame=tuple(frames),
        minimum_frequency_hz=candidate_set.minimum_frequency_hz,
        maximum_frequency_hz=candidate_set.maximum_frequency_hz,
        effective_candidate_separation_hz=candidate_set.effective_candidate_separation_hz,
        effective_background_exclusion_half_width_hz=candidate_set.effective_background_exclusion_half_width_hz,
        config=candidate_set.config,
        source_path=candidate_set.source_path,
    )
    result = _run(
        weakened,
        edge_config=EdgeRescueConfig(minimum_background_db=20.0),
    )
    assert result.leading_decision is not None
    assert result.leading_decision.stopped_early
    assert not np.any(result.modified_mask[:8])
    assert np.any(result.modified_mask[8:20])
