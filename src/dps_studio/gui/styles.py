"""Small, centralized visual rules for the desktop shell."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget

from dps_studio.runtime_paths import package_resource_path


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
    min-height: 25px;
    padding: 3px 9px;
    border-radius: 4px;
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

APPLICATION_STYLE_SHEET += """
QWidget { background: #f4f6f8; color: #283d4c; }
QTabWidget::pane, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #ffffff; border: 0;
}
QToolBar { padding: 7px; spacing: 8px; border-bottom: 1px solid #dce3e9; }
QToolButton { padding: 5px 9px; border-radius: 4px; }
QToolButton:hover { background: #e9f0f6; }
QToolButton#sectionDisclosure { text-align: left; font-weight: 600; color: #254b66; }
QPushButton:checked { background: #e4eff8; border-color: #6e9cba; color: #154c73; }
QPushButton[primary="true"] { background: #25658d; color: white; border: 1px solid #25658d; }
QPushButton[primary="true"]:hover { background: #194f74; }
QComboBox, QSpinBox, QDoubleSpinBox {
    background: white; min-height: 25px; padding: 2px 6px;
    border: 1px solid #ced8e0; border-radius: 4px; selection-background-color: #dcecf6;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #3b799f; }
QComboBox::drop-down { width: 19px; border: 0; }
QComboBox::down-arrow { width: 10px; height: 7px; image: url(__PDV_CHEVRON__); }
QComboBox QAbstractItemView { background: white; selection-background-color: #dcecf6; }
QRadioButton { min-height: 23px; padding: 2px 6px; border: 0; border-radius: 4px; }
QCheckBox { spacing: 7px; min-height: 24px; }
QListWidget { border: 0; background: #edf2f6; outline: 0; }
QListWidget::item { padding: 12px 8px; border-radius: 4px; margin-bottom: 4px; }
QListWidget::item:selected { background: #dbe9f3; color: #1c506e; }
QTabBar::tab { padding: 7px 12px; border: 0; background: #edf2f6; }
QTabBar::tab:selected { background: white; color: #1b6088; border-bottom: 2px solid #337ca6; }
QTableWidget { background: white; alternate-background-color: #f7f9fb; gridline-color: #e8edf1; }
QHeaderView::section { background: #edf2f6; color: #4c6475; border: 0;
    border-bottom: 1px solid #d9e2e9; padding: 5px 7px; }
QScrollBar:vertical { background: #f3f6f8; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #c8d4de; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLabel#segmentStatus, QLabel#plannedNotice { color: #647989; }
QLabel#sectionTitle { font-size: 10pt; color: #2a526c; }
QSplitter::handle:vertical { background: #e0e7ed; height: 5px; }
QLabel { background: transparent; }
"""


def apply_application_style(application: QApplication) -> None:
    """Apply a native-looking light theme without fixed widget geometry."""
    # Microsoft YaHei UI contains both Chinese and Latin glyphs on supported
    # Windows installations; Qt falls back to the native system font elsewhere.
    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleHint(QFont.StyleHint.System)
    application.setFont(font)
    chevron = package_resource_path("gui", "icons", "chevron_down.svg").as_posix()
    application.setStyleSheet(APPLICATION_STYLE_SHEET.replace("__PDV_CHEVRON__", chevron))


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
