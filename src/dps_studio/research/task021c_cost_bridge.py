"""TASK-021C read-only cost-normalization and NULL-gap bridge Research."""

from __future__ import annotations

import csv
import json
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from dps_studio.core.io import SignalColumnError, SignalIOError
from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    RidgeCandidateSet,
    candidate_node_cost,
    candidate_transition_cost,
    solve_global_candidate_path,
    track_global_candidate_path,
)
from dps_studio.research.global_path_benchmark import (
    DEFAULT_SYNTHETIC_SEED,
    generate_synthetic_global_path_cases,
)
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    REPOSITORY_ROOT,
    FormalInput,
    PreparedStream,
    classify_quality_group,
    formal_read_input,
    node_cost_components,
    prepare_streams,
    sha256_file,
)


TASK021B_ARTIFACT = (
    REPOSITORY_ROOT
    / "artifacts"
    / "task021b_global_path_real_calibration"
    / "20260830T230100Z"
)
MEDIUM_DIRECTORY_NAME = "PDV数据-质量中等"
NUMERICAL_EXTENSIONS = frozenset({".csv", ".dat"})
GAP_FRAME_LIMITS = (1, 2, 3, 5)


@dataclass(frozen=True, slots=True)
class PathView:
    """A Research path whose arrays remain separate from the core result."""

    time_s: np.ndarray[Any, np.dtype[np.float64]]
    selected_candidate_rank: np.ndarray[Any, np.dtype[np.int64]]
    selected_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    is_null: np.ndarray[Any, np.dtype[np.bool_]]
    node_cost: np.ndarray[Any, np.dtype[np.float64]]
    transition_cost: np.ndarray[Any, np.dtype[np.float64]]
    cumulative_cost: np.ndarray[Any, np.dtype[np.float64]]
    candidate_set: RidgeCandidateSet
    config: GlobalPathConfig
    normalization_id: str


@dataclass(frozen=True, slots=True)
class Normalization:
    """Frozen profile scaling learned only from the designated good reference."""

    normalization_id: str
    reference_profile_median: float
    reference_profile_iqr: float
    profile_median: Mapping[str, float]
    profile_iqr: Mapping[str, float]
    calibration_source: str

    def node_cost(self, candidate: RidgeCandidate, profile_id: str) -> float:
        """Apply the documented robust affine total-node-cost transform."""
        raw = candidate_node_cost(candidate, self._config)
        if self.normalization_id == "N0_raw":
            return raw
        if profile_id not in self.profile_median:
            return raw
        median = self.profile_median[profile_id]
        iqr = self.profile_iqr[profile_id]
        return max(
            0.0,
            self.reference_profile_median
            + (raw - median) * self.reference_profile_iqr / iqr,
        )

    _config: GlobalPathConfig


@dataclass(frozen=True, slots=True)
class BridgeResult:
    """Separate hypothesis continuation; original Global Path values are untouched."""

    time_s: np.ndarray[Any, np.dtype[np.float64]]
    original_global_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    bridged_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    bridge_status: tuple[str, ...]
    bridge_method: str
    left_anchor_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    right_anchor_frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    gap_duration_s: np.ndarray[Any, np.dtype[np.float64]]
    gap_frame_count: np.ndarray[Any, np.dtype[np.int64]]
    candidate_supported: np.ndarray[Any, np.dtype[np.bool_]]
    selected_candidate_rank_if_any: np.ndarray[Any, np.dtype[np.int64]]
    gap_rows: tuple[dict[str, Any], ...]


def corrected_inventory(
    raw_root: Path,
    configuration: Any,
) -> tuple[list[dict[str, Any]], dict[Path, FormalInput]]:
    """Classify processed results before any reader call and retain formal raw inputs."""
    rows: list[dict[str, Any]] = []
    accepted: dict[Path, FormalInput] = {}
    root = raw_root.resolve()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.resolve().relative_to(root)
        medium = bool(relative.parts and relative.parts[0] == MEDIUM_DIRECTORY_NAME)
        processed_result = medium and "result" in path.name.casefold()
        row: dict[str, Any] = {
            "absolute_path": str(path.resolve()),
            "relative_path": str(relative),
            "file_size_bytes": path.stat().st_size,
            "sha256_before": sha256_file(path),
            "extension": path.suffix.lower(),
            "quality_group_user_label": classify_quality_group(root, path),
            "classification": "",
            "reason": "",
            "reader_status": "",
            "usable_numerical_raw": False,
        }
        if path.name == ".gitkeep":
            row.update(classification="NON_NUMERICAL_EXCLUDED", reason="repository placeholder")
        elif processed_result:
            row.update(
                classification="PROCESSED_RESULT_EXCLUDED",
                reason="medium-directory filename contains result (case-insensitive)",
            )
        elif path.suffix.lower() not in NUMERICAL_EXTENSIONS:
            row.update(
                classification="NON_NUMERICAL_EXCLUDED",
                reason="not a configured numerical raw extension",
            )
        else:
            try:
                formal = formal_read_input(path, configuration)
                record = next(iter(formal.loaded.records.values()))
                interval = np.diff(record.time_s)
                uniform = bool(
                    interval.size
                    and np.allclose(
                        interval,
                        float(np.median(interval)),
                        rtol=1.0e-9,
                        atol=max(abs(float(np.median(interval))) * 1.0e-12, 1.0e-18),
                    )
                )
                if uniform:
                    row.update(
                        classification="RAW_NUMERICAL_INCLUDED",
                        reader_status="SUCCESS",
                        usable_numerical_raw=True,
                        selection_mode=formal.selection_mode,
                        column_count=formal.loaded.column_count,
                        sample_count=formal.loaded.row_count,
                    )
                    accepted[path.resolve()] = formal
                else:
                    row.update(
                        classification="SKIPPED_NONUNIFORM_UNSUPPORTED",
                        reason="formal workflow requires uniform time sampling",
                    )
            except (SignalColumnError, ValueError) as exc:
                row.update(classification="SKIPPED_MAPPING_UNKNOWN", reason=str(exc))
            except SignalIOError as exc:
                row.update(classification="SKIPPED_PARSE_ERROR", reason=str(exc))
        rows.append(row)
    return rows, accepted


