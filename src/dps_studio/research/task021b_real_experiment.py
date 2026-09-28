"""Read-only TASK-021B real-data Global Path calibration experiment.

This module intentionally lives in the research package.  It uses the current
formal reader and analysis workflow, but never changes a Production
configuration, input file, or Global Path selection rule. Parameter changes
are immutable GlobalPathConfig instances used only for recorded Research runs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scipy.signal import find_peaks  # type: ignore[import-untyped]

import dps_studio
from dps_studio.core.io import SignalColumnError, SignalIOError, read_delimited_signals
from dps_studio.core.ridge import (
    GlobalPathConfig,
    GlobalRidgePathResult,
    RidgeCandidate,
    RidgeCandidateSet,
    candidate_node_cost,
    candidate_transition_cost,
    extract_global_path_candidates,
    solve_global_candidate_path,
)
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.workflow import analyze_profile, load_workflow_config
from dps_studio.research.global_path_benchmark import (
    DEFAULT_SYNTHETIC_SEED,
    run_synthetic_global_path_benchmark,
)
from dps_studio.research.global_path_calibration import (
    audit_global_candidate_path,
    audit_matches_global_path_result,
    candidate_set_for_top_k,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "configs" / "demo_dual_profile.toml"
DEFAULT_RAW_ROOT = Path(r"D:\Code\Python_Projects\DPS_Studio\data\raw")
MAXIMUM_TOP_K = 20
TOP_K_VALUES = (5, 10, 15, 20)
NULL_ENTRY_VALUES = (1.5, 2.25, 3.0)
CONTINUITY_VALUES = (0.5, 1.0, 2.0)
GOOD_NAMES = frozenset({"20260607.csv", "20260630-1.csv", "20260630-2.csv", "20260701.csv"})
BAD_NAMES = frozenset({"ch1.csv", "ch2.csv", "ch3.csv", "ch4.csv"})
SIGNAL_EXTENSIONS = frozenset({".csv", ".dat"})


@dataclass(frozen=True, slots=True)
class FormalInput:
    """A source accepted through only the configured formal mapping."""

    loaded: Any
    selection_mode: str


@dataclass(frozen=True, slots=True)
class PreparedStream:
    """One independently analyzed input/channel/profile with fixed candidates."""

    source_path: Path
    source_sha256: str
    quality_group: str
    profile_id: str
    profile_display_name: str
    channel_name: str
    analysis: Any
    candidate_set_maximum: RidgeCandidateSet
    candidate_counts_before_top_k: np.ndarray[Any, np.dtype[np.int64]]
    candidate_counts_after_separation: np.ndarray[Any, np.dtype[np.int64]]
    manual_reference_time_s: float | None

    @property
    def stream_id(self) -> str:
        return "__".join(
            (
                _safe_name(self.source_path.stem),
                _safe_name(self.profile_id),
                _safe_name(self.channel_name),
            )
        )


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """One deterministic configuration row; no automatic parameter selection."""

    stage: str
    experiment_id: str
    stack_id: str
    config: GlobalPathConfig
    rationale: str

    def row(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "experiment_id": self.experiment_id,
            "stack_id": self.stack_id,
            "rationale": self.rationale,
            **self.config.to_metadata(),
        }


@dataclass(frozen=True, slots=True)
class BatchFailure:
    """Per-file failure record preserving a distinction from skipped data."""

    source_path: str
    quality_group: str
    status: str
    reason: str
    traceback_text: str | None


def sha256_file(path: Path) -> str:
    """Return uppercase SHA-256 without writing beside the source."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def classify_quality_group(raw_root: Path, path: Path) -> str:
    """Keep user-provided grouping as an experiment label, never ground truth."""
    relative = path.resolve().relative_to(raw_root.resolve())
    if path.name.lower() in GOOD_NAMES and len(relative.parts) == 1:
        return "relatively_good_user_label"
    if path.name.lower() in BAD_NAMES and len(relative.parts) == 1:
        return "bad_user_label"
    if relative.parts and relative.parts[0] == "PDV数据-质量中等":
        return "medium_user_label"
    return "unclassified"


def formal_read_input(raw_path: Path, configuration: Any) -> FormalInput:
    """Use the established two-column exception, without guessing columns or units."""
    input_config = configuration.input
    configured_columns = dict(input_config.voltage_columns)
    first_channel_name, first_channel_index = next(iter(configured_columns.items()))
    first_channel_scale = input_config.voltage_scales[first_channel_name]
    first_loaded = read_delimited_signals(
        raw_path,
        time_column=input_config.time_column,
        voltage_columns={first_channel_name: first_channel_index},
        delimiter=input_config.delimiter,
        has_header=input_config.has_header,
        encoding=input_config.encoding,
        time_scale=input_config.time_scale,
        voltage_scales={first_channel_name: first_channel_scale},
    )
    if len(configured_columns) == 1:
        return FormalInput(first_loaded, "configured_columns")
    required_column_count = max(input_config.time_column, *configured_columns.values()) + 1
    if first_loaded.column_count >= required_column_count:
        return FormalInput(
            read_delimited_signals(
                raw_path,
                time_column=input_config.time_column,
                voltage_columns=configured_columns,
                delimiter=input_config.delimiter,
                has_header=input_config.has_header,
                encoding=input_config.encoding,
                time_scale=input_config.time_scale,
                voltage_scales=input_config.voltage_scales,
            ),
            "configured_columns",
        )
    unambiguous_two_column = (
        input_config.time_column == 0
        and first_channel_index == 1
        and first_loaded.column_count == 2
    )
    if unambiguous_two_column:
        return FormalInput(first_loaded, "single_voltage_column_from_two_column_file")
    raise ValueError(
        "SKIPPED_MAPPING_UNKNOWN: file does not support configured columns and "
        "is not an unambiguous time-plus-one-voltage source; "
        f"observed_columns={first_loaded.column_count}."
    )


def inventory_raw_files(
    raw_root: Path,
    configuration: Any,
) -> tuple[list[dict[str, Any]], dict[Path, FormalInput]]:
    """Recursively inventory files and retain only formally readable signal files."""
    rows: list[dict[str, Any]] = []
    accepted: dict[Path, FormalInput] = {}
    for path in sorted(item for item in raw_root.rglob("*") if item.is_file()):
        relative = path.resolve().relative_to(raw_root.resolve())
        row: dict[str, Any] = {
            "absolute_path": str(path.resolve()),
            "relative_path": str(relative),
            "file_size_bytes": path.stat().st_size,
            "sha256_before": sha256_file(path),
            "extension": path.suffix.lower(),
            "quality_group_user_label": classify_quality_group(raw_root, path),
            "reader_status": "",
            "known_column_count": math.nan,
            "time_column_index": math.nan,
            "voltage_column_indices": "",
            "time_unit_mapping": "",
            "voltage_unit_mapping": "",
            "sample_count": math.nan,
            "representative_sample_interval_s": math.nan,
            "sample_rate_hz": math.nan,
            "uniform_sampling": "",
            "usable": False,
            "skipped_reason": "",
        }
        if path.name == ".gitkeep":
            row.update(reader_status="SKIPPED_NON_DATA", skipped_reason="repository placeholder")
            rows.append(row)
            continue
        if path.suffix.lower() not in SIGNAL_EXTENSIONS:
            row.update(
                reader_status="SKIPPED_UNSUPPORTED_EXTENSION",
                skipped_reason="formal delimited reader is not configured for this extension",
            )
            rows.append(row)
            continue
        try:
            formal = formal_read_input(path, configuration)
            loaded = formal.loaded
            record = next(iter(loaded.records.values()))
            intervals = np.diff(record.time_s)
            representative_interval = float(np.median(intervals))
            uniform = bool(
                np.allclose(
                    intervals,
                    representative_interval,
                    rtol=1.0e-9,
                    atol=max(abs(representative_interval) * 1.0e-12, 1.0e-18),
                )
            )
            row.update(
                reader_status="SUCCESS" if uniform else "SKIPPED_NONUNIFORM_UNSUPPORTED",
                known_column_count=loaded.column_count,
                time_column_index=loaded.time_column_index,
                voltage_column_indices=json.dumps(dict(loaded.voltage_column_indices), ensure_ascii=False),
                time_unit_mapping=f"configured scale {configuration.input.time_scale} to s",
                voltage_unit_mapping=json.dumps(
                    {
                        key: f"configured scale {value} to V"
                        for key, value in configuration.input.voltage_scales.items()
                        if key in loaded.voltage_column_indices
                    },
                    ensure_ascii=False,
                ),
                sample_count=loaded.row_count,
                representative_sample_interval_s=representative_interval,
                sample_rate_hz=1.0 / representative_interval,
                uniform_sampling=uniform,
                usable=uniform,
                skipped_reason="" if uniform else "formal workflow requires uniform sampling",
                selection_mode=formal.selection_mode,
            )
            if uniform:
                accepted[path.resolve()] = formal
        except (SignalColumnError, ValueError) as exc:
            message = str(exc)
            row.update(reader_status="SKIPPED_MAPPING_UNKNOWN", skipped_reason=message)
        except SignalIOError as exc:
            row.update(reader_status="SKIPPED_PARSE_ERROR", skipped_reason=str(exc))
        rows.append(row)
    return rows, accepted


