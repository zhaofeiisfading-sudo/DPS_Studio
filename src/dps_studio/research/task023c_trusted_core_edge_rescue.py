"""Trusted-core locked strongest optimization for TASK-023C (Research only)."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidateSet
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.time_frequency import STFTResult
from dps_studio.research.task021b_real_experiment import node_cost_components
from dps_studio.research.task021e_transition_models import robust_first_order_cost
from dps_studio.research.task023b_segment_rescue import (
    SegmentRescueConfig,
    SegmentRescueResult,
    StrongestPath,
    build_strongest_path,
    rescue_suspicious_segments,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


class EdgeDirection(str, Enum):
    """Direction and region of a single-anchor rescue."""

    LEADING_BACKWARD = "LEADING_BACKWARD"
    TRAILING_FORWARD = "TRAILING_FORWARD"


class EdgeMethod(str, Enum):
    """Required E0/E1/E2/E3 edge comparators."""

    E0_KEEP_STRONGEST = "E0_KEEP_STRONGEST"
    E1_GREEDY = "E1_GREEDY"
    E2_BEAM_B4 = "E2_BEAM_B4"
    E3_BEAM_B8 = "E3_BEAM_B8"


class EdgeStatus(str, Enum):
    """Auditable edge decision outcome."""

    ACCEPTED = "ACCEPTED"
    KEEP_NO_CORE = "KEEP_NO_CORE"
    KEEP_NO_ALTERNATIVE = "KEEP_NO_ALTERNATIVE"
    KEEP_MARGIN = "KEEP_MARGIN"
    KEEP_DEVIATION_BUDGET = "KEEP_DEVIATION_BUDGET"
    KEEP_OVERSMOOTHING_RISK = "KEEP_OVERSMOOTHING_RISK"


class EdgeQualityFlag(str, Enum):
    """Quality labels that never turn a frequency into NaN."""

    CANDIDATE_UPDATE = "CANDIDATE_UPDATE"
    LOW_CONFIDENCE_EDGE = "LOW_CONFIDENCE_EDGE"
    BROADBAND_ELEVATED = "BROADBAND_ELEVATED"
    STOP_RESCUE_FALLBACK = "STOP_RESCUE_FALLBACK"


@dataclass(frozen=True, slots=True)
class TrustedCoreConfig:
    """Synthetic-calibrated, interpretable trust thresholds."""

    trust_threshold: float = 0.62
    minimum_core_frames: int = 10
    maximum_internal_gap_frames: int = 6
    support_tolerance_hz: float = 220.0e6
    support_context_frames: int = 2
    support_rank_limit: int = 3
    minimum_support_fraction: float = 0.50
    background_low_db: float = 5.0
    background_high_db: float = 23.0
    competitor_low_db: float = -8.0
    competitor_high_db: float = 6.0
    consistency_scale_hz: float = 400.0e6
    broadband_z_scale: float = 6.0
    spectral_weight: float = 0.25
    competitor_weight: float = 0.10
    refinement_weight: float = 0.08
    support_weight: float = 0.37
    consistency_weight: float = 0.20
    broadband_penalty_weight: float = 0.12

    def __post_init__(self) -> None:
        if not 0.0 <= self.trust_threshold <= 1.0:
            raise ValueError("trust_threshold must lie in [0, 1].")
        if self.minimum_core_frames < 2 or self.maximum_internal_gap_frames < 1:
            raise ValueError("Core frame counts are invalid.")
        if self.support_tolerance_hz <= 0.0 or self.consistency_scale_hz <= 0.0:
            raise ValueError("Core physical scales must be positive.")

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"parameter": item.name, "value": getattr(self, item.name), "scope": "synthetic_only"}
            for item in fields(self)
        ]


@dataclass(frozen=True, slots=True)
class EdgeRescueConfig:
    """Synthetic-calibrated single-anchor tracking and acceptance controls."""

    frequency_scale_hz: float = 100.0e6
    huber_delta_normalized: float = 0.25
    transition_weight: float = 1.0
    node_weight: float = 0.22
    deviation_weight: float = 0.10
    slope_memory: float = 0.70
    enter_margin: float = 1.25
    exit_margin: float = -0.15
    edge_acceptance_margin: float = 1.0
    stop_patience_frames: int = 2
    minimum_background_db: float = 10.0
    minimum_competitor_db: float = -12.0
    minimum_candidate_support: float = 0.50
    broadband_z_threshold: float = 3.0
    broadband_support_floor: float = 0.75
    confidence_decay_s: float = 200.0e-9
    minimum_tracking_confidence: float = 0.16
    maximum_modified_frames: int = 48
    maximum_modified_fraction: float = 1.00
    maximum_total_deviation_normalized: float = 700.0
    oversmoothing_slope_ratio: float = 0.35
    fast_slope_hz_per_s: float = 5.0e15

    def __post_init__(self) -> None:
        positive = (
            self.frequency_scale_hz,
            self.huber_delta_normalized,
            self.transition_weight,
            self.node_weight,
            self.confidence_decay_s,
            self.maximum_total_deviation_normalized,
            self.fast_slope_hz_per_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("Edge physical scales and weights must be positive and finite.")
        fractions = (
            self.slope_memory,
            self.minimum_candidate_support,
            self.broadband_support_floor,
            self.minimum_tracking_confidence,
            self.maximum_modified_fraction,
            self.oversmoothing_slope_ratio,
        )
        if any(not 0.0 <= value <= 1.0 for value in fractions):
            raise ValueError("Edge fractions must lie in [0, 1].")
        if self.stop_patience_frames < 1 or self.maximum_modified_frames < 1:
            raise ValueError("Edge frame limits must be positive.")
        if self.enter_margin <= self.exit_margin:
            raise ValueError("enter_margin must exceed exit_margin for hysteresis.")

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"parameter": item.name, "value": getattr(self, item.name), "scope": "synthetic_only"}
            for item in fields(self)
        ]


@dataclass(frozen=True, slots=True, eq=False)
class TrustDiagnostics:
    """Per-frame decomposed strongest trust evidence."""

    trust_score: FloatArray
    spectral_score: FloatArray
    competitor_score: FloatArray
    refinement_score: FloatArray
    candidate_support: FloatArray
    consistency_score: FloatArray
    broadband_penalty: FloatArray
    trusted_frame: BoolArray


@dataclass(frozen=True, slots=True)
class TrustedCore:
    """One locked contiguous run of strongest frames."""

    core_id: str
    frame_start: int
    frame_end: int
    start_time_s: float
    end_time_s: float
    frame_count: int
    duration_s: float
    mean_trust: float


@dataclass(frozen=True, slots=True)
class EdgeStepAudit:
    """One frame of an accepted or rejected edge proposal."""

    frame_index: int
    time_s: float
    distance_from_anchor_s: float
    original_frequency_hz: float
    proposed_frequency_hz: float
    original_rank: int
    proposed_rank: int
    candidate_peak_to_background_db: float
    candidate_peak_to_competitor_db: float
    local_candidate_support: float
    slope_consistency_cost: float
    broadband_elevated: bool
    edge_tracking_confidence: float
    local_gain: float
    modified: bool
    quality_flags: tuple[EdgeQualityFlag, ...]


@dataclass(frozen=True, slots=True)
class EdgeDecision:
    """One leading or trailing single-anchor decision."""

    direction: EdgeDirection
    status: EdgeStatus
    selected_method: EdgeMethod
    anchor_frame: int
    frame_start: int
    frame_end: int
    candidate_frame_count: int
    modified_frame_count: int
    total_deviation_hz: float
    maximum_modified_run: int
    proposal_margin: float
    stopped_early: bool
    oversmoothing_risk: bool
    steps: tuple[EdgeStepAudit, ...]


@dataclass(frozen=True, slots=True, eq=False)
class TrustedCoreOptimizationResult:
    """Immutable baseline, locked core, internal result, and final optimized path."""

    time_s: FloatArray
    strongest: StrongestPath
    trust: TrustDiagnostics
    cores: tuple[TrustedCore, ...]
    core_mask: BoolArray
    internal_result: SegmentRescueResult
    final_frequency_hz: FloatArray
    final_rank: IntArray
    modification_reason: tuple[str, ...]
    leading_decision: EdgeDecision | None
    trailing_decision: EdgeDecision | None

    @property
    def modified_mask(self) -> BoolArray:
        return np.asarray(self.final_frequency_hz != self.strongest.frequency_hz, dtype=np.bool_)

    @property
    def core_preservation_rate(self) -> float:
        if not np.any(self.core_mask):
            return math.nan
        return float(np.mean(self.final_frequency_hz[self.core_mask] == self.strongest.frequency_hz[self.core_mask]))


@dataclass(frozen=True, slots=True)
class _BeamState:
    current_frequency_hz: float
    recent_slope_hz_per_s: float
    cumulative_cost: float
    cumulative_spectral_cost: float
    cumulative_deviation_hz: float
    frequencies_hz: tuple[float, ...]
    ranks: tuple[int, ...]
    incremental_costs: tuple[float, ...]
    slope_costs: tuple[float, ...]


def optimize_trusted_core_trajectory(
    candidate_set: RidgeCandidateSet,
    *,
    core_config: TrustedCoreConfig,
    edge_config: EdgeRescueConfig,
    internal_config: SegmentRescueConfig,
    stft_result: STFTResult | None = None,
) -> TrustedCoreOptimizationResult:
    """Preserve strongest core and repair only internal gaps and one-anchor edges."""
    strongest = build_strongest_path(candidate_set, stft_result=stft_result)
    snapshot = strongest.frequency_hz.copy()
    trust, cores = identify_trusted_cores(
        strongest, candidate_set, config=core_config, stft_result=stft_result
    )
    core_mask = np.zeros(strongest.time_s.size, dtype=np.bool_)
    for core in cores:
        core_mask[core.frame_start : core.frame_end + 1] = True
    internal = rescue_suspicious_segments(
        candidate_set, config=internal_config, stft_result=stft_result
    )
    final = strongest.frequency_hz.copy()
    final_rank = strongest.selected_rank.copy()
    reason = ["KEEP_STRONGEST" for _ in range(final.size)]
    if cores:
        backbone_start = cores[0].frame_start
        backbone_end = cores[-1].frame_end
        internal_allowed = (
            (np.arange(final.size) >= backbone_start)
            & (np.arange(final.size) <= backbone_end)
            & ~core_mask
            & internal.modified_mask
        )
        final[internal_allowed] = internal.final_frequency_hz[internal_allowed]
        final_rank[internal_allowed] = internal.final_rank[internal_allowed]
        for index in np.flatnonzero(internal_allowed):
            reason[int(index)] = "INTERNAL_DUAL_ANCHOR_RESCUE"
        leading = _edge_rescue(
            EdgeDirection.LEADING_BACKWARD,
            backbone_start,
            cores[0],
            strongest,
            candidate_set,
            core_config,
            edge_config,
            stft_result,
        )
        trailing = _edge_rescue(
            EdgeDirection.TRAILING_FORWARD,
            backbone_end,
            cores[-1],
            strongest,
            candidate_set,
            core_config,
            edge_config,
            stft_result,
        )
        _apply_edge(leading, final, final_rank, reason)
        _apply_edge(trailing, final, final_rank, reason)
    else:
        leading = None
        trailing = None
    if not np.array_equal(strongest.frequency_hz, snapshot):
        raise RuntimeError("Trusted-core optimization mutated StrongestPath.")
    if np.any(final[core_mask] != strongest.frequency_hz[core_mask]):
        raise RuntimeError("Edge or internal rescue modified the locked trusted core.")
    if not np.all(np.isfinite(final)):
        raise RuntimeError("Trusted-core optimization produced a silent NaN.")
    _verify_candidate_provenance(final, strongest, candidate_set)
    return TrustedCoreOptimizationResult(
        _immutable_float(candidate_set.time_s),
        strongest,
        trust,
        cores,
        _immutable_bool(core_mask),
        internal,
        _immutable_float(final),
        _immutable_int(final_rank),
        tuple(reason),
        leading,
        trailing,
    )


def identify_trusted_cores(
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    *,
    config: TrustedCoreConfig,
    stft_result: STFTResult | None = None,
) -> tuple[TrustDiagnostics, tuple[TrustedCore, ...]]:
    """Find a primary high-trust backbone without treating slope magnitude as distrust."""
    count = strongest.time_s.size
    spectral = np.zeros(count, dtype=np.float64)
    competitor = np.zeros(count, dtype=np.float64)
    refinement = np.zeros(count, dtype=np.float64)
    support = np.zeros(count, dtype=np.float64)
    consistency = np.ones(count, dtype=np.float64)
    broadband = _broadband_robust_z(stft_result) if stft_result is not None else np.zeros(count)
    for index, frame in enumerate(candidate_set.candidates_by_frame):
        if not frame:
            continue
        candidate = frame[0]
        spectral[index] = _unit_interval(
            candidate.peak_to_background_db, config.background_low_db, config.background_high_db
        )
        competitor[index] = _unit_interval(
            candidate.peak_to_competitor_db, config.competitor_low_db, config.competitor_high_db
        )
        refinement[index] = float(candidate.refinement_status is RidgeRefinementStatus.REFINED)
        support[index] = _rank_limited_support(
            candidate_set,
            index,
            strongest.frequency_hz[index],
            tolerance_hz=config.support_tolerance_hz,
            context_frames=config.support_context_frames,
            rank_limit=config.support_rank_limit,
        )
    if count >= 3:
        second = np.abs(
            strongest.frequency_hz[2:]
            - 2.0 * strongest.frequency_hz[1:-1]
            + strongest.frequency_hz[:-2]
        )
        consistency[1:-1] = np.exp(-second / config.consistency_scale_hz)
        consistency[0] = consistency[1]
        consistency[-1] = consistency[-2]
    broadband_penalty = np.clip(broadband / config.broadband_z_scale, 0.0, 1.0)
    score = np.clip(
        config.spectral_weight * spectral
        + config.competitor_weight * competitor
        + config.refinement_weight * refinement
        + config.support_weight * support
        + config.consistency_weight * consistency
        - config.broadband_penalty_weight * broadband_penalty,
        0.0,
        1.0,
    )
    trusted = (score >= config.trust_threshold) & (support >= config.minimum_support_fraction)
    runs = [run for run in _true_runs(trusted) if run[1] - run[0] + 1 >= config.minimum_core_frames]
    if not runs:
        diagnostics = _trust_diagnostics(
            score, spectral, competitor, refinement, support, consistency, broadband_penalty, trusted
        )
        return diagnostics, tuple()
    primary = max(
        runs,
        key=lambda run: (
            run[1] - run[0] + 1,
            float(np.mean(score[run[0] : run[1] + 1])),
            -run[0],
        ),
    )
    selected = [primary]
    changed = True
    while changed:
        changed = False
        for run in runs:
            if run in selected or run[0] == 0 or run[1] == count - 1:
                continue
            left_gap = min(abs(run[1] - item[0]) - 1 for item in selected)
            right_gap = min(abs(item[1] - run[0]) - 1 for item in selected)
            if min(left_gap, right_gap) <= config.maximum_internal_gap_frames:
                selected.append(run)
                changed = True
    selected.sort()
    core_values = tuple(
        TrustedCore(
            f"CORE_{number:02d}",
            start,
            end,
            float(strongest.time_s[start]),
            float(strongest.time_s[end]),
            end - start + 1,
            float(strongest.time_s[end] - strongest.time_s[start]),
            float(np.mean(score[start : end + 1])),
        )
        for number, (start, end) in enumerate(selected, start=1)
    )
    diagnostics = _trust_diagnostics(
        score, spectral, competitor, refinement, support, consistency, broadband_penalty, trusted
    )
    return diagnostics, core_values


def _edge_rescue(
    direction: EdgeDirection,
    anchor_frame: int,
    core: TrustedCore,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    core_config: TrustedCoreConfig,
    config: EdgeRescueConfig,
    stft_result: STFTResult | None,
) -> EdgeDecision:
    if direction is EdgeDirection.LEADING_BACKWARD:
        indices = tuple(range(anchor_frame - 1, -1, -1))
    else:
        indices = tuple(range(anchor_frame + 1, strongest.time_s.size))
    if not indices:
        return EdgeDecision(
            direction,
            EdgeStatus.KEEP_NO_ALTERNATIVE,
            EdgeMethod.E0_KEEP_STRONGEST,
            anchor_frame,
            anchor_frame,
            anchor_frame,
            0,
            0,
            0.0,
            0,
            0.0,
            False,
            False,
            tuple(),
        )
    anchor_slope = _anchor_slope(direction, anchor_frame, core, strongest)
    baseline = _follow_fixed_strongest(indices, anchor_frame, anchor_slope, strongest, candidate_set, config)
    proposals = [
        _beam_proposal(indices, anchor_frame, anchor_slope, strongest, candidate_set, config, width)
        for width in (1, 4, 8)
    ]
    methods = (EdgeMethod.E1_GREEDY, EdgeMethod.E2_BEAM_B4, EdgeMethod.E3_BEAM_B8)
    evaluated = [
        _gate_edge_proposal(
            direction,
            method,
            indices,
            anchor_frame,
            baseline,
            proposal,
            strongest,
            candidate_set,
            core_config,
            config,
            stft_result,
        )
        for method, proposal in zip(methods, proposals, strict=True)
    ]
    return max(
        evaluated,
        key=lambda item: (
            item.status is EdgeStatus.ACCEPTED,
            item.proposal_margin,
            -item.modified_frame_count,
            -list(EdgeMethod).index(item.selected_method),
        ),
    )


def _beam_proposal(
    indices: tuple[int, ...],
    anchor_frame: int,
    anchor_slope: float,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: EdgeRescueConfig,
    width: int,
) -> _BeamState:
    states: tuple[_BeamState, ...] = (
        _BeamState(
            float(strongest.frequency_hz[anchor_frame]),
            anchor_slope,
            0.0,
            0.0,
            0.0,
            tuple(),
            tuple(),
            tuple(),
            tuple(),
        ),
    )
    previous_frame = anchor_frame
    for frame_index in indices:
        dt = float(strongest.time_s[frame_index] - strongest.time_s[previous_frame])
        candidates = candidate_set.candidates_by_frame[frame_index]
        expanded: list[_BeamState] = []
        for state in states:
            if not candidates:
                expanded.append(
                    _extend_state(
                        state,
                        strongest.frequency_hz[frame_index],
                        0,
                        0.0,
                        strongest.frequency_hz[frame_index],
                        dt,
                        config,
                    )
                )
                continue
            for candidate in candidates:
                spectral_cost = float(
                    node_cost_components(candidate, candidate_set.config)["total_candidate_node_cost"]
                )
                expanded.append(
                    _extend_state(
                        state,
                        candidate.transition_frequency_hz,
                        candidate.candidate_rank,
                        spectral_cost,
                        strongest.frequency_hz[frame_index],
                        dt,
                        config,
                    )
                )
        states = tuple(
            sorted(
                expanded,
                key=lambda item: (item.cumulative_cost, item.ranks, item.frequencies_hz),
            )[:width]
        )
        previous_frame = frame_index
    return states[0]


def _follow_fixed_strongest(
    indices: tuple[int, ...],
    anchor_frame: int,
    anchor_slope: float,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: EdgeRescueConfig,
) -> _BeamState:
    state = _BeamState(
        float(strongest.frequency_hz[anchor_frame]),
        anchor_slope,
        0.0,
        0.0,
        0.0,
        tuple(),
        tuple(),
        tuple(),
        tuple(),
    )
    previous_frame = anchor_frame
    for frame_index in indices:
        frame = candidate_set.candidates_by_frame[frame_index]
        candidate = frame[0] if frame else None
        spectral_cost = (
            float(node_cost_components(candidate, candidate_set.config)["total_candidate_node_cost"])
            if candidate is not None
            else 0.0
        )
        dt = float(strongest.time_s[frame_index] - strongest.time_s[previous_frame])
        state = _extend_state(
            state,
            strongest.frequency_hz[frame_index],
            strongest.selected_rank[frame_index],
            spectral_cost,
            strongest.frequency_hz[frame_index],
            dt,
            config,
        )
        previous_frame = frame_index
    return state


def _extend_state(
    state: _BeamState,
    frequency_hz: float,
    rank: int,
    spectral_cost: float,
    strongest_hz: float,
    dt_s: float,
    config: EdgeRescueConfig,
) -> _BeamState:
    predicted = state.current_frequency_hz + state.recent_slope_hz_per_s * dt_s
    residual = frequency_hz - predicted
    transition = config.transition_weight * robust_first_order_cost(
        residual,
        config=GlobalPathConfig(frequency_step_scale_hz=config.frequency_scale_hz),
        weight=1.0,
        huber_delta_normalized=config.huber_delta_normalized,
    )
    deviation_hz = abs(frequency_hz - strongest_hz)
    incremental = (
        transition
        + config.node_weight * spectral_cost
        + config.deviation_weight * deviation_hz / config.frequency_scale_hz
    )
    observed_slope = (frequency_hz - state.current_frequency_hz) / dt_s
    slope = (
        config.slope_memory * state.recent_slope_hz_per_s
        + (1.0 - config.slope_memory) * observed_slope
    )
    return _BeamState(
        frequency_hz,
        slope,
        state.cumulative_cost + incremental,
        state.cumulative_spectral_cost + spectral_cost,
        state.cumulative_deviation_hz + deviation_hz,
        (*state.frequencies_hz, float(frequency_hz)),
        (*state.ranks, int(rank)),
        (*state.incremental_costs, float(incremental)),
        (*state.slope_costs, float(transition)),
    )


def _gate_edge_proposal(
    direction: EdgeDirection,
    method: EdgeMethod,
    indices: tuple[int, ...],
    anchor_frame: int,
    baseline: _BeamState,
    proposal: _BeamState,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    core_config: TrustedCoreConfig,
    config: EdgeRescueConfig,
    stft_result: STFTResult | None,
) -> EdgeDecision:
    broadband = _broadband_robust_z(stft_result) if stft_result is not None else np.zeros(strongest.time_s.size)
    active = False
    stopped = False
    bad_streak = 0
    accepted = np.zeros(len(indices), dtype=np.bool_)
    audits: list[EdgeStepAudit] = []
    for offset, frame_index in enumerate(indices):
        proposed_hz = proposal.frequencies_hz[offset]
        original_hz = float(strongest.frequency_hz[frame_index])
        changed = proposed_hz != original_hz
        rank = proposal.ranks[offset]
        frame = candidate_set.candidates_by_frame[frame_index]
        candidate = frame[rank - 1] if rank > 0 else None
        support = _rank_limited_support(
            candidate_set,
            frame_index,
            proposed_hz,
            tolerance_hz=core_config.support_tolerance_hz,
            context_frames=core_config.support_context_frames,
            rank_limit=core_config.support_rank_limit,
        )
        distance = abs(float(strongest.time_s[frame_index] - strongest.time_s[anchor_frame]))
        spectral_confidence = (
            _unit_interval(candidate.peak_to_background_db, config.minimum_background_db, 30.0)
            if candidate is not None
            else 0.0
        )
        confidence = float(
            np.clip(
                math.exp(-distance / config.confidence_decay_s)
                * (0.55 * support + 0.45 * spectral_confidence),
                0.0,
                1.0,
            )
        )
        elevated = bool(broadband[frame_index] >= config.broadband_z_threshold)
        evidence_ok = (
            candidate is not None
            and math.isfinite(candidate.peak_to_background_db)
            and math.isfinite(candidate.peak_to_competitor_db)
            and candidate.peak_to_background_db >= config.minimum_background_db
            and candidate.peak_to_competitor_db >= config.minimum_competitor_db
            and support >= config.minimum_candidate_support
            and (not elevated or support >= config.broadband_support_floor)
            and confidence >= config.minimum_tracking_confidence
        )
        local_gain = baseline.incremental_costs[offset] - proposal.incremental_costs[offset]
        if not stopped and changed:
            if not active and evidence_ok and local_gain >= config.enter_margin:
                active = True
                accepted[offset] = True
            elif active and evidence_ok and local_gain >= config.exit_margin:
                accepted[offset] = True
                bad_streak = 0
            elif active:
                bad_streak += 1
                if bad_streak >= config.stop_patience_frames:
                    stopped = True
        elif active and not stopped:
            bad_streak = 0
        flags: list[EdgeQualityFlag] = []
        if accepted[offset]:
            flags.append(EdgeQualityFlag.CANDIDATE_UPDATE)
        if confidence < 0.35:
            flags.append(EdgeQualityFlag.LOW_CONFIDENCE_EDGE)
        if elevated:
            flags.append(EdgeQualityFlag.BROADBAND_ELEVATED)
        if stopped:
            flags.append(EdgeQualityFlag.STOP_RESCUE_FALLBACK)
        audits.append(
            EdgeStepAudit(
                frame_index,
                float(strongest.time_s[frame_index]),
                distance,
                original_hz,
                proposed_hz,
                int(strongest.selected_rank[frame_index]),
                int(rank),
                math.nan if candidate is None else candidate.peak_to_background_db,
                math.nan if candidate is None else candidate.peak_to_competitor_db,
                support,
                proposal.slope_costs[offset],
                elevated,
                confidence,
                local_gain,
                bool(accepted[offset]),
                tuple(flags),
            )
        )
    modified = int(np.count_nonzero(accepted))
    total_deviation = float(
        sum(
            abs(proposal.frequencies_hz[index] - strongest.frequency_hz[frame_index])
            for index, frame_index in enumerate(indices)
            if accepted[index]
        )
    )
    margin = float(
        sum(
            baseline.incremental_costs[index] - proposal.incremental_costs[index]
            for index in range(len(indices))
            if accepted[index]
        )
    )
    max_run = _maximum_true_run(accepted)
    oversmoothing = _edge_oversmoothing(indices, accepted, proposal, strongest, candidate_set, config)
    status = EdgeStatus.ACCEPTED
    if modified == 0:
        status = EdgeStatus.KEEP_NO_ALTERNATIVE
    elif (
        modified > config.maximum_modified_frames
        or modified / len(indices) > config.maximum_modified_fraction
        or total_deviation / config.frequency_scale_hz > config.maximum_total_deviation_normalized
    ):
        status = EdgeStatus.KEEP_DEVIATION_BUDGET
    elif oversmoothing:
        status = EdgeStatus.KEEP_OVERSMOOTHING_RISK
    elif margin < config.edge_acceptance_margin:
        status = EdgeStatus.KEEP_MARGIN
    if status is not EdgeStatus.ACCEPTED:
        audits = [replace(item, modified=False) for item in audits]
        modified = 0
    return EdgeDecision(
        direction,
        status,
        method,
        anchor_frame,
        min(indices),
        max(indices),
        len(indices),
        modified,
        total_deviation,
        max_run,
        margin,
        stopped,
        oversmoothing,
        tuple(audits),
    )


def _edge_oversmoothing(
    indices: tuple[int, ...],
    accepted: BoolArray,
    proposal: _BeamState,
    strongest: StrongestPath,
    candidate_set: RidgeCandidateSet,
    config: EdgeRescueConfig,
) -> bool:
    selected = np.flatnonzero(accepted)
    if selected.size < 3:
        return False
    chronological = sorted((indices[int(index)], int(index)) for index in selected)
    frames = np.asarray([item[0] for item in chronological], dtype=np.int64)
    original = strongest.frequency_hz[frames]
    proposed = np.asarray([proposal.frequencies_hz[item[1]] for item in chronological])
    time_s = strongest.time_s[frames]
    if np.any(np.diff(frames) != 1) or np.any(np.diff(time_s) <= 0.0):
        return False
    original_slope = float(np.median(np.diff(original) / np.diff(time_s)))
    proposed_slope = float(np.median(np.diff(proposed) / np.diff(time_s)))
    support = np.mean(
        [
            _rank_limited_support(
                candidate_set,
                int(frame),
                float(strongest.frequency_hz[frame]),
                tolerance_hz=max(config.frequency_scale_hz, 220.0e6),
                context_frames=2,
                rank_limit=3,
            )
            for frame in frames
        ]
    )
    return bool(
        support >= 0.8
        and abs(original_slope) >= config.fast_slope_hz_per_s
        and abs(proposed_slope) < config.oversmoothing_slope_ratio * abs(original_slope)
    )


def _anchor_slope(
    direction: EdgeDirection,
    anchor_frame: int,
    core: TrustedCore,
    strongest: StrongestPath,
) -> float:
    if direction is EdgeDirection.LEADING_BACKWARD:
        end = min(core.frame_end, anchor_frame + 3)
        frames = np.arange(anchor_frame, end + 1)
    else:
        start = max(core.frame_start, anchor_frame - 3)
        frames = np.arange(start, anchor_frame + 1)
    if frames.size < 2:
        return 0.0
    return float(
        np.median(
            np.diff(strongest.frequency_hz[frames]) / np.diff(strongest.time_s[frames])
        )
    )


def _apply_edge(
    decision: EdgeDecision,
    final: FloatArray,
    final_rank: IntArray,
    reason: list[str],
) -> None:
    if decision.status is not EdgeStatus.ACCEPTED:
        return
    for step in decision.steps:
        if not step.modified:
            continue
        final[step.frame_index] = step.proposed_frequency_hz
        final_rank[step.frame_index] = step.proposed_rank
        reason[step.frame_index] = decision.direction.value


def _verify_candidate_provenance(
    final: FloatArray, strongest: StrongestPath, candidate_set: RidgeCandidateSet
) -> None:
    for index in np.flatnonzero(final != strongest.frequency_hz):
        available = {
            candidate.transition_frequency_hz
            for candidate in candidate_set.candidates_by_frame[int(index)]
        }
        if float(final[index]) not in available:
            raise RuntimeError("Optimized edge frequency is not an existing Top-K candidate.")


def _trust_diagnostics(
    score: FloatArray,
    spectral: FloatArray,
    competitor: FloatArray,
    refinement: FloatArray,
    support: FloatArray,
    consistency: FloatArray,
    broadband: FloatArray,
    trusted: BoolArray,
) -> TrustDiagnostics:
    return TrustDiagnostics(
        _immutable_float(score),
        _immutable_float(spectral),
        _immutable_float(competitor),
        _immutable_float(refinement),
        _immutable_float(support),
        _immutable_float(consistency),
        _immutable_float(broadband),
        _immutable_bool(trusted),
    )


def _unit_interval(value: float, low: float, high: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def _rank_limited_support(
    candidate_set: RidgeCandidateSet,
    frame_index: int,
    frequency_hz: float,
    *,
    tolerance_hz: float,
    context_frames: int,
    rank_limit: int,
) -> float:
    found = 0
    total = 0
    start = max(0, frame_index - context_frames)
    end = min(len(candidate_set.candidates_by_frame), frame_index + context_frames + 1)
    for neighbor in range(start, end):
        if neighbor == frame_index:
            continue
        total += 1
        if any(
            candidate.candidate_rank <= rank_limit
            and abs(candidate.transition_frequency_hz - frequency_hz) <= tolerance_hz
            for candidate in candidate_set.candidates_by_frame[neighbor]
        ):
            found += 1
    return found / total if total else 0.0


def _broadband_robust_z(stft_result: STFTResult) -> FloatArray:
    power = np.sum(np.square(np.abs(stft_result.spectrum)), axis=0)
    median = float(np.median(power))
    mad = float(np.median(np.abs(power - median)))
    scale = max(1.4826 * mad, np.finfo(np.float64).eps * max(abs(median), 1.0))
    return np.asarray((power - median) / scale, dtype=np.float64)


def _close_short_false_gaps(mask: BoolArray, maximum_gap: int) -> BoolArray:
    result = np.array(mask, dtype=np.bool_, copy=True)
    for start, end in _false_runs(result):
        if start > 0 and end + 1 < result.size and end - start + 1 <= maximum_gap:
            result[start : end + 1] = True
    return result


def _true_runs(mask: BoolArray) -> list[tuple[int, int]]:
    return _runs(mask, True)


def _false_runs(mask: BoolArray) -> list[tuple[int, int]]:
    return _runs(mask, False)


def _runs(mask: BoolArray, value: bool) -> list[tuple[int, int]]:
    selected = np.flatnonzero(mask == value)
    if selected.size == 0:
        return []
    result: list[tuple[int, int]] = []
    start = end = int(selected[0])
    for raw in selected[1:]:
        index = int(raw)
        if index == end + 1:
            end = index
        else:
            result.append((start, end))
            start = end = index
    result.append((start, end))
    return result


def _maximum_true_run(mask: BoolArray) -> int:
    return max((end - start + 1 for start, end in _true_runs(mask)), default=0)


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
    "EdgeDecision",
    "EdgeDirection",
    "EdgeMethod",
    "EdgeQualityFlag",
    "EdgeRescueConfig",
    "EdgeStatus",
    "EdgeStepAudit",
    "TrustDiagnostics",
    "TrustedCore",
    "TrustedCoreConfig",
    "TrustedCoreOptimizationResult",
    "identify_trusted_cores",
    "optimize_trusted_core_trajectory",
]
