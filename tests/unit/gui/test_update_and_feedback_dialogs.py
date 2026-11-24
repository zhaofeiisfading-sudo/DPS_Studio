from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from threading import Event, get_ident
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from dps_studio import __version__, feedback, updates
from dps_studio.gui import main_window, update_dialog
from dps_studio.gui.feedback_dialog import FeedbackDialog
from dps_studio.gui.i18n import TranslationManager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.update_dialog import AUTO_CHECK_KEY, UpdateDialog


LATEST = updates.Release("3.0.0", "## Changes\n\nInstaller and feedback.", None, None, None)
AVAILABLE = updates.UpdateCheck(__version__, LATEST)


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def wait_for(condition: Callable[[], bool]) -> None:
    deadline = monotonic() + 3
    while not condition():
        assert monotonic() < deadline, "Timed out waiting for Qt worker"
        QTest.qWait(5)


def forbid_question(*_args: object) -> None:
    pytest.fail("Unexpected confirmation dialog")


def test_help_actions_open_dialogs(
    qapp: QApplication, settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(updates, "check_for_updates", lambda **_kwargs: AVAILABLE)
    window = MainWindow(settings=settings)
    window.show()
    assert window.help_menu.title() == "帮助"
    update_action, feedback_action, separator, about = window.help_menu.actions()
    assert update_action is window.action_check_updates
    assert update_action.text() == "检查更新…"
    assert feedback_action is window.action_feedback
    assert feedback_action.text() == "意见反馈…"
    assert separator.isSeparator() and about is window.action_about

    update_action.trigger()
    feedback_action.trigger()
    update = window.findChild(UpdateDialog)
    draft = window.findChild(FeedbackDialog)
    assert update is not None and update.isVisible() and not update.isModal()
    assert draft is not None and draft.isVisible()
    wait_for(lambda: update.primary_button.text() == "下载更新")
    window.close()
    assert not update.isVisible()
    assert not draft.isVisible()
    qapp.processEvents()


def test_update_check_runs_off_thread_and_persists_setting(
    qapp: QApplication, settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_thread = get_ident()
    worker_threads = []

    def check(**_kwargs: object) -> updates.UpdateCheck:
        worker_threads.append(get_ident())
        return AVAILABLE

    monkeypatch.setattr(updates, "check_for_updates", check)
    dialog = UpdateDialog(settings)
    dialog.show()
    try:
        assert __version__ in dialog.current_version_label.text()
        assert dialog.auto_check.isChecked()
        dialog.auto_check.setChecked(False)
        reopened = QSettings(settings.fileName(), QSettings.Format.IniFormat)
        assert reopened.value(AUTO_CHECK_KEY, True, type=bool) is False
        dialog.primary_button.click()
        wait_for(lambda: dialog.primary_button.text() == "下载更新")
        assert LATEST.version in dialog.latest_version_label.text()
        assert dialog.release_notes.isReadOnly()
        assert dialog.release_notes.toPlainText() == LATEST.notes
        assert worker_threads and worker_threads[0] != main_thread
    finally:
        dialog.close()


def test_manual_offline_error_stays_in_dialog(
    settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(**_kwargs: object) -> updates.UpdateCheck:
        raise updates.UpdateError("offline")

    monkeypatch.setattr(updates, "check_for_updates", offline)
    monkeypatch.setattr(QMessageBox, "question", forbid_question)
    monkeypatch.setattr(QMessageBox, "critical", forbid_question)
    dialog = UpdateDialog(settings)
    dialog.show()
    try:
        dialog.start_check()
        wait_for(dialog.primary_button.isEnabled)
        assert dialog.status_banner.property("banner") == "error"
        assert "检查网络" in dialog.status_banner.label.text()
        assert dialog.isVisible() and not dialog.isModal()
    finally:
        dialog.close()


def test_download_progress_and_checksum_failure(
    settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    finish = Event()
    main_thread = get_ident()
    threads = []

    def bad_download(_release: updates.Release, *, progress: updates.ProgressCallback,
                     cancel_event: Event) -> updates.DownloadedInstaller:
        threads.append(get_ident())
        progress(400, 800)
        finish.wait(2)
        raise updates.UpdateIntegrityError("checksum mismatch")

    monkeypatch.setattr(updates, "download_installer", bad_download)
    monkeypatch.setattr(QMessageBox, "question", forbid_question)
    monkeypatch.setattr(updates, "launch_installer", forbid_question)
    dialog = UpdateDialog(settings, initial_result=AVAILABLE)
    dialog.show()
    try:
        dialog.primary_button.click()
        wait_for(lambda: dialog.progress_bar.value() == 50)
        assert dialog.progress_bar.isVisible()
        assert "400" in dialog.progress_label.text()
        assert "800" in dialog.progress_label.text()
        assert dialog.cancel_button.isVisible()
        assert threads and threads[0] != main_thread
        finish.set()
        wait_for(dialog.primary_button.isEnabled)
        assert not dialog.progress_bar.isVisible()
        assert dialog.status_banner.property("banner") == "error"
        assert "校验失败" in dialog.status_banner.label.text()
        assert dialog.primary_button.text() == "下载更新"
    finally:
        finish.set()
        dialog.close()


@pytest.mark.parametrize("close_with", ["cancel_button", "dialog", "main_window"])
def test_update_download_jobs_cancel_and_join(
    settings: QSettings, monkeypatch: pytest.MonkeyPatch, close_with: str,
) -> None:
    started, cancelled = Event(), Event()

    def download(_release: updates.Release, *, progress: updates.ProgressCallback,
                 cancel_event: Event) -> updates.DownloadedInstaller:
        started.set()
        if cancel_event.wait(2):
            cancelled.set()
        raise updates.UpdateCancelled("cancelled")

    monkeypatch.setattr(updates, "download_installer", download)
    window = MainWindow(settings=settings)
    window._startup_update_result = AVAILABLE
    window.show()
    window.update_notice.click()
    dialog = window.findChild(UpdateDialog)
    assert dialog is not None
    dialog.primary_button.click()
    wait_for(started.is_set)
    worker = dialog.findChild(update_dialog.UpdateThread)
    assert worker is not None and worker.isRunning()
    if close_with == "cancel_button":
        dialog.cancel_button.click()
        wait_for(dialog.primary_button.isEnabled)
        assert dialog.status_banner.label.text() == "已取消下载。"
    else:
        if close_with == "dialog":
            dialog.close()
        else:
            window.close()
        assert not worker.isRunning()
    assert cancelled.is_set()


def test_confirmation_precedes_installer_launch_and_main_window_close(
    settings: QSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    installer = updates.DownloadedInstaller(tmp_path / updates.INSTALLER_NAME, "0" * 64)
    monkeypatch.setattr(updates, "download_installer", lambda *_args, **_kwargs: installer)
    window = MainWindow(settings=settings)
    window._startup_update_result = AVAILABLE
    window.show()
    window.update_notice.click()
    dialog = window.findChild(UpdateDialog)
    assert dialog is not None
    dialog.primary_button.click()
    wait_for(lambda: dialog.primary_button.text() == "启动安装并退出")

    actions = []
    confirmations = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes])

    def confirm(_parent: QWidget, _title: str, prompt: str, *_buttons: object) -> object:
        assert "保存分析结果" in prompt and "pdv.exe" in prompt
        actions.append("confirm")
        return next(confirmations)

    def launch(value: updates.DownloadedInstaller) -> None:
        assert window.isVisible() and dialog.isVisible()
        assert value == installer
        actions.append("launch")

    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(updates, "launch_installer", launch)
    dialog.primary_button.click()
    assert actions == ["confirm"]
    assert window.isVisible()
    dialog.primary_button.click()
    assert actions == ["confirm", "confirm", "launch"]
    assert not window.isVisible()
    assert not dialog.isVisible()


@pytest.mark.parametrize("available", [True, False])
def test_startup_auto_check_is_non_blocking_and_silent_on_failure(
    qapp: QApplication, settings: QSettings, monkeypatch: pytest.MonkeyPatch, available: bool,
) -> None:
    start, finish = Event(), Event()
    main_thread = get_ident()
    threads = []

    def check(**_kwargs: object) -> updates.UpdateCheck:
        threads.append(get_ident())
        start.set()
        finish.wait(2)
        if not available:
            raise updates.UpdateError("offline")
        return AVAILABLE

    monkeypatch.setattr(main_window, "skip_automatic_update_check", lambda: False)
    monkeypatch.setattr(updates, "check_for_updates", check)
    monkeypatch.setattr(QMessageBox, "question", forbid_question)
    monkeypatch.setattr(QMessageBox, "critical", forbid_question)
    window = MainWindow(settings=settings)
    window.show()
    try:
        wait_for(start.is_set)
        assert window.isVisible()
        assert window.findChild(UpdateDialog) is None
        assert window.statusBar().currentMessage() == ""
        assert qapp.activeModalWidget() is None
        assert threads and threads[0] != main_thread
        finish.set()
        wait_for(lambda: window._startup_update_worker is None)
        assert window.update_notice.isVisible() is available
        assert window.findChild(UpdateDialog) is None
        assert qapp.activeModalWidget() is None
        assert window.statusBar().currentMessage() == ""
        if available:
            assert LATEST.version in window.update_notice.text()
            window.update_notice.click()
            dialog = window.findChild(UpdateDialog)
            assert dialog is not None and dialog.isVisible() and not dialog.isModal()
            assert LATEST.version in dialog.latest_version_label.text()
    finally:
        finish.set()
        window.close()


def test_startup_opt_out_and_offscreen_guard(
    qapp: QApplication, settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(updates, "check_for_updates", forbid_question)
    assert update_dialog.skip_automatic_update_check()
    window = MainWindow(settings=settings)
    window.show()
    qapp.processEvents()
    assert window._startup_update_worker is None
    monkeypatch.setattr(main_window, "skip_automatic_update_check", lambda: False)
    settings.setValue(AUTO_CHECK_KEY, False)
    window._start_startup_update_check()
    assert window._startup_update_worker is None


@pytest.mark.parametrize("flag", ["--startup-smoke-test", "--workflow-smoke-test", None])
def test_smoke_and_explicit_disable_guards(monkeypatch: pytest.MonkeyPatch, flag: str | None) -> None:
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("PDV_STUDIO_DISABLE_AUTO_UPDATE", raising=False)
    monkeypatch.setattr(QApplication, "platformName", lambda: "windows")
    monkeypatch.setattr(QApplication, "arguments", lambda: ["pdv-studio"])
    monkeypatch.setattr(sys, "argv", ["pdv-studio"])
    assert not update_dialog.skip_automatic_update_check()
    if flag is None:
        monkeypatch.setenv("PDV_STUDIO_DISABLE_AUTO_UPDATE", "1")
    else:
        monkeypatch.setattr(sys, "argv", ["pdv-studio", flag])
    assert update_dialog.skip_automatic_update_check()


def test_close_cancels_and_joins_startup_worker(
    settings: QSettings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, cancelled = Event(), Event()

    def check(*, cancel_event: Event) -> updates.UpdateCheck:
        started.set()
        if cancel_event.wait(2):
            cancelled.set()
        raise updates.UpdateCancelled("cancelled")

    monkeypatch.setattr(main_window, "skip_automatic_update_check", lambda: False)
    monkeypatch.setattr(updates, "check_for_updates", check)
    window = MainWindow(settings=settings)
    window.show()
    wait_for(started.is_set)
    worker = window._startup_update_worker
    assert worker is not None and worker.isRunning()
    window.close()
    assert cancelled.is_set() and not worker.isRunning()


def test_feedback_validates_and_confirms_before_opening_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions = []
    confirmations = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes])

    def confirm(*_args: object) -> object:
        actions.append("confirm")
        return next(confirmations)

    def open_url(url: QUrl) -> bool:
        actions.append(parse_qs(urlsplit(url.toString(QUrl.ComponentFormattingOption.FullyEncoded)).query))
        return True

    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    dialog = FeedbackDialog("zh_CN")
    dialog.show()
    try:
        dialog.title.setText("  ")
        dialog.submit_button.click()
        assert actions == []
        assert dialog.status_banner.label.text() == "请输入反馈标题。"
        dialog.category.setCurrentIndex(1)
        dialog.title.setText("图例 & 标签")
        dialog.description.setPlainText("复现步骤\n\n- 改为 C++ 字体")
        dialog.submit_button.click()
        assert actions == ["confirm"]
        dialog.submit_button.click()
        assert actions == ["confirm", "confirm", {
            "title": ["图例 & 标签"],
            "body": ["**Category:** 功能建议\n\n复现步骤\n\n- 改为 C++ 字体"],
        }]
    finally:
        dialog.close()


def test_feedback_copies_markdown_and_diagnostics_are_opt_in(qapp: QApplication) -> None:
    dialog = FeedbackDialog("en")
    dialog.show()
    try:
        assert not dialog.include_diagnostics.isChecked()
        assert dialog.submit_button.isDefault()
        assert not dialog.copy_button.autoDefault()
        assert set(dialog.include_diagnostics.toolTip().splitlines()) == set(feedback.DIAGNOSTIC_FIELDS)
        dialog.title.setText("图例")
        dialog.description.setPlainText("修改字体")
        dialog.copy_button.click()
        assert qapp.clipboard().text() == "# 图例\n\n**Category:** Bug 反馈\n\n修改字体"
        assert dialog.status_banner.isVisible()
        assert dialog.status_banner.property("banner") == "success"
        dialog.include_diagnostics.setChecked(True)
        dialog.copy_button.click()
        copied = qapp.clipboard().text()
        assert f"- app_version: {__version__}" in copied
        assert "- ui_language: en" in copied
        for field in feedback.DIAGNOSTIC_FIELDS:
            assert f"- {field}: " in copied
    finally:
        dialog.close()


def test_long_feedback_copies_body_and_opens_title_only(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)

    def open_url(url: QUrl) -> bool:
        urls.append(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    dialog = FeedbackDialog("zh_CN")
    try:
        dialog.title.setText("标题")
        text = "长反馈" * 500
        dialog.description.setPlainText(text)
        dialog.submit_button.click()
        assert qapp.clipboard().text() == feedback.format_feedback("bug", text)
        assert urls == [feedback.build_title_only_url("标题")]
    finally:
        dialog.close()


@pytest.mark.parametrize("language", ["zh_CN", "en"])
def test_dialogs_fit_small_high_dpi_viewport(
    qapp: QApplication, settings: QSettings, language: str,
) -> None:
    manager = TranslationManager(qapp, settings=settings)
    manager.install(language)
    update = UpdateDialog(settings, initial_result=AVAILABLE)
    draft = FeedbackDialog(language)
    try:
        update._show_progress(True)
        update._update_progress(1_100_000_000, 2_200_000_000)
        update.cancel_button.show()
        draft.copy_button.click()
        for dialog in (update, draft):
            dialog.show()
            # A 1024x640 display at 200% provides 512x320 logical pixels before window trim.
            assert dialog.sizeHint().width() <= 496
            assert dialog.sizeHint().height() <= 284
            dialog.resize(496, 284)
            qapp.processEvents()
            assert dialog.width() <= 496 and dialog.height() <= 284
            for child in dialog.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if child.isVisible():
                    assert dialog.rect().contains(child.geometry())
                    assert child.width() >= child.minimumSizeHint().width()
        if language == "en":
            assert update.windowTitle() == "Software Update"
            assert draft.windowTitle() == "Send Feedback"
            assert draft.category.itemText(0) == "Bug report"
    finally:
        update.close()
        draft.close()
        manager.install("zh_CN")