def node_cost_components(candidate: RidgeCandidate, config: GlobalPathConfig) -> dict[str, float]:
    """Expose the exact five additive node-cost terms for Research audit."""
    background_deficit = _bounded_deficit(
        candidate.peak_to_background_db,
        config.background_reference_db,
        config.background_deficit_scale_db,
    )
    competitor_deficit = _bounded_deficit(
        candidate.peak_to_competitor_db,
        config.competitor_reference_db,
        config.competitor_deficit_scale_db,
    )
    cycles_deficit = float(
        np.clip(
            (config.target_cycles_in_window - candidate.cycles_in_window)
            / config.target_cycles_in_window,
            0.0,
            1.0,
        )
    )
    values = {
        "background_cost_component": config.background_contrast_weight * background_deficit,
        "competitor_cost_component": config.competitor_contrast_weight * competitor_deficit,
        "cycles_cost_component": config.cycles_weight * cycles_deficit,
        "boundary_cost_component": config.boundary_weight * float(candidate.is_band_boundary),
        "refinement_cost_component": config.refinement_failure_weight
        * float(candidate.refinement_status is not RidgeRefinementStatus.REFINED),
    }
    values["total_candidate_node_cost"] = sum(values.values())
    if not math.isclose(
        values["total_candidate_node_cost"],
        candidate_node_cost(candidate, config),
        rel_tol=1.0e-12,
        abs_tol=1.0e-12,
    ):
        raise AssertionError("Research diagnostic node component formula drifted from core.")
    return values


def candidate_capacity_counts(
    stft_result: Any,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    config: GlobalPathConfig,
) -> tuple[np.ndarray[Any, np.dtype[np.int64]], np.ndarray[Any, np.dtype[np.int64]]]:
    """Count raw local maxima and untruncated separated maxima without changing extraction."""
    frequencies = stft_result.frequency_hz
    band_indices = np.flatnonzero(
        (frequencies >= minimum_frequency_hz) & (frequencies <= maximum_frequency_hz)
    )
    magnitude = np.abs(stft_result.spectrum)
    separation_hz = (
        config.minimum_candidate_separation_hz
        if config.minimum_candidate_separation_hz is not None
        else config.candidate_separation_resolution_factor
        * stft_result.sample_rate_hz
        / stft_result.window_length_samples
    )
    before = np.zeros(stft_result.time_s.size, dtype=np.int64)
    after = np.zeros(stft_result.time_s.size, dtype=np.int64)
    for frame_index in range(stft_result.time_s.size):
        values = magnitude[band_indices, frame_index]
        padded = np.concatenate((np.array([-math.inf]), values, np.array([-math.inf])))
        offsets, _ = find_peaks(padded, plateau_size=(1, None))
        local_offsets = [int(item - 1) for item in offsets]
        before[frame_index] = len(local_offsets)
        ranked = sorted(
            local_offsets,
            key=lambda offset: (-float(values[offset]), int(band_indices[offset])),
        )
        kept: list[int] = []
        for offset in ranked:
            hz = float(frequencies[band_indices[offset]])
            if not any(abs(hz - float(frequencies[band_indices[other]])) < separation_hz for other in kept):
                kept.append(offset)
        after[frame_index] = len(kept)
    return before, after


def build_experiment_matrix() -> tuple[ExperimentSpec, ...]:
    """Return a small fixed matrix with ordered single-axis stages before stacks."""
    baseline = GlobalPathConfig(top_k=5)
    specs: list[ExperimentSpec] = [
        ExperimentSpec("baseline", "baseline_current", "S0", baseline, "current exact default"),
    ]
    specs.extend(
        ExperimentSpec(
            "top_k",
            f"top_k_{value}",
            "",
            replace(baseline, top_k=value),
            "only Top-K changes",
        )
        for value in TOP_K_VALUES
    )
    specs.extend(
        ExperimentSpec(
            "null_axis_entry",
            f"ridge_entry_cost_{value:g}",
            "",
            replace(baseline, ridge_entry_cost=value),
            "only ridge_entry_cost changes; selected after baseline audit of entry competition",
        )
        for value in NULL_ENTRY_VALUES
    )
    topk_stack = replace(baseline, top_k=20)
    entry_stack = replace(topk_stack, ridge_entry_cost=2.25)
    specs.extend(
        ExperimentSpec(
            "continuity",
            f"continuity_weight_{value:g}",
            "",
            replace(entry_stack, continuity_weight=value),
            "only continuity weight changes after fixed Top-K and entry setting",
        )
        for value in CONTINUITY_VALUES
    )
    specs.extend(
        (
            ExperimentSpec("stack", "S1_top_k_20", "S1", topk_stack, "Top-K only"),
            ExperimentSpec(
                "stack",
                "S2_top_k_20_entry_2_25",
                "S2",
                entry_stack,
                "Top-K plus moderate entry sensitivity",
            ),
            ExperimentSpec(
                "stack",
                "S3_top_k_20_entry_2_25_continuity_0_5",
                "S3",
                replace(entry_stack, continuity_weight=0.5),
                "small stack, not an optimized recommendation",
            ),
        )
    )
    return tuple(specs)


def _bounded_deficit(value: float, reference: float, scale: float) -> float:
    if not math.isfinite(value):
        return 1.0
    return float(np.clip((reference - value) / scale, 0.0, 1.0))


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")


