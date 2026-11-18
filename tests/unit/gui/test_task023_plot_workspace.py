"""Stage 2 plot, import and waveform-fit cache contracts."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QStyleOptionComboBox, QToolButton
from shiboken6 import Shiboken

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import ManualFrequencyBoundary, ManualFrequencyRegion
from dps_studio.core.workflow.acceleration import channel_dechirp
from dps_studio.gui.app import translation_manager
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.plot_chrome import PlotActionButton, PlotCrosshairHud, PlotSelector
from test_task015_followup import _analysis_window, _wait_for_analysis


def _dispose_window(window: MainWindow, qapp: QApplication) -> None:
    window.close()
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_hud_ignores_bounds_and_reinstalls_once(qapp: QApplication) -> None:
    plot = pg.PlotWidget()
    plot.show()
    x = np.linspace(100, 110, 100)
    plot.plot(x, -x)
    qapp.processEvents()
    plot.autoRange()
    initial = plot.viewRange()
    hud = PlotCrosshairHud(plot, lambda x, y: f"{x:.3f}, {y:.3f}")
    for _ in range(3):
        hud.reinstall()
    assert plot.viewRange() == initial
    for line in hud.lines:
        assert plot.plotItem.items.count(line) == 1
        assert line not in plot.getViewBox().addedItems
        assert line.acceptedMouseButtons() == Qt.MouseButton.NoButton
        assert not line.acceptHoverEvents()
    point = plot.getViewBox().sceneBoundingRect().center()
    plot.scene().sigMouseMoved.emit(point)
    assert all(line.isVisible() for line in hud.lines)
    assert "," in hud.crosshair_readout_label.text()
    for line in hud.lines:
        line.setValue(1e12)
    plot.autoRange()
    np.testing.assert_allclose(plot.viewRange(), initial)
    qapp.sendEvent(plot.viewport(), QEvent(QEvent.Type.Leave))
    assert not any(line.isVisible() for line in hud.lines)
    assert hud.crosshair_readout_label.text() == "—"
    plot.clear()
    hud.reinstall()
    assert set(plot.plotItem.items) == set(hud.lines)
    hud.crosshair_readout_label.deleteLater()
    plot.close()
    plot.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_welcome_action_and_full_zoomed_waveform(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    def choose_file(*args: object) -> tuple[str, str]:
        calls.append(args)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", choose_file)
    window = MainWindow()
    try:
        view = window.raw_signal_view
        window.show()
        qapp.processEvents()
        assert view.empty_state_overlay.isVisible()
        assert view.empty_state_overlay.geometry() == view.plot_widget.geometry()
        view.welcome_open_button.click()
        assert len(calls) == 1
        t = np.arange(80000, dtype=float) / 40e9
        v = np.sin(np.arange(t.size))
        view.set_records({"signal": SignalRecord(t, v)})
        assert not view.empty_state_overlay.isVisible()
        assert "80,000" in view.dataset_badge.text() and "40 GS/s" in view.dataset_badge.text()
        curve = view._curves["signal"]
        view.plot_widget.setXRange(.5, .75, padding=0)
        qapp.processEvents()
        np.testing.assert_array_equal(curve.getData()[0], t * 1e6)
        np.testing.assert_array_equal(curve.getData()[1], v * 1e3)
        np.testing.assert_array_equal(curve.yData, v * 1e3)
        assert curve.opts["clipToView"] and not curve.opts["autoDownsample"]
        view.set_records({})
        assert view.empty_state_overlay.isVisible() and view.dataset_badge.isHidden()
    finally:
        _dispose_window(window, qapp)


def test_preview_roles_follow_edits_and_conflicts(qapp: QApplication, tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("t,A,B\n1,2,3\n4,5,6\n7,8,9\n10,11,12\n", encoding="utf-8")
    dialog = ImportSettingsDialog(path)
    dialog.show()
    table = dialog.preview_table
    assert (table.rowCount(), table.columnCount()) == (4, 3)
    cell = table.item(3, 2)
    assert cell is not None and cell.text() == "12"
    time_header = table.horizontalHeaderItem(0)
    assert time_header is not None and "时间" in time_header.text()
    dialog.channel_1_name.setText("detector")
    signal_header = table.horizontalHeaderItem(1)
    assert signal_header is not None and signal_header.text() == "列 1 · detector"
    dialog.channel_2_column.setValue(1)
    assert dialog.validation_banner.isVisible()
    assert all("c62828" in spin.styleSheet() for spin in (dialog.channel_1_column, dialog.channel_2_column))
    assert not dialog.button_box.styleSheet()
    dialog.channel_2_enabled.setChecked(False)
    assert not dialog.validation_banner.isVisible()
    assert not dialog.channel_1_column.styleSheet()
    dialog.channel_1_column.setValue(0)
    assert "c62828" in dialog.time_column_spin.styleSheet()
    dialog.channel_1_name.clear()
    assert "c62828" in dialog.channel_1_name.styleSheet()
    toggle = dialog.summary_toggle
    assert toggle.property("accordionToggle") is True
    assert toggle.accessibleName() == toggle.text()
    assert not toggle.icon().isNull() and dialog.column_preview_label.isHidden()
    collapsed_icon = toggle.icon().cacheKey()
    toggle.click()
    assert not toggle.icon().isNull() and toggle.icon().cacheKey() != collapsed_icon
    assert dialog.column_preview_label.isVisible()
    toggle.click()
    assert dialog.column_preview_label.isHidden()
    dialog.close()
    dialog.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_dechirp_cache_reuses_corrections_and_invalidates_event_edits(qapp: QApplication, tmp_path: Path) -> None:
    window = _analysis_window(qapp, tmp_path)
    try:
        _wait_for_analysis(window, window.run_automatic_analysis)
        view = window.acceleration_view
        session = window.analysis_session
        channel = view.channel_combo.currentData()
        before = session.channel_analyses[channel]
        record = session.records[channel]
        result = channel_dechirp(record, before, settings=view.dechirp_settings)
        view._cached = view._dechirp_key(record, before), result
        window.lif_b1_spin.setValue(.8)
        corrected = session.channel_analyses[channel]
        assert corrected is not before
        assert view.cached_dechirp(record, corrected) is result
        detection = replace(corrected.signal_detection_result, manual_event_reference_time_s=record.start_time_s)
        assert view.cached_dechirp(record, replace(corrected, signal_detection_result=detection)) is None
        view.dechirp_samples_spin.setValue(1024)
        assert view.cached_dechirp(record, corrected) is None
    finally:
        _dispose_window(window, qapp)


def test_six_english_tabs_and_compact_acceleration_row(qapp: QApplication, tmp_path: Path) -> None:
    manager = translation_manager()
    manager.install("en")
    window: MainWindow | None = None
    try:
        window = _analysis_window(qapp, tmp_path)
        window.show()
        _wait_for_analysis(window, window.run_automatic_analysis)
        view = window.acceleration_view
        window.science_tabs.setCurrentWidget(view)
        for width, height in ((900, 570), (1024, 640)):
            window.resize(width, height)
            qapp.processEvents()
            bar = window.science_tabs.tabBar()
            assert bar.rect().contains(bar.tabRect(5))
            assert not any(b.isVisible() for b in bar.findChildren(QToolButton))
            strip = view.crosshair_readout_label.parentWidget()
            assert strip is not None
            controls = (view.method_combo, view.settings_toggle, view.fit_visible,
                        view.fit_analysis_range_button, view.fit_result_range_button,
                        view.crosshair_readout_label)
            for control in controls:
                assert control.parentWidget() is strip and control.isVisible()
                assert strip.rect().contains(control.geometry())
            for first, second in zip(controls, controls[1:]):
                assert first.geometry().right() < second.geometry().left()
    finally:
        if window is not None:
            _dispose_window(window, qapp)
        manager.install("zh_CN")


def test_corridor_detach_disposes_roi_with_a_queued_refresh(qapp: QApplication, tmp_path: Path) -> None:
    window = _analysis_window(qapp, tmp_path)
    try:
        _wait_for_analysis(window, window.run_automatic_analysis)
        controller = window.spectrogram_view.corridor_controller
        channel, analysis = next(iter(window.analysis_session.channel_analyses.items()))
        stft = analysis.stft_result
        frequency = float(stft.frequency_hz[len(stft.frequency_hz) // 2])
        region = ManualFrequencyRegion(upper_boundary=ManualFrequencyBoundary(
            control_times_s=stft.time_s[[0, -1]],
            control_frequencies_hz=np.array([frequency, frequency]),
        ))
        controller.set_context(channel, stft, region, analysis_start_time_s=None,
                               analysis_end_time_s=None)
        roi = controller._boundary_rois["upper"]
        assert controller.begin_boundary("lower")
        roi.sigRegionChangeFinished.emit(roi)
        assert controller._overlay_timer.isActive()
        controller.detach_context()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert controller.channel_name is None and not controller.drawing
        assert not controller._boundary_rois and not controller._overlay_timer.isActive()
        assert not Shiboken.isValid(roi)
    finally:
        _dispose_window(window, qapp)


@pytest.mark.parametrize(("locale", "all_channels"), [("zh_CN", "全部通道"), ("en", "All channels")])
def test_desktop_plot_chrome(
    qapp: QApplication, tmp_path: Path, locale: str, all_channels: str,
) -> None:
    manager = translation_manager()
    manager.install(locale)
    window: MainWindow | None = None
    try:
        window = _analysis_window(qapp, tmp_path)
        window.resize(1366, 768)
        window.show()
        _wait_for_analysis(window, window.run_automatic_analysis)
        raw, spec, acceleration = window.raw_signal_view, window.spectrogram_view, window.acceleration_view
        for page, selector, caption in (
            (raw, raw.channel_combo, all_channels),
            (raw, raw.channel_combo, "pdv_channel_1"),
            (spec, spec.channel_combo, "pdv_channel_1"),
            (spec, spec.colormap_combo, "Viridis"),
        ):
            assert isinstance(selector, PlotSelector)
            window.science_tabs.setCurrentWidget(page)
            index = selector.findText(caption)
            assert index >= 0
            selector.setCurrentIndex(index)
            qapp.processEvents()
            option = QStyleOptionComboBox()
            selector.initStyleOption(option)
            assert option.currentText == caption
        assert window.ridge_view.quality_label.wordWrap()
        assert spec.definition_label.wordWrap()
        assert all(button.property("plotAction") is True for button in acceleration.findChildren(PlotActionButton))
        if qapp.platformName() != "windows":
            return
        window.science_tabs.setCurrentWidget(acceleration)
        for width, height in ((1280, 720), (1366, 768), (1440, 900)):
            window.resize(width, height)
            qapp.processEvents()
            for button in acceleration.findChildren(PlotActionButton):
                if button.isVisible():
                    assert button.toolButtonStyle() == button.full_style, (locale, width, button.text())
            plot = acceleration.plot_widget
            plot.scene().sigMouseMoved.emit(plot.getViewBox().sceneBoundingRect().center())
            assert " · " in acceleration.crosshair_readout_label.text()
    finally:
        if window is not None:
            _dispose_window(window, qapp)
        manager.install("zh_CN")
