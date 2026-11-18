"""Regression coverage for deferred file drops and the Quick Analysis icon."""

from collections.abc import Callable, Iterator
from os import stat_result
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog, QMessageBox

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.gui.data_controller import DataImportController, SignalLoadRequest
from dps_studio.gui.icons import vector_icon
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow


_RAW = Path(__file__).resolve().parents[3] / "data/raw/20260630-1.csv"
_COPY = Qt.DropAction.CopyAction
_MOVE = Qt.DropAction.MoveAction
_BUTTONS = Qt.MouseButton.LeftButton
_MODIFIERS = Qt.KeyboardModifier.NoModifier


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.show()
    qapp.processEvents()
    try:
        yield window
    finally:
        window.close()
        _wait_for_import(window)
        qapp.processEvents()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def _drop(window: MainWindow, path: Path, *, actions: Qt.DropAction = _COPY | _MOVE) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(QPointF(), actions, mime, _BUTTONS, _MODIFIERS)
    window.dropEvent(event)
    assert event.isAccepted()
    assert event.dropAction() == (_COPY if actions & _COPY else event.proposedAction())


def _wait_for_import(window: MainWindow) -> None:
    deadline = monotonic() + 10
    while window._busy and monotonic() < deadline:
        QApplication.processEvents()
        sleep(0.01)
    assert not window._busy
    assert window._import_worker is None


def _observe_modal(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[ImportSettingsDialog], None],
) -> list[ImportSettingsDialog | None]:
    active: list[ImportSettingsDialog | None] = []
    execute = ImportSettingsDialog.exec

    def observe(dialog: ImportSettingsDialog) -> int:
        def click() -> None:
            active.append(dialog if QApplication.activeModalWidget() is dialog else None)
            try:
                respond(dialog)
            finally:
                if dialog.isVisible():
                    dialog.reject()

        QTimer.singleShot(0, dialog, click)
        return execute(dialog)

    monkeypatch.setattr(ImportSettingsDialog, "exec", observe)
    return active


def _click_ok(dialog: ImportSettingsDialog) -> None:
    dialog.button_box.button(QDialogButtonBox.StandardButton.Ok).click()


