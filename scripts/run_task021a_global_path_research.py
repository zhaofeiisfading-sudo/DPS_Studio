"""Generate non-overwriting TASK-021A synthetic and real-data research artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

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
    track_global_candidate_path,
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
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


def main(arguments: Sequence[str] | None = None) -> int:
    """Run deterministic research without changing production outputs or raw data."""
    parsed = _parse_arguments(arguments)
    output_directory = parsed.output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"Research output already exists: {output_directory}")
    raw_path = parsed.raw_data.resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw input does not exist: {raw_path}")
    output_directory.mkdir(parents=True)
    raw_hash_before = _sha256(raw_path)

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

    real_summary = _run_real_data(
        raw_path=raw_path,
        config_path=parsed.config.resolve(),
        output_directory=output_directory / "real_data",
    )
    raw_hash_after = _sha256(raw_path)
    if raw_hash_after != raw_hash_before:
        raise RuntimeError("Raw data hash changed during read-only research run.")
    metadata = {
        "task": "TASK-021A",
        "status": GlobalPathConfig.DEVELOPMENT_STATUS,
        "scope": "single profile / single channel; every stream solved independently",
        "synthetic_seed": DEFAULT_SYNTHETIC_SEED,
        "required_top_k": list(REQUIRED_TOP_K),
        "default_global_path_config": GlobalPathConfig().to_metadata(),
        "raw_data_path": str(raw_path),
        "raw_data_sha256_before": raw_hash_before,
        "raw_data_sha256_after": raw_hash_after,
        "manual_event_reference_in_path_cost": False,
        "second_order_curvature": False,
        "channel_fusion": False,
        "profile_fusion": False,
        "production_default_modified": False,
        "physical_identity": "unreviewed",
        "real_streams": real_summary,
    }
    _write_json(output_directory / "metadata.json", metadata)
    _write_readme(output_directory, raw_hash_before, real_summary)
    return 0


def _parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--raw-data", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser.parse_args(arguments)


def _run_real_data(
    *,
    raw_path: Path,
    config_path: Path,
    output_directory: Path,
) -> list[dict[str, Any]]:
    configuration = load_workflow_config(config_path, repository_root=REPOSITORY_ROOT)
    loaded = read_delimited_signals(
        raw_path,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    )
    output_directory.mkdir()
    summaries: list[dict[str, Any]] = []
    for profile in configuration.analysis.profiles:
        for channel_name, record in loaded.records.items():
            # Supplying one record proves that no other channel can affect this stream.
            analysis = analyze_profile(
                {channel_name: record},
                profile=profile,
                analysis_start_time_s=configuration.analysis.analysis_start_time_s,
                analysis_end_time_s=configuration.analysis.analysis_end_time_s,
                manual_event_reference_time_s=(
                    configuration.analysis.manual_event_reference_time_s
                ),
                vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
                detection_config=configuration.quality.signal_detection,
                event_candidate_config=configuration.event_candidate,
                background_guard_window_scale=(
                    configuration.quality.background_guard_window_scale
                ),
                minimum_background_bin_count=(
                    configuration.quality.minimum_background_bin_count
                ),
                automatic_ridge_selection_config=(
                    configuration.automatic_ridge_selection
                ),
                velocity_correction_config=configuration.velocity_correction,
            )[channel_name]
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
                manual_reference_time_s=(
                    configuration.analysis.manual_event_reference_time_s
                ),
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
                manual_reference_time_s=(
                    configuration.analysis.manual_event_reference_time_s
                ),
                disagreement_count=len({int(row["frame_index"]) for row in disagreement_rows}),
            )
            _write_json(stream_directory / "summary.json", summary)
            summaries.append(summary)
    _write_csv(output_directory / "real_stream_summary.csv", summaries)
    return summaries


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


def _write_readme(
    output_directory: Path,
    raw_hash: str,
    real_summary: Sequence[Mapping[str, Any]],
) -> None:
    lines = [
        "# TASK-021A research artifacts",
        "",
        "Development / uncalibrated; not a production algorithm.",
        "",
        f"Raw SHA-256: `{raw_hash}`",
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