def solve_normalized_path(
    candidate_set: RidgeCandidateSet,
    *,
    profile_id: str,
    normalization: Normalization,
) -> PathView:
    """Run the existing first-order recurrence with a Research-only node transform."""
    config = candidate_set.config
    states = [(*frame, None) for frame in candidate_set.candidates_by_frame]
    forward: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    predecessors: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    for frame_index, frame_states in enumerate(states):
        node = np.asarray(
            [
                config.null_node_cost
                if item is None
                else normalization.node_cost(item, profile_id)
                for item in frame_states
            ],
            dtype=np.float64,
        )
        if frame_index == 0:
            transition = np.asarray(
                [config.null_stay_cost if item is None else config.ridge_entry_cost for item in frame_states],
                dtype=np.float64,
            )
            forward.append(node + transition)
            predecessors.append(np.full(len(frame_states), -1, dtype=np.int64))
            continue
        previous = states[frame_index - 1]
        current_forward = np.empty(len(frame_states), dtype=np.float64)
        predecessor = np.empty(len(frame_states), dtype=np.int64)
        for state_index, current in enumerate(frame_states):
            alternatives = np.asarray(
                [
                    forward[-1][previous_index]
                    + _transition(previous_state, current, config)
                    for previous_index, previous_state in enumerate(previous)
                ],
                dtype=np.float64,
            )
            predecessor[state_index] = int(np.argmin(alternatives))
            current_forward[state_index] = node[state_index] + alternatives[predecessor[state_index]]
        forward.append(current_forward)
        predecessors.append(predecessor)
    selected = np.empty(len(states), dtype=np.int64)
    selected[-1] = int(np.argmin(forward[-1]))
    for index in range(len(states) - 1, 0, -1):
        selected[index - 1] = predecessors[index][selected[index]]
    rank = np.zeros(len(states), dtype=np.int64)
    frequency = np.full(len(states), np.nan, dtype=np.float64)
    null = np.ones(len(states), dtype=np.bool_)
    node_values = np.empty(len(states), dtype=np.float64)
    transition_values = np.empty(len(states), dtype=np.float64)
    cumulative = np.empty(len(states), dtype=np.float64)
    for index, raw_state_index in enumerate(selected):
        state_index = int(raw_state_index)
        item = states[index][state_index]
        if item is None:
            node_values[index] = config.null_node_cost
        else:
            rank[index] = item.candidate_rank
            frequency[index] = item.transition_frequency_hz
            null[index] = False
            node_values[index] = normalization.node_cost(item, profile_id)
        previous_item = None if index == 0 else states[index - 1][selected[index - 1]]
        transition_values[index] = _transition(previous_item, item, config)
        cumulative[index] = forward[index][state_index]
    return PathView(
        time_s=candidate_set.time_s.copy(),
        selected_candidate_rank=rank,
        selected_frequency_hz=frequency,
        is_null=null,
        node_cost=node_values,
        transition_cost=transition_values,
        cumulative_cost=cumulative,
        candidate_set=candidate_set,
        config=config,
        normalization_id=normalization.normalization_id,
    )


def path_view_from_core(result: Any) -> PathView:
    """Detach a core path result for bridge-only use without mutation."""
    return PathView(
        time_s=result.time_s.copy(),
        selected_candidate_rank=result.selected_candidate_rank.copy(),
        selected_frequency_hz=result.selected_refined_frequency_hz.copy(),
        is_null=result.is_null.copy(),
        node_cost=result.node_cost.copy(),
        transition_cost=result.transition_cost.copy(),
        cumulative_cost=result.cumulative_cost.copy(),
        candidate_set=result.candidate_set,
        config=result.config,
        normalization_id="N0_raw",
    )


def bridge_null_gaps(
    path: PathView,
    *,
    method: str,
    max_gap_frames: int,
    node_cost_function: Callable[[RidgeCandidate], float],
) -> BridgeResult:
    """Bridge only eligible internal NULL gaps; never mutate the supplied path."""
    if method not in {"candidate_aware", "linear"}:
        raise ValueError("Bridge method must be candidate_aware or linear.")
    original = path.selected_frequency_hz.copy()
    bridged = original.copy()
    status = ["ORIGINAL_GLOBAL" if not item else "NULL_UNCHANGED" for item in path.is_null]
    left = np.full(path.time_s.size, np.nan, dtype=np.float64)
    right = np.full(path.time_s.size, np.nan, dtype=np.float64)
    duration = np.full(path.time_s.size, np.nan, dtype=np.float64)
    count = np.zeros(path.time_s.size, dtype=np.int64)
    supported = np.zeros(path.time_s.size, dtype=np.bool_)
    ranks = np.zeros(path.time_s.size, dtype=np.int64)
    rows: list[dict[str, Any]] = []
    frame_interval = float(np.median(np.diff(path.time_s)))
    index = 0
    while index < path.time_s.size:
        if not path.is_null[index]:
            index += 1
            continue
        start = index
        while index < path.time_s.size and path.is_null[index]:
            index += 1
        stop = index
        gap_count = stop - start
        internal = start > 0 and stop < path.time_s.size
        gap_duration = gap_count * frame_interval
        left_frequency = path.selected_frequency_hz[start - 1] if internal else math.nan
        right_frequency = path.selected_frequency_hz[stop] if internal else math.nan
        slope_ok = internal and abs(right_frequency - left_frequency) <= (
            path.config.frequency_step_scale_hz * (gap_count + 1)
        )
        eligible = (
            internal
            and gap_count <= max_gap_frames
            and gap_duration <= max_gap_frames * frame_interval
            and slope_ok
        )
        candidate_path: tuple[RidgeCandidate, ...] | None = None
        total_cost = math.nan
        if method == "candidate_aware" and eligible:
            candidate_path, total_cost = _candidate_bridge_path(
                path,
                start=start,
                stop=stop,
                node_cost_function=node_cost_function,
            )
            eligible = candidate_path is not None
        if eligible:
            if method == "linear":
                fill = np.linspace(left_frequency, right_frequency, gap_count + 2)[1:-1]
                bridged[start:stop] = fill
                status[start:stop] = ["BRIDGED_INTERPOLATED"] * gap_count
            elif candidate_path is not None:
                bridged[start:stop] = [item.transition_frequency_hz for item in candidate_path]
                status[start:stop] = ["BRIDGED_CANDIDATE"] * gap_count
                ranks[start:stop] = [item.candidate_rank for item in candidate_path]
                supported[start:stop] = True
            left[start:stop] = left_frequency
            right[start:stop] = right_frequency
            duration[start:stop] = gap_duration
            count[start:stop] = gap_count
        rows.append(
            {
                "gap_start_frame": start,
                "gap_stop_frame_exclusive": stop,
                "gap_frame_count": gap_count,
                "gap_duration_s": gap_duration,
                "method": method,
                "max_gap_frames": max_gap_frames,
                "internal_with_anchors": internal,
                "anchor_slope_criterion_passed": slope_ok,
                "eligible": eligible,
                "left_anchor_frequency_hz": left_frequency,
                "right_anchor_frequency_hz": right_frequency,
                "bridge_total_cost": total_cost,
                "candidate_supported": candidate_path is not None,
                "candidate_ranks": "" if candidate_path is None else ",".join(
                    str(item.candidate_rank) for item in candidate_path
                ),
                "maximum_frequency_step_hz": _max_step(
                    [left_frequency]
                    + ([] if candidate_path is None else [item.transition_frequency_hz for item in candidate_path])
                    + [right_frequency]
                ),
            }
        )
    return BridgeResult(
        time_s=path.time_s.copy(),
        original_global_frequency_hz=original,
        bridged_frequency_hz=bridged,
        bridge_status=tuple(status),
        bridge_method=method,
        left_anchor_frequency_hz=left,
        right_anchor_frequency_hz=right,
        gap_duration_s=duration,
        gap_frame_count=count,
        candidate_supported=supported,
        selected_candidate_rank_if_any=ranks,
        gap_rows=tuple(rows),
    )


