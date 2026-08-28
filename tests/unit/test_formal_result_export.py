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
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultExportOptions,
    ResultExportValidationError,
    ResultExportWriteError,
    export_formal_results,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import (
    ManualFrequencyBoundary,
    ManualFrequencyRegion,
    RidgeCorridorConstraint,
)
from dps_studio.core.workflow import (
    PRE_EVENT_DISPLAY_ORIGIN,
    analyze_configuration,
    analyze_stft_results,
)


def _analyses(
    tmp_path: Path,
    *,
    manual_event_reference_time_s: float | None = 0.4e-6,
    include_active_signal: bool = True,
    window_name: str = "hann",
) -> dict[str, Any]:
    sample_rate_hz = 4.0e9
    sample_count = 4096
    source_path = tmp_path / "20260607.csv"
    source_path.write_text("source remains unchanged\n", encoding="utf-8")
    time_s = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    active = (time_s >= 0.4e-6) & (time_s < 0.8e-6)
    if not include_active_signal:
        active[:] = False
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
        window_name=window_name,
        minimum_frequency_hz=20.0e6,
        maximum_frequency_hz=800.0e6,
        analysis_start_time_s=0.1e-6,
        analysis_end_time_s=0.9e-6,
        manual_event_reference_time_s=manual_event_reference_time_s,
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
        manual_event_reference_time_s=manual_event_reference_time_s,
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
    event_reference_source: str | None = "config",
    event_time_source: str | None = "manual",
    time_origin: ExportTimeOrigin = ExportTimeOrigin.EVENT,
) -> ResultExportOptions:
    return ResultExportOptions(
        output_directory=destination,
        analysis_mode=mode,
        channel_analyses=analyses,
        time_origin=time_origin,
        include_pre_event_display_rows=include_pre_event_display_rows,
        source_path=source_path,
        analysis_profile_name="task017r-test",
        pre_event_display_enabled=True,
        pre_event_display_velocity_m_s=12.5,
        event_reference_source=event_reference_source,
        event_time_source=event_time_source,
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
    assert set(simple_rows[0]) == {
        "time_from_event_s",
        "display_velocity_m_s",
    }
    assert set(detail_rows[0]) == {
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
    }
    assert len(simple_rows) == len(detail_rows)
    for index, (simple, detail) in enumerate(zip(simple_rows, detail_rows, strict=True)):
        assert _same_float(
            simple["time_from_event_s"],
            analysis.signal_detection_result.time_s[index] - 0.4e-6,
        )
        assert _same_float(
            detail["time_s"],
            analysis.signal_detection_result.time_s[index],
        )
        assert simple["time_from_event_s"] == detail["time_from_event_s"]
        assert _same_float(
            simple["display_velocity_m_s"],
            analysis.display_velocity_m_s[index],
        )
        assert simple["display_velocity_m_s"] == detail["display_velocity_m_s"]
        assert _same_float(
            detail["apparent_velocity_m_s"],
            analysis.apparent_velocity_m_s[index],
        )
        assert _same_float(
            detail["angle_corrected_apparent_velocity_m_s"],
            analysis.angle_corrected_apparent_velocity_m_s[index],
        )
        assert _same_float(
            detail["corrected_velocity_m_s"],
            analysis.corrected_velocity_m_s[index],
        )

    display_only_rows = [
        row for row in detail_rows if row["is_pre_event_display_only"] == "true"
    ]
    assert display_only_rows
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
        _same_float(
            simple_rows[index]["display_velocity_m_s"],
            analysis.corrected_velocity_m_s[index],
        )
        for index in post_event_invalid_indices
    )

    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert metadata["export_schema_version"] == "pdv-studio-formal-result-v6"
    selection_metadata = metadata["automatic_ridge_selection"]
    assert selection_metadata["recovery_tolerance_hz"] == pytest.approx(
        15_625_000.0
    )
    assert {key: value for key, value in selection_metadata.items() if key != "recovery_tolerance_hz"} == {
        "continuity_reselection_count": 0,
        "continuity_reselection_enabled": True,
        "minimum_candidate_peak_to_background_db": 10.0,
        "minimum_candidate_relative_to_strongest_db": -6.0,
        "mode": "continuity_assisted",
        "recovery_tolerance_source": (
            "sample_rate_hz_divided_by_window_length_samples"
        ),
        "selection_method": (
            "strongest local peak by default; optional isolated-jump-only "
            "event-aware continuity rescue under explicit spectral and "
            "two-neighbor hard gates; no interpolation, smoothing, filtering, "
            "or gap filling"
        ),
        "top_k_candidates": 3,
    }
    assert metadata["data_file"] == exported.csv_path.name
    assert metadata["detail_data_file"] == exported.detail_csv_path.name
    assert metadata["source_file"] == str(results["source_path"])
    assert metadata["source_channel"] == "pdv_channel_1"
    assert metadata["analysis_mode"] == "automatic"
    assert metadata["automatic_event_candidate_time_s"] == (
        analysis.stream_event_candidates.primary_candidate_time_s
    )
    assert metadata["compatibility_event_candidate_time_s"] == (
        analysis.signal_detection_result.detected_event_candidate_time_s
    )
    assert metadata["event_reference_time_s"] == 0.4e-6
    assert metadata["event_reference_source"] == "config"
    assert metadata["time_coordinate"] == {
        "absolute_time_preserved": True,
        "detail_csv_absolute_time_column": "time_s",
        "detail_csv_relative_time_column": "time_from_event_s",
        "event_reference_time_s": 0.4e-6,
        "export_time_origin": "event",
        "relative_time_definition": (
            "time_from_event_s = time_s - event_reference_time_s"
        ),
        "simple_csv_time_column": "time_from_event_s",
    }
    assert metadata["physics"] == {
        "vacuum_wavelength_m": 1.55e-6,
        "velocity_relation": "v_app=lambda0*f_b/2",
    }
    correction = metadata["velocity_correction"]
    assert correction["execution_order"] == [
        "apparent_velocity",
        "geometrical_angle_correction",
        "window_correction",
    ]
    assert correction["angle"]["angle_rad"] == 0.0
    assert correction["angle"]["source_doi"] == "10.1063/1.4940935"
    assert correction["window"] == {
        "b1": 0.7895,
        "b2": 0.9918,
        "crystal_orientation": "[100]",
        "custom_parameters": False,
        "enabled": True,
        "loading_context": "dynamic compression / calibrated window correction",
        "material": "LiF",
        "model": "Rigg2014_Eq16",
        "paper_velocity_unit": "km/s",
        "parameter_provenance": "formal_default",
        "reference_wavelength_m": 1.55e-6,
        "source": "Rigg et al., Journal of Applied Physics 116, 033515 (2014)",
        "source_doi": "10.1063/1.4890714",
        "wavelength_matches_model_reference": True,
        "wavelength_validation_message": None,
    }
    assert metadata["pre_event_display"]["included_in_csv"] is True
    assert metadata["pre_event_display"]["formal_measurement_modified"] is False
    assert metadata["result_counts"]["exported_row_count"] == len(simple_rows)
    assert metadata["working_ridge"] == {
        "frequency_field": "ChannelAnalysis.working_frequency_hz",
        "working_source_field": "ChannelAnalysis.working_source",
        "formal_frequency_field": (
            "SignalDetectionResult.refined_frequency_hz"
        ),
        "formal_quality_gates_modified": False,
        "same_frame_fallback_only": True,
        "interpolation_or_smoothing_applied": False,
    }
    assert metadata["result_counts"]["working_finite_frame_count"] == int(
        np.count_nonzero(np.isfinite(analysis.working_frequency_hz))
    )
    assert metadata["result_counts"]["working_source_counts"]
    assert metadata["result_status"]["simple_csv_velocity_source"] == (
        "display_velocity_m_s"
    )
    assert metadata["result_status"]["unreliable_formal_values_preserved_as_nan"]
    assert analysis.signal_detection_result.apparent_velocity_m_s.tobytes() == formal_before
    assert analysis.display_velocity_m_s.tobytes() == display_before


