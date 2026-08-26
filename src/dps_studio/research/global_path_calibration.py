"""Research-only audit and calibration helpers for Global Candidate Path."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import (
    GlobalPathConfig,
    GlobalRidgePathResult,
    RidgeCandidate,
    RidgeCandidateSet,
    candidate_node_cost,
    candidate_transition_cost,
)
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


@dataclass(frozen=True)
class GlobalPathCostAudit:
    """All DP state costs needed to explain candidate-versus-NULL competition.

    Each frame orders states as retained candidates by rank, followed by NULL.
    Costs are calculated with the same recurrence, ordering, and ``argmin``
    tie-breaking as the public solver; this module does not alter that solver.
    """

    candidate_set: RidgeCandidateSet
    node_costs_by_frame: tuple[FloatArray, ...]
    transition_costs_by_frame: tuple[FloatArray, ...]
    cumulative_costs_by_frame: tuple[FloatArray, ...]
    predecessor_indices_by_frame: tuple[IntArray, ...]
    selected_state_indices: IntArray
    candidate_vs_null_cost_margin: FloatArray

    @property
    def frame_states(self) -> tuple[tuple[RidgeCandidate | None, ...], ...]:
        """Return candidates followed by the explicit NULL state for every frame."""
        return tuple(
            (*frame, None) for frame in self.candidate_set.candidates_by_frame
        )


@dataclass(frozen=True)
class CalibrationMetrics:
    """Comparable, source-agnostic metrics for one dataset/profile/configuration."""

    frame_count: int
    average_retained_candidate_count: float
    candidate_available_fraction: float
    null_fraction: float
    rank_1_fraction: float
    rank_2_fraction: float
    rank_3_fraction: float
    rank_4_plus_fraction: float
    refinement_success_fraction: float
    production_disagreement_fraction: float
    pre_event_non_null_fraction: float
    longest_continuous_selected_segment: int
    null_candidate_transition_count: int
    median_candidate_vs_null_cost_margin: float
    candidate_vs_null_margin_p10: float
    candidate_vs_null_margin_p90: float

    def to_metadata(self) -> dict[str, int | float]:
        """Return one CSV/JSON-compatible row."""
        return {
            "frame_count": self.frame_count,
            "average_retained_candidate_count": self.average_retained_candidate_count,
            "candidate_available_fraction": self.candidate_available_fraction,
            "null_fraction": self.null_fraction,
            "rank_1_fraction": self.rank_1_fraction,
            "rank_2_fraction": self.rank_2_fraction,
            "rank_3_fraction": self.rank_3_fraction,
            "rank_4_plus_fraction": self.rank_4_plus_fraction,
            "refinement_success_fraction": self.refinement_success_fraction,
            "production_disagreement_fraction": self.production_disagreement_fraction,
            "pre_event_non_null_fraction": self.pre_event_non_null_fraction,
            "longest_continuous_selected_segment": self.longest_continuous_selected_segment,
            "null_candidate_transition_count": self.null_candidate_transition_count,
            "median_candidate_vs_null_cost_margin": self.median_candidate_vs_null_cost_margin,
            "candidate_vs_null_margin_p10": self.candidate_vs_null_margin_p10,
            "candidate_vs_null_margin_p90": self.candidate_vs_null_margin_p90,
        }


def research_aggressiveness_presets(
    *,
    top_k: int,
) -> dict[str, GlobalPathConfig]:
    """Return small, auditable candidate-vs-NULL research calibrations.

    Conservative exactly reproduces TASK-021A. The other two presets alter
    only the cost terms audited as direct NULL preference: NULL node cost and
    entry/exit costs. Candidate extraction, node-evidence definitions,
    continuity form, and every Production configuration remain unchanged.
    """
    conservative = GlobalPathConfig(top_k=top_k)
    return {
        "conservative": conservative,
        "balanced": replace(
            conservative,
            null_node_cost=0.45,
            ridge_entry_cost=2.25,
            ridge_exit_cost=2.25,
        ),
        "permissive": replace(
            conservative,
            null_node_cost=0.65,
            ridge_entry_cost=1.5,
            ridge_exit_cost=1.5,
        ),
    }


def candidate_set_for_top_k(
    candidate_set: RidgeCandidateSet,
    *,
    config: GlobalPathConfig,
) -> RidgeCandidateSet:
    """Derive an exact lower-K prefix from a fixed maximum-K extraction."""
    if config.top_k > candidate_set.config.top_k:
        raise ValueError("Calibration config cannot exceed extracted candidate top_k.")
    return RidgeCandidateSet(
        time_s=candidate_set.time_s,
        candidates_by_frame=tuple(
            frame[: config.top_k] for frame in candidate_set.candidates_by_frame
        ),
        minimum_frequency_hz=candidate_set.minimum_frequency_hz,
        maximum_frequency_hz=candidate_set.maximum_frequency_hz,
        effective_candidate_separation_hz=(
            candidate_set.effective_candidate_separation_hz
        ),
        effective_background_exclusion_half_width_hz=(
            candidate_set.effective_background_exclusion_half_width_hz
        ),
        config=config,
        source_path=candidate_set.source_path,
    )


def audit_global_candidate_path(candidate_set: RidgeCandidateSet) -> GlobalPathCostAudit:
    """Recompute each DP state cost for Research diagnostics only."""
    config = candidate_set.config
    frame_states = tuple(
        (*frame, None) for frame in candidate_set.candidates_by_frame
    )
    node_by_frame: list[FloatArray] = []
    transition_by_frame: list[FloatArray] = []
    cumulative_by_frame: list[FloatArray] = []
    predecessor_by_frame: list[IntArray] = []

    for frame_index, states in enumerate(frame_states):
        node_costs = np.fromiter(
            (
                config.null_node_cost
                if state is None
                else candidate_node_cost(state, config)
                for state in states
            ),
            dtype=np.float64,
            count=len(states),
        )
        if frame_index == 0:
            transition_costs = np.fromiter(
                (
                    config.null_stay_cost
                    if state is None
                    else config.ridge_entry_cost
                    for state in states
                ),
                dtype=np.float64,
                count=len(states),
            )
            predecessors = np.full(len(states), -1, dtype=np.int64)
            cumulative = node_costs + transition_costs
        else:
            previous_states = frame_states[frame_index - 1]
            previous_cumulative = cumulative_by_frame[-1]
            transition_costs = np.empty(len(states), dtype=np.float64)
            predecessors = np.empty(len(states), dtype=np.int64)
            cumulative = np.empty(len(states), dtype=np.float64)
            for state_index, state in enumerate(states):
                alternatives = np.fromiter(
                    (
                        previous_cumulative[previous_index]
                        + _transition_cost(previous_state, state, config)
                        for previous_index, previous_state in enumerate(previous_states)
                    ),
                    dtype=np.float64,
                    count=len(previous_states),
                )
                predecessor = int(np.argmin(alternatives))
                predecessors[state_index] = predecessor
                transition_costs[state_index] = _transition_cost(
                    previous_states[predecessor],
                    state,
                    config,
                )
                cumulative[state_index] = node_costs[state_index] + alternatives[predecessor]
        node_by_frame.append(node_costs)
        transition_by_frame.append(transition_costs)
        cumulative_by_frame.append(cumulative)
        predecessor_by_frame.append(predecessors)

    selected_state_indices = np.empty(len(frame_states), dtype=np.int64)
    selected_state_indices[-1] = int(np.argmin(cumulative_by_frame[-1]))
    for frame_index in range(len(frame_states) - 1, 0, -1):
        selected_state_indices[frame_index - 1] = predecessor_by_frame[frame_index][
            selected_state_indices[frame_index]
        ]
    margin = np.full(len(frame_states), np.nan, dtype=np.float64)
    for frame_index, frame in enumerate(candidate_set.candidates_by_frame):
        if frame:
            margin[frame_index] = (
                float(np.min(cumulative_by_frame[frame_index][:-1]))
                - float(cumulative_by_frame[frame_index][-1])
            )
    return GlobalPathCostAudit(
        candidate_set=candidate_set,
        node_costs_by_frame=tuple(node_by_frame),
        transition_costs_by_frame=tuple(transition_by_frame),
        cumulative_costs_by_frame=tuple(cumulative_by_frame),
        predecessor_indices_by_frame=tuple(predecessor_by_frame),
        selected_state_indices=selected_state_indices,
        candidate_vs_null_cost_margin=margin,
    )


def audit_matches_global_path_result(
    audit: GlobalPathCostAudit,
    result: GlobalRidgePathResult,
) -> bool:
    """Check that an audit follows the public solver's selected recurrence."""
    if audit.candidate_set is not result.candidate_set:
        return False
    selected_cumulative = np.fromiter(
        (
            audit.cumulative_costs_by_frame[frame_index][state_index]
            for frame_index, state_index in enumerate(audit.selected_state_indices)
        ),
        dtype=np.float64,
        count=result.time_s.size,
    )
    selected_rank = np.fromiter(
        (
            _state_rank(audit.candidate_set.candidates_by_frame[frame_index], state_index)
            for frame_index, state_index in enumerate(audit.selected_state_indices)
        ),
        dtype=np.int64,
        count=result.time_s.size,
    )
    return bool(
        np.array_equal(selected_rank, result.selected_candidate_rank)
        and np.allclose(selected_cumulative, result.cumulative_cost, rtol=1.0e-12, atol=1.0e-12)
    )


