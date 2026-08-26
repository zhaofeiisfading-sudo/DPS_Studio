"""Generate non-overwriting TASK-021A synthetic and real-data research artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dps_studio
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from numpy.typing import NDArray

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.ridge import (
    GlobalPathConfig,
    GlobalRidgePathResult,
    RidgeCandidate,
    candidate_node_cost,
    extract_global_path_candidates,
    solve_global_candidate_path,
    track_global_candidate_path,
)
from dps_studio.research.global_path_calibration import (
    audit_global_candidate_path,
    audit_matches_global_path_result,
    audit_rows,
    calibration_metrics,
    candidate_set_for_top_k,
    research_aggressiveness_presets,
)
from dps_studio.core.workflow import (
    ChannelAnalysis,
    analyze_profile,
    load_workflow_config,
)
from dps_studio.research.global_path_benchmark import (
    DEFAULT_SYNTHETIC_SEED,
    SyntheticBenchmarkResult,
    run_synthetic_global_path_benchmark,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "configs" / "demo_dual_profile.toml"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task021a_global_path"
REQUIRED_TOP_K = (3, 5, 10)
CALIBRATION_TOP_K = (5, 10, 15, 20)
CALIBRATION_MAXIMUM_TOP_K = max(CALIBRATION_TOP_K)
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True)
class RealDataInput:
    """A formally read source file and its explicit channel-selection provenance."""

    loaded: Any
    selection_mode: str


@dataclass(frozen=True)
class RealDataRun:
    """Output provenance returned by the real-data orchestration layer."""

    summaries: tuple[dict[str, Any], ...]
    stream_directories: tuple[Path, ...]
    profile_metadata: tuple[dict[str, Any], ...]


def main(arguments: Sequence[str] | None = None) -> int:
    """Run one explicit real-data or synthetic-benchmark research mode."""
    parsed = _parse_arguments(arguments)
    output_directory = parsed.output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"Research output already exists: {output_directory}")
    if parsed.mode == "benchmark":
        output_directory.mkdir(parents=True)
        _run_synthetic_benchmark(output_directory)
        return 0

    if parsed.mode == "calibration":
        raw_paths = _require_calibration_inputs(parsed)
        output_directory.mkdir(parents=True)
        _run_real_data_calibration(
            raw_paths=raw_paths,
            config_path=parsed.config.resolve(),
            output_directory=output_directory,
        )
        return 0

    raw_path = _require_real_input(parsed)
    configuration = load_workflow_config(parsed.config.resolve(), repository_root=REPOSITORY_ROOT)
    real_input = _load_real_input(raw_path=raw_path, configuration=configuration)
    resolved_input = real_input.loaded.source_path.resolve()
    if resolved_input != raw_path:
        raise RuntimeError(
            "Formal reader source does not match the requested input: "
            f"requested={raw_path!s}, resolved={resolved_input!s}."
        )
    raw_hash_before = _sha256(resolved_input)
    _print_real_input_diagnostics(resolved_input, raw_hash_before)

    output_directory.mkdir(parents=True)
    real_run = _run_real_data(
        loaded=real_input.loaded,
        configuration=configuration,
        output_directory=output_directory / "real_data",
    )
    raw_hash_after = _sha256(resolved_input)
    if raw_hash_after != raw_hash_before:
        raise RuntimeError("Raw data hash changed during read-only research run.")
    _write_real_result_summary(output_directory, real_run)
    metadata = _real_run_metadata(
        input_path=resolved_input,
        input_sha256=raw_hash_before,
        input_selection_mode=real_input.selection_mode,
        loaded=real_input.loaded,
        configuration=configuration,
        real_run=real_run,
        output_directory=output_directory,
    )
    _write_json(output_directory / "run_metadata.json", metadata)
    _write_real_readme(output_directory, metadata, real_run.summaries)
    return 0


def _parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("real", "benchmark", "calibration"),
        default="real",
        help=(
            "Run one real input file (default), only the A-H synthetic benchmark, "
            "or an explicit multi-input calibration grid."
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--raw-data",
        type=Path,
        action="append",
        help=(
            "Required once in real mode and one or more times in calibration mode; "
            "each exact source file to analyze."
        ),
    )
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser.parse_args(arguments)


def _require_real_input(parsed: argparse.Namespace) -> Path:
    raw_data = tuple(parsed.raw_data or ())
    if len(raw_data) != 1:
        raise ValueError("Exactly one --raw-data is required when --mode real is selected.")
    raw_path = raw_data[0].resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw input does not exist: {raw_path}")
    return raw_path


def _require_calibration_inputs(parsed: argparse.Namespace) -> tuple[Path, ...]:
    raw_data = tuple(parsed.raw_data or ())
    if not raw_data:
        raise ValueError("One or more --raw-data values are required in calibration mode.")
    resolved_paths = tuple(path.resolve() for path in raw_data)
    if len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("Calibration input files must be unique.")
    missing = tuple(path for path in resolved_paths if not path.is_file())
    if missing:
        raise FileNotFoundError(f"Calibration raw input does not exist: {missing[0]}")
    return resolved_paths


def _load_real_input(*, raw_path: Path, configuration: Any) -> RealDataInput:
    """Use the formal reader and only infer the unambiguous two-column case."""
    input_config = configuration.input
    configured_columns = dict(input_config.voltage_columns)
    first_channel_name, first_channel_index = next(iter(configured_columns.items()))
    first_channel_scale = input_config.voltage_scales[first_channel_name]
    single_channel_loaded = read_delimited_signals(
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
        return RealDataInput(single_channel_loaded, "configured_columns")

    configured_maximum_column = max(
        input_config.time_column,
        *configured_columns.values(),
    )
    if single_channel_loaded.column_count > configured_maximum_column:
        configured_loaded = read_delimited_signals(
            raw_path,
            time_column=input_config.time_column,
            voltage_columns=configured_columns,
            delimiter=input_config.delimiter,
            has_header=input_config.has_header,
            encoding=input_config.encoding,
            time_scale=input_config.time_scale,
            voltage_scales=input_config.voltage_scales,
        )
        return RealDataInput(configured_loaded, "configured_columns")

    single_column_count = max(input_config.time_column, first_channel_index) + 1
    if (
        input_config.time_column == 0
        and first_channel_index == 1
        and single_channel_loaded.column_count == single_column_count
    ):
        return RealDataInput(
            single_channel_loaded,
            "single_voltage_column_from_two_column_file",
        )

    raise ValueError(
        "Input does not contain every configured signal column and is not an "
        "unambiguous time-plus-one-voltage file. Provide a matching formal config; "
        f"observed_columns={single_channel_loaded.column_count}, "
        f"configured_columns={configured_columns!r}."
    )


def _print_real_input_diagnostics(input_path: Path, input_sha256: str) -> None:
    print(f"Resolved input file: {input_path}")
    print(f"Input SHA-256: {input_sha256}")
    print(f"Research source root: {REPOSITORY_ROOT}")
    print(f"dps_studio import: {Path(dps_studio.__file__).resolve()}")


def _run_real_data(
    *,
    loaded: Any,
    configuration: Any,
    output_directory: Path,
) -> RealDataRun:
    output_directory.mkdir()
    summaries: list[dict[str, Any]] = []
    stream_directories: list[Path] = []
    profile_metadata: list[dict[str, Any]] = []
    for profile in configuration.analysis.profiles:
        profile_metadata.append(_profile_metadata(profile))
        for channel_name, record in loaded.records.items():
            analysis, manual_reference_time_s = _analyze_real_record(
                channel_name=channel_name,
                record=record,
                profile=profile,
                configuration=configuration,
            )
            production_before = analysis.signal_detection_result.refined_frequency_hz.copy()
            result = track_global_candidate_path(
                analysis.stft_result,
                minimum_frequency_hz=profile.minimum_frequency_hz,
                maximum_frequency_hz=profile.maximum_frequency_hz,
                config=GlobalPathConfig(top_k=5),
            )
            if not np.array_equal(
                production_before,
                analysis.signal_detection_result.refined_frequency_hz,
                equal_nan=True,
            ):
                raise RuntimeError("Opt-in global path mutated a production result array.")
            stream_name = f"{profile.profile_id.value}__{channel_name}"
            stream_directory = output_directory / stream_name
            stream_directory.mkdir()
            disagreement_rows = _disagreement_rows(analysis, result)
            _write_csv(stream_directory / "path_disagreement.csv", disagreement_rows)
            _candidate_cloud_plot(
                stream_directory / "candidate_cloud.png",
                result,
                production_frequency_hz=production_before,
                title=f"{profile.display_name} / {channel_name}",
                manual_reference_time_s=manual_reference_time_s,
            )
            _selected_rank_plot(
                stream_directory / "selected_rank.png",
                result,
                title=f"{profile.display_name} / {channel_name}",
            )
            _disagreement_plot(
                stream_directory / "path_disagreement.png",
                analysis,
                result,
                title=f"{profile.display_name} / {channel_name}",
            )
            summary = _real_stream_summary(
                stream_name,
                analysis,
                result,
                manual_reference_time_s=manual_reference_time_s,
                disagreement_count=len({int(row["frame_index"]) for row in disagreement_rows}),
            )
            _write_json(stream_directory / "summary.json", summary)
            summaries.append(summary)
            stream_directories.append(stream_directory)
    _write_csv(output_directory / "real_stream_summary.csv", summaries)
    return RealDataRun(
        summaries=tuple(summaries),
        stream_directories=tuple(stream_directories),
        profile_metadata=tuple(profile_metadata),
    )


def _analyze_real_record(
    *,
    channel_name: str,
    record: Any,
    profile: Any,
    configuration: Any,
) -> tuple[ChannelAnalysis, float | None]:
    """Run the unchanged single-channel production analysis for one Research stream."""
    analysis_start_time_s = float(record.time_s[0])
    analysis_end_time_s = float(record.time_s[-1])
    configured_reference = configuration.analysis.manual_event_reference_time_s
    manual_reference_time_s = (
        configured_reference
        if configured_reference is not None
        and analysis_start_time_s <= configured_reference <= analysis_end_time_s
        else None
    )
    # Supplying one record proves that no other channel can affect this stream.
    analysis = analyze_profile(
        {channel_name: record},
        profile=profile,
        analysis_start_time_s=analysis_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        manual_event_reference_time_s=manual_reference_time_s,
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        background_guard_window_scale=configuration.quality.background_guard_window_scale,
        minimum_background_bin_count=configuration.quality.minimum_background_bin_count,
        automatic_ridge_selection_config=configuration.automatic_ridge_selection,
        velocity_correction_config=configuration.velocity_correction,
    )[channel_name]
    return analysis, manual_reference_time_s


def _run_real_data_calibration(
    *,
    raw_paths: tuple[Path, ...],
    config_path: Path,
    output_directory: Path,
) -> None:
    """Run an explicit, small Research-only K and NULL-cost calibration grid.

    Candidate extraction is performed once at K=20 for each stream, then each
    lower-K result is a deterministic prefix of that fixed candidate cloud.
    This isolates K and the audited NULL-preference costs without changing the
    STFT profiles, candidate separation, node-evidence form, or core solver.
    """
    configuration = load_workflow_config(config_path, repository_root=REPOSITORY_ROOT)
    summary_directory = output_directory / "00_RESULT_SUMMARY"
    audit_directory = output_directory / "cost_audits"
    summary_directory.mkdir()
    audit_directory.mkdir()

    rows: list[dict[str, Any]] = []
    input_metadata: list[dict[str, Any]] = []
    profile_metadata = tuple(_profile_metadata(profile) for profile in configuration.analysis.profiles)
    for raw_path in raw_paths:
        real_input = _load_real_input(raw_path=raw_path, configuration=configuration)
        loaded = real_input.loaded
        resolved_input = loaded.source_path.resolve()
        if resolved_input != raw_path:
            raise RuntimeError(
                "Formal reader source does not match the requested calibration input: "
                f"requested={raw_path!s}, resolved={resolved_input!s}."
            )
        raw_hash_before = _sha256(resolved_input)
        _print_real_input_diagnostics(resolved_input, raw_hash_before)
        input_metadata.append(
            _calibration_input_metadata(
                input_path=resolved_input,
                input_sha256=raw_hash_before,
                input_selection_mode=real_input.selection_mode,
                loaded=loaded,
            )
        )

        for profile in configuration.analysis.profiles:
            for channel_name, record in loaded.records.items():
                analysis, manual_reference_time_s = _analyze_real_record(
                    channel_name=channel_name,
                    record=record,
                    profile=profile,
                    configuration=configuration,
                )
                production_frequency_hz = (
                    analysis.signal_detection_result.refined_frequency_hz.copy()
                )
                maximum_candidate_set = extract_global_path_candidates(
                    analysis.stft_result,
                    minimum_frequency_hz=profile.minimum_frequency_hz,
                    maximum_frequency_hz=profile.maximum_frequency_hz,
                    config=GlobalPathConfig(top_k=CALIBRATION_MAXIMUM_TOP_K),
                )
                stream_id = _calibration_stream_id(
                    input_path=resolved_input,
                    profile=profile,
                    channel_name=channel_name,
                )
                for top_k in CALIBRATION_TOP_K:
                    for preset_name, path_config in research_aggressiveness_presets(
                        top_k=top_k
                    ).items():
                        candidate_set = candidate_set_for_top_k(
                            maximum_candidate_set,
                            config=path_config,
                        )
                        result = solve_global_candidate_path(candidate_set)
                        audit = audit_global_candidate_path(candidate_set)
                        if not audit_matches_global_path_result(audit, result):
                            raise RuntimeError(
                                "Research cost audit recurrence does not match the core DP solver."
                            )
                        metrics = calibration_metrics(
                            result=result,
                            audit=audit,
                            production_frequency_hz=production_frequency_hz,
                            pre_event_reference_time_s=manual_reference_time_s,
                        )
                        row: dict[str, Any] = {
                            "dataset": resolved_input.name,
                            "source_path": str(resolved_input),
                            "source_sha256": raw_hash_before,
                            "source_selection_mode": real_input.selection_mode,
                            "stream": stream_id,
                            "profile_id": profile.profile_id.value,
                            "profile_display_name": profile.display_name,
                            "channel": channel_name,
                            "top_k": top_k,
                            "preset": preset_name,
                            "manual_reference_time_s_diagnostic_only": manual_reference_time_s,
                        }
                        row.update(path_config.to_metadata())
                        row.update(metrics.to_metadata())
                        rows.append(row)

                        is_baseline_audit = preset_name == "conservative" and top_k == 5
                        is_summary_view = (
                            preset_name == "balanced"
                            and top_k == CALIBRATION_MAXIMUM_TOP_K
                        )
                        if is_baseline_audit or is_summary_view:
                            _write_csv(
                                audit_directory / f"{stream_id}__{preset_name}_k{top_k}_cost_audit.csv",
                                audit_rows(audit),
                            )
                        if is_summary_view:
                            _candidate_cloud_plot(
                                summary_directory / f"{stream_id}__candidate_cloud.png",
                                result,
                                production_frequency_hz=production_frequency_hz,
                                title=f"{resolved_input.name} / {profile.display_name} / {channel_name}",
                                manual_reference_time_s=manual_reference_time_s,
                            )
                            _stft_candidate_path_plot(
                                summary_directory / f"{stream_id}__stft_candidate_path.png",
                                analysis=analysis,
                                result=result,
                                title=f"{resolved_input.name} / {profile.display_name} / {channel_name}",
                                manual_reference_time_s=manual_reference_time_s,
                            )
                            _selected_rank_plot(
                                summary_directory / f"{stream_id}__selected_rank.png",
                                result,
                                title=f"{resolved_input.name} / {profile.display_name} / {channel_name}",
                            )
                            _disagreement_plot(
                                summary_directory / f"{stream_id}__path_disagreement.png",
                                analysis,
                                result,
                                title=f"{resolved_input.name} / {profile.display_name} / {channel_name}",
                            )
                            _dp_cost_competition_plot(
                                summary_directory / f"{stream_id}__dp_cost_competition.png",
                                audit=audit,
                                result=result,
                                title=f"{resolved_input.name} / {profile.display_name} / {channel_name}",
                                manual_reference_time_s=manual_reference_time_s,
                            )

                if not np.array_equal(
                    production_frequency_hz,
                    analysis.signal_detection_result.refined_frequency_hz,
                    equal_nan=True,
                ):
                    raise RuntimeError("Research calibration mutated a production result array.")
        raw_hash_after = _sha256(resolved_input)
        if raw_hash_after != raw_hash_before:
            raise RuntimeError("Raw data hash changed during read-only calibration run.")

    _write_csv(output_directory / "calibration_summary.csv", rows)
    shutil.copy2(output_directory / "calibration_summary.csv", summary_directory / "calibration_summary.csv")
    synthetic_rows = _run_calibration_synthetic_regression()
    _write_csv(output_directory / "synthetic_regression_summary.csv", synthetic_rows)
    shutil.copy2(
        output_directory / "synthetic_regression_summary.csv",
        summary_directory / "synthetic_regression_summary.csv",
    )
    _write_json(
        output_directory / "calibration_metadata.json",
        _calibration_run_metadata(
            configuration=configuration,
            input_metadata=input_metadata,
            profile_metadata=profile_metadata,
            output_directory=output_directory,
        ),
    )
    _write_calibration_readme(output_directory)


def _run_calibration_synthetic_regression() -> list[dict[str, Any]]:
    """Return all A–H truth metrics for every explicitly evaluated preset."""
    rows: list[dict[str, Any]] = []
    for top_k in CALIBRATION_TOP_K:
        for preset_name, path_config in research_aggressiveness_presets(top_k=top_k).items():
            for benchmark in run_synthetic_global_path_benchmark(config=path_config):
                global_metrics = next(
                    metrics
                    for metrics in benchmark.metrics
                    if metrics.method == "task021a_global_path"
                )
                row: dict[str, Any] = {
                    "case_id": benchmark.case.case_id,
                    "preset": preset_name,
                    "top_k": top_k,
                }
                row.update(path_config.to_metadata())
                row.update(global_metrics.to_dict())
                rows.append(row)
    return rows


def _calibration_input_metadata(
    *,
    input_path: Path,
    input_sha256: str,
    input_selection_mode: str,
    loaded: Any,
) -> dict[str, Any]:
    return {
        "source_path": str(input_path),
        "source_filename": input_path.name,
        "source_sha256": input_sha256,
        "source_size_bytes": input_path.stat().st_size,
        "source_selection_mode": input_selection_mode,
        "formal_reader": {
            "source_path": str(loaded.source_path.resolve()),
            "column_count": loaded.column_count,
            "row_count": loaded.row_count,
            "time_column_index": loaded.time_column_index,
            "voltage_column_indices": dict(loaded.voltage_column_indices),
            "channel_names": list(loaded.channel_names),
            "unselected_column_indices": list(loaded.unselected_column_indices),
        },
    }


def _calibration_run_metadata(
    *,
    configuration: Any,
    input_metadata: Sequence[Mapping[str, Any]],
    profile_metadata: Sequence[Mapping[str, Any]],
    output_directory: Path,
) -> dict[str, Any]:
    """Record every calibration choice without modifying Production defaults."""
    return {
        "mode": "calibration",
        "task": "TASK-021B",
        "status": GlobalPathConfig.DEVELOPMENT_STATUS,
        "research_branch": _git_value("branch", "--show-current"),
        "research_commit": _git_value("rev-parse", "HEAD"),
        "research_source_root": str(REPOSITORY_ROOT),
        "dps_studio_import_path": str(Path(dps_studio.__file__).resolve()),
        "config_path": str(configuration.config_path),
        "raw_inputs": list(input_metadata),
        "stft_profiles": list(profile_metadata),
        "top_k_sweep": list(CALIBRATION_TOP_K),
        "presets_by_top_k": {
            str(top_k): {
                name: config.to_metadata()
                for name, config in research_aggressiveness_presets(top_k=top_k).items()
            }
            for top_k in CALIBRATION_TOP_K
        },
        "fixed_scientific_definitions": {
            "stft_profiles": "unchanged configured Balanced and High-time profiles",
            "candidate_separation": "unchanged GlobalPathConfig extraction definition",
            "node_evidence": "unchanged candidate_node_cost definition",
            "continuity": "unchanged candidate_transition_cost definition",
            "core_dp_solver": "unchanged exact first-order DP and backtracking",
        },
        "calibrated_cost_terms": [
            "null_node_cost",
            "ridge_entry_cost",
            "ridge_exit_cost",
        ],
        "manual_event_reference_in_path_cost": False,
        "production_default_modified": False,
        "channel_fusion": False,
        "profile_fusion": False,
        "synthetic_seed": DEFAULT_SYNTHETIC_SEED,
        "analysis_timestamp_utc": datetime.now(UTC).isoformat(),
        "output_directory": str(output_directory),
    }


def _calibration_stream_id(*, input_path: Path, profile: Any, channel_name: str) -> str:
    """Build a portable display/output identifier without source-specific rules."""
    return f"{input_path.stem}__{profile.profile_id.value}__{channel_name}"


def _write_calibration_readme(output_directory: Path) -> None:
    lines = [
        "# TASK-021B real-data Global Path calibration",
        "",
        "Research-only, development / uncalibrated; no Production configuration was modified.",
        "",
        "`calibration_summary.csv` has one row per dataset/profile/channel/K/preset.",
        "`synthetic_regression_summary.csv` has the A–H truth metrics for the same grid.",
        "`cost_audits/` contains full per-state DP records for the conservative K=5 baseline",
        "and the balanced K=20 view of every stream.",
        "`00_RESULT_SUMMARY/` contains the comparison tables and key plots.",
        "",
        "Candidate-vs-NULL margin is best candidate cumulative cost minus NULL cumulative cost.",
        "A negative margin favors a candidate; a positive margin favors NULL.",
        "Manual event references, when inside an input time range, are plot-only diagnostics.",
    ]
    (output_directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _profile_metadata(profile: Any) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id.value,
        "display_name": profile.display_name,
        "window_name": profile.window_name,
        "window_length_samples": profile.window_length_samples,
        "overlap_samples": profile.overlap_samples,
        "hop_samples": profile.hop_samples,
        "nfft": profile.nfft,
        "minimum_frequency_hz": profile.minimum_frequency_hz,
        "maximum_frequency_hz": profile.maximum_frequency_hz,
        "ridge_refinement": profile.ridge_refinement,
    }


def _run_synthetic_benchmark(output_directory: Path) -> None:
    all_benchmarks: dict[int, tuple[SyntheticBenchmarkResult, ...]] = {}
    metric_rows: list[dict[str, str | int | float | None]] = []
    for top_k in REQUIRED_TOP_K:
        config = GlobalPathConfig(top_k=top_k)
        benchmarks = run_synthetic_global_path_benchmark(config=config)
        all_benchmarks[top_k] = benchmarks
        for benchmark in benchmarks:
            for metrics in benchmark.metrics:
                row = metrics.to_dict()
                row["evaluated_top_k"] = top_k
                metric_rows.append(row)
    _write_csv(output_directory / "synthetic_benchmark_table.csv", metric_rows)
    _write_synthetic_artifacts(output_directory / "synthetic", all_benchmarks[5])
    _write_parameter_sensitivity(output_directory, all_benchmarks)
    _write_json(
        output_directory / "benchmark_metadata.json",
        {
            "mode": "benchmark",
            "task": "TASK-021A",
            "synthetic_seed": DEFAULT_SYNTHETIC_SEED,
            "required_top_k": list(REQUIRED_TOP_K),
            "default_global_path_config": GlobalPathConfig().to_metadata(),
        },
    )


def _write_synthetic_artifacts(
    output_directory: Path,
    benchmarks: tuple[SyntheticBenchmarkResult, ...],
) -> None:
    output_directory.mkdir()
    for benchmark in benchmarks:
        case_directory = output_directory / benchmark.case.case_id
        case_directory.mkdir()
        _candidate_cloud_plot(
            case_directory / "candidate_cloud.png",
            benchmark.global_path,
            production_frequency_hz=benchmark.production_frequency_hz,
            argmax_frequency_hz=benchmark.argmax_frequency_hz,
            truth_frequency_hz=benchmark.case.truth_frequency_hz,
            title=benchmark.case.case_id,
        )
        _selected_rank_plot(
            case_directory / "selected_rank.png",
            benchmark.global_path,
            title=benchmark.case.case_id,
        )
        _synthetic_disagreement_plot(case_directory / "path_disagreement.png", benchmark)
        rows = _synthetic_disagreement_rows(benchmark)
        _write_csv(case_directory / "path_disagreement.csv", rows)


def _candidate_cloud_plot(
    path: Path,
    result: GlobalRidgePathResult,
    *,
    production_frequency_hz: FloatArray,
    title: str,
    argmax_frequency_hz: FloatArray | None = None,
    truth_frequency_hz: FloatArray | None = None,
    manual_reference_time_s: float | None = None,
) -> None:
    figure = Figure(figsize=(12.0, 5.5), constrained_layout=True)
    axis = figure.subplots()
    for rank in range(1, result.config.top_k + 1):
        points = [
            item
            for frame in result.candidate_set.candidates_by_frame
            for item in frame
            if item.candidate_rank == rank
        ]
        if points:
            axis.scatter(
                [item.time_s for item in points],
                [item.refined_frequency_hz * 1.0e-9 for item in points],
                s=max(7.0, 24.0 - rank),
                alpha=0.45,
                label=f"candidate rank {rank}",
            )
    time_s = result.time_s
    if truth_frequency_hz is not None:
        axis.plot(time_s, truth_frequency_hz * 1.0e-9, color="black", linewidth=2.0, label="truth")
    if argmax_frequency_hz is not None:
        axis.plot(time_s, argmax_frequency_hz * 1.0e-9, color="0.55", linewidth=1.0, label="argmax")
    axis.plot(time_s, production_frequency_hz * 1.0e-9, color="#d55e00", linewidth=1.3, label="production")
    axis.plot(
        time_s,
        result.selected_refined_frequency_hz * 1.0e-9,
        color="#0072b2",
        linewidth=1.8,
        label="global path",
    )
    if manual_reference_time_s is not None:
        axis.axvline(
            manual_reference_time_s,
            color="0.3",
            linestyle="--",
            label="manual reference (diagnostic only)",
        )
    axis.set(xlabel="Time (s)", ylabel="Frequency (GHz)", title=f"Candidate cloud — {title}")
    axis.legend(loc="best", fontsize=7, ncols=2)
    _save_figure(figure, path)


def _stft_candidate_path_plot(
    path: Path,
    *,
    analysis: ChannelAnalysis,
    result: GlobalRidgePathResult,
    title: str,
    manual_reference_time_s: float | None,
) -> None:
    """Render the unchanged STFT with retained candidates and one Research path."""
    stft = analysis.stft_result
    frequency_mask = (
        (stft.frequency_hz >= result.candidate_set.minimum_frequency_hz)
        & (stft.frequency_hz <= result.candidate_set.maximum_frequency_hz)
    )
    magnitude = np.abs(stft.spectrum[frequency_mask, :])
    finite_magnitude = magnitude[np.isfinite(magnitude) & (magnitude > 0.0)]
    reference_magnitude = float(np.max(finite_magnitude)) if finite_magnitude.size else 1.0
    relative_db = 20.0 * np.log10(np.maximum(magnitude, np.finfo(np.float64).tiny) / reference_magnitude)
    figure = Figure(figsize=(12.0, 5.5), constrained_layout=True)
    axis = figure.subplots()
    mesh = axis.pcolormesh(
        stft.time_s,
        stft.frequency_hz[frequency_mask] * 1.0e-9,
        relative_db,
        shading="auto",
        cmap="viridis",
        vmin=-60.0,
        vmax=0.0,
        rasterized=True,
    )
    for rank in range(1, result.config.top_k + 1):
        points = [
            item
            for frame in result.candidate_set.candidates_by_frame
            for item in frame
            if item.candidate_rank == rank
        ]
        if points:
            axis.scatter(
                [item.time_s for item in points],
                [item.refined_frequency_hz * 1.0e-9 for item in points],
                s=6.0,
                alpha=0.3,
                color="white",
            )
    axis.plot(
        result.time_s,
        result.selected_refined_frequency_hz * 1.0e-9,
        color="#d55e00",
        linewidth=1.6,
        label="balanced Global Path",
    )
    if manual_reference_time_s is not None:
        axis.axvline(
            manual_reference_time_s,
            color="white",
            linestyle="--",
            label="manual reference (diagnostic only)",
        )
    figure.colorbar(mesh, ax=axis, label="STFT magnitude (dB relative to stream maximum)")
    axis.set(xlabel="Time (s)", ylabel="Frequency (GHz)", title=f"STFT / candidates / path — {title}")
    axis.legend(loc="best", fontsize=8)
    _save_figure(figure, path)


def _selected_rank_plot(path: Path, result: GlobalRidgePathResult, *, title: str) -> None:
    figure = Figure(figsize=(12.0, 3.2), constrained_layout=True)
    axis = figure.subplots()
    rank = result.selected_candidate_rank.astype(np.float64)
    axis.step(result.time_s, rank, where="mid", color="#009e73")
    axis.set(
        xlabel="Time (s)",
        ylabel="Selected rank (0 = NULL)",
        title=f"Selected candidate rank — {title}",
        yticks=range(result.config.top_k + 1),
    )
    axis.grid(alpha=0.25)
    _save_figure(figure, path)


def _dp_cost_competition_plot(
    path: Path,
    *,
    audit: Any,
    result: GlobalRidgePathResult,
    title: str,
    manual_reference_time_s: float | None,
) -> None:
    """Show the forward-DP candidate-versus-NULL competition at every frame."""
    best_candidate_cumulative = np.fromiter(
        (
            float(np.min(costs[:-1])) if costs.size > 1 else math.nan
            for costs in audit.cumulative_costs_by_frame
        ),
        dtype=np.float64,
        count=result.time_s.size,
    )
    null_cumulative = np.fromiter(
        (float(costs[-1]) for costs in audit.cumulative_costs_by_frame),
        dtype=np.float64,
        count=result.time_s.size,
    )
    figure = Figure(figsize=(12.0, 7.5), constrained_layout=True)
    cumulative_axis, margin_axis, state_axis = figure.subplots(
        3,
        1,
        sharex=True,
        height_ratios=(3, 1.35, 1),
    )
    cumulative_axis.plot(
        result.time_s,
        best_candidate_cumulative,
        color="#0072b2",
        linewidth=1.3,
        label="best candidate cumulative cost",
    )
    cumulative_axis.plot(
        result.time_s,
        null_cumulative,
        color="#d55e00",
        linewidth=1.3,
        label="NULL cumulative cost",
    )
    if manual_reference_time_s is not None:
        cumulative_axis.axvline(
            manual_reference_time_s,
            color="0.3",
            linestyle="--",
            label="manual reference (diagnostic only)",
        )
        margin_axis.axvline(manual_reference_time_s, color="0.3", linestyle="--")
        state_axis.axvline(manual_reference_time_s, color="0.3", linestyle="--")
    cumulative_axis.set(
        ylabel="Forward DP cumulative cost",
        title=f"DP cost competition — {title}",
    )
    cumulative_axis.legend(loc="best", fontsize=8)
    cumulative_axis.grid(alpha=0.25)
    margin_axis.axhline(0.0, color="0.2", linewidth=0.8)
    margin_axis.plot(
        result.time_s,
        audit.candidate_vs_null_cost_margin,
        color="#6a3d9a",
        linewidth=1.1,
    )
    margin_axis.set(
        ylabel="Best candidate −\nNULL cost",
        title="Negative margin favors candidate; positive margin favors NULL",
    )
    margin_axis.grid(alpha=0.25)
    state_axis.step(
        result.time_s,
        result.selected_candidate_rank,
        where="mid",
        color="#009e73",
    )
    state_axis.set(
        xlabel="Time (s)",
        ylabel="Selected\nrank (0=NULL)",
        yticks=range(result.config.top_k + 1),
    )
    state_axis.grid(alpha=0.25)
    _save_figure(figure, path)


def _disagreement_plot(
    path: Path,
    analysis: ChannelAnalysis,
    result: GlobalRidgePathResult,
    *,
    title: str,
) -> None:
    production = analysis.signal_detection_result.refined_frequency_hz
    disagreement = _disagreement_mask(production, result.selected_refined_frequency_hz)
    figure = Figure(figsize=(12.0, 4.0), constrained_layout=True)
    axis = figure.subplots()
    axis.scatter(
        result.time_s[disagreement],
        production[disagreement] * 1.0e-9,
        color="#d55e00",
        s=18,
        label="production",
    )
    axis.scatter(
        result.time_s[disagreement],
        result.selected_refined_frequency_hz[disagreement] * 1.0e-9,
        color="#0072b2",
        s=18,
        label="global path",
    )
    axis.set(xlabel="Time (s)", ylabel="Frequency (GHz)", title=f"Disagreement only — {title}")
    axis.legend()
    _save_figure(figure, path)


def _synthetic_disagreement_plot(path: Path, benchmark: SyntheticBenchmarkResult) -> None:
    figure = Figure(figsize=(12.0, 4.0), constrained_layout=True)
    axis = figure.subplots()
    time_s = benchmark.case.stft_result.time_s
    for name, values, color in (
        ("truth", benchmark.case.truth_frequency_hz, "black"),
        ("argmax", benchmark.argmax_frequency_hz, "0.55"),
        ("production", benchmark.production_frequency_hz, "#d55e00"),
        ("global", benchmark.global_path.selected_refined_frequency_hz, "#0072b2"),
    ):
        disagreement = _disagreement_mask(benchmark.case.truth_frequency_hz, values)
        axis.scatter(time_s[disagreement], values[disagreement] * 1.0e-9, s=16, label=name, color=color)
    axis.set(xlabel="Time (s)", ylabel="Frequency (GHz)", title="Truth disagreement frames only")
    axis.legend()
    _save_figure(figure, path)


def _disagreement_rows(
    analysis: ChannelAnalysis,
    result: GlobalRidgePathResult,
) -> list[dict[str, Any]]:
    production = analysis.signal_detection_result.refined_frequency_hz
    mask = _disagreement_mask(production, result.selected_refined_frequency_hz)
    rows: list[dict[str, Any]] = []
    for frame_index in np.flatnonzero(mask):
        index = int(frame_index)
        selected_rank = int(result.selected_candidate_rank[index])
        candidates = result.candidate_set.candidates_by_frame[index]
        if not candidates:
            rows.append(_candidate_row(index, None, analysis, result, selected_rank))
        else:
            rows.extend(
                _candidate_row(index, candidate, analysis, result, selected_rank)
                for candidate in candidates
            )
    return rows


def _candidate_row(
    frame_index: int,
    candidate: RidgeCandidate | None,
    analysis: ChannelAnalysis,
    result: GlobalRidgePathResult,
    selected_rank: int,
) -> dict[str, Any]:
    candidate_rank = 0 if candidate is None else candidate.candidate_rank
    return {
        "frame_index": frame_index,
        "time_s": float(result.time_s[frame_index]),
        "production_frequency_hz": float(
            analysis.signal_detection_result.refined_frequency_hz[frame_index]
        ),
        "global_frequency_hz": float(result.selected_refined_frequency_hz[frame_index]),
        "candidate_rank": candidate_rank,
        "candidate_frequency_hz": math.nan if candidate is None else candidate.refined_frequency_hz,
        "candidate_amplitude": math.nan if candidate is None else candidate.peak_amplitude,
        "peak_to_background_db": math.nan if candidate is None else candidate.peak_to_background_db,
        "peak_to_competitor_db": math.nan if candidate is None else candidate.peak_to_competitor_db,
        "candidate_node_cost": (
            result.config.null_node_cost
            if candidate is None
            else candidate_node_cost(candidate, result.config)
        ),
        "selected": candidate_rank == selected_rank,
        "selected_transition_cost": float(result.transition_cost[frame_index]),
        "selected_cumulative_cost": float(result.cumulative_cost[frame_index]),
        "selection_reason": "global minimum cumulative DP cost",
        "physical_identity": "unreviewed",
    }


def _synthetic_disagreement_rows(benchmark: SyntheticBenchmarkResult) -> list[dict[str, Any]]:
    result = benchmark.global_path
    mask = _disagreement_mask(benchmark.case.truth_frequency_hz, result.selected_refined_frequency_hz)
    rows: list[dict[str, Any]] = []
    for frame_index in np.flatnonzero(mask):
        index = int(frame_index)
        rows.append(
            {
                "frame_index": index,
                "time_s": float(result.time_s[index]),
                "truth_frequency_hz": float(benchmark.case.truth_frequency_hz[index]),
                "argmax_frequency_hz": float(benchmark.argmax_frequency_hz[index]),
                "production_frequency_hz": float(benchmark.production_frequency_hz[index]),
                "global_frequency_hz": float(result.selected_refined_frequency_hz[index]),
                "selected_rank": int(result.selected_candidate_rank[index]),
                "node_cost": float(result.node_cost[index]),
                "transition_cost": float(result.transition_cost[index]),
                "cumulative_cost": float(result.cumulative_cost[index]),
            }
        )
    return rows


def _real_stream_summary(
    stream_name: str,
    analysis: ChannelAnalysis,
    result: GlobalRidgePathResult,
    *,
    manual_reference_time_s: float | None,
    disagreement_count: int,
) -> dict[str, Any]:
    production = analysis.signal_detection_result.refined_frequency_hz
    selected_rank = result.selected_candidate_rank
    time_s = result.time_s
    pre_reference = (
        time_s < manual_reference_time_s
        if manual_reference_time_s is not None
        else np.zeros(time_s.size, dtype=np.bool_)
    )
    tail = np.arange(time_s.size) >= int(0.9 * time_s.size)
    production_nan_global_secondary = (
        ~np.isfinite(production) & np.isfinite(result.selected_refined_frequency_hz) & (selected_rank > 1)
    )
    multiple_candidates = np.fromiter(
        (len(frame) >= 2 for frame in result.candidate_set.candidates_by_frame),
        dtype=np.bool_,
        count=time_s.size,
    )
    return {
        "stream": stream_name,
        "frame_count": int(time_s.size),
        "global_null_frame_count": int(np.count_nonzero(result.is_null)),
        "selected_rank_1_count": int(np.count_nonzero(selected_rank == 1)),
        "selected_rank_2_count": int(np.count_nonzero(selected_rank == 2)),
        "selected_rank_3_count": int(np.count_nonzero(selected_rank == 3)),
        "selected_rank_4_plus_count": int(np.count_nonzero(selected_rank >= 4)),
        "production_global_disagreement_frame_count": disagreement_count,
        "pre_reference_global_selected_count": int(
            np.count_nonzero(pre_reference & ~result.is_null)
        ),
        "multiple_parallel_candidate_frame_count": int(np.count_nonzero(multiple_candidates)),
        "low_frequency_selected_below_0_5ghz_count": int(
            np.count_nonzero(result.selected_refined_frequency_hz < 0.5e9)
        ),
        "production_nan_global_rank_gt1_count": int(
            np.count_nonzero(production_nan_global_secondary)
        ),
        "tail_selected_frame_count": int(np.count_nonzero(tail & ~result.is_null)),
        "tail_physical_identity": "unreviewed",
        "production_array_sha256": _array_sha256(production),
        "production_array_unchanged_after_global": True,
        "manual_reference_used_for_path": False,
    }


def _write_parameter_sensitivity(
    output_directory: Path,
    benchmarks: Mapping[int, tuple[SyntheticBenchmarkResult, ...]],
) -> None:
    rows: list[dict[str, Any]] = []
    for top_k, results in benchmarks.items():
        global_metrics = [
            metrics
            for result in results
            for metrics in result.metrics
            if metrics.method == "task021a_global_path"
        ]
        rows.append(
            {
                "top_k": top_k,
                "continuity_weight": 1.0,
                "ridge_entry_cost": 3.0,
                "total_wrong_branch_frames": sum(
                    item.wrong_branch_frame_count for item in global_metrics
                ),
                "total_null_false_negatives": sum(
                    item.null_false_negative_count for item in global_metrics
                ),
                "total_false_pre_event_detections": sum(
                    item.false_pre_event_detection_count for item in global_metrics
                ),
            }
        )
    for continuity_weight in (0.5, 2.0):
        config = replace(GlobalPathConfig(top_k=5), continuity_weight=continuity_weight)
        results = run_synthetic_global_path_benchmark(config=config)
        global_metrics = [
            metrics
            for result in results
            for metrics in result.metrics
            if metrics.method == "task021a_global_path"
        ]
        rows.append(
            {
                "top_k": 5,
                "continuity_weight": continuity_weight,
                "ridge_entry_cost": config.ridge_entry_cost,
                "total_wrong_branch_frames": sum(
                    item.wrong_branch_frame_count for item in global_metrics
                ),
                "total_null_false_negatives": sum(
                    item.null_false_negative_count for item in global_metrics
                ),
                "total_false_pre_event_detections": sum(
                    item.false_pre_event_detection_count for item in global_metrics
                ),
            }
        )
    _write_csv(output_directory / "parameter_sensitivity.csv", rows)


def _disagreement_mask(left: FloatArray, right: FloatArray) -> BoolArray:
    left_finite = np.isfinite(left)
    right_finite = np.isfinite(right)
    mask: BoolArray = np.asarray(
        (left_finite != right_finite)
        | (left_finite & right_finite & (np.abs(left - right) > 1.0e6)),
        dtype=np.bool_,
    )
    return mask


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
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=True) + "\n",
        encoding="utf-8",
    )


def _write_real_result_summary(output_directory: Path, real_run: RealDataRun) -> None:
    """Put the first real-data figures and summaries at a predictable entry point."""
    summary_directory = output_directory / "00_RESULT_SUMMARY"
    summary_directory.mkdir()
    shutil.copy2(
        output_directory / "real_data" / "real_stream_summary.csv",
        summary_directory / "real_stream_summary.csv",
    )
    for stream_directory in real_run.stream_directories:
        stream_name = stream_directory.name
        for filename in (
            "candidate_cloud.png",
            "path_disagreement.png",
            "selected_rank.png",
            "summary.json",
        ):
            shutil.copy2(
                stream_directory / filename,
                summary_directory / f"{stream_name}__{filename}",
            )


def _real_run_metadata(
    *,
    input_path: Path,
    input_sha256: str,
    input_selection_mode: str,
    loaded: Any,
    configuration: Any,
    real_run: RealDataRun,
    output_directory: Path,
) -> dict[str, Any]:
    return {
        "mode": "real",
        "task": "TASK-021A",
        "status": GlobalPathConfig.DEVELOPMENT_STATUS,
        "source_path": str(input_path),
        "source_filename": input_path.name,
        "source_sha256": input_sha256,
        "source_size_bytes": input_path.stat().st_size,
        "source_selection_mode": input_selection_mode,
        "formal_reader": {
            "source_path": str(loaded.source_path.resolve()),
            "column_count": loaded.column_count,
            "row_count": loaded.row_count,
            "time_column_index": loaded.time_column_index,
            "voltage_column_indices": dict(loaded.voltage_column_indices),
            "channel_names": list(loaded.channel_names),
            "unselected_column_indices": list(loaded.unselected_column_indices),
        },
        "research_branch": _git_value("branch", "--show-current"),
        "research_commit": _git_value("rev-parse", "HEAD"),
        "research_source_root": str(REPOSITORY_ROOT),
        "dps_studio_import_path": str(Path(dps_studio.__file__).resolve()),
        "config_path": str(configuration.config_path),
        "stft_profiles": list(real_run.profile_metadata),
        "global_path_config": GlobalPathConfig().to_metadata(),
        "analysis_timestamp_utc": datetime.now(UTC).isoformat(),
        "output_directory": str(output_directory),
        "manual_event_reference_in_path_cost": False,
        "production_default_modified": False,
        "channel_fusion": False,
        "profile_fusion": False,
        "physical_identity": "unreviewed",
        "real_streams": list(real_run.summaries),
    }


def _git_value(*arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _write_real_readme(
    output_directory: Path,
    metadata: Mapping[str, Any],
    real_summary: Sequence[Mapping[str, Any]],
) -> None:
    lines = [
        "# TASK-021A real-data research artifacts",
        "",
        "Development / uncalibrated; not a production algorithm.",
        "",
        f"Source: `{metadata['source_path']}`",
        f"Source SHA-256: `{metadata['source_sha256']}`",
        "",
        "Top-level results are in `00_RESULT_SUMMARY/`; detailed diagnostics are in `real_data/`.",
        "",
        "Each profile/channel stream was solved independently. Manual event reference was plot-only.",
        "Candidate rank 0 means NULL; NULL frequencies are NaN. Tail identities remain unreviewed.",
        "",
        f"Real stream count: {len(real_summary)}",
    ]
    (output_directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=160)
    figure.clear()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _array_sha256(array: NDArray[np.generic]) -> str:
    return hashlib.sha256(np.asarray(array).tobytes(order="C")).hexdigest().upper()


if __name__ == "__main__":
    raise SystemExit(main())
