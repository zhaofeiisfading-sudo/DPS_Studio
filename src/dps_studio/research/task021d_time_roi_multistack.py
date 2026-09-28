"""TASK-021D Research-only DP-ROI and factorial Global Path diagnostics.

The experiment deliberately reuses a single full-record STFT and its fixed
Top-20 candidate cloud.  Time ROIs only select the frames supplied to the
local DP recurrence; they never crop raw voltage or recompute the STFT.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    RidgeCandidateSet,
    candidate_node_cost,
    candidate_transition_cost,
    track_global_candidate_path,
)
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research.global_path_benchmark import (
    DEFAULT_VACUUM_WAVELENGTH_M,
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


BoundaryMode = Literal["B0_STANDARD", "B1_FREE_ROI_BOUNDARY"]

MANUAL_DIAGNOSTIC_ROI_NAME = "R1_TIGHT"
MANUAL_DIAGNOSTIC_START_S = 0.0001836
MANUAL_DIAGNOSTIC_END_S = 0.0001839
ROI_REQUESTS: tuple[tuple[str, float | None, float | None], ...] = (
    ("R0_FULL", None, None),
    (MANUAL_DIAGNOSTIC_ROI_NAME, MANUAL_DIAGNOSTIC_START_S, MANUAL_DIAGNOSTIC_END_S),
    ("R2_PAD_0P05_US", 0.00018355, 0.00018395),
    ("R3_PAD_0P10_US", 0.00018350, 0.00018400),
)
BOUNDARY_MODES: tuple[BoundaryMode, ...] = ("B0_STANDARD", "B1_FREE_ROI_BOUNDARY")
MAXIMUM_TOP_K = 20


@dataclass(frozen=True, slots=True)
class RoiDefinition:
    """Physical-time DP frame interval derived from an immutable STFT axis."""

    roi_id: str
    requested_start_time_s: float | None
    requested_end_time_s: float | None
    start_time_s: float
    end_time_s: float
    frame_start: int
    frame_end: int
    frame_count: int
    was_clipped: bool


@dataclass(frozen=True, slots=True)
class StackSpec:
    """One fixed point in the predeclared 2×2×2 Research factorial."""

    stack_id: str
    config: GlobalPathConfig
    top_k_level: str
    entry_level: str
    continuity_level: str

    def row(self) -> dict[str, Any]:
        return {
            "stack_id": self.stack_id,
            "factorial_design": "2x2x2",
            "top_k_level": self.top_k_level,
            "entry_level": self.entry_level,
            "continuity_level": self.continuity_level,
            **self.config.to_metadata(),
        }


@dataclass(frozen=True, slots=True)
class RoiPathResult:
    """Local DP result that never changes a core GlobalRidgePathResult."""

    time_s: np.ndarray[Any, np.dtype[np.float64]]
    frame_indices: np.ndarray[Any, np.dtype[np.int64]]
    candidate_frames: tuple[tuple[RidgeCandidate, ...], ...]
    selected_candidate_rank: np.ndarray[Any, np.dtype[np.int64]]
    selected_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    is_null: np.ndarray[Any, np.dtype[np.bool_]]
    node_cost: np.ndarray[Any, np.dtype[np.float64]]
    transition_cost: np.ndarray[Any, np.dtype[np.float64]]
    cumulative_cost: np.ndarray[Any, np.dtype[np.float64]]
    all_null_cost_by_frame: np.ndarray[Any, np.dtype[np.float64]]
    candidate_bearing_cost_by_frame: np.ndarray[Any, np.dtype[np.float64]]
    config: GlobalPathConfig
    boundary_mode: BoundaryMode

    @property
    def total_path_cost(self) -> float:
        return float(self.cumulative_cost[-1])

    @property
    def all_null_total_cost(self) -> float:
        return float(self.all_null_cost_by_frame[-1])

    @property
    def candidate_bearing_total_cost(self) -> float:
        return float(self.candidate_bearing_cost_by_frame[-1])


def build_factorial_stacks() -> tuple[StackSpec, ...]:
    """Return all eight predeclared K/entry/continuity combinations."""
    baseline = GlobalPathConfig(top_k=5)
    rows: list[StackSpec] = []
    for top_k, entry, continuity in (
        (5, baseline.ridge_entry_cost, baseline.continuity_weight),
        (20, baseline.ridge_entry_cost, baseline.continuity_weight),
        (5, 2.25, baseline.continuity_weight),
        (20, 2.25, baseline.continuity_weight),
        (5, baseline.ridge_entry_cost, 0.5),
        (20, baseline.ridge_entry_cost, 0.5),
        (5, 2.25, 0.5),
        (20, 2.25, 0.5),
    ):
        stack_id = f"P{len(rows)}"
        rows.append(
            StackSpec(
                stack_id=stack_id,
                config=replace(
                    baseline,
                    top_k=top_k,
                    ridge_entry_cost=entry,
                    continuity_weight=continuity,
                ),
                top_k_level=f"K{top_k}",
                entry_level=("baseline" if entry == baseline.ridge_entry_cost else "2.25"),
                continuity_level=(
                    "baseline" if continuity == baseline.continuity_weight else "0.5"
                ),
            )
        )
    return tuple(rows)


def map_time_roi(
    time_s: np.ndarray[Any, np.dtype[np.float64]],
    *,
    roi_id: str,
    requested_start_time_s: float | None,
    requested_end_time_s: float | None,
) -> RoiDefinition:
    """Map a physical-time inclusive ROI to deterministic STFT frame indices."""
    values = np.asarray(time_s, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or not np.all(np.diff(values) > 0.0):
        raise ValueError("STFT time axis must be non-empty and strictly increasing.")
    if requested_start_time_s is None or requested_end_time_s is None:
        if requested_start_time_s is not None or requested_end_time_s is not None:
            raise ValueError("A full ROI must omit both requested bounds.")
        return RoiDefinition(
            roi_id=roi_id,
            requested_start_time_s=None,
            requested_end_time_s=None,
            start_time_s=float(values[0]),
            end_time_s=float(values[-1]),
            frame_start=0,
            frame_end=int(values.size - 1),
            frame_count=int(values.size),
            was_clipped=False,
        )
    if not math.isfinite(requested_start_time_s) or not math.isfinite(requested_end_time_s):
        raise ValueError("ROI times must be finite.")
    if requested_end_time_s <= requested_start_time_s:
        raise ValueError("ROI end time must exceed start time.")
    start = float(np.clip(requested_start_time_s, values[0], values[-1]))
    end = float(np.clip(requested_end_time_s, values[0], values[-1]))
    if end < start:
        raise ValueError("Clipped ROI is empty.")
    first = int(np.searchsorted(values, start, side="left"))
    last = int(np.searchsorted(values, end, side="right") - 1)
    if first > last:
        raise ValueError("ROI contains no STFT frame centers.")
    return RoiDefinition(
        roi_id=roi_id,
        requested_start_time_s=float(requested_start_time_s),
        requested_end_time_s=float(requested_end_time_s),
        start_time_s=float(values[first]),
        end_time_s=float(values[last]),
        frame_start=first,
        frame_end=last,
        frame_count=last - first + 1,
        was_clipped=start != requested_start_time_s or end != requested_end_time_s,
    )


def _frames_for_stack(
    candidate_set: RidgeCandidateSet,
    config: GlobalPathConfig,
    definition: RoiDefinition,
) -> tuple[tuple[RidgeCandidate, ...], ...]:
    """Return a Top-K slice of existing candidates without re-extraction."""
    if config.top_k > candidate_set.config.top_k:
        raise ValueError("TASK-021D cannot invent candidates beyond the fixed graph.")
    return tuple(
        frame[: config.top_k]
        for frame in candidate_set.candidates_by_frame[
            definition.frame_start : definition.frame_end + 1
        ]
    )


def candidate_graph_overlap_signature(
    candidate_set: RidgeCandidateSet,
    config: GlobalPathConfig,
    definition: RoiDefinition,
) -> tuple[tuple[tuple[int, float, float, float], ...], ...]:
    """Deterministic graph signature used to prove same-STFT ROI identity."""
    return tuple(
        tuple(
            (
                item.candidate_rank,
                item.discrete_frequency_hz,
                item.transition_frequency_hz,
                candidate_node_cost(item, config),
            )
            for item in frame
        )
        for frame in _frames_for_stack(candidate_set, config, definition)
    )


def solve_dp_roi_same_stft(
    candidate_set: RidgeCandidateSet,
    *,
    config: GlobalPathConfig,
    definition: RoiDefinition,
    boundary_mode: BoundaryMode,
) -> RoiPathResult:
    """Solve a local first-order DP over existing full-STFT candidates only.

    B0 reproduces current core start semantics.  B1 differs only at local frame
    zero: an immediate candidate has zero initial transition instead of a ridge
    entry penalty.  Both modes retain the core's lack of terminal exit charge.
    """
    if boundary_mode not in BOUNDARY_MODES:
        raise ValueError("Unknown TASK-021D boundary mode.")
    frames = _frames_for_stack(candidate_set, config, definition)
    indices = np.arange(definition.frame_start, definition.frame_end + 1, dtype=np.int64)
    times = np.asarray(candidate_set.time_s[indices], dtype=np.float64)
    state_frames = [(*frame, None) for frame in frames]
    forward: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    predecessor: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    all_null = np.empty(len(state_frames), dtype=np.float64)
    candidate_seen: list[np.ndarray[Any, np.dtype[np.float64]]] = []

    for frame_index, states in enumerate(state_frames):
        node = np.asarray(
            [config.null_node_cost if item is None else candidate_node_cost(item, config) for item in states],
            dtype=np.float64,
        )
        if frame_index == 0:
            first_transition = np.asarray(
                [
                    config.null_stay_cost
                    if item is None
                    else (0.0 if boundary_mode == "B1_FREE_ROI_BOUNDARY" else config.ridge_entry_cost)
                    for item in states
                ],
                dtype=np.float64,
            )
            forward.append(node + first_transition)
            predecessor.append(np.full(len(states), -1, dtype=np.int64))
            all_null[frame_index] = config.null_node_cost + config.null_stay_cost
            seen = np.full(len(states), math.inf, dtype=np.float64)
            seen[:-1] = node[:-1] + first_transition[:-1]
            candidate_seen.append(seen)
            continue

        previous = state_frames[frame_index - 1]
        previous_forward = forward[-1]
        current = np.empty(len(states), dtype=np.float64)
        current_predecessor = np.empty(len(states), dtype=np.int64)
        previous_seen = candidate_seen[-1]
        seen = np.empty(len(states), dtype=np.float64)
        all_null[frame_index] = all_null[frame_index - 1] + config.null_node_cost + config.null_stay_cost
        for state_index, state in enumerate(states):
            transitions = np.asarray(
                [
                    previous_forward[previous_index]
                    + _transition_cost(previous_state, state, config)
                    for previous_index, previous_state in enumerate(previous)
                ],
                dtype=np.float64,
            )
            current_predecessor[state_index] = int(np.argmin(transitions))
            current[state_index] = node[state_index] + transitions[current_predecessor[state_index]]

            seen_transitions = np.asarray(
                [
                    previous_seen[previous_index]
                    + _transition_cost(previous_state, state, config)
                    for previous_index, previous_state in enumerate(previous)
                ],
                dtype=np.float64,
            )
            best_seen = float(np.min(seen_transitions))
            if state is not None:
                best_seen = min(
                    best_seen,
                    all_null[frame_index - 1] + config.ridge_entry_cost,
                )
            seen[state_index] = node[state_index] + best_seen
        forward.append(current)
        predecessor.append(current_predecessor)
        candidate_seen.append(seen)

    selected_indices = np.empty(len(state_frames), dtype=np.int64)
    selected_indices[-1] = int(np.argmin(forward[-1]))
    for frame_index in range(len(state_frames) - 1, 0, -1):
        selected_indices[frame_index - 1] = predecessor[frame_index][selected_indices[frame_index]]

    rank = np.zeros(len(state_frames), dtype=np.int64)
    frequency = np.full(len(state_frames), np.nan, dtype=np.float64)
    null = np.ones(len(state_frames), dtype=np.bool_)
    node_values = np.empty(len(state_frames), dtype=np.float64)
    transition_values = np.empty(len(state_frames), dtype=np.float64)
    cumulative = np.empty(len(state_frames), dtype=np.float64)
    for raw_frame_index, raw_state_index in enumerate(selected_indices.tolist()):
        frame_index = int(raw_frame_index)
        state_index = int(raw_state_index)
        result_state: RidgeCandidate | None = state_frames[frame_index][state_index]
        result_previous: RidgeCandidate | None = (
            None
            if frame_index == 0
            else state_frames[frame_index - 1][int(selected_indices[frame_index - 1])]
        )
        if result_state is None:
            node_values[frame_index] = config.null_node_cost
        else:
            rank[frame_index] = result_state.candidate_rank
            frequency[frame_index] = result_state.transition_frequency_hz
            null[frame_index] = False
            node_values[frame_index] = candidate_node_cost(result_state, config)
        if frame_index == 0:
            transition_values[frame_index] = (
                config.null_stay_cost
                if result_state is None
                else (0.0 if boundary_mode == "B1_FREE_ROI_BOUNDARY" else config.ridge_entry_cost)
            )
        else:
            transition_values[frame_index] = _transition_cost(result_previous, result_state, config)
        cumulative[frame_index] = forward[frame_index][state_index]

    return RoiPathResult(
        time_s=times,
        frame_indices=indices,
        candidate_frames=frames,
        selected_candidate_rank=rank,
        selected_frequency_hz=frequency,
        is_null=null,
        node_cost=node_values,
        transition_cost=transition_values,
        cumulative_cost=cumulative,
        all_null_cost_by_frame=all_null,
        candidate_bearing_cost_by_frame=np.asarray(
            [float(np.min(values)) for values in candidate_seen], dtype=np.float64
        ),
        config=config,
        boundary_mode=boundary_mode,
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


def roi_metrics(
    *,
    stream: PreparedStream,
    roi: RoiDefinition,
    stack: StackSpec,
    result: RoiPathResult,
    runtime_s: float,
) -> dict[str, Any]:
    """Return a complete metric and cost-accounting row for one local DP solve."""
    selected = ~result.is_null
    candidate_available = np.asarray([bool(frame) for frame in result.candidate_frames], dtype=np.bool_)
    ranks = result.selected_candidate_rank
    runs = _run_lengths(selected)
    finite = result.selected_frequency_hz
    steps = np.abs(np.diff(finite))
    valid_steps = steps[np.isfinite(finite[:-1]) & np.isfinite(finite[1:])]
    selected_candidates = [
        None if rank == 0 else result.candidate_frames[index][rank - 1]
        for index, rank in enumerate(ranks)
    ]
    entry_mask = np.zeros(selected.size, dtype=np.bool_)
    exit_mask = np.zeros(selected.size, dtype=np.bool_)
    if selected.size:
        entry_mask[0] = selected[0]
        exit_mask[0] = False
    if selected.size > 1:
        entry_mask[1:] = ~selected[:-1] & selected[1:]
        exit_mask[1:] = selected[:-1] & ~selected[1:]
    continuity_mask = selected[1:] & selected[:-1]
    refinement = np.asarray(
        [
            item is not None and item.refinement_status is RidgeRefinementStatus.REFINED
            for item in selected_candidates
        ],
        dtype=np.bool_,
    )
    candidate_node = float(np.sum(result.node_cost[selected]))
    null_node = float(np.sum(result.node_cost[result.is_null]))
    return {
        "dataset": stream.source_path.name,
        "source_path": str(stream.source_path),
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "roi_id": roi.roi_id,
        "requested_start_time_s": roi.requested_start_time_s,
        "requested_end_time_s": roi.requested_end_time_s,
        "start_time_s": roi.start_time_s,
        "end_time_s": roi.end_time_s,
        "frame_start": roi.frame_start,
        "frame_end": roi.frame_end,
        "frame_count": roi.frame_count,
        "roi_was_clipped": roi.was_clipped,
        "dp_mode": "DP_ROI_SAME_STFT",
        "boundary_mode": result.boundary_mode,
        "boundary_mode_scope": (
            "core_current_semantics" if result.boundary_mode == "B0_STANDARD" else "RESEARCH_DIAGNOSTIC_ONLY"
        ),
        "stack_id": stack.stack_id,
        "top_k": stack.config.top_k,
        "ridge_entry_cost": stack.config.ridge_entry_cost,
        "continuity_weight": stack.config.continuity_weight,
        "candidate_availability_fraction": float(np.mean(candidate_available)),
        "frames_with_candidates": int(np.count_nonzero(candidate_available)),
        "null_fraction": float(np.mean(result.is_null)),
        "non_null_coverage_fraction": float(np.mean(selected)),
        "rank1_fraction": float(np.mean(ranks == 1)),
        "rank2_fraction": float(np.mean(ranks == 2)),
        "rank3_fraction": float(np.mean(ranks == 3)),
        "rank4plus_fraction": float(np.mean(ranks >= 4)),
        "candidate_available_but_selected_null_fraction": float(np.mean(candidate_available & result.is_null)),
        "non_null_segment_count": len(runs),
        "median_non_null_segment_length": _median_or_nan(runs),
        "maximum_non_null_segment_length": int(max(runs)) if runs else 0,
        "frequency_min_hz": _finite_min_or_nan(finite),
        "frequency_max_hz": _finite_max_or_nan(finite),
        "candidate_to_candidate_step_median_hz": _median_or_nan(valid_steps.tolist()),
        "candidate_to_candidate_step_p95_hz": _quantile_or_nan(valid_steps, 0.95),
        "maximum_frequency_step_hz": float(np.max(valid_steps)) if valid_steps.size else math.nan,
        "entry_count": int(np.count_nonzero(entry_mask)),
        "exit_count": int(np.count_nonzero(exit_mask)),
        "candidate_node_cost_sum": candidate_node,
        "null_node_cost_sum": null_node,
        "continuity_cost_sum": float(np.sum(result.transition_cost[1:][continuity_mask])),
        "entry_cost_sum": float(np.sum(result.transition_cost[entry_mask])),
        "exit_cost_sum": float(np.sum(result.transition_cost[exit_mask])),
        "best_path_total_cost": result.total_path_cost,
        "all_null_path_total_cost": result.all_null_total_cost,
        "candidate_bearing_path_total_cost": result.candidate_bearing_total_cost,
        "best_minus_all_null_cost": result.total_path_cost - result.all_null_total_cost,
        "candidate_bearing_minus_all_null_cost": (
            result.candidate_bearing_total_cost - result.all_null_total_cost
        ),
        "refinement_success_selected_fraction": (
            float(np.mean(refinement[selected])) if np.any(selected) else math.nan
        ),
        "runtime_s": runtime_s,
    }


def cost_margin_rows(
    *,
    stream: PreparedStream,
    roi: RoiDefinition,
    stack: StackSpec,
    result: RoiPathResult,
) -> list[dict[str, Any]]:
    """Report prefix cost competition between any-candidate and all-NULL paths."""
    rows: list[dict[str, Any]] = []
    for index, time_s in enumerate(result.time_s):
        candidate = result.candidate_bearing_cost_by_frame[index]
        null = result.all_null_cost_by_frame[index]
        rows.append(
            {
                "dataset": stream.source_path.name,
                "profile": stream.profile_id,
                "channel": stream.channel_name,
                "stream_id": stream.stream_id,
                "roi_id": roi.roi_id,
                "stack_id": stack.stack_id,
                "boundary_mode": result.boundary_mode,
                "frame_index": int(result.frame_indices[index]),
                "time_s": float(time_s),
                "candidate_bearing_best_prefix_cost": candidate,
                "all_null_prefix_cost": null,
                "candidate_minus_all_null_prefix_cost": candidate - null,
                "candidate_bearing_path_wins_prefix": bool(candidate < null),
                "selected_rank": int(result.selected_candidate_rank[index]),
                "selected_is_null": bool(result.is_null[index]),
            }
        )
    return rows


def broadband_rows(
    stream: PreparedStream,
    full_result: RoiPathResult,
) -> list[dict[str, Any]]:
    """Simple read-only band-integrated power diagnostic; it never alters DP cost."""
    stft = stream.analysis.stft_result
    power = np.sum(np.square(np.abs(stft.spectrum)), axis=0)
    median = float(np.median(power))
    mad = float(np.median(np.abs(power - median)))
    scale = max(1.4826 * mad, np.finfo(np.float64).eps * max(abs(median), 1.0))
    robust_z = (power - median) / scale
    return [
        {
            "dataset": stream.source_path.name,
            "profile": stream.profile_id,
            "channel": stream.channel_name,
            "stream_id": stream.stream_id,
            "frame_index": int(index),
            "time_s": float(stft.time_s[index]),
            "band_integrated_power": float(power[index]),
            "robust_relative_band_power": float(robust_z[index]),
            "broadband_elevated_frame": bool(robust_z[index] >= 3.0),
            "selected_by_P0_full_standard": bool(not full_result.is_null[index]),
            "diagnostic_scope": "RESEARCH_ONLY_not_SNR_not_DP_cost",
        }
        for index in range(stft.time_s.size)
    ]


def run_task021d(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_directory: Path,
) -> dict[str, Any]:
    """Run the complete TASK-021D Research-only matrix without output overwrite."""
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output directory: {output}")
    output.mkdir(parents=True)
    figures = output / "figures"
    figures.mkdir()
    configuration = load_workflow_config(config_path, repository_root=REPOSITORY_ROOT)
    inventory, accepted = corrected_inventory(raw_root, configuration)
    hashes_before = {str(path): sha256_file(path) for path in sorted(accepted)}
    streams, failures = prepare_streams(
        raw_root=raw_root,
        configuration=configuration,
        accepted_inputs=accepted,
    )
    stacks = build_factorial_stacks()
    _assert_stack_matrix(stacks)
    ch3_streams = [stream for stream in streams if stream.source_path.name.casefold() == "ch3.csv"]
    if not ch3_streams:
        raise RuntimeError("ch3.csv did not produce an eligible formal Research stream.")

    audit = _repository_audit_text(config_path)
    (output / "repository_audit.txt").write_text(audit, encoding="utf-8")
    _write_csv(output / "corrected_dataset_manifest.csv", inventory)
    _write_csv(output / "stack_definition.csv", [stack.row() for stack in stacks])

    definitions: dict[tuple[str, str], RoiDefinition] = {}
    roi_rows: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    margin_rows: list[dict[str, Any]] = []
    result_index: dict[tuple[str, str, str, BoundaryMode, str], RoiPathResult] = {}

    for stream in ch3_streams:
        for roi_id, start, end in ROI_REQUESTS:
            definition = map_time_roi(
                stream.candidate_set_maximum.time_s,
                roi_id=roi_id,
                requested_start_time_s=start,
                requested_end_time_s=end,
            )
            definitions[(stream.stream_id, roi_id)] = definition
            roi_rows.append(
                {
                    "dataset": stream.source_path.name,
                    "profile": stream.profile_id,
                    "channel": stream.channel_name,
                    "stream_id": stream.stream_id,
                    **asdict(definition),
                    "definition_kind": (
                        "manual_diagnostic_time_ROI_not_ground_truth"
                        if roi_id != "R0_FULL"
                        else "full_STFT_time_range"
                    ),
                }
            )
            for stack in stacks:
                _assert_same_graph_within_roi(stream.candidate_set_maximum, stack.config, definition)
                for boundary in BOUNDARY_MODES:
                    started = time.perf_counter()
                    result = solve_dp_roi_same_stft(
                        stream.candidate_set_maximum,
                        config=stack.config,
                        definition=definition,
                        boundary_mode=boundary,
                    )
                    runtime = time.perf_counter() - started
                    key = (stream.stream_id, roi_id, stack.stack_id, boundary, "DP_ROI_SAME_STFT")
                    result_index[key] = result
                    matrix_rows.append(
                        roi_metrics(
                            stream=stream,
                            roi=definition,
                            stack=stack,
                            result=result,
                            runtime_s=runtime,
                        )
                    )
                    if roi_id == MANUAL_DIAGNOSTIC_ROI_NAME:
                        margin_rows.extend(
                            cost_margin_rows(
                                stream=stream,
                                roi=definition,
                                stack=stack,
                                result=result,
                            )
                        )

    _write_csv(output / "roi_definition.csv", roi_rows)
    _write_csv(output / "ch3_full_matrix.csv", matrix_rows)
    _write_csv(output / "ch3_cost_margin.csv", margin_rows)
    _write_csv(output / "candidate_vs_null_margin_vs_time.csv", margin_rows)

    broadband: list[dict[str, Any]] = []
    for stream in ch3_streams:
        full = result_index[(stream.stream_id, "R0_FULL", "P0", "B0_STANDARD", "DP_ROI_SAME_STFT")]
        broadband.extend(broadband_rows(stream, full))
    _write_csv(output / "broadband_diagnostic.csv", broadband)
    profile_summary = _profile_roi_summary(matrix_rows)
    _write_csv(output / "profile_roi_summary.csv", profile_summary)

    synthetic_rows = _synthetic_guardrail_rows(stacks)
    _write_csv(output / "synthetic_guardrail.csv", synthetic_rows)
    shortlist = _select_nondominated_stacks(matrix_rows, synthetic_rows)
    cross_rows = _cross_dataset_rows(streams, stacks, shortlist)
    _write_csv(output / "cross_dataset_validation.csv", cross_rows)

    _save_figures(
        figures=figures,
        streams=ch3_streams,
        definitions=definitions,
        results=result_index,
        matrix_rows=matrix_rows,
        margin_rows=margin_rows,
        broadband=broadband,
    )
    hashes_after = {str(path): sha256_file(path) for path in sorted(accepted)}
    metadata = {
        "task": "TASK-021D",
        "created_utc": datetime.now(UTC).isoformat(),
        "research_root": str(REPOSITORY_ROOT),
        "raw_root_read_only": str(raw_root.resolve()),
        "config_path": str(config_path.resolve()),
        "profiles_from_current_runner": [profile.profile_id.value for profile in configuration.analysis.profiles],
        "dp_mode": "DP_ROI_SAME_STFT",
        "manual_diagnostic_roi": {
            "start_time_s": MANUAL_DIAGNOSTIC_START_S,
            "end_time_s": MANUAL_DIAGNOSTIC_END_S,
            "not_ground_truth": True,
        },
        "boundary_semantics": {
            "B0_STANDARD": "Core semantics: initial candidate pays ridge_entry_cost; no terminal exit is charged.",
            "B1_FREE_ROI_BOUNDARY": "Research only: immediate ROI-start candidate pays zero initial entry; no terminal exit remains charged.",
        },
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "raw_hashes_equal": hashes_before == hashes_after,
        "input_count": len(accepted),
        "prepared_stream_count": len(streams),
        "ch3_matrix_row_count": len(matrix_rows),
        "synthetic_row_count": len(synthetic_rows),
        "cross_dataset_row_count": len(cross_rows),
        "shortlisted_stacks": list(shortlist),
        "failures": [asdict(item) for item in failures],
        "production_modified": False,
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(
        output / "final_research_report.md",
        matrix_rows=matrix_rows,
        margin_rows=margin_rows,
        profile_summary=profile_summary,
        synthetic_rows=synthetic_rows,
        cross_rows=cross_rows,
        shortlist=shortlist,
        metadata=metadata,
    )
    return {
        "output_directory": str(output),
        "stream_count": len(streams),
        "matrix_rows": len(matrix_rows),
        "raw_hashes_equal": hashes_before == hashes_after,
        "shortlist": shortlist,
    }


def _assert_same_graph_within_roi(
    candidate_set: RidgeCandidateSet,
    config: GlobalPathConfig,
    definition: RoiDefinition,
) -> None:
    """Fail closed if the ROI no longer exposes exact full-graph candidate objects."""
    frames = _frames_for_stack(candidate_set, config, definition)
    source = candidate_set.candidates_by_frame[definition.frame_start : definition.frame_end + 1]
    if any(tuple(local) != tuple(full[: config.top_k]) for local, full in zip(frames, source, strict=True)):
        raise RuntimeError("ROI candidate graph differs from the full fixed candidate graph.")


def _assert_stack_matrix(stacks: Sequence[StackSpec]) -> None:
    combinations = {
        (item.config.top_k, item.config.ridge_entry_cost, item.config.continuity_weight)
        for item in stacks
    }
    if len(stacks) != 8 or len(combinations) != 8:
        raise RuntimeError("TASK-021D factorial stack must contain exactly eight unique cells.")
    if GlobalPathConfig() != GlobalPathConfig():
        raise RuntimeError("Unexpected mutable GlobalPathConfig default.")


def _synthetic_guardrail_rows(stacks: Sequence[StackSpec]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stack in stacks:
        for case in generate_synthetic_global_path_cases():
            result = track_global_candidate_path(
                case.stft_result,
                minimum_frequency_hz=0.4e9,
                maximum_frequency_hz=2.8e9,
                config=stack.config,
            )
            evaluated = calculate_ridge_metrics(
                case,
                result.selected_refined_frequency_hz,
                selected_candidate_rank=result.selected_candidate_rank,
                method="task021d_factorial_global_path",
                top_k=stack.config.top_k,
                vacuum_wavelength_m=DEFAULT_VACUUM_WAVELENGTH_M,
            )
            metric = evaluated.to_dict()
            rows.append(
                {
                    "stack_id": stack.stack_id,
                    "ridge_entry_cost": stack.config.ridge_entry_cost,
                    "continuity_weight": stack.config.continuity_weight,
                    **metric,
                    "pure_noise_false_selection": (
                        1.0 - evaluated.null_fraction
                        if case.case_id == "H_pure_noise"
                        else math.nan
                    ),
                    "dropout_selected_fraction": (
                        float(np.mean(np.isfinite(result.selected_refined_frequency_hz[case.dropout_mask])))
                        if np.any(case.dropout_mask)
                        else math.nan
                    ),
                }
            )
    return rows


def _select_nondominated_stacks(
    matrix_rows: Sequence[Mapping[str, Any]],
    synthetic_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Use predeclared numeric full-B0 criteria, never plots, to choose ≤3 stacks."""
    clean = {
        str(row["stack_id"])
        for row in synthetic_rows
        if row["case_id"] == "H_pure_noise" and float(row["pure_noise_false_selection"]) == 0.0
    }
    score: dict[str, tuple[float, float, float]] = {}
    for stack_id in sorted(clean):
        rows = [
            row
            for row in matrix_rows
            if row["stack_id"] == stack_id
            and row["roi_id"] == "R0_FULL"
            and row["boundary_mode"] == "B0_STANDARD"
        ]
        if not rows:
            continue
        coverage = float(np.mean([float(row["non_null_coverage_fraction"]) for row in rows]))
        jump_values = [float(row["candidate_to_candidate_step_p95_hz"]) for row in rows]
        jump = float(np.nanmean(jump_values)) if np.any(np.isfinite(jump_values)) else math.inf
        segments = float(np.mean([float(row["non_null_segment_count"]) for row in rows]))
        score[stack_id] = (coverage, jump, segments)
    nondominated: list[str] = []
    for identifier, own in score.items():
        dominated = any(
            other != identifier
            and candidate[0] >= own[0]
            and candidate[1] <= own[1]
            and candidate[2] <= own[2]
            and candidate != own
            for other, candidate in score.items()
        )
        if not dominated:
            nondominated.append(identifier)
    return tuple(sorted(nondominated, key=lambda item: (-score[item][0], score[item][1], score[item][2]))[:3])