def audit_rows(audit: GlobalPathCostAudit) -> list[dict[str, Any]]:
    """Flatten every candidate and NULL state into an auditable CSV table."""
    rows: list[dict[str, Any]] = []
    states_by_frame = audit.frame_states
    for frame_index, states in enumerate(states_by_frame):
        selected_index = int(audit.selected_state_indices[frame_index])
        selected_predecessor = int(audit.predecessor_indices_by_frame[frame_index][selected_index])
        best_candidate_cumulative = (
            float(np.min(audit.cumulative_costs_by_frame[frame_index][:-1]))
            if len(states) > 1
            else math.nan
        )
        null_node_cost = float(audit.node_costs_by_frame[frame_index][-1])
        null_transition_cost = float(audit.transition_costs_by_frame[frame_index][-1])
        null_cumulative = float(audit.cumulative_costs_by_frame[frame_index][-1])
        for state_index, state in enumerate(states):
            predecessor_index = int(audit.predecessor_indices_by_frame[frame_index][state_index])
            row = _state_row(
                frame_index=frame_index,
                time_s=float(audit.candidate_set.time_s[frame_index]),
                state=state,
                state_index=state_index,
                node_cost=float(audit.node_costs_by_frame[frame_index][state_index]),
                transition_cost=float(
                    audit.transition_costs_by_frame[frame_index][state_index]
                ),
                cumulative_cost=float(
                    audit.cumulative_costs_by_frame[frame_index][state_index]
                ),
                predecessor_state=_state_label(
                    states_by_frame,
                    frame_index - 1,
                    predecessor_index,
                ),
            )
            row.update(
                {
                    "best_candidate_cumulative_cost": best_candidate_cumulative,
                    "null_node_cost": null_node_cost,
                    "null_transition_cost": null_transition_cost,
                    "null_cumulative_cost": null_cumulative,
                    "candidate_node_cost": (
                        math.nan
                        if state is None
                        else float(audit.node_costs_by_frame[frame_index][state_index])
                    ),
                    "candidate_transition_cost": (
                        math.nan
                        if state is None
                        else float(audit.transition_costs_by_frame[frame_index][state_index])
                    ),
                    "candidate_cumulative_cost": (
                        math.nan
                        if state is None
                        else float(audit.cumulative_costs_by_frame[frame_index][state_index])
                    ),
                    "candidate_vs_null_cost_margin": float(
                        audit.candidate_vs_null_cost_margin[frame_index]
                    ),
                    "selected_state": _state_label(
                        states_by_frame,
                        frame_index,
                        selected_index,
                    ),
                    "selected_rank": _state_rank(
                        audit.candidate_set.candidates_by_frame[frame_index],
                        selected_index,
                    ),
                    "selected_cumulative_cost": float(
                        audit.cumulative_costs_by_frame[frame_index][selected_index]
                    ),
                    "selected_winning_predecessor": _state_label(
                        states_by_frame,
                        frame_index - 1,
                        selected_predecessor,
                    ),
                    "is_selected": state_index == selected_index,
                }
            )
            rows.append(row)
    return rows


