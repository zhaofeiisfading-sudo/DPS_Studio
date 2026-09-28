"""Smooth wrong-branch discrimination for TASK-023D (Research only).

The module deliberately consumes an existing :class:`RidgeCandidateSet`.  It
never creates candidates and never emits a frequency outside that graph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import RidgeCandidate, RidgeCandidateSet
from dps_studio.core.time_frequency import STFTResult
from dps_studio.research.task021b_real_experiment import node_cost_components
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import (
    EdgeDecision,
    EdgeDirection,
    EdgeRescueConfig,
    TrustedCore,
    TrustedCoreConfig,
    TrustedCoreOptimizationResult,
    _apply_edge,
    _broadband_robust_z,
    _edge_rescue,
    _rank_limited_support,
    optimize_trusted_core_trajectory,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


class SmoothBranchMethod(str, Enum):
    """Required TASK-023D comparators."""

    E0_KEEP_STRONGEST = "E0_KEEP_STRONGEST"
    E1_TASK023C = "E1_TASK023C"
    E2_CORE_TRIM_CURRENT = "E2_CORE_TRIM_CURRENT"
    E3_CORE_TRIM_BRANCH = "E3_CORE_TRIM_BRANCH"
    E4_CONSERVATIVE_BRANCH = "E4_CONSERVATIVE_BRANCH"


class BranchDecisionStatus(str, Enum):
    """Auditable branch-level outcome."""

    ACCEPTED = "ACCEPTED"
    KEEP_NO_EDGE = "KEEP_NO_EDGE"
    KEEP_NO_ALTERNATIVE = "KEEP_NO_ALTERNATIVE"
    KEEP_MARGIN = "KEEP_MARGIN"
    KEEP_EVIDENCE = "KEEP_EVIDENCE"
    KEEP_DEVIATION_BUDGET = "KEEP_DEVIATION_BUDGET"


@dataclass(frozen=True, slots=True)
class BranchAmbiguityConfig:
    """Physical candidate-tube persistence and ambiguity controls."""

    context_time_s: float = 16.0e-9
    link_base_hz: float = 180.0e6
    maximum_rate_hz_per_s: float = 80.0e15
    maximum_candidate_rank: int = 4
    minimum_persistent_frames: int = 4
    minimum_branch_separation_hz: float = 260.0e6
    evidence_balance_scale_db: float = 8.0

    def __post_init__(self) -> None:
        positive = (
            self.context_time_s,
            self.link_base_hz,
            self.maximum_rate_hz_per_s,
            self.minimum_branch_separation_hz,
            self.evidence_balance_scale_db,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("Ambiguity physical scales must be positive and finite.")
        if self.maximum_candidate_rank < 2 or self.minimum_persistent_frames < 2:
            raise ValueError("Ambiguity rank and persistence limits are invalid.")

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"parameter": item.name, "value": getattr(self, item.name), "scope": "synthetic_only"}
            for item in fields(self)
        ]


@dataclass(frozen=True, slots=True)
class CoreTrimConfig:
    """Inward-only trusted-core boundary refinement."""

    ambiguity_threshold: float = 0.42
    minimum_ambiguity_increase: float = 0.15
    maximum_strongest_advantage_db: float = 7.0
    degraded_background_db: float = 14.0
    degraded_competitor_db: float = 2.0
    minimum_background_drop_db: float = 6.0
    minimum_competitor_drop_db: float = 3.0
    minimum_edge_review_fraction: float = 0.50
    edge_review_time_s: float = 16.0e-9
    maximum_trim_time_s: float = 32.0e-9
    minimum_retained_core_frames: int = 8
    maximum_unambiguous_gap_frames: int = 1

    def __post_init__(self) -> None:
        fractions = (self.ambiguity_threshold, self.minimum_edge_review_fraction)
        if any(not 0.0 <= value <= 1.0 for value in fractions):
            raise ValueError("Core-trim fractions must lie in [0, 1].")
        if self.edge_review_time_s <= 0.0 or self.maximum_trim_time_s <= 0.0:
            raise ValueError("Core-trim physical durations must be positive.")
        if self.minimum_retained_core_frames < 2 or self.maximum_unambiguous_gap_frames < 0:
            raise ValueError("Core-trim frame limits are invalid.")

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"parameter": item.name, "value": getattr(self, item.name), "scope": "synthetic_only"}
            for item in fields(self)
        ]


@dataclass(frozen=True, slots=True)
class BranchCompetitionConfig:
    """Local branch-hypothesis scoring and acceptance controls."""

    beam_width: int = 8
    link_base_hz: float = 180.0e6
    maximum_rate_hz_per_s: float = 80.0e15
    slope_memory: float = 0.65
    spectral_weight: float = 0.10
    persistence_weight: float = 0.35
    identity_weight: float = 1.20
    ambiguity_weight: float = 0.35
    broadband_weight: float = 0.02
    deviation_weight: float = 0.008
    identity_break_penalty: float = 9.0
    minimum_identity_support: float = 0.48
    minimum_local_support: float = 0.50
    branch_acceptance_margin: float = 1.50
    maximum_modified_frames: int = 64
    maximum_modified_fraction: float = 1.0
    maximum_total_deviation_hz: float = 120.0e9
    broadband_z_threshold: float = 3.0
    broadband_support_floor: float = 0.75

    def __post_init__(self) -> None:
        positive = (
            self.link_base_hz,
            self.maximum_rate_hz_per_s,
            self.identity_break_penalty,
            self.branch_acceptance_margin,
            self.maximum_total_deviation_hz,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("Branch competition scales must be positive and finite.")
        fractions = (
            self.slope_memory,
            self.minimum_identity_support,
            self.minimum_local_support,
            self.maximum_modified_fraction,
            self.broadband_support_floor,
        )
        if any(not 0.0 <= value <= 1.0 for value in fractions):
            raise ValueError("Branch competition fractions must lie in [0, 1].")
        if self.beam_width < 1 or self.maximum_modified_frames < 1:
            raise ValueError("Branch beam and modification limits must be positive.")

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"parameter": item.name, "value": getattr(self, item.name), "scope": "synthetic_only"}
            for item in fields(self)
        ]


@dataclass(frozen=True, slots=True, eq=False)
class BranchAmbiguityDiagnostics:
    """Per-frame persistent-tube evidence."""

    branch_ambiguity: FloatArray
    persistent_branch_count: IntArray
    strongest_backward_persistence: FloatArray
    strongest_forward_persistence: FloatArray
    strongest_branch_persistence: FloatArray
    strongest_vs_rank2_evidence_db: FloatArray
    strongest_peak_to_background_db: FloatArray
    strongest_peak_to_competitor_db: FloatArray
    best_alternative_rank: IntArray
    best_alternative_frequency_hz: FloatArray
    best_alternative_persistence: FloatArray


@dataclass(frozen=True, slots=True)
class CoreTrimDecision:
    """Original and inward-only refined bounds for one core."""

    core_id: str
    original_frame_start: int
    original_frame_end: int
    trimmed_frame_start: int
    trimmed_frame_end: int
    left_trimmed_frames: int
    right_trimmed_frames: int
    original_start_time_s: float
    original_end_time_s: float
    trimmed_start_time_s: float
    trimmed_end_time_s: float
    left_reason: str
    right_reason: str


@dataclass(frozen=True, slots=True)
class BranchStepAudit:
    """One candidate selection in an edge branch hypothesis."""

    frame_index: int
    time_s: float
    original_frequency_hz: float
    proposed_frequency_hz: float
    original_rank: int
    proposed_rank: int
    branch_identity_support: float
    local_candidate_support: float
    persistent_branch_count: int
    branch_ambiguity: float
    spectral_cost: float
    persistence_cost: float
    anchor_connection_cost: float
    ambiguity_cost: float
    broadband_cost: float
    deviation_cost: float
    broadband_exposure: float
    modified: bool


@dataclass(frozen=True, slots=True)
class BranchScoreComponents:
    """Decomposed proposal gain relative to the strongest edge branch."""

    spectral_evidence_gain: float
    persistence_gain: float
    anchor_connection_gain: float
    ambiguity_gain: float
    broadband_risk_change: float
    deviation_from_strongest: float
    branch_margin: float


@dataclass(frozen=True, slots=True)
class BranchDecision:
    """One complete leading or trailing branch competition."""

    direction: EdgeDirection
    status: BranchDecisionStatus
    anchor_frame: int
    frame_start: int
    frame_end: int
    modified_frame_count: int
    branch_duration_s: float
    score: BranchScoreComponents
    steps: tuple[BranchStepAudit, ...]


@dataclass(frozen=True, slots=True, eq=False)
class SmoothBranchOptimizationResult:
    """TASK-023D result with all comparator provenance retained."""

    method: SmoothBranchMethod
    task023c: TrustedCoreOptimizationResult
    ambiguity: BranchAmbiguityDiagnostics
    original_cores: tuple[TrustedCore, ...]
    trimmed_cores: tuple[TrustedCore, ...]
    trim_decisions: tuple[CoreTrimDecision, ...]
    trimmed_core_mask: BoolArray
    final_frequency_hz: FloatArray
    final_rank: IntArray
    modification_reason: tuple[str, ...]
    leading_branch_decision: BranchDecision | None
    trailing_branch_decision: BranchDecision | None
    leading_current_decision: EdgeDecision | None
    trailing_current_decision: EdgeDecision | None

    @property
    def strongest(self) -> Any:
        return self.task023c.strongest

    @property
    def modified_mask(self) -> BoolArray:
        return np.asarray(
            self.final_frequency_hz != self.task023c.strongest.frequency_hz,
            dtype=np.bool_,
        )

    @property
    def core_preservation_rate(self) -> float:
        if not np.any(self.trimmed_core_mask):
            return math.nan
        strongest = self.task023c.strongest.frequency_hz
        return float(np.mean(self.final_frequency_hz[self.trimmed_core_mask] == strongest[self.trimmed_core_mask]))


@dataclass(frozen=True, slots=True)
class _BranchState:
    current_frequency_hz: float
    recent_slope_hz_per_s: float
    identity_support: float
    total_cost: float
    spectral_cost: float
    persistence_cost: float
    anchor_cost: float
    ambiguity_cost: float
    broadband_cost: float
    deviation_cost: float
    frequencies_hz: tuple[float, ...]
    ranks: tuple[int, ...]
    identities: tuple[float, ...]
    local_supports: tuple[float, ...]
    increments: tuple[tuple[float, float, float, float, float, float], ...]


def branch_ambiguity_diagnostics(
    candidate_set: RidgeCandidateSet,
    *,
    config: BranchAmbiguityConfig,
) -> BranchAmbiguityDiagnostics:
    """Measure coexisting persistent candidate tubes, not raw candidate count."""
    count = len(candidate_set.candidates_by_frame)
    backward, forward = _candidate_persistence(candidate_set, config)
    ambiguity = np.zeros(count, dtype=np.float64)
    branch_count = np.zeros(count, dtype=np.int64)
    strongest_back = np.zeros(count, dtype=np.float64)
    strongest_forward = np.zeros(count, dtype=np.float64)
    strongest_persistence = np.zeros(count, dtype=np.float64)
    evidence = np.full(count, math.nan, dtype=np.float64)
    background_db = np.full(count, math.nan, dtype=np.float64)
    competitor_db = np.full(count, math.nan, dtype=np.float64)
    alternative_rank = np.zeros(count, dtype=np.int64)
    alternative_hz = np.full(count, math.nan, dtype=np.float64)
    alternative_persistence = np.zeros(count, dtype=np.float64)
    for frame_index, frame in enumerate(candidate_set.candidates_by_frame):
        retained = frame[: config.maximum_candidate_rank]
        if not retained:
            continue
        background_db[frame_index] = retained[0].peak_to_background_db
        competitor_db[frame_index] = retained[0].peak_to_competitor_db
        context_frames = _context_frame_count(candidate_set.time_s, frame_index, config.context_time_s)
        total_persistence = [
            min(1.0, (backward[frame_index][index] + forward[frame_index][index] - 1) / context_frames)
            for index in range(len(retained))
        ]
        persistent = [
            index
            for index, value in enumerate(total_persistence)
            if backward[frame_index][index] + forward[frame_index][index] - 1
            >= config.minimum_persistent_frames
        ]
        branch_count[frame_index] = len(persistent)
        strongest_back[frame_index] = min(1.0, backward[frame_index][0] / context_frames)
        strongest_forward[frame_index] = min(1.0, forward[frame_index][0] / context_frames)
        strongest_persistence[frame_index] = total_persistence[0]
        alternatives = [
            index
            for index in persistent
            if index > 0
            and abs(
                retained[index].transition_frequency_hz
                - retained[0].transition_frequency_hz
            )
            >= config.minimum_branch_separation_hz
        ]
        if not alternatives:
            continue
        best = max(
            alternatives,
            key=lambda index: (
                total_persistence[index],
                retained[index].peak_amplitude,
                -retained[index].candidate_rank,
            ),
        )
        advantage_db = 20.0 * math.log10(
            max(retained[0].peak_amplitude, np.finfo(float).tiny)
            / max(retained[best].peak_amplitude, np.finfo(float).tiny)
        )
        evidence[frame_index] = advantage_db
        alternative_rank[frame_index] = retained[best].candidate_rank
        alternative_hz[frame_index] = retained[best].transition_frequency_hz
        alternative_persistence[frame_index] = total_persistence[best]
        balance = math.exp(-max(advantage_db, 0.0) / config.evidence_balance_scale_db)
        co_persistence = min(total_persistence[0], total_persistence[best])
        ambiguity[frame_index] = float(np.clip(balance * co_persistence, 0.0, 1.0))
    return BranchAmbiguityDiagnostics(
        _immutable_float(ambiguity),
        _immutable_int(branch_count),
        _immutable_float(strongest_back),
        _immutable_float(strongest_forward),
        _immutable_float(strongest_persistence),
        _immutable_float(evidence),
        _immutable_float(background_db),
        _immutable_float(competitor_db),
        _immutable_int(alternative_rank),
        _immutable_float(alternative_hz),
        _immutable_float(alternative_persistence),
    )


def refine_trusted_core_boundaries(
    cores: tuple[TrustedCore, ...],
    time_s: FloatArray,
    ambiguity: BranchAmbiguityDiagnostics,
    *,
    config: CoreTrimConfig,
) -> tuple[tuple[TrustedCore, ...], tuple[CoreTrimDecision, ...]]:
    """Trim core edges inward only; never expand or change a core frequency."""
    refined: list[TrustedCore] = []
    decisions: list[CoreTrimDecision] = []
    for core in cores:
        start, end = core.frame_start, core.frame_end
        maximum_by_length = max(0, core.frame_count - config.minimum_retained_core_frames)
        left_limit = min(
            maximum_by_length,
            _frames_within_duration(time_s, start, end, config.maximum_trim_time_s, forward=True),
        )
        left_trim = _trim_count(
            start,
            end,
            ambiguity,
            time_s,
            config,
            forward=True,
            limit=left_limit,
        )
        remaining = maximum_by_length - left_trim
        right_limit = min(
            remaining,
            _frames_within_duration(time_s, start + left_trim, end, config.maximum_trim_time_s, forward=False),
        )
        right_trim = _trim_count(
            start + left_trim,
            end,
            ambiguity,
            time_s,
            config,
            forward=False,
            limit=right_limit,
        )
        new_start = start + left_trim
        new_end = end - right_trim
        if new_start < start or new_end > end or new_start > new_end:
            raise RuntimeError("Trusted-core refinement attempted expansion or deletion.")
        refined.append(
            TrustedCore(
                core.core_id,
                new_start,
                new_end,
                float(time_s[new_start]),
                float(time_s[new_end]),
                new_end - new_start + 1,
                float(time_s[new_end] - time_s[new_start]),
                core.mean_trust,
            )
        )
        decisions.append(
            CoreTrimDecision(
                core.core_id,
                start,
                end,
                new_start,
                new_end,
                left_trim,
                right_trim,
                float(time_s[start]),
                float(time_s[end]),
                float(time_s[new_start]),
                float(time_s[new_end]),
                "PERSISTENT_BRANCH_AMBIGUITY" if left_trim else "KEEP_BOUNDARY",
                "PERSISTENT_BRANCH_AMBIGUITY" if right_trim else "KEEP_BOUNDARY",
            )
        )
    return tuple(refined), tuple(decisions)


def optimize_smooth_wrong_branches(
    candidate_set: RidgeCandidateSet,
    *,
    method: SmoothBranchMethod,
    core_config: TrustedCoreConfig,
    edge_config: EdgeRescueConfig,
    internal_config: SegmentRescueConfig,
    ambiguity_config: BranchAmbiguityConfig,
    trim_config: CoreTrimConfig,
    branch_config: BranchCompetitionConfig,
    stft_result: STFTResult | None = None,
) -> SmoothBranchOptimizationResult:
    """Run one E0--E4 comparator without mutating strongest or upstream data."""
    candidate_snapshot = candidate_set.candidates_by_frame
    task023c = optimize_trusted_core_trajectory(
        candidate_set,
        core_config=core_config,
        edge_config=edge_config,
        internal_config=internal_config,
        stft_result=stft_result,
    )
    strongest_snapshot = task023c.strongest.frequency_hz.copy()
    ambiguity = branch_ambiguity_diagnostics(candidate_set, config=ambiguity_config)
    trimmed, trim_decisions = refine_trusted_core_boundaries(
        task023c.cores,
        task023c.time_s,
        ambiguity,
        config=trim_config,
    )
    mask = np.zeros(task023c.time_s.size, dtype=np.bool_)
    for core in trimmed:
        mask[core.frame_start : core.frame_end + 1] = True
    final = task023c.strongest.frequency_hz.copy()
    rank = task023c.strongest.selected_rank.copy()
    reason = ["KEEP_STRONGEST" for _ in range(final.size)]
    leading_branch: BranchDecision | None = None
    trailing_branch: BranchDecision | None = None
    leading_current: EdgeDecision | None = None
    trailing_current: EdgeDecision | None = None
    if method is SmoothBranchMethod.E1_TASK023C:
        final[:] = task023c.final_frequency_hz
        rank[:] = task023c.final_rank
        reason[:] = list(task023c.modification_reason)
    elif method is not SmoothBranchMethod.E0_KEEP_STRONGEST and trimmed:
        _apply_internal(task023c, trimmed, mask, final, rank, reason)
        if method is SmoothBranchMethod.E2_CORE_TRIM_CURRENT:
            leading_current, trailing_current = _current_edge_decisions(
                task023c,
                trimmed,
                candidate_set,
                core_config,
                edge_config,
                stft_result,
            )
            _apply_edge(leading_current, final, rank, reason)
            _apply_edge(trailing_current, final, rank, reason)
        else:
            effective = branch_config
            if method is SmoothBranchMethod.E4_CONSERVATIVE_BRANCH:
                effective = replace(
                    branch_config,
                    minimum_identity_support=max(branch_config.minimum_identity_support, 0.62),
                    minimum_local_support=max(branch_config.minimum_local_support, 0.65),
                    branch_acceptance_margin=branch_config.branch_acceptance_margin + 1.5,
                    deviation_weight=branch_config.deviation_weight * 1.5,
                )
            leading_branch = _compete_edge_branch(
                EdgeDirection.LEADING_BACKWARD,
                trimmed[0].frame_start,
                task023c,
                candidate_set,
                ambiguity,
                ambiguity_config,
                effective,
                stft_result,
            )
            trailing_branch = _compete_edge_branch(
                EdgeDirection.TRAILING_FORWARD,
                trimmed[-1].frame_end,
                task023c,
                candidate_set,
                ambiguity,
                ambiguity_config,
                effective,
                stft_result,
            )
            _apply_branch(leading_branch, final, rank, reason)
            _apply_branch(trailing_branch, final, rank, reason)
    if not np.array_equal(task023c.strongest.frequency_hz, strongest_snapshot):
        raise RuntimeError("TASK-023D mutated immutable strongest.")
    if candidate_set.candidates_by_frame != candidate_snapshot:
        raise RuntimeError("TASK-023D mutated the candidate graph.")
    if np.any(final[mask] != task023c.strongest.frequency_hz[mask]):
        raise RuntimeError("TASK-023D modified retained trusted-core frequencies.")
    if not np.all(np.isfinite(final)):
        raise RuntimeError("TASK-023D produced a silent NaN.")
    _verify_provenance(final, task023c.strongest.frequency_hz, candidate_set)
    return SmoothBranchOptimizationResult(
        method,
        task023c,
        ambiguity,
        task023c.cores,
        trimmed,
        trim_decisions,
        _immutable_bool(mask),
        _immutable_float(final),
        _immutable_int(rank),
        tuple(reason),
        leading_branch,
        trailing_branch,
        leading_current,
        trailing_current,
    )


def _candidate_persistence(
    candidate_set: RidgeCandidateSet,
    config: BranchAmbiguityConfig,
) -> tuple[list[list[int]], list[list[int]]]:
    frames = [frame[: config.maximum_candidate_rank] for frame in candidate_set.candidates_by_frame]
    backward = [[1 for _ in frame] for frame in frames]
    forward = [[1 for _ in frame] for frame in frames]
    for frame_index in range(1, len(frames)):
        dt = float(candidate_set.time_s[frame_index] - candidate_set.time_s[frame_index - 1])
        tolerance = config.link_base_hz + config.maximum_rate_hz_per_s * dt
        for index, candidate in enumerate(frames[frame_index]):
            linked = [
                backward[frame_index - 1][previous]
                for previous, item in enumerate(frames[frame_index - 1])
                if abs(candidate.transition_frequency_hz - item.transition_frequency_hz) <= tolerance
            ]
            if linked:
                backward[frame_index][index] = 1 + max(linked)
    for frame_index in range(len(frames) - 2, -1, -1):
        dt = float(candidate_set.time_s[frame_index + 1] - candidate_set.time_s[frame_index])
        tolerance = config.link_base_hz + config.maximum_rate_hz_per_s * dt
        for index, candidate in enumerate(frames[frame_index]):
            linked = [
                forward[frame_index + 1][following]
                for following, item in enumerate(frames[frame_index + 1])
                if abs(candidate.transition_frequency_hz - item.transition_frequency_hz) <= tolerance
            ]
            if linked:
                forward[frame_index][index] = 1 + max(linked)
    return backward, forward


def _context_frame_count(time_s: FloatArray, frame_index: int, duration_s: float) -> int:
    left = int(np.searchsorted(time_s, time_s[frame_index] - duration_s, side="left"))
    right = int(np.searchsorted(time_s, time_s[frame_index] + duration_s, side="right"))
    return max(right - left, 1)


def _frames_within_duration(
    time_s: FloatArray,
    start: int,
    end: int,
    duration_s: float,
    *,
    forward: bool,
) -> int:
    if forward:
        return int(np.count_nonzero(time_s[start : end + 1] - time_s[start] <= duration_s))
    return int(np.count_nonzero(time_s[end] - time_s[start : end + 1] <= duration_s))


def _trim_count(
    start: int,
    end: int,
    ambiguity: BranchAmbiguityDiagnostics,
    time_s: FloatArray,
    config: CoreTrimConfig,
    *,
    forward: bool,
    limit: int,
) -> int:
    del time_s
    if limit <= 0:
        return 0
    ordered = list(range(start, end + 1)) if forward else list(range(end, start - 1, -1))
    ordered = ordered[:limit]
    core_slice = slice(start, end + 1)
    reference_ambiguity = float(np.nanmedian(ambiguity.branch_ambiguity[core_slice]))
    reference_background = float(np.nanmedian(ambiguity.strongest_peak_to_background_db[core_slice]))
    reference_competitor = float(np.nanmedian(ambiguity.strongest_peak_to_competitor_db[core_slice]))
    review = []
    for index in ordered:
        persistent_ambiguity = (
            ambiguity.branch_ambiguity[index] >= config.ambiguity_threshold
            and ambiguity.branch_ambiguity[index]
            >= reference_ambiguity + config.minimum_ambiguity_increase
            and (
                not math.isfinite(ambiguity.strongest_vs_rank2_evidence_db[index])
                or ambiguity.strongest_vs_rank2_evidence_db[index]
                <= config.maximum_strongest_advantage_db
            )
        )
        degraded_strongest = (
            math.isfinite(ambiguity.strongest_peak_to_background_db[index])
            and math.isfinite(ambiguity.strongest_peak_to_competitor_db[index])
            and ambiguity.strongest_peak_to_background_db[index]
            <= config.degraded_background_db
            and ambiguity.strongest_peak_to_competitor_db[index]
            <= config.degraded_competitor_db
            and (
                ambiguity.strongest_peak_to_background_db[index]
                <= reference_background - config.minimum_background_drop_db
                or ambiguity.strongest_peak_to_competitor_db[index]
                <= reference_competitor - config.minimum_competitor_drop_db
            )
        )
        review.append(bool(persistent_ambiguity or degraded_strongest))
    if not review or not review[0]:
        return 0
    trim = 0
    gaps = 0
    reviewed = 0
    for is_reviewable in review:
        reviewed += 1
        if is_reviewable:
            gaps = 0
        else:
            gaps += 1
            if gaps > config.maximum_unambiguous_gap_frames:
                break
        if sum(review[:reviewed]) / reviewed >= config.minimum_edge_review_fraction:
            trim = reviewed
    return trim


def _apply_internal(
    task023c: TrustedCoreOptimizationResult,
    cores: tuple[TrustedCore, ...],
    core_mask: BoolArray,
    final: FloatArray,
    rank: IntArray,
    reason: list[str],
) -> None:
    index = np.arange(final.size)
    allowed = (
        (index >= cores[0].frame_start)
        & (index <= cores[-1].frame_end)
        & ~core_mask
        & task023c.internal_result.modified_mask
    )
    final[allowed] = task023c.internal_result.final_frequency_hz[allowed]
    rank[allowed] = task023c.internal_result.final_rank[allowed]
    for frame_index in np.flatnonzero(allowed):
        reason[int(frame_index)] = "INTERNAL_DUAL_ANCHOR_RESCUE"


def _current_edge_decisions(
    task023c: TrustedCoreOptimizationResult,
    cores: tuple[TrustedCore, ...],
    candidate_set: RidgeCandidateSet,
    core_config: TrustedCoreConfig,
    edge_config: EdgeRescueConfig,
    stft_result: STFTResult | None,
) -> tuple[EdgeDecision, EdgeDecision]:
    leading = _edge_rescue(
        EdgeDirection.LEADING_BACKWARD,
        cores[0].frame_start,
        cores[0],
        task023c.strongest,
        candidate_set,
        core_config,
        edge_config,
        stft_result,
    )
    trailing = _edge_rescue(
        EdgeDirection.TRAILING_FORWARD,
        cores[-1].frame_end,
        cores[-1],
        task023c.strongest,
        candidate_set,
        core_config,
        edge_config,
        stft_result,
    )
    return leading, trailing


def _compete_edge_branch(
    direction: EdgeDirection,
    anchor_frame: int,
    task023c: TrustedCoreOptimizationResult,
    candidate_set: RidgeCandidateSet,
    ambiguity: BranchAmbiguityDiagnostics,
    ambiguity_config: BranchAmbiguityConfig,
    config: BranchCompetitionConfig,
    stft_result: STFTResult | None,
) -> BranchDecision:
    if direction is EdgeDirection.LEADING_BACKWARD:
        indices = tuple(range(anchor_frame - 1, -1, -1))
        slope_frames = np.arange(anchor_frame, min(anchor_frame + 4, task023c.time_s.size))
    else:
        indices = tuple(range(anchor_frame + 1, task023c.time_s.size))
        slope_frames = np.arange(max(0, anchor_frame - 3), anchor_frame + 1)
    if not indices:
        return _empty_branch_decision(direction, anchor_frame)
    if any(not candidate_set.candidates_by_frame[frame_index] for frame_index in indices):
        empty = _empty_branch_decision(direction, anchor_frame)
        return replace(
            empty,
            status=BranchDecisionStatus.KEEP_EVIDENCE,
            frame_start=min(indices),
            frame_end=max(indices),
        )
    anchor_slope = 0.0
    if slope_frames.size >= 2:
        anchor_slope = float(
            np.median(
                np.diff(task023c.strongest.frequency_hz[slope_frames])
                / np.diff(task023c.time_s[slope_frames])
            )
        )
    broadband = (
        _broadband_robust_z(stft_result)
        if stft_result is not None
        else np.zeros(task023c.time_s.size, dtype=np.float64)
    )
    best = _search_branch(
        indices,
        anchor_frame,
        anchor_slope,
        task023c,
        candidate_set,
        ambiguity,
        ambiguity_config,
        config,
        broadband,
    )
    baseline = _score_strongest_branch(
        indices,
        anchor_frame,
        anchor_slope,
        task023c,
        candidate_set,
        ambiguity,
        ambiguity_config,
        config,
        broadband,
    )
    score = _score_gain(baseline, best)
    changed = np.asarray(
        [
            frequency != task023c.strongest.frequency_hz[frame_index]
            for frame_index, frequency in zip(indices, best.frequencies_hz, strict=True)
        ],
        dtype=np.bool_,
    )
    acceptable = np.zeros(len(indices), dtype=np.bool_)
    stopped = False
    for offset, frame_index in enumerate(indices):
        if stopped or not changed[offset]:
            continue
        identity = best.identities[offset]
        support = best.local_supports[offset]
        elevated = broadband[frame_index] >= config.broadband_z_threshold
        if (
            identity >= config.minimum_identity_support
            and support >= config.minimum_local_support
            and (not elevated or support >= config.broadband_support_floor)
        ):
            acceptable[offset] = True
        else:
            stopped = True
    modified = int(np.count_nonzero(acceptable))
    deviation = float(
        sum(
            abs(best.frequencies_hz[offset] - task023c.strongest.frequency_hz[frame_index])
            for offset, frame_index in enumerate(indices)
            if acceptable[offset]
        )
    )
    status = BranchDecisionStatus.ACCEPTED
    if not np.any(changed):
        status = BranchDecisionStatus.KEEP_NO_ALTERNATIVE
    elif modified == 0:
        status = BranchDecisionStatus.KEEP_EVIDENCE
    elif score.branch_margin < config.branch_acceptance_margin:
        status = BranchDecisionStatus.KEEP_MARGIN
    elif (
        modified > config.maximum_modified_frames
        or modified / len(indices) > config.maximum_modified_fraction
        or deviation > config.maximum_total_deviation_hz
    ):
        status = BranchDecisionStatus.KEEP_DEVIATION_BUDGET
    if status is not BranchDecisionStatus.ACCEPTED:
        acceptable[:] = False
        modified = 0
    steps = tuple(
        _branch_step(
            offset,
            frame_index,
            best,
            task023c,
            candidate_set,
            ambiguity,
            broadband,
            bool(acceptable[offset]),
        )
        for offset, frame_index in enumerate(indices)
    )
    modified_times = [step.time_s for step in steps if step.modified]
    duration = max(modified_times) - min(modified_times) if len(modified_times) >= 2 else 0.0
    return BranchDecision(
        direction,
        status,
        anchor_frame,
        min(indices),
        max(indices),
        modified,
        float(duration),
        score,
        steps,
    )


def _initial_state(task023c: TrustedCoreOptimizationResult, anchor_frame: int, slope: float) -> _BranchState:
    return _BranchState(
        float(task023c.strongest.frequency_hz[anchor_frame]),
        slope,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        tuple(),
        tuple(),
        tuple(),
        tuple(),
        tuple(),
    )


def _search_branch(
    indices: tuple[int, ...],
    anchor_frame: int,
    anchor_slope: float,
    task023c: TrustedCoreOptimizationResult,
    candidate_set: RidgeCandidateSet,
    ambiguity: BranchAmbiguityDiagnostics,
    ambiguity_config: BranchAmbiguityConfig,
    config: BranchCompetitionConfig,
    broadband: FloatArray,
) -> _BranchState:
    states: tuple[_BranchState, ...] = (
        _initial_state(task023c, anchor_frame, anchor_slope),
    )
    previous_frame = anchor_frame
    for frame_index in indices:
        expanded: list[_BranchState] = []
        frame = candidate_set.candidates_by_frame[frame_index]
        for state in states:
            for candidate in frame:
                expanded.append(
                    _extend_branch(
                        state,
                        candidate,
                        previous_frame,
                        frame_index,
                        task023c,
                        candidate_set,
                        ambiguity,
                        ambiguity_config,
                        config,
                        broadband,
                    )
                )
        if not expanded:
            return states[0]
        states = tuple(
            sorted(
                expanded,
                key=lambda state: (state.total_cost, state.ranks, state.frequencies_hz),
            )[: config.beam_width]
        )
        previous_frame = frame_index
    return states[0]


def _score_strongest_branch(
    indices: tuple[int, ...],
    anchor_frame: int,
    anchor_slope: float,
    task023c: TrustedCoreOptimizationResult,
    candidate_set: RidgeCandidateSet,
    ambiguity: BranchAmbiguityDiagnostics,
    ambiguity_config: BranchAmbiguityConfig,
    config: BranchCompetitionConfig,
    broadband: FloatArray,
) -> _BranchState:
    state = _initial_state(task023c, anchor_frame, anchor_slope)
    previous_frame = anchor_frame
    for frame_index in indices:
        frame = candidate_set.candidates_by_frame[frame_index]
        candidate = frame[0]
        state = _extend_branch(
            state,
            candidate,
            previous_frame,
            frame_index,
            task023c,
            candidate_set,
            ambiguity,
            ambiguity_config,
            config,
            broadband,
        )
        previous_frame = frame_index
    return state


def _extend_branch(
    state: _BranchState,
    candidate: RidgeCandidate,
    previous_frame: int,
    frame_index: int,
    task023c: TrustedCoreOptimizationResult,
    candidate_set: RidgeCandidateSet,
    ambiguity: BranchAmbiguityDiagnostics,
    ambiguity_config: BranchAmbiguityConfig,
    config: BranchCompetitionConfig,
    broadband: FloatArray,
) -> _BranchState:
    dt = float(task023c.time_s[frame_index] - task023c.time_s[previous_frame])
    predicted = state.current_frequency_hz + state.recent_slope_hz_per_s * dt
    residual = abs(candidate.transition_frequency_hz - predicted)
    tolerance = config.link_base_hz + config.maximum_rate_hz_per_s * abs(dt)
    link_quality = math.exp(-0.5 * (residual / tolerance) ** 2)
    broken = residual > tolerance
    identity = state.identity_support * (0.10 if broken else 0.90 + 0.10 * link_quality)
    support = _rank_limited_support(
        candidate_set,
        frame_index,
        candidate.transition_frequency_hz,
        tolerance_hz=ambiguity_config.link_base_hz,
        context_frames=max(1, ambiguity_config.minimum_persistent_frames // 2),
        rank_limit=ambiguity_config.maximum_candidate_rank,
    )
    node = float(node_cost_components(candidate, candidate_set.config)["total_candidate_node_cost"])
    changed = candidate.transition_frequency_hz != task023c.strongest.frequency_hz[frame_index]
    spectral_cost = config.spectral_weight * node
    persistence_cost = config.persistence_weight * (1.0 - support)
    anchor_cost = config.identity_weight * (1.0 - identity)
    if broken:
        anchor_cost += config.identity_break_penalty
    ambiguity_cost = config.ambiguity_weight * (1.0 - ambiguity.branch_ambiguity[frame_index]) * float(changed)
    elevated = max(float(broadband[frame_index] - config.broadband_z_threshold), 0.0)
    broadband_cost = config.broadband_weight * min(elevated, 10.0) * float(changed)
    deviation = abs(candidate.transition_frequency_hz - task023c.strongest.frequency_hz[frame_index])
    deviation_cost = config.deviation_weight * deviation / 100.0e6
    incremental = spectral_cost + persistence_cost + anchor_cost + ambiguity_cost + broadband_cost + deviation_cost
    observed_slope = (candidate.transition_frequency_hz - state.current_frequency_hz) / dt
    slope = config.slope_memory * state.recent_slope_hz_per_s + (1.0 - config.slope_memory) * observed_slope
    return _BranchState(
        candidate.transition_frequency_hz,
        slope,
        identity,
        state.total_cost + incremental,
        state.spectral_cost + spectral_cost,
        state.persistence_cost + persistence_cost,
        state.anchor_cost + anchor_cost,
        state.ambiguity_cost + ambiguity_cost,
        state.broadband_cost + broadband_cost,
        state.deviation_cost + deviation_cost,
        (*state.frequencies_hz, float(candidate.transition_frequency_hz)),
        (*state.ranks, candidate.candidate_rank),
        (*state.identities, float(identity)),
        (*state.local_supports, float(support)),
        (*state.increments, (spectral_cost, persistence_cost, anchor_cost, ambiguity_cost, broadband_cost, deviation_cost)),
    )


def _score_gain(baseline: _BranchState, proposal: _BranchState) -> BranchScoreComponents:
    return BranchScoreComponents(
        baseline.spectral_cost - proposal.spectral_cost,
        baseline.persistence_cost - proposal.persistence_cost,
        baseline.anchor_cost - proposal.anchor_cost,
        baseline.ambiguity_cost - proposal.ambiguity_cost,
        proposal.broadband_cost - baseline.broadband_cost,
        proposal.deviation_cost,
        baseline.total_cost - proposal.total_cost,
    )


def _branch_step(
    offset: int,
    frame_index: int,
    state: _BranchState,
    task023c: TrustedCoreOptimizationResult,
    candidate_set: RidgeCandidateSet,
    ambiguity: BranchAmbiguityDiagnostics,
    broadband: FloatArray,
    modified: bool,
) -> BranchStepAudit:
    spectral, persistence, anchor, ambiguous, broadband_cost, deviation = state.increments[offset]
    return BranchStepAudit(
        frame_index,
        float(task023c.time_s[frame_index]),
        float(task023c.strongest.frequency_hz[frame_index]),
        state.frequencies_hz[offset],
        int(task023c.strongest.selected_rank[frame_index]),
        state.ranks[offset],
        state.identities[offset],
        state.local_supports[offset],
        int(ambiguity.persistent_branch_count[frame_index]),
        float(ambiguity.branch_ambiguity[frame_index]),
        spectral,
        persistence,
        anchor,
        ambiguous,
        broadband_cost,
        deviation,
        float(broadband[frame_index]),
        modified,
    )


def _empty_branch_decision(direction: EdgeDirection, anchor_frame: int) -> BranchDecision:
    return BranchDecision(
        direction,
        BranchDecisionStatus.KEEP_NO_EDGE,
        anchor_frame,
        anchor_frame,
        anchor_frame,
        0,
        0.0,
        BranchScoreComponents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        tuple(),
    )


def _apply_branch(
    decision: BranchDecision,
    final: FloatArray,
    rank: IntArray,
    reason: list[str],
) -> None:
    if decision.status is not BranchDecisionStatus.ACCEPTED:
        return
    for step in decision.steps:
        if not step.modified:
            continue
        final[step.frame_index] = step.proposed_frequency_hz
        rank[step.frame_index] = step.proposed_rank
        reason[step.frame_index] = f"BRANCH_COMPETITION_{decision.direction.value}"


def _verify_provenance(
    final: FloatArray,
    strongest: FloatArray,
    candidate_set: RidgeCandidateSet,
) -> None:
    for frame_index in np.flatnonzero(final != strongest):
        available = {
            candidate.transition_frequency_hz
            for candidate in candidate_set.candidates_by_frame[int(frame_index)]
        }
        if float(final[frame_index]) not in available:
            raise RuntimeError("TASK-023D output is not an existing Top-K candidate.")


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
    "BranchAmbiguityConfig",
    "BranchAmbiguityDiagnostics",
    "BranchCompetitionConfig",
    "BranchDecision",
    "BranchDecisionStatus",
    "BranchScoreComponents",
    "BranchStepAudit",
    "CoreTrimConfig",
    "CoreTrimDecision",
    "SmoothBranchMethod",
    "SmoothBranchOptimizationResult",
    "branch_ambiguity_diagnostics",
    "optimize_smooth_wrong_branches",
    "refine_trusted_core_boundaries",
]