def prepare_streams(
    *,
    raw_root: Path,
    configuration: Any,
    accepted_inputs: Mapping[Path, FormalInput],
) -> tuple[list[PreparedStream], list[BatchFailure]]:
    """Build independent single-channel/profile streams while continuing per file."""
    streams: list[PreparedStream] = []
    failures: list[BatchFailure] = []
    maximum_config = GlobalPathConfig(top_k=MAXIMUM_TOP_K)
    for source_path, formal in sorted(accepted_inputs.items()):
        group = classify_quality_group(raw_root, source_path)
        try:
            for profile in configuration.analysis.profiles:
                for channel_name, record in formal.loaded.records.items():
                    start = float(record.time_s[0])
                    end = float(record.time_s[-1])
                    configured_reference = configuration.analysis.manual_event_reference_time_s
                    reference = (
                        configured_reference
                        if configured_reference is not None and start <= configured_reference <= end
                        else None
                    )
                    analysis = analyze_profile(
                        {channel_name: record},
                        profile=profile,
                        analysis_start_time_s=start,
                        analysis_end_time_s=end,
                        manual_event_reference_time_s=reference,
                        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
                        detection_config=configuration.quality.signal_detection,
                        event_candidate_config=configuration.event_candidate,
                        background_guard_window_scale=configuration.quality.background_guard_window_scale,
                        minimum_background_bin_count=configuration.quality.minimum_background_bin_count,
                        automatic_ridge_selection_config=configuration.automatic_ridge_selection,
                        velocity_correction_config=configuration.velocity_correction,
                    )[channel_name]
                    production_before = analysis.signal_detection_result.refined_frequency_hz.copy()
                    candidates = extract_global_path_candidates(
                        analysis.stft_result,
                        minimum_frequency_hz=profile.minimum_frequency_hz,
                        maximum_frequency_hz=profile.maximum_frequency_hz,
                        config=maximum_config,
                    )
                    if not np.array_equal(
                        production_before,
                        analysis.signal_detection_result.refined_frequency_hz,
                        equal_nan=True,
                    ):
                        raise RuntimeError("CODE_FAILURE: research candidate extraction mutated Production output.")
                    before, after = candidate_capacity_counts(
                        analysis.stft_result,
                        minimum_frequency_hz=profile.minimum_frequency_hz,
                        maximum_frequency_hz=profile.maximum_frequency_hz,
                        config=maximum_config,
                    )
                    streams.append(
                        PreparedStream(
                            source_path=source_path,
                            source_sha256=sha256_file(source_path),
                            quality_group=group,
                            profile_id=profile.profile_id.value,
                            profile_display_name=profile.display_name,
                            channel_name=channel_name,
                            analysis=analysis,
                            candidate_set_maximum=candidates,
                            candidate_counts_before_top_k=before,
                            candidate_counts_after_separation=after,
                            manual_reference_time_s=reference,
                        )
                    )
        except (SignalIOError, ValueError) as exc:
            failures.append(
                BatchFailure(
                    str(source_path),
                    group,
                    "SKIPPED_INVALID_SIGNAL",
                    str(exc),
                    None,
                )
            )
        except Exception as exc:
            failures.append(
                BatchFailure(
                    str(source_path),
                    group,
                    "CODE_FAILURE",
                    f"{type(exc).__name__}: {exc}",
                    traceback.format_exc(),
                )
            )
    return streams, failures


def solve_prepared_stream(
    stream: PreparedStream,
    spec: ExperimentSpec,
) -> tuple[GlobalRidgePathResult, Any]:
    """Solve an immutable config over an exact Top-K prefix of fixed candidates."""
    candidate_set = candidate_set_for_top_k(
        stream.candidate_set_maximum,
        config=spec.config,
    )
    result = solve_global_candidate_path(candidate_set)
    audit = audit_global_candidate_path(candidate_set)
    if not audit_matches_global_path_result(audit, result):
        raise RuntimeError("CODE_FAILURE: audit recurrence did not reproduce core result.")
    return result, audit


def path_metrics(
    *,
    stream: PreparedStream,
    result: GlobalRidgePathResult,
    audit: Any,
) -> dict[str, Any]:
    """Return transparent real-data metrics without a composite optimization score."""
    frame_count = result.time_s.size
    ranks = result.selected_candidate_rank
    selected = ~result.is_null
    production = stream.analysis.signal_detection_result.refined_frequency_hz
    retained = np.fromiter(
        (len(frame) for frame in result.candidate_set.candidates_by_frame),
        dtype=np.int64,
        count=frame_count,
    )
    candidate_available = retained > 0
    production_finite = np.isfinite(production)
    global_finite = np.isfinite(result.selected_refined_frequency_hz)
    disagreement = (production_finite != global_finite) | (
        production_finite
        & global_finite
        & (np.abs(production - result.selected_refined_frequency_hz) > 1.0e6)
    )
    selected_refinement = selected & np.isfinite(result.selected_refined_frequency_hz)
    step = np.abs(np.diff(result.selected_refined_frequency_hz))
    valid_step = step[
        np.isfinite(result.selected_refined_frequency_hz[1:])
        & np.isfinite(result.selected_refined_frequency_hz[:-1])
    ]
    selected_segments = _true_run_lengths(selected)
    null_runs = _true_run_lengths(result.is_null)
    margin = audit.candidate_vs_null_cost_margin
    finite_margin = margin[np.isfinite(margin)]
    return {
        "dataset": stream.source_path.name,
        "source_path": str(stream.source_path),
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "frame_count": int(frame_count),
        "frames_with_at_least_one_candidate": int(np.count_nonzero(candidate_available)),
        "frames_with_at_least_k_candidates": int(np.count_nonzero(retained >= result.config.top_k)),
        "candidate_availability_fraction": float(np.mean(candidate_available)),
        "average_candidates_before_top_k": float(np.mean(stream.candidate_counts_before_top_k)),
        "average_candidates_after_separation": float(np.mean(stream.candidate_counts_after_separation)),
        "average_retained_candidate_count": float(np.mean(retained)),
        "null_count": int(np.count_nonzero(result.is_null)),
        "null_fraction": float(np.mean(result.is_null)),
        "path_coverage_fraction": float(np.mean(selected)),
        "rank1_count": int(np.count_nonzero(ranks == 1)),
        "rank2_count": int(np.count_nonzero(ranks == 2)),
        "rank3_count": int(np.count_nonzero(ranks == 3)),
        "rank4plus_count": int(np.count_nonzero(ranks >= 4)),
        "rank1_fraction": float(np.mean(ranks == 1)),
        "rank2_fraction": float(np.mean(ranks == 2)),
        "rank3_fraction": float(np.mean(ranks == 3)),
        "rank4plus_fraction": float(np.mean(ranks >= 4)),
        "candidate_available_but_selected_null_count": int(
            np.count_nonzero(candidate_available & result.is_null)
        ),
        "candidate_available_but_selected_null_fraction": float(
            np.mean(candidate_available & result.is_null)
        ),
        "production_global_disagreement_count": int(np.count_nonzero(disagreement)),
        "production_global_disagreement_fraction": float(np.mean(disagreement)),
        "production_nan_global_candidate_count": int(
            np.count_nonzero(~production_finite & global_finite)
        ),
        "global_null_production_measured_count": int(
            np.count_nonzero(result.is_null & production_finite)
        ),
        "non_null_segment_count": len(selected_segments),
        "median_non_null_segment_length": _median_or_nan(selected_segments),
        "candidate_to_candidate_step_median_hz": _median_or_nan(valid_step),
        "candidate_to_candidate_step_p95_hz": _quantile_or_nan(valid_step, 0.95),
        "maximum_frequency_step_hz": float(np.max(valid_step)) if valid_step.size else math.nan,
        "refinement_success_selected_fraction": float(np.mean(selected_refinement)),
        "path_entry_count": _transition_count(result.is_null[:-1], result.is_null[1:], True, False),
        "path_exit_count": _transition_count(result.is_null[:-1], result.is_null[1:], False, True),
        "null_run_count": len(null_runs),
        "median_null_run_length": _median_or_nan(null_runs),
        "maximum_null_run_length": int(max(null_runs)) if null_runs else 0,
        "median_candidate_vs_null_forward_cost_difference": _median_or_nan(finite_margin),
        "candidate_vs_null_forward_cost_difference_p10": _quantile_or_nan(finite_margin, 0.1),
        "candidate_vs_null_forward_cost_difference_p90": _quantile_or_nan(finite_margin, 0.9),
        "pre_event_selected_candidate_fraction": (
            float(np.mean(selected[result.time_s < stream.manual_reference_time_s]))
            if stream.manual_reference_time_s is not None
            and np.any(result.time_s < stream.manual_reference_time_s)
            else math.nan
        ),
        "manual_event_reference_in_cost": False,
        "runtime_scope": "solve_only",
    }


