"""Non-overwriting CSV and JSON export of existing formal workflow results."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.core.export.models import (
    ExportTimeOrigin,
    ExportedChannelResult,
    ResultAnalysisMode,
    ResultExportOptions,
    ResultExportReport,
    ResultExportValidationError,
    ResultExportWriteError,
)
from dps_studio.core.export.time_coordinates import event_relative_time_s
from dps_studio.core.physics import velocity_correction_metadata
from dps_studio.core.workflow import PRE_EVENT_DISPLAY_ORIGIN
from dps_studio.core.workflow.models import ChannelAnalysis


EXPORT_SCHEMA_VERSION = "pdv-studio-formal-result-v6"
_DETAIL_CSV_FIELDS = (
    "time_s",
    "time_from_event_s",
    "coarse_peak_frequency_hz",
    "refined_frequency_hz",
    "apparent_velocity_m_s",
    "angle_corrected_apparent_velocity_m_s",
    "corrected_velocity_m_s",
    "display_velocity_m_s",
    "ridge_quality_flag",
    "ridge_refinement_status",
    "ridge_selection_origin",
    "selected_candidate_rank",
    "signal_state",
    "velocity_origin",
    "is_pre_event_display_only",
    "channel",
    "analysis_mode",
)
_INVALID_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
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
_PDV_CHANNEL_RE = re.compile(r"^pdv_channel_(\d+)$")
_MODE_FILENAME_TOKENS = {
    ResultAnalysisMode.AUTOMATIC: "auto",
    ResultAnalysisMode.GUIDED: "guided",
}


@dataclass(frozen=True, slots=True)
class _ChannelExportPlan:
    """Final file names allocated for one channel without overwriting."""

    channel_name: str
    simple_csv_name: str
    detail_csv_name: str
    metadata_name: str


def export_formal_results(options: ResultExportOptions) -> ResultExportReport:
    """Write simple CSV, diagnostic CSV, and metadata JSON for current results.

    The public API consumes immutable ``ChannelAnalysis`` instances. It neither
    runs analysis nor alters the supplied objects. Final files are published
    directly in the user-selected directory only after their complete staged
    set has been written. Existing files are never overwritten.
    """
    if not isinstance(options, ResultExportOptions):
        raise TypeError("options must be a ResultExportOptions instance.")
    _validate_options_for_write(options)
    output_directory = _validated_output_directory(options)
    timestamp = datetime.now(UTC)
    plans = _plan_export_files(output_directory, options)
    staging_directory = _create_staging_directory(output_directory, timestamp)
    published_paths: list[Path] = []
    try:
        exported_channels = _write_staged_results(
            staging_directory,
            output_directory,
            options,
            timestamp,
            plans,
        )
        _publish_staged_results(
            staging_directory,
            output_directory,
            plans,
            published_paths,
        )
    except Exception as exc:
        _cleanup_failed_export(staging_directory, published_paths)
        if isinstance(exc, (ResultExportValidationError, ResultExportWriteError)):
            raise
        raise ResultExportWriteError(
            f"Could not write formal result export in {output_directory}: {exc}"
        ) from exc
    return ResultExportReport(
        output_directory=output_directory,
        analysis_mode=options.analysis_mode,
        exported_channels=tuple(exported_channels),
    )


def _validate_options_for_write(options: ResultExportOptions) -> None:
    for channel_name, analysis in options.channel_analyses.items():
        _validate_channel_filename(channel_name)
        _validate_analysis_arrays(channel_name, analysis)
        reference_time_s = (
            analysis.signal_detection_result.manual_event_reference_time_s
        )
        if (reference_time_s is None) != (
            options.event_reference_source is None
        ):
            raise ResultExportValidationError(
                "event_reference_source must be present exactly when the exported "
                f"event reference is present for {channel_name!r}."
            )
        if (
            options.time_origin is ExportTimeOrigin.EVENT
            and reference_time_s is None
        ):
            raise ResultExportValidationError(
                "Event-relative export requires a formally adopted event "
                f"reference for {channel_name!r}."
            )


def _validated_output_directory(options: ResultExportOptions) -> Path:
    output_directory = options.output_directory.expanduser()
    try:
        resolved_output = output_directory.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResultExportWriteError(
            f"Export output directory does not exist: {output_directory}"
        ) from exc
    if not resolved_output.is_dir():
        raise ResultExportWriteError(
            f"Export output path is not a directory: {resolved_output}"
        )
    if _is_within_raw_data_directory(resolved_output):
        raise ResultExportWriteError(
            "Export output directory is inside data/raw and cannot receive "
            f"result files: {resolved_output}"
        )
    for protected_path in options.protected_output_directories:
        try:
            resolved_protected = protected_path.expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ResultExportValidationError(
                f"Invalid protected output directory: {protected_path}"
            ) from exc
        if (
            resolved_output == resolved_protected
            or resolved_protected in resolved_output.parents
        ):
            raise ResultExportWriteError(
                "Export output directory is protected and cannot receive result files: "
                f"{resolved_output}"
            )
    return resolved_output


def _is_within_raw_data_directory(path: Path) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    return any(
        parts[index : index + 2] == ("data", "raw")
        for index in range(len(parts) - 1)
    )


def _plan_export_files(
    output_directory: Path,
    options: ResultExportOptions,
) -> tuple[_ChannelExportPlan, ...]:
    """Allocate one collision-free three-file group for every requested channel."""
    plans: list[_ChannelExportPlan] = []
    allocated_names: set[str] = set()
    for channel_name, analysis in options.channel_analyses.items():
        source_stem = _source_stem(options, analysis)
        channel_token = _channel_filename_token(channel_name)
        mode_token = _MODE_FILENAME_TOKENS[options.analysis_mode]
        base_stem = f"{source_stem}_{channel_token}_{mode_token}"
        plan = _allocate_file_group(output_directory, base_stem, allocated_names)
        plans.append(
            _ChannelExportPlan(
                channel_name=channel_name,
                simple_csv_name=plan[0],
                detail_csv_name=plan[1],
                metadata_name=plan[2],
            )
        )
        allocated_names.update(plan)
    return tuple(plans)


def _source_stem(options: ResultExportOptions, analysis: ChannelAnalysis) -> str:
    """Use the real source path, with a deliberate fallback when unavailable."""
    source_path = _effective_source_path(options, analysis)
    if source_path is None:
        return "unsourced"
    normalized = _safe_filename_token(source_path.stem)
    return normalized or "unsourced"


def _effective_source_path(
    options: ResultExportOptions,
    analysis: ChannelAnalysis,
) -> Path | None:
    return options.source_path or analysis.stft_result.source_path


def _channel_filename_token(channel_name: str) -> str:
    match = _PDV_CHANNEL_RE.fullmatch(channel_name)
    if match is not None:
        return f"ch{match.group(1)}"
    normalized = _safe_filename_token(channel_name)
    if not normalized:
        raise ResultExportValidationError(
            f"Channel name cannot produce an export filename: {channel_name!r}"
        )
    return normalized


def _safe_filename_token(value: str) -> str:
    """Retain readable source/channel identity in a Windows-safe filename token."""
    normalized = value.strip()
    normalized = "".join(
        "-" if character in _INVALID_FILENAME_CHARACTERS or ord(character) < 32 else character
        for character in normalized
    )
    normalized = re.sub(r"\s+", "_", normalized).strip(". _-")
    return normalized[:100]


def _allocate_file_group(
    output_directory: Path,
    base_stem: str,
    allocated_names: set[str],
) -> tuple[str, str, str]:
    for suffix in range(1, 10_000):
        suffix_text = "" if suffix == 1 else f"_{suffix}"
        stem = f"{base_stem}{suffix_text}"
        names = (
            f"{stem}.csv",
            f"{stem}_detail.csv",
            f"{stem}.metadata.json",
        )
        if any(name in allocated_names for name in names):
            continue
        if any(_path_exists_or_is_symlink(output_directory / name) for name in names):
            continue
        return names
    raise ResultExportWriteError(
        "Could not allocate a unique non-overwriting formal result file group."
    )


def _path_exists_or_is_symlink(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _create_staging_directory(output_directory: Path, timestamp: datetime) -> Path:
    base_name = timestamp.strftime(".pdv_studio_export_staging_%Y%m%dT%H%M%SZ")
    for suffix in range(1, 10_000):
        name = base_name if suffix == 1 else f"{base_name}_{suffix}"
        candidate = output_directory / name
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            raise ResultExportWriteError(
                f"Export output directory is not writable: {output_directory}"
            ) from exc
        return candidate
    raise ResultExportWriteError("Could not allocate a temporary formal export directory.")


def _write_staged_results(
    staging_directory: Path,
    output_directory: Path,
    options: ResultExportOptions,
    timestamp: datetime,
    plans: tuple[_ChannelExportPlan, ...],
) -> list[ExportedChannelResult]:
    exported_channels: list[ExportedChannelResult] = []
    for plan in plans:
        analysis = options.channel_analyses[plan.channel_name]
        row_indices = _export_row_indices(analysis, options)
        row_count = _write_simple_csv(
            staging_directory / plan.simple_csv_name,
            analysis,
            options,
            row_indices,
        )
        _write_detail_csv(
            staging_directory / plan.detail_csv_name,
            plan.channel_name,
            analysis,
            options,
            row_indices,
        )
        metadata = _metadata_document(
            plan.channel_name,
            analysis,
            options,
            timestamp,
            plan.simple_csv_name,
            plan.detail_csv_name,
            row_count,
        )
        _write_json(staging_directory / plan.metadata_name, metadata)
        exported_channels.append(
            ExportedChannelResult(
                channel_name=plan.channel_name,
                csv_path=output_directory / plan.simple_csv_name,
                detail_csv_path=output_directory / plan.detail_csv_name,
                metadata_path=output_directory / plan.metadata_name,
                exported_row_count=row_count,
            )
        )
    return exported_channels


def _export_row_indices(
    analysis: ChannelAnalysis,
    options: ResultExportOptions,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, origin in enumerate(analysis.velocity_origins)
        if options.include_pre_event_display_rows or origin != PRE_EVENT_DISPLAY_ORIGIN
    )


def _write_simple_csv(
    path: Path,
    analysis: ChannelAnalysis,
    options: ResultExportOptions,
    row_indices: tuple[int, ...],
) -> int:
    """Write the user-facing time--display-velocity CSV without recalculation."""
    detection = analysis.signal_detection_result
    relative_time_s = event_relative_time_s(
        detection.time_s,
        detection.manual_event_reference_time_s,
    )
    time_column = _simple_time_column(options.time_origin)
    time_values = (
        relative_time_s
        if options.time_origin is ExportTimeOrigin.EVENT
        else detection.time_s
    )
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(time_column, "display_velocity_m_s"),
                lineterminator="\n",
            )
            writer.writeheader()
            for index in row_indices:
                writer.writerow(
                    {
                        time_column: _csv_float(time_values[index]),
                        "display_velocity_m_s": _csv_float(
                            analysis.display_velocity_m_s[index]
                        ),
                    }
                )
    except OSError as exc:
        raise ResultExportWriteError(
            f"Could not write simple CSV file {path.name}: {exc}"
        ) from exc
    return len(row_indices)


def _write_detail_csv(
    path: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    options: ResultExportOptions,
    row_indices: tuple[int, ...],
) -> None:
    detection = analysis.signal_detection_result
    relative_time_s = event_relative_time_s(
        detection.time_s,
        detection.manual_event_reference_time_s,
    )
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=_DETAIL_CSV_FIELDS,
                lineterminator="\n",
            )
            writer.writeheader()
            for index in row_indices:
                origin = analysis.velocity_origins[index]
                display_only = origin == PRE_EVENT_DISPLAY_ORIGIN
                writer.writerow(
                    {
                        "time_s": _csv_float(detection.time_s[index]),
                        "time_from_event_s": _csv_float(relative_time_s[index]),
                        "coarse_peak_frequency_hz": _csv_float(
                            detection.coarse_peak_frequency_hz[index]
                        ),
                        "refined_frequency_hz": _csv_float(
                            detection.refined_frequency_hz[index]
                        ),
                        "apparent_velocity_m_s": _csv_float(
                            detection.apparent_velocity_m_s[index]
                        ),
                        "angle_corrected_apparent_velocity_m_s": _csv_float(
                            analysis.angle_corrected_apparent_velocity_m_s[index]
                        ),
                        "corrected_velocity_m_s": _csv_float(
                            analysis.corrected_velocity_m_s[index]
                        ),
                        "display_velocity_m_s": _csv_float(
                            analysis.display_velocity_m_s[index]
                        ),
                        "ridge_quality_flag": analysis.ridge_result.quality_flags[
                            index
                        ].value,
                        "ridge_refinement_status": detection.refinement_statuses[
                            index
                        ].value,
                        "ridge_selection_origin": (
                            analysis.automatic_ridge_selection_result.origins[
                                index
                            ].value
                        ),
                        "selected_candidate_rank": int(
                            analysis.automatic_ridge_selection_result.selected_candidate_rank[
                                index
                            ]
                        ),
                        "signal_state": detection.signal_states[index].value,
                        "velocity_origin": origin,
                        "is_pre_event_display_only": str(display_only).lower(),
                        "channel": channel_name,
                        "analysis_mode": options.analysis_mode.value,
                    }
                )
    except OSError as exc:
        raise ResultExportWriteError(
            f"Could not write diagnostic CSV file {path.name}: {exc}"
        ) from exc


def _metadata_document(
    channel_name: str,
    analysis: ChannelAnalysis,
    options: ResultExportOptions,
    timestamp: datetime,
    simple_csv_name: str,
    detail_csv_name: str,
    exported_row_count: int,
) -> dict[str, Any]:
    detection = analysis.signal_detection_result
    stft = analysis.stft_result
    refined = analysis.refined_result
    source_path = _effective_source_path(options, analysis)
    display_only_count = sum(
        origin == PRE_EVENT_DISPLAY_ORIGIN for origin in analysis.velocity_origins
    )
    exported_display_only_count = (
        display_only_count if options.include_pre_event_display_rows else 0
    )
    measured_count = sum(
        state.value == "measured" for state in detection.signal_states
    )
    automatic_candidate_time_s = None
    compatibility_candidate_time_s = None
    if options.analysis_mode is ResultAnalysisMode.AUTOMATIC:
        automatic_candidate_time_s = (
            analysis.stream_event_candidates.primary_candidate_time_s
        )
        compatibility_candidate_time_s = detection.detected_event_candidate_time_s
    selection = analysis.automatic_ridge_selection_result
    automatic_selection_metadata: dict[str, Any] | None = None
    if options.analysis_mode is ResultAnalysisMode.AUTOMATIC:
        selection_config = selection.config
        automatic_selection_metadata = {
            "mode": selection_config.mode.value,
            "top_k_candidates": selection_config.top_k_candidates,
            "continuity_reselection_enabled": (
                selection_config.reselection_is_active
            ),
            "minimum_candidate_peak_to_background_db": (
                selection_config.minimum_candidate_peak_to_background_db
            ),
            "minimum_candidate_relative_to_strongest_db": (
                selection_config.minimum_candidate_relative_to_strongest_db
            ),
            "recovery_tolerance_hz": (
                selection.effective_recovery_tolerance_hz
            ),
            "recovery_tolerance_source": (
                "explicit_configuration"
                if selection_config.recovery_tolerance_hz is not None
                else "sample_rate_hz_divided_by_window_length_samples"
            ),
            "selection_method": selection.method,
            "continuity_reselection_count": len(
                selection.reselected_frame_indices
            ),
        }
    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "dps_studio_version": options.dps_studio_version,
        "exported_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "data_file": simple_csv_name,
        "detail_data_file": detail_csv_name,
        "source_file": str(source_path) if source_path is not None else None,
        "source_channel": channel_name,
        "analysis_mode": options.analysis_mode.value,
        "analysis_profile_name": options.analysis_profile_name,
        "analysis_time_range_s": {
            "start_time_s": detection.analysis_start_time_s,
            "end_time_s": detection.analysis_end_time_s,
        },
        "time_coordinate": {
            "absolute_time_preserved": True,
            "event_reference_time_s": detection.manual_event_reference_time_s,
            "export_time_origin": options.time_origin.value,
            "relative_time_definition": (
                "time_from_event_s = time_s - event_reference_time_s"
            ),
            "simple_csv_time_column": _simple_time_column(options.time_origin),
            "detail_csv_absolute_time_column": "time_s",
            "detail_csv_relative_time_column": "time_from_event_s",
        },
        "stft_configuration": {
            "window_name": stft.window_name,
            "window_length_samples": stft.window_length_samples,
            "overlap_samples": stft.overlap_samples,
            "hop_samples": stft.hop_samples,
            "nfft": stft.nfft,
            "sample_rate_hz": stft.sample_rate_hz,
            "scaling": stft.scaling,
            "one_sided": stft.is_one_sided,
            "detrend_applied": stft.detrend_applied,
            "boundary_padding_applied": stft.boundary_padding_applied,
        },
        "ridge_configuration": {
            "search_minimum_frequency_hz": (
                analysis.ridge_result.minimum_frequency_hz
            ),
            "search_maximum_frequency_hz": (
                analysis.ridge_result.maximum_frequency_hz
            ),
            "refinement_method": refined.refinement_method,
        },
        "quality_configuration": {
            "detection_method": detection.detection_method,
            "minimum_peak_to_background_db": (
                detection.detection_config.minimum_peak_to_background_db
            ),
            "minimum_peak_to_competitor_db": (
                detection.detection_config.minimum_peak_to_competitor_db
            ),
            "peak_exclusion_half_width_bins": (
                detection.detection_config.peak_exclusion_half_width_bins
            ),
            "minimum_consecutive_frames": (
                detection.detection_config.minimum_consecutive_frames
            ),
            "minimum_cycles_in_window": (
                detection.detection_config.minimum_cycles_in_window
            ),
            "enabled": detection.detection_config.enabled,
        },
        "vacuum_wavelength_m": (
            analysis.discrete_velocity_result.vacuum_wavelength_m
        ),
        "physics": {
            "vacuum_wavelength_m": (
                analysis.discrete_velocity_result.vacuum_wavelength_m
            ),
            "velocity_relation": "v_app=lambda0*f_b/2",
        },
        "velocity_correction": velocity_correction_metadata(
            analysis.velocity_correction_result
        ),
        "automatic_ridge_selection": automatic_selection_metadata,
        "automatic_event_candidate_time_s": automatic_candidate_time_s,
        "compatibility_event_candidate_time_s": compatibility_candidate_time_s,
        "event_reference_time_s": detection.manual_event_reference_time_s,
        "event_reference_source": options.event_reference_source,
        "pre_event_display": {
            "enabled": options.pre_event_display_enabled,
            "configured_velocity_m_s": options.pre_event_display_velocity_m_s,
            "included_in_csv": options.include_pre_event_display_rows,
            "formal_measurement_modified": False,
            "display_only_origin": PRE_EVENT_DISPLAY_ORIGIN,
        },
        "result_counts": {
            "stft_frame_count": int(stft.time_s.size),
            "exported_row_count": exported_row_count,
            "measured_frame_count": measured_count,
            "pre_event_display_only_frame_count": display_only_count,
            "exported_pre_event_display_only_row_count": exported_display_only_count,
            "signal_state_counts": dict(
                Counter(state.value for state in detection.signal_states)
            ),
            "ridge_quality_flag_counts": dict(
                Counter(flag.value for flag in analysis.ridge_result.quality_flags)
            ),
            "ridge_refinement_status_counts": dict(
                Counter(status.value for status in detection.refinement_statuses)
            ),
            "ridge_selection_origin_counts": dict(
                Counter(origin.value for origin in selection.origins)
            ),
        },
        "result_status": {
            "simple_csv_time_column": _simple_time_column(options.time_origin),
            "simple_csv_velocity_column": "display_velocity_m_s",
            "simple_csv_velocity_source": "display_velocity_m_s",
            "formal_measurement_column": "apparent_velocity_m_s",
            "angle_corrected_measurement_column": (
                "angle_corrected_apparent_velocity_m_s"
            ),
            "final_corrected_measurement_column": "corrected_velocity_m_s",
            "display_column": "display_velocity_m_s",
            "formal_measurement_preserved": True,
            "unreliable_formal_values_preserved_as_nan": True,
            "interpolation_or_smoothing_applied_by_export": False,
            "channel_fusion_applied_by_export": False,
        },
    }


def _simple_time_column(time_origin: ExportTimeOrigin) -> str:
    if time_origin is ExportTimeOrigin.EVENT:
        return "time_from_event_s"
    return "time_s"


def _write_json(path: Path, document: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        raise ResultExportWriteError(
            f"Could not serialize metadata file {path.name}: {exc}"
        ) from exc


def _publish_staged_results(
    staging_directory: Path,
    output_directory: Path,
    plans: tuple[_ChannelExportPlan, ...],
    published_paths: list[Path],
) -> None:
    """Publish fully written files using hard links, which refuse overwrites."""
    for plan in plans:
        for file_name in (
            plan.simple_csv_name,
            plan.detail_csv_name,
            plan.metadata_name,
        ):
            staged_path = staging_directory / file_name
            final_path = output_directory / file_name
            try:
                os.link(staged_path, final_path)
            except FileExistsError as exc:
                raise ResultExportWriteError(
                    "A result file appeared during export; no existing file was "
                    f"overwritten: {final_path.name}"
                ) from exc
            except OSError as exc:
                raise ResultExportWriteError(
                    f"Could not publish formal result file {final_path.name}: {exc}"
                ) from exc
            published_paths.append(final_path)
            staged_path.unlink()
    staging_directory.rmdir()


def _validate_analysis_arrays(channel_name: str, analysis: ChannelAnalysis) -> None:
    frame_count = analysis.stft_result.time_s.size
    detection = analysis.signal_detection_result
    sequences = (
        ("coarse_peak_frequency_hz", detection.coarse_peak_frequency_hz),
        ("refined_frequency_hz", detection.refined_frequency_hz),
        ("apparent_velocity_m_s", detection.apparent_velocity_m_s),
        ("display_velocity_m_s", analysis.display_velocity_m_s),
        ("ridge_quality_flags", analysis.ridge_result.quality_flags),
        ("ridge_refinement_statuses", detection.refinement_statuses),
        ("signal_states", detection.signal_states),
        ("velocity_origins", analysis.velocity_origins),
        (
            "angle_corrected_apparent_velocity_m_s",
            analysis.angle_corrected_apparent_velocity_m_s,
        ),
        ("corrected_velocity_m_s", analysis.corrected_velocity_m_s),
        (
            "ridge_selection_origins",
            analysis.automatic_ridge_selection_result.origins,
        ),
        (
            "selected_candidate_rank",
            analysis.automatic_ridge_selection_result.selected_candidate_rank,
        ),
    )
    for field_name, values in sequences:
        if len(values) != frame_count:
            raise ResultExportValidationError(
                f"Channel {channel_name!r} has incomplete {field_name} data."
            )
    if not np.array_equal(detection.time_s, analysis.stft_result.time_s):
        raise ResultExportValidationError(
            f"Channel {channel_name!r} has mismatched STFT and formal result times."
        )


def _validate_channel_filename(channel_name: str) -> None:
    if (
        len(channel_name) > 100
        or channel_name in {".", ".."}
        or channel_name[-1] in {".", " "}
        or any(character in _INVALID_FILENAME_CHARACTERS for character in channel_name)
        or any(ord(character) < 32 for character in channel_name)
        or channel_name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise ResultExportValidationError(
            f"Channel name cannot be used safely in an export filename: {channel_name!r}"
        )


def _csv_float(value: object) -> str:
    converted = float(value)  # type: ignore[arg-type]
    if math.isnan(converted):
        return "nan"
    if not math.isfinite(converted):
        raise ResultExportValidationError("Result arrays must not contain infinity.")
    return format(converted, ".17g")


def _cleanup_failed_export(
    staging_directory: Path,
    published_paths: list[Path],
) -> None:
    for path in reversed(published_paths):
        try:
            path.unlink()
        except OSError:
            pass
    try:
        shutil.rmtree(staging_directory)
    except OSError:
        # The original write failure remains more informative. A remaining
        # hidden staging directory contains no published result file group.
        pass


__all__ = ["EXPORT_SCHEMA_VERSION", "export_formal_results"]