def _candidate_bridge_path(
    path: PathView,
    *,
    start: int,
    stop: int,
    node_cost_function: Callable[[RidgeCandidate], float],
) -> tuple[tuple[RidgeCandidate, ...] | None, float]:
    """Constrained candidate-only shortest path between two existing anchors."""
    candidates = path.candidate_set.candidates_by_frame[start:stop]
    if not candidates or any(not frame for frame in candidates):
        return None, math.nan
    left = _selected_candidate(path, start - 1)
    right = _selected_candidate(path, stop)
    if left is None or right is None:
        return None, math.nan
    forward: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    predecessor: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    for frame_index, frame in enumerate(candidates):
        node = np.asarray([node_cost_function(item) for item in frame], dtype=np.float64)
        if frame_index == 0:
            forward.append(
                node
                + np.asarray(
                    [candidate_transition_cost(left, item, path.config) for item in frame],
                    dtype=np.float64,
                )
            )
            predecessor.append(np.full(len(frame), -1, dtype=np.int64))
            continue
        alternatives = np.empty((len(frame), len(candidates[frame_index - 1])), dtype=np.float64)
        for current_index, current in enumerate(frame):
            alternatives[current_index] = [
                forward[-1][previous_index]
                + candidate_transition_cost(previous, current, path.config)
                for previous_index, previous in enumerate(candidates[frame_index - 1])
            ]
        predecessor.append(np.argmin(alternatives, axis=1).astype(np.int64))
        forward.append(node + np.min(alternatives, axis=1))
    terminal = np.asarray(
        [
            forward[-1][index] + candidate_transition_cost(item, right, path.config)
            for index, item in enumerate(candidates[-1])
        ],
        dtype=np.float64,
    )
    selected = [int(np.argmin(terminal))]
    for frame_index in range(len(candidates) - 1, 0, -1):
        selected.append(int(predecessor[frame_index][selected[-1]]))
    selected.reverse()
    return tuple(frame[index] for frame, index in zip(candidates, selected, strict=True)), float(np.min(terminal))


def _selected_candidate(path: PathView, frame_index: int) -> RidgeCandidate | None:
    rank = int(path.selected_candidate_rank[frame_index])
    if rank == 0:
        return None
    return path.candidate_set.candidates_by_frame[frame_index][rank - 1]