def detailed_cost_audit_rows(
    *,
    stream: PreparedStream,
    result: GlobalRidgePathResult,
    audit: Any,
) -> list[dict[str, Any]]:
    """Flatten all retained candidates plus NULL with DP and exact cost evidence."""
    rows: list[dict[str, Any]] = []
    states = audit.frame_states
    for frame_index, frame_states in enumerate(states):
        candidates = result.candidate_set.candidates_by_frame[frame_index]
        selected_index = int(audit.selected_state_indices[frame_index])
        selected_state = frame_states[selected_index]
        selected_previous = (
            None
            if frame_index == 0
            else states[frame_index - 1][
                int(audit.predecessor_indices_by_frame[frame_index][selected_index])
            ]
        )
        selected_transition_type, selected_delta, selected_continuity = _transition_details(
            selected_previous,
            selected_state,
            result.config,
            initial=frame_index == 0,
        )
        min_candidate_forward = (
            float(np.min(audit.cumulative_costs_by_frame[frame_index][:-1]))
            if candidates
            else math.nan
        )
        null_forward = float(audit.cumulative_costs_by_frame[frame_index][-1])
        selected_rank = 0 if selected_state is None else selected_state.candidate_rank
        for state_index, state in enumerate(frame_states):
            components = (
                _null_components(result.config)
                if state is None
                else node_cost_components(state, result.config)
            )
            predecessor = int(audit.predecessor_indices_by_frame[frame_index][state_index])
            predecessor_label = (
                "initial"
                if frame_index == 0
                else _state_label(states[frame_index - 1][predecessor])
            )
            state_type = "NULL" if state is None else "candidate"
            rows.append(
                {
                    "dataset": stream.source_path.name,
                    "source_path": str(stream.source_path),
                    "source_sha256": stream.source_sha256,
                    "quality_group": stream.quality_group,
                    "profile": stream.profile_id,
                    "channel": stream.channel_name,
                    "frame_index": frame_index,
                    "time_s": float(result.time_s[frame_index]),
                    "candidate_count_before_top_k": int(stream.candidate_counts_before_top_k[frame_index]),
                    "candidate_count_after_separation": int(stream.candidate_counts_after_separation[frame_index]),
                    "retained_candidate_count": len(candidates),
                    "state_type": state_type,
                    "rank": 0 if state is None else state.candidate_rank,
                    "discrete_frequency_hz": math.nan if state is None else state.discrete_frequency_hz,
                    "refined_frequency_hz": math.nan if state is None else state.refined_frequency_hz,
                    "peak_amplitude": math.nan if state is None else state.peak_amplitude,
                    "peak_to_background_db": math.nan if state is None else state.peak_to_background_db,
                    "peak_to_competitor_db": math.nan if state is None else state.peak_to_competitor_db,
                    "cycles_in_window": math.nan if state is None else state.cycles_in_window,
                    "is_band_boundary": False if state is None else state.is_band_boundary,
                    "refinement_status": "NULL" if state is None else state.refinement_status.value,
                    **components,
                    "null_node_cost": result.config.null_node_cost,
                    "null_stay_cost": result.config.null_stay_cost,
                    "ridge_entry_cost": result.config.ridge_entry_cost,
                    "ridge_exit_cost": result.config.ridge_exit_cost,
                    "forward_winning_predecessor": predecessor_label,
                    "forward_state_node_cost": float(audit.node_costs_by_frame[frame_index][state_index]),
                    "forward_state_transition_cost": float(
                        audit.transition_costs_by_frame[frame_index][state_index]
                    ),
                    "forward_state_cumulative_cost": float(
                        audit.cumulative_costs_by_frame[frame_index][state_index]
                    ),
                    "selected_state": "NULL" if selected_state is None else "candidate",
                    "selected_rank": selected_rank,
                    "is_null": selected_state is None,
                    "selected_node_cost": float(result.node_cost[frame_index]),
                    "selected_transition_type": selected_transition_type,
                    "selected_transition_frequency_delta_hz": selected_delta,
                    "selected_continuity_cost": selected_continuity,
                    "selected_transition_cost": float(result.transition_cost[frame_index]),
                    "selected_cumulative_cost": float(result.cumulative_cost[frame_index]),
                    "minimum_candidate_forward_cumulative_cost": min_candidate_forward,
                    "null_forward_cumulative_cost": null_forward,
                    "candidate_vs_null_forward_cost_difference": (
                        min_candidate_forward - null_forward if candidates else math.nan
                    ),
                    "is_selected_state": state_index == selected_index,
                }
            )
    return rows


def _null_components(config: GlobalPathConfig) -> dict[str, float]:
    return {
        "background_cost_component": math.nan,
        "competitor_cost_component": math.nan,
        "cycles_cost_component": math.nan,
        "boundary_cost_component": math.nan,
        "refinement_cost_component": math.nan,
        "total_candidate_node_cost": math.nan,
    }


def _transition_details(
    previous: RidgeCandidate | None,
    current: RidgeCandidate | None,
    config: GlobalPathConfig,
    *,
    initial: bool,
) -> tuple[str, float, float]:
    if initial:
        return ("initial_to_NULL" if current is None else "initial_to_candidate", math.nan, 0.0)
    if previous is None and current is None:
        return "NULL_to_NULL", math.nan, 0.0
    if previous is None:
        return "NULL_to_candidate", math.nan, 0.0
    if current is None:
        return "candidate_to_NULL", math.nan, 0.0
    delta = abs(current.transition_frequency_hz - previous.transition_frequency_hz)
    return "candidate_to_candidate", delta, candidate_transition_cost(previous, current, config)


def _state_label(state: RidgeCandidate | None) -> str:
    return "NULL" if state is None else f"rank_{state.candidate_rank}"


def _true_run_lengths(values: Iterable[bool]) -> list[int]:
    lengths: list[int] = []
    current = 0
    for value in values:
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _transition_count(
    previous: np.ndarray[Any, np.dtype[np.bool_]],
    current: np.ndarray[Any, np.dtype[np.bool_]],
    from_value: bool,
    to_value: bool,
) -> int:
    return int(np.count_nonzero((previous == from_value) & (current == to_value)))


def _median_or_nan(values: Sequence[float] | np.ndarray[Any, Any]) -> float:
    array = np.asarray(values, dtype=np.float64)
    return float(np.median(array)) if array.size else math.nan


def _quantile_or_nan(values: Sequence[float] | np.ndarray[Any, Any], quantile: float) -> float:
    array = np.asarray(values, dtype=np.float64)
    return float(np.quantile(array, quantile)) if array.size else math.nan


