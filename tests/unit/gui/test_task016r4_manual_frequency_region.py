from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.ridge import (
    ManualFrequencyBoundary,
    ManualFrequencyRegion,
)
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.analysis_adapter import AnalysisResultSource
from dps_studio.gui.analysis_session import EventTimeSource, RidgeExtractionMode
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.ridge_corridor import draw_static_corridor


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _window(qapp: QApplication, tmp_path: Path) -> MainWindow:
    sample_rate_hz = 40.0e9
    time_s = 5.54e-4 + np.arange(4096, dtype=np.float64) / sample_rate_hz
    relative_s = time_s - time_s[0]
    values = np.column_stack(
        (
            time_s,
            np.sin(2.0 * np.pi * 0.63e9 * relative_s),
            np.sin(2.0 * np.pi * 0.82e9 * relative_s + 0.2),
        )
    )
    source = tmp_path / "task016r4_dual_channel.csv"
    np.savetxt(source, values, delimiter=",", fmt="%.17e")
    loaded = DataImportController().load(
        SignalLoadRequest(
            path=source,
            time_column=0,
            channels=(
                ChannelImportSpec("pdv_channel_1", 1, 1.0),
                ChannelImportSpec("pdv_channel_2", 2, 1.0),
            ),
            delimiter=",",
            has_header=False,
            encoding="utf-8",
            time_scale=1.0,
        )
    )
    window = MainWindow(translation_manager=translation_manager())
    window.set_loaded_result(loaded)
    window.set_analysis_configuration(
        load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    )
    window.analysis_range_panel.use_full_range()
    qapp.processEvents()
    return window


