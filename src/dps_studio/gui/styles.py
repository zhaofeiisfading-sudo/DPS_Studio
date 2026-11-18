"""Small, centralized visual rules for the desktop shell."""

from __future__ import annotations

from typing import overload

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QProxyStyle,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)


APPLICATION_STYLE_SHEET = """
QMainWindow, QDialog {
    background: #eef2f6;
    color: #1e293b;
}
QMenuBar, QToolBar, QStatusBar {
    background: #f7f9fc;
    color: #1b2a3b;
}
QMenuBar::item {
    padding: 4px 8px;
    background: transparent;
    border-radius: 2px;
}
QMenuBar::item:selected {
    background: #dce8f3;
    color: #102a43;
}
QMenuBar::item:pressed {
    background: #d2e5f3;
    color: #0d2338;
}
QMenu {
    background: #ffffff;
    color: #1b2a3b;
    border: 1px solid #b5c4d4;
    padding: 3px 2px;
}
QMenu::item {
    padding: 5px 26px 5px 22px;
    border: 1px solid transparent;
    border-radius: 2px;
    color: #1b2a3b;
}
QMenu::item:selected {
    background: #d2e5f3;
    color: #0d2338;
    border-color: #79a7c7;
}
QMenu::item:disabled {
    color: #8a99a8;
    background: transparent;
    border-color: transparent;
}
QMenu::separator {
    height: 1px;
    background: #dce4ec;
    margin: 3px 6px;
}
QToolBar#mainToolbar {
    background: #ffffff; border: none; border-bottom: 1px solid #dce3ec;
    padding: 4px 10px; spacing: 6px;
}
QToolButton { padding: 4px 7px; border-radius: 5px; }
QToolButton:hover:enabled { background: #e8f2f8; }
QToolButton:disabled { color: #94a3b8; }
QStatusBar#mainStatusBar { background: #ffffff; border-top: 1px solid #dce3ec; }
QStatusBar::item { border: none; }
QStatusBar QLabel { padding: 1px 5px; }
QListWidget#workflowNavigation {
    background: #f8fafc; border: none; border-bottom: 1px solid #dce3ec;
    padding: 4px 8px; outline: none;
}
QListWidget#workflowNavigation::item {
    color: #475569; padding: 5px 14px; border-radius: 6px;
    border-bottom: 2px solid transparent;
}
QListWidget#workflowNavigation::item:disabled { color: #94a3b8; }
QListWidget#workflowNavigation::item:hover:enabled { background: #edf3f9; }
QListWidget#workflowNavigation::item:selected {
    background: #e6f1f8; border-bottom: 2px solid #0f5c8a;
    color: #0c4b72; font-weight: 600;
}
QSplitter::handle:horizontal, QMainWindow::separator { background: #cbd5e1; }
QSplitter::handle:horizontal:hover, QMainWindow::separator:hover { background: #176993; }
QTabWidget::pane, QTableWidget, QPlainTextEdit, QScrollArea {
    border: 1px solid #cbd5e1;
    background: #ffffff;
}
QTableWidget {
    border: none; gridline-color: #dce3ec; alternate-background-color: #f8fafc;
    selection-background-color: #e6f1f8; selection-color: #0c4b72;
}
QHeaderView::section {
    padding: 4px 6px; background: #f8fafc; color: #475569;
    border: none; border-bottom: 1px solid #dce3ec;
}
QWidget#analysisParameterPanel { background: #f3f6fb; border-left: 1px solid #dce3ec; }
QStackedWidget#parameterStack, QWidget[inspectorPage="true"] { background: #f3f6fb; }
QScrollArea[inspectorScroll="true"] { border: none; background: transparent; }
QFrame[inspectorCard="true"] { background: #ffffff; border: 1px solid #dfe6ef; border-radius: 8px; }
QLabel[role="cardTitle"] { color: #1e293b; font-weight: bold; }
QToolButton[accordionToggle="true"] {
    text-align: left; background: transparent; border: none; color: #1e293b; font-weight: bold;
}
QToolButton[accordionToggle="true"]:hover { background: #e8f2f8; }
QFrame[banner="info"], QLabel[role="badge"] {
    background: #e8f2f8; color: #0c4b72; border: 1px solid #cbdfea; border-radius: 6px;
}
QFrame[banner="info"] QLabel { color: #0c4b72; }
QFrame[banner="success"] { background: #e9f7f2; border: 1px solid #9ed9c9; border-radius: 6px; }
QFrame[banner="success"] QLabel { color: #0e8a6d; }
QFrame[banner="warning"] { background: #fff8e8; border: 1px solid #ebd6aa; border-radius: 6px; }
QFrame[banner="warning"] QLabel { color: #b7791f; }
QFrame[banner="error"] { background: #fff1f1; border: 1px solid #e9baba; border-radius: 6px; }
QFrame[banner="error"] QLabel { color: #c62828; }
QLabel[role="badge"] { padding: 3px 6px; }
QFrame[eventCandidate="true"] { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
QRadioButton[ridgeMode="true"] { padding: 4px 8px; border-radius: 5px; }
QRadioButton[ridgeMode="true"]:checked { background: #e8f2f8; }
QWidget[plotToolbar="true"] { background: #f8fafc; border-radius: 5px; }
QWidget[plotToolbar="true"] QPushButton { min-height: 20px; padding: 2px 5px; }
QWidget[plotToolbar="true"] QToolButton { padding: 2px 3px; min-height: 20px; }
QWidget[plotToolbar="true"] QToolButton:checked { background: #dcebf5; }
QWidget[plotToolbar="true"] QComboBox { font-size: 11px; }
QWidget[plotToolbar="true"] QToolButton[plotAction="true"] {
    background: #ffffff; border: 1px solid #cbd5e1; border-radius: 5px;
    color: #1e293b; font-size: 11px; padding: 2px 7px; min-height: 20px;
}
QWidget[plotToolbar="true"] QToolButton[plotAction="true"]:hover:enabled {
    background: #f1f5f9; border-color: #648dae;
}
QWidget[plotToolbar="true"] QToolButton[plotAction="true"]:checked:enabled,
QWidget[plotToolbar="true"] QToolButton[plotAction="true"]:pressed:enabled {
    background: #e6f1f8; border-color: #0f5c8a; color: #0c4b72;
}
QWidget[plotToolbar="true"] QToolButton[plotAction="true"]:disabled {
    background: #f1f5f9; color: #94a3b8; border-color: #dce3ec;
}
QScrollArea#comparisonSeriesScroll { border: none; background: transparent; }
QLabel[role="hudReadout"] {
    background: #edf3f8; color: #334155; padding: 3px 5px; border-radius: 5px;
    font-family: Consolas, monospace; font-size: 11px;
}
QLabel[role="plotFooter"], QLabel[role="workflowChip"] {
    background: #f1f5f9; color: #475569; padding: 3px 6px; font-size: 11px; border-radius: 4px;
}
QWidget#rawWelcomeOverlay { background: #f4f7fb; }
QFrame[welcomeCard="true"] { background: white; border: 1px solid #dfe6ef; border-radius: 12px; }
QLabel#rawWelcomeTitle { color: #173e5b; font-size: 20px; font-weight: 600; }
QFrame[settingsStrip="true"] { background: #f8fafc; border: 1px solid #dfe6ef; border-radius: 6px; }
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
QTabWidget#scienceTabs > QTabBar::tab {
    min-height: 28px; padding: 5px 8px; background: #e8edf3; color: #475569;
}
QTabWidget#scienceTabs > QTabBar::tab:selected {
    background: #ffffff; border-bottom: 2px solid #0f5c8a; color: #0f5c8a; font-weight: 600;
}
QTabWidget#scienceTabs > QTabBar::tab:disabled { color: #94a3b8; }
QPushButton, QPushButton[variant="secondary"] {
    min-height: 21px; padding: 2px 8px; border: 1px solid #cbd5e1;
    border-radius: 5px; background: #ffffff; color: #1e293b;
}
QPushButton:hover:enabled { background: #f1f5f9; border-color: #648dae; }
QPushButton:pressed:enabled, QPushButton:checked { background: #e6f1f8; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: #475569; }
QPushButton[variant="ghost"]:hover:enabled { background: #edf3f9; }
QPushButton[variant="primary"], QPushButton:default:enabled {
    min-height: 28px; border-radius: 6px; background: #0f5c8a; color: #ffffff;
    border: 1px solid #0f5c8a; font-weight: 600;
}
QPushButton[variant="primary"]:hover:enabled, QPushButton:default:hover:enabled { background: #0c4b72; }
QPushButton[variant="primary"]:pressed:enabled, QPushButton:default:pressed:enabled { background: #093a59; }
QPushButton:disabled, QPushButton[variant="primary"]:disabled {
    background: #e2e8f0; color: #64748b; border-color: #dce3ec;
}
QComboBox, QAbstractSpinBox, QLineEdit {
    min-height: 21px;
    padding-left: 4px;
    border: 1px solid #c5d1de;
    border-radius: 2px;
    background: #ffffff;
    color: #1b2a3b;
}
QComboBox:hover:enabled {
    background: #f5f9fc;
    border-color: #5c8eac;
}
QPushButton:focus:enabled, QComboBox:focus, QAbstractSpinBox:focus, QLineEdit:focus {
    border: 1px solid #166d9b;
}
QComboBox:on:enabled {
    background: #eaf3fa;
    border: 1px solid #166d9b;
}
QComboBox:disabled, QAbstractSpinBox:disabled, QLineEdit:disabled {
    background: #edf2f6;
    color: #6d7c8d;
    border-color: #d8e1e9;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #1b2a3b;
    border: 1px solid #b5c4d4;
    padding: 2px;
    outline: none;
    selection-background-color: #e4f0f8;
    selection-color: #102a43;
}
QComboBox QAbstractItemView::item {
    min-height: 22px;
    padding: 2px 6px;
    color: #1b2a3b;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
}
QComboBox QAbstractItemView::item:selected {
    background: #e4f0f8;
    color: #102a43;
    border-color: #b7d2e6;
}
QComboBox QAbstractItemView::item:hover:enabled,
QComboBox QAbstractItemView::item:selected:hover:enabled {
    background: #d2e5f3;
    color: #0d2338;
    border-color: #79a7c7;
}
QComboBox QAbstractItemView::item:pressed:enabled,
QComboBox QAbstractItemView::item:selected:pressed:enabled {
    background: #c1dcf0;
    color: #091d30;
    border-color: #5c8eac;
}
QComboBox QAbstractItemView::item:disabled,
QComboBox QAbstractItemView::item:disabled:hover {
    color: #8a99a8;
    background: transparent;
    border-color: transparent;
}
QRadioButton, QCheckBox { spacing: 6px; padding: 2px; }
QRadioButton:hover:enabled { color: #145c85; }
QRadioButton:checked { color: #145c85; font-weight: 600; }
QLabel#sectionTitle { color: #173e5b; font-weight: 700; padding: 2px 0; }
QLabel#plannedNotice { color: #526477; }
QProgressBar { background: #dbe5ed; border: none; min-height: 5px; max-height: 5px; }
QProgressBar::chunk { background: #1776a3; }
"""