def test_real_drop_returns_before_import_preview_and_modal_exec(
    window: MainWindow, qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    events: list[str] = []
    import_file = window._import_file
    initialize = ImportSettingsDialog.__init__

    def observe_import(path: Path) -> bool:
        events.append("import")
        return import_file(path)

    def observe_preview(dialog: ImportSettingsDialog, path: Path, parent: MainWindow) -> None:
        events.append("preview")
        initialize(dialog, path, parent)

    def confirm(dialog: ImportSettingsDialog) -> None:
        events.append("modal")
        _click_ok(dialog)

    active = _observe_modal(monkeypatch, confirm)
    monkeypatch.setattr(window, "_import_file", observe_import)
    monkeypatch.setattr(ImportSettingsDialog, "__init__", observe_preview)
    _drop(window, _RAW)
    assert events == []
    assert window._import_worker is None
    events.append("drop returned")
    qapp.processEvents()
    _wait_for_import(window)

    assert events == ["drop returned", "import", "preview", "modal"]
    assert len(active) == 1 and active[0] is not None
    result = window.load_result
    assert result is not None and result.source_path == _RAW
    assert result.row_count == 200_001
    assert result.channel_names == ("pdv_channel_1", "pdv_channel_2")
    record = result.records["pdv_channel_1"]
    assert record.time_s[0] == pytest.approx(7.4395401499e-4)
    assert record.voltage_v[0] == pytest.approx(-8.11304e-4)
    assert window.main_toolbar.grab().save(str(tmp_path / "toolbar.png"))


def test_drag_move_and_drop_reach_main_window_over_raw_plot(
    window: MainWindow, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    views = (
        window.raw_signal_view, window.spectrogram_view, window.ridge_view,
        window.velocity_view, window.acceleration_view, window.comparison_view,
    )
    for view in views:
        assert not view.plot_widget.acceptDrops()
        assert not view.plot_widget.viewport().acceptDrops()

    paths: list[Path] = []
    monkeypatch.setattr(window, "_import_file", paths.append)
    path = tmp_path / "missing.csv"
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.invalid/a.csv"), QUrl.fromLocalFile(str(path))])
    viewport = window.raw_signal_view.plot_widget.viewport()
    position = viewport.rect().center()
    for event_class in (QDragEnterEvent, QDragMoveEvent):
        event = event_class(position, _COPY | _MOVE, mime, _BUTTONS, _MODIFIERS)
        qapp.sendEvent(viewport, event)
        assert event.isAccepted() and event.dropAction() == _COPY
    drop_event = QDropEvent(QPointF(position), _COPY | _MOVE, mime, _BUTTONS, _MODIFIERS)
    qapp.sendEvent(viewport, drop_event)
    assert drop_event.isAccepted() and drop_event.dropAction() == _COPY
    assert paths == []
    qapp.processEvents()
    assert paths == [path]

    mime.setUrls([QUrl("https://example.invalid/a.csv")])
    for event_class in (QDragEnterEvent, QDragMoveEvent):
        event = event_class(QPoint(), _COPY, mime, _BUTTONS, _MODIFIERS)
        qapp.sendEvent(window, event)
        assert not event.isAccepted()
    drop_event = QDropEvent(QPointF(), _COPY, mime, _BUTTONS, _MODIFIERS)
    window.dropEvent(drop_event)
    assert not drop_event.isAccepted()


def test_open_action_cancel_and_repeat_import(
    window: MainWindow, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.csv"
    first.write_text("0,1\n1,2\n", encoding="utf-8")
    second = tmp_path / "second.txt"
    second.write_text("0 10\n1 20\n2 30\n", encoding="utf-8")
    choose = iter(("", str(first), str(second)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (next(choose), ""))
    responses = iter((True, False, True))

    def respond(dialog: ImportSettingsDialog) -> None:
        button = (QDialogButtonBox.StandardButton.Ok if next(responses)
                  else QDialogButtonBox.StandardButton.Cancel)
        dialog.button_box.button(button).click()

    active = _observe_modal(monkeypatch, respond)
    window.action_open_data.trigger()
    assert active == [] and window.load_result is None
    window.action_open_data.trigger()
    _wait_for_import(window)
    result = window.load_result
    assert result is not None and result.source_path == first

    _drop(window, second, actions=_MOVE)
    qapp.processEvents()
    assert window._import_worker is None and window.load_result is result
    window.action_open_data.trigger()
    _wait_for_import(window)
    assert window.load_result is not None and window.load_result.source_path == second
    assert window.load_result.row_count == 3
    assert len(active) == 3 and all(dialog is not None for dialog in active)


def test_drops_during_modal_import_and_pending_close_are_discarded(
    window: MainWindow, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "first.csv"
    source.write_text("0,1\n1,2\n", encoding="utf-8")
    blocked = tmp_path / "blocked.csv"
    worker_started = Event()
    release_worker = Event()
    load = DataImportController.load

    def hold_worker(
        controller: DataImportController, request: SignalLoadRequest,
    ) -> DelimitedSignalLoadResult:
        worker_started.set()
        if not release_worker.wait(10):
            raise TimeoutError("Import test did not release the worker")
        return load(controller, request)

    monkeypatch.setattr(DataImportController, "load", hold_worker)
    active = _observe_modal(monkeypatch, _click_ok)
    modal = QDialog(window)
    modal.open()
    try:
        assert qapp.activeModalWidget() is modal
        _drop(window, blocked)
        qapp.processEvents()
        assert active == [] and window._import_worker is None
    finally:
        modal.reject()
        modal.deleteLater()

    try:
        _drop(window, source)
        qapp.processEvents()
        assert worker_started.wait(5) and window._import_worker is not None
        _drop(window, blocked)
        qapp.processEvents()
        assert window._import_worker is not None
        assert window._pending_drop is None and len(active) == 1
    finally:
        release_worker.set()
        _wait_for_import(window)
    assert window.load_result is not None and window.load_result.source_path == source
    _drop(window, blocked)
    window.close()
    qapp.processEvents()
    assert window._pending_drop is None and len(active) == 1


@pytest.mark.parametrize("kind", ["missing", "directory", "stat_denied"])
def test_drop_of_invalid_path_warns_after_return(
    kind: str, window: MainWindow, qapp: QApplication, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "invalid.csv"
    if kind == "directory":
        path.mkdir()
    if kind == "stat_denied":
        path.touch()
        stat = Path.stat

        def deny(candidate: Path, *args: Any, **kwargs: Any) -> stat_result:
            if candidate == path:
                raise PermissionError(str(candidate))
            return stat(candidate, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", deny)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: warnings.append(message))
    _drop(window, path)
    assert warnings == []
    qapp.processEvents()
    assert len(warnings) == 1 and str(path) in warnings[0]
    assert window._pending_drop is None and window._import_worker is None
    assert window.load_result is None


@pytest.mark.parametrize(("contents", "reason"), [
    pytest.param(b"", "empty", id="empty"),
    pytest.param(b"time,voltage\n0,\0\n1,2\n", "binary", id="binary"),
    pytest.param(b"time,voltage\nstart,high\nstop,low\n", "无效数值", id="non-numeric"),
    pytest.param(b"time,voltage\n0,1\n1,2,3\n", "delimiter", id="inconsistent-columns"),
    pytest.param(b"0," + b"9" * 1_000_000, "preview limit", id="oversized-line"),
    pytest.param(b"0,1\n", "至少需要两行", id="single-row"),
])
def test_bad_preview_warns_without_starting_worker_and_next_drop_succeeds(
    contents: bytes, reason: str, window: MainWindow, qapp: QApplication, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = tmp_path / "invalid.csv"
    bad.write_bytes(contents)
    good = tmp_path / "valid.csv"
    good.write_text("0,1\n1,2\n", encoding="utf-8")
    notices: list[tuple[str, bool]] = []

    def respond(dialog: ImportSettingsDialog) -> None:
        _click_ok(dialog)
        notices.append((dialog.validation_error_label.text(), dialog.isVisible()))

    _observe_modal(monkeypatch, respond)
    _drop(window, bad)
    qapp.processEvents()
    assert len(notices) == 1 and notices[0][1] and reason in notices[0][0]
    assert window._pending_drop is None and window._import_worker is None
    assert window.load_result is None
    _drop(window, good)
    qapp.processEvents()
    _wait_for_import(window)
    assert window.load_result is not None and window.load_result.source_path == good


def test_worker_error_after_successful_preview_clears_busy_state(
    window: MainWindow, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "worker_error.csv"
    source.write_text("0,1\n1,2\n2,3\n3,4\n4,5\n5,invalid\n", encoding="utf-8")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, message: errors.append(message))
    _observe_modal(monkeypatch, _click_ok)
    _drop(window, source)
    qapp.processEvents()
    _wait_for_import(window)
    assert len(errors) == 1 and "Non-numeric field" in errors[0]
    assert window.load_result is None
    source.write_text("0,1\n1,2\n", encoding="utf-8")
    _drop(window, source)
    qapp.processEvents()
    _wait_for_import(window)
    assert window.load_result is not None and window.load_result.source_path == source


@pytest.mark.parametrize("density", [1, 2])
def test_quick_analysis_icon_is_only_a_solid_triangle(qapp: QApplication, density: int) -> None:
    image = vector_icon("quick_analysis").pixmap(QSize(24, 24), density).toImage()
    assert image.width() == image.height() == 24 * density
    for x, y in ((8, 8), (8, 16), (12, 12), (16, 12)):
        assert image.pixelColor(x * density, y * density) == QColor("#1e293b")
    for x in range(15 * density, 22 * density):
        for y in range(16 * density, 23 * density):
            assert image.pixelColor(x, y).alpha() == 0


def test_quick_analysis_keeps_toolbar_alignment(window: MainWindow) -> None:
    toolbar = window.main_toolbar
    buttons = [toolbar.widgetForAction(action) for action in (
        window.action_open_data, window.action_quick_analysis, window.action_export,
    )]
    assert toolbar.iconSize() == QSize(20, 20)
    assert all(button.isVisible() for button in buttons)
    assert len({(button.geometry().y(), button.height()) for button in buttons}) == 1
