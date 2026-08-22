from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import velocity_correction_metadata
from dps_studio.gui.app import translation_manager
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _event_result(tmp_path: Path, *, sample_interval_s: float = 25.0e-12) -> DelimitedSignalLoadResult:
    sample_count = 8192
    time_s = 744.0e-6 + np.arange(sample_count, dtype=np.float64) * sample_interval_s
    onset_s = time_s[0] + 60.0e-9
    active = time_s >= onset_s
    phase = 2.0 * np.pi * 0.65e9 * (time_s - onset_s)
    voltage_v = np.zeros_like(time_s)
    voltage_v[active] = np.sin(phase[active])
    records = {"pdv_channel_1": SignalRecord(time_s, voltage_v)}
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "experiment.csv",
        records=records,
        row_count=sample_count,
        column_count=2,
        channel_names=tuple(records),
        header=None,
        time_column_index=0,
        voltage_column_indices={"pdv_channel_1": 1},
        unselected_column_indices=(),
        delimiter=",",
        encoding="utf-8",
    )


def _wait_for_analysis(window: MainWindow, start: object) -> None:
    loop = QEventLoop()
    failures: list[str] = []
    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(
        lambda _generation, error_type, message, _traceback: (
            failures.append(f"{error_type}: {message}"),
            loop.quit(),
        )
    )
    start()
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()
    assert not failures
    assert not window._analysis_adapter.busy


