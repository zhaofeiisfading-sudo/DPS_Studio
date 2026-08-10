from __future__ import annotations

import csv
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dps_studio.core.export import (
    ResultAnalysisMode,
    ResultExportOptions,
    ResultExportValidationError,
    ResultExportWriteError,
    export_formal_results,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import (
    PRE_EVENT_DISPLAY_ORIGIN,
    analyze_configuration,
    analyze_stft_results,
)


def _analyses(tmp_path: Path) -> dict[str, Any]:
    sample_rate_hz = 4.0e9
    sample_count = 4096
    source_path = tmp_path / "20260607.csv"
    source_path.write_text("source remains unchanged\n", encoding="utf-8")
    time_s = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    active = (time_s >= 0.4e-6) & (time_s < 0.8e-6)
    records: dict[str, SignalRecord] = {}
    for channel_name, frequency_hz in (
        ("pdv_channel_1", 200.0e6),
        ("pdv_channel_2", 240.0e6),
    ):
        voltage_v = np.zeros(sample_count, dtype=np.float64)
        voltage_v[active] = np.sin(2.0 * np.pi * frequency_hz * time_s[active])
        records[channel_name] = SignalRecord(time_s, voltage_v, source_path=source_path)
    automatic = analyze_configuration(
        records,
        window_length_samples=256,
        overlap_samples=128,
        nfft=1024,
        window_name="hann",
        minimum_frequency_hz=20.0e6,
        maximum_frequency_hz=800.0e6,
        analysis_start_time_s=0.1e-6,
        analysis_end_time_s=0.9e-6,
        manual_event_reference_time_s=0.4e-6,
        vacuum_wavelength_m=1.55e-6,
        assume_pre_event_zero_for_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    first = automatic["pdv_channel_1"]
    stft = first.stft_result
    constrained_times = stft.time_s[
        (stft.time_s >= 0.2e-6) & (stft.time_s <= 0.8e-6)
    ]
    constraint = RidgeCorridorConstraint(
        control_times_s=np.asarray([constrained_times[0], constrained_times[-1]]),
        control_frequencies_hz=np.asarray([200.0e6, 200.0e6]),
        half_width_hz=75.0e6,
    )
    guided = analyze_stft_results(
        {"pdv_channel_1": stft},
        minimum_frequency_hz=20.0e6,
        maximum_frequency_hz=800.0e6,
        profile_name="task017-guided",
        analysis_start_time_s=0.1e-6,
        analysis_end_time_s=0.9e-6,
        manual_event_reference_time_s=0.4e-6,
        vacuum_wavelength_m=1.55e-6,
        assume_pre_event_zero_for_display=True,
        pre_event_display_velocity_m_s=12.5,
        ridge_constraints={"pdv_channel_1": constraint},
    )
    return {"automatic": automatic, "guided": guided, "source_path": source_path}


def _options(
    destination: Path,
    *,
    mode: ResultAnalysisMode,
    analyses: dict[str, Any],
    source_path: Path | None,
    include_pre_event_display_rows: bool = True,
    protected_output_directories: tuple[Path, ...] = (),
) -> ResultExportOptions:
    return ResultExportOptions(
        output_directory=destination,
        analysis_mode=mode,
        channel_analyses=analyses,
        include_pre_event_display_rows=include_pre_event_display_rows,
        source_path=source_path,
        analysis_profile_name="task017r-test",
        pre_event_display_enabled=True,
        pre_event_display_velocity_m_s=12.5,
        protected_output_directories=protected_output_directories,
    )


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _same_float(csv_value: str, value: float) -> bool:
    actual = float(csv_value)
    return math.isnan(actual) if math.isnan(value) else actual == value


def test_export_writes_simple_csv_detail_csv_and_traceable_metadata(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path)
    analysis = results["automatic"]["pdv_channel_1"]
    formal_before = analysis.signal_detection_result.apparent_velocity_m_s.tobytes()
    display_before = analysis.display_velocity_m_s.tobytes()

    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
        )
    )

    exported = report.exported_channels[0]
    simple_rows = _rows(exported.csv_path)
    detail_rows = _rows(exported.detail_csv_path)
    assert report.analysis_mode is ResultAnalysisMode.AUTOMATIC
    assert report.output_directory == tmp_path.resolve()
    assert exported.csv_path.name == "20260607_ch1_auto.csv"
    assert exported.detail_csv_path.name == "20260607_ch1_auto_detail.csv"
    assert exported.metadata_path.name == "20260607_ch1_auto.metadata.json"
    assert set(simple_rows[0]) == {"time_s", "velocity_m_s"}
    assert set(detail_rows[0]) == {
        "time_s",
        "coarse_peak_frequency_hz",
        "refined_frequency_hz",
        "apparent_velocity_m_s",
        "display_velocity_m_s",
        "ridge_quality_flag",
        "ridge_refinement_status",
        "signal_state",
        "velocity_origin",
        "is_pre_event_display_only",
        "channel",
        "analysis_mode",
    }
    assert len(simple_rows) == len(detail_rows)
    for index, (simple, detail) in enumerate(zip(simple_rows, detail_rows, strict=True)):
        assert _same_float(simple["time_s"], analysis.signal_detection_result.time_s[index])
        assert _same_float(simple["velocity_m_s"], analysis.display_velocity_m_s[index])
        assert simple["velocity_m_s"] == detail["display_velocity_m_s"]

    display_only_rows = [
        row for row in detail_rows if row["is_pre_event_display_only"] == "true"
    ]
    assert display_only_rows
    assert all(math.isnan(float(row["apparent_velocity_m_s"])) for row in display_only_rows)
    assert all(float(row["display_velocity_m_s"]) == 12.5 for row in display_only_rows)
    assert all(row["analysis_mode"] == "automatic" for row in detail_rows)
    assert all(row["channel"] == "pdv_channel_1" for row in detail_rows)

    post_event_invalid_indices = [
        index
        for index, origin in enumerate(analysis.velocity_origins)
        if origin != PRE_EVENT_DISPLAY_ORIGIN
        and math.isnan(analysis.signal_detection_result.apparent_velocity_m_s[index])
    ]
    assert post_event_invalid_indices
    assert all(
        math.isnan(float(simple_rows[index]["velocity_m_s"]))
        for index in post_event_invalid_indices
    )

    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert metadata["export_schema_version"] == "pdv-studio-formal-result-v2"
    assert metadata["data_file"] == exported.csv_path.name
    assert metadata["detail_data_file"] == exported.detail_csv_path.name
    assert metadata["source_file"] == str(results["source_path"])
    assert metadata["source_channel"] == "pdv_channel_1"
    assert metadata["analysis_mode"] == "automatic"
    assert metadata["pre_event_display"]["included_in_csv"] is True
    assert metadata["pre_event_display"]["formal_measurement_modified"] is False
    assert metadata["result_counts"]["exported_row_count"] == len(simple_rows)
    assert metadata["result_status"]["simple_csv_velocity_source"] == (
        "display_velocity_m_s"
    )
    assert metadata["result_status"]["unreliable_formal_values_preserved_as_nan"]
    assert analysis.signal_detection_result.apparent_velocity_m_s.tobytes() == formal_before
    assert analysis.display_velocity_m_s.tobytes() == display_before


