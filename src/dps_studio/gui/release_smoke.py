"""Explicit release verification through the existing public analysis APIs."""

from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import dps_studio.core.workflow.analysis as workflow_analysis

from dps_studio import __version__
from dps_studio.core.export import ResultAnalysisMode, ResultExportOptions, export_formal_results
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.workflow import analyze_profile, load_workflow_config
from dps_studio.runtime_paths import application_resource_path, application_resource_root


def smoke_options(arguments: Sequence[str]) -> tuple[Path | None, Path | None]:
    """Read hidden test arguments without altering ordinary Qt arguments."""
    values: list[Path | None] = []
    for flag in ("--startup-smoke-test", "--analysis-smoke-input"):
        if flag not in arguments:
            values.append(None)
            continue
        index = arguments.index(flag) + 1
        if index >= len(arguments) or arguments[index].startswith("--"):
            raise ValueError(f"{flag} requires a path")
        values.append(Path(arguments[index]))
    if values[1] is not None and values[0] is None:
        raise ValueError("--analysis-smoke-input requires --startup-smoke-test")
    return values[0], values[1]


def loaded_runtime_paths() -> dict[str, str]:
    """Query Windows for the actual DLLs loaded by this GUI process."""
    if sys.platform == "darwin":
        from dps_studio.gui.release_smoke_macos import loaded_runtime_paths as darwin_paths

        return darwin_paths()
    import PySide6
    import shiboken6
    from scipy._lib import _ccallback_c  # type: ignore[import-untyped]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    paths = {
        "PySide6": str(PySide6.__file__), "shiboken6": str(shiboken6.__file__),
        "scipy._lib._ccallback_c": str(_ccallback_c.__file__),
    }
    for name in (
        "QtCore.pyd", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
        "Shiboken.pyd", "shiboken6.abi3.dll", "qwindows.dll",
        Path(_ccallback_c.__file__).name,
    ):
        module = kernel.GetModuleHandleW(name)
        if not module:
            raise RuntimeError(f"Required runtime is not loaded: {name}")
        buffer = ctypes.create_unicode_buffer(32768)
        if not kernel.GetModuleFileNameW(module, buffer, len(buffer)):
            raise ctypes.WinError(ctypes.get_last_error())
        paths[name] = buffer.value
    return paths


def _file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _csv_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return tuple(reader.fieldnames or ()), list(reader)


