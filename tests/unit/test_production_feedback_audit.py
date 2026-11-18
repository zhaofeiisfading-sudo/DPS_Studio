"""Independent regressions for the verified Production export issues."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio import __version__
from dps_studio.core.export import (
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultExportOptions,
    ResultExportValidationError,
    export_formal_results,
)
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import PRE_EVENT_DISPLAY_ORIGIN, analyze_configuration


def _analyze(record: SignalRecord):
    return analyze_configuration(
        {"ch1": record}, window_length_samples=256, overlap_samples=128,
        nfft=1024, window_name="hann", minimum_frequency_hz=20e6,
        maximum_frequency_hz=800e6, vacuum_wavelength_m=1.55e-6,
        manual_event_reference_time_s=0.8e-6, assume_pre_event_zero_for_display=True,
    )["ch1"]


def _loaded_analysis(tmp_path: Path):
    time = np.arange(8192) / 4e9
    voltage = np.random.default_rng(29).normal(0, 0.002, time.size)
    active = (time >= 0.8e-6) & (time <= 1.6e-6)
    voltage[active] += np.sin(2 * np.pi * 200e6 * time[active])
    path = tmp_path / "mapped_input.csv"
    np.savetxt(path, np.column_stack((voltage * 1e3, time * 1e6)),
               delimiter=",", header="signal_mV,time_us", comments="", fmt="%.17g")
    loaded = read_delimited_signals(
        path, time_column=1, voltage_columns={"ch1": 0}, has_header=True,
        time_scale=1e-6, voltage_scales={"ch1": 1e-3},
        original_time_unit="us", original_voltage_units={"ch1": "mV"},
    )
    return loaded, _analyze(loaded.records["ch1"])


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_continuous_and_quality_exports_have_distinct_sources_and_full_diagnostics(tmp_path):
    loaded, analysis = _loaded_analysis(tmp_path)
    source_before = loaded.source_path.read_bytes()
    formal_before = analysis.corrected_velocity_m_s.tobytes()
    options = ResultExportOptions(
        tmp_path, ResultAnalysisMode.AUTOMATIC, {"ch1": analysis},
        time_origin=ExportTimeOrigin.ABSOLUTE,
        event_reference_source="manual",
    )
    continuous = export_formal_results(options).exported_channels[0]
    continuous_rows = _rows(continuous.csv_path)
    detail = _rows(continuous.detail_csv_path)
    low_quality = [
        row for row in detail if row["signal_state"] != "measured"
        and np.isfinite(float(row["display_velocity_m_s"]))
    ]
    assert low_quality  # Proves that finite display values can fail formal gates.
    assert len(continuous_rows) == len(detail)
    assert set(continuous_rows[0]) == {"time_s", "display_velocity_m_s"}
    assert all(a["display_velocity_m_s"] == b["display_velocity_m_s"]
               for a, b in zip(continuous_rows, detail, strict=True))
    assert any(row["is_pre_event_display_only"] == "true" for row in detail)
    for row in low_quality:
        assert np.isnan(float(row["apparent_velocity_m_s"]))
        assert row["ridge_quality_flag"]
    # Make plot and formal velocities deliberately differ, even on measured frames.
    changed_display = replace(analysis, display_velocity_m_s=np.full(analysis.stft_result.time_s.size, 12345.0))
    filtered = export_formal_results(replace(
        options, channel_analyses={"ch1": changed_display}, quality_passed_only=True,
    )).exported_channels[0]
    rows = _rows(filtered.csv_path)
    filtered_detail = _rows(filtered.detail_csv_path)
    assert "_quality_passed" in filtered.csv_path.stem
    assert set(rows[0]) == {"time_s", "corrected_velocity_m_s"}
    expected = [i for i, state in enumerate(analysis.signal_detection_result.signal_states)
                if state is SignalState.MEASURED and analysis.velocity_origins[i] != PRE_EVENT_DISPLAY_ORIGIN
                and np.isfinite(analysis.corrected_velocity_m_s[i])]
    assert len(rows) == len(expected) < len(continuous_rows)
    for row, index in zip(rows, expected, strict=True):
        assert float(row["time_s"]) == analysis.stft_result.time_s[index]
        assert float(row["corrected_velocity_m_s"]) == analysis.corrected_velocity_m_s[index]
        assert float(row["corrected_velocity_m_s"]) != 12345.0
    assert len(filtered_detail) == len(detail)
    metadata = json.loads(filtered.metadata_path.read_text(encoding="utf-8"))
    assert metadata["dps_studio_version"] == __version__
    assert metadata["simple_export"]["quality_filtering_applied"]
    assert metadata["simple_export"]["time_series_may_have_gaps"]
    assert not metadata["simple_export"]["detailed_csv_quality_filtering_applied"]
    assert metadata["simple_export"]["excluded_by_quality_filter_count"] == len(detail) - len(rows)
    assert not metadata["pre_event_display"]["included_in_csv"]
    assert metadata["pre_event_display"]["included_in_detail_csv"]
    assert metadata["result_counts"]["detail_exported_row_count"] == len(detail)
    assert source_before == loaded.source_path.read_bytes()
    assert formal_before == analysis.corrected_velocity_m_s.tobytes()


def test_original_mapping_and_explicit_units_survive_staged_analysis_and_json(tmp_path):
    loaded, analysis = _loaded_analysis(tmp_path)
    record = loaded.records["ch1"]
    assert record.metadata["time_column_index"] == 1
    assert analysis.stft_result.source_metadata == record.metadata
    exported = export_formal_results(ResultExportOptions(
        tmp_path, ResultAnalysisMode.AUTOMATIC, {"ch1": analysis},
        event_reference_source="manual",
    )).exported_channels[0]
    document = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert document["source_file"] == str(loaded.source_path)
    assert document["input_provenance"] == {
        "time_column_index": 1, "voltage_column_index": 0,
        "original_time_unit": "us", "original_voltage_unit": "mV",
        "time_scale": 1e-6, "voltage_scale": 1e-3,
        "delimiter": ",", "encoding": "utf-8", "has_header": True,
        "header": ["signal_mV", "time_us"],
    }
    assert document["stft_configuration"]["sample_rate_hz"] == pytest.approx(4e9)


def test_unknown_original_units_are_not_guessed_from_conversion_factor(tmp_path):
    path = tmp_path / "unknown_units.csv"
    path.write_text("0,1\n1,2\n", encoding="utf-8")
    record = read_delimited_signals(
        path, time_column=0, voltage_columns={"ch1": 1}, time_scale=1e-6,
    ).records["ch1"]
    assert record.metadata["original_time_unit"] is None
    assert record.metadata["original_voltage_unit"] is None


def test_quality_export_of_unreliable_signal_is_header_only(tmp_path):
    analysis = _analyze(SignalRecord(np.arange(8192) / 4e9, np.zeros(8192)))
    exported = export_formal_results(ResultExportOptions(
        tmp_path, ResultAnalysisMode.AUTOMATIC, {"ch1": analysis},
        quality_passed_only=True,
        event_reference_source="manual",
    )).exported_channels[0]
    assert exported.csv_path.read_text(encoding="utf-8") == "time_s,corrected_velocity_m_s\n"
    assert exported.exported_row_count == 0
    assert _rows(exported.detail_csv_path)


def test_quality_option_requires_explicit_boolean(tmp_path):
    analysis = _analyze(SignalRecord(np.arange(8192) / 4e9, np.zeros(8192)))
    with pytest.raises(ResultExportValidationError, match="quality_passed_only"):
        ResultExportOptions(tmp_path, ResultAnalysisMode.AUTOMATIC,
                            {"ch1": analysis}, quality_passed_only="yes")


def test_long_static_white_noise_does_not_become_confirmed_event():
    time = np.arange(32768) / 4e9
    analysis = _analyze(SignalRecord(time, np.random.default_rng(29).normal(0, 0.002, time.size)))
    assert analysis.stream_event_candidates.primary_candidate_time_s is None
    assert analysis.signal_detection_result.manual_event_reference_time_s == 0.8e-6
