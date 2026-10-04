"""Auditable 1-D numerical contract using public, unchanged Production APIs.

No spectrum is serialized. NaNs are JSON null; masks, bin identities, quality
and event selections are compared independently from floating point tolerances.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import platform
import tomllib
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio import __version__
from dps_studio.core.export import ResultAnalysisMode, ResultExportOptions, export_formal_results
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.workflow import ChannelAnalysis, analyze_profile, load_workflow_config
from dps_studio.runtime_paths import application_resource_path, application_resource_root


TOLERANCES = {
    "frequency_grid_hz": (1e-12, 1e-6),
    "ridge_frequency_hz": (1e-12, 1e-6),
    "refined_frequency_hz": (1e-9, 1e-3),
    "apparent_velocity_m_s": (1e-9, 1e-5),
    "corrected_velocity_m_s": (1e-9, 1e-5),
    "time_s": (0.0, 0.0),
}
DEPENDENCIES = (
    "numpy", "scipy", "pandas", "matplotlib", "PySide6", "shiboken6",
    "pyqtgraph", "pydantic", "pyinstaller", "pyinstaller-hooks-contrib",
)


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def lf_text_hash(path: Path) -> str:
    """Audit only Git's CRLF/LF checkout difference; never rewrite the source."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def float_values(values: NDArray[np.float64]) -> list[float | None]:
    if np.any(np.isinf(values)):
        raise RuntimeError("Infinite numerical value in release reference")
    return [float(value) if np.isfinite(value) else None for value in values]


def runs(values: list[Any]) -> list[list[Any]]:
    """Lossless run-length encoding of discrete per-frame decisions."""
    result: list[list[Any]] = []
    for value in values:
        if result and result[-1][0] == value:
            result[-1][1] += 1
        else:
            result.append([value, 1])
    return result


def synthetic_record() -> SignalRecord:
    """Explicit deterministic synthetic fixture, never presented as raw data.

    Fs=40 GHz, 8192 samples, a silent prefix and a chirped beat. No random
    generator, file fallback, filtering, smoothing or interpolation is used.
    """
    time = np.arange(8192, dtype=np.float64) / 40e9
    phase = 2 * np.pi * (450e6 * time + 0.5 * 1e15 * time**2)
    voltage = np.cos(phase) + 0.001 * np.cos(2 * np.pi * 1.3e9 * time)
    voltage[:2048] = 0.0
    return SignalRecord(time_s=time, voltage_v=voltage,
                        metadata={"fixture": "deterministic synthetic chirp"})


def channel_snapshot(analysis: ChannelAnalysis) -> dict[str, Any]:
    detection = analysis.signal_detection_result
    vectors = {
        "time_s": analysis.stft_result.time_s,
        "frequency_grid_hz": analysis.stft_result.frequency_hz,
        "ridge_frequency_hz": analysis.ridge_result.frequency_hz,
        "refined_frequency_hz": detection.refined_frequency_hz,
        "apparent_velocity_m_s": detection.apparent_velocity_m_s,
        "corrected_velocity_m_s": analysis.velocity_correction_result.corrected_velocity_m_s,
    }
    states = [state.value for state in detection.signal_states]
    candidates = analysis.stream_event_candidates
    return {
        "vectors": {name: float_values(value) for name, value in vectors.items()},
        "nan_masks": {name: runs(np.isnan(value).tolist()) for name, value in vectors.items()},
        "nan_counts": {name: int(np.isnan(value).sum()) for name, value in vectors.items()},
        "ridge_bins": runs(analysis.refined_result.discrete_frequency_bin_index.tolist()),
        "quality_flags": runs([flag.value for flag in analysis.ridge_result.quality_flags]),
        "signal_states": runs(states), "signal_state_counts": dict(Counter(states)),
        "refinement_statuses": runs([flag.value for flag in detection.refinement_statuses]),
        "selected_bins": runs(detection.peak_bin_index.tolist()),
        "working_source": runs([source.value for source in analysis.working_source]),
        "event_selection": {
            "primary_segment_id": candidates.primary_candidate_segment_id,
            "primary_time_s": candidates.primary_candidate_time_s,
            "detected_time_s": detection.detected_event_candidate_time_s,
            "detected_source": detection.detected_event_candidate_source,
            "segments": [
                [entry.segment.segment_id, entry.segment.start_frame_index,
                 entry.segment.end_frame_index, entry.candidate_eligible,
                 [reason.value for reason in entry.rejection_reasons]]
                for entry in candidates.segment_assessments
            ],
        },
        "stft": {
            key: getattr(analysis.stft_result, key) for key in (
                "window_name", "window_length_samples", "overlap_samples", "hop_samples",
                "nfft", "sample_rate_hz", "scaling", "is_one_sided", "detrend_applied",
                "boundary_padding_applied",
            )
        },
        "frame_count": int(detection.time_s.size),
    }


