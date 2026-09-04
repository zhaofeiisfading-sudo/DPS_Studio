from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from dps_studio.core.export import ExportTimeOrigin
from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import WindowMaterial
from dps_studio.core.workflow import analyze_configuration
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.result_views import finite_velocity_xy_view_range
from dps_studio.gui.state import WorkflowState


def _loaded_result(tmp_path: Path) -> DelimitedSignalLoadResult:
    sample_rate_hz = 5.0e9
    time_s = 744.0e-6 + np.arange(4096, dtype=np.float64) / sample_rate_hz
    active = (time_s >= 744.2e-6) & (time_s < 744.65e-6)
    records: dict[str, SignalRecord] = {}
    for name, frequency_hz in (
        ("pdv_channel_1", 200.0e6),
        ("pdv_channel_2", 260.0e6),
    ):
        voltage_v = np.zeros_like(time_s)
        phase = 2.0 * np.pi * frequency_hz * (time_s - time_s[0])
        voltage_v[active] = np.sin(phase[active])
        records[name] = SignalRecord(time_s, voltage_v)
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "task019a_gui.csv",
        records=records,
        row_count=time_s.size,
        column_count=3,
        channel_names=tuple(records),
        header=None,
        time_column_index=0,
        voltage_column_indices={"pdv_channel_1": 1, "pdv_channel_2": 2},
        unselected_column_indices=(),
        delimiter=",",
        encoding="utf-8",
    )


def _prepare_result(window: MainWindow, tmp_path: Path) -> None:
    window.set_loaded_result(_loaded_result(tmp_path))
    session = window.analysis_session
    configuration = session.run_configuration
    analysis_range = session.analysis_range
    assert configuration is not None and analysis_range is not None
    parameters = configuration.parameters
    analyses = analyze_configuration(
        session.records,
        window_length_samples=parameters.window_length_samples,
        overlap_samples=parameters.overlap_samples,
        nfft=parameters.nfft,
        window_name=parameters.window_name,
        minimum_frequency_hz=parameters.minimum_frequency_hz,
        maximum_frequency_hz=parameters.maximum_frequency_hz,
        analysis_start_time_s=analysis_range.start_time_s,
        analysis_end_time_s=analysis_range.end_time_s,
        vacuum_wavelength_m=configuration.vacuum_wavelength_m,
        detection_config=configuration.detection_config,
        event_candidate_config=configuration.event_candidate_config,
        automatic_ridge_selection_config=(
            configuration.automatic_ridge_selection_config
        ),
        velocity_correction_config=configuration.velocity_correction_config,
    )
    reference_s = float(next(iter(analyses.values())).stft_result.time_s[8])
    session.set_event_reference_time_s(reference_s, source="task019a_gui")
    assert session.accept_results(
        generation_id=session.generation_id,
        analyses=analyses,
    )
    assert session.accept_guided_results(
        generation_id=session.guided_generation_id,
        analyses={"pdv_channel_1": analyses["pdv_channel_1"]},
    )
    window._workflow_state = WorkflowState.RESULT_READY
    window._sync_scientific_view_configuration()
    window._refresh_result_source_views()
    window._apply_state()