def run_analysis_smoke(source: Path, output_directory: Path) -> dict[str, Any]:
    """Analyze the documented three-column s/V example, without GUI automation.

    The caller supplies a copy of docs/原始数据.csv. Units and mapping are the
    documented input selections, not inferred from converted numerical arrays.
    """
    output_directory.mkdir(parents=True, exist_ok=False)
    before = _file_hash(source)
    config = load_workflow_config(
        application_resource_path("configs", "pdv_studio_defaults.toml"),
        repository_root=application_resource_root(),
    )
    loaded = read_delimited_signals(
        source, time_column=0, voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        original_time_unit="s", original_voltage_units={"pdv_channel_1": "V", "pdv_channel_2": "V"},
    )
    analyses = analyze_profile(
        loaded.records, profile=config.analysis.default_profile,
        analysis_start_time_s=max(record.start_time_s for record in loaded.records.values()),
        analysis_end_time_s=min(record.end_time_s for record in loaded.records.values()),
        vacuum_wavelength_m=config.analysis.vacuum_wavelength_m,
        detection_config=config.quality.signal_detection, event_candidate_config=config.event_candidate,
        automatic_ridge_selection_config=config.automatic_ridge_selection,
        velocity_correction_config=config.velocity_correction,
        background_guard_window_scale=config.quality.background_guard_window_scale,
        minimum_background_bin_count=config.quality.minimum_background_bin_count,
    )
    options = ResultExportOptions(
        output_directory, ResultAnalysisMode.AUTOMATIC, analyses,
        analysis_profile_name=config.analysis.default_profile.profile_id.value,
    )
    continuous = export_formal_results(options)
    quality = export_formal_results(replace(options, quality_passed_only=True))
    channels: dict[str, Any] = {}
    for first, second in zip(continuous.exported_channels, quality.exported_channels, strict=True):
        columns, rows = _csv_rows(first.csv_path)
        quality_columns, quality_rows = _csv_rows(second.csv_path)
        detail_columns, detail_rows = _csv_rows(first.detail_csv_path)
        _, quality_detail_rows = _csv_rows(second.detail_csv_path)
        document = json.loads(first.metadata_path.read_text(encoding="utf-8"))
        quality_document = json.loads(second.metadata_path.read_text(encoding="utf-8"))
        analysis = analyses[first.channel_name]
        if columns != ("time_s", "display_velocity_m_s") or quality_columns != (
            "time_s", "corrected_velocity_m_s"
        ):
            raise RuntimeError("Release export lost the two-column schema")
        for metadata in (document, quality_document):
            if not metadata["software_version"] == metadata["dps_studio_version"] == __version__:
                raise RuntimeError("Release export version differs")
            provenance = metadata["input_provenance"]
            expected_column = loaded.voltage_column_indices[first.channel_name]
            if not (
                provenance["time_column_index"] == 0
                and provenance["voltage_column_index"] == expected_column
                and provenance["original_time_unit"] == "s"
                and provenance["original_voltage_unit"] == "V"
                and provenance["time_scale"] == provenance["voltage_scale"] == 1.0
            ):
                raise RuntimeError("Release export lost the explicit import provenance")
        if document["simple_export"]["quality_filtering_applied"] or not (
            quality_document["simple_export"]["quality_filtering_applied"]
            and quality_document["simple_export"]["time_series_may_have_gaps"]
            and "quality_passed" in second.csv_path.name
        ):
            raise RuntimeError("Release export filtering mode differs")
        values = np.asarray([float(row["display_velocity_m_s"]) for row in rows])
        if not np.array_equal(values, analysis.plot_velocity_m_s, equal_nan=True):
            raise RuntimeError("Continuous CSV differs from the display trajectory")
        expected_quality = [
            row for row in detail_rows
            if row["signal_state"] == "measured" and row["is_pre_event_display_only"] == "false"
            and np.isfinite(float(row["corrected_velocity_m_s"]))
        ]
        if len(quality_rows) != len(expected_quality) or not quality_rows:
            raise RuntimeError("Release quality filtering has an unexpected row set")
        for row, expected in zip(quality_rows, expected_quality, strict=True):
            if row["time_s"] != expected["time_s"] or row["corrected_velocity_m_s"] != expected["corrected_velocity_m_s"]:
                raise RuntimeError("Quality CSV differs from the formal corrected trajectory")
        if len(rows) != len(detail_rows) or len(quality_detail_rows) != len(detail_rows):
            raise RuntimeError("Release detailed export lost diagnostic rows")
        if not {"signal_state", "ridge_quality_flag", "working_source"}.issubset(detail_columns):
            raise RuntimeError("Release detailed export lost quality diagnostics")
        channels[first.channel_name] = {
            "continuous_rows": len(rows), "quality_rows": len(quality_rows),
            "detail_rows": len(detail_rows), "csv_columns": columns,
            "quality_csv_columns": quality_columns, "version": document["software_version"],
            "input_provenance": document["input_provenance"],
            "continuous_csv": str(first.csv_path), "quality_csv": str(second.csv_path),
            "detail_csv": str(first.detail_csv_path), "metadata_json": str(first.metadata_path),
        }
    if before != _file_hash(source):
        raise RuntimeError("Analysis smoke changed its source input")
    return {
        "status": "PASS", "execution": "public core analysis inside the release EXE GUI event loop",
        "input_sha256": before, "input_unchanged": True, "sample_count": loaded.row_count,
        "profile": config.analysis.default_profile.profile_id.value,
        "core_module": str(workflow_analysis.__file__), "channels": channels,
    }