def _wait(
    window: MainWindow,
    launch: Any,
    *,
    expected_source: AnalysisResultSource,
) -> None:
    loop = QEventLoop()
    state = {"timed_out": False, "error": None}

    def timeout() -> None:
        state["timed_out"] = True
        loop.quit()

    def failed(
        _generation: int,
        error_type: str,
        message: str,
        _traceback: str,
    ) -> None:
        state["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(15_000, timeout)
    assert launch()
    assert window._pending_analysis_source is expected_source
    loop.exec()
    assert not state["timed_out"]
    assert state["error"] is None


def _region(
    window: MainWindow,
    channel_name: str,
    *,
    center_hz: float,
    both: bool = True,
) -> ManualFrequencyRegion:
    stft = window.analysis_session.stft_results[channel_name]
    times = np.array([stft.time_s[2], stft.time_s[-3]])
    upper = ManualFrequencyBoundary(
        times,
        np.array([center_hz + 110.0e6, center_hz + 130.0e6]),
    )
    lower = (
        ManualFrequencyBoundary(
            times,
            np.array([center_hz - 110.0e6, center_hz - 90.0e6]),
        )
        if both
        else None
    )
    return ManualFrequencyRegion(upper_boundary=upper, lower_boundary=lower)


def _select_channel(window: MainWindow, channel_name: str) -> None:
    combo = window.spectrogram_view.channel_combo
    index = combo.findData(channel_name)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_manual_mode_defaults_to_full_band_and_runs_without_boundaries(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(
            window,
            window.run_stft_analysis,
            expected_source=AnalysisResultSource.SPECTROGRAM,
        )
        assert window.findChild(QObject, "corridorHalfWidthMhz") is None
        window.guided_mode_radio.click()
        qapp.processEvents()

        controller = window.spectrogram_view.corridor_controller
        assert window.ridge_extraction_mode is RidgeExtractionMode.GUIDED
        assert window.guided_mode_radio.text() == "人工范围"
        assert window.run_guided_button.isEnabled()
        assert "完整搜索频带" in window.guided_status_label.text()
        assert controller.constraint is None
        assert controller._fill_item is not None
        assert controller._fill_item.isVisible()

        stft = window.analysis_session.stft_results["pdv_channel_1"]
        assert controller.begin_boundary("upper")
        controller._draft_points = [(float(stft.time_s[3]), 0.75e9)]
        controller._refresh_draft()
        assert controller.finish_drawing()
        assert controller.constraint is None
        assert not window.analysis_session.ridge_constraints

        _wait(
            window,
            window.run_guided_analysis,
            expected_source=AnalysisResultSource.GUIDED,
        )
        assert set(window.analysis_session.valid_guided_channel_analyses) == {
            "pdv_channel_1"
        }
        assert not window.analysis_session.ridge_constraints

        window.automatic_mode_radio.click()
        qapp.processEvents()
        assert window.ridge_extraction_mode is RidgeExtractionMode.AUTOMATIC
        assert not controller._fill_item.isVisible()
        window.guided_mode_radio.click()
        qapp.processEvents()
        assert controller._fill_item.isVisible()

        window.resize(1280, 720)
        window.show()
        qapp.processEvents()
        assert window.ridge_parameter_scroll.widgetResizable()
        assert all(size > 0 for size in window.workspace_splitter.sizes())
    finally:
        window.close()
        qapp.processEvents()


def test_boundaries_are_channel_local_and_cursor_undo_clear_are_stable(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(
            window,
            window.run_stft_analysis,
            expected_source=AnalysisResultSource.SPECTROGRAM,
        )
        window.guided_mode_radio.click()
        region_1 = _region(window, "pdv_channel_1", center_hz=0.63e9)
        region_2 = _region(
            window,
            "pdv_channel_2",
            center_hz=0.82e9,
            both=False,
        )
        window._ridge_constraint_changed("pdv_channel_1", region_1)
        _select_channel(window, "pdv_channel_2")
        window._ridge_constraint_changed("pdv_channel_2", region_2)
        qapp.processEvents()

        controller = window.spectrogram_view.corridor_controller
        assert controller.constraint is region_2
        assert window.upper_boundary_point_count_label.text() == "2"
        assert window.lower_boundary_point_count_label.text() == "0"
        _select_channel(window, "pdv_channel_1")
        qapp.processEvents()
        assert controller.constraint is region_1
        assert window.lower_boundary_point_count_label.text() == "2"

        window.edit_upper_boundary_button.click()
        qapp.processEvents()
        assert controller.drawing
        assert controller.active_boundary == "upper"
        assert (
            window.spectrogram_view.plot_widget.cursor().shape()
            is Qt.CursorShape.CrossCursor
        )
        window.action_cancel_corridor_drawing.trigger()
        qapp.processEvents()
        assert not controller.drawing
        assert (
            window.spectrogram_view.plot_widget.cursor().shape()
            is Qt.CursorShape.ArrowCursor
        )
        assert controller.constraint is region_1

        window.edit_lower_boundary_button.click()
        qapp.processEvents()
        assert controller.active_boundary == "lower"
        window.science_tabs.setCurrentWidget(window.raw_signal_view)
        qapp.processEvents()
        assert not controller.drawing
        assert (
            window.spectrogram_view.plot_widget.cursor().shape()
            is Qt.CursorShape.ArrowCursor
        )

        window.science_tabs.setCurrentWidget(window.spectrogram_view)
        window.edit_lower_boundary_button.click()
        stft = window.analysis_session.stft_results["pdv_channel_1"]
        controller._draft_points = [
            (float(stft.time_s[3]), 0.90e9),
            (float(stft.time_s[-4]), 0.90e9),
        ]
        controller._refresh_draft()
        controller._commit_live_draft()
        qapp.processEvents()
        assert controller.invalid_draft
        assert not window.run_guided_button.isEnabled()
        assert "交叉" in window.guided_status_label.text()
        assert window.analysis_session.ridge_constraints["pdv_channel_1"] is region_1

        window.undo_corridor_button.click()
        qapp.processEvents()
        assert not controller.invalid_draft
        assert window.run_guided_button.isEnabled()
        window.action_cancel_corridor_drawing.trigger()
        window.clear_corridor_button.click()
        qapp.processEvents()
        assert "pdv_channel_1" not in window.analysis_session.ridge_constraints
        assert window.analysis_session.ridge_constraints["pdv_channel_2"] is region_2
        assert "完整搜索频带" in window.guided_status_label.text()
        assert controller._fill_item is not None
    finally:
        window.close()
        qapp.processEvents()


def test_decreasing_draft_times_are_rejected_without_sorting(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(
            window,
            window.run_stft_analysis,
            expected_source=AnalysisResultSource.SPECTROGRAM,
        )
        window.guided_mode_radio.click()
        controller = window.spectrogram_view.corridor_controller
        assert controller.begin_boundary("upper")
        stft = window.analysis_session.stft_results["pdv_channel_1"]
        controller._draft_points = [
            (float(stft.time_s[-3]), 0.8e9),
            (float(stft.time_s[3]), 0.7e9),
        ]
        controller._refresh_draft()
        controller._commit_live_draft()
        qapp.processEvents()

        assert controller.invalid_draft
        assert not window.analysis_session.ridge_constraints
        assert "从左到右" in window.guided_status_label.text()
        assert controller._draft_points[0][0] > controller._draft_points[1][0]
    finally:
        window.close()
        qapp.processEvents()


def test_r5_allowed_fill_uses_endpoint_extension_and_editing_hides_handles(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(
            window,
            window.run_stft_analysis,
            expected_source=AnalysisResultSource.SPECTROGRAM,
        )
        window.guided_mode_radio.click()
        stft = window.analysis_session.stft_results["pdv_channel_1"]
        upper = ManualFrequencyBoundary(
            np.asarray([stft.time_s[5], stft.time_s[-6]]),
            np.asarray([0.72e9, 0.76e9]),
        )
        window._ridge_constraint_changed(
            "pdv_channel_1",
            ManualFrequencyRegion(upper_boundary=upper),
        )
        qapp.processEvents()
        controller = window.spectrogram_view.corridor_controller
        _x, upper_ghz = controller._upper_curve.getData()
        _x, lower_ghz = controller._lower_curve.getData()
        assert upper_ghz[0] == pytest.approx(0.72)
        assert upper_ghz[-1] == pytest.approx(0.76)
        assert np.all(lower_ghz < upper_ghz)
        configuration = window.analysis_session.run_configuration
        assert configuration is not None
        fill, _label, (static_upper, static_lower) = draw_static_corridor(
            window.spectrogram_view.plot_widget,
            ManualFrequencyRegion(upper_boundary=upper),
            center_name="manual-static-regression",
            stft_result=stft,
            minimum_frequency_hz=configuration.parameters.minimum_frequency_hz,
            maximum_frequency_hz=configuration.parameters.maximum_frequency_hz,
        )
        assert fill is not None
        assert static_upper.getData()[1][0] == pytest.approx(0.72)
        assert static_lower.getData()[1][0] == pytest.approx(
            configuration.parameters.minimum_frequency_hz * 1.0e-9
        )

        search_lines = tuple(window.spectrogram_view._search_lines)
        assert search_lines and all(line.isVisible() for line in search_lines)
        assert controller.begin_boundary("upper")
        qapp.processEvents()
        assert all(not line.isVisible() for line in search_lines)
        assert all(not line.movable for line in search_lines)
        controller.cancel_drawing()
        qapp.processEvents()
        assert all(line.isVisible() for line in search_lines)
        assert all(line.movable for line in search_lines)
    finally:
        window.close()
        qapp.processEvents()


def test_r5_mode_click_is_one_shot_fit_and_velocity_has_no_event_line(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(
            window,
            window.run_stft_analysis,
            expected_source=AnalysisResultSource.SPECTROGRAM,
        )
        plot = window.spectrogram_view.plot_widget
        plot.setXRange(-10.0, -5.0, padding=0.0)
        plot.setYRange(4.0, 5.0, padding=0.0)
        window.guided_mode_radio.click()
        qapp.processEvents()
        fitted = plot.plotItem.vb.viewRange()
        assert window.science_tabs.currentWidget() is window.spectrogram_view
        assert window.workflow_navigation.currentRow() == 1
        assert fitted[0][0] > 500.0
        plot.setXRange(-20.0, -10.0, padding=0.0)
        before_refresh = plot.plotItem.vb.viewRange()
        window._sync_guided_panel()
        qapp.processEvents()
        assert plot.plotItem.vb.viewRange() == before_refresh

        window.automatic_mode_radio.click()
        qapp.processEvents()
        assert plot.plotItem.vb.viewRange()[0][0] > 500.0
        _wait(
            window,
            window.run_staged_automatic_analysis,
            expected_source=AnalysisResultSource.AUTOMATIC,
        )
        assert window.velocity_view.event_reference_line is None
    finally:
        window.close()
        qapp.processEvents()


def test_four_step_direct_commit_and_optional_manual_event_reference(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        panel = window.analysis_range_panel
        assert window.parameter_stack.count() == 4
        assert tuple(
            window.workflow_navigation.item(index).text() for index in range(4)
        ) == (
            "1  数据与时频",
            "2  脊线提取",
            "3  速度结果",
            "4  复核与导出",
        )
        assert panel.apply_button.isHidden()
        assert panel.apply_event_reference_button.isHidden()
        assert panel.unset_event_time_radio.isChecked()
        assert not panel.event_reference_spin.isEnabled()
        assert window.analysis_session.event_time_source is EventTimeSource.UNSET

        start_s, end_s = window.analysis_session.data_bounds_s()
        manual_s = 0.5 * (start_s + end_s)
        panel.event_reference_spin.setValue(manual_s * 1.0e6)
        panel.manual_event_time_radio.click()
        qapp.processEvents()
        assert panel.event_reference_spin.isEnabled()
        assert window.analysis_session.event_time_source is EventTimeSource.MANUAL
        assert window.analysis_session.event_reference_time_s == pytest.approx(manual_s)
        with pytest.raises(ValueError, match="inside"):
            window.analysis_session.set_event_reference_time_s(end_s + 1.0)

        panel.automatic_event_time_radio.click()
        qapp.processEvents()
        assert window.analysis_session.event_time_source is EventTimeSource.UNSET
        assert not panel.event_reference_spin.isEnabled()
    finally:
        window.close()
        qapp.processEvents()