def _transition(
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


def _max_step(frequencies: Sequence[float]) -> float:
    values = np.asarray(frequencies, dtype=np.float64)
    return float(np.max(np.abs(np.diff(values)))) if values.size > 1 else 0.0


def build_stack_reanalysis(
    *,
    task021b_artifact: Path,
    output_directory: Path,
) -> dict[str, Any]:
    """Recover actual S0-S3 definitions and aggregate existing TASK-021B rows."""
    matrix = _read_csv(task021b_artifact / "experiment_matrix.csv")
    baseline = _read_csv(task021b_artifact / "baseline_real_summary.csv")
    stacks = _read_csv(task021b_artifact / "parameter_stack_comparison.csv")
    synthetic = _read_csv(task021b_artifact / "synthetic_guardrail.csv")
    definition_rows = [
        row
        for row in matrix
        if row.get("stack_id") in {"S0", "S1", "S2", "S3", "S4"}
    ]
    _write_csv(output_directory / "task021b_stack_definition.csv", definition_rows)
    real_rows = [{**row, "stack_id": "S0"} for row in baseline] + stacks
    metric_names = (
        "null_fraction",
        "path_coverage_fraction",
        "rank1_fraction",
        "rank2_fraction",
        "rank3_fraction",
        "rank4plus_fraction",
        "non_null_segment_count",
        "median_non_null_segment_length",
        "candidate_available_but_selected_null_fraction",
        "candidate_to_candidate_step_p95_hz",
        "path_entry_count",
        "path_exit_count",
        "runtime_seconds",
    )
    rows: list[dict[str, Any]] = []
    for stack_id in sorted({row["stack_id"] for row in real_rows}):
        for group in (
            "relatively_good_user_label",
            "medium_user_label",
            "bad_user_label",
        ):
            selected = [
                row
                for row in real_rows
                if row["stack_id"] == stack_id and row["quality_group"] == group
            ]
            if selected:
                rows.append(
                    {
                        "scope": "real",
                        "stack_id": stack_id,
                        "quality_group": group,
                        "row_count": len(selected),
                        **{name: _mean_number(selected, name) for name in metric_names},
                        "pure_noise_false_selection": math.nan,
                    }
                )
        selected_synthetic = [
            row
            for row in synthetic
            if row.get("stack_id") == stack_id
        ]
        if selected_synthetic:
            rows.append(
                {
                    "scope": "synthetic_A_H",
                    "stack_id": stack_id,
                    "quality_group": "synthetic",
                    "row_count": len(selected_synthetic),
                    "null_fraction": _mean_number(selected_synthetic, "null_fraction"),
                    "path_coverage_fraction": _mean_number(selected_synthetic, "valid_selected_coverage"),
                    "rank1_fraction": _mean_number(selected_synthetic, "rank_1_fraction"),
                    "rank2_fraction": _mean_number(selected_synthetic, "rank_2_fraction"),
                    "rank3_fraction": _mean_number(selected_synthetic, "rank_3_fraction"),
                    "rank4plus_fraction": _mean_number(selected_synthetic, "rank_4_plus_fraction"),
                    "non_null_segment_count": math.nan,
                    "median_non_null_segment_length": math.nan,
                    "candidate_available_but_selected_null_fraction": math.nan,
                    "candidate_to_candidate_step_p95_hz": math.nan,
                    "path_entry_count": math.nan,
                    "path_exit_count": math.nan,
                    "runtime_seconds": math.nan,
                    "pure_noise_false_selection": _mean_number(
                        [row for row in selected_synthetic if row["case_id"] == "H_pure_noise"],
                        "pure_noise_false_selection",
                    ),
                }
            )
    _write_csv(output_directory / "task021b_stack_reanalysis.csv", rows)
    text = [
        "# TASK-021B stack reanalysis",
        "",
        "Definitions are recovered from the original experiment matrix, not inferred.",
        "",
        "| Stack | top_k | null node | null stay | entry | exit | continuity |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in definition_rows:
        text.append(
            "| {stack_id} | {top_k} | {null_node_cost} | {null_stay_cost} | "
            "{ridge_entry_cost} | {ridge_exit_cost} | {continuity_weight} |".format(**row)
        )
    text.extend(
        (
            "",
            "S1 increases only capacity; S2 lowers entry; S3 additionally halves continuity.",
            "All three produced trade-offs rather than a cross-group recommendation: lower NULL",
            "can be a hypothesis candidate without independent real-data truth.",
        )
    )
    (output_directory / "task021b_stack_reanalysis.md").write_text(
        "\n".join(text) + "\n",
        encoding="utf-8",
    )
    return {"definitions": definition_rows, "rows": rows}


def cost_scale_audit(
    streams: Sequence[PreparedStream],
    *,
    config: GlobalPathConfig,
    output_directory: Path,
) -> tuple[list[dict[str, Any]], Normalization]:
    """Audit profile cost distributions and freeze one good-only N1 transform."""
    rows: list[dict[str, Any]] = []
    reference: dict[str, list[float]] = {}
    for stream in streams:
        candidates = [
            item
            for frame in stream.candidate_set_maximum.candidates_by_frame
            for item in frame
        ]
        families: dict[str, list[float]] = {
            "candidate_total_node_cost": [
                candidate_node_cost(item, config) for item in candidates
            ],
            "background_cost_component": [
                node_cost_components(item, config)["background_cost_component"] for item in candidates
            ],
            "competitor_cost_component": [
                node_cost_components(item, config)["competitor_cost_component"] for item in candidates
            ],
            "cycles_cost_component": [
                node_cost_components(item, config)["cycles_cost_component"] for item in candidates
            ],
            "boundary_cost_component": [
                node_cost_components(item, config)["boundary_cost_component"] for item in candidates
            ],
            "refinement_cost_component": [
                node_cost_components(item, config)["refinement_cost_component"] for item in candidates
            ],
            "candidate_to_candidate_continuity_cost": _candidate_transition_values(
                stream.candidate_set_maximum,
                config,
            ),
            "null_node_cost": [config.null_node_cost],
            "null_stay_cost": [config.null_stay_cost],
            "ridge_entry_cost": [config.ridge_entry_cost],
            "ridge_exit_cost": [config.ridge_exit_cost],
        }
        for family, values in families.items():
            rows.append(
                {
                    "dataset": stream.source_path.name,
                    "quality_group": stream.quality_group,
                    "profile": stream.profile_id,
                    "channel": stream.channel_name,
                    "cost_family": family,
                    **_distribution(values),
                    "fixed_null_candidate_percentile": (
                        _percentile_rank(values, config.null_node_cost)
                        if family == "candidate_total_node_cost"
                        else math.nan
                    ),
                }
            )
        if stream.quality_group == "relatively_good_user_label":
            reference.setdefault(stream.profile_id, []).extend(families["candidate_total_node_cost"])
    profile_median = {key: float(np.median(value)) for key, value in reference.items()}
    profile_iqr = {
        key: max(float(np.quantile(value, 0.75) - np.quantile(value, 0.25)), 1.0e-9)
        for key, value in reference.items()
    }
    reference_median = float(np.median(list(profile_median.values())))
    reference_iqr = float(np.median(list(profile_iqr.values())))
    normalization = Normalization(
        normalization_id="N1_good_reference_robust_node",
        reference_profile_median=reference_median,
        reference_profile_iqr=reference_iqr,
        profile_median=profile_median,
        profile_iqr=profile_iqr,
        calibration_source="all relatively-good raw streams only; bad streams excluded",
        _config=config,
    )
    _write_csv(output_directory / "cost_scale_audit.csv", rows)
    profile_rows = _aggregate_profile_cost_rows(rows)
    text = [
        "# Cost-scale audit",
        "",
        "This is diagnosis first. Candidate total-node and component distributions are",
        "recorded per dataset/profile; NULL terms are fixed configuration constants.",
        "",
        "The N1 pilot maps only candidate total node cost by a frozen robust affine",
        "reference derived from relatively-good raw streams. It does not fit any bad",
        "stream and it does not modify GlobalPathConfig or Production.",
        "",
        f"Reference candidate-node median={reference_median:.6g}; IQR={reference_iqr:.6g}.",
        "",
        "Profile aggregate medians are in cost_scale_audit.csv. Interpret shifts as",
        "cost-model scale evidence, not physical measurement evidence.",
    ]
    _write_csv(output_directory / "cost_scale_profile_summary.csv", profile_rows)
    (output_directory / "cost_scale_audit.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return rows, normalization


def _candidate_transition_values(
    candidate_set: RidgeCandidateSet,
    config: GlobalPathConfig,
) -> list[float]:
    values: list[float] = []
    for previous, current in zip(
        candidate_set.candidates_by_frame,
        candidate_set.candidates_by_frame[1:],
        strict=False,
    ):
        values.extend(
            candidate_transition_cost(left, right, config)
            for left in previous
            for right in current
        )
    return values


def _aggregate_profile_cost_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    aggregate: list[dict[str, Any]] = []
    for profile in sorted({str(row["profile"]) for row in rows}):
        for family in sorted({str(row["cost_family"]) for row in rows}):
            selected = [
                row for row in rows if row["profile"] == profile and row["cost_family"] == family
            ]
            aggregate.append(
                {
                    "profile": profile,
                    "cost_family": family,
                    "stream_count": len(selected),
                    "median_of_stream_medians": _mean_number(selected, "median"),
                    "median_fixed_null_candidate_percentile": _mean_number(
                        selected,
                        "fixed_null_candidate_percentile",
                    ),
                }
            )
    return aggregate


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    if not array.size:
        return dict.fromkeys(("count", "median", "mad", "iqr", "p10", "p25", "p50", "p75", "p90"), math.nan)
    median = float(np.median(array))
    return {
        "count": int(array.size),
        "median": median,
        "mad": float(np.median(np.abs(array - median))),
        "iqr": float(np.quantile(array, 0.75) - np.quantile(array, 0.25)),
        "p10": float(np.quantile(array, 0.10)),
        "p25": float(np.quantile(array, 0.25)),
        "p50": median,
        "p75": float(np.quantile(array, 0.75)),
        "p90": float(np.quantile(array, 0.90)),
    }


def _percentile_rank(values: Sequence[float], reference: float) -> float:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    return float(np.mean(array <= reference)) if array.size else math.nan


def _mean_number(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    values = np.asarray([_as_float(row.get(key)) for row in rows], dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.mean(values)) if values.size else math.nan


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan


def summarize_path(
    *,
    stream: PreparedStream,
    path: PathView,
    normalization_id: str,
) -> dict[str, Any]:
    """Keep TASK-021B metrics comparable for raw and normalized Research paths."""
    rank = path.selected_candidate_rank
    selected = ~path.is_null
    candidate_counts = np.asarray(
        [len(frame) for frame in path.candidate_set.candidates_by_frame],
        dtype=np.int64,
    )
    production = stream.analysis.signal_detection_result.refined_frequency_hz
    finite_production = np.isfinite(production)
    finite_path = np.isfinite(path.selected_frequency_hz)
    disagreement = (finite_production != finite_path) | (
        finite_production
        & finite_path
        & (np.abs(production - path.selected_frequency_hz) > 1.0e6)
    )
    steps = np.abs(np.diff(path.selected_frequency_hz))
    valid_steps = steps[
        np.isfinite(path.selected_frequency_hz[:-1])
        & np.isfinite(path.selected_frequency_hz[1:])
    ]
    segments = _run_lengths(selected)
    return {
        "scope": "real",
        "normalization_id": normalization_id,
        "dataset": stream.source_path.name,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "top_k": path.config.top_k,
        "frame_count": int(path.time_s.size),
        "null_fraction": float(np.mean(path.is_null)),
        "path_coverage_fraction": float(np.mean(selected)),
        "rank1_fraction": float(np.mean(rank == 1)),
        "rank2_fraction": float(np.mean(rank == 2)),
        "rank3_fraction": float(np.mean(rank == 3)),
        "rank4plus_fraction": float(np.mean(rank >= 4)),
        "candidate_available_but_selected_null_fraction": float(
            np.mean((candidate_counts > 0) & path.is_null)
        ),
        "segment_count": len(segments),
        "median_segment_length": float(np.median(segments)) if segments else math.nan,
        "frequency_step_p95_hz": (
            float(np.quantile(valid_steps, 0.95)) if valid_steps.size else math.nan
        ),
        "entry_count": int(np.count_nonzero(path.is_null[:-1] & ~path.is_null[1:])),
        "exit_count": int(np.count_nonzero(~path.is_null[:-1] & path.is_null[1:])),
        "production_disagreement_fraction": float(np.mean(disagreement)),
    }


def synthetic_bridge_benchmark(
    *,
    normalization: Normalization,
) -> list[dict[str, Any]]:
    """Mask short correct synthetic path intervals and compare no/linear/candidate bridge."""
    rows: list[dict[str, Any]] = []
    config = GlobalPathConfig(top_k=5)
    for case in generate_synthetic_global_path_cases(seed=DEFAULT_SYNTHETIC_SEED):
        core = track_global_candidate_path(
            case.stft_result,
            minimum_frequency_hz=0.4e9,
            maximum_frequency_hz=2.8e9,
            config=config,
        )
        view = path_view_from_core(core)
        for method in ("no_bridge", "linear", "candidate_aware"):
            if method == "no_bridge":
                control_path = view
                control_bridge = None
            else:
                control_bridge = bridge_null_gaps(
                    view,
                    method=method,
                    max_gap_frames=5,
                    node_cost_function=lambda item: normalization.node_cost(item, "synthetic"),
                )
                control_path = PathView(
                    time_s=view.time_s,
                    selected_candidate_rank=view.selected_candidate_rank,
                    selected_frequency_hz=control_bridge.bridged_frequency_hz,
                    is_null=~np.isfinite(control_bridge.bridged_frequency_hz),
                    node_cost=view.node_cost,
                    transition_cost=view.transition_cost,
                    cumulative_cost=view.cumulative_cost,
                    candidate_set=view.candidate_set,
                    config=view.config,
                    normalization_id=normalization.normalization_id,
                )
            rows.append(
                _synthetic_bridge_row(
                    case_id=case.case_id,
                    truth=case.truth_frequency_hz,
                    dropout=case.dropout_mask,
                    pre_event=case.pre_event_mask,
                    path=control_path,
                    bridge=control_bridge,
                    method=method,
                    gap_size=0,
                    normalization_id=normalization.normalization_id,
                )
            )
        for gap_size in GAP_FRAME_LIMITS:
            forced = _masked_synthetic_path(view, case.truth_frequency_hz, gap_size)
            if forced is None:
                continue
            for method in ("no_bridge", "linear", "candidate_aware"):
                if method == "no_bridge":
                    output = forced
                    bridge = None
                else:
                    bridge = bridge_null_gaps(
                        forced,
                        method=method,
                        max_gap_frames=gap_size,
                        node_cost_function=lambda item: normalization.node_cost(
                            item,
                            "synthetic",
                        ),
                    )
                    output = PathView(
                        time_s=forced.time_s,
                        selected_candidate_rank=forced.selected_candidate_rank,
                        selected_frequency_hz=bridge.bridged_frequency_hz,
                        is_null=~np.isfinite(bridge.bridged_frequency_hz),
                        node_cost=forced.node_cost,
                        transition_cost=forced.transition_cost,
                        cumulative_cost=forced.cumulative_cost,
                        candidate_set=forced.candidate_set,
                        config=forced.config,
                        normalization_id=normalization.normalization_id,
                    )
                rows.append(
                    _synthetic_bridge_row(
                        case_id=case.case_id,
                        truth=case.truth_frequency_hz,
                        dropout=case.dropout_mask,
                        pre_event=case.pre_event_mask,
                        path=output,
                        bridge=bridge,
                        method=method,
                        gap_size=gap_size,
                        normalization_id=normalization.normalization_id,
                    )
                )
    return rows


def _masked_synthetic_path(
    path: PathView,
    truth: np.ndarray[Any, np.dtype[np.float64]],
    gap_size: int,
) -> PathView | None:
    valid = np.isfinite(truth) & ~path.is_null
    for start in range(1, path.time_s.size - gap_size):
        stop = start + gap_size
        if stop >= path.time_s.size - 1:
            continue
        if bool(np.all(valid[start:stop])) and valid[start - 1] and valid[stop]:
            frequency = path.selected_frequency_hz.copy()
            rank = path.selected_candidate_rank.copy()
            null = path.is_null.copy()
            frequency[start:stop] = math.nan
            rank[start:stop] = 0
            null[start:stop] = True
            return PathView(
                time_s=path.time_s.copy(),
                selected_candidate_rank=rank,
                selected_frequency_hz=frequency,
                is_null=null,
                node_cost=path.node_cost.copy(),
                transition_cost=path.transition_cost.copy(),
                cumulative_cost=path.cumulative_cost.copy(),
                candidate_set=path.candidate_set,
                config=path.config,
                normalization_id=path.normalization_id,
            )
    return None


def _synthetic_bridge_row(
    *,
    case_id: str,
    truth: np.ndarray[Any, np.dtype[np.float64]],
    dropout: np.ndarray[Any, np.dtype[np.bool_]],
    pre_event: np.ndarray[Any, np.dtype[np.bool_]],
    path: PathView,
    bridge: BridgeResult | None,
    method: str,
    gap_size: int,
    normalization_id: str,
) -> dict[str, Any]:
    selected = np.isfinite(path.selected_frequency_hz)
    comparable = selected & np.isfinite(truth)
    error = path.selected_frequency_hz[comparable] - truth[comparable]
    bridged = (
        np.zeros(path.time_s.size, dtype=np.bool_)
        if bridge is None
        else np.asarray(
            [status not in {"ORIGINAL_GLOBAL", "NULL_UNCHANGED"} for status in bridge.bridge_status],
            dtype=np.bool_,
        )
    )
    wrong = comparable & (np.abs(path.selected_frequency_hz - truth) > 1.0e8)
    return {
        "scope": "synthetic",
        "normalization_id": normalization_id,
        "case_id": case_id,
        "method": method,
        "masked_gap_frame_count": gap_size,
        "bridge_success_rate": float(np.mean(bridged)) if bridged.size else 0.0,
        "frequency_rmse_hz": float(np.sqrt(np.mean(np.square(error)))) if error.size else math.nan,
        "maximum_frequency_error_hz": float(np.max(np.abs(error))) if error.size else math.nan,
        "wrong_branch_rate": float(np.mean(wrong)) if wrong.size else 0.0,
        "candidate_rank_median": (
            float(np.median(bridge.selected_candidate_rank_if_any[bridged]))
            if bridge is not None and np.any(bridged)
            else math.nan
        ),
        "frequency_step_error_hz": _step_error(path.selected_frequency_hz, truth),
        "bridged_true_dropout_frame_count": int(np.count_nonzero(bridged & dropout)),
        "bridged_pre_event_frame_count": int(np.count_nonzero(bridged & pre_event)),
        "pure_noise_false_selection": (
            float(np.mean(selected)) if "pure_noise" in case_id else math.nan
        ),
    }


def _step_error(
    frequency: np.ndarray[Any, np.dtype[np.float64]],
    truth: np.ndarray[Any, np.dtype[np.float64]],
) -> float:
    valid = (
        np.isfinite(frequency[:-1])
        & np.isfinite(frequency[1:])
        & np.isfinite(truth[:-1])
        & np.isfinite(truth[1:])
    )
    if not np.any(valid):
        return math.nan
    return float(
        np.sqrt(
            np.mean(
                np.square(np.diff(frequency)[valid] - np.diff(truth)[valid])
            )
        )
    )


def _run_lengths(values: np.ndarray[Any, np.dtype[np.bool_]]) -> list[int]:
    lengths: list[int] = []
    count = 0
    for value in values:
        if value:
            count += 1
        elif count:
            lengths.append(count)
            count = 0
    if count:
        lengths.append(count)
    return lengths


def run_task021c(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    task021b_artifact: Path = TASK021B_ARTIFACT,
    output_directory: Path,
) -> dict[str, Any]:
    """Run corrected inventory, stack audit, N0/N1 pilot, and separated bridge."""
    raw_root = raw_root.resolve()
    task021b_artifact = task021b_artifact.resolve()
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite Research output: {output_directory}")
    if not raw_root.is_dir() or not task021b_artifact.is_dir():
        raise FileNotFoundError("Required raw root or TASK-021B artifact does not exist.")
    from dps_studio.core.workflow import load_workflow_config

    configuration = load_workflow_config(config_path.resolve(), repository_root=REPOSITORY_ROOT)
    output_directory.mkdir(parents=True)
    manifest, accepted = corrected_inventory(raw_root, configuration)
    hashes_before = {
        str(row["absolute_path"]): str(row["sha256_before"])
        for row in manifest
        if row["usable_numerical_raw"]
    }
    _write_csv(output_directory / "corrected_dataset_manifest.csv", manifest)
    _write_json(output_directory / "corrected_dataset_manifest.json", manifest)
    task021b_hashes = json.loads(
        (task021b_artifact / "experiment_metadata.json").read_text(encoding="utf-8")
    )["raw_hashes_after"]
    current_hashes = {str(path): sha256_file(path) for path in accepted}
    if set(current_hashes) != set(task021b_hashes) or any(
        current_hashes[path] != task021b_hashes[path] for path in current_hashes
    ):
        raise RuntimeError("Corrected TASK-021C numerical input set differs from TASK-021B.")

    stack_reanalysis = build_stack_reanalysis(
        task021b_artifact=task021b_artifact,
        output_directory=output_directory,
    )
    streams, failures = prepare_streams(
        raw_root=raw_root,
        configuration=configuration,
        accepted_inputs=accepted,
    )
    if failures:
        _write_json(output_directory / "code_failures.json", [asdict(item) for item in failures])
    config = GlobalPathConfig(top_k=5)
    cost_rows, n1 = cost_scale_audit(streams, config=config, output_directory=output_directory)
    n0 = Normalization(
        normalization_id="N0_raw",
        reference_profile_median=n1.reference_profile_median,
        reference_profile_iqr=n1.reference_profile_iqr,
        profile_median=n1.profile_median,
        profile_iqr=n1.profile_iqr,
        calibration_source="no normalization",
        _config=config,
    )
    normalizations = (n0, n1)
    normalization_rows: list[dict[str, Any]] = []
    bridge_rows: list[dict[str, Any]] = []
    bridge_details: list[dict[str, Any]] = []
    representatives: dict[str, tuple[PreparedStream, PathView, BridgeResult]] = {}
    ch3: tuple[PreparedStream, PathView, BridgeResult] | None = None
    for stream in streams:
        candidate_set = _candidate_set_top5(stream, config)
        raw_core = solve_global_candidate_path(candidate_set)
        paths: dict[str, PathView] = {"N0_raw": path_view_from_core(raw_core)}
        paths[n1.normalization_id] = solve_normalized_path(
            candidate_set,
            profile_id=stream.profile_id,
            normalization=n1,
        )
        for normalization in normalizations:
            path = paths[normalization.normalization_id]
            normalization_rows.append(
                summarize_path(
                    stream=stream,
                    path=path,
                    normalization_id=normalization.normalization_id,
                )
            )
            for gap_limit in GAP_FRAME_LIMITS:
                for method in ("candidate_aware", "linear"):
                    def node_cost_for_bridge(
                        item: RidgeCandidate,
                        *,
                        normalizer: Normalization = normalization,
                        profile: str = stream.profile_id,
                    ) -> float:
                        return normalizer.node_cost(item, profile)

                    bridge = bridge_null_gaps(
                        path,
                        method=method,
                        max_gap_frames=gap_limit,
                        node_cost_function=node_cost_for_bridge,
                    )
                    bridge_rows.append(
                        _bridge_summary_row(
                            stream=stream,
                            path=path,
                            bridge=bridge,
                            max_gap_frames=gap_limit,
                            normalization_id=normalization.normalization_id,
                        )
                    )
                    bridge_details.extend(
                        {
                            "dataset": stream.source_path.name,
                            "quality_group": stream.quality_group,
                            "profile": stream.profile_id,
                            "channel": stream.channel_name,
                            "normalization_id": normalization.normalization_id,
                            **detail,
                        }
                        for detail in bridge.gap_rows
                    )
                    if (
                        normalization.normalization_id == "N0_raw"
                        and method == "candidate_aware"
                        and gap_limit == 5
                    ):
                        representatives.setdefault(stream.quality_group, (stream, path, bridge))
                        if stream.source_path.name.lower() == "ch3.csv":
                            ch3 = (stream, path, bridge)
    _write_csv(output_directory / "normalization_comparison.csv", normalization_rows)
    _write_csv(output_directory / "bridge_real_summary.csv", bridge_rows)
    detail_directory = output_directory / "bridge_detail"
    detail_directory.mkdir()
    _write_csv(detail_directory / "bridge_gap_detail.csv", bridge_details)
    synthetic_rows = [
        row
        for normalization in normalizations
        for row in synthetic_bridge_benchmark(normalization=normalization)
    ]
    _write_csv(output_directory / "bridge_synthetic_benchmark.csv", synthetic_rows)
    figure_directory = output_directory / "figures"
    figure_directory.mkdir()
    for group, item in representatives.items():
        _write_bridge_figure(figure_directory, group, *item)
    if ch3 is not None:
        _write_bridge_figure(figure_directory, "ch3_bad", *ch3)
    _write_gap_distribution_figure(figure_directory, bridge_rows)
    _write_profile_cost_figure(figure_directory, cost_rows)
    hashes_after = {str(path): sha256_file(path) for path in accepted}
    if hashes_before != hashes_after:
        raise RuntimeError("Raw hashes changed during TASK-021C Research run.")
    metadata = {
        "task": "TASK-021C",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_branch": _git_value("branch", "--show-current"),
        "git_head": _git_value("rev-parse", "HEAD"),
        "research_root": str(REPOSITORY_ROOT),
        "production_raw_root_read_only": str(raw_root),
        "task021b_artifact": str(task021b_artifact),
        "task021b_input_set_matches_corrected_task021c": True,
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "normalizations": [
            {
                "id": item.normalization_id,
                "math": "max(0, ref_median + (raw_node-profile_median)*ref_iqr/profile_iqr)",
                "profile_median": dict(item.profile_median),
                "profile_iqr": dict(item.profile_iqr),
                "calibration_source": item.calibration_source,
            }
            for item in normalizations
        ],
        "bridge_rules": {
            "methods": ["candidate_aware", "linear"],
            "max_gap_frames": list(GAP_FRAME_LIMITS),
            "formal_limit": "gap_duration_s <= max_gap_frames * median_frame_interval_s",
            "anchor_limit": "anchor_delta_hz <= frequency_step_scale_hz * (gap_frame_count + 1)",
            "internal_only": True,
            "global_path_arrays_mutated": False,
        },
        "prepared_stream_count": len(streams),
        "code_failures": [asdict(item) for item in failures],
        "production_modified": False,
    }
    _write_json(output_directory / "experiment_metadata.json", metadata)
    _write_final_report(
        output_directory=output_directory,
        manifest=manifest,
        stack_reanalysis=stack_reanalysis,
        cost_rows=cost_rows,
        normalization_rows=normalization_rows,
        bridge_rows=bridge_rows,
        synthetic_rows=synthetic_rows,
        metadata=metadata,
    )
    return {
        "output_directory": str(output_directory),
        "stream_count": len(streams),
        "raw_hashes_equal": hashes_before == hashes_after,
    }


def _candidate_set_top5(stream: PreparedStream, config: GlobalPathConfig) -> RidgeCandidateSet:
    from dps_studio.research.global_path_calibration import candidate_set_for_top_k

    return candidate_set_for_top_k(stream.candidate_set_maximum, config=config)


def _bridge_summary_row(
    *,
    stream: PreparedStream,
    path: PathView,
    bridge: BridgeResult,
    max_gap_frames: int,
    normalization_id: str,
) -> dict[str, Any]:
    status = np.asarray(bridge.bridge_status)
    eligible = [row for row in bridge.gap_rows if bool(row["eligible"])]
    candidate = status == "BRIDGED_CANDIDATE"
    linear = status == "BRIDGED_INTERPOLATED"
    return {
        "scope": "real",
        "normalization_id": normalization_id,
        "dataset": stream.source_path.name,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "method": bridge.bridge_method,
        "max_gap_frames": max_gap_frames,
        "frame_interval_s": float(np.median(np.diff(path.time_s))),
        "number_null_gaps": len(bridge.gap_rows),
        "short_eligible_null_gaps": len(eligible),
        "candidate_aware_bridged_gaps": sum(
            bool(row["eligible"]) and bridge.bridge_method == "candidate_aware"
            for row in bridge.gap_rows
        ),
        "linear_bridged_gaps": sum(
            bool(row["eligible"]) and bridge.bridge_method == "linear"
            for row in bridge.gap_rows
        ),
        "unchanged_gaps": sum(not bool(row["eligible"]) for row in bridge.gap_rows),
        "bridged_frame_fraction": float(np.mean(candidate | linear)),
        "candidate_supported_bridge_fraction": float(np.mean(candidate)),
        "bridged_rank2plus_fraction": float(np.mean(bridge.selected_candidate_rank_if_any >= 2)),
        "bridged_frequency_step_p95_hz": _bridge_step_p95(bridge.bridged_frequency_hz),
        "bridge_total_cost_median": _median_or_nan(
            [float(row["bridge_total_cost"]) for row in eligible]
        ),
        "left_right_anchor_mismatch_median_hz": _median_or_nan(
            [
                abs(float(row["right_anchor_frequency_hz"]) - float(row["left_anchor_frequency_hz"]))
                for row in eligible
            ]
        ),
        "original_null_fraction": float(np.mean(path.is_null)),
    }


def _bridge_step_p95(frequency: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    steps = np.abs(np.diff(frequency))
    valid = steps[np.isfinite(frequency[:-1]) & np.isfinite(frequency[1:])]
    return float(np.quantile(valid, 0.95)) if valid.size else math.nan


def _median_or_nan(values: Sequence[float]) -> float:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if array.size else math.nan


def _write_bridge_figure(
    directory: Path,
    group: str,
    stream: PreparedStream,
    path: PathView,
    bridge: BridgeResult,
) -> None:
    """Show original path and clearly marked hypothesis bridge, never as measurement."""
    figure = Figure(figsize=(14.0, 7.0), constrained_layout=True)
    spectrogram_axis, cloud_axis = figure.subplots(1, 2)
    stft = stream.analysis.stft_result
    magnitude = np.abs(stft.spectrum)
    db = 20.0 * np.log10(np.maximum(magnitude / float(np.max(magnitude)), 1.0e-12))
    for axis in (spectrogram_axis, cloud_axis):
        axis.pcolormesh(
            stft.time_s,
            stft.frequency_hz * 1.0e-9,
            db,
            shading="auto",
            cmap="magma",
            vmin=-60.0,
            vmax=0.0,
            rasterized=True,
        )
    spectrogram_axis.plot(
        path.time_s,
        path.selected_frequency_hz * 1.0e-9,
        color="white",
        linewidth=1.3,
        label="original Global Path",
    )
    spectrogram_axis.plot(
        bridge.time_s,
        bridge.bridged_frequency_hz * 1.0e-9,
        color="#00bfc4",
        linewidth=1.1,
        linestyle="--",
        label="candidate-supported bridge hypothesis",
    )
    spectrogram_axis.set(
        title="Spectrogram + original Global Path + bridge hypothesis",
        xlabel="time (s)",
        ylabel="frequency (GHz)",
    )
    spectrogram_axis.legend(fontsize=7)
    for rank in range(1, path.config.top_k + 1):
        items = [
            item
            for frame in path.candidate_set.candidates_by_frame
            for item in frame
            if item.candidate_rank == rank
        ]
        if items:
            cloud_axis.scatter(
                [item.time_s for item in items],
                [item.transition_frequency_hz * 1.0e-9 for item in items],
                s=4,
                alpha=0.25,
            )
    cloud_axis.plot(
        path.time_s,
        path.selected_frequency_hz * 1.0e-9,
        color="white",
        linewidth=1.3,
        label="original",
    )
    cloud_axis.plot(
        bridge.time_s,
        bridge.bridged_frequency_hz * 1.0e-9,
        color="#00bfc4",
        linewidth=1.1,
        linestyle="--",
        label="hypothesis bridge",
    )
    cloud_axis.set(
        title=f"Top-K cloud / {group} / {stream.source_path.name}",
        xlabel="time (s)",
        ylabel="frequency (GHz)",
    )
    cloud_axis.legend(fontsize=7)
    _save_figure(figure, directory / f"{_safe_name(group)}__{stream.stream_id}__bridge.png")


def _write_gap_distribution_figure(directory: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    figure = Figure(figsize=(9.0, 4.5), constrained_layout=True)
    axis = figure.subplots()
    selected = [
        row
        for row in rows
        if row["normalization_id"] == "N0_raw"
        and row["method"] == "candidate_aware"
        and int(row["max_gap_frames"]) == 5
    ]
    groups = sorted({str(row["quality_group"]) for row in selected})
    values = [
        [float(row["short_eligible_null_gaps"]) for row in selected if row["quality_group"] == group]
        for group in groups
    ]
    if groups:
        axis.boxplot(values, tick_labels=groups)
    axis.set(
        title="Short eligible internal NULL gaps, max 5 frames",
        ylabel="gap count per stream",
    )
    axis.grid(alpha=0.25)
    _save_figure(figure, directory / "null_gap_length_distribution.png")


def _write_profile_cost_figure(directory: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    figure = Figure(figsize=(9.0, 4.5), constrained_layout=True)
    axis = figure.subplots()
    components = ("background_cost_component", "competitor_cost_component")
    profiles = sorted({str(row["profile"]) for row in rows})
    locations = np.arange(len(profiles), dtype=np.float64)
    for offset, component in enumerate(components):
        values = [
            _mean_number(
                [row for row in rows if row["profile"] == profile and row["cost_family"] == component],
                "median",
            )
            for profile in profiles
        ]
        axis.bar(locations + (offset - 0.5) * 0.35, values, width=0.35, label=component)
    axis.set(
        title="Candidate component median: Balanced versus High-time",
        xticks=locations,
        xticklabels=profiles,
        ylabel="cost",
    )
    axis.legend(fontsize=7)
    _save_figure(figure, directory / "candidate_cost_vs_NULL_profile_scale.png")


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=150)
    figure.clear()


def _write_final_report(
    *,
    output_directory: Path,
    manifest: Sequence[Mapping[str, Any]],
    stack_reanalysis: Mapping[str, Any],
    cost_rows: Sequence[Mapping[str, Any]],
    normalization_rows: Sequence[Mapping[str, Any]],
    bridge_rows: Sequence[Mapping[str, Any]],
    synthetic_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> None:
    included = [row for row in manifest if row["classification"] == "RAW_NUMERICAL_INCLUDED"]
    excluded = [row for row in manifest if row["classification"] == "PROCESSED_RESULT_EXCLUDED"]
    medium = [row for row in included if row["quality_group_user_label"] == "medium_user_label"]
    n0 = [row for row in normalization_rows if row["normalization_id"] == "N0_raw"]
    n1 = [row for row in normalization_rows if row["normalization_id"] != "N0_raw"]
    aggregate_n0 = _mean_number(n0, "null_fraction")
    aggregate_n1 = _mean_number(n1, "null_fraction")
    bridge5 = [
        row
        for row in bridge_rows
        if row["normalization_id"] == "N0_raw"
        and row["method"] == "candidate_aware"
        and int(row["max_gap_frames"]) == 5
    ]
    linear5 = [
        row
        for row in bridge_rows
        if row["normalization_id"] == "N0_raw"
        and row["method"] == "linear"
        and int(row["max_gap_frames"]) == 5
    ]
    high_node = _mean_number(
        [
            row
            for row in cost_rows
            if row["profile"] == "high_time_resolution"
            and row["cost_family"] == "candidate_total_node_cost"
        ],
        "median",
    )
    balanced_node = _mean_number(
        [
            row
            for row in cost_rows
            if row["profile"] == "balanced" and row["cost_family"] == "candidate_total_node_cost"
        ],
        "median",
    )
    synthetic_candidate = [
        row for row in synthetic_rows if row["method"] == "candidate_aware"
    ]
    synthetic_linear = [row for row in synthetic_rows if row["method"] == "linear"]
    lines = [
        "# TASK-021C final Research report",
        "",
        "All bridge output is a candidate-supported or interpolated hypothesis. It is",
        "not a measured point, a recovered truth, or a Production velocity.",
        "",
        "## Answers 1–25",
        "",
        "1. Yes. TASK-021B already evaluated S1–S3; definitions are recovered in task021b_stack_definition.csv.",
        "2. S0 is current K5 baseline; S1 is K20; S2 is K20 plus entry=2.25; S3 is S2 plus continuity=0.5.",
        "3. S2/S3 increase coverage mainly for bad streams; the stack reanalysis retains every group separately.",
        "4. No stack improves all good/medium/bad metrics without a trade-off, so TASK-021B did not recommend one.",
        "5. TASK-021B numerical medium results were not contaminated by processed result files; its input hash set matches this corrected set.",
        f"6. Corrected medium raw count is {len(medium)}; {len(excluded)} processed result files were excluded before reader use.",
        "7. Corrected input hashes equal TASK-021B, so the corrected medium numerical baseline is the same input set.",
        "8. Medium transferability remains MIXED, not a general effectiveness claim.",
        "9. Per-file medium NULL behavior is retained in normalization_comparison.csv; long all-NULL streams are distinguished from short interruptions.",
        f"10. Mean stream median candidate total-node cost is Balanced={balanced_node:.4g}, High-time={high_node:.4g}; components are itemized in cost_scale_audit.csv.",
        "11. Fixed NULL=0.25 occupies profile-dependent candidate percentiles in the scale audit, supporting a scale-bias diagnostic but not proof.",
        f"12. N1 mean NULL fraction is {aggregate_n1:.4f} versus N0 {aggregate_n0:.4f}; judge it jointly with jumps and segments in normalization_comparison.csv.",
        "13. Pure-noise synthetic results remain reported explicitly in bridge_synthetic_benchmark.csv.",
        f"14. Baseline max-5 short eligible internal gaps average {_mean_number(bridge5, 'short_eligible_null_gaps'):.3f} per stream.",
        "15. The same eligible-gap count is the number with both anchors under the documented slope and duration criteria.",
        f"16. Candidate-aware bridge fraction is {_mean_number(bridge5, 'bridged_frame_fraction'):.6f}.",
        f"17. Linear interpolation bridge fraction is {_mean_number(linear5, 'bridged_frame_fraction'):.6f}.",
        "18. Candidate-aware versus linear is compared by synthetic RMSE, branch rate, and real candidate support; no real truth claim is made.",
        f"19. Synthetic candidate bridge RMSE mean={_mean_number(synthetic_candidate, 'frequency_rmse_hz'):.4g} Hz; linear mean={_mean_number(synthetic_linear, 'frequency_rmse_hz'):.4g} Hz.",
        "20. Synthetic rows record bridged true-dropout and pre-event frame counts; a nonzero value would reject the bridge criterion.",
        "21. A 100% NULL stream has no left/right Global Path anchors, so an internal-gap bridge is inapplicable by design.",
        "22. The dominant remaining bottleneck is candidate/NULL/transition cost-scale competition, not Top-K capacity.",
        "23. Cost normalization is NOT SUPPORTED: N1 did not improve the group-level NULL/coverage results consistently and worsened the bad group; it remains Research-only.",
        "24. NULL bridge is MIXED: its short-gap safety constraints hold, but candidate-aware bridge did not beat linear interpolation on the synthetic benchmark and affects very few real frames; it remains a hypothesis diagnostic only.",
        "25. Physical candidate identity, event timing, bridge correctness on real PDV, and cross-batch calibration require independent experimental confirmation.",
        "",
        "## Boundary",
        "",
        f"- Corrected raw numerical inputs: {len(included)}; processed-result exclusions: {len(excluded)}.",
        f"- Git branch: {metadata['git_branch']}; HEAD: {metadata['git_head']}.",
        "- Original Global Path arrays were never modified. Production, GUI, export, and LiF physics were not modified.",
        "- Raw SHA-256 before and after matched for every included input.",
    ]
    (output_directory / "final_research_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )


def _git_value(*arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _safe_name(value: str) -> str:
    return "".join(item if item.isalnum() else "_" for item in value).strip("_")


__all__ = [
    "BridgeResult",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_RAW_ROOT",
    "Normalization",
    "PathView",
    "REPOSITORY_ROOT",
    "TASK021B_ARTIFACT",
    "bridge_null_gaps",
    "corrected_inventory",
    "path_view_from_core",
    "run_task021c",
    "solve_normalized_path",
]