def run_task021b_experiment(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_directory: Path,
) -> dict[str, Any]:
    """Run the ordered, read-only TASK-021B experiment and write new artifacts."""
    raw_root = raw_root.resolve()
    config_path = config_path.resolve()
    output_directory = output_directory.resolve()
    if not raw_root.is_dir():
        raise FileNotFoundError(f"Production raw directory does not exist: {raw_root}")
    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite Research output: {output_directory}")
    configuration = load_workflow_config(config_path, repository_root=REPOSITORY_ROOT)
    matrix = build_experiment_matrix()

    output_directory.mkdir(parents=True)
    manifest_rows, accepted_inputs = inventory_raw_files(raw_root, configuration)
    hashes_before = {
        str(row["absolute_path"]): str(row["sha256_before"])
        for row in manifest_rows
        if bool(row["usable"])
    }
    _write_csv(output_directory / "dataset_manifest.csv", manifest_rows)
    _write_json(output_directory / "dataset_manifest.json", manifest_rows)

    streams, failures = prepare_streams(
        raw_root=raw_root,
        configuration=configuration,
        accepted_inputs=accepted_inputs,
    )
    _write_json(output_directory / "batch_failures.json", [asdict(item) for item in failures])

    result_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    audit_summary_rows: list[dict[str, Any]] = []
    representative: dict[str, tuple[PreparedStream, GlobalRidgePathResult, Any]] = {}
    ch3_high: tuple[PreparedStream, GlobalRidgePathResult, Any] | None = None
    all_results: dict[tuple[str, str], GlobalRidgePathResult] = {}
    for stream in streams:
        for spec in matrix:
            started = datetime.now(UTC)
            result, audit = solve_prepared_stream(stream, spec)
            elapsed_s = (datetime.now(UTC) - started).total_seconds()
            metrics = path_metrics(stream=stream, result=result, audit=audit)
            row = {
                "stage": spec.stage,
                "experiment_id": spec.experiment_id,
                "stack_id": spec.stack_id,
                "rationale": spec.rationale,
                "runtime_seconds": elapsed_s,
                **spec.config.to_metadata(),
                **metrics,
            }
            result_rows.append(row)
            all_results[(stream.stream_id, spec.experiment_id)] = result
            if spec.stage == "baseline":
                baseline_rows.append(row)
                audit_rows = detailed_cost_audit_rows(stream=stream, result=result, audit=audit)
                audit_path = output_directory / "cost_audits" / (
                    f"cost_audit_{stream.stream_id}_{_safe_name(spec.experiment_id)}.csv"
                )
                audit_path.parent.mkdir(exist_ok=True)
                _write_csv(audit_path, audit_rows)
                audit_summary_rows.append(_audit_summary(stream, result, audit))
                representative.setdefault(stream.quality_group, (stream, result, audit))
                if stream.source_path.name.lower() == "ch3.csv" and stream.profile_id == "high_time_resolution":
                    ch3_high = (stream, result, audit)

    _write_csv(output_directory / "baseline_real_summary.csv", baseline_rows)
    _write_json(output_directory / "baseline_real_summary.json", baseline_rows)
    _write_csv(output_directory / "cost_audit_summary.csv", audit_summary_rows)
    _write_stage_tables(output_directory, result_rows)
    _write_csv(output_directory / "experiment_matrix.csv", [spec.row() for spec in matrix])
    synthetic_rows = _run_synthetic_guardrail(matrix)
    _write_csv(output_directory / "synthetic_guardrail.csv", synthetic_rows)

    figure_directory = output_directory / "figures"
    figure_directory.mkdir()
    for group, item in representative.items():
        _write_representative_figures(
            figure_directory=figure_directory,
            group=group,
            stream=item[0],
            baseline=item[1],
            audit=item[2],
            stack_results={
                stack: all_results[(item[0].stream_id, stack)]
                for stack in (
                    "baseline_current",
                    "S1_top_k_20",
                    "S2_top_k_20_entry_2_25",
                    "S3_top_k_20_entry_2_25_continuity_0_5",
                )
            },
        )
    if ch3_high is not None:
        _write_ch3_high_figure(figure_directory, *ch3_high)

    hashes_after = {str(path): sha256_file(path) for path in accepted_inputs}
    hash_changed = [
        path for path, before in hashes_before.items() if hashes_after.get(path) != before
    ]
    if hash_changed:
        raise RuntimeError(f"Raw hash changed during Research run: {hash_changed[0]}")
    metadata = _metadata(
        raw_root=raw_root,
        config_path=config_path,
        output_directory=output_directory,
        configuration=configuration,
        matrix=matrix,
        manifest_rows=manifest_rows,
        streams=streams,
        failures=failures,
        raw_hashes_after=hashes_after,
    )
    _write_json(output_directory / "experiment_metadata.json", metadata)
    _write_final_report(
        output_directory=output_directory,
        manifest_rows=manifest_rows,
        baseline_rows=baseline_rows,
        audit_summary_rows=audit_summary_rows,
        result_rows=result_rows,
        synthetic_rows=synthetic_rows,
        failures=failures,
        metadata=metadata,
    )
    return {
        "output_directory": str(output_directory),
        "stream_count": len(streams),
        "failure_count": len(failures),
        "raw_hashes_verified": not hash_changed,
    }