def calibration_metrics(
    *,
    result: GlobalRidgePathResult,
    audit: GlobalPathCostAudit,
    production_frequency_hz: FloatArray,
    pre_event_reference_time_s: float | None,
) -> CalibrationMetrics:
    """Summarize one DP result without treating more output as improvement."""
    if not audit_matches_global_path_result(audit, result):
        raise ValueError("Cost audit does not match the supplied global-path result.")
    frame_count = result.time_s.size
    selected = ~result.is_null
    ranks = result.selected_candidate_rank
    candidate_counts = np.fromiter(
        (len(frame) for frame in result.candidate_set.candidates_by_frame),
        dtype=np.float64,
        count=frame_count,
    )
    refinement_success = selected & np.isfinite(result.selected_refined_frequency_hz)
    production = np.asarray(production_frequency_hz, dtype=np.float64)
    if production.shape != result.time_s.shape:
        raise ValueError("production_frequency_hz must match the path time axis.")
    production_finite = np.isfinite(production)
    global_finite = np.isfinite(result.selected_refined_frequency_hz)
    disagreement = (production_finite != global_finite) | (
        production_finite
        & global_finite
        & (np.abs(production - result.selected_refined_frequency_hz) > 1.0e6)
    )
    pre_event = (
        result.time_s < pre_event_reference_time_s
        if pre_event_reference_time_s is not None
        else np.zeros(frame_count, dtype=np.bool_)
    )
    margins = audit.candidate_vs_null_cost_margin
    finite_margins = margins[np.isfinite(margins)]
    return CalibrationMetrics(
        frame_count=frame_count,
        average_retained_candidate_count=float(np.mean(candidate_counts)),
        candidate_available_fraction=float(np.mean(candidate_counts > 0.0)),
        null_fraction=float(np.mean(result.is_null)),
        rank_1_fraction=float(np.mean(ranks == 1)),
        rank_2_fraction=float(np.mean(ranks == 2)),
        rank_3_fraction=float(np.mean(ranks == 3)),
        rank_4_plus_fraction=float(np.mean(ranks >= 4)),
        refinement_success_fraction=float(np.mean(refinement_success)),
        production_disagreement_fraction=float(np.mean(disagreement)),
        pre_event_non_null_fraction=(
            float(np.mean(selected[pre_event])) if np.any(pre_event) else math.nan
        ),
        longest_continuous_selected_segment=_longest_true_run(selected),
        null_candidate_transition_count=int(np.count_nonzero(np.diff(result.is_null))),
        median_candidate_vs_null_cost_margin=(
            float(np.median(finite_margins)) if finite_margins.size else math.nan
        ),
        candidate_vs_null_margin_p10=(
            float(np.quantile(finite_margins, 0.1)) if finite_margins.size else math.nan
        ),
        candidate_vs_null_margin_p90=(
            float(np.quantile(finite_margins, 0.9)) if finite_margins.size else math.nan
        ),
    )


