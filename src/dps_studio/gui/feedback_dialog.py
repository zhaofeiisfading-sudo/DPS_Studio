"""Prepare feedback locally and open a GitHub issue draft after confirmation."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from dps_studio.feedback import (
    DIAGNOSTIC_FIELDS, build_issue_url, build_title_only_url, collect_safe_diagnostics,
    format_feedback,
)
from dps_studio.gui.inspector_widgets import InspectorCard, StatusBanner
from dps_studio.gui.styles import configure_action_button_cursors


class FeedbackDialog(QDialog):
    """Collect an issue draft with explicit opt-in to basic environment information."""

    def __init__(self, language_code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("意见反馈"))
        self._language_code = language_code

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        card = InspectorCard()
        card.body_layout.setSpacing(6)
        layout.addWidget(card)
        form = QFormLayout()
        form.setVerticalSpacing(5)
        card.add_form(form)

        self.category = QComboBox()
        self.category.addItem(self.tr("Bug 反馈"), "bug")
        self.category.addItem(self.tr("功能建议"), "enhancement")
        self.category.addItem(self.tr("其他意见"), "feedback")
        form.addRow(self.tr("类别"), self.category)
        self.title = QLineEdit()
        form.addRow(self.tr("标题"), self.title)
        self.description = QPlainTextEdit()
        self.description.setAccessibleName(self.tr("反馈内容"))
        self.description.setPlaceholderText(self.tr("描述遇到的问题、复现步骤或建议。"))
        self.description.setMinimumHeight(52)
        self.description.setMaximumHeight(66)
        card.body_layout.addWidget(self.description)

        self.include_diagnostics = QCheckBox(
            self.tr("附带基础环境信息\n（仅版本、系统与语言，不含文件路径或实验数据）")
        )
        self.include_diagnostics.setToolTip("\n".join(DIAGNOSTIC_FIELDS))
        card.body_layout.addWidget(self.include_diagnostics)

        self.status_banner = StatusBanner()
        self.status_banner.hide()
        layout.addWidget(self.status_banner)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.copy_button = QPushButton(self.tr("复制反馈内容"))
        self.copy_button.clicked.connect(self._copy_feedback)
        self.submit_button = QPushButton(self.tr("在 GitHub 提交"))
        self.submit_button.setProperty("variant", "primary")
        self.submit_button.clicked.connect(self._open_issue)
        self.close_button = QPushButton(self.tr("关闭"))
        self.close_button.clicked.connect(self.reject)
        self.copy_button.setAutoDefault(False)
        self.close_button.setAutoDefault(False)
        for button in (self.copy_button, self.submit_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.submit_button.setDefault(True)
        configure_action_button_cursors(self)
        self.resize(430, self.sizeHint().height())
        self.title.setFocus()

    def _markdown(self, category: str) -> str:
        diagnostics = (
            collect_safe_diagnostics(self._language_code)
            if self.include_diagnostics.isChecked() else None
        )
        return format_feedback(category, self.description.toPlainText(), diagnostics)

    def _status(self, text: str, tone: str) -> None:
        self.status_banner.set_tone(tone)
        self.status_banner.label.setText(text)
        self.status_banner.show()

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self._status(self.tr("已复制到剪贴板，可离线保存或粘贴提交。"), "success")

    @Slot()
    def _copy_feedback(self) -> None:
        body = self._markdown(str(self.category.currentData()))
        title = self.title.text().strip()
        self._copy(f"# {title}\n\n{body}" if title else body)

    @Slot()
    def _open_issue(self) -> None:
        title = self.title.text().strip()
        if not title:
            self._status(self.tr("请输入反馈标题。"), "warning")
            self.title.setFocus()
            return
        category = str(self.category.currentData())
        body = self._markdown(category)
        # GitHub requires label permissions for the labels query parameter.
        url, too_long = build_issue_url(title, body, category, include_label=False)
        prompt = self.tr("将在浏览器中打开 GitHub 反馈草稿。请检查内容后在 GitHub 提交。")
        if too_long:
            prompt = self.tr("反馈内容较长。继续将复制内容并打开 GitHub，请粘贴后提交。")
        if QMessageBox.question(
            self,
            self.tr("在 GitHub 提交"),
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        if too_long:
            url = build_title_only_url(title)
            self._copy(f"# {title}\n\n{body}" if "?" not in url else body)
        if not QDesktopServices.openUrl(QUrl(url)):
            self._status(self.tr("无法打开浏览器，可复制反馈内容。"), "warning")