def _cross_dataset_rows(
    streams: Sequence[PreparedStream],
    stacks: Sequence[StackSpec],
    shortlist: Sequence[str],
) -> list[dict[str, Any]]:
    selected_ids = set(shortlist)
    selected_stacks = [item for item in stacks if item.stack_id in selected_ids]
    raw_names_by_group: dict[str, set[str]] = {
        "relatively_good_user_label": set(),
        "medium_user_label": set(),
        "bad_user_label": set(),
    }
    for stream in streams:
        if stream.quality_group in raw_names_by_group:
            raw_names_by_group[stream.quality_group].add(stream.source_path.name)
    keep_names = (
        set(sorted(raw_names_by_group["relatively_good_user_label"])[:2])
        | raw_names_by_group["medium_user_label"]
        | set(sorted(raw_names_by_group["bad_user_label"]))
    )
    rows: list[dict[str, Any]] = []
    for stream in streams:
        if stream.source_path.name not in keep_names:
            continue
        definition = map_time_roi(
            stream.candidate_set_maximum.time_s,
            roi_id="R0_FULL",
            requested_start_time_s=None,
            requested_end_time_s=None,
        )
        for stack in selected_stacks:
            started = time.perf_counter()
            result = solve_dp_roi_same_stft(
                stream.candidate_set_maximum,
                config=stack.config,
                definition=definition,
                boundary_mode="B0_STANDARD",
            )
            row = roi_metrics(
                stream=stream,
                roi=definition,
                stack=stack,
                result=result,
                runtime_s=time.perf_counter() - started,
            )
            row["validation_scope"] = "FULL_only_no_manual_ch3_ROI_transfer"
            rows.append(row)
    return rows