@pytest.mark.parametrize(
    "window_name",
    ["hann", "hamming", "blackman", "blackmanharris", "boxcar"],
)
def test_actual_stft_window_is_recorded_in_the_single_metadata_json(
    tmp_path: Path,
    window_name: str,
) -> None:
    analysis = _analyses(tmp_path, window_name=window_name)["automatic"][
        "pdv_channel_1"
    ]
    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=tmp_path / "20260607.csv",
        )
    )
    metadata_files = list(tmp_path.glob("*.metadata.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(
        report.exported_channels[0].metadata_path.read_text(encoding="utf-8")
    )
    assert metadata["stft_configuration"]["window_name"] == window_name
    assert metadata["stft_configuration"]["window_length_samples"] == 256
    assert metadata["stft_configuration"]["overlap_samples"] == 128
    assert metadata["stft_configuration"]["hop_samples"] == 128
    assert metadata["stft_configuration"]["nfft"] == 1024


def test_event_metadata_case_a_automatic_candidate_is_the_resolved_reference(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path, manual_event_reference_time_s=None)
    analysis = results["automatic"]["pdv_channel_1"]

    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
            event_reference_source="automatic",
            event_time_source="automatic",
            time_origin=ExportTimeOrigin.ABSOLUTE,
        )
    )
    metadata = json.loads(
        report.exported_channels[0].metadata_path.read_text(encoding="utf-8")
    )

    assert metadata["automatic_event_candidate_time_s"] is not None
    assert metadata["compatibility_event_candidate_time_s"] is not None
    assert metadata["event_reference_time_s"] == metadata[
        "automatic_event_candidate_time_s"
    ]
    assert metadata["event_reference_source"] == "automatic"
    assert metadata["event_time_source"] == "automatic"
    assert metadata["event_time_s"] == metadata["event_reference_time_s"]
    assert len(tuple(tmp_path.iterdir())) == 4  # source fixture plus exactly three exports
    assert len(tuple(tmp_path.glob("*.metadata.json"))) == 1