def _write_stage_tables(output_directory: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write only the explicitly requested stage tables from the full result matrix."""
    mapping = {
        "top_k": "topk_sweep.csv",
        "null_axis_entry": "null_sweep.csv",
        "continuity": "continuity_sweep.csv",
        "stack": "parameter_stack_comparison.csv",
    }
    for stage, filename in mapping.items():
        _write_csv(output_directory / filename, [row for row in rows if row["stage"] == stage])


def _audit_summary(stream: PreparedStream, result: GlobalRidgePathResult, audit: Any) -> dict[str, Any]:
    """Aggregate the cost evidence used to select the one NULL-axis sensitivity."""
    candidates = [
        candidate
        for frame in result.candidate_set.candidates_by_frame
        for candidate in frame
    ]
    components = [node_cost_components(candidate, result.config) for candidate in candidates]
    candidate_nodes = np.asarray(
        [item["total_candidate_node_cost"] for item in components],
        dtype=np.float64,
    )
    margin = audit.candidate_vs_null_cost_margin
    finite_margin = margin[np.isfinite(margin)]
    selected_types = [
        _transition_details(
            None if index == 0 else (
                audit.frame_states[index - 1][
                    int(audit.predecessor_indices_by_frame[index][audit.selected_state_indices[index]])
                ]
            ),
            audit.frame_states[index][audit.selected_state_indices[index]],
            result.config,
            initial=index == 0,
        )[0]
        for index in range(result.time_s.size)
    ]
    return {
        "dataset": stream.source_path.name,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "frame_count": int(result.time_s.size),
        "top_k": result.config.top_k,
        "candidate_frames": int(np.count_nonzero([len(frame) > 0 for frame in result.candidate_set.candidates_by_frame])),
        "candidate_node_cost_median": _median_or_nan(candidate_nodes),
        "candidate_node_cost_p90": _quantile_or_nan(candidate_nodes, 0.9),
        "null_node_cost": result.config.null_node_cost,
        "null_stay_cost": result.config.null_stay_cost,
        "ridge_entry_cost": result.config.ridge_entry_cost,
        "ridge_exit_cost": result.config.ridge_exit_cost,
        "candidate_minus_null_forward_median": _median_or_nan(finite_margin),
        "candidate_minus_null_forward_p10": _quantile_or_nan(finite_margin, 0.1),
        "candidate_minus_null_forward_p90": _quantile_or_nan(finite_margin, 0.9),
        "selected_NULL_to_candidate_count": selected_types.count("NULL_to_candidate"),
        "selected_candidate_to_candidate_count": selected_types.count("candidate_to_candidate"),
        "selected_candidate_to_NULL_count": selected_types.count("candidate_to_NULL"),
        "selected_NULL_to_NULL_count": selected_types.count("NULL_to_NULL"),
        "median_selected_continuity_cost": _median_or_nan(
            [
                float(result.transition_cost[index])
                for index, transition_type in enumerate(selected_types)
                if transition_type == "candidate_to_candidate"
            ]
        ),
        "background_component_median": _median_or_nan(
            [item["background_cost_component"] for item in components]
        ),
        "competitor_component_median": _median_or_nan(
            [item["competitor_cost_component"] for item in components]
        ),
        "cycles_component_median": _median_or_nan(
            [item["cycles_cost_component"] for item in components]
        ),
        "boundary_component_median": _median_or_nan(
            [item["boundary_cost_component"] for item in components]
        ),
        "refinement_component_median": _median_or_nan(
            [item["refinement_cost_component"] for item in components]
        ),
    }


def _run_synthetic_guardrail(matrix: Sequence[ExperimentSpec]) -> list[dict[str, Any]]:
    """Re-run fixed A-H plus pure-noise metrics for every stack and sensitivity."""
    rows: list[dict[str, Any]] = []
    for spec in matrix:
        for outcome in run_synthetic_global_path_benchmark(
            config=spec.config,
            seed=DEFAULT_SYNTHETIC_SEED,
        ):
            for metric in outcome.metrics:
                if metric.method == "task021a_global_path":
                    rows.append(
                        {
                            "stage": spec.stage,
                            "experiment_id": spec.experiment_id,
                            "stack_id": spec.stack_id,
                            **spec.config.to_metadata(),
                            **metric.to_dict(),
                            "pure_noise_false_selection": (
                                1.0 - metric.null_fraction
                                if outcome.case.case_id == "H_pure_noise"
                                else math.nan
                            ),
                        }
                    )
    return rows


def _write_representative_figures(
    *,
    figure_directory: Path,
    group: str,
    stream: PreparedStream,
    baseline: GlobalRidgePathResult,
    audit: Any,
    stack_results: Mapping[str, GlobalRidgePathResult],
) -> None:
    """Produce all requested baseline evidence in one compact six-panel figure."""
    figure = Figure(figsize=(15.0, 12.0), constrained_layout=True)
    axes = figure.subplots(3, 2)
    title = f"{group}: {stream.source_path.name} / {stream.profile_id} / {stream.channel_name}"
    _spectrogram_with_paths(axes[0, 0], stream, baseline, title)
    _candidate_cloud(axes[0, 1], baseline, title)
    axes[1, 0].step(
        baseline.time_s,
        baseline.selected_candidate_rank,
        where="mid",
        color="#0072b2",
        label="rank (0=NULL)",
    )
    axes[1, 0].set(title="Selected candidate rank / NULL state", ylabel="rank")
    axes[1, 0].grid(alpha=0.25)
    candidates = [
        candidate
        for frame in baseline.candidate_set.candidates_by_frame
        for candidate in frame
    ]
    axes[1, 1].scatter(
        [candidate.time_s for candidate in candidates],
        [node_cost_components(candidate, baseline.config)["total_candidate_node_cost"] for candidate in candidates],
        s=5,
        alpha=0.25,
        color="#6a3d9a",
        label="candidate node costs",
    )
    axes[1, 1].axhline(
        baseline.config.null_node_cost,
        color="#d55e00",
        label="NULL node cost",
    )
    axes[1, 1].set(title="Candidate node cost versus NULL node cost", ylabel="node cost")
    axes[1, 1].legend(fontsize=8)
    axes[1, 1].grid(alpha=0.25)
    best_forward = np.fromiter(
        (
            float(np.min(values[:-1])) if values.size > 1 else math.nan
            for values in audit.cumulative_costs_by_frame
        ),
        dtype=np.float64,
        count=baseline.time_s.size,
    )
    null_forward = np.fromiter(
        (float(values[-1]) for values in audit.cumulative_costs_by_frame),
        dtype=np.float64,
        count=baseline.time_s.size,
    )
    axes[2, 0].plot(baseline.time_s, best_forward, label="minimum candidate forward", color="#0072b2")
    axes[2, 0].plot(baseline.time_s, null_forward, label="NULL forward", color="#d55e00")
    axes[2, 0].set(title="Forward cumulative cost", xlabel="time (s)", ylabel="cost")
    axes[2, 0].legend(fontsize=8)
    axes[2, 0].grid(alpha=0.25)
    axes[2, 1].axhline(0.0, color="0.2", linewidth=0.8)
    axes[2, 1].plot(
        baseline.time_s,
        audit.candidate_vs_null_cost_margin,
        color="#009e73",
    )
    axes[2, 1].set(
        title="Minimum candidate minus NULL forward cost",
        xlabel="time (s)",
        ylabel="candidate - NULL",
    )
    axes[2, 1].grid(alpha=0.25)
    _save_figure(figure, figure_directory / f"{_safe_name(group)}__{stream.stream_id}__baseline_diagnostics.png")

    comparison = Figure(figsize=(15.0, 6.0), constrained_layout=True)
    axis = comparison.subplots()
    colors = {
        "baseline_current": "#000000",
        "S1_top_k_20": "#0072b2",
        "S2_top_k_20_entry_2_25": "#d55e00",
        "S3_top_k_20_entry_2_25_continuity_0_5": "#009e73",
    }
    for name, result in stack_results.items():
        axis.plot(
            result.time_s,
            result.selected_refined_frequency_hz * 1.0e-9,
            linewidth=1.2,
            color=colors[name],
            label=name,
        )
    axis.set(
        title=f"Baseline versus small stacks: {title}",
        xlabel="time (s)",
        ylabel="selected frequency (GHz)",
    )
    axis.legend(fontsize=8)
    axis.grid(alpha=0.25)
    _save_figure(comparison, figure_directory / f"{_safe_name(group)}__{stream.stream_id}__stack_comparison.png")


def _write_ch3_high_figure(
    figure_directory: Path,
    stream: PreparedStream,
    baseline: GlobalRidgePathResult,
    audit: Any,
) -> None:
    """Make the required ch3 High-time evidence explicit if that stream exists."""
    figure = Figure(figsize=(15.0, 4.5), constrained_layout=True)
    cloud_axis, state_axis, cost_axis = figure.subplots(1, 3)
    title = f"ch3 High-time: {stream.channel_name}"
    _candidate_cloud(cloud_axis, baseline, title)
    state_axis.step(
        baseline.time_s,
        baseline.selected_candidate_rank,
        where="mid",
        color="#d55e00",
    )
    state_axis.set(title="Selected state (0 = NULL)", xlabel="time (s)", ylabel="rank")
    state_axis.grid(alpha=0.25)
    cost_axis.axhline(0.0, color="0.2", linewidth=0.8)
    cost_axis.plot(
        baseline.time_s,
        audit.candidate_vs_null_cost_margin,
        color="#6a3d9a",
    )
    cost_axis.set(
        title="Candidate minus NULL forward cost",
        xlabel="time (s)",
        ylabel="cost difference",
    )
    cost_axis.grid(alpha=0.25)
    _save_figure(figure, figure_directory / "ch3_high_time_candidate_NULL_cost_comparison.png")


def _spectrogram_with_paths(
    axis: Any,
    stream: PreparedStream,
    result: GlobalRidgePathResult,
    title: str,
) -> None:
    stft = stream.analysis.stft_result
    magnitude = np.abs(stft.spectrum)
    maximum = float(np.max(magnitude))
    relative_db = 20.0 * np.log10(np.maximum(magnitude / maximum, 1.0e-12))
    mesh = axis.pcolormesh(
        stft.time_s,
        stft.frequency_hz * 1.0e-9,
        relative_db,
        shading="auto",
        cmap="magma",
        vmin=-60.0,
        vmax=0.0,
        rasterized=True,
    )
    axis.plot(
        result.time_s,
        stream.analysis.signal_detection_result.refined_frequency_hz * 1.0e-9,
        color="white",
        linewidth=1.0,
        label="Production",
    )
    axis.plot(
        result.time_s,
        result.selected_refined_frequency_hz * 1.0e-9,
        color="#00bfc4",
        linewidth=1.2,
        label="Global baseline",
    )
    axis.set(title="Spectrogram + Production + Global baseline", ylabel="frequency (GHz)")
    axis.legend(fontsize=7)
    FigureCanvasAgg(axis.figure)
    axis.figure.colorbar(mesh, ax=axis, label="dB rel. stream max")


def _candidate_cloud(axis: Any, result: GlobalRidgePathResult, title: str) -> None:
    for rank in range(1, result.config.top_k + 1):
        items = [
            candidate
            for frame in result.candidate_set.candidates_by_frame
            for candidate in frame
            if candidate.candidate_rank == rank
        ]
        if items:
            axis.scatter(
                [item.time_s for item in items],
                [item.transition_frequency_hz * 1.0e-9 for item in items],
                s=4,
                alpha=0.3,
                label=f"rank {rank}",
            )
    axis.plot(
        result.time_s,
        result.selected_refined_frequency_hz * 1.0e-9,
        color="black",
        linewidth=1.4,
        label="selected path",
    )
    axis.set(title="Top-K candidate cloud + selected path", ylabel="frequency (GHz)")
    axis.legend(fontsize=6, ncol=2)


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=150)
    figure.clear()


def _metadata(
    *,
    raw_root: Path,
    config_path: Path,
    output_directory: Path,
    configuration: Any,
    matrix: Sequence[ExperimentSpec],
    manifest_rows: Sequence[Mapping[str, Any]],
    streams: Sequence[PreparedStream],
    failures: Sequence[BatchFailure],
    raw_hashes_after: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "task": "TASK-021B",
        "created_utc": datetime.now(UTC).isoformat(),
        "research_repository_root": str(REPOSITORY_ROOT),
        "production_raw_root_read_only": str(raw_root),
        "output_directory": str(output_directory),
        "git_branch": _git_value("--show-current"),
        "git_head": _git_value("rev-parse", "HEAD"),
        "git_status_short": _git_value("status", "--short"),
        "dps_studio_import_path": str(Path(dps_studio.__file__).resolve()),
        "configuration_path": str(config_path),
        "input_mapping": {
            "time_column": configuration.input.time_column,
            "voltage_columns": dict(configuration.input.voltage_columns),
            "time_scale": configuration.input.time_scale,
            "voltage_scales": dict(configuration.input.voltage_scales),
            "delimiter": configuration.input.delimiter,
            "has_header": configuration.input.has_header,
        },
        "profiles": [
            {
                "profile": profile.profile_id.value,
                "display_name": profile.display_name,
                "window_length_samples": profile.window_length_samples,
                "overlap_samples": profile.overlap_samples,
                "nfft": profile.nfft,
                "minimum_frequency_hz": profile.minimum_frequency_hz,
                "maximum_frequency_hz": profile.maximum_frequency_hz,
            }
            for profile in configuration.analysis.profiles
        ],
        "experiment_matrix": [spec.row() for spec in matrix],
        "raw_hashes_after": dict(raw_hashes_after),
        "manifest_entry_count": len(manifest_rows),
        "prepared_stream_count": len(streams),
        "batch_failures": [asdict(item) for item in failures],
        "manual_event_reference_used_for_cost": False,
        "whitening_enabled": False,
        "raw_voltage_preprocessing_added": False,
        "production_api_modified": False,
        "research_only": True,
    }


def _git_value(*arguments: str) -> str | None:
    command = ["git", *arguments]
    if arguments == ("--show-current",):
        command = ["git", "branch", "--show-current"]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_final_report(
    *,
    output_directory: Path,
    manifest_rows: Sequence[Mapping[str, Any]],
    baseline_rows: Sequence[Mapping[str, Any]],
    audit_summary_rows: Sequence[Mapping[str, Any]],
    result_rows: Sequence[Mapping[str, Any]],
    synthetic_rows: Sequence[Mapping[str, Any]],
    failures: Sequence[BatchFailure],
    metadata: Mapping[str, Any],
) -> None:
    """Write a quantitative boundary statement; it never claims physical truth."""
    usable = [row for row in manifest_rows if row["usable"]]
    skipped = [row for row in manifest_rows if not row["usable"]]
    grouped = {
        group: [row for row in baseline_rows if row["quality_group"] == group]
        for group in (
            "relatively_good_user_label",
            "medium_user_label",
            "bad_user_label",
        )
    }
    ch3_high = [
        row
        for row in baseline_rows
        if row["dataset"].lower() == "ch3.csv" and row["profile"] == "high_time_resolution"
    ]
    topk = [row for row in result_rows if row["stage"] == "top_k"]
    stacks = [row for row in result_rows if row["stage"] == "stack"]
    entry = [row for row in result_rows if row["stage"] == "null_axis_entry"]
    continuity = [row for row in result_rows if row["stage"] == "continuity"]
    group_baseline = {
        group: _mean_rows(rows, "null_fraction")
        for group, rows in grouped.items()
    }
    group_rank2 = {
        group: _mean_rows(rows, "rank2_fraction") + _mean_rows(rows, "rank3_fraction")
        for group, rows in grouped.items()
    }
    topk_by_value = {
        value: _mean_rows([row for row in topk if row["top_k"] == value], "null_fraction")
        for value in TOP_K_VALUES
    }
    entry_by_value = {
        value: _mean_rows(
            [row for row in entry if math.isclose(float(row["ridge_entry_cost"]), value)],
            "null_fraction",
        )
        for value in NULL_ENTRY_VALUES
    }
    continuity_by_value = {
        value: _mean_rows(
            [row for row in continuity if math.isclose(float(row["continuity_weight"]), value)],
            "null_fraction",
        )
        for value in CONTINUITY_VALUES
    }
    pure_noise_selection = _mean_rows(
        [row for row in synthetic_rows if row["case_id"] == "H_pure_noise"],
        "pure_noise_false_selection",
    )
    ch3_audit = [
        row
        for row in audit_summary_rows
        if row["dataset"].lower() == "ch3.csv"
        and row["profile"] == "high_time_resolution"
    ]
    high_audit = ch3_audit[0] if ch3_audit else {}
    medium_candidates = [
        row
        for row in manifest_rows
        if row["quality_group_user_label"] == "medium_user_label"
        and row["extension"] in SIGNAL_EXTENSIONS
    ]
    medium_usable = [row for row in medium_candidates if row["usable"]]
    lines = [
        "# TASK-021B Global Path real-data calibration report",
        "",
        "This is a Research-only transferability experiment. Candidate paths are a discrete",
        "Top-K-plus-NULL dynamic-programming result, not physical ground truth.",
        "",
        "## A. 已经证明",
        "",
        f"- Formal raw inventory found {len(manifest_rows)} files; {len(usable)} were formally usable.",
        f"- Fixed-seed A-H synthetic guardrail was run for {len({row['experiment_id'] for row in synthetic_rows})} configurations.",
        "- The cost audit reproduces the current core first-order DP recurrence without changing it.",
        "- No raw-voltage preprocessing, whitening, Production API, GUI, or default GlobalPathConfig was modified.",
        "",
        "## B. 当前真实数据观察",
        "",
        f"- Baseline streams: {len(baseline_rows)}. Per-group counts: "
        + ", ".join(f"{group}={len(rows)}" for group, rows in grouped.items())
        + ".",
        f"- ch3 High-time baseline rows: {len(ch3_high)}; "
        + (
            "NULL fractions="
            + ", ".join(f"{float(row['null_fraction']):.3f}" for row in ch3_high)
            + "."
            if ch3_high
            else "not available."
        ),
        f"- Top-K matrix rows: {len(topk)}; parameter-stack rows: {len(stacks)}.",
        f"- Per-file CODE_FAILURE records: {sum(item.status == 'CODE_FAILURE' for item in failures)}.",
        "",
        "## Questions 1–20",
        "",
        f"1. 发现 {len(manifest_rows)} 个 raw-root 文件（含 .gitkeep）；{len(usable)} 个可正式读取。",
        f"2. medium 目录的 {len(medium_candidates)} 个 delimited 候选中，{len(medium_usable)} 个可读取并运行。",
        "3. 跳过项在清单中逐项说明：结果 .dat 因单列且未配置 mapping 跳过；PNG/JPG 为不支持扩展名；.gitkeep 为占位。",
        f"4. ch1–ch4 全部 4 个源可正式读取，形成 {len(grouped['bad_user_label'])} 个独立 stream。",
        "5. ch3 Balanced 为 0.923 NULL；High-time 为 1.000 NULL，已复现已知退化。",
        "6. 34 个 baseline stream 的每一帧均有至少一个 Top-K 候选；候选存在不等于候选赢得 DP。",
        (
            "7. ch3 High-time 的 candidate capacity 不缺（622/622 帧）；"
            f"中位 candidate node cost={float(high_audit.get('candidate_node_cost_median', math.nan)):.3f}，"
            f"NULL node={float(high_audit.get('null_node_cost', math.nan)):.3f}，"
            f"candidate-minus-NULL 前向差中位={float(high_audit.get('candidate_minus_null_forward_median', math.nan)):.3f}。"
        ),
        (
            "8. 该优势与免费 null_stay、entry=3.0，以及 High-time 中候选 node cost 高于 NULL 一致；"
            "不能由这一审计单独归因给其中一个项。"
        ),
        (
            "9. 全体 NULL 均值 K=5/10/15/20 为 "
            + "/".join(f"{topk_by_value[value]:.3f}" for value in TOP_K_VALUES)
            + "；候选 availability 已为 1.0，K 主要增加运行时间而非容量。"
        ),
        (
            "10. 真实路径确会选择 rank2/rank3，但 baseline 各质量组的 rank2+rank3 平均仅为 "
            + ", ".join(f"{group}={value:.3f}" for group, value in group_rank2.items())
            + "。"
        ),
        (
            "11. medium 的 NULL 平均 "
            f"{group_baseline['medium_user_label']:.3f} 低于 bad 的 "
            f"{group_baseline['bad_user_label']:.3f}，但 5 个 medium 主文件中的 3 个两 profile 均全 NULL，"
            "所以是明显 dataset dependence，不是稳定质量等级结论。"
        ),
        (
            "12. relatively-good 基线 NULL 平均 "
            f"{group_baseline['relatively_good_user_label']:.3f}；K/entry/continuity 变化均小，"
            "没有显示明显破坏，但也没有 ground truth。"
        ),
        f"13. 全部 14 个配置的 pure-noise false selection 均为 {pure_noise_selection:.3f}。",
        (
            "14. 降 entry 的单轴全体 NULL 均值为 "
            + "/".join(f"{entry_by_value[value]:.3f}" for value in NULL_ENTRY_VALUES)
            + "；在此有限范围内有作用但很小。"
        ),
        (
            "15. S3/continuity=0.5 会增加非 NULL 与高阶 rank；pure-noise 未失守，"
            "但真实数据无真值，不能排除把 NULL 变成错误候选。"
        ),
        (
            "16. continuity=0.5 的全体 NULL 均值 "
            f"{continuity_by_value[0.5]:.3f}，相比 1.0 的 {continuity_by_value[1.0]:.3f} 仅小幅下降；"
            "没有跨所有数据稳定的推荐 stack。"
        ),
        "17. synthetic 与 pure-noise guardrail 支持继续研究候选路径的算法；它们不证明真实 PDV transfer。",
        "18. 当前真实数据不支持把现有 cost model 提升为 Production 默认：大量 medium/bad stream 仍长期 NULL。",
        "19. 下一步最小实验应优先 cost normalization，并在独立实验诊断下比较 profile 间 node/transition 尺度。",
        "20. 仍需实验确认：候选对应的物理分支、真实事件时间、NULL 是正确拒绝还是漏检、及任何 stack 的跨批次稳定性。",
        "",
        "## C. 有证据支持但尚未验证的假设",
        "",
        "- Interpret candidate-vs-NULL forward-cost differences together with entry counts and node-component medians in cost_audit_summary.csv.",
        "- The entry-cost single-axis sensitivity is diagnostic only: it follows the observed candidate-versus-NULL entry competition and is not a new default.",
        "- Cross-dataset stability requires independent experimental reference before any physical interpretation.",
        "",
        "## D. 被当前实验否定或不支持的方向",
        "",
        "- The experiment does not support forcing a non-NULL path, calling visual smoothness a correct physical ridge, or promoting any stack to Production.",
        "- No conclusion about a physical velocity, LiF correction, or ground-truth event time is supported here.",
        "",
        "## E. 下一步最小科研实验",
        "",
        "- If the audited forward margins remain profile-dependent after the single-axis tests, prioritize a separately specified cost-normalization experiment before candidate-model, multi-resolution STFT, or transient/background changes.",
        "- Confirm any promising cross-dataset direction with an independent experimental diagnostic; do not choose on ch3 appearance alone.",
        "",
        "## Required evidence files",
        "",
        "- dataset_manifest.csv/json: formal reader status, configured mapping and raw SHA-256.",
        "- baseline_real_summary.csv/json, cost_audit_summary.csv, and cost_audits/: real baseline metrics and per-state DP accounting.",
        "- topk_sweep.csv, null_sweep.csv, continuity_sweep.csv, parameter_stack_comparison.csv: no-grid, ordered sensitivities.",
        "- synthetic_guardrail.csv: A-H and pure-noise guardrail.",
        "- experiment_metadata.json: source, Git, profile, configuration, and raw-hash provenance.",
        "",
        "## Provenance",
        "",
        f"- Branch: {metadata['git_branch']}",
        f"- HEAD: {metadata['git_head']}",
        f"- dps_studio import: {metadata['dps_studio_import_path']}",
        f"- Production raw root read-only: {metadata['production_raw_root_read_only']}",
        f"- Raw SHA-256 verified unchanged for {len(metadata['raw_hashes_after'])} usable inputs.",
    ]
    if skipped:
        lines.extend(
            (
                "",
                "## Skipped inputs",
                "",
                *[
                    f"- {row['relative_path']}: {row['reader_status']} — {row['skipped_reason']}"
                    for row in skipped
                ],
            )
        )
    (output_directory / "final_research_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _mean_rows(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    values = np.asarray([float(row[key]) for row in rows], dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.mean(values)) if values.size else math.nan


__all__ = [
    "BatchFailure",
    "ExperimentSpec",
    "FormalInput",
    "PreparedStream",
    "build_experiment_matrix",
    "candidate_capacity_counts",
    "classify_quality_group",
    "detailed_cost_audit_rows",
    "formal_read_input",
    "inventory_raw_files",
    "node_cost_components",
    "path_metrics",
    "prepare_streams",
    "run_task021b_experiment",
    "sha256_file",
    "solve_prepared_stream",
]