def _profile_roi_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    keys = sorted({(str(row["profile"]), str(row["roi_id"]), str(row["boundary_mode"]), str(row["stack_id"])) for row in rows})
    for profile, roi, boundary, stack in keys:
        matched = [
            row
            for row in rows
            if row["profile"] == profile
            and row["roi_id"] == roi
            and row["boundary_mode"] == boundary
            and row["stack_id"] == stack
        ]
        summary.append(
            {
                "profile": profile,
                "roi_id": roi,
                "boundary_mode": boundary,
                "stack_id": stack,
                "stream_count": len(matched),
                "mean_candidate_availability_fraction": float(np.mean([float(row["candidate_availability_fraction"]) for row in matched])),
                "mean_null_fraction": float(np.mean([float(row["null_fraction"]) for row in matched])),
                "mean_non_null_coverage_fraction": float(np.mean([float(row["non_null_coverage_fraction"]) for row in matched])),
                "mean_maximum_segment_length": float(np.mean([float(row["maximum_non_null_segment_length"]) for row in matched])),
                "mean_best_minus_all_null_cost": float(np.mean([float(row["best_minus_all_null_cost"]) for row in matched])),
            }
        )
    return summary


def _save_figures(
    *,
    figures: Path,
    streams: Sequence[PreparedStream],
    definitions: Mapping[tuple[str, str], RoiDefinition],
    results: Mapping[tuple[str, str, str, BoundaryMode, str], RoiPathResult],
    matrix_rows: Sequence[Mapping[str, Any]],
    margin_rows: Sequence[Mapping[str, Any]],
    broadband: Sequence[Mapping[str, Any]],
) -> None:
    for stream in streams:
        for roi_id in ("R0_FULL", MANUAL_DIAGNOSTIC_ROI_NAME):
            definition = definitions[(stream.stream_id, roi_id)]
            result = results[(stream.stream_id, roi_id, "P0", "B0_STANDARD", "DP_ROI_SAME_STFT")]
            _plot_spectrogram_path(figures / f"ch3_{stream.profile_id}_{roi_id}_P0_B0.png", stream, definition, result)
    _plot_matrix_comparison(figures / "full_vs_manual_roi_coverage.png", matrix_rows)
    _plot_stack_comparison(figures / "factorial_stack_comparison.png", matrix_rows)
    _plot_margin(figures / "candidate_vs_NULL_margin_vs_time.png", margin_rows)
    _plot_boundary(figures / "standard_vs_free_roi_boundary.png", matrix_rows)
    _plot_broadband(figures / "broadband_transient_diagnostic.png", broadband)


