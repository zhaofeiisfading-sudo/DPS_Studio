from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.export import (
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultExportOptions,
    ResultExportValidationError,
    event_relative_time_s,
    export_formal_results,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import VelocityCorrectionConfig, WindowMaterial
from dps_studio.core.workflow import (
    ChannelAnalysis,
    analyze_configuration,
    configure_channel_event_reference,
    configure_channel_velocity_correction,
)


def _analysis(tmp_path: Path) -> ChannelAnalysis:
    sample_rate_hz = 4.0e9
    time_s = np.arange(4096, dtype=np.float64) / sample_rate_hz
    active = (time_s >= 0.2e-6) & (time_s < 0.8e-6)
    voltage_v = np.zeros_like(time_s)
    voltage_v[active] = np.sin(2.0 * np.pi * 250.0e6 * time_s[active])
    analysis = analyze_configuration(
        {
            "pdv_channel_1": SignalRecord(
                time_s,
                voltage_v,
                source_path=tmp_path / "task019a.csv",
            )
        },
        window_length_samples=256,
        overlap_samples=128,
        nfft=1024,
        window_name="hann",
        minimum_frequency_hz=20.0e6,
        maximum_frequency_hz=800.0e6,
        analysis_start_time_s=0.1e-6,
        analysis_end_time_s=0.9e-6,
        manual_event_reference_time_s=0.2e-6,
        vacuum_wavelength_m=1.55e-6,
        assume_pre_event_zero_for_display=True,
    )["pdv_channel_1"]
    reference_s = float(analysis.stft_result.time_s[8])
    return configure_channel_event_reference(
        analysis,
        event_reference_time_s=reference_s,
        event_reference_source="test",
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=0.0,
    )


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_event_relative_time_uses_the_formal_reference_and_handles_absence() -> None:
    absolute = np.asarray([744.0e-6, 744.1e-6, 744.2e-6])
    relative = event_relative_time_s(absolute, 744.1e-6)
    np.testing.assert_allclose(relative, [-0.1e-6, 0.0, 0.1e-6], atol=1e-20)
    assert relative[1] == 0.0
    assert np.isnan(event_relative_time_s(absolute, None)).all()
    np.testing.assert_array_equal(absolute, [744.0e-6, 744.1e-6, 744.2e-6])


def test_event_reference_changes_only_display_and_time_convention(
    tmp_path: Path,
) -> None:
    analysis = configure_channel_event_reference(
        _analysis(tmp_path),
        event_reference_time_s=None,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=0.0,
    )
    working_before = analysis.working_frequency_hz.copy()
    apparent_before = analysis.continuous_apparent_velocity_m_s.copy()
    corrected_before = analysis.continuous_corrected_velocity_m_s.copy()
    reference_s = float(analysis.stft_result.time_s[10])

    updated = configure_channel_event_reference(
        analysis,
        event_reference_time_s=reference_s,
        event_reference_source="user_adopted:test",
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=0.0,
    )

    np.testing.assert_array_equal(updated.working_frequency_hz, working_before)
    np.testing.assert_array_equal(
        updated.continuous_apparent_velocity_m_s,
        apparent_before,
    )
    np.testing.assert_array_equal(
        updated.continuous_corrected_velocity_m_s,
        corrected_before,
    )
    assert updated.stft_result is analysis.stft_result
    assert updated.ridge_result is analysis.ridge_result
    assert updated.signal_detection_result.manual_event_reference_time_s == (
        reference_s
    )


def test_export_time_origin_is_explicit_and_default_is_absolute(tmp_path: Path) -> None:
    analysis = _analysis(tmp_path)
    options = ResultExportOptions(
        output_directory=tmp_path,
        analysis_mode=ResultAnalysisMode.AUTOMATIC,
        channel_analyses={"pdv_channel_1": analysis},
        event_reference_source="test",
    )
    assert options.time_origin is ExportTimeOrigin.ABSOLUTE
    report = export_formal_results(options)
    exported = report.exported_channels[0]
    simple = _csv_rows(exported.csv_path)
    detail = _csv_rows(exported.detail_csv_path)
    assert set(simple[0]) == {"time_s", "display_velocity_m_s"}
    assert {"time_s", "time_from_event_s"}.issubset(detail[0])
    assert any(float(row["time_from_event_s"]) == 0.0 for row in detail)
    for simple_row, detail_row in zip(simple, detail, strict=True):
        assert simple_row["time_s"] == detail_row["time_s"]
        assert simple_row["display_velocity_m_s"] == detail_row[
            "display_velocity_m_s"
        ]
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    assert metadata["time_coordinate"]["absolute_time_preserved"] is True
    assert metadata["time_coordinate"]["export_time_origin"] == "absolute"
    assert metadata["time_coordinate"]["simple_csv_time_column"] == (
        "time_s"
    )


def test_absolute_export_retains_relative_detail_and_missing_reference_rules(
    tmp_path: Path,
) -> None:
    analysis = _analysis(tmp_path)
    detection = analysis.signal_detection_result
    without_reference = configure_channel_event_reference(
        analysis,
        event_reference_time_s=None,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=0.0,
    )
    absolute_options = ResultExportOptions(
        output_directory=tmp_path,
        analysis_mode=ResultAnalysisMode.AUTOMATIC,
        channel_analyses={"pdv_channel_1": without_reference},
        time_origin=ExportTimeOrigin.ABSOLUTE,
        event_reference_source=None,
    )
    report = export_formal_results(absolute_options)
    simple = _csv_rows(report.exported_channels[0].csv_path)
    detail = _csv_rows(report.exported_channels[0].detail_csv_path)
    assert set(simple[0]) == {"time_s", "display_velocity_m_s"}
    assert float(simple[0]["time_s"]) == float(detail[0]["time_s"])
    assert float(simple[0]["time_s"]) >= detection.analysis_start_time_s
    assert all(row["time_from_event_s"] == "nan" for row in detail)
    with pytest.raises(ResultExportValidationError, match="formally adopted"):
        export_formal_results(
            ResultExportOptions(
                output_directory=tmp_path,
                analysis_mode=ResultAnalysisMode.AUTOMATIC,
                channel_analyses={"pdv_channel_1": without_reference},
                time_origin=ExportTimeOrigin.EVENT,
                event_reference_source=None,
            )
        )


def test_velocity_postprocessing_reuses_all_upstream_results_and_preserves_nan(
    tmp_path: Path,
) -> None:
    analysis = _analysis(tmp_path)
    upstream = (
        analysis.stft_result,
        analysis.ridge_result,
        analysis.refined_result,
        analysis.signal_detection_result,
        analysis.stream_event_candidates,
        analysis.spectral_quality_result,
        analysis.continuity_result,
        analysis.event_aware_continuity_result,
    )
    apparent_before = analysis.apparent_velocity_m_s.copy()
    updated = configure_channel_velocity_correction(
        analysis,
        velocity_correction_config=VelocityCorrectionConfig(
            window_material=WindowMaterial.NONE,
            measurement_angle_rad=math.radians(60.0),
        ),
        vacuum_wavelength_m=1.55e-6,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=0.0,
    )
    assert upstream == (
        updated.stft_result,
        updated.ridge_result,
        updated.refined_result,
        updated.signal_detection_result,
        updated.stream_event_candidates,
        updated.spectral_quality_result,
        updated.continuity_result,
        updated.event_aware_continuity_result,
    )
    np.testing.assert_array_equal(updated.apparent_velocity_m_s, apparent_before)
    finite = np.isfinite(apparent_before)
    np.testing.assert_allclose(
        updated.corrected_velocity_m_s[finite],
        apparent_before[finite] / math.cos(math.radians(60.0)),
    )
    np.testing.assert_array_equal(
        np.isnan(updated.corrected_velocity_m_s),
        np.isnan(apparent_before),
    )
    assert updated.velocity_correction_result.config.window_material is (
        WindowMaterial.NONE
    )
