"""Regression tests for Production workstation state and import mapping."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio.gui.data_controller import ChannelImportSpec, SignalLoadRequest
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


@pytest.fixture
def workstation(qapp: QApplication, tmp_path: Path) -> MainWindow:
    window = MainWindow(settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat))
    window.show()
    qapp.processEvents()
    return window


def _request(tmp_path: Path, name: str) -> SignalLoadRequest:
    path = tmp_path / name
    time_s = np.arange(8192) * 25e-12
    voltage_v = 0.1 * np.sin(2 * np.pi * 650e6 * time_s)
    np.savetxt(path, np.column_stack((time_s, voltage_v)), delimiter=",")
    return SignalLoadRequest(
        path, 0, (ChannelImportSpec("signal", 1, 1.0, "V"),), ",", False, "utf-8", 1.0, "s",
    )


def _wait_idle(window: MainWindow) -> None:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: None if window._busy else loop.quit())
    timer.start()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    timer.stop()
    assert not window._busy


def test_second_analysis_does_not_redirect_pending_result(
    workstation: MainWindow, tmp_path: Path,
) -> None:
    request = _request(tmp_path, "first.csv")
    workstation.set_loaded_result(workstation._data_controller.load(request))
    assert workstation.run_stft_analysis()
    assert not workstation.run_automatic_analysis()
    assert not workstation.run_event_candidate_detection()
    assert not workstation.action_open_data.isEnabled()
    assert not workstation._start_import(request)
    _wait_idle(workstation)
    assert workstation.workflow_state is WorkflowState.STFT_READY
    assert workstation.workflow_navigation.currentRow() == 1
    assert workstation.science_tabs.currentWidget() is workstation.spectrogram_view


def test_reload_leaves_export_page_and_clears_the_previous_record(
    workstation: MainWindow, tmp_path: Path,
) -> None:
    first = _request(tmp_path, "first.csv")
    workstation.set_loaded_result(workstation._data_controller.load(first))
    assert workstation.run_automatic_analysis()
    _wait_idle(workstation)
    acceleration = workstation.acceleration_view
    workstation.science_tabs.setCurrentWidget(acceleration)
    assert acceleration.acceleration_curve is not None
    assert workstation.select_workflow_step(3)
    assert workstation.science_tabs.currentWidget() is workstation.velocity_view
    assert workstation.select_workflow_step(2)
    workstation.science_tabs.setCurrentWidget(acceleration)
    assert acceleration.acceleration_curve is not None
    assert workstation.select_workflow_step(3)
    second = _request(tmp_path, "second.csv")
    assert workstation._start_import(second)
    _wait_idle(workstation)
    assert workstation.analysis_session.source_path == second.path
    assert workstation.workflow_navigation.currentRow() == 0
    assert workstation.parameter_stack.currentIndex() == 0
    assert workstation.science_tabs.currentWidget() is workstation.raw_signal_view
    assert not workstation.analysis_session.any_formal_results_available
    assert acceleration.acceleration_curve is None
    assert not workstation.action_export.isEnabled()


def test_failed_background_import_preserves_data_and_reports_once(
    workstation: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _request(tmp_path, "good.csv")
    original = workstation._data_controller.load(first)
    workstation.set_loaded_result(original)
    bad = _request(tmp_path, "bad.csv")
    bad.path.write_text("0,1\n0,2\n", encoding="utf-8")
    errors: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _parent, _title, text: errors.append(text))
    assert workstation._start_import(bad)
    _wait_idle(workstation)
    assert workstation.load_result is original
    assert workstation.action_open_data.isEnabled()
    assert len(errors) == 1


def test_close_waits_for_import_worker_without_replacing_record(
    workstation: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    request = _request(tmp_path, "queued.csv")
    load = workstation._data_controller.load
    release = Event()

    def delayed_load(request: SignalLoadRequest) -> object:
        assert release.wait(5)
        return load(request)

    monkeypatch.setattr(workstation._data_controller, "load", delayed_load)
    assert workstation._start_import(request)
    try:
        assert not workstation.close()
        assert workstation.isVisible()
    finally:
        release.set()
    _wait_idle(workstation)
    qapp.processEvents()
    assert not workstation.isVisible()
    assert workstation.load_result is None


def test_header_override_updates_preview_and_keeps_explicit_mapping(
    qapp: QApplication, tmp_path: Path,
) -> None:
    path = tmp_path / "mapping.dat"
    path.write_text("0 200 900\n1 201 901\n2 202 902\n", encoding="utf-8")
    dialog = ImportSettingsDialog(path)
    try:
        assert not dialog.header_check.isChecked()
        assert "无表头" in dialog.column_preview_label.text()
        dialog.header_check.setChecked(True)
        assert "列 1 · 200：201, 202" in dialog.column_preview_label.text()
        dialog.time_unit_combo.setCurrentIndex(2)
        dialog.channel_1_unit.setCurrentIndex(1)
        request = dialog.load_request()
        assert request.has_header and request.time_scale == 1e-6
        assert request.channels[0].voltage_scale == 1e-3
    finally:
        dialog.close()


def test_invalid_time_range_disables_compute_until_reset(
    workstation: MainWindow, tmp_path: Path,
) -> None:
    request = _request(tmp_path, "range.csv")
    workstation.set_loaded_result(workstation._data_controller.load(request))
    panel = workstation.analysis_range_panel
    panel.end_spin.setValue(panel.start_spin.value())
    assert not workstation.compute_stft_button.isEnabled()
    assert not workstation.run_stft_analysis()
    panel.full_range_button.click()
    assert workstation.compute_stft_button.isEnabled()
