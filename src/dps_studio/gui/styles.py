"""Small, centralized visual rules for the desktop shell."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget


APPLICATION_STYLE_SHEET = """
QMainWindow, QDialog {
    background: #e9eef3;
    color: #1b2a3b;
}
QMenuBar, QMenu, QToolBar, QStatusBar {
    background: #f7f9fc;
    color: #1b2a3b;
}
QToolBar { border: none; padding: 3px 5px; spacing: 5px; }
QToolBar::separator { width: 1px; margin: 3px 4px; background: #cbd5e1; }
QToolButton { padding: 4px 7px; border-radius: 3px; }
QToolButton:hover:enabled { background: #dce8f3; }
QToolButton:disabled { color: #7e8b9b; }
QStatusBar { border-top: 1px solid #cbd5e1; }
QStatusBar::item { border: none; }
QStatusBar QLabel { padding: 0 5px; }
QListWidget#workflowNavigation {
    background: #22364a;
    border: none;
    padding: 2px 3px;
    outline: none;
}
QListWidget#workflowNavigation::item {
    color: #e7eff7;
    padding: 4px 13px;
    margin: 0 2px;
    border-bottom: 2px solid transparent;
}
QListWidget#workflowNavigation::item:disabled { color: #a4b3c2; }
QListWidget#workflowNavigation::item:hover:enabled { background: #304c65; }
QListWidget#workflowNavigation::item:selected {
    background: #304c65;
    border-bottom: 2px solid #58c3ea;
    color: #ffffff;
}
QSplitter::handle:horizontal, QMainWindow::separator { background: #cbd5e1; }
QSplitter::handle:horizontal:hover, QMainWindow::separator:hover { background: #176993; }
QTabWidget::pane, QTableWidget, QPlainTextEdit, QScrollArea {
    border: 1px solid #cbd5e1;
    background: #ffffff;
}
QStackedWidget#parameterStack { background: #f7f9fc; }
QGroupBox {
    border: 1px solid #d4dee8;
    margin-top: 9px;
    padding: 5px 3px 3px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 7px; padding: 0 3px; }
QTabBar::tab {
    color: #4b5e70;
    background: #e9eef3;
    padding: 5px 11px;
    border: none;
    border-bottom: 2px solid #cbd5e1;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #145c85;
    border-bottom-color: #1776a3;
}
QTabBar::tab:disabled { color: #788695; }
QPushButton {
    min-height: 21px;
    padding: 2px 8px;
    border: 1px solid #bbc9d6;
    border-radius: 3px;
    background: #ffffff;
    color: #21374c;
}
QPushButton:hover:enabled { background: #e4f0f8; border-color: #5c8eac; }
QPushButton:pressed:enabled, QPushButton:checked { background: #d2e5f3; }
QPushButton:focus:enabled, QComboBox:focus, QAbstractSpinBox:focus, QLineEdit:focus {
    border: 1px solid #166d9b;
}
QPushButton:default:enabled {
    color: white;
    background: #176993;
    border-color: #135a7f;
    font-weight: 600;
}
QPushButton:default:hover:enabled { background: #135a7f; }
QPushButton:default:pressed:enabled { background: #0d4768; }
QPushButton:disabled { color: #738396; background: #eaf0f5; border-color: #d8e1e9; }
QComboBox, QAbstractSpinBox, QLineEdit {
    min-height: 21px;
    padding-left: 4px;
    border: 1px solid #c5d1de;
    border-radius: 2px;
    background: #ffffff;
}
QComboBox:disabled, QAbstractSpinBox:disabled { background: #edf2f6; color: #6d7c8d; }
QRadioButton, QCheckBox { spacing: 6px; padding: 2px; }
QRadioButton:hover:enabled { color: #145c85; }
QRadioButton:checked { color: #145c85; font-weight: 600; }
QLabel#sectionTitle { color: #173e5b; font-weight: 700; padding: 2px 0; }
QLabel#plannedNotice { color: #526477; }
QProgressBar { background: #dbe5ed; border: none; min-height: 5px; max-height: 5px; }
QProgressBar::chunk { background: #1776a3; }
"""


def apply_application_style(application: QApplication) -> None:
    """Apply a native-looking light theme without fixed widget geometry."""
    # Microsoft YaHei UI contains both Chinese and Latin glyphs on supported
    # Windows installations; Qt falls back to the native system font elsewhere.
    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleHint(QFont.StyleHint.System)
    application.setStyle("Fusion")
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
