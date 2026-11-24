"""Navigation, inspector layout and file-drop regressions for the Production shell."""

from pathlib import Path

import pytest
from PySide6.QtCore import QElapsedTimer, QEvent, QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication

from dps_studio.gui.app import translation_manager
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from test_task015_followup import _analysis_window, _wait_for_analysis


@pytest.mark.parametrize("locale", ["en", "zh_CN"])
def test_translated_step_row_and_pinned_actions(qapp: QApplication, tmp_path: Path,
                                               locale: str) -> None:
    manager = translation_manager()
    manager.install(locale)
    window = MainWindow(settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat))
    try:
        window.show()
        nav = window.workflow_navigation
        pages = (
            (window.analysis_range_scroll, window.compute_stft_button),
            (window.ridge_parameter_scroll, window.extract_automatic_ridge_button),
            (window.velocity_parameter_scroll, window.review_export_button),
            (window.export_parameter_scroll, window.export_button),
        )
        for width, height in ((900, 570), (1024, 640)):
            window.resize(width, height)
            qapp.processEvents()
            for row, (scroll, action) in enumerate(pages):
                rect = nav.visualItemRect(nav.item(row))
                assert nav.viewport().rect().contains(rect)
                assert rect.top() == nav.visualItemRect(nav.item(0)).top()
                window.parameter_stack.setCurrentIndex(row)
                qapp.processEvents()
                assert not scroll.isAncestorOf(action)
                assert action.isVisible()
                assert window.rect().contains(action.mapTo(window, action.rect().bottomRight()))
        assert all(not spin.keyboardTracking()
                   for spin in window.parameter_stack.findChildren(QAbstractSpinBox))
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        manager.install("zh_CN")


def test_direct_tab_clicks_and_guided_reentry(qapp: QApplication, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    window = _analysis_window(qapp, tmp_path)
    try:
        window.show()
        assert window.change_data_button.isVisible() and window.open_button.isHidden()
        _wait_for_analysis(window, window.run_automatic_analysis)
        window.select_workflow_step(1)
        assert window.science_tabs.currentWidget() is window.ridge_view
        window.guided_mode_radio.click()
        window.select_workflow_step(0)
        window.select_workflow_step(1)
        assert window.science_tabs.currentWidget() is window.spectrogram_view
        assert window.run_guided_button.isVisible()
        assert window.extract_automatic_ridge_button.isHidden()
        window.automatic_mode_radio.click()
        assert window.extract_automatic_ridge_button.isVisible()
        assert window.run_guided_button.isHidden()
        for view, expected in (
            (window.raw_signal_view, 0), (window.ridge_view, 1),
            (window.velocity_view, 2), (window.spectrogram_view, 1),
            (window.acceleration_view, 2),
        ):
            window.science_tabs.setCurrentWidget(view)
            assert window.workflow_navigation.currentRow() == window.parameter_stack.currentIndex() == expected
            assert window.science_tabs.currentWidget() is view
        for result_view in (window.comparison_view, window.acceleration_view):
            window.review_export_button.click()
            assert window.parameter_stack.currentIndex() == 3
            assert window.velocity_view._export_preview_mode
            window.science_tabs.setCurrentWidget(result_view)
            assert window.parameter_stack.currentIndex() == 2
            assert not window.velocity_view._export_preview_mode
        window.select_workflow_step(3)
        window.export_absolute_time_origin_radio.click()
        window.export_acceleration_check.setChecked(True)
        window._set_export_output_directory(tmp_path)
        assert window.open_export_directory_button.isEnabled()
        opened: list[QUrl] = []
        monkeypatch.setattr(QDesktopServices, "openUrl", opened.append)
        window.open_export_directory_button.click()
        assert opened == [QUrl.fromLocalFile(str(tmp_path))]
        assert window.export_receipt_banner.isHidden()
        assert window._export_current_result()
        bundle_dir = next(tmp_path.glob("*_auto"))
        receipt = window.export_receipt_banner.label.text().splitlines()[1:]
        assert len(receipt) == 6 and all((bundle_dir / name).is_file() for name in receipt)
        assert window.export_receipt_banner.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def test_file_drop_reuses_confirmed_import_settings(qapp: QApplication, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    window = MainWindow()
    source = tmp_path / "signal.DaT"
    source.write_text("0,1\n1,2\n", encoding="utf-8")
    url = QUrl.fromLocalFile(str(source))
    mime = QMimeData()
    args = (Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    try:
        for urls in ([], [QUrl("https://example.invalid/file.csv")]):
            mime.setUrls(urls)
            invalid = QDragEnterEvent(QPoint(), *args)
            window.dragEnterEvent(invalid)
            assert not invalid.isAccepted()
        mime.setUrls([url])
        entered = QDragEnterEvent(QPoint(), *args)
        window.dragEnterEvent(entered)
        assert entered.isAccepted()
        monkeypatch.setattr(ImportSettingsDialog, "exec", lambda self: self.DialogCode.Rejected)
        window.dropEvent(QDropEvent(QPointF(), *args))
        qapp.processEvents()
        assert window.load_result is None and not window._busy
        monkeypatch.setattr(ImportSettingsDialog, "exec", lambda self: self.DialogCode.Accepted)
        dropped = QDropEvent(QPointF(), *args)
        window.dropEvent(dropped)
        assert dropped.isAccepted()
        qapp.processEvents()
        deadline = QElapsedTimer()
        deadline.start()
        while window._busy and deadline.elapsed() < 5000:
            QTest.qWait(10)
        assert window.load_result is not None and window.load_result.source_path == source
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
