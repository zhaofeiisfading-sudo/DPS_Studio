"""Generate TASK-018C production, window, export, and raw-integrity evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from dps_studio.core.analysis_profiles import (  # noqa: E402
    AnalysisParameterOverrides,
    build_analysis_run_parameters,
)
from dps_studio.core.export import (  # noqa: E402
    ResultAnalysisMode,
    ResultExportOptions,
    export_formal_results,
)
from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.core.models import SignalRecord  # noqa: E402
from dps_studio.core.ridge import (  # noqa: E402
    AutomaticRidgeExtractionMode,
    CandidateReselectionReason,
    RidgeContinuityStatus,
)
from dps_studio.core.workflow import (  # noqa: E402
    ChannelAnalysis,
    WorkflowConfiguration,
    analyze_stft_results,
    compute_configuration_stfts,
    load_workflow_config,
)


WINDOW_NAMES = ("hann", "hamming", "blackman", "blackmanharris", "boxcar")
WINDOW_SOURCES = ("20260607.csv", "20260701.csv", "20260630-1.csv")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"No rows are available for {path.name}.")
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _load_records(
    source: Path,
    configuration: WorkflowConfiguration,
) -> Mapping[str, SignalRecord]:
    return read_delimited_signals(
        source,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    ).records


def _context(
    records: Mapping[str, SignalRecord],
    configuration: WorkflowConfiguration,
) -> tuple[float, float, float | None, str]:
    data_start = max(record.start_time_s for record in records.values())
    data_end = min(record.end_time_s for record in records.values())
    configured_start = configuration.analysis.analysis_start_time_s
    configured_end = configuration.analysis.analysis_end_time_s
    if (
        configured_start is not None
        and configured_end is not None
        and data_start <= configured_start < configured_end <= data_end
    ):
        start_s, end_s = configured_start, configured_end
        source = "configuration"
    else:
        start_s, end_s = data_start, data_end
        source = "full_common_data_range"
    reference = configuration.analysis.event_reference_time_s
    if reference is not None and not start_s <= reference <= end_s:
        reference = None
    return start_s, end_s, reference, source


def _stfts(
    records: Mapping[str, SignalRecord],
    configuration: WorkflowConfiguration,
    window_name: str,
):
    parameters = build_analysis_run_parameters(
        base_profile=configuration.analysis.default_profile,
        base_vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        overrides=AnalysisParameterOverrides(window_name=window_name),
    )
    return parameters, compute_configuration_stfts(
        records,
        window_length_samples=parameters.window_length_samples,
        overlap_samples=parameters.overlap_samples,
        nfft=parameters.nfft,
        window_name=parameters.window_name,
    )


def _analyze(
    stft_results: Mapping[str, object],
    parameters: object,
    configuration: WorkflowConfiguration,
    *,
    start_s: float,
    end_s: float,
    reference_s: float | None,
    mode: AutomaticRidgeExtractionMode,
) -> Mapping[str, ChannelAnalysis]:
    selection = replace(configuration.automatic_ridge_selection, mode=mode)
    return analyze_stft_results(
        stft_results,  # type: ignore[arg-type]
        minimum_frequency_hz=parameters.minimum_frequency_hz,  # type: ignore[attr-defined]
        maximum_frequency_hz=parameters.maximum_frequency_hz,  # type: ignore[attr-defined]
        analysis_start_time_s=start_s,
        analysis_end_time_s=end_s,
        manual_event_reference_time_s=reference_s,
        vacuum_wavelength_m=parameters.vacuum_wavelength_m,  # type: ignore[attr-defined]
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        profile_name=parameters.provenance_name,  # type: ignore[attr-defined]
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
        automatic_ridge_selection_config=selection,
    )


def _same_optional(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    return float(left) == float(right)


def _array_equal(left: np.ndarray, right: np.ndarray) -> bool:
    if np.issubdtype(left.dtype, np.inexact) and np.issubdtype(
        right.dtype,
        np.inexact,
    ):
        return bool(np.array_equal(left, right, equal_nan=True))
    return bool(np.array_equal(left, right))


def _legacy_baseline_row(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    baseline_directory: Path,
    summary_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, object]:
    snapshot_path = baseline_directory / f"{source.stem}__{channel_name}.npz"
    with np.load(snapshot_path, allow_pickle=False) as baseline:
        current = {
            "time_s": analysis.stft_result.time_s,
            "formal_ridge_frequency_hz": analysis.ridge_result.frequency_hz,
            "refined_candidate_frequency_hz": (
                analysis.refined_result.refined_frequency_hz
            ),
            "formal_refined_frequency_hz": (
                analysis.signal_detection_result.refined_frequency_hz
            ),
            "signal_state": np.asarray(
                [state.value for state in analysis.signal_detection_result.signal_states],
                dtype="U32",
            ),
            "formal_apparent_velocity_m_s": analysis.refined_velocity_m_s,
            "display_velocity_m_s": analysis.display_velocity_m_s,
            "nan_mask": np.isnan(analysis.refined_velocity_m_s),
        }
        comparisons = {
            name: _array_equal(baseline[name], value)
            for name, value in current.items()
        }
    summary = summary_by_key[(source.name, channel_name)]
    comparisons["automatic_event_candidate_time_s"] = _same_optional(
        summary["stream_primary_candidate_time_s"],
        analysis.stream_event_candidates.primary_candidate_time_s,
    )
    comparisons["compatibility_event_candidate_time_s"] = _same_optional(
        summary["detected_event_candidate_time_s"],
        analysis.signal_detection_result.detected_event_candidate_time_s,
    )
    return {
        "source": source.name,
        "channel": channel_name,
        **comparisons,
        "all_required_fields_equal": all(comparisons.values()),
    }


def _changed_rows(
    source: Path,
    channel_name: str,
    legacy: ChannelAnalysis,
    continuity: ChannelAnalysis,
) -> list[dict[str, object]]:
    legacy_detection = legacy.signal_detection_result
    continuity_detection = continuity.signal_detection_result
    frequency_changed = ~np.isclose(
        legacy.refined_result.refined_frequency_hz,
        continuity.refined_result.refined_frequency_hz,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    state_changed = np.fromiter(
        (
            left is not right
            for left, right in zip(
                legacy_detection.signal_states,
                continuity_detection.signal_states,
                strict=True,
            )
        ),
        dtype=np.bool_,
        count=legacy_detection.time_s.size,
    )
    velocity_changed = ~np.isclose(
        legacy.refined_velocity_m_s,
        continuity.refined_velocity_m_s,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    rows: list[dict[str, object]] = []
    for frame in np.flatnonzero(frequency_changed | state_changed | velocity_changed):
        index = int(frame)
        evidence = ()
        if continuity.experimental_reselection_result is not None:
            evidence = continuity.experimental_reselection_result.evidence_by_frame[
                index
            ]
        selected = next((item for item in evidence if item.experimental_selected), None)
        rows.append(
            {
                "source": source.name,
                "channel": channel_name,
                "frame": index,
                "time_s": float(continuity.stft_result.time_s[index]),
                "legacy_frequency_hz": _json_number(
                    legacy.refined_result.refined_frequency_hz[index]
                ),
                "continuity_frequency_hz": _json_number(
                    continuity.refined_result.refined_frequency_hz[index]
                ),
                "legacy_state": legacy_detection.signal_states[index].value,
                "continuity_state": continuity_detection.signal_states[index].value,
                "legacy_velocity_m_s": _json_number(
                    legacy.refined_velocity_m_s[index]
                ),
                "continuity_velocity_m_s": _json_number(
                    continuity.refined_velocity_m_s[index]
                ),
                "candidate_rank": int(
                    continuity.automatic_ridge_selection_result.selected_candidate_rank[
                        index
                    ]
                ),
                "reselection_reason": (
                    selected.reselection_reason.value
                    if selected is not None
                    else CandidateReselectionReason.LEGACY_SELECTED.value
                ),
            }
        )
    return rows


def _json_number(value: object) -> float | None:
    converted = float(value)  # type: ignore[arg-type]
    return converted if math.isfinite(converted) else None


def _window_metric(
    source: Path,
    channel_name: str,
    window_name: str,
    analysis: ChannelAnalysis,
    hann: ChannelAnalysis,
) -> dict[str, object]:
    detection = analysis.signal_detection_result
    selected = analysis.refined_result.refined_frequency_hz
    hann_selected = hann.refined_result.refined_frequency_hz
    difference = ~np.isclose(
        selected,
        hann_selected,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    both_finite = np.isfinite(selected) & np.isfinite(hann_selected)
    finite_difference = np.abs(selected[both_finite] - hann_selected[both_finite])
    state_counts = Counter(state.value for state in detection.signal_states)
    return {
        "source": source.name,
        "channel": channel_name,
        "window_name": window_name,
        "event_candidate_time_s": (
            analysis.stream_event_candidates.primary_candidate_time_s
        ),
        "compatibility_event_candidate_time_s": (
            detection.detected_event_candidate_time_s
        ),
        "measured_count": state_counts["measured"],
        "nan_count": int(np.count_nonzero(np.isnan(detection.refined_frequency_hz))),
        "continuity_reselection_count": len(
            analysis.automatic_ridge_selection_result.reselected_frame_indices
        ),
        "formal_velocity_finite_count": int(
            np.count_nonzero(np.isfinite(detection.apparent_velocity_m_s))
        ),
        "ambiguous_peak_count": state_counts["ambiguous_peak"],
        "boundary_count": state_counts["peak_at_band_boundary"],
        "selected_ridge_difference_vs_hann_count": int(
            np.count_nonzero(difference)
        ),
        "selected_ridge_finite_pair_max_abs_difference_hz": (
            float(np.max(finite_difference)) if finite_difference.size else 0.0
        ),
        "formal_isolated_jump_count": sum(
            status is RidgeContinuityStatus.ISOLATED_JUMP
            for status in analysis.event_aware_continuity_result.statuses
        ),
    }


def _plot_ridge_overlay(
    path: Path,
    analyses: Mapping[str, ChannelAnalysis],
) -> None:
    figure, axis = plt.subplots(figsize=(9.2, 4.8), constrained_layout=True)
    for window_name in WINDOW_NAMES:
        analysis = analyses[window_name]
        time_us = (
            analysis.stft_result.time_s - analysis.stft_result.time_s[0]
        ) * 1.0e6
        axis.plot(
            time_us,
            analysis.signal_detection_result.refined_frequency_hz * 1.0e-6,
            linewidth=0.8,
            label=window_name,
        )
    axis.set_xlabel("Time from first STFT frame (µs)")
    axis.set_ylabel("Formal refined frequency (MHz)")
    axis.set_title("20260630-1 / pdv_channel_2 window comparison")
    axis.grid(alpha=0.25)
    axis.legend(ncol=3, fontsize="small")
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _plot_quality_counts(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    aggregated: dict[str, Counter[str]] = {
        name: Counter() for name in WINDOW_NAMES
    }
    for row in rows:
        counts = aggregated[str(row["window_name"])]
        for field in (
            "measured_count",
            "ambiguous_peak_count",
            "boundary_count",
            "continuity_reselection_count",
        ):
            counts[field] += int(row[field])
    fields = tuple(next(iter(aggregated.values())).keys())
    x = np.arange(len(WINDOW_NAMES), dtype=np.float64)
    width = 0.2
    figure, axis = plt.subplots(figsize=(9.2, 4.8), constrained_layout=True)
    for offset, field in enumerate(fields):
        axis.bar(
            x + (offset - 1.5) * width,
            [aggregated[name][field] for name in WINDOW_NAMES],
            width=width,
            label=field,
        )
    axis.set_xticks(x, WINDOW_NAMES, rotation=15)
    axis.set_ylabel("Count across 3 shots × 2 channels")
    axis.set_title("Window-dependent formal quality counts")
    axis.legend(fontsize="x-small")
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _formal_export(
    output_directory: Path,
    source: Path,
    analysis: ChannelAnalysis,
) -> dict[str, object]:
    output_directory.mkdir()
    report = export_formal_results(
        ResultExportOptions(
            output_directory=output_directory,
            analysis_mode=ResultAnalysisMode.AUTOMATIC,
            channel_analyses={"pdv_channel_2": analysis},
            source_path=source,
            analysis_profile_name="balanced",
            pre_event_display_enabled=False,
            pre_event_display_velocity_m_s=0.0,
            event_reference_source=None,
            protected_output_directories=(source.parent,),
        )
    )
    exported = report.exported_channels[0]
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    files = sorted(path.name for path in output_directory.iterdir() if path.is_file())
    return {
        "files": files,
        "metadata_json_count": len(list(output_directory.glob("*.metadata.json"))),
        "schema": metadata["export_schema_version"],
        "window_name": metadata["stft_configuration"]["window_name"],
        "automatic_ridge_selection": metadata["automatic_ridge_selection"],
        "automatic_event_candidate_time_s": metadata[
            "automatic_event_candidate_time_s"
        ],
        "compatibility_event_candidate_time_s": metadata[
            "compatibility_event_candidate_time_s"
        ],
        "event_reference_time_s": metadata["event_reference_time_s"],
        "event_reference_source": metadata["event_reference_source"],
        "frame_1015_detail": next(
            row
            for row in csv.DictReader(
                exported.detail_csv_path.open(encoding="utf-8")
            )
            if int(float(row["time_s"]) == float(analysis.stft_result.time_s[1015]))
        ),
    }


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    output_directory = repository_root / "artifacts" / "task018c" / "assessment"
    output_directory.mkdir(parents=True, exist_ok=True)
    window_directory = output_directory / "window_comparison"
    window_directory.mkdir(exist_ok=True)
    if any(path.is_file() for path in output_directory.rglob("*")):
        raise RuntimeError(
            "TASK-018C assessment output already contains files; refusing to overwrite."
        )
    raw_directory = repository_root / "data" / "raw"
    raw_files = sorted(path for path in raw_directory.iterdir() if path.is_file())
    hashes_before = {path.name: _sha256(path) for path in raw_files}
    configuration = load_workflow_config(
        repository_root / "configs" / "pdv_studio_defaults.toml",
        repository_root=repository_root,
    )
    baseline_directory = repository_root / "artifacts" / "task018c" / "baseline"
    baseline_summary = json.loads(
        (baseline_directory / "summary.json").read_text(encoding="utf-8")
    )
    summary_by_key = {
        (item["source"], item["channel"]): item for item in baseline_summary
    }
    baseline_rows: list[dict[str, object]] = []
    changed_rows: list[dict[str, object]] = []
    production_results: dict[
        tuple[str, str], tuple[ChannelAnalysis, ChannelAnalysis]
    ] = {}
    window_results: dict[tuple[str, str], ChannelAnalysis] = {}

    sources = sorted(raw_directory.glob("*.csv"))
    for source in sources:
        records = _load_records(source, configuration)
        start_s, end_s, reference_s, _ = _context(records, configuration)
        parameters, stft_results = _stfts(records, configuration, "hann")
        legacy = _analyze(
            stft_results,
            parameters,
            configuration,
            start_s=start_s,
            end_s=end_s,
            reference_s=reference_s,
            mode=AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK,
        )
        continuity = _analyze(
            stft_results,
            parameters,
            configuration,
            start_s=start_s,
            end_s=end_s,
            reference_s=reference_s,
            mode=AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED,
        )
        for channel_name in legacy:
            baseline_rows.append(
                _legacy_baseline_row(
                    source,
                    channel_name,
                    legacy[channel_name],
                    baseline_directory,
                    summary_by_key,
                )
            )
            changed_rows.extend(
                _changed_rows(
                    source,
                    channel_name,
                    legacy[channel_name],
                    continuity[channel_name],
                )
            )
            production_results[(source.name, channel_name)] = (
                legacy[channel_name],
                continuity[channel_name],
            )
            if source.name in WINDOW_SOURCES:
                window_results[(source.name, channel_name, "hann")] = continuity[
                    channel_name
                ]

    window_rows: list[dict[str, object]] = []
    focus_windows: dict[str, ChannelAnalysis] = {}
    for source_name in WINDOW_SOURCES:
        source = raw_directory / source_name
        records = _load_records(source, configuration)
        start_s, end_s, reference_s, _ = _context(records, configuration)
        for window_name in WINDOW_NAMES:
            if window_name == "hann":
                analyses = {
                    channel_name: window_results[(source_name, channel_name, "hann")]
                    for channel_name in records
                }
            else:
                parameters, stft_results = _stfts(
                    records,
                    configuration,
                    window_name,
                )
                analyses = _analyze(
                    stft_results,
                    parameters,
                    configuration,
                    start_s=start_s,
                    end_s=end_s,
                    reference_s=reference_s,
                    mode=AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED,
                )
            for channel_name, analysis in analyses.items():
                hann = window_results[(source_name, channel_name, "hann")]
                window_rows.append(
                    _window_metric(
                        source,
                        channel_name,
                        window_name,
                        analysis,
                        hann,
                    )
                )
                if source_name == "20260630-1.csv" and channel_name == "pdv_channel_2":
                    focus_windows[window_name] = analysis

    _write_csv(output_directory / "legacy_baseline_verification.csv", baseline_rows)
    _write_csv(output_directory / "production_changed_frames.csv", changed_rows)
    _write_csv(output_directory / "window_comparison.csv", window_rows)
    _plot_ridge_overlay(
        window_directory / "20260630-1__pdv_channel_2__ridge_overlay.png",
        focus_windows,
    )
    _plot_quality_counts(
        window_directory / "quality_count_comparison.png",
        window_rows,
    )
    focus_analysis = production_results[("20260630-1.csv", "pdv_channel_2")][1]
    formal_export = _formal_export(
        output_directory / "formal_export",
        raw_directory / "20260630-1.csv",
        focus_analysis,
    )
    hashes_after = {path.name: _sha256(path) for path in raw_files}
    if hashes_before != hashes_after:
        raise RuntimeError("A data/raw SHA-256 changed during TASK-018C assessment.")
    manifest = {
        "production_default_mode": configuration.automatic_ridge_selection.mode.value,
        "production_thresholds": {
            "top_k_candidates": configuration.automatic_ridge_selection.top_k_candidates,
            "minimum_candidate_peak_to_background_db": (
                configuration.automatic_ridge_selection.minimum_candidate_peak_to_background_db
            ),
            "minimum_candidate_relative_to_strongest_db": (
                configuration.automatic_ridge_selection.minimum_candidate_relative_to_strongest_db
            ),
            "recovery_tolerance_source": (
                "sample_rate_hz_divided_by_window_length_samples"
            ),
        },
        "legacy_baseline_all_equal": all(
            bool(row["all_required_fields_equal"]) for row in baseline_rows
        ),
        "production_changed_frame_count": len(changed_rows),
        "production_changed_frames": changed_rows,
        "window_evaluation_source_count": len(WINDOW_SOURCES),
        "window_evaluation_channel_run_count": len(window_rows),
        "formal_export": formal_export,
        "raw_sha256_before": hashes_before,
        "raw_sha256_after": hashes_after,
        "raw_unchanged": True,
    }
    (output_directory / "assessment.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