def test_velocity_fit_buttons_use_only_visible_finite_curve_data(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        _prepare_result(window, tmp_path)
        view = window.velocity_view
        view.display_velocity_check.setChecked(True)
        window.science_tabs.setCurrentWidget(view)
        qapp.processEvents()
        analysis = next(iter(window.analysis_session.channel_analyses.values()))
        reference_s = analysis.signal_detection_result.manual_event_reference_time_s
        assert reference_s is not None
        start_s = reference_s - 0.1e-6
        end_s = reference_s + 0.1e-6
        view.set_view_configuration(
            analysis_start_time_s=start_s,
            analysis_end_time_s=end_s,
            minimum_frequency_hz=0.0,
            maximum_frequency_hz=1.0,
        )
        assert view.apparent_curve is not None
        assert view.corrected_curve is not None
        view.apparent_curve.setData(
            np.asarray([-0.1, 0.0, 0.2]),
            np.asarray([10.0, 20.0, 1000.0]),
        )
        view.corrected_curve.setData(
            np.asarray([-0.1, 0.0, 0.2]),
            np.asarray([15.0, np.nan, np.nan]),
        )
        view.fit_analysis_range()
        plot_range = view.plot_widget.plotItem.vb.viewRange()
        assert plot_range[0] == pytest.approx([-0.1, 0.1])
        expected_analysis = finite_velocity_xy_view_range(
            (
                (np.asarray([-0.1, 0.0]), np.asarray([10.0, 20.0])),
                (np.asarray([-0.1]), np.asarray([15.0])),
            )
        )
        assert expected_analysis is not None
        assert plot_range[1] == pytest.approx(expected_analysis[1])

        view.apparent_curve.hide()
        view.corrected_curve.setData(
            np.asarray([5.0, 6.0, 7.0]),
            np.asarray([50.0, 60.0, np.nan]),
        )
        view.fit_result_range()
        plot_range = view.plot_widget.plotItem.vb.viewRange()
        assert plot_range[0] == pytest.approx([5.0, 6.0])
        assert plot_range[1] == pytest.approx([49.25, 60.75])
    finally:
        window.close()
        qapp.processEvents()


def test_velocity_hides_only_its_builtin_auto_button_and_has_top_controls(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.velocity_view.plot_widget.plotItem.buttonsHidden
        assert not window.ridge_view.plot_widget.plotItem.buttonsHidden
        assert not window.spectrogram_view.plot_widget.plotItem.buttonsHidden
        assert window.velocity_view.fit_analysis_range_button.text() == (
            "适合分析范围"
        )
        assert window.velocity_view.fit_result_range_button.text() == (
            "适合结果范围"
        )
        assert window.velocity_view.fit_analysis_range_button.toolTip()
        assert window.velocity_view.fit_result_range_button.toolTip()
    finally:
        window.close()
        qapp.processEvents()


def test_step5_step6_share_correction_and_preserve_ready_state_and_upstream(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        _prepare_result(window, tmp_path)
        session = window.analysis_session
        first = next(iter(session.channel_analyses.values()))
        generation = session.generation_id
        guided_generation = session.guided_generation_id
        upstream = (
            first.stft_result,
            first.ridge_result,
            first.refined_result,
            first.signal_detection_result,
            first.stream_event_candidates,
            first.spectral_quality_result,
        )
        apparent = first.apparent_velocity_m_s.copy()
        corrected_before = first.corrected_velocity_m_s.copy()
        analysis_range_before = session.analysis_range

        window.workflow_navigation.setCurrentRow(3)
        none_index = window.window_material_combo.findData(
            WindowMaterial.NONE.value
        )
        window.window_material_combo.setCurrentIndex(none_index)
        window.measurement_angle_spin.setValue(20.0)
        qapp.processEvents()
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert window.workflow_navigation.currentRow() == 3
        assert session.generation_id == generation
        assert session.guided_generation_id == guided_generation
        assert session.analysis_range is analysis_range_before
        assert session.results_valid and session.stft_valid
        assert session.guided_result_is_valid("pdv_channel_1")
        refreshed = next(iter(session.channel_analyses.values()))
        assert upstream == (
            refreshed.stft_result,
            refreshed.ridge_result,
            refreshed.refined_result,
            refreshed.signal_detection_result,
            refreshed.stream_event_candidates,
            refreshed.spectral_quality_result,
        )
        np.testing.assert_array_equal(refreshed.apparent_velocity_m_s, apparent)
        assert not np.array_equal(
            refreshed.corrected_velocity_m_s,
            corrected_before,
            equal_nan=True,
        )
        assert window.export_window_material_combo.currentData() == (
            WindowMaterial.NONE.value
        )
        assert window.export_measurement_angle_spin.value() == pytest.approx(20.0)

        window.workflow_navigation.setCurrentRow(3)
        lif_index = window.export_window_material_combo.findData(
            WindowMaterial.LIF.value
        )
        window.export_window_material_combo.setCurrentIndex(lif_index)
        window.export_measurement_angle_spin.setValue(30.0)
        qapp.processEvents()
        assert window.workflow_navigation.currentRow() == 3
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert window.window_material_combo.currentData() == WindowMaterial.LIF.value
        assert window.measurement_angle_spin.value() == pytest.approx(30.0)
        assert session.run_configuration is not None
        correction = session.run_configuration.velocity_correction_config
        assert correction.window_material is WindowMaterial.LIF
        assert correction.measurement_angle_rad == pytest.approx(
            math.radians(30.0)
        )
        assert "LiF" in window.export_velocity_summary_label.text()
    finally:
        window.close()
        qapp.processEvents()


def test_gui_export_uses_the_visible_shared_correction_and_time_origin(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        _prepare_result(window, tmp_path)
        none_index = window.export_window_material_combo.findData(
            WindowMaterial.NONE.value
        )
        window.export_window_material_combo.setCurrentIndex(none_index)
        window.export_measurement_angle_spin.setValue(25.0)
        window.export_event_time_origin_radio.click()
        output_directory = tmp_path / "export"
        output_directory.mkdir()
        window._set_export_output_directory(output_directory)
        monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
        assert window._export_current_result()

        metadata_path = next(output_directory.glob("*.metadata.json"))
        simple_path = next(
            path
            for path in output_directory.glob("*.csv")
            if not path.name.endswith("_detail.csv")
        )
        detail_path = next(output_directory.glob("*_detail.csv"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        with simple_path.open(encoding="utf-8", newline="") as handle:
            simple = list(csv.DictReader(handle))
        with detail_path.open(encoding="utf-8", newline="") as handle:
            detail = list(csv.DictReader(handle))
        assert set(simple[0]) == {"time_from_event_s", "display_velocity_m_s"}
        assert metadata["time_coordinate"]["export_time_origin"] == "event"
        assert metadata["velocity_correction"]["window"]["material"] == "none"
        assert metadata["velocity_correction"]["angle"]["angle_deg_display"] == (
            pytest.approx(25.0)
        )
        assert all(
            simple_row["display_velocity_m_s"]
            == detail_row["display_velocity_m_s"]
            for simple_row, detail_row in zip(simple, detail, strict=True)
        )
    finally:
        window.close()
        qapp.processEvents()


def test_time_origin_defaults_to_absolute_and_controls_velocity_axis(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        _prepare_result(window, tmp_path)
        session = window.analysis_session
        analysis = next(iter(session.channel_analyses.values()))
        reference_s = analysis.signal_detection_result.manual_event_reference_time_s
        assert reference_s is not None
        assert session.export_time_origin is ExportTimeOrigin.ABSOLUTE
        assert window.export_absolute_time_origin_radio.isChecked()
        assert window.velocity_view.event_reference_line is None

        window.export_event_time_origin_radio.click()
        qapp.processEvents()
        assert session.export_time_origin is ExportTimeOrigin.EVENT
        window.export_absolute_time_origin_radio.click()
        qapp.processEvents()
        assert session.export_time_origin is ExportTimeOrigin.ABSOLUTE
        assert window.velocity_view.event_reference_line is None
    finally:
        window.close()
        qapp.processEvents()


def test_task019a_controls_have_complete_english_translations(
    qapp: QApplication,
) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        labels = {label.text() for label in window.findChildren(QLabel)}
        assert "Time Origin" in labels
        assert "Final Export Velocity" in labels
        assert window.export_event_time_origin_radio.text() == "Event Time = 0"
        assert window.export_absolute_time_origin_radio.text() == (
            "Absolute Experiment Time"
        )
        assert window.velocity_view.fit_analysis_range_button.text() == (
            "Fit Analysis Range"
        )
        assert window.velocity_view.fit_result_range_button.text() == (
            "Fit Result Range"
        )
        assert window.velocity_view.fit_analysis_range_button.toolTip() == (
            "Fit the view to the configured analysis time range."
        )
        assert window.velocity_view.fit_result_range_button.toolTip() == (
            "Fit the view to the currently displayed valid velocity results."
        )
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()
