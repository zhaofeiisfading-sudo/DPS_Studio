"""Update workflow dialog and cancellable background operations."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from threading import Event
from time import monotonic

from PySide6.QtCore import QLocale, QSettings, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from dps_studio import __version__, updates
from dps_studio.gui.inspector_widgets import InspectorCard, StatusBanner
from dps_studio.gui.styles import configure_action_button_cursors


AUTO_CHECK_KEY = "updates/auto_check_on_startup"
type UpdateResult = updates.UpdateCheck | updates.DownloadedInstaller
type Operation = Callable[[Event, updates.ProgressCallback], UpdateResult]


def auto_check_enabled(settings: QSettings) -> bool:
    return bool(settings.value(AUTO_CHECK_KEY, True, type=bool))


def skip_automatic_update_check() -> bool:
    smoke_flags = {"--startup-smoke-test", "--workflow-smoke-test"}
    return (
        bool(smoke_flags.intersection(sys.argv + QApplication.arguments()))
        or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        or QApplication.platformName() == "offscreen"
        or os.environ.get("PDV_STUDIO_DISABLE_AUTO_UPDATE") == "1"
    )


def check_operation(cancel_event: Event, _progress: updates.ProgressCallback) -> updates.UpdateCheck:
    return updates.check_for_updates(cancel_event=cancel_event)


class UpdateThread(QThread):
    """Keep network and disk operations off the Qt event loop."""

    progress_changed = Signal(object, object)

    def __init__(self, operation: Operation, parent: QWidget) -> None:
        super().__init__(parent)
        self._operation = operation
        self.cancel_event = Event()
        self.result: UpdateResult | None = None
        self.error: updates.UpdateError | None = None
        self._last_progress = 0.0

    def run(self) -> None:
        try:
            self.result = self._operation(self.cancel_event, self._report_progress)
        except updates.UpdateError as exc:
            self.error = exc

    def _report_progress(self, downloaded: int, total: int | None) -> None:
        now = monotonic()
        if downloaded == 0 or downloaded == total or now - self._last_progress >= 0.08:
            self._last_progress = now
            self.progress_changed.emit(downloaded, total)

    def stop(self) -> None:
        self.cancel_event.set()
        self.wait()
        self.deleteLater()


class UpdateDialog(QDialog):
    """Check releases, download a verified installer and hand off to Setup."""

    install_started = Signal()

    def __init__(
        self,
        settings: QSettings,
        parent: QWidget | None = None,
        *,
        initial_result: updates.UpdateCheck | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("软件更新"))
        self._settings = settings
        self._worker: UpdateThread | None = None
        self._release: updates.Release | None = None
        self._installer: updates.DownloadedInstaller | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        card = InspectorCard()
        card.body_layout.setSpacing(5)
        layout.addWidget(card)
        versions = QHBoxLayout()
        self.current_version_label = QLabel(self.tr("当前版本 {version}").format(version=__version__))
        self.latest_version_label = QLabel(self.tr("最新正式版 {version}").format(version="—"))
        versions.addWidget(self.current_version_label, 1)
        versions.addWidget(self.latest_version_label, 1)
        card.body_layout.addLayout(versions)
        self.status_banner = StatusBanner()
        card.body_layout.addWidget(self.status_banner)
        self.release_notes = QPlainTextEdit()
        self.release_notes.setReadOnly(True)
        self.release_notes.setPlaceholderText(self.tr("发布说明"))
        self.release_notes.setAccessibleName(self.tr("发布说明"))
        self.release_notes.setMinimumHeight(48)
        self.release_notes.setMaximumHeight(68)
        card.body_layout.addWidget(self.release_notes)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel()
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)
        layout.addLayout(progress_row)
        self._show_progress(False)

        self.auto_check = QCheckBox(self.tr("启动时自动检查更新"))
        self.auto_check.setChecked(auto_check_enabled(settings))
        self.auto_check.toggled.connect(self._store_auto_check)
        layout.addWidget(self.auto_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.primary_button = QPushButton()
        self.primary_button.setProperty("variant", "primary")
        self.primary_button.clicked.connect(self._advance)
        self.cancel_button = QPushButton(self.tr("取消下载"))
        self.cancel_button.clicked.connect(self._cancel_download)
        self.cancel_button.hide()
        self.close_button = QPushButton(self.tr("关闭"))
        self.close_button.clicked.connect(self.reject)
        self.cancel_button.setAutoDefault(False)
        self.close_button.setAutoDefault(False)
        for button in (self.primary_button, self.cancel_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.primary_button.setDefault(True)
        configure_action_button_cursors(self)
        self.resize(430, self.sizeHint().height())

        if initial_result is None:
            self._set_status(self.tr("可以检查正式版本。"))
        else:
            self._display_result(initial_result)
        self._refresh_actions()

    def _set_status(self, message: str, tone: str = "info") -> None:
        self.status_banner.set_tone(tone)
        self.status_banner.label.setText(message)

    @Slot(bool)
    def _store_auto_check(self, enabled: bool) -> None:
        self._settings.setValue(AUTO_CHECK_KEY, enabled)
        self._settings.sync()

    def _display_result(self, result: updates.UpdateCheck) -> None:
        self.current_version_label.setText(
            self.tr("当前版本 {version}").format(version=result.current_version)
        )
        latest = result.latest
        self._release = latest if result.update_available else None
        self.latest_version_label.setText(
            self.tr("最新正式版 {version}").format(version=latest.version if latest else "—")
        )
        self.release_notes.setPlainText(latest.notes[:6000] if latest else "")
        if self._release is not None:
            self._set_status(self.tr("发现可用更新。"), "success")
        elif latest is None:
            self._set_status(self.tr("暂无正式版本。"))
        else:
            self._set_status(self.tr("当前版本已是最新。"), "success")

    def _refresh_actions(self) -> None:
        if self._installer is not None:
            text = self.tr("启动安装并退出")
        elif self._release is not None:
            text = self.tr("下载更新")
        else:
            text = self.tr("检查更新")
        self.primary_button.setText(text)
        self.primary_button.setEnabled(self._worker is None)

    def start_check(self) -> None:
        if self._worker is not None:
            return
        self._release = None
        self._installer = None
        self.latest_version_label.setText(self.tr("最新正式版 {version}").format(version="—"))
        self.release_notes.clear()
        self._set_status(self.tr("正在检查更新…"))
        self._start_worker(check_operation)

    @Slot()
    def _advance(self) -> None:
        if self._worker is not None:
            return
        if self._installer is not None:
            self._confirm_install()
        elif self._release is not None:
            self._start_download(self._release)
        else:
            self.start_check()

    def _start_download(self, release: updates.Release) -> None:
        def download(cancel_event: Event, progress: updates.ProgressCallback) -> updates.DownloadedInstaller:
            return updates.download_installer(release, progress=progress, cancel_event=cancel_event)

        self._set_status(self.tr("正在下载并校验安装程序…"))
        self._update_progress(0, None)
        self._show_progress(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self._start_worker(download)

    def _start_worker(self, operation: Operation) -> None:
        worker = UpdateThread(operation, self)
        self._worker = worker
        worker.progress_changed.connect(self._update_progress)
        worker.finished.connect(self._worker_finished)
        self._refresh_actions()
        worker.start()

    def _show_progress(self, shown: bool) -> None:
        self.progress_bar.setVisible(shown)
        self.progress_label.setVisible(shown)

    @Slot(object, object)
    def _update_progress(self, downloaded: int, total: int | None) -> None:
        sender = self.sender()
        if isinstance(sender, UpdateThread) and sender is not self._worker:
            return
        locale = QLocale()
        completed = locale.formattedDataSize(downloaded, 1)
        if total is not None and total > 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(min(100, (downloaded * 100) // total))
            completed = f"{completed} / {locale.formattedDataSize(total, 1)}"
        else:
            self.progress_bar.setRange(0, 0)
        self.progress_label.setText(completed)

    @Slot()
    def _cancel_download(self) -> None:
        if self._worker is not None:
            self._worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self._set_status(self.tr("正在取消下载…"))

    @Slot()
    def _worker_finished(self) -> None:
        worker = self._worker
        if worker is None or self.sender() is not worker:
            return
        self._worker = None
        worker.wait()
        worker.deleteLater()
        self.cancel_button.hide()
        self._show_progress(False)
        if worker.error is not None:
            self._show_error(worker.error)
        elif isinstance(worker.result, updates.UpdateCheck):
            self._display_result(worker.result)
        elif isinstance(worker.result, updates.DownloadedInstaller):
            self._installer = worker.result
            self._set_status(self.tr("安装程序已通过校验。"), "success")
        self._refresh_actions()

    def _show_error(self, error: updates.UpdateError) -> None:
        if isinstance(error, updates.UpdateCancelled):
            self._set_status(self.tr("已取消下载。"))
        elif isinstance(error, updates.UpdateIntegrityError):
            self._set_status(self.tr("安装程序校验失败，请重新下载。"), "error")
        elif isinstance(error, updates.InstallerUnavailable):
            self._release = None
            self._set_status(self.tr("此版本缺少安装程序或可信的 SHA-256 校验值。"), "warning")
        elif self._release is not None:
            self._set_status(self.tr("下载失败，请检查网络或安装目录权限后重试。"), "error")
        else:
            self._set_status(self.tr("检查更新失败，请检查网络后重试。"), "error")

    def _confirm_install(self) -> None:
        installer = self._installer
        if installer is None:
            return
        confirmed = QMessageBox.question(
            self,
            self.tr("启动安装并退出"),
            self.tr("请保存分析结果，并关闭其他 PDV Studio 窗口和 pdv.exe 实例。"
                    "继续将启动安装程序并关闭当前窗口。"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        try:
            updates.launch_installer(installer)
        except updates.UpdateIntegrityError as exc:
            self._installer = None
            self._show_error(exc)
            self._refresh_actions()
        except updates.UpdateError:
            self._set_status(self.tr("无法启动安装程序，请重试。"), "error")
        else:
            self.accept()
            self.install_started.emit()

    def done(self, result: int) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.stop()
        super().done(result)