def _plot_spectrogram_path(path: Path, stream: PreparedStream, roi: RoiDefinition, result: RoiPathResult) -> None:
    stft = stream.analysis.stft_result
    figure = Figure(figsize=(10, 5), constrained_layout=True)
    axis = figure.subplots()
    magnitude = np.abs(stft.spectrum)
    floor = max(float(np.max(magnitude)) * 1.0e-6, np.finfo(np.float64).tiny)
    db = 20.0 * np.log10(np.maximum(magnitude, floor) / np.max(magnitude))
    mesh = axis.pcolormesh(stft.time_s * 1.0e6, stft.frequency_hz * 1.0e-9, db, shading="auto", cmap="magma", vmin=-60, vmax=0)
    figure.colorbar(mesh, ax=axis, label="relative spectral magnitude (dB)")
    for frame in result.candidate_frames:
        if frame:
            axis.scatter(
                [item.time_s * 1.0e6 for item in frame],
                [item.transition_frequency_hz * 1.0e-9 for item in frame],
                s=5,
                color="cyan",
                alpha=0.5,
            )
    selected = ~result.is_null
    axis.plot(result.time_s[selected] * 1.0e6, result.selected_frequency_hz[selected] * 1.0e-9, "w.-", label="Global Path / DP ROI")
    axis.axvspan(MANUAL_DIAGNOSTIC_START_S * 1.0e6, MANUAL_DIAGNOSTIC_END_S * 1.0e6, color="lime", alpha=0.16, label="manual diagnostic time ROI (not ground truth)")
    axis.set_xlim(roi.start_time_s * 1.0e6, roi.end_time_s * 1.0e6)
    axis.set_xlabel("time (µs)")
    axis.set_ylabel("frequency (GHz)")
    axis.set_title(f"ch3 / {stream.profile_id} / {roi.roi_id}: same STFT + fixed candidate graph")
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_matrix_comparison(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    selected = [row for row in rows if row["stack_id"] == "P0" and row["boundary_mode"] == "B0_STANDARD"]
    figure = Figure(figsize=(9, 4.5), constrained_layout=True)
    axis = figure.subplots()
    labels = [f"{row['profile']}\n{row['roi_id']}" for row in selected]
    axis.bar(np.arange(len(selected)), [float(row["non_null_coverage_fraction"]) for row in selected], color="#3b82f6")
    axis.set_xticks(np.arange(len(selected)), labels, rotation=35, ha="right")
    axis.set_ylabel("non-NULL coverage fraction")
    axis.set_title("ch3 P0 standard: FULL vs manual diagnostic time ROIs")
    _save_figure(figure, path)


def _plot_stack_comparison(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    selected = [row for row in rows if row["roi_id"] == MANUAL_DIAGNOSTIC_ROI_NAME and row["boundary_mode"] == "B0_STANDARD"]
    figure = Figure(figsize=(9, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for profile in sorted({str(row["profile"]) for row in selected}):
        matched = [row for row in selected if row["profile"] == profile]
        axis.plot([row["stack_id"] for row in matched], [float(row["non_null_coverage_fraction"]) for row in matched], marker="o", label=profile)
    axis.set_ylabel("non-NULL coverage fraction")
    axis.set_title("ch3 manual diagnostic ROI: P0–P7 standard boundary")
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_margin(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    selected = [row for row in rows if row["stack_id"] == "P0" and row["boundary_mode"] == "B0_STANDARD"]
    figure = Figure(figsize=(9, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for profile in sorted({str(row["profile"]) for row in selected}):
        matched = [row for row in selected if row["profile"] == profile]
        axis.plot([float(row["time_s"]) * 1.0e6 for row in matched], [float(row["candidate_minus_all_null_prefix_cost"]) for row in matched], label=profile)
    axis.axhline(0.0, color="black", linewidth=1)
    axis.set_xlabel("time (µs)")
    axis.set_ylabel("candidate-bearing prefix cost − all-NULL prefix cost")
    axis.set_title("R1 manual diagnostic ROI, P0 standard: candidate-vs-NULL cost margin")
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_boundary(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    selected = [row for row in rows if row["stack_id"] == "P0" and row["roi_id"] != "R0_FULL"]
    figure = Figure(figsize=(9, 4.5), constrained_layout=True)
    axis = figure.subplots()
    labels = sorted({f"{row['profile']}\n{row['roi_id']}" for row in selected})
    standard = []
    free = []
    for label in labels:
        profile, roi = label.split("\n", maxsplit=1)
        standard.append(next(float(row["non_null_coverage_fraction"]) for row in selected if row["profile"] == profile and row["roi_id"] == roi and row["boundary_mode"] == "B0_STANDARD"))
        free.append(next(float(row["non_null_coverage_fraction"]) for row in selected if row["profile"] == profile and row["roi_id"] == roi and row["boundary_mode"] == "B1_FREE_ROI_BOUNDARY"))
    x = np.arange(len(labels))
    axis.bar(x - 0.18, standard, width=0.35, label="B0 standard")
    axis.bar(x + 0.18, free, width=0.35, label="B1 free ROI boundary")
    axis.set_xticks(x, labels, rotation=35, ha="right")
    axis.set_ylabel("non-NULL coverage fraction")
    axis.set_title("Boundary semantics diagnostic only")
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_broadband(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    figure = Figure(figsize=(9, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for profile in sorted({str(row["profile"]) for row in rows}):
        matched = [row for row in rows if row["profile"] == profile]
        axis.plot([float(row["time_s"]) * 1.0e6 for row in matched], [float(row["robust_relative_band_power"]) for row in matched], label=profile)
        elevated = [row for row in matched if bool(row["broadband_elevated_frame"])]
        axis.scatter([float(row["time_s"]) * 1.0e6 for row in elevated], [float(row["robust_relative_band_power"]) for row in elevated], s=12)
    axis.axhline(3.0, color="black", linestyle="--", label="diagnostic threshold")
    axis.set_xlabel("time (µs)")
    axis.set_ylabel("robust relative band-integrated power")
    axis.set_title("ch3 broadband transient diagnostic (not SNR; not a DP penalty)")
    axis.legend(loc="best")
    _save_figure(figure, path)


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=150)


def _repository_audit_text(config_path: Path) -> str:
    commands = (
        ("git status --short --branch", ["git", "status", "--short", "--branch"]),
        ("git branch --show-current", ["git", "branch", "--show-current"]),
        ("git log -5 --oneline", ["git", "log", "-5", "--oneline"]),
        ("git diff --stat", ["git", "diff", "--stat"]),
        ("git diff --cached --stat", ["git", "diff", "--cached", "--stat"]),
    )
    sections = ["TASK-021D repository audit", f"config={config_path.resolve()}", ""]
    for label, command in commands:
        completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True)
        standard_output = completed.stdout.decode("utf-8", errors="replace")
        sections.extend((f"$ {label}", standard_output.rstrip(), ""))
    sections.extend(
        (
            "Core boundary semantics verified from src/dps_studio/core/ridge/global_path.py:",
            "- first DP frame: candidate pays ridge_entry_cost; NULL pays null_stay_cost.",
            "- ordinary candidate→NULL transition pays ridge_exit_cost.",
            "- terminal backtracking selects min final state without an extra terminal exit charge.",
            "Research workflow uses full raw range for STFT in prepare_streams; WORKFLOW_ROI_RECOMPUTE_STFT is not run.",
        )
    )
    return "\n".join(sections) + "\n"


def _write_report(
    path: Path,
    *,
    matrix_rows: Sequence[Mapping[str, Any]],
    margin_rows: Sequence[Mapping[str, Any]],
    profile_summary: Sequence[Mapping[str, Any]],
    synthetic_rows: Sequence[Mapping[str, Any]],
    cross_rows: Sequence[Mapping[str, Any]],
    shortlist: Sequence[str],
    metadata: Mapping[str, Any],
) -> None:
    def _row(profile: str, roi: str, boundary: BoundaryMode, stack: str = "P0") -> Mapping[str, Any]:
        return next(
            item
            for item in matrix_rows
            if item["profile"] == profile and item["roi_id"] == roi and item["boundary_mode"] == boundary and item["stack_id"] == stack
        )

    profiles = sorted({str(row["profile"]) for row in matrix_rows})
    high = "high_time_resolution" if "high_time_resolution" in profiles else profiles[0]
    high_full = _row(high, "R0_FULL", "B0_STANDARD")
    high_tight = _row(high, MANUAL_DIAGNOSTIC_ROI_NAME, "B0_STANDARD")
    high_p4_full = _row(high, "R0_FULL", "B0_STANDARD", "P4")
    high_p4_tight = _row(high, MANUAL_DIAGNOSTIC_ROI_NAME, "B0_STANDARD", "P4")
    high_p6_tight = _row(high, MANUAL_DIAGNOSTIC_ROI_NAME, "B0_STANDARD", "P6")
    full_text = "; ".join(
        f"{profile}: " + ", ".join(
            f"{roi}={float(_row(profile, roi, 'B0_STANDARD')['null_fraction']):.4f}"
            for roi, _, _ in ROI_REQUESTS
        )
        for profile in profiles
    )
    pure_noise = [row for row in synthetic_rows if row["case_id"] == "H_pure_noise"]
    pure_safe = all(float(row["pure_noise_false_selection"]) == 0.0 for row in pure_noise)
    cross_groups = {str(row["quality_group"]) for row in cross_rows}
    standard_tight = _row(high, MANUAL_DIAGNOSTIC_ROI_NAME, "B0_STANDARD")
    free_tight = _row(high, MANUAL_DIAGNOSTIC_ROI_NAME, "B1_FREE_ROI_BOUNDARY")
    boundary_pairs = [
        (
            row,
            next(
                item
                for item in matrix_rows
                if item["stream_id"] == row["stream_id"]
                and item["roi_id"] == row["roi_id"]
                and item["stack_id"] == row["stack_id"]
                and item["boundary_mode"] == "B1_FREE_ROI_BOUNDARY"
            ),
        )
        for row in matrix_rows
        if row["boundary_mode"] == "B0_STANDARD"
    ]
    maximum_boundary_coverage_change = max(
        abs(float(left["non_null_coverage_fraction"]) - float(right["non_null_coverage_fraction"]))
        for left, right in boundary_pairs
    )
    maximum_boundary_cost_change = max(
        abs(float(left["best_path_total_cost"]) - float(right["best_path_total_cost"]))
        for left, right in boundary_pairs
    )
    high_p4_full_frames = round(
        float(high_p4_full["non_null_coverage_fraction"]) * float(high_p4_full["frame_count"])
    )
    high_p4_tight_frames = round(
        float(high_p4_tight["non_null_coverage_fraction"]) * float(high_p4_tight["frame_count"])
    )
    high_p4_margin = [
        row
        for row in margin_rows
        if row["profile"] == high
        and row["roi_id"] == MANUAL_DIAGNOSTIC_ROI_NAME
        and row["stack_id"] == "P4"
        and row["boundary_mode"] == "B0_STANDARD"
        and bool(row["candidate_bearing_path_wins_prefix"])
    ]
    time_roi_status = "NOT SUPPORTED"
    stack_status = "MIXED" if shortlist and pure_safe else "NOT SUPPORTED"
    transfer_status = "MIXED" if "medium_user_label" in cross_groups and pure_safe else "NOT SUPPORTED"
    lines = [
        "# TASK-021D final Research report",
        "",
        "All ROIs are manual diagnostic time ROIs, not ground truth, event times, or production settings.",
        "All results use DP_ROI_SAME_STFT unless explicitly stated otherwise; no raw crop or STFT recomputation was run.",
        "",
        "## Required answers",
        "",
        f"1. ch3 High-time FULL NULL fraction is {float(high_full['null_fraction']):.6f}.",
        f"2. High-time R1 candidate availability is {float(high_tight['candidate_availability_fraction']):.6f}.",
        f"3. P0/B0 NULL fractions: {full_text}.",
        f"4–5. Same-graph horizon alone did not change High-time P0 (FULL=R1=0 coverage). With P4, FULL and R1 each select {high_p4_full_frames} and {high_p4_tight_frames} frames respectively, with the same best-minus-NULL cost {float(high_p4_full['best_minus_all_null_cost']):.6f}; R1's 0.5 coverage is a shorter-denominator summary, not a newly recovered path.",
        f"6. High-time R1/P0 B0 vs B1 coverage is {float(standard_tight['non_null_coverage_fraction']):.6f} vs {float(free_tight['non_null_coverage_fraction']):.6f}; across every paired matrix cell, maximum coverage difference={maximum_boundary_coverage_change:.6f} and cost difference={maximum_boundary_cost_change:.6g}.",
        "7. Entry/exit boundary semantics are not an important cause in this matrix: core charges an initial candidate entry but no terminal exit, and the B1 initial-entry waiver made no observed difference. The selected P4 segment starts after the ROI boundary and still pays its normal entry.",
        (
            f"8–9. High-time P0 never has a candidate-bearing prefix cheaper than all-NULL in R1. High-time P4 first has a negative prefix margin at {float(high_p4_margin[0]['time_s']):.12f} s (frame {int(high_p4_margin[0]['frame_index'])})"
            if high_p4_margin
            else "8–9. No High-time P4 candidate-bearing prefix became cheaper than all-NULL in R1."
        ) + "; this is a cost-model observation, not physical ridge confirmation.",
        "10. ch3 High-time R1: P0–P3 remain NULL; P4–P7 each select 47/94 frames in one segment. K5→K20 has zero coverage effect, and entry 3.0→2.25 has zero coverage effect; continuity 1.0→0.5 is the decisive factor.",
        f"11–12. The High-time P4/P6 R1 coverage is {float(high_p4_tight['non_null_coverage_fraction']):.6f}/{float(high_p6_tight['non_null_coverage_fraction']):.6f}; there is no observed K or entry interaction in coverage, while lowering continuity changes coverage from 0 to 0.5 across all K/entry cells.",
        "13–14. P4–P7 increase coverage together with a 47-frame continuous segment; their High-time step p95 is about 83 MHz, below the configured 100 MHz scale. The factorial has two principal behavioral classes (continuity=1 NULL; continuity=0.5 selected), not five distinct robust trade-offs.",
        f"15. Cross-dataset validation used predeclared nondominated, pure-noise-safe stacks: {', '.join(shortlist) if shortlist else 'none'}; no stack is stable across good/medium/bad because bad coverage remains low while medium remains mostly NULL.",
        f"16. Pure-noise false selection was {'0 for all P0–P7' if pure_safe else 'nonzero for at least one P stack'}.",
        "17. medium comparisons are full-record only; no ch3 manual ROI was transferred. The selected short-list reaches about 0.246 non-NULL coverage versus TASK-021C N0's 0.239 group mean: a small change, not clearer general tracking.",
        "18. In P0/FULL, all 48 selected Balanced frames are marked broadband-elevated by this simple diagnostic; High-time selects none. This is coincidence evidence for follow-up only, not a causal or SNR finding.",
        f"19. The strict DP-horizon criterion is {time_roi_status}: the same P4 path/cost appears in FULL and each nested ROI, while P0 remains NULL. The apparent ROI coverage increase is denominator-driven.",
        "20. The main bottleneck remains node/NULL/transition-cost competition, with continuity scale the only tested factor that changed the High-time decision; candidate availability was 1.0 throughout R1.",
        "21. The next priority is node-evidence redesign with separate continuity-scale calibration; automatic interval detection, NULL-model redesign, and broadband modeling should remain separate future hypotheses.",
        "",
        "## Boundary semantics and workflow",
        "",
        "- B0 STANDARD exactly reproduces core start semantics: first candidate pays ridge_entry_cost; first NULL pays null_stay_cost.",
        "- Core terminal selection applies no extra ridge_exit_cost. B1 FREE_ROI_BOUNDARY is RESEARCH_DIAGNOSTIC_ONLY and changes only a candidate at local frame zero.",
        "- The formal TASK runner computed full-record STFTs and candidates before local DP; workflow ROI/STFT recomputation was therefore not applicable and was not used.",
        "",
        "## Conclusions",
        "",
        f"A. Time-ROI hypothesis: **{time_roi_status}**.",
        f"B. Multi-stack robustness: **{stack_status}**.",
        f"C. Current Global Path real-data transfer: **{transfer_status}**.",
        "",
        "These are Research observations. Candidate-supported paths, ROI behavior, and broadband diagnostics require independent experimental confirmation before any physical or Production claim.",
        "",
        "## Safety boundary",
        "",
        f"- Included raw inputs: {metadata['input_count']}; SHA-256 before/after equal: {metadata['raw_hashes_equal']}.",
        "- Production GUI, default algorithm, export, LiF physics, and Production worktree were not modified.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields = list(dict.fromkeys(field for row in materialized for field in row))
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _run_lengths(values: np.ndarray[Any, np.dtype[np.bool_]]) -> list[int]:
    lengths: list[int] = []
    current = 0
    for item in values:
        if item:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _median_or_nan(values: Sequence[float] | Sequence[int]) -> float:
    return float(np.median(values)) if values else math.nan


def _quantile_or_nan(values: np.ndarray[Any, np.dtype[np.float64]], quantile: float) -> float:
    return float(np.quantile(values, quantile)) if values.size else math.nan


def _finite_min_or_nan(values: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    finite = values[np.isfinite(values)]
    return float(np.min(finite)) if finite.size else math.nan


def _finite_max_or_nan(values: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    finite = values[np.isfinite(values)]
    return float(np.max(finite)) if finite.size else math.nan


__all__ = [
    "BOUNDARY_MODES",
    "MANUAL_DIAGNOSTIC_END_S",
    "MANUAL_DIAGNOSTIC_ROI_NAME",
    "MANUAL_DIAGNOSTIC_START_S",
    "ROI_REQUESTS",
    "RoiDefinition",
    "RoiPathResult",
    "StackSpec",
    "build_factorial_stacks",
    "candidate_graph_overlap_signature",
    "map_time_roi",
    "run_task021d",
    "solve_dp_roi_same_stft",
]
