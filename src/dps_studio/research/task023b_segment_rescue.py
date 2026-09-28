"""Strongest-first suspicious-segment rescue for TASK-023B (Research only).

The immutable reference is the frame-wise strongest Top-K candidate.  Detection
only flags frames.  Local dynamic programming is attempted only inside merged
flagged segments with trustworthy anchors on both sides, and an explainable
positive margin is required before any strongest value is replaced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidate, RidgeCandidateSet
from dps_studio.core.time_frequency import STFTResult
from dps_studio.research.task021b_real_experiment import node_cost_components
from dps_studio.research.task021e_transition_models import robust_first_order_cost
from dps_studio.research.task023a_imm_mht_tracker import structure_tensor_diagnostic

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]
TransitionKind = Literal["quadratic", "pseudo_huber"]


class DetectorFlag(str, Enum):
    """Independent reasons that a strongest frame deserves local review."""

    LARGE_ISOLATED_JUMP = "LARGE_ISOLATED_JUMP"
    JUMP_OUT_AND_RETURN = "JUMP_OUT_AND_RETURN"
    SHORT_BRANCH_EXCURSION = "SHORT_BRANCH_EXCURSION"
    LOCAL_SLOPE_INCONSISTENCY = "LOCAL_SLOPE_INCONSISTENCY"
    BROADBAND_COINCIDENT_EXCURSION = "BROADBAND_COINCIDENT_EXCURSION"
    RANK_SUPPORT_INSTABILITY = "RANK_SUPPORT_INSTABILITY"


class RescueStatus(str, Enum):
    """Auditable segment-level acceptance outcome."""

    ACCEPTED_R1 = "ACCEPTED_R1"
    ACCEPTED_R2 = "ACCEPTED_R2"
    KEEP_STRONGEST_NO_LEFT_ANCHOR = "KEEP_STRONGEST_NO_LEFT_ANCHOR"
    KEEP_STRONGEST_NO_RIGHT_ANCHOR = "KEEP_STRONGEST_NO_RIGHT_ANCHOR"
    KEEP_STRONGEST_EMPTY_CANDIDATE_FRAME = "KEEP_STRONGEST_EMPTY_CANDIDATE_FRAME"
    KEEP_STRONGEST_NO_ALTERNATIVE = "KEEP_STRONGEST_NO_ALTERNATIVE"
    KEEP_STRONGEST_WEAK_SPECTRAL_EVIDENCE = "KEEP_STRONGEST_WEAK_SPECTRAL_EVIDENCE"
    KEEP_STRONGEST_ANCHOR_NOT_IMPROVED = "KEEP_STRONGEST_ANCHOR_NOT_IMPROVED"
    KEEP_STRONGEST_MARGIN = "KEEP_STRONGEST_MARGIN"
    KEEP_STRONGEST_OVERSMOOTHING_RISK = "KEEP_STRONGEST_OVERSMOOTHING_RISK"


@dataclass(frozen=True, slots=True)
class SegmentRescueConfig:
    """Synthetic-calibrated Research parameters; never fitted on ch3."""

    large_jump_hz: float = 450.0e6
    return_tolerance_hz: float = 250.0e6
    excursion_deviation_hz: float = 350.0e6
    slope_inconsistency_hz: float = 350.0e6
    support_tolerance_hz: float = 220.0e6
    minimum_support_fraction: float = 0.40
    alternative_support_advantage: float = 0.25
    broadband_robust_z_threshold: float = 3.0
    maximum_excursion_frames: int = 5
    support_context_frames: int = 2
    merge_gap_frames: int = 1
    anchor_search_frames: int = 5
    anchor_curvature_tolerance_hz: float = 300.0e6
    node_weight: float = 0.20
    deviation_weight: float = 0.16
    minimum_rescue_background_db: float = 15.0
    minimum_rescue_competitor_db: float = -8.0
    jump_reduction_weight: float = 0.35
    support_gain_weight: float = 0.50
    orientation_guard_weight: float = 0.0
    acceptance_margin: float = 0.75
    frequency_step_scale_hz: float = 100.0e6
    e2_huber_delta_normalized: float = 0.25
    oversmoothing_slope_ratio: float = 0.35
    supported_slope_min_hz_per_s: float = 5.0e15

    def __post_init__(self) -> None:
        positive = (
            self.large_jump_hz,
            self.return_tolerance_hz,
            self.excursion_deviation_hz,
            self.slope_inconsistency_hz,
            self.support_tolerance_hz,
            self.broadband_robust_z_threshold,
            self.anchor_curvature_tolerance_hz,
            self.frequency_step_scale_hz,
            self.e2_huber_delta_normalized,
            self.supported_slope_min_hz_per_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("Physical detector/rescue scales must be positive and finite.")
        fractions = (
            self.minimum_support_fraction,
            self.alternative_support_advantage,
            self.oversmoothing_slope_ratio,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in fractions):
            raise ValueError("Support and slope ratios must lie in [0, 1].")
        integers = (
            self.maximum_excursion_frames,
            self.support_context_frames,
            self.merge_gap_frames,
            self.anchor_search_frames,
        )
        if any(value < 1 for value in integers):
            raise ValueError("Frame-count parameters must be positive integers.")

    def rows(self) -> list[dict[str, Any]]:
        """Return a reproducible parameter table."""
        return [
            {
                "parameter": name,
                "value": value,
                "calibration_scope": "synthetic calibration subset only",
                "research_only": True,
            }
            for item in fields(self)
            for name, value in ((item.name, getattr(self, item.name)),)
        ]


@dataclass(frozen=True, slots=True, eq=False)
class StrongestPath:
    """Immutable rank-one candidate reference plus explicit STFT fallbacks."""

    time_s: FloatArray
    frequency_hz: FloatArray
    selected_rank: IntArray
    selected_candidate_index: IntArray
    strongest_bin_fallback: BoolArray

    def __post_init__(self) -> None:
        arrays = (
            np.asarray(self.time_s, dtype=np.float64),
            np.asarray(self.frequency_hz, dtype=np.float64),
            np.asarray(self.selected_rank, dtype=np.int64),
            np.asarray(self.selected_candidate_index, dtype=np.int64),
            np.asarray(self.strongest_bin_fallback, dtype=np.bool_),
        )
        if arrays[0].ndim != 1 or arrays[0].size == 0 or any(
            item.shape != arrays[0].shape for item in arrays
        ):
            raise ValueError("StrongestPath arrays must share a non-empty 1-D axis.")
        if not np.all(np.isfinite(arrays[1])):
            raise ValueError("StrongestPath must have complete finite coverage.")
        object.__setattr__(self, "time_s", _immutable_float(arrays[0]))
        object.__setattr__(self, "frequency_hz", _immutable_float(arrays[1]))
        object.__setattr__(self, "selected_rank", _immutable_int(arrays[2]))
        object.__setattr__(self, "selected_candidate_index", _immutable_int(arrays[3]))
        object.__setattr__(self, "strongest_bin_fallback", _immutable_bool(arrays[4]))


@dataclass(frozen=True, slots=True)
class SuspiciousSegment:
    """Merged flagged interval with physical time span and external anchors."""

    segment_id: str
    frame_start: int
    frame_end: int
    start_time_s: float
    end_time_s: float
    length_frames: int
    duration_s: float
    trigger_flags: tuple[DetectorFlag, ...]
    left_anchor_frame: int | None
    right_anchor_frame: int | None
    context_start_time_s: float
    context_end_time_s: float


@dataclass(frozen=True, slots=True)
class RescueComponents:
    """Signed gains; positive values favor the alternative."""

    spectral_evidence_gain: float
    anchor_connection_gain: float
    jump_reduction: float
    local_continuity_gain: float
    candidate_support_gain: float
    broadband_risk_change: float
    deviation_from_strongest: float
    rescue_margin: float


@dataclass(frozen=True, slots=True)
class SegmentDecision:
    """Complete local-path proposal and its acceptance audit."""

    segment: SuspiciousSegment
    status: RescueStatus
    selected_model: str
    original_frequency_hz: FloatArray
    proposed_frequency_hz: FloatArray
    original_rank: IntArray
    proposed_rank: IntArray
    original_segment_cost: float
    rescued_segment_cost: float
    components: RescueComponents
    original_support_fraction: float
    rescued_support_fraction: float
    strongest_local_slope_hz_per_s: float
    rescued_local_slope_hz_per_s: float
    candidate_supported_slope_min_hz_per_s: float
    candidate_supported_slope_max_hz_per_s: float
    oversmoothing_risk: bool


@dataclass(frozen=True, slots=True, eq=False)
class SegmentRescueResult:
    """Strongest-preserving final path and every attempted local intervention."""

    time_s: FloatArray
    strongest: StrongestPath
    final_frequency_hz: FloatArray
    final_rank: IntArray
    suspicious_flags_by_frame: tuple[tuple[DetectorFlag, ...], ...]
    segments: tuple[SuspiciousSegment, ...]
    decisions: tuple[SegmentDecision, ...]

    @property
    def modified_mask(self) -> BoolArray:
        return np.asarray(
            self.final_frequency_hz != self.strongest.frequency_hz, dtype=np.bool_
        )


def build_strongest_path(
    candidate_set: RidgeCandidateSet,
    *,
    stft_result: STFTResult | None = None,
) -> StrongestPath:
    """Create the immutable strongest candidate reference without mutating input."""
    count = candidate_set.time_s.size
    frequency = np.empty(count, dtype=np.float64)
    rank = np.ones(count, dtype=np.int64)
    candidate_index = np.zeros(count, dtype=np.int64)
    fallback = np.zeros(count, dtype=np.bool_)
    for frame_index, frame in enumerate(candidate_set.candidates_by_frame):
        if frame:
            frequency[frame_index] = frame[0].transition_frequency_hz
            continue
        if stft_result is None:
            raise ValueError("Candidate-empty strongest frame requires the original STFT.")
        band = np.flatnonzero(
            (stft_result.frequency_hz >= candidate_set.minimum_frequency_hz)
            & (stft_result.frequency_hz <= candidate_set.maximum_frequency_hz)
        )
        bin_index = int(
            band[int(np.argmax(np.abs(stft_result.spectrum[band, frame_index])))]
        )
        frequency[frame_index] = float(stft_result.frequency_hz[bin_index])
        rank[frame_index] = 0
        candidate_index[frame_index] = -1
        fallback[frame_index] = True
    return StrongestPath(candidate_set.time_s, frequency, rank, candidate_index, fallback)


def detect_suspicious_segments(
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    *,
    config: SegmentRescueConfig,
    stft_result: STFTResult | None = None,
) -> tuple[tuple[tuple[DetectorFlag, ...], ...], tuple[SuspiciousSegment, ...]]:
    """Flag and merge suspicious frames without modifying trajectory values."""
    frequency = strongest.frequency_hz
    count = frequency.size
    flags: list[set[DetectorFlag]] = [set() for _ in range(count)]
    broadband = _broadband_robust_z(stft_result) if stft_result is not None else None
    for index in range(1, count - 1):
        previous_step = frequency[index] - frequency[index - 1]
        next_step = frequency[index + 1] - frequency[index]
        neighbor_recovery = abs(frequency[index + 1] - frequency[index - 1])
        if (
            abs(previous_step) >= config.large_jump_hz
            and abs(next_step) >= config.large_jump_hz
            and neighbor_recovery <= config.return_tolerance_hz
        ):
            flags[index].add(DetectorFlag.LARGE_ISOLATED_JUMP)
            flags[index].add(DetectorFlag.JUMP_OUT_AND_RETURN)
        second_difference = abs(next_step - previous_step)
        if (
            second_difference >= config.slope_inconsistency_hz
            and previous_step * next_step < 0.0
        ):
            flags[index].add(DetectorFlag.LOCAL_SLOPE_INCONSISTENCY)
        expected = 0.5 * (frequency[index - 1] + frequency[index + 1])
        excursion = abs(frequency[index] - expected)
        if (
            broadband is not None
            and broadband[index] >= config.broadband_robust_z_threshold
            and excursion >= config.excursion_deviation_hz
        ):
            flags[index].add(DetectorFlag.BROADBAND_COINCIDENT_EXCURSION)
        strongest_support = local_candidate_support(
            candidate_set, index, frequency[index], config=config
        )
        alternative_support = max(
            (
                local_candidate_support(
                    candidate_set, index, candidate.transition_frequency_hz, config=config
                )
                for candidate in candidate_set.candidates_by_frame[index][1:]
            ),
            default=0.0,
        )
        if (
            strongest_support < config.minimum_support_fraction
            and alternative_support - strongest_support
            >= config.alternative_support_advantage
            and excursion >= config.excursion_deviation_hz
        ):
            flags[index].add(DetectorFlag.RANK_SUPPORT_INSTABILITY)
    outer_context = config.maximum_excursion_frames + 1
    trend_frames = 3
    first_index = outer_context + trend_frames - 1
    for index in range(first_index, count - first_index):
        left_end = index - outer_context
        left_start = left_end - trend_frames + 1
        right_start = index + outer_context
        right_end = right_start + trend_frames - 1
        left_slope = float(
            np.median(
                np.diff(frequency[left_start : left_end + 1])
                / np.diff(strongest.time_s[left_start : left_end + 1])
            )
        )
        right_slope = float(
            np.median(
                np.diff(frequency[right_start : right_end + 1])
                / np.diff(strongest.time_s[right_start : right_end + 1])
            )
        )
        left_prediction = frequency[left_end] + left_slope * (
            strongest.time_s[index] - strongest.time_s[left_end]
        )
        right_prediction = frequency[right_start] - right_slope * (
            strongest.time_s[right_start] - strongest.time_s[index]
        )
        if abs(left_prediction - right_prediction) > config.return_tolerance_hz:
            continue
        expected = 0.5 * (left_prediction + right_prediction)
        if abs(frequency[index] - expected) >= config.excursion_deviation_hz:
            flags[index].add(DetectorFlag.SHORT_BRANCH_EXCURSION)
    suspicious = np.asarray([bool(item) for item in flags], dtype=np.bool_)
    segments = _merge_segments(
        suspicious,
        flags,
        strongest,
        candidate_set,
        config,
    )
    frozen_flags = tuple(tuple(sorted(item, key=lambda flag: flag.value)) for item in flags)
    return frozen_flags, segments


def rescue_suspicious_segments(
    candidate_set: RidgeCandidateSet,
    *,
    config: SegmentRescueConfig,
    stft_result: STFTResult | None = None,
) -> SegmentRescueResult:
    """Detect, locally optimize, and independently gate strongest modifications."""
    strongest = build_strongest_path(candidate_set, stft_result=stft_result)
    strongest_snapshot = strongest.frequency_hz.copy()
    flags, segments = detect_suspicious_segments(
        strongest,
        candidate_set,
        config=config,
        stft_result=stft_result,
    )
    final = strongest.frequency_hz.copy()
    final_rank = strongest.selected_rank.copy()
    decisions: list[SegmentDecision] = []
    for segment in segments:
        decision = _rescue_segment(
            segment,
            strongest,
            candidate_set,
            config,
            stft_result,
        )
        decisions.append(decision)
        if decision.status in {RescueStatus.ACCEPTED_R1, RescueStatus.ACCEPTED_R2}:
            frame_slice = slice(segment.frame_start, segment.frame_end + 1)
            final[frame_slice] = decision.proposed_frequency_hz
            final_rank[frame_slice] = decision.proposed_rank
    if not np.array_equal(strongest.frequency_hz, strongest_snapshot):
        raise RuntimeError("Rescue mutated the immutable strongest reference.")
    if not np.all(np.isfinite(final)):
        raise RuntimeError("Segment rescue produced a silent NaN.")
    return SegmentRescueResult(
        candidate_set.time_s,
        strongest,
        _immutable_float(final),
        _immutable_int(final_rank),
        flags,
        segments,
        tuple(decisions),
    )


def local_candidate_support(
    candidate_set: RidgeCandidateSet,
    frame_index: int,
    frequency_hz: float,
    *,
    config: SegmentRescueConfig,
) -> float:
    """Fraction of ±context neighboring frames with a nearby Top-K candidate."""
    found = 0
    total = 0
    start = max(0, frame_index - config.support_context_frames)
    end = min(len(candidate_set.candidates_by_frame), frame_index + config.support_context_frames + 1)
    for neighbor in range(start, end):
        if neighbor == frame_index:
            continue
        total += 1
        if any(
            abs(candidate.transition_frequency_hz - frequency_hz)
            <= config.support_tolerance_hz
            for candidate in candidate_set.candidates_by_frame[neighbor]
        ):
            found += 1
    return found / total if total else 0.0


def local_robust_transition_cost(
    delta_frequency_hz: float, config: SegmentRescueConfig
) -> float:
    """Expose the exact TASK-021E E2 pseudo-Huber transition for verification."""
    return _transition(delta_frequency_hz, config, "pseudo_huber")


def _merge_segments(
    suspicious: BoolArray,
    flags: list[set[DetectorFlag]],
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: SegmentRescueConfig,
) -> tuple[SuspiciousSegment, ...]:
    indices = np.flatnonzero(suspicious)
    if indices.size == 0:
        return tuple()
    runs: list[tuple[int, int]] = []
    start = int(indices[0])
    end = start
    for value in indices[1:]:
        index = int(value)
        if index - end <= config.merge_gap_frames + 1:
            end = index
        else:
            runs.append((start, end))
            start = end = index
    runs.append((start, end))
    segments: list[SuspiciousSegment] = []
    for number, (frame_start, frame_end) in enumerate(runs, start=1):
        left = _find_anchor(
            frame_start,
            direction=-1,
            suspicious=suspicious,
            strongest=strongest,
            candidate_set=candidate_set,
            config=config,
        )
        right = _find_anchor(
            frame_end,
            direction=1,
            suspicious=suspicious,
            strongest=strongest,
            candidate_set=candidate_set,
            config=config,
        )
        trigger = tuple(
            sorted(
                {flag for index in range(frame_start, frame_end + 1) for flag in flags[index]},
                key=lambda item: item.value,
            )
        )
        context_start = max(0, frame_start - config.anchor_search_frames)
        context_end = min(strongest.time_s.size - 1, frame_end + config.anchor_search_frames)
        segments.append(
            SuspiciousSegment(
                f"SEG_{number:04d}",
                frame_start,
                frame_end,
                float(strongest.time_s[frame_start]),
                float(strongest.time_s[frame_end]),
                frame_end - frame_start + 1,
                float(strongest.time_s[frame_end] - strongest.time_s[frame_start]),
                trigger,
                left,
                right,
                float(strongest.time_s[context_start]),
                float(strongest.time_s[context_end]),
            )
        )
    return tuple(segments)


def _find_anchor(
    boundary: int,
    *,
    direction: int,
    suspicious: BoolArray,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: SegmentRescueConfig,
) -> int | None:
    for distance in range(1, config.anchor_search_frames + 1):
        index = boundary + direction * distance
        if index < 2 or index + 2 >= strongest.time_s.size or suspicious[index]:
            continue
        curvature = abs(
            strongest.frequency_hz[index + 1]
            - 2.0 * strongest.frequency_hz[index]
            + strongest.frequency_hz[index - 1]
        )
        support = local_candidate_support(
            candidate_set, index, strongest.frequency_hz[index], config=config
        )
        if curvature <= config.anchor_curvature_tolerance_hz and support >= config.minimum_support_fraction:
            return index
    return None


def _rescue_segment(
    segment: SuspiciousSegment,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: SegmentRescueConfig,
    stft_result: STFTResult | None,
) -> SegmentDecision:
    original = strongest.frequency_hz[segment.frame_start : segment.frame_end + 1]
    original_rank = strongest.selected_rank[segment.frame_start : segment.frame_end + 1]
    if segment.left_anchor_frame is None:
        return _empty_decision(segment, original, original_rank, RescueStatus.KEEP_STRONGEST_NO_LEFT_ANCHOR)
    if segment.right_anchor_frame is None:
        return _empty_decision(segment, original, original_rank, RescueStatus.KEEP_STRONGEST_NO_RIGHT_ANCHOR)
    frames = candidate_set.candidates_by_frame[segment.frame_start : segment.frame_end + 1]
    if any(not frame for frame in frames):
        return _empty_decision(
            segment, original, original_rank, RescueStatus.KEEP_STRONGEST_EMPTY_CANDIDATE_FRAME
        )
    proposals = []
    for model in ("R1_LOCAL_QUADRATIC", "R2_E2_PSEUDO_HUBER"):
        kind: TransitionKind = "pseudo_huber" if model.startswith("R2") else "quadratic"
        proposed, ranks = _local_dp(
            frames,
            strongest,
            segment,
            candidate_set.config,
            config,
            transition_kind=kind,
        )
        proposals.append(
            _evaluate_proposal(
                segment,
                original,
                original_rank,
                proposed,
                ranks,
                model,
                strongest,
                candidate_set,
                config,
                stft_result,
            )
        )
    alternative = min(proposals, key=lambda item: (-item.components.rescue_margin, item.selected_model))
    if np.array_equal(alternative.proposed_frequency_hz, original):
        return _replace_status(alternative, RescueStatus.KEEP_STRONGEST_NO_ALTERNATIVE)
    changed_candidates = [
        candidate_set.candidates_by_frame[segment.frame_start + offset][int(rank) - 1]
        for offset, rank in enumerate(alternative.proposed_rank)
        if alternative.proposed_frequency_hz[offset] != original[offset]
    ]
    if any(
        not math.isfinite(candidate.peak_to_background_db)
        or not math.isfinite(candidate.peak_to_competitor_db)
        or candidate.peak_to_background_db < config.minimum_rescue_background_db
        or candidate.peak_to_competitor_db < config.minimum_rescue_competitor_db
        for candidate in changed_candidates
    ):
        return _replace_status(
            alternative, RescueStatus.KEEP_STRONGEST_WEAK_SPECTRAL_EVIDENCE
        )
    if alternative.components.anchor_connection_gain < 0.0:
        return _replace_status(
            alternative, RescueStatus.KEEP_STRONGEST_ANCHOR_NOT_IMPROVED
        )
    if alternative.oversmoothing_risk:
        return _replace_status(alternative, RescueStatus.KEEP_STRONGEST_OVERSMOOTHING_RISK)
    if alternative.components.rescue_margin < config.acceptance_margin:
        return _replace_status(alternative, RescueStatus.KEEP_STRONGEST_MARGIN)
    accepted = (
        RescueStatus.ACCEPTED_R2
        if alternative.selected_model == "R2_E2_PSEUDO_HUBER"
        else RescueStatus.ACCEPTED_R1
    )
    return _replace_status(alternative, accepted)


def _local_dp(
    frames: tuple[tuple[RidgeCandidate, ...], ...],
    strongest: StrongestPath,
    segment: SuspiciousSegment,
    node_config: GlobalPathConfig,
    config: SegmentRescueConfig,
    *,
    transition_kind: TransitionKind,
) -> tuple[FloatArray, IntArray]:
    assert segment.left_anchor_frame is not None and segment.right_anchor_frame is not None
    left_hz = strongest.frequency_hz[segment.left_anchor_frame]
    right_hz = strongest.frequency_hz[segment.right_anchor_frame]
    first_frame = segment.frame_start
    costs = np.asarray(
        [
            _candidate_local_node(candidate, strongest.frequency_hz[first_frame], node_config, config)
            + _transition(candidate.transition_frequency_hz - left_hz, config, transition_kind)
            for candidate in frames[0]
        ],
        dtype=np.float64,
    )
    predecessors: list[IntArray] = [np.full(len(frames[0]), -1, dtype=np.int64)]
    for local_index in range(1, len(frames)):
        current_cost = np.empty(len(frames[local_index]), dtype=np.float64)
        parent = np.empty(len(frames[local_index]), dtype=np.int64)
        strongest_hz = strongest.frequency_hz[first_frame + local_index]
        for current_index, candidate in enumerate(frames[local_index]):
            alternatives = costs + np.asarray(
                [
                    _transition(
                        candidate.transition_frequency_hz - previous.transition_frequency_hz,
                        config,
                        transition_kind,
                    )
                    for previous in frames[local_index - 1]
                ],
                dtype=np.float64,
            )
            parent[current_index] = int(np.argmin(alternatives))
            current_cost[current_index] = alternatives[parent[current_index]] + _candidate_local_node(
                candidate, strongest_hz, node_config, config
            )
        predecessors.append(parent)
        costs = current_cost
    terminal = costs + np.asarray(
        [
            _transition(right_hz - candidate.transition_frequency_hz, config, transition_kind)
            for candidate in frames[-1]
        ],
        dtype=np.float64,
    )
    selected = np.empty(len(frames), dtype=np.int64)
    selected[-1] = int(np.argmin(terminal))
    for local_index in range(len(frames) - 1, 0, -1):
        selected[local_index - 1] = predecessors[local_index][selected[local_index]]
    frequency = np.asarray(
        [frames[index][value].transition_frequency_hz for index, value in enumerate(selected)],
        dtype=np.float64,
    )
    rank = np.asarray(
        [frames[index][value].candidate_rank for index, value in enumerate(selected)],
        dtype=np.int64,
    )
    return frequency, rank


def _candidate_local_node(
    candidate: RidgeCandidate,
    strongest_frequency_hz: float,
    node_config: GlobalPathConfig,
    config: SegmentRescueConfig,
) -> float:
    components = node_cost_components(candidate, node_config)
    spectral = float(components["total_candidate_node_cost"])
    deviation = abs(candidate.transition_frequency_hz - strongest_frequency_hz) / config.frequency_step_scale_hz
    return config.node_weight * spectral + config.deviation_weight * deviation


def _transition(delta_hz: float, config: SegmentRescueConfig, kind: TransitionKind) -> float:
    if kind == "quadratic":
        return (abs(delta_hz) / config.frequency_step_scale_hz) ** 2
    return robust_first_order_cost(
        delta_hz,
        config=GlobalPathConfig(frequency_step_scale_hz=config.frequency_step_scale_hz),
        weight=1.0,
        huber_delta_normalized=config.e2_huber_delta_normalized,
    )


def _evaluate_proposal(
    segment: SuspiciousSegment,
    original: FloatArray,
    original_rank: IntArray,
    proposed: FloatArray,
    proposed_rank: IntArray,
    model: str,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: SegmentRescueConfig,
    stft_result: STFTResult | None,
) -> SegmentDecision:
    assert segment.left_anchor_frame is not None and segment.right_anchor_frame is not None
    left_hz = strongest.frequency_hz[segment.left_anchor_frame]
    right_hz = strongest.frequency_hz[segment.right_anchor_frame]
    kind: TransitionKind = "pseudo_huber" if model.startswith("R2") else "quadratic"
    original_spectral = _path_spectral_cost(original_rank, segment, candidate_set, config)
    rescued_spectral = _path_spectral_cost(proposed_rank, segment, candidate_set, config)
    original_anchor = _transition(original[0] - left_hz, config, kind) + _transition(
        right_hz - original[-1], config, kind
    )
    rescued_anchor = _transition(proposed[0] - left_hz, config, kind) + _transition(
        right_hz - proposed[-1], config, kind
    )
    original_continuity = sum(
        _transition(float(value), config, kind) for value in np.diff(original)
    )
    rescued_continuity = sum(
        _transition(float(value), config, kind) for value in np.diff(proposed)
    )
    original_jumps = _jump_count_with_anchors(original, left_hz, right_hz, config.large_jump_hz)
    rescued_jumps = _jump_count_with_anchors(proposed, left_hz, right_hz, config.large_jump_hz)
    original_support = _path_support(original, segment, candidate_set, config)
    rescued_support = _path_support(proposed, segment, candidate_set, config)
    broadband_change = _broadband_risk_change(
        original, proposed, segment, strongest, stft_result, config
    )
    deviation = config.deviation_weight * float(
        np.sum(np.abs(proposed - original) / config.frequency_step_scale_hz)
    )
    components_values = {
        "spectral_evidence_gain": config.node_weight * (original_spectral - rescued_spectral),
        "anchor_connection_gain": original_anchor - rescued_anchor,
        "jump_reduction": config.jump_reduction_weight * (original_jumps - rescued_jumps),
        "local_continuity_gain": original_continuity - rescued_continuity,
        "candidate_support_gain": config.support_gain_weight * (rescued_support - original_support),
        "broadband_risk_change": broadband_change,
        "deviation_from_strongest": deviation,
    }
    margin = (
        components_values["spectral_evidence_gain"]
        + components_values["anchor_connection_gain"]
        + components_values["jump_reduction"]
        + components_values["local_continuity_gain"]
        + components_values["candidate_support_gain"]
        + config.orientation_guard_weight * components_values["broadband_risk_change"]
        - deviation
    )
    components = RescueComponents(**components_values, rescue_margin=margin)
    original_cost = original_spectral + original_anchor + original_continuity
    rescued_cost = rescued_spectral + rescued_anchor + rescued_continuity + deviation
    strongest_slope = _robust_slope(original, segment, strongest)
    rescued_slope = _robust_slope(proposed, segment, strongest)
    slope_min, slope_max = _candidate_slope_range(segment, candidate_set)
    support_has_fast_slope = max(abs(slope_min), abs(slope_max)) >= config.supported_slope_min_hz_per_s
    oversmoothing = (
        support_has_fast_slope
        and abs(strongest_slope) >= config.supported_slope_min_hz_per_s
        and abs(rescued_slope) < config.oversmoothing_slope_ratio * abs(strongest_slope)
    )
    return SegmentDecision(
        segment,
        RescueStatus.KEEP_STRONGEST_MARGIN,
        model,
        _immutable_float(original),
        _immutable_float(proposed),
        _immutable_int(original_rank),
        _immutable_int(proposed_rank),
        original_cost,
        rescued_cost,
        components,
        original_support,
        rescued_support,
        strongest_slope,
        rescued_slope,
        slope_min,
        slope_max,
        oversmoothing,
    )


def _path_spectral_cost(
    ranks: IntArray,
    segment: SuspiciousSegment,
    candidate_set: RidgeCandidateSet,
    config: SegmentRescueConfig,
) -> float:
    total = 0.0
    for offset, rank in enumerate(ranks):
        candidate = candidate_set.candidates_by_frame[segment.frame_start + offset][int(rank) - 1]
        total += float(node_cost_components(candidate, candidate_set.config)["total_candidate_node_cost"])
    return total


def _path_support(
    frequency: FloatArray,
    segment: SuspiciousSegment,
    candidate_set: RidgeCandidateSet,
    config: SegmentRescueConfig,
) -> float:
    values = [
        local_candidate_support(candidate_set, segment.frame_start + offset, float(value), config=config)
        for offset, value in enumerate(frequency)
    ]
    return float(np.mean(values)) if values else 0.0


def _broadband_risk_change(
    original: FloatArray,
    proposed: FloatArray,
    segment: SuspiciousSegment,
    strongest: StrongestPath,
    stft_result: STFTResult | None,
    config: SegmentRescueConfig,
) -> float:
    if stft_result is None:
        return 0.0
    broadband = _broadband_robust_z(stft_result)
    original_risk = 0.0
    proposed_risk = 0.0
    for offset, frame_index in enumerate(range(segment.frame_start, segment.frame_end + 1)):
        if broadband[frame_index] < config.broadband_robust_z_threshold:
            continue
        time_s = float(strongest.time_s[frame_index])
        original_risk += structure_tensor_diagnostic(
            stft_result, time_s=time_s, frequency_hz=float(original[offset])
        ).vertical_likeness
        proposed_risk += structure_tensor_diagnostic(
            stft_result, time_s=time_s, frequency_hz=float(proposed[offset])
        ).vertical_likeness
    # Diagnostic only in phase one: record signed unweighted change.
    return original_risk - proposed_risk


def _jump_count_with_anchors(
    frequency: FloatArray, left_hz: float, right_hz: float, threshold_hz: float
) -> int:
    joined = np.concatenate((np.asarray([left_hz]), frequency, np.asarray([right_hz])))
    return int(np.count_nonzero(np.abs(np.diff(joined)) >= threshold_hz))


def _robust_slope(
    frequency: FloatArray, segment: SuspiciousSegment, strongest: StrongestPath
) -> float:
    if frequency.size < 2:
        assert segment.left_anchor_frame is not None and segment.right_anchor_frame is not None
        dt = strongest.time_s[segment.right_anchor_frame] - strongest.time_s[segment.left_anchor_frame]
        return float(
            (strongest.frequency_hz[segment.right_anchor_frame] - strongest.frequency_hz[segment.left_anchor_frame])
            / dt
        )
    time_s = strongest.time_s[segment.frame_start : segment.frame_end + 1]
    return float(np.median(np.diff(frequency) / np.diff(time_s)))


def _candidate_slope_range(
    segment: SuspiciousSegment, candidate_set: RidgeCandidateSet
) -> tuple[float, float]:
    slopes: list[float] = []
    for frame_index in range(segment.frame_start + 1, segment.frame_end + 1):
        dt = float(candidate_set.time_s[frame_index] - candidate_set.time_s[frame_index - 1])
        for previous in candidate_set.candidates_by_frame[frame_index - 1]:
            for current in candidate_set.candidates_by_frame[frame_index]:
                slopes.append((current.transition_frequency_hz - previous.transition_frequency_hz) / dt)
    return (min(slopes), max(slopes)) if slopes else (0.0, 0.0)


def _replace_status(decision: SegmentDecision, status: RescueStatus) -> SegmentDecision:
    return SegmentDecision(
        decision.segment,
        status,
        decision.selected_model,
        decision.original_frequency_hz,
        decision.proposed_frequency_hz,
        decision.original_rank,
        decision.proposed_rank,
        decision.original_segment_cost,
        decision.rescued_segment_cost,
        decision.components,
        decision.original_support_fraction,
        decision.rescued_support_fraction,
        decision.strongest_local_slope_hz_per_s,
        decision.rescued_local_slope_hz_per_s,
        decision.candidate_supported_slope_min_hz_per_s,
        decision.candidate_supported_slope_max_hz_per_s,
        decision.oversmoothing_risk,
    )


def _empty_decision(
    segment: SuspiciousSegment,
    original: FloatArray,
    original_rank: IntArray,
    status: RescueStatus,
) -> SegmentDecision:
    zero = RescueComponents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return SegmentDecision(
        segment,
        status,
        "NONE",
        _immutable_float(original),
        _immutable_float(original),
        _immutable_int(original_rank),
        _immutable_int(original_rank),
        0.0,
        0.0,
        zero,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        False,
    )


def _broadband_robust_z(stft_result: STFTResult) -> FloatArray:
    power = np.sum(np.square(np.abs(stft_result.spectrum)), axis=0)
    median = float(np.median(power))
    mad = float(np.median(np.abs(power - median)))
    scale = max(1.4826 * mad, np.finfo(np.float64).eps * max(abs(median), 1.0))
    return np.asarray((power - median) / scale, dtype=np.float64)


def _immutable_float(value: NDArray[Any]) -> FloatArray:
    array = np.array(value, dtype=np.float64, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _immutable_int(value: NDArray[Any]) -> IntArray:
    array = np.array(value, dtype=np.int64, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.int64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _immutable_bool(value: NDArray[Any]) -> BoolArray:
    array = np.array(value, dtype=np.bool_, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.bool_).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = [
    "DetectorFlag",
    "RescueComponents",
    "RescueStatus",
    "SegmentDecision",
    "SegmentRescueConfig",
    "SegmentRescueResult",
    "StrongestPath",
    "SuspiciousSegment",
    "build_strongest_path",
    "detect_suspicious_segments",
    "local_candidate_support",
    "local_robust_transition_cost",
    "rescue_suspicious_segments",
]