def test_import_dialog_keeps_buttons_outside_scroll_area(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "three_columns.csv"
    source.write_text("0,1,2\n1,3,4\n", encoding="utf-8")
    dialog = ImportSettingsDialog(source)
    try:
        dialog.show()
        qapp.processEvents()
        assert not dialog.scroll_area.isAncestorOf(dialog.button_box)
        assert dialog.button_box.parentWidget() is dialog
        assert dialog.height() <= int(dialog.screen().availableGeometry().height() * 0.85)
        dialog.resize(520, 400)
        qapp.processEvents()
        assert dialog.button_box.isVisibleTo(dialog)
        assert dialog.load_request().time_column == 0
    finally:
        dialog.close()


@pytest.mark.parametrize(
    ("screen_width", "screen_height"),
    ((1920, 1080), (1440, 900), (1366, 768)),
)
def test_import_dialog_initial_size_fits_common_work_areas(
    screen_width: int,
    screen_height: int,
) -> None:
    width, height = ImportSettingsDialog._bounded_initial_size(
        screen_width,
        screen_height,
    )
    assert width <= int(screen_width * 0.85)
    assert height <= int(screen_height * 0.85)
    assert width >= 480
    assert height >= 400


def test_range_reset_commits_directly_and_has_no_current_view_action(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        panel = window.analysis_range_panel
        panel.set_data_bounds(1.0e-6, 2.0e-6)
        panel.set_draft_range_s(1.2e-6, 1.8e-6)
        confirmed: list[tuple[float, float]] = []
        panel.range_confirmed.connect(lambda start, end: confirmed.append((start, end)))
        panel.full_range_button.click()
        qapp.processEvents()
        assert panel.draft_range_s == pytest.approx((1.0e-6, 2.0e-6))
        assert confirmed == [pytest.approx((1.0e-6, 2.0e-6))]
        assert not hasattr(panel, "current_view_button")

        visible_button_text = {
            button.text() for button in panel.findChildren(type(panel.apply_button))
        }
        assert "使用当前显示范围" not in visible_button_text
    finally:
        window.close()


def test_one_click_runs_full_workflow_and_candidate_detection_does_not_confirm(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    one_click = MainWindow(translation_manager=translation_manager())
    candidate = MainWindow(translation_manager=translation_manager())
    try:
        result = _event_result(tmp_path)
        one_click.set_loaded_result(result)
        assert one_click.action_automatic.text() == "一键分析"
        assert one_click.action_automatic.isEnabled()
        _wait_for_analysis(one_click, one_click.action_automatic.trigger)
        assert one_click.workflow_state is WorkflowState.RESULT_READY
        assert one_click.science_tabs.currentIndex() == 3

        candidate.set_loaded_result(result)
        assert candidate.analysis_session.event_reference_time_s is None
        _wait_for_analysis(
            candidate,
            candidate.analysis_range_panel.detect_candidates_button.click,
        )
        assert candidate.analysis_session.event_reference_time_s is None
        assert candidate.analysis_range_panel.confirmed_event_reference_s is None
        assert candidate.science_tabs.currentIndex() == 0
        assert candidate.workflow_state is WorkflowState.RANGE_DEFINED
        assert not candidate.analysis_session.stft_valid
        assert not candidate.analysis_session.any_formal_results_available
        assert candidate.analysis_range_panel.candidate_labels
        assert "primary" not in candidate.analysis_range_panel.candidate_heading.text().lower()
        if candidate.analysis_range_panel.candidate_buttons:
            button = next(iter(candidate.analysis_range_panel.candidate_buttons.values()))
            button.click()
            qapp.processEvents()
            assert candidate.analysis_session.event_reference_time_s is not None
            candidate.analysis_range_panel.clear_event_reference_button.click()
            qapp.processEvents()
            assert candidate.analysis_session.event_reference_time_s is None
    finally:
        one_click.close()
        candidate.close()


def test_search_band_defaults_nyquist_spin_and_graphical_sync(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.minimum_frequency_spin.value() == pytest.approx(0.05)
        assert window.maximum_frequency_spin.value() == pytest.approx(6.0)
        assert window.minimum_frequency_spin.singleStep() == pytest.approx(1.0)
        assert window.maximum_frequency_spin.singleStep() == pytest.approx(1.0)
        window.minimum_frequency_spin.setValue(0.125)
        assert window.minimum_frequency_spin.value() == pytest.approx(0.125)

        low_nyquist = _event_result(tmp_path, sample_interval_s=100.0e-12)
        window.set_loaded_result(low_nyquist)
        assert window.maximum_frequency_spin.maximum() == pytest.approx(5.0)
        assert window.maximum_frequency_spin.value() == pytest.approx(5.0)

        window.set_loaded_result(_event_result(tmp_path))
        _wait_for_analysis(window, window.action_automatic.trigger)
        session = window.analysis_session
        stft = next(iter(session.stft_results.values()))
        original_stft = stft
        grid_hz = stft.frequency_hz
        lower_hz = float(grid_hz[40])
        lower_line = window.spectrogram_view._search_lines[0]
        assert lower_line.cursor().shape() is Qt.CursorShape.SizeVerCursor
        assert lower_line.toolTip()
        lower_line.setPos(lower_hz * 1e-9)
        window.spectrogram_view._search_boundary_finished(0)
        qapp.processEvents()
        configuration = session.run_configuration
        assert configuration is not None
        assert configuration.parameters.minimum_frequency_hz == pytest.approx(lower_hz)
        assert window.minimum_frequency_spin.value() == pytest.approx(lower_hz * 1e-9)
        assert session.stft_valid
        assert next(iter(session.stft_results.values())) is original_stft
        assert not session.automatic_results_available
        assert not session.guided_results_available
        assert not session.any_formal_results_available

        upper_hz = float(grid_hz[500])
        upper_line = window.spectrogram_view._search_lines[1]
        upper_line.setPos(upper_hz * 1e-9)
        window.spectrogram_view._search_boundary_finished(1)
        qapp.processEvents()
        configuration = session.run_configuration
        assert configuration is not None
        assert configuration.parameters.maximum_frequency_hz == pytest.approx(upper_hz)
        assert configuration.parameters.minimum_frequency_hz < upper_hz

        window.minimum_frequency_spin.setValue(0.25)
        qapp.processEvents()
        assert window.spectrogram_view._search_lines[0].value() == pytest.approx(0.25)
        before = configuration.parameters.minimum_frequency_hz
        window.spectrogram_view.plot_widget.setYRange(0.0, 1.0, padding=0.0)
        qapp.processEvents()
        current = session.run_configuration
        assert current is not None
        assert current.parameters.minimum_frequency_hz != before
        scientific_lower = current.parameters.minimum_frequency_hz
        window.spectrogram_view.plot_widget.setYRange(1.0, 2.0, padding=0.0)
        qapp.processEvents()
        assert session.run_configuration is not None
        assert session.run_configuration.parameters.minimum_frequency_hz == scientific_lower
    finally:
        window.close()


def test_custom_lif_updates_only_correction_and_metadata(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_event_result(tmp_path))
        _wait_for_analysis(window, window.action_automatic.trigger)
        session = window.analysis_session
        before = next(iter(session.channel_analyses.values()))
        upstream = (
            before.stft_result,
            before.ridge_result,
            before.refined_result,
            before.signal_detection_result,
            before.spectral_quality_result,
        )
        apparent = before.apparent_velocity_m_s.copy()
        corrected = before.corrected_velocity_m_s.copy()
        generation = session.generation_id

        window.lif_b1_spin.setValue(0.8)
        qapp.processEvents()
        after = next(iter(session.channel_analyses.values()))
        assert session.generation_id == generation
        assert upstream == (
            after.stft_result,
            after.ridge_result,
            after.refined_result,
            after.signal_detection_result,
            after.spectral_quality_result,
        )
        np.testing.assert_array_equal(after.apparent_velocity_m_s, apparent)
        assert not np.array_equal(after.corrected_velocity_m_s, corrected, equal_nan=True)
        assert session.run_configuration is not None
        assert session.run_configuration.velocity_correction_config.lif_model.b1 == 0.8
        metadata = velocity_correction_metadata(after.velocity_correction_result)
        metadata_window = metadata["window"]
        assert isinstance(metadata_window, dict)
        assert metadata_window["b1"] == 0.8
        assert metadata_window["parameter_provenance"] == "user_custom"
        assert metadata_window["custom_parameters"] is True
        assert "Custom LiF" in window.lif_provenance_label.text()

        window.restore_lif_defaults_button.click()
        qapp.processEvents()
        assert session.run_configuration is not None
        restored = session.run_configuration.velocity_correction_config.lif_model
        assert restored.b1 == pytest.approx(0.7895)
        assert restored.b2 == pytest.approx(0.9918)
        assert "Custom LiF" not in window.lif_provenance_label.text()
        assert window.export_window_material_combo is window.window_material_combo
        assert window.export_measurement_angle_spin is window.measurement_angle_spin
    finally:
        window.close()


def test_new_usability_controls_have_finished_english_translations(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "translation_smoke.csv"
    source.write_text("0,1\n1,2\n", encoding="utf-8")
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    dialog = ImportSettingsDialog(source)
    try:
        assert window.action_automatic.text() == "Run Analysis"
        assert window.analysis_range_panel.full_range_button.text() == "Reset"
        assert (
            window.analysis_range_panel.detect_candidates_button.text()
            == "Detect Candidates"
        )
        assert "Recommended Candidates" in (
            window.analysis_range_panel.candidate_heading.text()
        )
        assert window.window_length_spin.suffix() == " samples"
        assert window.hop_label.text().endswith("samples")
        assert window.automatic_ridge_extraction_combo.currentText() == (
            "Continuity-assisted"
        )
        assert window.lif_parameter_toggle.text() == "Material Parameters…"
        assert window.restore_lif_defaults_button.text() == "Restore LiF Defaults"
        assert dialog.windowTitle() == "Data Import Settings"
        assert dialog.button_box.parentWidget() is dialog
    finally:
        dialog.close()
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()
