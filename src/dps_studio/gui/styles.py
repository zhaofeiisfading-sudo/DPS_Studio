"""Small, centralized visual rules for the desktop shell."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


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
}
QPushButton:default {
    background: #0b6fa4;
    color: #ffffff;
    border: 1px solid #07577f;
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


__all__ = ["apply_application_style"]
