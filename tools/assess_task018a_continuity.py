"""Run TASK-018A read-only event and continuity assessment on every raw CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import (
    AutomaticRidgeExtractionMode,
    AutomaticRidgeSelectionConfig,
    RidgeContinuityStatus,
)
from dps_studio.core.workflow import (
    ChannelAnalysis,
    WorkflowConfiguration,
    analyze_profile,
    load_workflow_config,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _analysis_context(
    configuration: WorkflowConfiguration,
    records: Mapping[str, SignalRecord],
) -> tuple[float, float, str, float | None]:
    data_start_s = max(record.start_time_s for record in records.values())
    data_end_s = min(record.end_time_s for record in records.values())
    configured_start_s = configuration.analysis.analysis_start_time_s
    configured_end_s = configuration.analysis.analysis_end_time_s
    if (
        configured_start_s is not None
        and configured_end_s is not None
        and data_start_s <= configured_start_s < configured_end_s <= data_end_s
    ):
        start_s = configured_start_s
        end_s = configured_end_s
        range_source = "configuration"
    else:
        start_s = data_start_s
        end_s = data_end_s
        range_source = "full_common_data_range"
    manual_reference_s = configuration.analysis.event_reference_time_s
    if manual_reference_s is not None and not (
        start_s <= manual_reference_s <= end_s
    ):
        manual_reference_s = None
    return start_s, end_s, range_source, manual_reference_s


def _analyze_source(
    source: Path,
    configuration: WorkflowConfiguration,
) -> tuple[Mapping[str, ChannelAnalysis], str, float, float, float | None]:
    loaded = read_delimited_signals(
        source,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    )
    start_s, end_s, range_source, manual_reference_s = _analysis_context(
        configuration,
        loaded.records,
    )
    analyses = analyze_profile(
        loaded.records,
        profile=configuration.analysis.default_profile,
        analysis_start_time_s=start_s,
        analysis_end_time_s=end_s,
        manual_event_reference_time_s=manual_reference_s,
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        automatic_ridge_selection_config=AutomaticRidgeSelectionConfig(
            mode=AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK,
        ),
        background_guard_window_scale=(
            configuration.quality.background_guard_window_scale
        ),
        minimum_background_bin_count=(
            configuration.quality.minimum_background_bin_count
        ),
        assume_pre_event_zero_for_display=(
            configuration.plot.assume_pre_event_zero_for_display
        ),
        pre_event_display_velocity_m_s=(
            configuration.plot.pre_event_display_velocity_m_s
        ),
    )
    return analyses, range_source, start_s, end_s, manual_reference_s


def _candidate_metric(analysis: ChannelAnalysis) -> dict[str, float | int | None]:
    detection = analysis.signal_detection_result
    candidate_s = detection.detected_event_candidate_time_s
    if candidate_s is None:
        return {
            "run_frame_count": 0,
            "peak_to_background_db": None,
            "peak_to_competitor_db": None,
            "refined_frequency_hz": None,
        }
    index = int(np.searchsorted(detection.time_s, candidate_s))
    return {
        "run_frame_count": detection.detected_event_candidate_run_frame_count,
        "peak_to_background_db": float(detection.peak_to_background_db[index]),
        "peak_to_competitor_db": float(detection.peak_to_competitor_db[index]),
        "refined_frequency_hz": float(detection.refined_frequency_hz[index]),
    }


def _event_row(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    range_source: str,
    analysis_start_s: float,
    analysis_end_s: float,
    manual_reference_s: float | None,
) -> dict[str, object]:
    detection = analysis.signal_detection_result
    candidate_s = detection.detected_event_candidate_time_s
    primary_s = analysis.stream_event_candidates.primary_candidate_time_s
    return {
        "source": source.name,
        "channel": channel_name,
        "analysis_range_source": range_source,
        "analysis_start_time_s": analysis_start_s,
        "analysis_end_time_s": analysis_end_s,
        "manual_event_reference_time_s": manual_reference_s,
        "detected_event_time_s": candidate_s,
        "detected_event_time_us_display_only": (
            None if candidate_s is None else candidate_s * 1.0e6
        ),
        "detection_status": (
            "spectral_detection_candidate" if candidate_s is not None else "no_candidate"
        ),
        "fallback_used": False,
        "fallback_behavior": "none; returns None and analysis continues",
        "event_level_primary_candidate_time_s": primary_s,
        "event_level_primary_candidate_time_us_display_only": (
            None if primary_s is None else primary_s * 1.0e6
        ),
        "continuity_event_reference_time_s": (
            analysis.event_aware_continuity_result.event_reference_time_s
        ),
        "continuity_event_reference_source": (
            analysis.event_aware_continuity_result.event_reference_source
        ),
        "relevant_algorithm_metric": json.dumps(
            _candidate_metric(analysis),
            sort_keys=True,
        ),
        "visual_comparison": "pending_engineering_review",
    }


def _largest_steps(analysis: ChannelAnalysis, limit: int = 5) -> list[dict[str, object]]:
    result = analysis.event_aware_continuity_result
    values = np.abs(result.delta_frequency_from_previous_hz)
    finite_indices = np.flatnonzero(np.isfinite(values))
    ordered = finite_indices[np.argsort(values[finite_indices])[::-1]][:limit]
    return [
        {
            "frame_index": int(index),
            "time_s": float(result.time_s[index]),
            "absolute_step_hz": float(values[index]),
            "status": result.statuses[index].value,
        }
        for index in ordered
    ]


def _continuity_row(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> dict[str, object]:
    result = analysis.event_aware_continuity_result
    detection = analysis.signal_detection_result
    isolated = [
        index
        for index, status in enumerate(result.statuses)
        if status is RidgeContinuityStatus.ISOLATED_JUMP
    ]
    event_transition = [
        index
        for index, status in enumerate(result.statuses)
        if status is RidgeContinuityStatus.EVENT_TRANSITION
    ]
    measured_count = sum(state.value == "measured" for state in detection.signal_states)
    suspicious = [
        {
            "frame_index": index,
            "time_s": float(result.time_s[index]),
            "frequency_hz": float(result.frequency_hz[index]),
            "neighbor_recovery_difference_hz": float(
                result.neighbor_recovery_difference_hz[index]
            ),
        }
        for index in isolated
    ]
    return {
        "source": source.name,
        "channel": channel_name,
        "frame_count": int(result.time_s.size),
        "measured_count": measured_count,
        "nan_count": int(np.count_nonzero(np.isnan(result.frequency_hz))),
        "event_transition_frames": json.dumps(event_transition),
        "event_transition_frame_count": len(event_transition),
        "largest_frequency_steps": json.dumps(_largest_steps(analysis)),
        "isolated_jump_candidates": json.dumps(isolated),
        "isolated_jump_candidate_count": len(isolated),
        "suspicious_frames": json.dumps(suspicious),
        "current_selected_rank": "not_retained",
        "alternative_candidate_available": False,
        "alternative_candidate_frequency": None,
        "continuity_improvement": None,
        "isolated_jump_threshold_hz": result.config.isolated_jump_threshold_hz,
        "neighbor_recovery_tolerance_hz": (
            result.config.neighbor_recovery_tolerance_hz
        ),
        "stft_window_duration_s": result.stft_window_duration_s,
        "event_reference_time_s": result.event_reference_time_s,
        "event_reference_source": result.event_reference_source,
    }


def _plot_assessment(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    output_path: Path,
) -> None:
    stft = analysis.stft_result
    event_aware = analysis.event_aware_continuity_result
    detection = analysis.signal_detection_result
    band = (stft.frequency_hz >= analysis.ridge_result.minimum_frequency_hz) & (
        stft.frequency_hz <= analysis.ridge_result.maximum_frequency_hz
    )
    magnitude = np.abs(stft.spectrum[band, :])
    positive = magnitude[magnitude > 0.0]
    floor = float(np.min(positive)) if positive.size else np.finfo(np.float64).tiny
    db = 20.0 * np.log10(np.maximum(magnitude, floor))
    db -= float(np.max(db))
    isolated = np.fromiter(
        (
            status is RidgeContinuityStatus.ISOLATED_JUMP
            for status in event_aware.statuses
        ),
        dtype=np.bool_,
        count=event_aware.time_s.size,
    )

    figure, (spectrogram_axis, step_axis) = plt.subplots(
        2,
        1,
        figsize=(12.0, 8.0),
        sharex=True,
        constrained_layout=True,
        gridspec_kw={"height_ratios": (3.0, 1.0)},
    )
    mesh = spectrogram_axis.pcolormesh(
        stft.time_s * 1.0e6,
        stft.frequency_hz[band] * 1.0e-6,
        db,
        shading="auto",
        cmap="viridis",
        vmin=-60.0,
        vmax=0.0,
    )
    figure.colorbar(mesh, ax=spectrogram_axis, label="relative magnitude (dB)")
    spectrogram_axis.plot(
        analysis.refined_result.time_s * 1.0e6,
        analysis.refined_result.refined_frequency_hz * 1.0e-6,
        color="white",
        linewidth=0.8,
        label="selected refined ridge (diagnostic candidate)",
    )
    spectrogram_axis.plot(
        detection.time_s * 1.0e6,
        detection.refined_frequency_hz * 1.0e-6,
        color="cyan",
        linewidth=1.2,
        label="formal quality-gated ridge",
    )
    if np.any(isolated):
        spectrogram_axis.scatter(
            event_aware.time_s[isolated] * 1.0e6,
            event_aware.frequency_hz[isolated] * 1.0e-6,
            color="red",
            marker="x",
            s=45.0,
            label="isolated continuity anomaly",
        )
    line_specs = (
        (
            detection.detected_event_candidate_time_s,
            "compatibility spectral candidate",
            "tab:orange",
            "--",
        ),
        (
            analysis.stream_event_candidates.primary_candidate_time_s,
            "event-level primary candidate",
            "magenta",
            ":",
        ),
        (
            event_aware.event_reference_time_s,
            f"continuity reference ({event_aware.event_reference_source})",
            "black",
            "-.",
        ),
    )
    drawn: set[tuple[float, str]] = set()
    for value_s, label, color, linestyle in line_specs:
        if value_s is None:
            continue
        key = (float(value_s), label)
        if key in drawn:
            continue
        drawn.add(key)
        spectrogram_axis.axvline(
            value_s * 1.0e6,
            color=color,
            linestyle=linestyle,
            linewidth=1.1,
            label=label,
        )
        step_axis.axvline(
            value_s * 1.0e6,
            color=color,
            linestyle=linestyle,
            linewidth=1.1,
        )
    spectrogram_axis.set_ylabel("frequency (MHz)")
    spectrogram_axis.set_title(f"{source.name} — {channel_name}")
    spectrogram_axis.legend(loc="upper right", fontsize="small")

    step_axis.plot(
        event_aware.time_s * 1.0e6,
        np.abs(event_aware.delta_frequency_from_previous_hz) * 1.0e-6,
        color="tab:blue",
        linewidth=0.9,
    )
    if np.any(isolated):
        step_axis.scatter(
            event_aware.time_s[isolated] * 1.0e6,
            np.abs(event_aware.delta_frequency_from_previous_hz[isolated])
            * 1.0e-6,
            color="red",
            marker="x",
            s=45.0,
        )
    step_axis.axhline(
        event_aware.config.isolated_jump_threshold_hz * 1.0e-6,
        color="gray",
        linestyle="--",
        linewidth=0.8,
        label="isolated-jump deviation threshold",
    )
    step_axis.set_xlabel("absolute time (μs)")
    step_axis.set_ylabel("|Δf from previous| (MHz)")
    step_axis.legend(loc="upper right", fontsize="small")
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def _load_baseline_summary(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise ValueError("Baseline summary must contain a JSON list.")
    return {
        (str(item["source"]), str(item["channel"])): item
        for item in document
    }


def _array_equal(left: np.ndarray[Any, Any], right: np.ndarray[Any, Any]) -> bool:
    if left.dtype.kind in "fc" or right.dtype.kind in "fc":
        return bool(np.array_equal(left, right, equal_nan=True))
    return bool(np.array_equal(left, right))


def _regression_row(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    baseline_directory: Path,
    baseline_summary: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, object]:
    snapshot_path = baseline_directory / f"{source.stem}__{channel_name}.npz"
    baseline = np.load(snapshot_path, allow_pickle=False)
    detection = analysis.signal_detection_result
    current = {
        "time_s": analysis.stft_result.time_s,
        "formal_ridge_frequency_hz": analysis.ridge_result.frequency_hz,
        "refined_candidate_frequency_hz": analysis.refined_result.refined_frequency_hz,
        "formal_refined_frequency_hz": detection.refined_frequency_hz,
        "signal_state": np.array(
            [state.value for state in detection.signal_states],
            dtype="U32",
        ),
        "formal_apparent_velocity_m_s": analysis.refined_velocity_m_s,
        "display_velocity_m_s": analysis.display_velocity_m_s,
        "nan_mask": np.isnan(analysis.refined_velocity_m_s),
    }
    comparisons = {
        name: _array_equal(baseline[name], value) for name, value in current.items()
    }
    baseline_event = baseline_summary[(source.name, channel_name)][
        "detected_event_candidate_time_s"
    ]
    current_event = detection.detected_event_candidate_time_s
    event_equal = (
        baseline_event is None and current_event is None
    ) or (
        baseline_event is not None
        and current_event is not None
        and float(baseline_event) == current_event
    )
    comparisons["detected_event_candidate_time_s"] = event_equal
    return {
        "source": source.name,
        "channel": channel_name,
        "all_formal_results_unchanged": all(comparisons.values()),
        "comparisons": comparisons,
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows available for {path.name}.")
    with path.open("x", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("artifacts/task018a/assessment"),
    )
    parser.add_argument(
        "--baseline-directory",
        type=Path,
        default=Path("artifacts/task018a/baseline"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    output_directory = (repository_root / arguments.output_directory).resolve()
    baseline_directory = (repository_root / arguments.baseline_directory).resolve()
    raw_directory = repository_root / "data" / "raw"
    sources = sorted(raw_directory.glob("*.csv"))
    if not sources:
        raise FileNotFoundError("No raw CSV files are available for TASK-018A.")
    output_directory.mkdir(parents=True, exist_ok=False)
    plot_directory = output_directory / "figures"
    plot_directory.mkdir()
    configuration = load_workflow_config(
        repository_root / "configs" / "pdv_studio_defaults.toml",
        repository_root=repository_root,
    )
    baseline_summary = _load_baseline_summary(
        baseline_directory / "summary.json"
    )

    raw_hashes_before = {source.name: _sha256(source) for source in sources}
    event_rows: list[dict[str, object]] = []
    continuity_rows: list[dict[str, object]] = []
    regression_rows: list[dict[str, object]] = []
    for source in sources:
        analyses, range_source, start_s, end_s, manual_reference_s = _analyze_source(
            source,
            configuration,
        )
        for channel_name, analysis in analyses.items():
            event_rows.append(
                _event_row(
                    source,
                    channel_name,
                    analysis,
                    range_source=range_source,
                    analysis_start_s=start_s,
                    analysis_end_s=end_s,
                    manual_reference_s=manual_reference_s,
                )
            )
            continuity_rows.append(
                _continuity_row(source, channel_name, analysis)
            )
            regression_rows.append(
                _regression_row(
                    source,
                    channel_name,
                    analysis,
                    baseline_directory,
                    baseline_summary,
                )
            )
            _plot_assessment(
                source,
                channel_name,
                analysis,
                plot_directory / f"{source.stem}__{channel_name}.png",
            )

    raw_hashes_after = {source.name: _sha256(source) for source in sources}
    if raw_hashes_after != raw_hashes_before:
        raise RuntimeError("A data/raw SHA-256 changed during the read-only audit.")
    _write_csv(output_directory / "event_detection.csv", event_rows)
    _write_csv(output_directory / "continuity_assessment.csv", continuity_rows)
    manifest = {
        "sources": [source.name for source in sources],
        "source_count": len(sources),
        "channel_assessment_count": len(continuity_rows),
        "raw_sha256_before": raw_hashes_before,
        "raw_sha256_after": raw_hashes_after,
        "raw_unchanged": True,
        "production_regression": regression_rows,
        "all_production_results_unchanged": all(
            bool(row["all_formal_results_unchanged"])
            for row in regression_rows
        ),
        "candidate_representation": (
            "Only the selected peak and strongest competitor magnitude are retained; "
            "no alternative candidate frequency/rank is available."
        ),
    }
    (output_directory / "assessment.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