def _transition_cost(
    previous: RidgeCandidate | None,
    current: RidgeCandidate | None,
    config: GlobalPathConfig,
) -> float:
    if previous is None and current is None:
        return config.null_stay_cost
    if previous is None:
        return config.ridge_entry_cost
    if current is None:
        return config.ridge_exit_cost
    return candidate_transition_cost(previous, current, config)


def _state_rank(frame: tuple[RidgeCandidate, ...], state_index: int) -> int:
    return 0 if state_index == len(frame) else frame[state_index].candidate_rank


def _state_label(
    states_by_frame: tuple[tuple[RidgeCandidate | None, ...], ...],
    frame_index: int,
    state_index: int,
) -> str:
    if frame_index < 0 or state_index < 0:
        return "initial"
    state = states_by_frame[frame_index][state_index]
    return "NULL" if state is None else f"rank_{state.candidate_rank}"


def _state_row(
    *,
    frame_index: int,
    time_s: float,
    state: RidgeCandidate | None,
    state_index: int,
    node_cost: float,
    transition_cost: float,
    cumulative_cost: float,
    predecessor_state: str,
) -> dict[str, Any]:
    if state is None:
        return {
            "frame_index": frame_index,
            "time_s": time_s,
            "state_type": "NULL",
            "state_index": state_index,
            "candidate_rank": 0,
            "discrete_frequency_hz": math.nan,
            "refined_frequency_hz": math.nan,
            "peak_amplitude": math.nan,
            "peak_to_background_db": math.nan,
            "peak_to_competitor_db": math.nan,
            "cycles_in_window": math.nan,
            "is_band_boundary": False,
            "refinement_status": "NULL",
            "node_cost": node_cost,
            "winning_predecessor": predecessor_state,
            "transition_cost": transition_cost,
            "cumulative_cost": cumulative_cost,
        }
    return {
        "frame_index": frame_index,
        "time_s": state.time_s,
        "state_type": "candidate",
        "state_index": state_index,
        "candidate_rank": state.candidate_rank,
        "discrete_frequency_hz": state.discrete_frequency_hz,
        "refined_frequency_hz": state.refined_frequency_hz,
        "peak_amplitude": state.peak_amplitude,
        "peak_to_background_db": state.peak_to_background_db,
        "peak_to_competitor_db": state.peak_to_competitor_db,
        "cycles_in_window": state.cycles_in_window,
        "is_band_boundary": state.is_band_boundary,
        "refinement_status": state.refinement_status.value,
        "node_cost": node_cost,
        "winning_predecessor": predecessor_state,
        "transition_cost": transition_cost,
        "cumulative_cost": cumulative_cost,
    }


def _longest_true_run(values: Iterable[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


__all__ = [
    "CalibrationMetrics",
    "GlobalPathCostAudit",
    "audit_global_candidate_path",
    "audit_matches_global_path_result",
    "audit_rows",
    "calibration_metrics",
    "candidate_set_for_top_k",
    "research_aggressiveness_presets",
]