def csv_schema(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return {"columns": next(reader), "rows": sum(1 for _ in reader)}


def capture_snapshot(source: Path, output_directory: Path) -> dict[str, Any]:
    """Run real example and synthetic chain with the actual built-in defaults."""
    before = file_hash(source)
    output_path = output_directory.resolve()
    parts = [part.lower() for part in output_path.parts]
    if any(left == "data" and right == "raw" for left, right in zip(parts, parts[1:])):
        raise ValueError("Release reference output cannot be inside protected data/raw")
    output_directory.mkdir(parents=True, exist_ok=False)
    config_path = application_resource_path("configs", "pdv_studio_defaults.toml")
    config = load_workflow_config(config_path, repository_root=application_resource_root())
    loaded = read_delimited_signals(
        source, time_column=0, voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        original_time_unit="s", original_voltage_units={"pdv_channel_1": "V", "pdv_channel_2": "V"},
    )

    def analyze(records: Mapping[str, SignalRecord]) -> Mapping[str, ChannelAnalysis]:
        return analyze_profile(
            records, profile=config.analysis.default_profile,
            analysis_start_time_s=max(record.start_time_s for record in records.values()),
            analysis_end_time_s=min(record.end_time_s for record in records.values()),
            vacuum_wavelength_m=config.analysis.vacuum_wavelength_m,
            detection_config=config.quality.signal_detection,
            event_candidate_config=config.event_candidate,
            automatic_ridge_selection_config=config.automatic_ridge_selection,
            velocity_correction_config=config.velocity_correction,
            background_guard_window_scale=config.quality.background_guard_window_scale,
            minimum_background_bin_count=config.quality.minimum_background_bin_count,
        )

    analyses = analyze(dict(loaded.records))
    synthetic = synthetic_record()
    synthetic_analysis = analyze({"synthetic_chirp": synthetic})
    options = ResultExportOptions(
        output_directory, ResultAnalysisMode.AUTOMATIC, analyses,
        analysis_profile_name=config.analysis.default_profile.profile_id.value,
    )
    continuous = export_formal_results(options)
    quality = export_formal_results(replace(options, quality_passed_only=True))
    schema: dict[str, Any] = {}
    for first, second in zip(continuous.exported_channels, quality.exported_channels, strict=True):
        metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
        quality_metadata = json.loads(second.metadata_path.read_text(encoding="utf-8"))
        if metadata["software_version"] != __version__:
            raise RuntimeError("Export version does not match runtime")
        provenance = metadata["input_provenance"]
        schema[first.channel_name] = {
            "continuous": csv_schema(first.csv_path), "quality_passed": csv_schema(second.csv_path),
            "detailed": csv_schema(first.detail_csv_path),
            "json_keys": sorted(metadata), "quality_json_keys": sorted(quality_metadata),
            "version": metadata["software_version"],
            "input_units": [provenance["original_time_unit"], provenance["original_voltage_unit"]],
            "column_mapping": [provenance["time_column_index"], provenance["voltage_column_index"]],
            "scales": [provenance["time_scale"], provenance["voltage_scale"]],
        }
        if schema[first.channel_name]["continuous"]["columns"] != ["time_s", "display_velocity_m_s"]:
            raise RuntimeError("Continuous export must have two SI columns")
        if schema[first.channel_name]["quality_passed"]["columns"] != ["time_s", "corrected_velocity_m_s"]:
            raise RuntimeError("Quality export must have two SI columns")
    if before != file_hash(source):
        raise RuntimeError("Release verification modified its input")
    return {
        "contract_version": 1, "software_version": __version__, "input_sha256": before,
        "input_lf_sha256": lf_text_hash(source),
        "sample_count": loaded.row_count, "input_unchanged": True,
        "config_sha256": file_hash(config_path),
        "config_lf_sha256": lf_text_hash(config_path),
        "config": tomllib.loads(config_path.read_text(encoding="utf-8")),
        "profile": asdict(config.analysis.default_profile),
        "units": {"frequency": "Hz", "time": "s", "velocity": "m/s", "voltage": "V"},
        "channels": {name: channel_snapshot(value) for name, value in analyses.items()},
        "synthetic": {"description": "deterministic synthetic chirp; not experimental raw",
                      "sample_count": 8192, "sample_rate_hz": 40e9,
                      "silent_prefix_samples": 2048,
                      "channels": {name: channel_snapshot(value)
                                   for name, value in synthetic_analysis.items()}},
        "export_schema": schema,
    }


def compare_snapshots(reference: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on structure/decisions; apply only the audited float contract."""
    expected = reference.get("snapshot", reference)
    failures: list[str] = []
    metrics: dict[str, Any] = {}

    def compare(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            if left.keys() != right.keys():
                failures.append(f"{path}: schema/keys differ")
                return
            for key in left:
                if path == "snapshot" and key in {"input_sha256", "config_sha256"}:
                    metrics[f"{path}.{key}"] = {
                        "windows_bytes_sha256": left[key], "runtime_bytes_sha256": right[key],
                        "byte_equal": left[key] == right[key],
                        "contract": "CRLF/LF-only canonical hash is compared strictly",
                    }
                    continue
                compare(left[key], right[key], f"{path}.{key}")
        elif ".vectors." in path and path.rsplit(".", 1)[-1] in TOLERANCES and isinstance(left, list):
            a = np.asarray([np.nan if value is None else value for value in left], dtype=np.float64)
            b = np.asarray([np.nan if value is None else value for value in right], dtype=np.float64)
            if a.shape != b.shape:
                failures.append(f"{path}: row count differs")
                return
            mask_equal = bool(np.array_equal(np.isnan(a), np.isnan(b)))
            finite = np.isfinite(a) & np.isfinite(b)
            difference = np.abs(a[finite] - b[finite])
            rtol, atol = TOLERANCES[path.rsplit(".", 1)[-1]]
            # Relative denominator uses the absolute tolerance as a declared near-zero scale.
            scale = np.maximum(np.abs(a[finite]), max(atol, np.finfo(float).tiny))
            passed = mask_equal and bool(np.allclose(a, b, rtol=rtol, atol=atol, equal_nan=True))
            metrics[path] = {
                "max_abs_difference": float(difference.max()) if difference.size else 0.0,
                "max_relative_difference": float((difference / scale).max()) if difference.size else 0.0,
                "relative_denominator_floor": max(atol, np.finfo(float).tiny),
                "rtol": rtol, "atol": atol, "nan_mask_equal": mask_equal, "passed": passed,
            }
            if not passed:
                failures.append(f"{path}: numeric tolerance or NaN mask differs")
        elif left != right:
            failures.append(f"{path}: exact decision/schema/config differs")

    compare(expected, actual, "snapshot")
    maximums = {key: max((value["max_abs_difference"] for name, value in metrics.items()
                         if name.endswith(f".vectors.{key}")), default=0.0)
                for key in TOLERANCES}
    return {"status": "FAIL" if failures else "PASS", "failures": failures, "metrics": metrics,
            "max_abs_differences": maximums,
            "nan_mask_equality": (all(value.get("nan_mask_equal", True) for value in metrics.values())
                                  and not any("nan_mask" in item for item in failures)),
            "quality_flag_equality": not any(any(key in item for key in (
                "quality_flags", "signal_states", "refinement_statuses")) for item in failures),
            "ridge_bin_equality": not any("bins" in item for item in failures),
            "event_selection_equality": not any("event_selection" in item for item in failures),
            "row_count_equality": not any(any(key in item for key in (
                "row count", "rows", "frame_count", "sample_count")) for item in failures),
            "schema_equality": not any("schema" in item for item in failures)}


def dependency_versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in DEPENDENCIES}


def reference_environment() -> dict[str, Any]:
    return {"platform": platform.system(), "machine": platform.machine(),
            "python": platform.python_version(), "dependencies": dependency_versions()}