class _ComboBoxItemDelegate(QStyledItemDelegate):
    """Styled item delegate so QComboBox popup items honor QSS hover and selection."""

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width() + 4, max(size.height(), 24))


class _ComboBoxPopupSizer(QObject):
    """Ensure QComboBox popups stay wide enough for option labels without clipping."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() is QEvent.Type.Show:
            view = self._combo.view()
            content_width = max(0, view.sizeHintForColumn(0))
            scrollbar_width = (
                view.verticalScrollBar().sizeHint().width()
                if self._combo.count() > self._combo.maxVisibleItems()
                else 0
            )
            needed_width = max(self._combo.width(), content_width + scrollbar_width + 12)
            screen = self._combo.screen()
            available = screen.availableGeometry() if screen is not None else None
            if available is not None and available.isValid():
                needed_width = min(needed_width, int(available.width() * 0.9))
            view.setMinimumWidth(needed_width)
            container = view.window()
            if container is not view and container.width() < needed_width:
                container.resize(needed_width, container.height())
            if (
                available is not None
                and available.isValid()
                and container.x() + container.width() > available.right()
            ):
                clamped_x = max(
                    available.left(),
                    available.right() - container.width() + 1,
                )
                container.move(clamped_x, container.y())
        return super().eventFilter(watched, event)


def configure_combo_box_popup(combo: QComboBox) -> None:
    """Install styled popup rendering and contrast-safe palette on a QComboBox."""
    if bool(combo.property("comboBoxPopupConfigured")):
        return
    combo.setProperty("comboBoxPopupConfigured", True)
    if not isinstance(combo.itemDelegate(), QStyledItemDelegate):
        combo.setItemDelegate(_ComboBoxItemDelegate(combo))
    view = combo.view()
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1b2a3b"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#e4f0f8"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#102a43"))
    view.setPalette(palette)
    view.window().installEventFilter(_ComboBoxPopupSizer(combo))


class _DesktopProxyStyle(QProxyStyle):
    """Fusion base style that ensures every QComboBox popup uses styled items."""

    def __init__(self) -> None:
        super().__init__("Fusion")

    @overload
    def polish(self, application: QApplication, /) -> None: ...

    @overload
    def polish(self, widget: QWidget, /) -> None: ...

    @overload
    def polish(
        self,
        palette: QPalette | Qt.GlobalColor | QColor,
        /,
    ) -> None: ...

    def polish(
        self,
        target: QApplication | QWidget | QPalette | Qt.GlobalColor | QColor,
    ) -> None:
        if isinstance(target, QComboBox):
            configure_combo_box_popup(target)
        super().polish(target)


def apply_application_style(application: QApplication) -> None:
    """Apply a native-looking light theme without fixed widget geometry."""
    # Microsoft YaHei UI contains both Chinese and Latin glyphs on supported
    # Windows installations; Qt falls back to the native system font elsewhere.
    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleHint(QFont.StyleHint.System)
    application.setStyle(_DesktopProxyStyle())
    application.setFont(font)
    application.setStyleSheet(APPLICATION_STYLE_SHEET)
    for widget in application.allWidgets():
        if isinstance(widget, QComboBox):
            configure_combo_box_popup(widget)


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


__all__ = [
    "apply_application_style",
    "configure_action_button_cursors",
    "configure_combo_box_popup",
]