def test_disabling_pre_event_rows_changes_only_exported_row_selection(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path)
    analysis = results["automatic"]["pdv_channel_1"]
    formal_before = analysis.signal_detection_result.apparent_velocity_m_s.tobytes()
    display_before = analysis.display_velocity_m_s.tobytes()
    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
            include_pre_event_display_rows=False,
        )
    )
    exported = report.exported_channels[0]
    simple_rows = _rows(exported.csv_path)
    detail_rows = _rows(exported.detail_csv_path)
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert simple_rows
    assert len(simple_rows) == len(detail_rows)
    assert not any(row["is_pre_event_display_only"] == "true" for row in detail_rows)
    assert metadata["pre_event_display"]["included_in_csv"] is False
    assert metadata["result_counts"]["pre_event_display_only_frame_count"] > 0
    assert metadata["result_counts"]["exported_pre_event_display_only_row_count"] == 0
    assert analysis.signal_detection_result.apparent_velocity_m_s.tobytes() == formal_before
    assert analysis.display_velocity_m_s.tobytes() == display_before


def test_dual_channels_and_automatic_guided_results_export_independently(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path)
    automatic_report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses=results["automatic"],
            source_path=results["source_path"],
        )
    )
    guided_report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.GUIDED,
            analyses=results["guided"],
            source_path=results["source_path"],
        )
    )
    assert automatic_report.output_directory == guided_report.output_directory
    assert {item.csv_path.name for item in automatic_report.exported_channels} == {
        "20260607_ch1_auto.csv",
        "20260607_ch2_auto.csv",
    }
    assert {item.detail_csv_path.name for item in automatic_report.exported_channels} == {
        "20260607_ch1_auto_detail.csv",
        "20260607_ch2_auto_detail.csv",
    }
    assert [item.csv_path.name for item in guided_report.exported_channels] == [
        "20260607_ch1_guided.csv"
    ]
    for item in (*automatic_report.exported_channels, *guided_report.exported_channels):
        metadata = json.loads(item.metadata_path.read_text(encoding="utf-8"))
        assert metadata["source_channel"] == item.channel_name
        assert metadata["analysis_mode"] in {"automatic", "guided"}


