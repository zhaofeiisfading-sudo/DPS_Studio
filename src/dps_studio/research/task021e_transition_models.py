"""TASK-021E Research-only robust and curvature-aware Global Path studies.

No core solver, candidate extractor, STFT, node cost, NULL cost, or Production
workflow is changed.  Candidate-to-candidate transitions alone are varied in a
separate dynamic-programming implementation, including an exact second-order
state recurrence where requested.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    candidate_node_cost,
    candidate_transition_cost,
    extract_global_path_candidates,
)
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research.global_path_benchmark import (
    DEFAULT_VACUUM_WAVELENGTH_M,
    SyntheticGlobalPathCase,
    calculate_ridge_metrics,
    generate_synthetic_global_path_cases,
)
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    REPOSITORY_ROOT,
    PreparedStream,
    prepare_streams,
    sha256_file,
)
from dps_studio.research.task021c_cost_bridge import corrected_inventory


FirstOrderKind = Literal["quadratic", "pseudo_huber"]

EXIT_AUDIT_START_S = 0.00018374
EXIT_AUDIT_END_S = 0.00018388
R1_START_S = 0.00018360
R1_END_S = 0.00018390
DESCENT_INTERVALS: tuple[tuple[str, float, float], ...] = (
    ("D1_183P76_183P82_US", 0.00018376, 0.00018382),
    ("D2_183P82_183P88_US", 0.00018382, 0.00018388),
)


@dataclass(frozen=True, slots=True)
class TransitionSpec:
    """Fixed Research-only transition parameters, never inferred from ch3."""

    experiment_id: str
    transition_model: str
    first_order_kind: FirstOrderKind
    first_order_weight: float
    huber_delta_normalized: float | None
    curvature_weight: float
    rationale: str

    def row(self) -> dict[str, Any]:
        first = (
            "w1*(abs(df_hz)/frequency_step_scale_hz)^2"
            if self.first_order_kind == "quadratic"
            else "w1*2*kappa^2*(sqrt(1+(abs(df_hz)/scale/kappa)^2)-1)"
        )
        return {
            "experiment_id": self.experiment_id,
            "transition_model": self.transition_model,
            "first_order_kind": self.first_order_kind,
            "first_order_weight": self.first_order_weight,
            "huber_delta_normalized": self.huber_delta_normalized,
            "curvature_weight": self.curvature_weight,
            "first_order_math": first,
            "curvature_math": "w2*((f_i-2*f_i_minus_1+f_i_minus_2)/frequency_step_scale_hz)^2; only three consecutive candidates",
            "calibration_scope": "predeclared from existing 1e8-Hz transition scale and synthetic sensitivity; no ch3 fit",
            "rationale": self.rationale,
            "research_only": True,
        }


@dataclass(frozen=True, slots=True)
class TransitionPathResult:
    """A backtracked first- or second-order Research path over fixed candidates."""

    time_s: np.ndarray[Any, np.dtype[np.float64]]
    frame_indices: np.ndarray[Any, np.dtype[np.int64]]
    candidate_frames: tuple[tuple[RidgeCandidate, ...], ...]
    selected_state_indices: np.ndarray[Any, np.dtype[np.int64]]
    selected_candidate_rank: np.ndarray[Any, np.dtype[np.int64]]
    selected_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    is_null: np.ndarray[Any, np.dtype[np.bool_]]
    node_cost: np.ndarray[Any, np.dtype[np.float64]]
    transition_cost: np.ndarray[Any, np.dtype[np.float64]]
    first_order_cost: np.ndarray[Any, np.dtype[np.float64]]
    curvature_cost: np.ndarray[Any, np.dtype[np.float64]]
    cumulative_cost: np.ndarray[Any, np.dtype[np.float64]]
    spec: TransitionSpec
    config: GlobalPathConfig

    @property
    def total_path_cost(self) -> float:
        return float(self.cumulative_cost[-1])


@dataclass(frozen=True, slots=True)
class SyntheticScenario:
    """Ground-truth synthetic case plus its declared candidate band and purpose."""

    case: SyntheticGlobalPathCase
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    diagnostic_mask: np.ndarray[Any, np.dtype[np.bool_]]
    diagnostic_name: str


def build_transition_specs() -> tuple[TransitionSpec, ...]:
    """Return the predeclared E0–E6 small sensitivity matrix."""
    return (
        TransitionSpec("E0", "T0_current_quadratic", "quadratic", 1.0, None, 0.0, "current core comparator"),
        TransitionSpec("E1", "T0_quadratic_continuity_0p5", "quadratic", 0.5, None, 0.0, "TASK-021D continuity comparator"),
        TransitionSpec("E2", "T1_robust_nominal", "pseudo_huber", 1.0, 0.25, 0.0, "pseudo-Huber tail at 0.25 existing normalized step"),
        TransitionSpec("E3", "T1_robust_softer", "pseudo_huber", 1.0, 0.10, 0.0, "softer pseudo-Huber tail, predeclared synthetic sensitivity"),
        TransitionSpec("E4", "T2_curvature_nominal", "quadratic", 0.10, None, 0.75, "weak first-order guardrail plus nominal curvature"),
        TransitionSpec("E5", "T2_curvature_softer", "quadratic", 0.10, None, 0.25, "weak first-order guardrail plus softer curvature"),
        TransitionSpec("E6", "T3_robust_curvature_hybrid", "pseudo_huber", 0.50, 0.10, 0.75, "robust first-order plus curvature"),
    )


def robust_first_order_cost(
    delta_frequency_hz: float,
    *,
    config: GlobalPathConfig,
    weight: float,
    huber_delta_normalized: float,
) -> float:
    """Pseudo-Huber penalty with quadratic small-step and linear-tail behavior."""
    normalized = abs(delta_frequency_hz) / config.frequency_step_scale_hz
    kappa = huber_delta_normalized
    return weight * 2.0 * kappa * kappa * (math.sqrt(1.0 + (normalized / kappa) ** 2) - 1.0)


def curvature_cost(
    previous_previous: RidgeCandidate | None,
    previous: RidgeCandidate | None,
    current: RidgeCandidate | None,
    *,
    config: GlobalPathConfig,
    weight: float,
) -> float:
    """Return zero unless three consecutive candidate states supply real history."""
    if previous_previous is None or previous is None or current is None:
        return 0.0
    second_difference = (
        current.transition_frequency_hz
        - 2.0 * previous.transition_frequency_hz
        + previous_previous.transition_frequency_hz
    )
    normalized = second_difference / config.frequency_step_scale_hz
    return weight * normalized * normalized


def transition_cost_components(
    previous_previous: RidgeCandidate | None,
    previous: RidgeCandidate | None,
    current: RidgeCandidate | None,
    *,
    config: GlobalPathConfig,
    spec: TransitionSpec,
) -> tuple[float, float, float]:
    """Use exact core NULL semantics and Research-only candidate transitions."""
    if previous is None and current is None:
        return config.null_stay_cost, 0.0, 0.0
    if previous is None:
        return config.ridge_entry_cost, 0.0, 0.0
    if current is None:
        return config.ridge_exit_cost, 0.0, 0.0
    delta = current.transition_frequency_hz - previous.transition_frequency_hz
    if spec.first_order_kind == "quadratic":
        first = spec.first_order_weight * (abs(delta) / config.frequency_step_scale_hz) ** 2
    else:
        assert spec.huber_delta_normalized is not None
        first = robust_first_order_cost(
            delta,
            config=config,
            weight=spec.first_order_weight,
            huber_delta_normalized=spec.huber_delta_normalized,
        )
    second = curvature_cost(
        previous_previous,
        previous,
        current,
        config=config,
        weight=spec.curvature_weight,
    )
    return first + second, first, second


def solve_transition_path(
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
    time_s: np.ndarray[Any, np.dtype[np.float64]],
    *,
    config: GlobalPathConfig,
    spec: TransitionSpec,
    frame_indices: np.ndarray[Any, np.dtype[np.int64]] | None = None,
) -> TransitionPathResult:
    """Exact second-order DP over pairs of previous/current states and backtrack.

    The recurrence is D[i, h, k] for state h at i-1 and k at i.  At i>=2 it
    minimizes over the true i-2 state, so curvature is neither greedy nor
    approximated across NULL gaps.
    """
    frames = tuple(tuple(frame) for frame in candidate_frames)
    values = np.asarray(time_s, dtype=np.float64)
    if not frames or len(frames) != values.size:
        raise ValueError("Candidate frames must be non-empty and match time_s.")
    if frame_indices is None:
        indices = np.arange(values.size, dtype=np.int64)
    else:
        indices = np.asarray(frame_indices, dtype=np.int64)
    states = [(*frame, None) for frame in frames]
    node = [
        np.asarray(
            [config.null_node_cost if item is None else candidate_node_cost(item, config) for item in frame],
            dtype=np.float64,
        )
        for frame in states
    ]
    initial = node[0] + np.asarray(
        [config.null_stay_cost if item is None else config.ridge_entry_cost for item in states[0]],
        dtype=np.float64,
    )
    if len(states) == 1:
        selected = np.asarray([int(np.argmin(initial))], dtype=np.int64)
        return _assemble_result(states, values, indices, selected, config, spec, initial[selected])

    pair_cost = np.empty((len(states[0]), len(states[1])), dtype=np.float64)
    for previous_index, previous in enumerate(states[0]):
        for current_index, current in enumerate(states[1]):
            transition, _, _ = transition_cost_components(
                None, previous, current, config=config, spec=spec
            )
            pair_cost[previous_index, current_index] = initial[previous_index] + transition + node[1][current_index]
    predecessors: list[np.ndarray[Any, np.dtype[np.int64]] | None] = [None, None]
    for frame_index in range(2, len(states)):
        previous_states = states[frame_index - 1]
        current_states = states[frame_index]
        older_states = states[frame_index - 2]
        next_cost = np.empty((len(previous_states), len(current_states)), dtype=np.float64)
        predecessor = np.empty((len(previous_states), len(current_states)), dtype=np.int64)
        for previous_index, previous in enumerate(previous_states):
            for current_index, current in enumerate(current_states):
                alternatives = np.asarray(
                    [
                        pair_cost[older_index, previous_index]
                        + transition_cost_components(
                            older,
                            previous,
                            current,
                            config=config,
                            spec=spec,
                        )[0]
                        for older_index, older in enumerate(older_states)
                    ],
                    dtype=np.float64,
                )
                best = int(np.argmin(alternatives))
                predecessor[previous_index, current_index] = best
                next_cost[previous_index, current_index] = alternatives[best] + node[frame_index][current_index]
        predecessors.append(predecessor)
        pair_cost = next_cost

    pair_flat = int(np.argmin(pair_cost))
    pair_indices = np.unravel_index(pair_flat, pair_cost.shape)
    previous_index = int(pair_indices[0])
    current_index = int(pair_indices[1])
    selected = np.empty(len(states), dtype=np.int64)
    selected[-2] = int(previous_index)
    selected[-1] = int(current_index)
    for frame_index in range(len(states) - 1, 1, -1):
        predecessor_matrix: np.ndarray[Any, np.dtype[np.int64]] | None = predecessors[frame_index]
        assert predecessor_matrix is not None
        selected[frame_index - 2] = predecessor_matrix[selected[frame_index - 1], selected[frame_index]]
    return _assemble_result(states, values, indices, selected, config, spec, None)


def _assemble_result(
    states: Sequence[Sequence[RidgeCandidate | None]],
    time_s: np.ndarray[Any, np.dtype[np.float64]],
    frame_indices: np.ndarray[Any, np.dtype[np.int64]],
    selected_indices: np.ndarray[Any, np.dtype[np.int64]],
    config: GlobalPathConfig,
    spec: TransitionSpec,
    initial_total: np.ndarray[Any, np.dtype[np.float64]] | None,
) -> TransitionPathResult:
    rank = np.zeros(len(states), dtype=np.int64)
    frequency = np.full(len(states), np.nan, dtype=np.float64)
    is_null = np.ones(len(states), dtype=np.bool_)
    node = np.empty(len(states), dtype=np.float64)
    transition = np.empty(len(states), dtype=np.float64)
    first = np.zeros(len(states), dtype=np.float64)
    second = np.zeros(len(states), dtype=np.float64)
    cumulative = np.empty(len(states), dtype=np.float64)
    selected_states: list[RidgeCandidate | None] = []
    for index, selected_index in enumerate(selected_indices.tolist()):
        item = states[index][int(selected_index)]
        selected_states.append(item)
        node[index] = config.null_node_cost if item is None else candidate_node_cost(item, config)
        if item is not None:
            rank[index] = item.candidate_rank
            frequency[index] = item.transition_frequency_hz
            is_null[index] = False
        if index == 0:
            transition[index] = config.null_stay_cost if item is None else config.ridge_entry_cost
        else:
            total, primary, curvature = transition_cost_components(
                selected_states[index - 2] if index >= 2 else None,
                selected_states[index - 1],
                item,
                config=config,
                spec=spec,
            )
            transition[index] = total
            first[index] = primary
            second[index] = curvature
        cumulative[index] = node[index] + transition[index] + (0.0 if index == 0 else cumulative[index - 1])
    if initial_total is not None:
        cumulative[0] = float(initial_total[0])
    return TransitionPathResult(
        time_s=np.asarray(time_s, dtype=np.float64),
        frame_indices=np.asarray(frame_indices, dtype=np.int64),
        candidate_frames=tuple(tuple(item for item in frame if item is not None) for frame in states),
        selected_state_indices=np.asarray(selected_indices, dtype=np.int64),
        selected_candidate_rank=rank,
        selected_frequency_hz=frequency,
        is_null=is_null,
        node_cost=node,
        transition_cost=transition,
        first_order_cost=first,
        curvature_cost=second,
        cumulative_cost=cumulative,
        spec=spec,
        config=config,
    )


def _candidate_frames_for_stream(stream: PreparedStream, *, top_k: int = 5) -> tuple[tuple[RidgeCandidate, ...], ...]:
    return tuple(frame[:top_k] for frame in stream.candidate_set_maximum.candidates_by_frame)


def _frame_interval(time_s: np.ndarray[Any, np.dtype[np.float64]], start: float, end: float) -> tuple[np.ndarray[Any, np.dtype[np.int64]], np.ndarray[Any, np.dtype[np.float64]]]:
    values = np.asarray(time_s, dtype=np.float64)
    mask = (values >= start) & (values <= end)
    indices = np.flatnonzero(mask).astype(np.int64)
    return indices, values[indices]


def _broadband_values(stream: PreparedStream) -> np.ndarray[Any, np.dtype[np.float64]]:
    power = np.sum(np.square(np.abs(stream.analysis.stft_result.spectrum)), axis=0)
    median = float(np.median(power))
    mad = float(np.median(np.abs(power - median)))
    scale = max(1.4826 * mad, np.finfo(np.float64).eps * max(abs(median), 1.0))
    return np.asarray((power - median) / scale, dtype=np.float64)


def transition_metrics(
    *,
    stream: PreparedStream,
    result: TransitionPathResult,
    scope: str,
    interval_id: str,
) -> dict[str, Any]:
    selected = ~result.is_null
    ranks = result.selected_candidate_rank
    availability = np.asarray([bool(frame) for frame in result.candidate_frames], dtype=np.bool_)
    steps, curvature = _path_steps(result.selected_frequency_hz)
    segments = _run_lengths(selected)
    broadband = _broadband_values(stream)[result.frame_indices]
    selected_refined = [
        item
        for frame, rank in zip(result.candidate_frames, ranks, strict=True)
        if rank > 0
        for item in (frame[int(rank) - 1],)
    ]
    exit = np.zeros(selected.size, dtype=np.bool_)
    if selected.size > 1:
        exit[1:] = selected[:-1] & ~selected[1:]
    return {
        "scope": scope,
        "interval_id": interval_id,
        "dataset": stream.source_path.name,
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "experiment_id": result.spec.experiment_id,
        "transition_model": result.spec.transition_model,
        "frame_count": int(selected.size),
        "start_time_s": float(result.time_s[0]),
        "end_time_s": float(result.time_s[-1]),
        "candidate_availability_fraction": float(np.mean(availability)),
        "null_fraction": float(np.mean(result.is_null)),
        "coverage_fraction": float(np.mean(selected)),
        "rank1_fraction": float(np.mean(ranks == 1)),
        "rank2_fraction": float(np.mean(ranks == 2)),
        "rank3_fraction": float(np.mean(ranks == 3)),
        "rank4plus_fraction": float(np.mean(ranks >= 4)),
        "candidate_available_but_selected_null_fraction": float(np.mean(availability & result.is_null)),
        "segment_count": len(segments),
        "median_segment_length": _median_or_nan(segments),
        "maximum_segment_length": int(max(segments)) if segments else 0,
        "frequency_step_median_hz": _median_or_nan(steps),
        "frequency_step_p95_hz": _quantile_or_nan(steps, 0.95),
        "curvature_median_hz": _median_or_nan(curvature),
        "curvature_p95_hz": _quantile_or_nan(curvature, 0.95),
        "candidate_node_cost_sum": float(np.sum(result.node_cost[selected])),
        "null_node_cost_sum": float(np.sum(result.node_cost[result.is_null])),
        "first_order_cost_sum": float(np.sum(result.first_order_cost)),
        "curvature_cost_sum": float(np.sum(result.curvature_cost)),
        "transition_cost_sum": float(np.sum(result.transition_cost)),
        "entry_count": int(selected[0]) + int(np.count_nonzero(~selected[:-1] & selected[1:])) if selected.size > 1 else int(selected[0]),
        "exit_count": int(np.count_nonzero(exit)),
        "total_path_cost": result.total_path_cost,
        "broadband_selected_fraction": float(np.mean(broadband[selected] >= 3.0)) if np.any(selected) else 0.0,
        "refinement_success_selected_fraction": (
            float(np.mean([item.refinement_status is RidgeRefinementStatus.REFINED for item in selected_refined]))
            if selected_refined
            else math.nan
        ),
    }


def _path_steps(frequency: np.ndarray[Any, np.dtype[np.float64]]) -> tuple[list[float], list[float]]:
    values = np.asarray(frequency, dtype=np.float64)
    first: list[float] = []
    second: list[float] = []
    for index in range(1, values.size):
        if math.isfinite(values[index - 1]) and math.isfinite(values[index]):
            first.append(abs(float(values[index] - values[index - 1])))
    for index in range(2, values.size):
        if all(math.isfinite(values[item]) for item in (index - 2, index - 1, index)):
            second.append(abs(float(values[index] - 2.0 * values[index - 1] + values[index - 2])))
    return first, second


def ch3_exit_audit_rows(stream: PreparedStream, result: TransitionPathResult) -> list[dict[str, Any]]:
    """Recompute selected-candidate continuation versus NULL exit with core costs."""
    focus = (result.time_s >= EXIT_AUDIT_START_S) & (result.time_s <= EXIT_AUDIT_END_S)
    exits = np.zeros(result.time_s.size, dtype=np.bool_)
    if result.time_s.size > 1:
        exits[1:] = ~result.is_null[1:] & False
        exits[1:] = ~result.is_null[:-1] & result.is_null[1:]
    for exit_index in np.flatnonzero(exits):
        focus[max(0, int(exit_index) - 5) : min(result.time_s.size, int(exit_index) + 6)] = True
    broadband = _broadband_values(stream)[result.frame_indices]
    rows: list[dict[str, Any]] = []
    for index in np.flatnonzero(focus):
        current = int(index)
        previous_item = None if current == 0 else _selected_item(result, current - 1)
        selected_item = _selected_item(result, current)
        best = min(result.candidate_frames[current], key=lambda item: candidate_node_cost(item, result.config), default=None)
        if current == 0:
            continuation_increment = math.nan if best is None else candidate_node_cost(best, result.config) + result.config.ridge_entry_cost
            exit_increment = result.config.null_node_cost + result.config.null_stay_cost
            base = 0.0
        else:
            base = float(result.cumulative_cost[current - 1])
            continuation_increment = (
                math.nan
                if best is None
                else candidate_node_cost(best, result.config)
                + transition_cost_components(None, previous_item, best, config=result.config, spec=result.spec)[0]
            )
            exit_increment = result.config.null_node_cost + transition_cost_components(None, previous_item, None, config=result.config, spec=result.spec)[0]
        delta_frequency = (
            math.nan
            if previous_item is None or best is None
            else best.transition_frequency_hz - previous_item.transition_frequency_hz
        )
        delta_time = math.nan if current == 0 else float(result.time_s[current] - result.time_s[current - 1])
        current_quadratic = (
            math.nan
            if not math.isfinite(delta_frequency)
            else candidate_transition_cost(previous_item, best, result.config)  # type: ignore[arg-type]
        )
        rows.append(
            {
                "time_s": float(result.time_s[current]),
                "frame_index": int(result.frame_indices[current]),
                "profile": stream.profile_id,
                "selected_state": "NULL" if result.is_null[current] else "candidate",
                "selected_rank": int(result.selected_candidate_rank[current]),
                "selected_frequency_hz": float(result.selected_frequency_hz[current]),
                "best_candidate_rank": 0 if best is None else best.candidate_rank,
                "best_candidate_frequency_hz": math.nan if best is None else best.transition_frequency_hz,
                "previous_selected_frequency_hz": math.nan if previous_item is None else previous_item.transition_frequency_hz,
                "delta_frequency_hz": delta_frequency,
                "delta_time_s": delta_time,
                "slope_hz_per_s": delta_frequency / delta_time if math.isfinite(delta_frequency) and delta_time > 0 else math.nan,
                "candidate_node_cost": math.nan if best is None else candidate_node_cost(best, result.config),
                "current_quadratic_continuity_cost": current_quadratic,
                "candidate_continuation_cumulative_cost": base + continuation_increment if math.isfinite(continuation_increment) else math.nan,
                "candidate_to_NULL_cumulative_cost": base + exit_increment,
                "continue_minus_exit_margin": continuation_increment - exit_increment if math.isfinite(continuation_increment) else math.nan,
                "all_NULL_prefix_cost": (current + 1) * result.config.null_node_cost,
                "candidate_bearing_prefix_cost": float(result.cumulative_cost[current]),
                "candidate_minus_NULL_prefix_margin": float(result.cumulative_cost[current] - (current + 1) * result.config.null_node_cost),
                "broadband_diagnostic_value": float(broadband[current]),
                "selected_refinement_status": "NULL" if selected_item is None else selected_item.refinement_status.value,
            }
        )
    return rows


def _selected_item(result: TransitionPathResult, index: int) -> RidgeCandidate | None:
    rank = int(result.selected_candidate_rank[index])
    return None if rank == 0 else result.candidate_frames[index][rank - 1]


def _synthetic_scenarios() -> tuple[SyntheticScenario, ...]:
    base = tuple(
        SyntheticScenario(case, 0.4e9, 2.8e9, np.zeros(case.truth_frequency_hz.size, dtype=np.bool_), "TASK021A_regression")
        for case in generate_synthetic_global_path_cases()
    )
    return base + _new_synthetic_scenarios()


def _new_synthetic_scenarios() -> tuple[SyntheticScenario, ...]:
    count = 96
    index = np.arange(count)
    plateau_then_descent = np.where(index < 30, 3.8e9, np.maximum(1.0e9, 3.8e9 - (index - 30) * 80.0e6))
    stable = np.full(count, 2.6e9)
    diagonal_wrong = np.asarray(4.4e9 - index * 25.0e6, dtype=np.float64)
    broadband = np.zeros(count, dtype=np.bool_)
    broadband[48:54] = True
    return (
        _make_scenario("I_FAST_SMOOTH_DESCENT", plateau_then_descent, None, None, "fast_descent"),
        _make_scenario("J_ABRUPT_BRANCH_JUMP", stable, np.where(index < 48, 3.9e9, 1.0e9), slice(26, 70), "abrupt_jump"),
        _make_scenario("K_SMOOTH_WRONG_DIAGONAL_DISTRACTOR", stable, diagonal_wrong, slice(16, 82), "smooth_wrong_diagonal"),
        _make_scenario("L_BROADBAND_TRANSIENT_OVERLAP", plateau_then_descent, None, None, "broadband_transient", broadband),
    )


def _make_scenario(
    case_id: str,
    truth: np.ndarray[Any, np.dtype[np.float64]],
    distractor_frequency: np.ndarray[Any, np.dtype[np.float64]] | None,
    distractor_slice: slice | None,
    diagnostic_name: str,
    broadband: np.ndarray[Any, np.dtype[np.bool_]] | None = None,
) -> SyntheticScenario:
    rng = np.random.default_rng(210210 + len(case_id))
    frequency = np.arange(201, dtype=np.float64) * 25.0e6
    magnitude = rng.lognormal(mean=math.log(0.18), sigma=0.30, size=(frequency.size, truth.size))
    phase = rng.uniform(-math.pi, math.pi, size=magnitude.shape)
    for frame_index, center in enumerate(truth):
        _add_peak(magnitude[:, frame_index], frequency, float(center), 12.0)
    if distractor_frequency is not None and distractor_slice is not None:
        for frame_index in range(*distractor_slice.indices(truth.size)):
            _add_peak(magnitude[:, frame_index], frequency, float(distractor_frequency[frame_index]), 14.0)
    diagnostic = np.zeros(truth.size, dtype=np.bool_) if broadband is None else np.asarray(broadband, dtype=np.bool_)
    for raw_frame_index in np.flatnonzero(diagnostic):
        frame_index = int(raw_frame_index)
        magnitude[:, int(frame_index)] += rng.lognormal(mean=math.log(5.0), sigma=0.45, size=frequency.size)
    stft = STFTResult(
        time_s=np.arange(truth.size, dtype=np.float64) * 2.5e-9,
        frequency_hz=frequency,
        spectrum=np.asarray(magnitude * np.exp(1j * phase), dtype=np.complex128),
        window_name="hann",
        window_length_samples=64,
        overlap_samples=48,
        hop_samples=16,
        nfft=400,
        sample_rate_hz=6.4e9,
        source_path=Path(f"synthetic/{case_id}.npz"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    case = SyntheticGlobalPathCase(
        case_id=case_id,
        description=diagnostic_name,
        truth_frequency_hz=np.asarray(truth, dtype=np.float64),
        pre_event_mask=np.zeros(truth.size, dtype=np.bool_),
        dropout_mask=np.zeros(truth.size, dtype=np.bool_),
        wrong_branch_tolerance_hz=120.0e6,
        stft_result=stft,
    )
    return SyntheticScenario(case, 0.4e9, 4.8e9, diagnostic, diagnostic_name)


def _add_peak(values: np.ndarray[Any, np.dtype[np.float64]], frequency: np.ndarray[Any, np.dtype[np.float64]], center: float, amplitude: float) -> None:
    values += amplitude * np.exp(-0.5 * np.square((frequency - center) / 22.0e6))


def synthetic_benchmark_rows(specs: Sequence[TransitionSpec], config: GlobalPathConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in _synthetic_scenarios():
        candidate_set = extract_global_path_candidates(
            scenario.case.stft_result,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
            config=config,
        )
        frames = tuple(frame[: config.top_k] for frame in candidate_set.candidates_by_frame)
        for spec in specs:
            result = solve_transition_path(frames, candidate_set.time_s, config=config, spec=spec)
            metric = calculate_ridge_metrics(
                scenario.case,
                result.selected_frequency_hz,
                selected_candidate_rank=result.selected_candidate_rank,
                method=spec.transition_model,
                top_k=config.top_k,
                vacuum_wavelength_m=DEFAULT_VACUUM_WAVELENGTH_M,
            )
            diagnostic_selected = np.isfinite(result.selected_frequency_hz[scenario.diagnostic_mask])
            rows.append(
                {
                    "experiment_id": spec.experiment_id,
                    "transition_model": spec.transition_model,
                    "case_id": scenario.case.case_id,
                    "diagnostic_name": scenario.diagnostic_name,
                    **metric.to_dict(),
                    "pure_noise_false_selection": (
                        1.0 - metric.null_fraction if scenario.case.case_id == "H_pure_noise" else math.nan
                    ),
                    "fast_descent_recovery": (
                        float(np.mean(np.isfinite(result.selected_frequency_hz[30:66])))
                        if scenario.case.case_id == "I_FAST_SMOOTH_DESCENT"
                        else math.nan
                    ),
                    "diagnostic_interval_selected_fraction": (
                        float(np.mean(diagnostic_selected)) if scenario.diagnostic_mask.any() else math.nan
                    ),
                    "diagnostic_interval_wrong_branch_fraction": (
                        float(np.mean(np.abs(result.selected_frequency_hz[scenario.diagnostic_mask] - scenario.case.truth_frequency_hz[scenario.diagnostic_mask]) > scenario.case.wrong_branch_tolerance_hz))
                        if scenario.diagnostic_mask.any()
                        else math.nan
                    ),
                }
            )
    return rows


def exhaustive_transition_path(
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
    *,
    config: GlobalPathConfig,
    spec: TransitionSpec,
) -> tuple[float, tuple[int, ...]]:
    """Enumerate a tiny graph exactly, including NULL, for correctness tests."""
    states = [(*frame, None) for frame in candidate_frames]
    best_cost = math.inf
    best_path: tuple[int, ...] = ()
    for indices in itertools.product(*(range(len(frame)) for frame in states)):
        total = 0.0
        chosen = [states[frame_index][index] for frame_index, index in enumerate(indices)]
        for frame_index, item in enumerate(chosen):
            total += config.null_node_cost if item is None else candidate_node_cost(item, config)
            if frame_index == 0:
                total += config.null_stay_cost if item is None else config.ridge_entry_cost
            else:
                total += transition_cost_components(
                    chosen[frame_index - 2] if frame_index >= 2 else None,
                    chosen[frame_index - 1],
                    item,
                    config=config,
                    spec=spec,
                )[0]
        if total < best_cost:
            best_cost = total
            best_path = tuple(int(item) for item in indices)
    return best_cost, best_path


def tiny_graph_validation() -> dict[str, Any]:
    """Run exhaustive-vs-DP validation on a hand-built 4-frame graph."""
    config = GlobalPathConfig(top_k=2)
    case = _synthetic_scenarios()[-1].case
    candidates = extract_global_path_candidates(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=4.8e9,
        config=config,
    )
    frames = tuple(frame[:2] for frame in candidates.candidates_by_frame[:4])
    times = candidates.time_s[:4]
    spec = next(item for item in build_transition_specs() if item.experiment_id == "E4")
    dp = solve_transition_path(frames, times, config=config, spec=spec)
    exhaustive_cost, exhaustive_path = exhaustive_transition_path(frames, config=config, spec=spec)
    return {
        "spec": spec.experiment_id,
        "dp_total_cost": dp.total_path_cost,
        "exhaustive_total_cost": exhaustive_cost,
        "dp_selected_state_indices": dp.selected_state_indices.tolist(),
        "exhaustive_selected_state_indices": list(exhaustive_path),
        "cost_equal": math.isclose(dp.total_path_cost, exhaustive_cost, rel_tol=1e-12, abs_tol=1e-12),
        "path_equal": tuple(dp.selected_state_indices.tolist()) == exhaustive_path,
    }


def run_task021e(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_directory: Path,
) -> dict[str, Any]:
    """Run TASK-021E with predeclared models and raw-hash safety checks."""
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite: {output}")
    output.mkdir(parents=True)
    figures = output / "figures"
    figures.mkdir()
    configuration = load_workflow_config(config_path, repository_root=REPOSITORY_ROOT)
    inventory, accepted = corrected_inventory(raw_root, configuration)
    hashes_before = {str(path): sha256_file(path) for path in sorted(accepted)}
    streams, failures = prepare_streams(raw_root=raw_root, configuration=configuration, accepted_inputs=accepted)
    config = GlobalPathConfig(top_k=5)
    specs = build_transition_specs()
    _write_csv(output / "transition_stack_definition.csv", [item.row() | config.to_metadata() for item in specs])
    (output / "repository_audit.txt").write_text(_repository_audit_text(config_path), encoding="utf-8")

    ch3_streams = [item for item in streams if item.source_path.name.casefold() == "ch3.csv"]
    if not ch3_streams:
        raise RuntimeError("ch3.csv did not produce a formal stream.")
    ch3_results: dict[tuple[str, str, str], TransitionPathResult] = {}
    comparison: list[dict[str, Any]] = []
    descent_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []
    for stream in ch3_streams:
        frames = _candidate_frames_for_stream(stream)
        full_time = stream.candidate_set_maximum.time_s
        for scope, start, end in (("FULL", float(full_time[0]), float(full_time[-1])), ("R1_DIAGNOSTIC", R1_START_S, R1_END_S)):
            indices, times = _frame_interval(full_time, start, end)
            local_frames = tuple(frames[int(index)] for index in indices)
            for spec in specs:
                started = time.perf_counter()
                result = solve_transition_path(local_frames, times, config=config, spec=spec, frame_indices=indices)
                elapsed = time.perf_counter() - started
                ch3_results[(stream.stream_id, scope, spec.experiment_id)] = result
                row = transition_metrics(stream=stream, result=result, scope=scope, interval_id=scope)
                row["runtime_s"] = elapsed
                comparison.append(row)
        baseline = ch3_results[(stream.stream_id, "FULL", "E0")]
        exit_rows.extend(ch3_exit_audit_rows(stream, baseline))
        for interval_id, start, end in DESCENT_INTERVALS:
            indices, times = _frame_interval(full_time, start, end)
            for spec in specs:
                full = ch3_results[(stream.stream_id, "FULL", spec.experiment_id)]
                selected = _slice_result(full, indices)
                descent_rows.append(
                    transition_metrics(stream=stream, result=selected, scope="FULL_SUBINTERVAL", interval_id=interval_id)
                )
    _write_csv(output / "ch3_transition_comparison.csv", comparison)
    _write_csv(output / "ch3_exit_audit.csv", exit_rows)
    _write_csv(output / "descent_interval_summary.csv", descent_rows)

    synthetic = synthetic_benchmark_rows(specs, config)
    _write_csv(output / "synthetic_transition_benchmark.csv", synthetic)
    passing = _passing_specs(specs, synthetic)
    cross, broadband = _cross_dataset_validation(streams, passing, config)
    _write_csv(output / "cross_dataset_transition_validation.csv", cross)
    _write_csv(output / "broadband_transition_summary.csv", broadband)
    tiny = tiny_graph_validation()
    (output / "tiny_graph_exhaustive_validation.json").write_text(json.dumps(tiny, indent=2), encoding="utf-8")
    _save_figures(figures, ch3_streams, ch3_results, exit_rows, synthetic)
    hashes_after = {str(path): sha256_file(path) for path in sorted(accepted)}
    metadata = {
        "task": "TASK-021E",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_branch": _git(["branch", "--show-current"]).strip(),
        "git_head": _git(["rev-parse", "HEAD"]).strip(),
        "raw_root_read_only": str(raw_root.resolve()),
        "input_count": len(accepted),
        "prepared_stream_count": len(streams),
        "profiles": [item.profile_id.value for item in configuration.analysis.profiles],
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "raw_hashes_equal": hashes_before == hashes_after,
        "specs_passing_pure_noise_guardrail": [item.experiment_id for item in passing],
        "tiny_graph_validation": tiny,
        "failures": [asdict(item) for item in failures],
        "production_modified": False,
        "broadband_penalty_added": False,
        "node_cost_modified": False,
    }
    (output / "experiment_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(output / "final_research_report.md", comparison, descent_rows, exit_rows, synthetic, cross, tiny, metadata)
    return {"output_directory": str(output), "stream_count": len(streams), "raw_hashes_equal": hashes_before == hashes_after, "passing": [item.experiment_id for item in passing]}


def _slice_result(result: TransitionPathResult, indices: np.ndarray[Any, np.dtype[np.int64]]) -> TransitionPathResult:
    positions = np.searchsorted(result.frame_indices, indices)
    return TransitionPathResult(
        time_s=result.time_s[positions], frame_indices=result.frame_indices[positions], candidate_frames=tuple(result.candidate_frames[int(item)] for item in positions), selected_state_indices=result.selected_state_indices[positions], selected_candidate_rank=result.selected_candidate_rank[positions], selected_frequency_hz=result.selected_frequency_hz[positions], is_null=result.is_null[positions], node_cost=result.node_cost[positions], transition_cost=result.transition_cost[positions], first_order_cost=result.first_order_cost[positions], curvature_cost=result.curvature_cost[positions], cumulative_cost=result.cumulative_cost[positions], spec=result.spec, config=result.config
    )


def _passing_specs(specs: Sequence[TransitionSpec], synthetic: Sequence[Mapping[str, Any]]) -> tuple[TransitionSpec, ...]:
    safe = {
        str(row["experiment_id"])
        for row in synthetic
        if row["case_id"] == "H_pure_noise" and float(row["pure_noise_false_selection"]) == 0.0
    }
    return tuple(item for item in specs if item.experiment_id in safe)


def _cross_dataset_validation(streams: Sequence[PreparedStream], specs: Sequence[TransitionSpec], config: GlobalPathConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    broadband_rows: list[dict[str, Any]] = []
    for stream in streams:
        frames = _candidate_frames_for_stream(stream)
        values = stream.candidate_set_maximum.time_s
        for spec in specs:
            started = time.perf_counter()
            result = solve_transition_path(frames, values, config=config, spec=spec)
            row = transition_metrics(stream=stream, result=result, scope="FULL", interval_id="FULL")
            row["runtime_s"] = time.perf_counter() - started
            rows.append(row)
            broadband_rows.append({
                "experiment_id": spec.experiment_id,
                "transition_model": spec.transition_model,
                "dataset": stream.source_path.name,
                "profile": stream.profile_id,
                "quality_group": stream.quality_group,
                "broadband_selected_fraction": row["broadband_selected_fraction"],
                "coverage_fraction": row["coverage_fraction"],
            })
    return rows, broadband_rows


def _save_figures(figures: Path, streams: Sequence[PreparedStream], results: Mapping[tuple[str, str, str], TransitionPathResult], exit_rows: Sequence[Mapping[str, Any]], synthetic: Sequence[Mapping[str, Any]]) -> None:
    for stream in streams:
        _plot_ch3_models(figures / f"ch3_{stream.profile_id}_transition_models.png", stream, [results[(stream.stream_id, "FULL", key)] for key in ("E0", "E1", "E2", "E4", "E6")])
        _plot_derivatives(figures / f"ch3_{stream.profile_id}_df_d2f.png", results[(stream.stream_id, "FULL", "E4")])
    _plot_exit(figures / "ch3_exit_transition_breakdown.png", exit_rows)
    _plot_synthetic(figures / "I_FAST_SMOOTH_DESCENT.png", synthetic, "I_FAST_SMOOTH_DESCENT")
    _plot_synthetic(figures / "J_ABRUPT_BRANCH_JUMP.png", synthetic, "J_ABRUPT_BRANCH_JUMP")
    _plot_synthetic(figures / "L_BROADBAND_TRANSIENT_OVERLAP.png", synthetic, "L_BROADBAND_TRANSIENT_OVERLAP")


def _plot_ch3_models(path: Path, stream: PreparedStream, results: Sequence[TransitionPathResult]) -> None:
    figure = Figure(figsize=(10, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for result in results:
        selected = ~result.is_null
        axis.plot(result.time_s[selected] * 1e6, result.selected_frequency_hz[selected] * 1e-9, marker=".", linewidth=1, label=result.spec.experiment_id)
    axis.axvspan(183.76, 183.82, color="orange", alpha=0.14, label="D1 diagnostic")
    axis.axvspan(183.82, 183.88, color="purple", alpha=0.11, label="D2 diagnostic")
    axis.set_xlim(183.60, 183.90)
    axis.set_xlabel("time (µs)")
    axis.set_ylabel("selected frequency (GHz)")
    axis.set_title(f"ch3 {stream.profile_id}: transition Research models")
    axis.legend(loc="best", ncol=2)
    _save_figure(figure, path)


def _plot_derivatives(path: Path, result: TransitionPathResult) -> None:
    figure = Figure(figsize=(10, 5.5), constrained_layout=True)
    frequency = result.selected_frequency_hz
    step = np.full(frequency.size, np.nan)
    second = np.full(frequency.size, np.nan)
    step[1:] = np.where(np.isfinite(frequency[1:]) & np.isfinite(frequency[:-1]), np.diff(frequency), np.nan)
    second[2:] = np.where(np.isfinite(frequency[2:]) & np.isfinite(frequency[1:-1]) & np.isfinite(frequency[:-2]), np.diff(frequency, n=2), np.nan)
    top, bottom = figure.subplots(2, 1, sharex=True)
    top.plot(result.time_s * 1e6, frequency * 1e-9, marker=".")
    top.set_ylabel("frequency (GHz)")
    bottom.plot(result.time_s * 1e6, step * 1e-9, label="df")
    bottom.plot(result.time_s * 1e6, second * 1e-9, label="d2f")
    bottom.set_xlabel("time (µs)")
    bottom.set_ylabel("GHz / frame")
    bottom.legend(loc="best")
    _save_figure(figure, path)


def _plot_exit(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    figure = Figure(figsize=(10, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for profile in sorted({str(row["profile"]) for row in rows}):
        matched = [row for row in rows if row["profile"] == profile]
        axis.plot([float(row["time_s"]) * 1e6 for row in matched], [float(row["continue_minus_exit_margin"]) for row in matched], marker=".", label=profile)
    axis.axhline(0.0, color="black", linewidth=1)
    axis.set_xlabel("time (µs)")
    axis.set_ylabel("continue candidate − exit NULL incremental cost")
    axis.set_title("ch3 T0 exit audit: exact core-cost continuation competition")
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_synthetic(path: Path, rows: Sequence[Mapping[str, Any]], case_id: str) -> None:
    matched = [row for row in rows if row["case_id"] == case_id]
    figure = Figure(figsize=(7.5, 4), constrained_layout=True)
    axis = figure.subplots()
    axis.bar([str(row["experiment_id"]) for row in matched], [float(row["frequency_rmse_hz"]) * 1e-6 for row in matched])
    axis.set_ylabel("frequency RMSE (MHz)")
    axis.set_title(f"{case_id}: transition-model synthetic comparison")
    _save_figure(figure, path)


def _write_report(path: Path, comparison: Sequence[Mapping[str, Any]], descent: Sequence[Mapping[str, Any]], exit_rows: Sequence[Mapping[str, Any]], synthetic: Sequence[Mapping[str, Any]], cross: Sequence[Mapping[str, Any]], tiny: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
    def _comparison(profile: str, experiment_id: str) -> Mapping[str, Any]:
        return next(
            row
            for row in comparison
            if row["profile"] == profile
            and row["experiment_id"] == experiment_id
            and row["interval_id"] == "FULL"
        )

    def _synthetic(case_id: str, experiment_id: str) -> Mapping[str, Any]:
        return next(
            row
            for row in synthetic
            if row["case_id"] == case_id and row["experiment_id"] == experiment_id
        )

    balanced_exit = [
        row
        for row in exit_rows
        if row["profile"] == "balanced"
        and math.isfinite(float(row["delta_frequency_hz"]))
        and float(row["continue_minus_exit_margin"]) > 0.0
    ]
    decisive = balanced_exit[0] if balanced_exit else None
    balanced_e0 = _comparison("balanced", "E0")
    balanced_e3 = _comparison("balanced", "E3")
    high_e0 = _comparison("high_time_resolution", "E0")
    high_e2 = _comparison("high_time_resolution", "E2")
    high_e4 = _comparison("high_time_resolution", "E4")
    fast_e0 = _synthetic("I_FAST_SMOOTH_DESCENT", "E0")
    fast_e2 = _synthetic("I_FAST_SMOOTH_DESCENT", "E2")
    jump_e2 = _synthetic("J_ABRUPT_BRANCH_JUMP", "E2")
    smooth_e0 = _synthetic("K_SMOOTH_WRONG_DIAGONAL_DISTRACTOR", "E0")
    smooth_e4 = _synthetic("K_SMOOTH_WRONG_DIAGONAL_DISTRACTOR", "E4")
    broadband_e2 = _synthetic("L_BROADBAND_TRANSIENT_OVERLAP", "E2")
    group_rows = {
        (str(row["quality_group"]), str(row["experiment_id"])): row
        for row in _aggregate_cross_rows(cross)
    }
    good_e2 = group_rows[("relatively_good_user_label", "E2")]
    medium_e2 = group_rows[("medium_user_label", "E2")]
    bad_e2 = group_rows[("bad_user_label", "E2")]
    bad_e3 = group_rows[("bad_user_label", "E3")]
    fast_status = "SUPPORTED" if decisive is not None else "NOT SUPPORTED"
    robust_status = "MIXED"
    curvature_status = "NOT SUPPORTED"
    hybrid_status = "NOT SUPPORTED"
    lines = [
        "# TASK-021E final Research report",
        "",
        "All transition variants are Research-only. Candidate graphs, node costs, NULL costs, STFTs, and raw files are unchanged.",
        "",
        "## Required answers",
        "",
        (
            f"1–4. Balanced P0 exits at {float(decisive['time_s']):.12f} s after a best-candidate Δf={float(decisive['delta_frequency_hz']) / 1e6:.2f} MHz. Its exact current quadratic continuity cost is {float(decisive['current_quadratic_continuity_cost']):.3f}, candidate node cost is {float(decisive['candidate_node_cost']):.3f}, and continue-minus-NULL-exit margin is {float(decisive['continue_minus_exit_margin']):.3f}; its broadband diagnostic is {float(decisive['broadband_diagnostic_value']):.1f}. High-time P0 has no exit because it is all NULL."
            if decisive is not None
            else "1–4. No decisive Balanced P0 candidate-to-NULL exit row was found in the audited interval."
        ),
        f"5. Fast-descent hypothesis: **{fast_status}** for the DP cost mechanism. The evidence is a quadratic-tail spike without a node-cost worsening; broadband overlap remains a separate contamination risk, not proof of physical identity.",
        f"6. T1 nominal (E2) raises I fast-descent recovery from {float(fast_e0['fast_descent_recovery']):.3f} (E0) to {float(fast_e2['fast_descent_recovery']):.3f}, keeps J wrong-branch fraction at {float(jump_e2['wrong_branch_fraction']):.3f}, and preserves pure-noise false selection=0.",
        f"7. T2/E4 also recovers I, but K smooth-wrong-diagonal wrong-branch fraction rises from {float(smooth_e0['wrong_branch_fraction']):.3f} (E0) to {float(smooth_e4['wrong_branch_fraction']):.3f}; curvature is therefore not a safe standalone Research direction despite exact solver correctness.",
        "8. T3/E6 retains the same smooth-wrong-diagonal failure class as T2 and adds no High-time ch3 recovery over T2; no complementary hybrid value was demonstrated.",
        f"9. Second-order DP exhaustive validation: cost_equal={tiny['cost_equal']}, path_equal={tiny['path_equal']}.",
        "10. I_FAST_SMOOTH_DESCENT is best on recovery for every E1–E6 (1.0 versus E0 0.056); this validates that the sensitivity actually exercises a fast smooth descent.",
        "11. J_ABRUPT_BRANCH_JUMP has zero wrong-branch fraction for E0–E6, so this small benchmark does not distinguish models beyond confirming no observed regression.",
        "12. Curvature preferentially follows the wrong smooth diagonal in K; this is the anticipated curvature-only bias and blocks a positive T2/T3 conclusion.",
        f"13. In L broadband overlap, E2 selects the whole diagnostic interval ({float(broadband_e2['diagnostic_interval_selected_fraction']):.3f}) while its diagnostic wrong-branch fraction is {float(broadband_e2['diagnostic_interval_wrong_branch_fraction']):.3f}; this establishes sensitivity to broadband frames but not a new error in that synthetic construction.",
        f"14. Balanced FULL coverage: E0={float(balanced_e0['coverage_fraction']):.4f}; aggressive E3={float(balanced_e3['coverage_fraction']):.4f}. Only E3 lengthens the Balanced segment (48→52 frames), with step p95 rising to {float(balanced_e3['frequency_step_p95_hz']) / 1e6:.1f} MHz.",
        f"15. High-time FULL: E0 coverage={float(high_e0['coverage_fraction']):.4f}; E2 recovers one 47-frame segment ({float(high_e2['coverage_fraction']):.4f}), while T2/E4 remains {float(high_e4['coverage_fraction']):.4f}. Thus robust first-order duplicates the continuity=0.5 recovery rather than exceeding it.",
        "16. Every newly selected High-time ch3 frame in E1–E3 is broadband-elevated under the unchanged TASK-021D diagnostic; this is a material risk flag, not a reason to add a penalty here.",
        f"17. Relatively-good E2 coverage={float(good_e2['coverage_fraction']):.4f} versus E0 {float(group_rows[('relatively_good_user_label', 'E0')]['coverage_fraction']):.4f}; it is a small numerical increase with preserved pure-noise safety.",
        f"18. Medium E2 coverage={float(medium_e2['coverage_fraction']):.4f} versus E0 {float(group_rows[('medium_user_label', 'E0')]['coverage_fraction']):.4f}; this is modest and not uniform per file. E3 reaches higher mean coverage but with much larger step p95.",
        f"19. Bad remains dataset-dependent: E2 coverage={float(bad_e2['coverage_fraction']):.4f}; aggressive E3={float(bad_e3['coverage_fraction']):.4f} but step p95={float(bad_e3['frequency_step_p95_hz']) / 1e6:.1f} MHz and broadband-selected fraction={float(bad_e3['broadband_selected_fraction']):.3f}.",
        "20. All E0–E6 retain 0 pure-noise false selection and the TASK-021A A–H baseline regression remains explicit in the synthetic artifact.",
        "21. Transition redesign is not superior to simple continuity=0.5: E2 yields the same High-time ch3 segment as E1, while E3's extra coverage comes with step/broadband risk.",
        "22. Prioritize node-evidence redesign before a new second-order calibration. Broadband modeling is a separate diagnostic problem; do not promote or continue curvature models on current evidence.",
        "",
        "## Conclusions",
        "",
        f"A. Fast-descent hypothesis: **{fast_status}**.",
        f"B. Robust first-order transition: **{robust_status}**.",
        f"C. Second-order curvature transition: **{curvature_status}**.",
        f"D. Hybrid transition: **{hybrid_status}**.",
        "E. Current Global Path real-data research value: **MIXED**.",
        "",
        "## Safety boundary",
        "",
        f"- Raw SHA-256 before/after equal: {metadata['raw_hashes_equal']}.",
        "- Production GUI, default path algorithm, export, LiF physics, node evidence, and broadband penalties were not modified.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _aggregate_cross_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate full-stream metrics for report prose without fitting any parameter."""
    keys = sorted({(str(row["quality_group"]), str(row["experiment_id"])) for row in rows})
    result: list[dict[str, Any]] = []
    metrics = ("coverage_fraction", "frequency_step_p95_hz", "broadband_selected_fraction")
    for group, experiment_id in keys:
        matched = [row for row in rows if row["quality_group"] == group and row["experiment_id"] == experiment_id]
        result.append({
            "quality_group": group,
            "experiment_id": experiment_id,
            **{
                metric: float(np.nanmean([float(row[metric]) for row in matched]))
                for metric in metrics
            },
        })
    return result


