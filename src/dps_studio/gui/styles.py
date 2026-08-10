"""Small, centralized visual rules for the desktop shell."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget


APPLICATION_STYLE_SHEET = """
QMainWindow, QWidget {
    background: #f5f7f9;
    color: #263746;
}
QMenuBar, QMenu, QToolBar, QStatusBar {
    background: #ffffff;
}
QToolBar {
    border-bottom: 1px solid #d6dde3;
    spacing: 4px;
}
QSplitter::handle:horizontal {
    background: #d6dde3;
    width: 7px;
    margin: 0 2px;
}
QSplitter::handle:horizontal:hover {
    background: #0b6fa4;
}
QMainWindow::separator {
    background: #d6dde3;
    width: 7px;
    height: 7px;
}
QMainWindow::separator:hover {
    background: #0b6fa4;
}
QListWidget, QTabWidget::pane, QStackedWidget, QTableWidget,
QPlainTextEdit, QGroupBox {
    background: #ffffff;
    border: 1px solid #d6dde3;
}
QGroupBox {
    margin-top: 8px;
    padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 3px;
}
QListWidget::item {
    padding: 8px 6px;
}
QListWidget::item:selected {
    background: #dceaf4;
    color: #173a52;
}
QTabBar::tab {
    background: #e9eef2;
    padding: 7px 12px;
    border: 1px solid #d6dde3;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #0b6fa4;
}
QPushButton {
    min-height: 26px;
    padding: 2px 10px;
    background: #ffffff;
    border: 1px solid #d6dde3;
    color: #263746;
}
QPushButton:hover:enabled {
    background: #edf0f2;
    border-color: #c5d0d7;
}
QPushButton:pressed:enabled {
    background: #dfe5e9;
    border-color: #afbec8;
}
QPushButton:focus:enabled {
    border-color: #0b6fa4;
}
QPushButton:disabled {
    background: #f1f3f5;
    border-color: #e0e5e9;
    color: #8a98a3;
}
QPushButton:default {
    background: #0b6fa4;
    color: #ffffff;
    border: 1px solid #07577f;
}
QPushButton:default:hover:enabled {
    background: #07577f;
    border-color: #064364;
}
QPushButton:default:pressed:enabled {
    background: #064364;
    border-color: #04364f;
}
QPushButton:default:focus:enabled {
    border-color: #04364f;
}
QRadioButton {
    min-height: 26px;
    padding: 2px 12px;
    spacing: 7px;
    background: #ffffff;
    border: 1px solid #d6dde3;
    color: #263746;
}
QRadioButton:checked {
    background: #dceaf4;
    border-color: #0b6fa4;
    color: #173a52;
    font-weight: 600;
}
QRadioButton:focus:enabled {
    border-color: #07577f;
}
QRadioButton:hover:unchecked {
    background: #edf5fa;
    border-color: #82b4ce;
}
QRadioButton:hover:checked {
    background: #c9e2f1;
    border-color: #07577f;
}
QRadioButton:pressed {
    background: #bdd9ea;
}
QRadioButton:disabled {
    background: #f1f3f5;
    border-color: #e0e5e9;
    color: #8a98a3;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 2px solid #607583;
    border-radius: 8px;
    background: #ffffff;
}
QRadioButton::indicator:unchecked:hover {
    border-color: #0b6fa4;
    background: #edf5fa;
}
QRadioButton::indicator:checked {
    border: 2px solid #07577f;
    border-radius: 8px;
    background: #0b6fa4;
}
QRadioButton::indicator:checked:hover {
    border-color: #064364;
    background: #07577f;
}
QRadioButton::indicator:checked:pressed {
    background: #064364;
}
QRadioButton::indicator:disabled:unchecked {
    border-color: #aab5bd;
    background: #f1f3f5;
}
QRadioButton::indicator:disabled:checked {
    border-color: #719ab1;
    background: #8ab5cc;
}
QLabel#sectionTitle {
    color: #173a52;
    font-weight: 600;
}
QLabel#plannedNotice {
    color: #607583;
}
"""


def apply_application_style(application: QApplication) -> None:
    """Apply a native-looking light theme without fixed widget geometry."""
    # Microsoft YaHei UI contains both Chinese and Latin glyphs on supported
    # Windows installations; Qt falls back to the native system font elsewhere.
    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleHint(QFont.StyleHint.System)
    application.setFont(font)
    application.setStyleSheet(APPLICATION_STYLE_SHEET)


def _set_action_button_cursor(button: QPushButton | QToolButton) -> None:
    """Use a click cursor only while a discrete action is available."""
    cursor = (
        Qt.CursorShape.PointingHandCursor
        if button.isEnabled()
        else Qt.CursorShape.ArrowCursor
    )
    button.setCursor(cursor)


class _ActionButtonCursorFilter(QObject):
    """Keep action-button cursors synchronized with enabled state changes."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, (QPushButton, QToolButton)) and (
            event.type() is QEvent.Type.EnabledChange
        ):
            _set_action_button_cursor(watched)
        return super().eventFilter(watched, event)


_ACTION_BUTTON_CURSOR_FILTER = _ActionButtonCursorFilter()


def configure_action_button_cursors(root: QWidget) -> None:
    """Apply enabled-state-aware click cursors to discrete action buttons."""
    buttons: list[QPushButton | QToolButton] = [
        *root.findChildren(QPushButton),
        *root.findChildren(QToolButton),
    ]
    if isinstance(root, (QPushButton, QToolButton)):
        buttons.append(root)
    for button in buttons:
        if not bool(button.property("actionButtonCursorConfigured")):
            button.setProperty("actionButtonCursorConfigured", True)
            button.installEventFilter(_ACTION_BUTTON_CURSOR_FILTER)
        _set_action_button_cursor(button)


__all__ = ["apply_application_style", "configure_action_button_cursors"]