def test_existing_exports_receive_a_consistent_suffix_without_overwrite(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path)
    options = _options(
        tmp_path,
        mode=ResultAnalysisMode.AUTOMATIC,
        analyses={"pdv_channel_1": results["automatic"]["pdv_channel_1"]},
        source_path=results["source_path"],
    )
    first = export_formal_results(options).exported_channels[0]
    first_csv = first.csv_path.read_bytes()
    second = export_formal_results(options).exported_channels[0]
    assert first.csv_path.name == "20260607_ch1_auto.csv"
    assert second.csv_path.name == "20260607_ch1_auto_2.csv"
    assert second.detail_csv_path.name == "20260607_ch1_auto_2_detail.csv"
    assert second.metadata_path.name == "20260607_ch1_auto_2.metadata.json"
    assert first.csv_path.read_bytes() == first_csv


def test_missing_source_path_uses_explicit_unsourced_filename_fallback(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path)
    analysis = results["automatic"]["pdv_channel_1"]
    analysis_without_source = replace(
        analysis,
        stft_result=replace(analysis.stft_result, source_path=None),
    )
    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis_without_source},
            source_path=None,
        )
    )
    exported = report.exported_channels[0]
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert exported.csv_path.name == "unsourced_ch1_auto.csv"
    assert metadata["source_file"] is None


def test_invalid_name_protected_path_and_write_failure_are_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _analyses(tmp_path)
    analysis = results["automatic"]["pdv_channel_1"]
    with pytest.raises(ResultExportValidationError, match="filename"):
        export_formal_results(
            _options(
                tmp_path,
                mode=ResultAnalysisMode.AUTOMATIC,
                analyses={"bad/name": analysis},
                source_path=results["source_path"],
            )
        )

    protected = tmp_path / "data" / "raw"
    protected.mkdir(parents=True)
    protected_options = _options(
        protected,
        mode=ResultAnalysisMode.AUTOMATIC,
        analyses={"pdv_channel_1": analysis},
        source_path=results["source_path"],
        protected_output_directories=(protected,),
    )
    with pytest.raises(ResultExportWriteError, match="data/raw|protected"):
        export_formal_results(protected_options)

    with pytest.raises(ResultExportWriteError, match="does not exist"):
        export_formal_results(
            _options(
                tmp_path / "missing_export_parent",
                mode=ResultAnalysisMode.AUTOMATIC,
                analyses={"pdv_channel_1": analysis},
                source_path=results["source_path"],
            )
        )

    from dps_studio.core.export import writer

    monkeypatch.setattr(
        writer,
        "_write_json",
        lambda _path, _document: (_ for _ in ()).throw(TypeError("not serializable")),
    )
    with pytest.raises(ResultExportWriteError, match="Could not write formal result"):
        export_formal_results(
            _options(
                tmp_path,
                mode=ResultAnalysisMode.AUTOMATIC,
                analyses={"pdv_channel_1": analysis},
                source_path=results["source_path"],
            )
        )
    assert not list(tmp_path.glob(".pdv_studio_export_staging_*"))