def test_event_metadata_case_b_user_adopts_primary(tmp_path: Path) -> None:
    results = _analyses(tmp_path, manual_event_reference_time_s=None)
    analysis = results["automatic"]["pdv_channel_1"]
    primary_s = analysis.stream_event_candidates.primary_candidate_time_s
    assert primary_s is not None
    detection = replace(
        analysis.signal_detection_result,
        manual_event_reference_time_s=primary_s,
    )
    adopted_analysis = replace(analysis, signal_detection_result=detection)

    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": adopted_analysis},
            source_path=results["source_path"],
            event_reference_source="user_adopted:automatic_primary:pdv_channel_1",
        )
    )
    metadata = json.loads(
        report.exported_channels[0].metadata_path.read_text(encoding="utf-8")
    )

    assert metadata["automatic_event_candidate_time_s"] == primary_s
    assert metadata["event_reference_time_s"] == primary_s
    assert metadata["event_reference_source"].startswith("user_adopted")


def test_event_metadata_case_c_configuration_reference_can_differ(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path, manual_event_reference_time_s=0.4e-6)
    analysis = results["automatic"]["pdv_channel_1"]

    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
            event_reference_source="config",
        )
    )
    metadata = json.loads(
        report.exported_channels[0].metadata_path.read_text(encoding="utf-8")
    )

    assert metadata["automatic_event_candidate_time_s"] is not None
    assert metadata["automatic_event_candidate_time_s"] != 0.4e-6
    assert metadata["event_reference_time_s"] == 0.4e-6
    assert metadata["event_reference_source"] == "config"


def test_event_metadata_case_d_absent_candidates_remain_null(tmp_path: Path) -> None:
    results = _analyses(
        tmp_path,
        manual_event_reference_time_s=None,
        include_active_signal=False,
    )
    analysis = results["automatic"]["pdv_channel_1"]

    report = export_formal_results(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
            event_reference_source=None,
            event_time_source=None,
            time_origin=ExportTimeOrigin.ABSOLUTE,
        )
    )
    metadata = json.loads(
        report.exported_channels[0].metadata_path.read_text(encoding="utf-8")
    )

    assert metadata["automatic_event_candidate_time_s"] is None
    assert metadata["compatibility_event_candidate_time_s"] is None
    assert metadata["event_reference_time_s"] is None
    assert metadata["event_reference_source"] is None


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
        assert metadata["velocity_correction"]["window"]["material"] == "LiF"
        assert metadata["velocity_correction"]["window"]["model"] == (
            "Rigg2014_Eq16"
        )
        assert metadata["velocity_correction"]["angle"]["angle_rad"] == 0.0
        assert "event_reference_time_s" in metadata


def test_guided_export_records_manual_frequency_boundaries_in_si(
    tmp_path: Path,
) -> None:
    results = _analyses(tmp_path)
    analysis = results["guided"]["pdv_channel_1"]
    region = ManualFrequencyRegion(
        upper_boundary=ManualFrequencyBoundary(
            np.array([0.2e-6, 0.8e-6]),
            np.array([300.0e6, 850.0e6]),
        ),
        lower_boundary=ManualFrequencyBoundary(
            np.array([0.3e-6, 0.7e-6]),
            np.array([100.0e6, 650.0e6]),
        ),
    )
    options = replace(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.GUIDED,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
        ),
        ridge_constraints={"pdv_channel_1": region},
    )

    exported = export_formal_results(options).exported_channels[0]
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    manual = metadata["manual_frequency_region"]

    assert manual["constraint_model"] == "manual_upper_lower_boundaries"
    assert manual["outside_manual_time_range"] == "endpoint_constant_extension"
    assert manual["boundary_interpolation"] == "piecewise_linear"
    assert manual["boundary_extrapolation"] == (
        "constant_first_and_last_frequency"
    )
    assert manual["legacy_corridor"] is None
    assert manual["upper_boundary"] == [
        {"time_s": 0.2e-6, "frequency_hz": 300.0e6},
        {"time_s": 0.8e-6, "frequency_hz": 850.0e6},
    ]
    assert manual["lower_boundary"] == [
        {"time_s": 0.3e-6, "frequency_hz": 100.0e6},
        {"time_s": 0.7e-6, "frequency_hz": 650.0e6},
    ]
    assert "corridor_half_width_hz" not in manual


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
    missing_reference_source = replace(
        _options(
            tmp_path,
            mode=ResultAnalysisMode.AUTOMATIC,
            analyses={"pdv_channel_1": analysis},
            source_path=results["source_path"],
        ),
        event_reference_source=None,
    )
    with pytest.raises(ResultExportValidationError, match="exactly when"):
        export_formal_results(missing_reference_source)

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