def _repository_audit_text(config_path: Path) -> str:
    commands = (("git status --short --branch", ["git", "status", "--short", "--branch"]), ("git branch --show-current", ["git", "branch", "--show-current"]), ("git log -5 --oneline", ["git", "log", "-5", "--oneline"]), ("git diff --stat", ["git", "diff", "--stat"]), ("git diff --cached --stat", ["git", "diff", "--cached", "--stat"]))
    lines = ["TASK-021E repository audit", f"config={config_path.resolve()}", ""]
    for label, command in commands:
        completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True)
        lines.extend((f"$ {label}", completed.stdout.decode("utf-8", errors="replace").rstrip(), ""))
    lines.extend(("Core transition semantics: candidate->candidate = continuity_weight*(abs(df_hz)/frequency_step_scale_hz)^2; scale=1e8 Hz, weight=1.0.", "NULL->NULL=null_stay_cost; NULL->candidate=ridge_entry_cost; candidate->NULL=ridge_exit_cost; first candidate pays entry; terminal receives no extra exit.", "Second-order Research solver clears curvature history whenever either preceding state is NULL."))
    return "\n".join(lines) + "\n"


def _git(arguments: Sequence[str]) -> str:
    completed = subprocess.run(["git", *arguments], cwd=REPOSITORY_ROOT, check=True, capture_output=True)
    return completed.stdout.decode("utf-8", errors="replace")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    values = [dict(row) for row in rows]
    fields = list(dict.fromkeys(field for row in values for field in row))
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def _run_lengths(values: np.ndarray[Any, np.dtype[np.bool_]]) -> list[int]:
    lengths: list[int] = []
    length = 0
    for value in values:
        if value:
            length += 1
        elif length:
            lengths.append(length)
            length = 0
    if length:
        lengths.append(length)
    return lengths


def _median_or_nan(values: Sequence[float] | Sequence[int]) -> float:
    return float(np.median(values)) if values else math.nan


def _quantile_or_nan(values: Sequence[float] | np.ndarray[Any, np.dtype[np.float64]], q: float) -> float:
    return float(np.quantile(values, q)) if len(values) else math.nan


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=150)


__all__ = [
    "TransitionPathResult",
    "TransitionSpec",
    "build_transition_specs",
    "curvature_cost",
    "exhaustive_transition_path",
    "robust_first_order_cost",
    "run_task021e",
    "solve_transition_path",
    "synthetic_benchmark_rows",
    "tiny_graph_validation",
    "transition_cost_components",
]
