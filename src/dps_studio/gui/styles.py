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
    background: #e9eef3;
    color: #1b2a3b;
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
QTableWidget {
    selection-background-color: #d2e5f3;
    selection-color: #0d2338;
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
