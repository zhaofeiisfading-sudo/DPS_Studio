"""Run the isolated TASK-020A background-whitening research assessment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from numpy.typing import NDArray

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from dps_studio.core.export import (  # noqa: E402
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultExportOptions,
    export_formal_results,
)
from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.core.models import SignalRecord  # noqa: E402
from dps_studio.core.time_frequency import STFTResult  # noqa: E402
from dps_studio.core.workflow import (  # noqa: E402
    ChannelAnalysis,
    WorkflowConfiguration,
    analyze_stft_results,
    compute_profile_stfts,
    load_workflow_config,
)

from task020a_background_whitening import (  # noqa: E402
    SpectralWhiteningResult,
    assess_background_uniformity,
    compute_frequency_background_whitening,
    frame_median_contrast_db,
)


FloatArray = NDArray[np.float64]
EXPERIMENTAL_LABEL = "EXPERIMENTAL — Background-normalized — Not production result"


@dataclass(frozen=True, slots=True)
class SourceSpec:
    path: Path
    voltage_columns: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CaseSpec:
    case_id: str
    classification: str
    background_start_s: float
    background_end_s: float
    background_mode: str
    selection_note: str
    sources: tuple[SourceSpec, ...]


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    analysis_start_s: float
    analysis_end_s: float
    manual_event_reference_s: float | None
    analysis_range_source: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _raw_hashes(repository_root: Path) -> dict[str, str]:
    return {
        path.name: _sha256(path)
        for path in sorted((repository_root / "data" / "raw").iterdir())
        if path.is_file()
    }


def _load_cases(path: Path, repository_root: Path) -> tuple[CaseSpec, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "task020a-explicit-cases-v1":
        raise ValueError("Unsupported TASK-020A case schema.")
    cases: list[CaseSpec] = []
    for raw_case in document["cases"]:
        if raw_case["background_mode"] != "explicit":
            raise ValueError("TASK-020A assessment accepts only explicit backgrounds.")
        sources = tuple(
            SourceSpec(
                path=(repository_root / item["path"]).resolve(),
                voltage_columns={
                    str(name): int(column)
                    for name, column in item["voltage_columns"].items()
                },
            )
            for item in raw_case["sources"]
        )
        cases.append(
            CaseSpec(
                case_id=str(raw_case["case_id"]),
                classification=str(raw_case["classification"]),
                background_start_s=float(raw_case["background_start_s"]),
                background_end_s=float(raw_case["background_end_s"]),
                background_mode="explicit",
                selection_note=str(raw_case["selection_note"]),
                sources=sources,
            )
        )
    if not cases:
        raise ValueError("The case configuration contains no cases.")
    return tuple(cases)


def _single_case(arguments: argparse.Namespace, repository_root: Path) -> CaseSpec:
    if arguments.background_start is None or arguments.background_end is None:
        raise ValueError(
            "--source requires both --background-start and --background-end in seconds."
        )
    source = (repository_root / arguments.source).resolve()
    if arguments.voltage_column:
        columns: dict[str, int] = {}
        for item in arguments.voltage_column:
            name, separator, raw_index = item.partition("=")
            if not separator or not name:
                raise ValueError("--voltage-column must use NAME=INDEX syntax.")
            columns[name] = int(raw_index)
    else:
        first_line = source.open(encoding="utf-8").readline()
        field_count = len(first_line.rstrip("\r\n").split(","))
        columns = {
            f"pdv_channel_{index}": index for index in range(1, field_count)
        }
    return CaseSpec(
        case_id="explicit_case",
        classification="User Explicit Case",
        background_start_s=float(arguments.background_start),
        background_end_s=float(arguments.background_end),
        background_mode="explicit",
        selection_note="CLI explicit background interval; no event-time inference.",
        sources=(SourceSpec(path=source, voltage_columns=columns),),
    )


def _read_records(
    source: SourceSpec,
    configuration: WorkflowConfiguration,
) -> Mapping[str, SignalRecord]:
    return read_delimited_signals(
        source.path,
        time_column=0,
        voltage_columns=source.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=False,
        encoding=configuration.input.encoding,
        time_scale=1.0,
        voltage_scales={name: 1.0 for name in source.voltage_columns},
    ).records


def _analysis_context(
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
        start, end, source = configured_start, configured_end, "configuration"
    else:
        start, end, source = data_start, data_end, "full_common_data_range"
    reference = configuration.analysis.event_reference_time_s
    if reference is not None and not start <= reference <= end:
        reference = None
    return start, end, reference, source


def _analyze_production(
    records: Mapping[str, SignalRecord],
    configuration: WorkflowConfiguration,
) -> tuple[
    Mapping[str, STFTResult],
    Mapping[str, ChannelAnalysis],
    AnalysisContext,
]:
    profile = configuration.analysis.default_profile
    start, end, reference, context_source = _analysis_context(records, configuration)
    stfts = compute_profile_stfts(records, profile=profile)
    analyses = _analyze_stfts(
        stfts,
        configuration,
        analysis_start_s=start,
        analysis_end_s=end,
        manual_reference_s=reference,
    )
    return stfts, analyses, AnalysisContext(
        analysis_start_s=start,
        analysis_end_s=end,
        manual_event_reference_s=reference,
        analysis_range_source=context_source,
    )


def _analyze_stfts(
    stfts: Mapping[str, STFTResult],
    configuration: WorkflowConfiguration,
    *,
    analysis_start_s: float,
    analysis_end_s: float,
    manual_reference_s: float | None,
) -> Mapping[str, ChannelAnalysis]:
    profile = configuration.analysis.default_profile
    return analyze_stft_results(
        stfts,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
        analysis_start_time_s=analysis_start_s,
        analysis_end_time_s=analysis_end_s,
        manual_event_reference_time_s=manual_reference_s,
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        profile_name=profile.profile_id.value,
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
        automatic_ridge_selection_config=(
            configuration.automatic_ridge_selection
        ),
        velocity_correction_config=configuration.velocity_correction,
    )


def _snapshot_name(case: CaseSpec, source: Path, channel: str) -> str:
    return f"{case.case_id}__{source.stem}__{channel}"


def _event_value(analysis: ChannelAnalysis) -> float:
    value = analysis.stream_event_candidates.primary_candidate_time_s
    return math.nan if value is None else value


def _save_snapshot(path: Path, analysis: ChannelAnalysis) -> None:
    detection = analysis.signal_detection_result
    np.savez_compressed(
        path,
        stft_time_s=analysis.stft_result.time_s,
        stft_frequency_hz=analysis.stft_result.frequency_hz,
        stft_spectrum=analysis.stft_result.spectrum,
        formal_ridge_frequency_hz=analysis.ridge_result.frequency_hz,
        formal_refined_frequency_hz=analysis.refined_result.refined_frequency_hz,
        quality_state=np.asarray([state.value for state in detection.signal_states]),
        apparent_velocity_m_s=analysis.apparent_velocity_m_s,
        corrected_velocity_m_s=analysis.corrected_velocity_m_s,
        event_time_s=np.asarray([_event_value(analysis)]),
    )


def _export_production(
    directory: Path,
    source: Path,
    analyses: Mapping[str, ChannelAnalysis],
    configuration: WorkflowConfiguration,
) -> dict[str, dict[str, object]]:
    directory.mkdir(parents=True, exist_ok=False)
    report = export_formal_results(
        ResultExportOptions(
            output_directory=directory,
            analysis_mode=ResultAnalysisMode.AUTOMATIC,
            channel_analyses=analyses,
            time_origin=ExportTimeOrigin.ABSOLUTE,
            source_path=source,
            analysis_profile_name=(
                configuration.analysis.default_profile.profile_id.value
            ),
            pre_event_display_enabled=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
            pre_event_display_velocity_m_s=(
                configuration.plot.pre_event_display_velocity_m_s
            ),
            event_reference_source=None,
            protected_output_directories=(source.parent,),
        )
    )
    signatures: dict[str, dict[str, object]] = {}
    for item in report.exported_channels:
        metadata = json.loads(item.metadata_path.read_text(encoding="utf-8"))
        metadata.pop("exported_at_utc", None)
        signatures[item.channel_name] = {
            "simple_csv_sha256": _sha256(item.csv_path),
            "detail_csv_sha256": _sha256(item.detail_csv_path),
            "metadata_without_timestamp": metadata,
        }
    return signatures


def _capture_baseline(
    output_root: Path,
    cases: Sequence[CaseSpec],
    configuration: WorkflowConfiguration,
    repository_root: Path,
) -> None:
    baseline = output_root / "baseline"
    baseline.mkdir(parents=True, exist_ok=False)
    snapshots = baseline / "snapshots"
    snapshots.mkdir()
    exports = baseline / "formal_exports"
    exports.mkdir()
    raw_before = _raw_hashes(repository_root)
    summary: list[dict[str, object]] = []
    for case in cases:
        for source_spec in case.sources:
            records = _read_records(source_spec, configuration)
            _stfts, analyses, context = _analyze_production(records, configuration)
            signatures = _export_production(
                exports / f"{case.case_id}__{source_spec.path.stem}",
                source_spec.path,
                analyses,
                configuration,
            )
            for channel, analysis in analyses.items():
                name = _snapshot_name(case, source_spec.path, channel)
                _save_snapshot(snapshots / f"{name}.npz", analysis)
                summary.append(
                    {
                        "snapshot": name,
                        "case_id": case.case_id,
                        "source": source_spec.path.name,
                        "channel": channel,
                        "context": {
                            "analysis_start_s": context.analysis_start_s,
                            "analysis_end_s": context.analysis_end_s,
                            "manual_event_reference_s": (
                                context.manual_event_reference_s
                            ),
                            "analysis_range_source": context.analysis_range_source,
                        },
                        "formal_export_signature": signatures[channel],
                    }
                )
    raw_after = _raw_hashes(repository_root)
    if raw_before != raw_after:
        raise RuntimeError("data/raw changed during baseline capture.")
    document = {
        "schema": "task020a-production-baseline-v1",
        "head": _git_output(repository_root, "rev-parse", "HEAD"),
        "raw_sha256_before": raw_before,
        "raw_sha256_after": raw_after,
        "raw_unchanged": True,
        "snapshots": summary,
    }
    _write_json_exclusive(baseline / "summary.json", document)
    print(json.dumps(document, indent=2, ensure_ascii=False))


def _git_output(repository_root: Path, *arguments: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _whitened_stft(
    stft: STFTResult,
    whitening: SpectralWhiteningResult,
) -> STFTResult:
    return STFTResult(
        time_s=stft.time_s,
        frequency_hz=stft.frequency_hz,
        spectrum=np.sqrt(whitening.whitened_ratio).astype(np.complex128),
        window_name=stft.window_name,
        window_length_samples=stft.window_length_samples,
        overlap_samples=stft.overlap_samples,
        hop_samples=stft.hop_samples,
        nfft=stft.nfft,
        sample_rate_hz=stft.sample_rate_hz,
        source_path=stft.source_path,
        scaling=stft.scaling,
        is_one_sided=stft.is_one_sided,
        detrend_applied=stft.detrend_applied,
        boundary_padding_applied=stft.boundary_padding_applied,
    )


def _measured_mask(analysis: ChannelAnalysis) -> NDArray[np.bool_]:
    return np.fromiter(
        (state.value == "measured" for state in analysis.signal_detection_result.signal_states),
        dtype=np.bool_,
        count=analysis.stft_result.time_s.size,
    )


def _finite_summary(values: FloatArray) -> dict[str, float | int | None]:
    finite = values[np.isfinite(values)]
    if not finite.size:
        return {"count": 0, "median": None, "p95_absolute": None, "maximum_absolute": None}
    return {
        "count": int(finite.size),
        "median": float(np.median(finite)),
        "p95_absolute": float(np.percentile(np.abs(finite), 95.0)),
        "maximum_absolute": float(np.max(np.abs(finite))),
    }


def _nearest_values(
    grid: FloatArray,
    values: FloatArray,
    ridge_hz: FloatArray,
) -> FloatArray:
    output = np.full(ridge_hz.shape, np.nan)
    for raw_index in np.flatnonzero(np.isfinite(ridge_hz)):
        index = int(raw_index)
        bin_index = int(np.argmin(np.abs(grid - ridge_hz[index])))
        output[index] = values[bin_index, index]
    return output


def _analysis_band_uniformity(
    whitening: SpectralWhiteningResult,
    minimum_hz: float,
    maximum_hz: float,
) -> dict[str, float | str]:
    band = (whitening.frequency_hz >= minimum_hz) & (
        whitening.frequency_hz <= maximum_hz
    )
    raw = np.median(
        whitening.raw_spectral_quantity[np.ix_(band, whitening.background_frame_mask)],
        axis=1,
    )
    white = np.median(
        whitening.whitened_ratio[np.ix_(band, whitening.background_frame_mask)],
        axis=1,
    )
    raw_spread = float(np.diff(np.percentile(10.0 * np.log10(raw), (5, 95)))[0])
    white_spread = float(
        np.diff(np.percentile(10.0 * np.log10(white), (5, 95)))[0]
    )
    return {
        "raw_nonuniformity_db": raw_spread,
        "whitened_nonuniformity_db": white_spread,
        "reduction_db": raw_spread - white_spread,
        "definition": "analysis-band P95-P5 spread across frequency of background time medians in dB",
    }


def _channel_metrics(
    case: CaseSpec,
    source: Path,
    channel: str,
    baseline: ChannelAnalysis,
    experimental: ChannelAnalysis,
    whitening: SpectralWhiteningResult,
    configuration: WorkflowConfiguration,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    profile = configuration.analysis.default_profile
    uniformity = assess_background_uniformity(whitening)
    baseline_mask = _measured_mask(baseline)
    experimental_mask = _measured_mask(experimental)
    baseline_frequency = baseline.refined_result.refined_frequency_hz
    experimental_frequency = experimental.refined_result.refined_frequency_hz
    mutual = np.isfinite(baseline_frequency) & np.isfinite(experimental_frequency)
    delta_frequency = np.full(baseline_frequency.shape, np.nan)
    delta_frequency[mutual] = experimental_frequency[mutual] - baseline_frequency[mutual]
    mutually_gate_passing = mutual & baseline_mask & experimental_mask
    delta_frequency_gate_passing = np.full(baseline_frequency.shape, np.nan)
    delta_frequency_gate_passing[mutually_gate_passing] = delta_frequency[
        mutually_gate_passing
    ]
    delta_velocity = (
        configuration.analysis.vacuum_wavelength_m * 0.5 * delta_frequency
    )
    delta_velocity_gate_passing = (
        configuration.analysis.vacuum_wavelength_m
        * 0.5
        * delta_frequency_gate_passing
    )
    changed = mutual & ~np.isclose(
        baseline_frequency,
        experimental_frequency,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    discrete_changed = ~np.isclose(
        baseline.ridge_result.frequency_hz,
        experimental.ridge_result.frequency_hz,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    raw_contrast = frame_median_contrast_db(
        whitening.raw_spectral_quantity + whitening.epsilon,
        frequency_hz=whitening.frequency_hz,
        ridge_frequency_hz=baseline_frequency,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
    )
    ratio_epsilon = np.finfo(np.float64).eps * max(
        1.0, float(np.max(whitening.whitened_ratio))
    )
    white_contrast = frame_median_contrast_db(
        whitening.whitened_ratio + ratio_epsilon,
        frequency_hz=whitening.frequency_hz,
        ridge_frequency_hz=baseline_frequency,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
    )
    ridge_background_contrast = _nearest_values(
        whitening.frequency_hz,
        whitening.background_contrast_db,
        baseline_frequency,
    )
    event_time = baseline.stream_event_candidates.primary_candidate_time_s
    experimental_event_time = (
        experimental.stream_event_candidates.primary_candidate_time_s
    )
    if event_time is None:
        baseline_pre_event = None
        experimental_pre_event = None
    else:
        pre_event = baseline.stft_result.time_s < event_time
        baseline_pre_event = int(np.count_nonzero(baseline_mask & pre_event))
        experimental_pre_event = int(np.count_nonzero(experimental_mask & pre_event))
    dc_contrast = whitening.background_contrast_db[0]
    low_frequency = whitening.frequency_hz < profile.minimum_frequency_hz
    metrics: dict[str, object] = {
        "case_id": case.case_id,
        "classification": case.classification,
        "source": source.name,
        "channel": channel,
        "background_mode": case.background_mode,
        "background_start_s": case.background_start_s,
        "background_end_s": case.background_end_s,
        "background_frame_count": int(np.count_nonzero(whitening.background_frame_mask)),
        "frequency_bin_spacing_hz": float(
            whitening.frequency_hz[1] - whitening.frequency_hz[0]
        ),
        "epsilon": whitening.epsilon,
        "epsilon_definition": "max(float64.eps * max(N), float64.smallest_subnormal)",
        "full_band_background_uniformity": {
            "raw_nonuniformity_db": uniformity.raw_nonuniformity_db,
            "whitened_nonuniformity_db": uniformity.whitened_nonuniformity_db,
            "reduction_db": uniformity.reduction_db,
            "definition": uniformity.definition,
        },
        "production_search_band_background_uniformity": _analysis_band_uniformity(
            whitening,
            profile.minimum_frequency_hz,
            profile.maximum_frequency_hz,
        ),
        "baseline_measured_frames": int(np.count_nonzero(baseline_mask)),
        "experimental_gate_passing_frames_not_production": int(
            np.count_nonzero(experimental_mask)
        ),
        "newly_recovered_frames_not_production": int(
            np.count_nonzero(experimental_mask & ~baseline_mask)
        ),
        "lost_frames_not_production": int(
            np.count_nonzero(baseline_mask & ~experimental_mask)
        ),
        "changed_mutually_finite_ridge_frames": int(np.count_nonzero(changed)),
        "changed_discrete_ridge_bin_frames": int(np.count_nonzero(discrete_changed)),
        "changed_discrete_ridge_bin_mutually_gate_passing_frames": int(
            np.count_nonzero(discrete_changed & mutually_gate_passing)
        ),
        "delta_frequency_hz": _finite_summary(delta_frequency),
        "delta_frequency_hz_mutually_gate_passing": _finite_summary(
            delta_frequency_gate_passing
        ),
        "delta_apparent_velocity_m_s": _finite_summary(delta_velocity),
        "delta_apparent_velocity_m_s_mutually_gate_passing": _finite_summary(
            delta_velocity_gate_passing
        ),
        "raw_frame_median_spectral_contrast_db": _finite_summary(raw_contrast),
        "whitened_frame_median_spectral_contrast_db": _finite_summary(white_contrast),
        "baseline_ridge_background_contrast_db": _finite_summary(
            ridge_background_contrast
        ),
        "event_time_s": event_time,
        "event_time_source": (
            None if event_time is None else "production event-level primary candidate"
        ),
        "experimental_event_time_s_not_production": experimental_event_time,
        "experimental_minus_production_event_time_s": (
            None
            if event_time is None or experimental_event_time is None
            else experimental_event_time - event_time
        ),
        "baseline_pre_event_gate_passing_frames": baseline_pre_event,
        "experimental_pre_event_gate_passing_frames_not_production": (
            experimental_pre_event
        ),
        "dc_contrast_db": _finite_summary(dc_contrast),
        "below_production_search_minimum": {
            "frequency_bin_count": int(np.count_nonzero(low_frequency)),
            "maximum_absolute_contrast_db": (
                float(np.max(np.abs(whitening.background_contrast_db[low_frequency])))
                if np.any(low_frequency)
                else None
            ),
        },
    }
    rows: list[dict[str, object]] = [
        {
            "case_id": case.case_id,
            "source": source.name,
            "channel": channel,
            "frame_index": index,
            "time_s": float(baseline.stft_result.time_s[index]),
            "baseline_refined_frequency_hz": _json_number(baseline_frequency[index]),
            "experimental_refined_frequency_hz_not_production": _json_number(
                experimental_frequency[index]
            ),
            "delta_frequency_hz": _json_number(delta_frequency[index]),
            "delta_apparent_velocity_m_s": _json_number(delta_velocity[index]),
            "mutually_gate_passing": bool(mutually_gate_passing[index]),
            "baseline_measured": bool(baseline_mask[index]),
            "experimental_gate_passed_not_production": bool(experimental_mask[index]),
            "raw_frame_median_spectral_contrast_db": _json_number(raw_contrast[index]),
            "whitened_frame_median_spectral_contrast_db": _json_number(
                white_contrast[index]
            ),
            "baseline_ridge_background_contrast_db": _json_number(
                ridge_background_contrast[index]
            ),
        }
        for index in range(baseline.stft_result.time_s.size)
    ]
    return metrics, rows


def _plot_channel(
    output: Path,
    case: CaseSpec,
    source: Path,
    channel: str,
    baseline: ChannelAnalysis,
    experimental: ChannelAnalysis,
    whitening: SpectralWhiteningResult,
    configuration: WorkflowConfiguration,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    profile = configuration.analysis.default_profile
    band = (whitening.frequency_hz >= profile.minimum_frequency_hz) & (
        whitening.frequency_hz <= profile.maximum_frequency_hz
    )
    time_us = whitening.time_s * 1.0e6
    frequency_ghz = whitening.frequency_hz[band] * 1.0e-9
    power = whitening.raw_spectral_quantity[band]
    raw_db = 10.0 * np.log10(power + whitening.epsilon)
    raw_db -= float(np.max(raw_db))
    contrast = whitening.background_contrast_db[band]
    title = f"{EXPERIMENTAL_LABEL}\n{case.classification}: {source.name} — {channel}"

    figure, axis = plt.subplots(figsize=(12.5, 6.2), constrained_layout=True)
    mesh = axis.pcolormesh(time_us, frequency_ghz, raw_db, shading="auto", cmap="viridis", vmin=-60, vmax=0)
    axis.plot(time_us, baseline.refined_result.refined_frequency_hz * 1.0e-9, color="white", linewidth=0.8, label="production baseline ridge (reference only)")
    axis.set(title=f"Raw STFT power\n{title}", xlabel="absolute time (µs)", ylabel="frequency (GHz)")
    axis.legend(fontsize="x-small")
    _experimental_watermark(axis)
    figure.colorbar(mesh, ax=axis, label="raw relative STFT power (dB)")
    figure.savefig(output / "raw_stft.png", dpi=170)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(10.0, 5.8), constrained_layout=True)
    plot_band = whitening.frequency_hz <= profile.maximum_frequency_hz
    frequencies = whitening.frequency_hz[plot_band] * 1.0e-9
    background = whitening.background_frequency_profile[plot_band]
    robust_sigma = 1.4826 * whitening.background_mad_frequency_profile[plot_band]
    lower = np.maximum(background - robust_sigma, np.finfo(np.float64).smallest_subnormal)
    axis.semilogy(frequencies, background, color="tab:blue", label="N(f): background median")
    axis.fill_between(frequencies, lower, background + robust_sigma, alpha=0.25, color="tab:blue", label="N(f) ± 1.4826 MAD (diagnostic; not CI)")
    axis.axvline(profile.minimum_frequency_hz * 1.0e-9, color="gray", linestyle="--", linewidth=0.8, label="production search minimum unchanged")
    axis.set(title=f"Frequency background profile\n{title}", xlabel="frequency (GHz)", ylabel="linear STFT power")
    axis.legend(fontsize="small")
    _experimental_watermark(axis)
    figure.savefig(output / "background_profile.png", dpi=170)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(12.5, 6.2), constrained_layout=True)
    mesh = axis.pcolormesh(time_us, frequency_ghz, contrast, shading="auto", cmap="magma", vmin=-20, vmax=30)
    axis.plot(time_us, experimental.refined_result.refined_frequency_hz * 1.0e-9, color="cyan", linewidth=0.8, label="experimental ridge A/B (not production)")
    axis.set(title=f"Whitened spectrogram C(t,f)\n{title}", xlabel="absolute time (µs)", ylabel="frequency (GHz)")
    axis.legend(fontsize="x-small")
    _experimental_watermark(axis)
    figure.colorbar(mesh, ax=axis, label="background contrast (dB; not calibrated SNR)")
    figure.savefig(output / "whitened_spectrogram.png", dpi=170)
    plt.close(figure)

    figure, axes = plt.subplots(2, 1, figsize=(13.0, 9.0), sharex=True, constrained_layout=True)
    raw_mesh = axes[0].pcolormesh(time_us, frequency_ghz, raw_db, shading="auto", cmap="viridis", vmin=-60, vmax=0)
    white_mesh = axes[1].pcolormesh(time_us, frequency_ghz, contrast, shading="auto", cmap="magma", vmin=-20, vmax=30)
    axes[0].plot(time_us, baseline.refined_result.refined_frequency_hz * 1.0e-9, color="white", linewidth=0.8, label="production baseline ridge")
    axes[1].plot(time_us, experimental.refined_result.refined_frequency_hz * 1.0e-9, color="cyan", linewidth=0.8, label="experimental whitened ridge")
    axes[0].set_title("RAW relative STFT power")
    axes[1].set_title("WHITENED background contrast")
    axes[1].set_xlabel("absolute time (µs)")
    for axis in axes:
        axis.set_ylabel("frequency (GHz)")
        axis.legend(fontsize="x-small")
        _experimental_watermark(axis)
    figure.suptitle(title)
    figure.colorbar(raw_mesh, ax=axes[0], label="relative power (dB)")
    figure.colorbar(white_mesh, ax=axes[1], label="background contrast (dB; not SNR)")
    figure.savefig(output / "raw_vs_whitened.png", dpi=170)
    plt.close(figure)


def _experimental_watermark(axis: Any) -> None:
    axis.text(
        0.01,
        0.99,
        EXPERIMENTAL_LABEL,
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=7,
        color="crimson",
        bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "crimson"},
    )


def _compare_snapshot(path: Path, analysis: ChannelAnalysis) -> dict[str, bool]:
    detection = analysis.signal_detection_result
    current: dict[str, NDArray[Any]] = {
        "stft_time_s": analysis.stft_result.time_s,
        "stft_frequency_hz": analysis.stft_result.frequency_hz,
        "stft_spectrum": analysis.stft_result.spectrum,
        "formal_ridge_frequency_hz": analysis.ridge_result.frequency_hz,
        "formal_refined_frequency_hz": analysis.refined_result.refined_frequency_hz,
        "quality_state": np.asarray([state.value for state in detection.signal_states]),
        "apparent_velocity_m_s": analysis.apparent_velocity_m_s,
        "corrected_velocity_m_s": analysis.corrected_velocity_m_s,
        "event_time_s": np.asarray([_event_value(analysis)]),
    }
    with np.load(path, allow_pickle=False) as baseline:
        comparisons: dict[str, bool] = {}
        for name, value in current.items():
            stored = baseline[name]
            if stored.dtype.kind in "fc" or value.dtype.kind in "fc":
                comparisons[name] = bool(
                    np.array_equal(stored, value, equal_nan=True)
                )
            else:
                comparisons[name] = bool(np.array_equal(stored, value))
        return comparisons


def _write_data_archive(path: Path, whitening: SpectralWhiteningResult) -> None:
    np.savez_compressed(
        path,
        time_s=whitening.time_s,
        frequency_hz=whitening.frequency_hz,
        raw_spectral_quantity=whitening.raw_spectral_quantity,
        background_frame_mask=whitening.background_frame_mask,
        background_frequency_profile=whitening.background_frequency_profile,
        background_mad_frequency_profile=(
            whitening.background_mad_frequency_profile
        ),
        whitened_ratio=whitening.whitened_ratio,
        background_contrast_db=whitening.background_contrast_db,
        epsilon=np.asarray([whitening.epsilon]),
    )


def _assessment(
    output_root: Path,
    cases: Sequence[CaseSpec],
    configuration: WorkflowConfiguration,
    repository_root: Path,
    *,
    assessment_directory_name: str,
    reports_directory_name: str,
) -> None:
    baseline_root = output_root / "baseline"
    baseline_document = json.loads(
        (baseline_root / "summary.json").read_text(encoding="utf-8")
    )
    baseline_by_name = {
        item["snapshot"]: item for item in baseline_document["snapshots"]
    }
    assessment = output_root / assessment_directory_name
    assessment.mkdir(parents=True, exist_ok=False)
    figure_root = assessment / "figures"
    figure_root.mkdir()
    data_root = assessment / "data"
    data_root.mkdir()
    export_root = assessment / "production_regression_exports"
    export_root.mkdir()
    raw_before = _raw_hashes(repository_root)
    metric_rows: list[dict[str, object]] = []
    ridge_rows: list[dict[str, object]] = []
    regression_rows: list[dict[str, object]] = []

    for case in cases:
        for source_spec in case.sources:
            records = _read_records(source_spec, configuration)
            stfts, baseline_analyses, context = _analyze_production(
                records, configuration
            )
            export_signatures = _export_production(
                export_root / f"{case.case_id}__{source_spec.path.stem}",
                source_spec.path,
                baseline_analyses,
                configuration,
            )
            for channel, baseline in baseline_analyses.items():
                stft = stfts[channel]
                spectrum_before = stft.spectrum.copy()
                power = np.square(np.abs(stft.spectrum))
                if not np.all(np.isfinite(power)):
                    raise RuntimeError("Linear STFT power overflowed or became non-finite.")
                whitening = compute_frequency_background_whitening(
                    power,
                    time_s=stft.time_s,
                    frequency_hz=stft.frequency_hz,
                    background_start_s=case.background_start_s,
                    background_end_s=case.background_end_s,
                    minimum_background_frames=3,
                )
                if not np.array_equal(stft.spectrum, spectrum_before):
                    raise RuntimeError("The original STFT changed during whitening.")
                experimental_stft = _whitened_stft(stft, whitening)
                experimental = _analyze_stfts(
                    {channel: experimental_stft},
                    configuration,
                    analysis_start_s=context.analysis_start_s,
                    analysis_end_s=context.analysis_end_s,
                    manual_reference_s=context.manual_event_reference_s,
                )[channel]
                metrics, rows = _channel_metrics(
                    case,
                    source_spec.path,
                    channel,
                    baseline,
                    experimental,
                    whitening,
                    configuration,
                )
                metric_rows.append(metrics)
                ridge_rows.extend(rows)
                name = _snapshot_name(case, source_spec.path, channel)
                comparisons = _compare_snapshot(
                    baseline_root / "snapshots" / f"{name}.npz", baseline
                )
                old_export = baseline_by_name[name]["formal_export_signature"]
                new_export = export_signatures[channel]
                export_equal = old_export == new_export
                regression_rows.append(
                    {
                        "snapshot": name,
                        "source": source_spec.path.name,
                        "channel": channel,
                        **comparisons,
                        "formal_export_equal_except_timestamp": export_equal,
                        "all_production_outputs_equal": (
                            all(comparisons.values()) and export_equal
                        ),
                    }
                )
                _write_data_archive(data_root / f"{name}.npz", whitening)
                _plot_channel(
                    figure_root / name,
                    case,
                    source_spec.path,
                    channel,
                    baseline,
                    experimental,
                    whitening,
                    configuration,
                )

    raw_after = _raw_hashes(repository_root)
    if raw_before != raw_after:
        raise RuntimeError("data/raw changed during TASK-020A assessment.")
    if not all(bool(row["all_production_outputs_equal"]) for row in regression_rows):
        raise RuntimeError("Production regression is non-zero.")
    _write_csv_exclusive(
        assessment / "background_metrics.csv",
        [_flatten_metric_row(row) for row in metric_rows],
    )
    _write_csv_exclusive(assessment / "ridge_comparison.csv", ridge_rows)
    _write_csv_exclusive(assessment / "production_regression.csv", regression_rows)
    conclusion = _conclusion(metric_rows)
    summary = {
        "schema": "task020a-assessment-v1",
        "experimental": True,
        "production_result": False,
        "cases": [_case_document(case) for case in cases],
        "mathematical_definition": {
            "raw_spectral_quantity": "P(t,f) = abs(STFT spectrum(t,f))**2 on a linear non-negative power scale",
            "background": "N(f) = median over explicit background frames of P(t,f)",
            "mad_diagnostic": "M(f) = median over explicit background frames of abs(P(t,f)-N(f))",
            "epsilon": "max(float64.eps * max(N), float64.smallest_subnormal)",
            "whitened_ratio": "R(t,f) = P(t,f)/(N(f)+epsilon)",
            "background_contrast_db": "C(t,f) = 10*log10((P(t,f)+epsilon)/(N(f)+epsilon))",
        },
        "production_search_band_hz_unchanged": [
            configuration.analysis.default_profile.minimum_frequency_hz,
            configuration.analysis.default_profile.maximum_frequency_hz,
        ],
        "channel_metrics": metric_rows,
        "production_regression": regression_rows,
        "all_production_outputs_equal": True,
        "raw_sha256_before": raw_before,
        "raw_sha256_after": raw_after,
        "raw_unchanged": True,
        "weak_ridge_assessment": conclusion,
        "ridge_ab_scope": "Existing production workflow reused on a detached sqrt(whitened_ratio) STFT solely for experimental A/B; outputs are never labeled production measurements.",
    }
    _write_json_exclusive(assessment / "summary.json", summary)
    reports = output_root / reports_directory_name
    reports.mkdir(exist_ok=False)
    _write_report(reports / "task020a_report.md", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))


def _case_document(case: CaseSpec) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "classification": case.classification,
        "background_mode": case.background_mode,
        "background_start_s": case.background_start_s,
        "background_end_s": case.background_end_s,
        "selection_note": case.selection_note,
        "sources": [
            {
                "path": str(source.path),
                "voltage_columns": dict(source.voltage_columns),
            }
            for source in case.sources
        ],
    }


def _conclusion(rows: Sequence[Mapping[str, object]]) -> str:
    hard = [row for row in rows if row["classification"] == "Hard Case"]
    if not hard:
        return "尚不能判断"
    gains = [
        _object_int(row["newly_recovered_frames_not_production"])
        - _object_int(row["lost_frames_not_production"])
        for row in hard
    ]
    contrast_changes = [
        _summary_median(row, "whitened_frame_median_spectral_contrast_db")
        - _summary_median(row, "raw_frame_median_spectral_contrast_db")
        for row in hard
        if _summary_median_or_none(
            row, "whitened_frame_median_spectral_contrast_db"
        )
        is not None
        and _summary_median_or_none(row, "raw_frame_median_spectral_contrast_db")
        is not None
    ]
    if sum(gains) > 0 and contrast_changes and float(np.median(contrast_changes)) > 1.0:
        return "有限改善"
    if sum(gains) < 0:
        return "恶化"
    return "无明显改善"


def _flatten_metric_row(row: Mapping[str, object]) -> dict[str, object]:
    band = _object_mapping(row["production_search_band_background_uniformity"])
    delta_frequency = _object_mapping(
        row["delta_frequency_hz_mutually_gate_passing"]
    )
    delta_velocity = _object_mapping(
        row["delta_apparent_velocity_m_s_mutually_gate_passing"]
    )
    raw_contrast = _object_mapping(row["raw_frame_median_spectral_contrast_db"])
    white_contrast = _object_mapping(
        row["whitened_frame_median_spectral_contrast_db"]
    )
    return {
        "case_id": row["case_id"],
        "classification": row["classification"],
        "source": row["source"],
        "channel": row["channel"],
        "background_mode": row["background_mode"],
        "background_start_s": row["background_start_s"],
        "background_end_s": row["background_end_s"],
        "background_frame_count": row["background_frame_count"],
        "epsilon": row["epsilon"],
        "frequency_bin_spacing_hz": row["frequency_bin_spacing_hz"],
        "raw_background_nonuniformity_db": band["raw_nonuniformity_db"],
        "whitened_background_nonuniformity_db": band[
            "whitened_nonuniformity_db"
        ],
        "background_nonuniformity_reduction_db": band["reduction_db"],
        "baseline_measured_frames": row["baseline_measured_frames"],
        "experimental_gate_passing_frames_not_production": row[
            "experimental_gate_passing_frames_not_production"
        ],
        "newly_recovered_frames_not_production": row[
            "newly_recovered_frames_not_production"
        ],
        "lost_frames_not_production": row["lost_frames_not_production"],
        "changed_discrete_ridge_bin_frames": row[
            "changed_discrete_ridge_bin_frames"
        ],
        "changed_discrete_ridge_bin_mutually_gate_passing_frames": row[
            "changed_discrete_ridge_bin_mutually_gate_passing_frames"
        ],
        "mutually_gate_passing_frame_count": delta_frequency["count"],
        "delta_frequency_median_hz_mutually_gate_passing": delta_frequency[
            "median"
        ],
        "delta_frequency_p95_absolute_hz_mutually_gate_passing": delta_frequency[
            "p95_absolute"
        ],
        "delta_frequency_maximum_absolute_hz_mutually_gate_passing": (
            delta_frequency["maximum_absolute"]
        ),
        "delta_velocity_p95_absolute_m_s_mutually_gate_passing": delta_velocity[
            "p95_absolute"
        ],
        "raw_frame_median_spectral_contrast_db_median": raw_contrast["median"],
        "whitened_frame_median_spectral_contrast_db_median": white_contrast[
            "median"
        ],
        "event_time_s": row["event_time_s"],
        "experimental_event_time_s_not_production": row[
            "experimental_event_time_s_not_production"
        ],
        "experimental_minus_production_event_time_s": row[
            "experimental_minus_production_event_time_s"
        ],
        "baseline_pre_event_gate_passing_frames": row[
            "baseline_pre_event_gate_passing_frames"
        ],
        "experimental_pre_event_gate_passing_frames_not_production": row[
            "experimental_pre_event_gate_passing_frames_not_production"
        ],
    }


def _object_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Expected a metric mapping.")
    return value


def _object_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError("Expected an integer metric.")
    return int(value)


def _summary_median_or_none(
    row: Mapping[str, object],
    key: str,
) -> float | None:
    summary = row[key]
    if not isinstance(summary, Mapping):
        raise TypeError(f"{key} must be a metric mapping.")
    value = summary["median"]
    if value is None:
        return None
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{key}.median must be numeric or None.")
    return float(value)


def _summary_median(row: Mapping[str, object], key: str) -> float:
    value = _summary_median_or_none(row, key)
    if value is None:
        raise ValueError(f"{key}.median is unavailable.")
    return value


def _write_report(path: Path, summary: Mapping[str, Any]) -> None:
    rows = summary["channel_metrics"]
    lines = [
        "# TASK-020A Background Whitening Research Report",
        "",
        f"> {EXPERIMENTAL_LABEL}",
        "",
        "## Scope and mathematical definition",
        "",
        "The tool computes linear STFT power `P=|Z|²`, then `N(f)=median_bg P`, "
        "`R=P/(N+epsilon)`, and `C=10 log10((P+epsilon)/(N+epsilon))`. "
        "The deterministic scale-aware epsilon is "
        "`max(float64.eps*max(N), float64.smallest_subnormal)`. MAD is diagnostic only.",
        "",
        "## Quantitative results",
        "",
        "| Case | Source | Channel | Raw bg spread dB | White bg spread dB | Baseline measured | Experimental gate-passing | New | Lost | Δf p95 abs Hz |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        band = row["production_search_band_background_uniformity"]
        delta = row["delta_frequency_hz_mutually_gate_passing"]
        lines.append(
            f"| {row['classification']} | {row['source']} | {row['channel']} | "
            f"{band['raw_nonuniformity_db']:.3f} | {band['whitened_nonuniformity_db']:.3g} | "
            f"{row['baseline_measured_frames']} | {row['experimental_gate_passing_frames_not_production']} | "
            f"{row['newly_recovered_frames_not_production']} | {row['lost_frames_not_production']} | "
            f"{delta['p95_absolute'] if delta['p95_absolute'] is not None else 'NA'} |"
        )
    lines.extend(
        [
            "",
            "Experimental weak-ridge assessment: "
            f"**{summary['weak_ridge_assessment']}**. This classification is based on "
            "gate-passing-frame balance plus frame-median spectral contrast; it is not "
            "a calibrated SNR claim.",
            "",
            "## Production regression",
            "",
            "Production changed: **NO**. STFT arrays, formal ridge, quality states, "
            "apparent velocity, corrected velocity, event candidate, and formal export "
            "content (excluding export timestamp) exactly match the pre-assessment baseline.",
            "",
            "## Risks and boundary checks",
            "",
            "The summary records DC and below-50-MHz contrast diagnostics separately. "
            "The production 0.05–6 GHz search band is unchanged. Frequency shifts, lost "
            "frames, and pre-event gate-passing frames must be reviewed channel by channel. "
            "MAD bands in figures are robust-scale diagnostics, not confidence intervals.",
            "",
            "## Next step",
            "",
            "Do not promote this algorithm. If the measured trade-off is accepted after "
            "human review, the only recommended continuation is TASK-020B: whitened "
            "candidate/ridge selection. Do not start it automatically.",
            "",
        ]
    )
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def _json_number(value: object) -> float | None:
    converted = float(value)  # type: ignore[arg-type]
    return converted if math.isfinite(converted) else None


def _write_csv_exclusive(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows available for {path.name}.")
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json_exclusive(path: Path, document: Mapping[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EXPERIMENTAL TASK-020A frequency-background whitening assessment."
    )
    parser.add_argument(
        "--case-config",
        type=Path,
        default=Path("tools/task020a_cases.json"),
        help="JSON with explicit SI background intervals.",
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--background-start",
        type=float,
        help="Explicit closed background start in SI seconds.",
    )
    parser.add_argument(
        "--background-end",
        type=float,
        help="Explicit closed background end in SI seconds.",
    )
    parser.add_argument(
        "--voltage-column",
        action="append",
        help="Repeatable NAME=INDEX mapping for --source.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("artifacts/task020a"),
    )
    parser.add_argument(
        "--capture-baseline",
        action="store_true",
        help="Capture production baseline only; do not run whitening.",
    )
    parser.add_argument(
        "--assessment-directory-name",
        default="assessment",
        help="Non-existing result subdirectory under --output-directory.",
    )
    parser.add_argument(
        "--reports-directory-name",
        default="reports",
        help="Non-existing report subdirectory under --output-directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    output_root = (repository_root / arguments.output_directory).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    configuration = load_workflow_config(
        repository_root / "configs" / "pdv_studio_defaults.toml",
        repository_root=repository_root,
    )
    if arguments.source is None:
        cases = _load_cases(
            (repository_root / arguments.case_config).resolve(), repository_root
        )
    else:
        cases = (_single_case(arguments, repository_root),)
    if arguments.capture_baseline:
        _capture_baseline(output_root, cases, configuration, repository_root)
    else:
        _assessment(
            output_root,
            cases,
            configuration,
            repository_root,
            assessment_directory_name=str(arguments.assessment_directory_name),
            reports_directory_name=str(arguments.reports_directory_name),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
