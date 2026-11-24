"""Unified 5-file Origin-ready export bundle shared by the CLI and desktop GUI."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio import __version__
from dps_studio.core.export.models import (
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultExportValidationError,
    ResultExportWriteError,
)
from dps_studio.core.export.time_coordinates import event_relative_time_s
from dps_studio.core.physics import velocity_correction_metadata
from dps_studio.core.physics.dechirp import DechirpResult
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import PRE_EVENT_DISPLAY_ORIGIN
from dps_studio.core.workflow.acceleration import acceleration_metadata, channel_acceleration
from dps_studio.core.workflow.models import ChannelAnalysis


BUNDLE_SCHEMA_VERSION = "pdv-studio-bundle-v1"
DEFAULT_MAX_BRIDGE_GAP_FRAMES = 5

_PDV_CHANNEL_RE = re.compile(r"^pdv_channel_(\d+)$")
_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{value}" for value in range(1, 10)),
        *(f"LPT{value}" for value in range(1, 10)),
    }
)
_MODE_DIRECTORY_TOKENS = {
    ResultAnalysisMode.AUTOMATIC: "auto",
    ResultAnalysisMode.GUIDED: "guided",
}
_DETAIL_CSV_FIELDS = (
    "time_s",
    "time_from_event_s",
    "coarse_peak_frequency_hz",
    "refined_frequency_hz",
    "working_frequency_hz",
    "apparent_velocity_m_s",
    "angle_corrected_apparent_velocity_m_s",
    "corrected_velocity_m_s",
    "continuous_apparent_velocity_m_s",
    "continuous_angle_corrected_apparent_velocity_m_s",
    "continuous_corrected_velocity_m_s",
    "display_velocity_m_s",
    "ridge_quality_flag",
    "ridge_refinement_status",
    "ridge_selection_origin",
    "selected_candidate_rank",
    "signal_state",
    "working_source",
    "velocity_origin",
    "is_pre_event_display_only",
    "channel",
    "analysis_mode",
)


@dataclass(frozen=True, slots=True, eq=False)
class DisplayVelocityCurveResult:
    """Derived ready-to-plot velocity curve built strictly from measured frames."""

    values: NDArray[np.float64]
    measured_frames: int
    total_frames: int
    bridged_gap_count: int
    bridged_frame_count: int
    bridged_intervals: tuple[tuple[int, int], ...]
    smoothing_applied: bool
    pre_event_enabled: bool
    pre_event_time_s: float | None
    pre_event_source: str


@dataclass(frozen=True, slots=True)
class ResultBundleOptions:
    """Validated caller selections for unified 5-file bundle export."""

    output_directory: Path
    analysis_mode: ResultAnalysisMode
    channel_analyses: Mapping[str, ChannelAnalysis]
    time_origin: ExportTimeOrigin = ExportTimeOrigin.ABSOLUTE
    source_path: Path | None = None
    source_sha256: str | None = None
    analysis_profile_name: str = ""
    pre_event_display_enabled: bool = True
    pre_event_display_velocity_m_s: float = 0.0
    max_bridge_gap_frames: int = DEFAULT_MAX_BRIDGE_GAP_FRAMES
    event_reference_source: str | None = None
    event_time_source: str = "unset"
    include_acceleration: bool = False
    acceleration_fit_window_s: float | None = None
    dechirp_results: Mapping[str, DechirpResult] = field(default_factory=dict)
    include_full_diagnostics: bool = False
    dps_studio_version: str = __version__
    input_format: Mapping[str, object] = field(default_factory=dict)
    experimental_conditions: Mapping[str, object] = field(default_factory=dict)
    analysis_parameters: Mapping[str, object] = field(default_factory=dict)
    auto_band_retry: Mapping[str, object] = field(default_factory=dict)
    extra_warnings: tuple[str, ...] = ()
    protected_output_directories: tuple[Path, ...] = ()
    spectrogram_renderer: Callable[[Path], None] | None = None
    pre_publish_hook: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class ResultBundleReport:
    """Created file inventory and display-processing audit for one bundle export."""

    output_directory: Path
    velocity_raw_csv_path: Path
    velocity_gated_csv_path: Path
    velocity_display_csv_path: Path
    run_summary_json_path: Path
    spectrogram_ridge_png_path: Path | None
    acceleration_csv_path: Path | None
    detail_csv_paths: Mapping[str, Path]
    channel_names: tuple[str, ...]
    channel_tokens: Mapping[str, str]
    display_curves: Mapping[str, DisplayVelocityCurveResult]
    warnings: tuple[str, ...]


def channel_token(channel_name: str) -> str:
    """Map internal channel IDs (e.g. pdv_channel_1 -> ch1) to concise CSV/file tokens."""
    match = _PDV_CHANNEL_RE.fullmatch(channel_name)
    if match is not None:
        return f"ch{match.group(1)}"
    normalized = _safe_filename_token(channel_name)
    if not normalized:
        raise ResultExportValidationError(
            f"Channel name cannot produce an export token: {channel_name!r}"
        )
    return normalized


def build_display_velocity_curve(
    analysis: ChannelAnalysis,
    *,
    pre_event_display_enabled: bool = True,
    pre_event_display_velocity_m_s: float = 0.0,
    max_bridge_gap_frames: int = DEFAULT_MAX_BRIDGE_GAP_FRAMES,
    event_reference_source: str | None = None,
) -> DisplayVelocityCurveResult:
    """Build an Origin-ready derived curve from formal measured frames without fabrication."""
    if not isinstance(pre_event_display_enabled, bool):
        raise TypeError("pre_event_display_enabled must be a boolean.")
    if not math.isfinite(pre_event_display_velocity_m_s):
        raise ResultExportValidationError("pre_event_display_velocity_m_s must be finite.")
    if max_bridge_gap_frames < 0:
        raise ResultExportValidationError("max_bridge_gap_frames must be non-negative.")

    time_s = np.asarray(analysis.stft_result.time_s, dtype=np.float64)
    states = analysis.signal_detection_result.signal_states
    corrected = np.asarray(analysis.corrected_velocity_m_s, dtype=np.float64)
    total_frames = int(time_s.size)

    gated = np.full(total_frames, np.nan, dtype=np.float64)
    for idx in range(total_frames):
        val = float(corrected[idx])
        if states[idx] is SignalState.MEASURED and math.isfinite(val):
            gated[idx] = val

    measured_indices = np.flatnonzero(np.isfinite(gated))
    measured_frames = int(measured_indices.size)
    if measured_frames == 0:
        return DisplayVelocityCurveResult(
            values=gated,
            measured_frames=0,
            total_frames=total_frames,
            bridged_gap_count=0,
            bridged_frame_count=0,
            bridged_intervals=(),
            smoothing_applied=False,
            pre_event_enabled=pre_event_display_enabled,
            pre_event_time_s=None,
            pre_event_source="no_measured_frames",
        )

    runs = _contiguous_true_runs(np.isfinite(gated))
    work = gated.copy()
    smoothing_applied = False
    for run_start, run_end in runs:
        if run_end - run_start + 1 >= 3:
            smoothing_applied = True
            for idx in range(run_start + 1, run_end):
                work[idx] = 0.25 * gated[idx - 1] + 0.5 * gated[idx] + 0.25 * gated[idx + 1]

    bridged_intervals: list[tuple[int, int]] = []
    bridged_frame_count = 0
    for (_left_start, left_end), (right_start, _right_end) in zip(runs, runs[1:], strict=False):
        gap_start = left_end + 1
        gap_end = right_start - 1
        gap_len = gap_end - gap_start + 1
        if 1 <= gap_len <= max_bridge_gap_frames:
            t0 = float(time_s[left_end])
            t1 = float(time_s[right_start])
            v0 = float(work[left_end])
            v1 = float(work[right_start])
            dt = t1 - t0
            for idx in range(gap_start, gap_end + 1):
                alpha = (float(time_s[idx]) - t0) / dt if dt > 0.0 else (idx - left_end) / (right_start - left_end)
                work[idx] = v0 + alpha * (v1 - v0)
            bridged_intervals.append((gap_start, gap_end))
            bridged_frame_count += gap_len

    first_measured_t = float(time_s[int(measured_indices[0])])
    manual_ref = analysis.signal_detection_result.manual_event_reference_time_s
    manual_valid = (
        manual_ref is not None
        and math.isfinite(manual_ref)
        and float(time_s[0]) <= float(manual_ref) <= float(time_s[-1])
    )
    resolved_t_event: float | None
    pre_event_source: str
    if pre_event_display_enabled:
        if manual_valid:
            assert manual_ref is not None
            resolved_t_event = float(manual_ref)
            pre_event_source = event_reference_source or "explicit_event_reference"
        else:
            cand = analysis.stream_event_candidates.primary_candidate_time_s
            if cand is not None and math.isfinite(cand) and float(time_s[0]) < float(cand) <= first_measured_t:
                resolved_t_event = float(cand)
                pre_event_source = "stream_event_candidate"
            else:
                resolved_t_event = first_measured_t
                pre_event_source = "first_measured_frame"
        work[time_s < resolved_t_event] = float(pre_event_display_velocity_m_s)
    else:
        resolved_t_event = float(manual_ref) if manual_valid and manual_ref is not None else None
        pre_event_source = "disabled"

    return DisplayVelocityCurveResult(
        values=work,
        measured_frames=measured_frames,
        total_frames=total_frames,
        bridged_gap_count=len(bridged_intervals),
        bridged_frame_count=bridged_frame_count,
        bridged_intervals=tuple(bridged_intervals),
        smoothing_applied=smoothing_applied,
        pre_event_enabled=pre_event_display_enabled,
        pre_event_time_s=resolved_t_event,
        pre_event_source=pre_event_source,
    )


def allocate_bundle_directory(
    parent_directory: Path,
    *,
    source_path: Path | None,
    analysis_mode: ResultAnalysisMode,
    protected_output_directories: tuple[Path, ...] = (),
) -> Path:
    """Choose a non-overwriting bundle subfolder under a validated parent directory."""
    parent = _validate_output_directory(
        parent_directory,
        protected_output_directories=protected_output_directories,
    )
    parent.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename_token(source_path.stem) if source_path is not None else "pdv_result"
    stem = stem or "pdv_result"
    mode_token = _MODE_DIRECTORY_TOKENS[analysis_mode]
    base_name = f"{stem}_{mode_token}"
    for suffix in range(1, 10_000):
        name = base_name if suffix == 1 else f"{base_name}_{suffix}"
        candidate = parent / name
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ResultExportWriteError(
        f"Could not allocate a non-overwriting bundle directory under {parent}."
    )


def export_result_bundle(options: ResultBundleOptions) -> ResultBundleReport:
    """Atomically write the unified 5-file bundle (plus opt-in extras) into output_directory."""
    if not options.channel_analyses:
        raise ResultExportValidationError("At least one analyzed channel is required to export.")
    if not isinstance(options.time_origin, ExportTimeOrigin):
        raise TypeError("time_origin must be an ExportTimeOrigin value.")
    if not math.isfinite(options.pre_event_display_velocity_m_s):
        raise ResultExportValidationError("pre_event_display_velocity_m_s must be finite.")
    if options.acceleration_fit_window_s is not None and (
        not options.include_acceleration
        or not math.isfinite(options.acceleration_fit_window_s)
        or options.acceleration_fit_window_s <= 0.0
    ):
        raise ResultExportValidationError(
            "acceleration_fit_window_s requires include_acceleration=True and a positive finite value."
        )

    output_dir = _validate_output_directory(
        options.output_directory,
        protected_output_directories=options.protected_output_directories,
    )
    channels = dict(options.channel_analyses)
    channel_names = tuple(channels)
    tokens: dict[str, str] = {name: channel_token(name) for name in channel_names}
    if len(set(tokens.values())) != len(tokens):
        raise ResultExportValidationError(
            f"Channel export tokens must be unique: {tokens}"
        )

    time_grid, time_values, time_column = _validate_shared_axes(channels, options.time_origin)

    output_dir.mkdir(parents=True, exist_ok=True)
    planned_names = [
        "velocity_raw.csv",
        "velocity_gated.csv",
        "velocity_display.csv",
        "run_summary.json",
    ]
    if options.spectrogram_renderer is not None:
        planned_names.append("spectrogram_ridge.png")
    if options.include_acceleration:
        planned_names.append("acceleration.csv")
    if options.include_full_diagnostics:
        planned_names.extend(f"{tokens[name]}_detail.csv" for name in channel_names)

    collisions = [name for name in planned_names if (output_dir / name).exists() or (output_dir / name).is_symlink()]
    if collisions:
        raise ResultExportWriteError(
            f"Target directory already contains result file(s): {', '.join(collisions)}"
        )

    display_curves: dict[str, DisplayVelocityCurveResult] = {}
    gated_arrays: dict[str, NDArray[np.float64]] = {}
    raw_arrays: dict[str, NDArray[np.float64]] = {}
    for name, analysis in channels.items():
        states = analysis.signal_detection_result.signal_states
        corrected = np.asarray(analysis.corrected_velocity_m_s, dtype=np.float64)
        gated = np.array(
            [
                float(corrected[i]) if states[i] is SignalState.MEASURED and math.isfinite(float(corrected[i])) else np.nan
                for i in range(time_grid.size)
            ],
            dtype=np.float64,
        )
        raw = np.asarray(analysis.continuous_corrected_velocity_m_s, dtype=np.float64)
        gated_arrays[name] = gated
        raw_arrays[name] = raw
        display_curves[name] = build_display_velocity_curve(
            analysis,
            pre_event_display_enabled=options.pre_event_display_enabled,
            pre_event_display_velocity_m_s=options.pre_event_display_velocity_m_s,
            max_bridge_gap_frames=options.max_bridge_gap_frames,
            event_reference_source=options.event_reference_source,
        )

    timestamp = datetime.now(UTC)
    staging = _create_staging_directory(output_dir, timestamp)
    detail_paths: dict[str, Path] = {}
    accel_path: Path | None = None
    plot_path: Path | None = None

    try:
        _write_multi_channel_velocity_csv(
            staging / "velocity_raw.csv",
            time_column=time_column,
            time_values=time_values,
            column_headers=tuple(f"{tokens[n]}_raw_velocity_m_s" for n in channel_names),
            arrays=tuple(raw_arrays[n] for n in channel_names),
        )
        _write_multi_channel_velocity_csv(
            staging / "velocity_gated.csv",
            time_column=time_column,
            time_values=time_values,
            column_headers=tuple(f"{tokens[n]}_gated_velocity_m_s" for n in channel_names),
            arrays=tuple(gated_arrays[n] for n in channel_names),
        )
        _write_multi_channel_velocity_csv(
            staging / "velocity_display.csv",
            time_column=time_column,
            time_values=time_values,
            column_headers=tuple(f"{tokens[n]}_display_velocity_m_s" for n in channel_names),
            arrays=tuple(display_curves[n].values for n in channel_names),
        )

        if options.spectrogram_renderer is not None:
            staged_plot = staging / "spectrogram_ridge.png"
            options.spectrogram_renderer(staged_plot)
            if not staged_plot.is_file() or staged_plot.stat().st_size == 0:
                raise ResultExportWriteError("Spectrogram renderer did not produce spectrogram_ridge.png.")
            plot_path = output_dir / "spectrogram_ridge.png"

        accel_meta: dict[str, Any] = {}
        if options.include_acceleration:
            staged_accel = staging / "acceleration.csv"
            accel_meta = _write_bundle_acceleration_csv(
                staged_accel,
                channels=channels,
                tokens=tokens,
                time_column=time_column,
                time_values=time_values,
                time_origin=options.time_origin,
                fit_window_s=options.acceleration_fit_window_s,
                dechirp_results=options.dechirp_results,
            )
            accel_path = output_dir / "acceleration.csv"

        if options.include_full_diagnostics:
            for name in channel_names:
                detail_name = f"{tokens[name]}_detail.csv"
                _write_bundle_detail_csv(
                    staging / detail_name,
                    channel_name=name,
                    analysis=channels[name],
                    analysis_mode=options.analysis_mode,
                )
                detail_paths[name] = output_dir / detail_name

        outputs_manifest: dict[str, object] = {
            "velocity_raw_csv": "velocity_raw.csv",
            "velocity_gated_csv": "velocity_gated.csv",
            "velocity_display_csv": "velocity_display.csv",
            "run_summary_json": "run_summary.json",
            "spectrogram_ridge_png": "spectrogram_ridge.png" if plot_path is not None else None,
            "acceleration_csv": "acceleration.csv" if accel_path is not None else None,
            "detail_csvs": {name: f"{tokens[name]}_detail.csv" for name in detail_paths},
        }
        quality_map, warnings_list = _build_quality_and_warnings(
            channels,
            extra_warnings=options.extra_warnings,
        )
        summary = _build_run_summary(
            options=options,
            timestamp=timestamp,
            time_column=time_column,
            channels=channels,
            tokens=tokens,
            display_curves=display_curves,
            quality_map=quality_map,
            warnings=warnings_list,
            accel_meta=accel_meta,
            outputs=outputs_manifest,
        )
        _write_json(staging / "run_summary.json", summary)

        if options.pre_publish_hook is not None:
            options.pre_publish_hook()

        _publish_staging(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return ResultBundleReport(
        output_directory=output_dir,
        velocity_raw_csv_path=output_dir / "velocity_raw.csv",
        velocity_gated_csv_path=output_dir / "velocity_gated.csv",
        velocity_display_csv_path=output_dir / "velocity_display.csv",
        run_summary_json_path=output_dir / "run_summary.json",
        spectrogram_ridge_png_path=plot_path,
        acceleration_csv_path=accel_path,
        detail_csv_paths=detail_paths,
        channel_names=channel_names,
        channel_tokens=tokens,
        display_curves=display_curves,
        warnings=tuple(warnings_list),
    )


def _contiguous_true_runs(mask: NDArray[np.bool_]) -> tuple[tuple[int, int], ...]:
    if not mask.size or not np.any(mask):
        return ()
    edges = np.flatnonzero(np.diff(mask.astype(np.int8), prepend=0, append=0))
    return tuple((int(start), int(stop) - 1) for start, stop in zip(edges[::2], edges[1::2], strict=True))


def _csv_cell(value: float) -> str:
    return "" if not math.isfinite(value) else repr(value)


def _safe_filename_token(value: str) -> str:
    normalized = value.strip()
    normalized = "".join(
        "-" if ch in _INVALID_FILENAME_CHARS or ord(ch) < 32 else ch
        for ch in normalized
    )
    normalized = re.sub(r"\s+", "_", normalized).strip(". _-")
    if normalized.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        normalized = f"pdv_{normalized}"
    return normalized[:100]


def _validate_output_directory(
    directory: Path,
    *,
    protected_output_directories: tuple[Path, ...],
) -> Path:
    if not isinstance(directory, Path):
        raise TypeError("output_directory must be a pathlib.Path instance.")
    expanded = directory.expanduser()
    resolved = expanded.resolve()
    for candidate in (expanded, resolved):
        parts = tuple(part.casefold() for part in candidate.parts)
        if any(pair == ("data", "raw") for pair in zip(parts, parts[1:], strict=False)):
            raise ResultExportValidationError(f"Cannot export inside data/raw: {directory}")
    for protected in protected_output_directories:
        if resolved.is_relative_to(protected.expanduser().resolve()):
            raise ResultExportValidationError(
                f"Cannot export into protected directory {protected}: {directory}"
            )
    if resolved.exists() and not resolved.is_dir():
        raise ResultExportValidationError(f"Output destination is not a directory: {directory}")
    return resolved


def _validate_shared_axes(
    channels: Mapping[str, ChannelAnalysis],
    time_origin: ExportTimeOrigin,
) -> tuple[NDArray[np.float64], NDArray[np.float64], str]:
    first_name = next(iter(channels))
    first_analysis = channels[first_name]
    time_grid = np.asarray(first_analysis.stft_result.time_s, dtype=np.float64)
    if time_grid.ndim != 1 or time_grid.size == 0 or not np.all(np.isfinite(time_grid)):
        raise ResultExportValidationError(f"Channel {first_name!r} has an invalid STFT time axis.")
    for name, analysis in channels.items():
        other_time = np.asarray(analysis.stft_result.time_s, dtype=np.float64)
        if not np.array_equal(other_time, time_grid):
            raise ResultExportValidationError(
                f"Channel {name!r} time axis does not match {first_name!r} for combined export."
            )
        if len(analysis.signal_detection_result.signal_states) != time_grid.size:
            raise ResultExportValidationError(f"Channel {name!r} signal states length mismatch.")
        if np.asarray(analysis.continuous_corrected_velocity_m_s).shape != time_grid.shape:
            raise ResultExportValidationError(f"Channel {name!r} raw velocity length mismatch.")
        if np.asarray(analysis.corrected_velocity_m_s).shape != time_grid.shape:
            raise ResultExportValidationError(f"Channel {name!r} corrected velocity length mismatch.")

    if time_origin is ExportTimeOrigin.EVENT:
        refs = [analysis.signal_detection_result.manual_event_reference_time_s for analysis in channels.values()]
        if any(ref is None or not math.isfinite(ref) for ref in refs):
            raise ResultExportValidationError(
                "Event time origin requires an explicit event reference time for all exported channels."
            )
        ref0 = float(refs[0])  # type: ignore[arg-type]
        if any(not math.isclose(float(r), ref0, rel_tol=0.0, abs_tol=1e-12) for r in refs if r is not None):
            raise ResultExportValidationError(
                "All exported channels must share one event reference time for combined time_from_event_s export."
            )
        return time_grid, event_relative_time_s(time_grid, ref0), "time_from_event_s"
    return time_grid, time_grid, "time_s"


def _create_staging_directory(output_directory: Path, timestamp: datetime) -> Path:
    base_name = timestamp.strftime(".pdv_bundle_%Y%m%dT%H%M%SZ")
    for suffix in range(1, 10_000):
        name = base_name if suffix == 1 else f"{base_name}_{suffix}"
        candidate = output_directory / name
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            raise ResultExportWriteError(
                f"Export output directory is not writable: {output_directory}"
            ) from exc
    raise ResultExportWriteError("Could not create temporary staging directory for export.")


def _publish_staging(staging: Path, output_directory: Path) -> None:
    paths = sorted(staging.iterdir(), key=lambda p: (p.name == "run_summary.json", p.name))
    published: list[Path] = []
    try:
        for src in paths:
            dst = output_directory / src.name
            os.link(src, dst)
            published.append(dst)
    except OSError as exc:
        for dst in reversed(published):
            dst.unlink(missing_ok=True)
        raise ResultExportWriteError(f"Could not commit bundle files into {output_directory}: {exc}") from exc
    for src in paths:
        src.unlink(missing_ok=True)
    staging.rmdir()


def _write_multi_channel_velocity_csv(
    path: Path,
    *,
    time_column: str,
    time_values: NDArray[np.float64],
    column_headers: tuple[str, ...],
    arrays: tuple[NDArray[np.float64], ...],
) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow((time_column, *column_headers))
            for idx in range(time_values.size):
                row = [_csv_cell(float(time_values[idx]))]
                row.extend(_csv_cell(float(arr[idx])) for arr in arrays)
                writer.writerow(row)
    except OSError as exc:
        raise ResultExportWriteError(f"Could not write {path.name}: {exc}") from exc


def _write_bundle_acceleration_csv(
    path: Path,
    *,
    channels: Mapping[str, ChannelAnalysis],
    tokens: Mapping[str, str],
    time_column: str,
    time_values: NDArray[np.float64],
    time_origin: ExportTimeOrigin,
    fit_window_s: float | None,
    dechirp_results: Mapping[str, DechirpResult],
) -> dict[str, Any]:
    fields: list[str] = [time_column]
    series: list[NDArray[np.float64] | tuple[str, ...]] = []
    per_channel: dict[str, Any] = {}
    for name, analysis in channels.items():
        tok = tokens[name]
        deriv = channel_acceleration(analysis)
        fitted = channel_acceleration(analysis, window_s=fit_window_s) if fit_window_s is not None else None
        dechirp = dechirp_results.get(name)
        fields.extend([f"{tok}_velocity_m_s", f"{tok}_acceleration_m_s2"])
        series.extend([np.asarray(analysis.plot_velocity_m_s, dtype=np.float64), np.asarray(deriv.acceleration_m_s2, dtype=np.float64)])
        ch_meta: dict[str, Any] = {
            **acceleration_metadata(analysis),
            "csv_file": "acceleration.csv",
            "velocity_column": f"{tok}_velocity_m_s",
            "acceleration_column": f"{tok}_acceleration_m_s2",
            "time_origin": time_origin.value,
            "row_count": int(time_values.size),
        }
        if fitted is not None:
            fields.append(f"{tok}_local_linear_acceleration_m_s2")
            series.append(np.asarray(fitted.acceleration_m_s2, dtype=np.float64))
            ch_meta["local_fit"] = {
                "method": "local_linear_least_squares",
                "window_s": fit_window_s,
                "column": f"{tok}_local_linear_acceleration_m_s2",
            }
        if dechirp is not None:
            fields.extend([f"{tok}_dechirp_apparent_acceleration_m_s2", f"{tok}_dechirp_flag"])
            series.extend([np.asarray(dechirp.apparent_acceleration_m_s2, dtype=np.float64), dechirp.flags])
            ch_meta["dechirp"] = {
                "method": "local_real_voltage_linear_chirp",
                "window_samples": dechirp.settings.window_samples,
                "acceleration_column": f"{tok}_dechirp_apparent_acceleration_m_s2",
                "flag_column": f"{tok}_dechirp_flag",
            }
        per_channel[name] = ch_meta

    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(fields)
            for idx in range(time_values.size):
                row = [_csv_cell(float(time_values[idx]))]
                for item in series:
                    if isinstance(item, tuple):
                        row.append(item[idx])
                    else:
                        row.append(_csv_cell(float(item[idx])))
                writer.writerow(row)
    except OSError as exc:
        raise ResultExportWriteError(f"Could not write {path.name}: {exc}") from exc
    return per_channel


def _write_bundle_detail_csv(
    path: Path,
    *,
    channel_name: str,
    analysis: ChannelAnalysis,
    analysis_mode: ResultAnalysisMode,
) -> None:
    detection = analysis.signal_detection_result
    relative = event_relative_time_s(detection.time_s, detection.manual_event_reference_time_s)
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_DETAIL_CSV_FIELDS, lineterminator="\n")
            writer.writeheader()
            for idx in range(detection.time_s.size):
                origin = analysis.velocity_origins[idx]
                writer.writerow(
                    {
                        "time_s": _csv_cell(float(detection.time_s[idx])),
                        "time_from_event_s": _csv_cell(float(relative[idx])),
                        "coarse_peak_frequency_hz": _csv_cell(float(detection.coarse_peak_frequency_hz[idx])),
                        "refined_frequency_hz": _csv_cell(float(detection.refined_frequency_hz[idx])),
                        "working_frequency_hz": _csv_cell(float(analysis.continuous_frequency_hz[idx])),
                        "apparent_velocity_m_s": _csv_cell(float(detection.apparent_velocity_m_s[idx])),
                        "angle_corrected_apparent_velocity_m_s": _csv_cell(
                            float(analysis.angle_corrected_apparent_velocity_m_s[idx])
                        ),
                        "corrected_velocity_m_s": _csv_cell(float(analysis.corrected_velocity_m_s[idx])),
                        "continuous_apparent_velocity_m_s": _csv_cell(
                            float(analysis.continuous_apparent_velocity_m_s[idx])
                        ),
                        "continuous_angle_corrected_apparent_velocity_m_s": _csv_cell(
                            float(analysis.continuous_angle_corrected_apparent_velocity_m_s[idx])
                        ),
                        "continuous_corrected_velocity_m_s": _csv_cell(
                            float(analysis.continuous_corrected_velocity_m_s[idx])
                        ),
                        "display_velocity_m_s": _csv_cell(float(analysis.plot_velocity_m_s[idx])),
                        "ridge_quality_flag": analysis.ridge_result.quality_flags[idx].value,
                        "ridge_refinement_status": detection.refinement_statuses[idx].value,
                        "ridge_selection_origin": analysis.automatic_ridge_selection_result.origins[idx],
                        "selected_candidate_rank": str(
                            analysis.automatic_ridge_selection_result.selected_candidate_rank[idx]
                        ),
                        "signal_state": detection.signal_states[idx].value,
                        "working_source": analysis.working_source[idx].value,
                        "velocity_origin": origin,
                        "is_pre_event_display_only": str(origin == PRE_EVENT_DISPLAY_ORIGIN).lower(),
                        "channel": channel_name,
                        "analysis_mode": analysis_mode.value,
                    }
                )
    except OSError as exc:
        raise ResultExportWriteError(f"Could not write {path.name}: {exc}") from exc


def _build_quality_and_warnings(
    channels: Mapping[str, ChannelAnalysis],
    *,
    extra_warnings: tuple[str, ...],
) -> tuple[dict[str, dict[str, object]], list[str]]:
    quality_map: dict[str, dict[str, object]] = {}
    warnings_list: list[str] = list(extra_warnings)
    for name, analysis in channels.items():
        detection = analysis.signal_detection_result
        states = detection.signal_states
        counts = Counter(states)
        measured = counts[SignalState.MEASURED]
        total = len(states)
        db = detection.peak_to_background_db[[state is SignalState.MEASURED for state in states]]
        finite_db = db[np.isfinite(db)]
        ch_warnings: list[str] = []
        if measured == 0:
            ch_warnings.append("No frames passed the formal signal quality gate.")
        for state in SignalState:
            if state not in {SignalState.MEASURED, SignalState.OUTSIDE_ANALYSIS_WINDOW} and counts[state]:
                ch_warnings.append(f"{counts[state]} frame(s) flagged {state.value}.")
        wavelength_warning = analysis.velocity_correction_result.wavelength_validation_message
        if wavelength_warning is not None:
            ch_warnings.append(wavelength_warning)
        for warning in ch_warnings:
            prefixed = f"{name}: {warning}"
            if prefixed not in warnings_list:
                warnings_list.append(prefixed)
        quality_map[name] = {
            "total_frames": total,
            "measured": measured,
            "measured_fraction": measured / total if total else 0.0,
            **{state.value: counts[state] for state in SignalState if state is not SignalState.MEASURED},
            "continuity_reselection_count": len(
                analysis.automatic_ridge_selection_result.reselected_frame_indices
            ),
            "primary_event_candidate_time_s": analysis.stream_event_candidates.primary_candidate_time_s,
            "median_peak_to_background_db": float(np.median(finite_db)) if finite_db.size else None,
            "max_peak_to_background_db": float(finite_db.max()) if finite_db.size else None,
            "warnings": ch_warnings,
        }
    return quality_map, warnings_list


def _build_run_summary(
    *,
    options: ResultBundleOptions,
    timestamp: datetime,
    time_column: str,
    channels: Mapping[str, ChannelAnalysis],
    tokens: Mapping[str, str],
    display_curves: Mapping[str, DisplayVelocityCurveResult],
    quality_map: Mapping[str, Mapping[str, object]],
    warnings: list[str],
    accel_meta: Mapping[str, Any],
    outputs: Mapping[str, object],
) -> dict[str, Any]:
    first_analysis = next(iter(channels.values()))
    source_path = options.source_path or first_analysis.stft_result.source_path
    correction_meta = velocity_correction_metadata(first_analysis.velocity_correction_result)
    stft_meta = {
        name: {
            "window_name": analysis.stft_result.window_name,
            "window_length_samples": analysis.stft_result.window_length_samples,
            "overlap_samples": analysis.stft_result.overlap_samples,
            "hop_samples": analysis.stft_result.hop_samples,
            "nfft": analysis.stft_result.nfft,
            "sample_rate_hz": analysis.stft_result.sample_rate_hz,
            "search_minimum_frequency_hz": analysis.ridge_result.minimum_frequency_hz,
            "search_maximum_frequency_hz": analysis.ridge_result.maximum_frequency_hz,
        }
        for name, analysis in channels.items()
    }
    display_processing = {
        name: {
            "measured_frames": curve.measured_frames,
            "total_frames": curve.total_frames,
            "smoothing": "3-frame [1,2,1]/4 interior binomial (endpoints preserved)"
            if curve.smoothing_applied else "none",
            "smoothing_applied": curve.smoothing_applied,
            "max_bridge_gap_frames": options.max_bridge_gap_frames,
            "bridged_gap_count": curve.bridged_gap_count,
            "bridged_frame_count": curve.bridged_frame_count,
            "bridged_intervals": [[s, e] for s, e in curve.bridged_intervals],
            "pre_event_enabled": curve.pre_event_enabled,
            "pre_event_time_s": curve.pre_event_time_s,
            "pre_event_source": curve.pre_event_source,
            "pre_event_display_velocity_m_s": options.pre_event_display_velocity_m_s
            if curve.pre_event_enabled else None,
        }
        for name, curve in display_curves.items()
    }
    document: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "software_version": options.dps_studio_version,
        "dps_studio_version": options.dps_studio_version,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "analysis_mode": options.analysis_mode.value,
        "analysis_profile_name": options.analysis_profile_name,
        "time_origin": options.time_origin.value,
        "time_column": time_column,
        "source_path": str(source_path) if source_path is not None else None,
        "source_sha256": options.source_sha256,
        "input_unchanged": True if options.source_sha256 is not None else None,
        "channels": list(channels),
        "channel_tokens": dict(tokens),
        "input_format": dict(options.input_format),
        "experimental_conditions": dict(options.experimental_conditions),
        "analysis_parameters": dict(options.analysis_parameters),
        "stft_and_ridge": stft_meta,
        "velocity_correction": correction_meta,
        "event_reference": {
            "event_reference_time_s": first_analysis.signal_detection_result.manual_event_reference_time_s,
            "event_reference_source": options.event_reference_source,
            "event_time_source": options.event_time_source,
        },
        "auto_band_retry": dict(options.auto_band_retry),
        "display_processing": display_processing,
        "quality": dict(quality_map),
        "warnings": warnings,
        "outputs": dict(outputs),
    }
    if accel_meta:
        document["acceleration_export"] = dict(accel_meta)
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        raise ResultExportWriteError(f"Could not write {path.name}: {exc}") from exc
