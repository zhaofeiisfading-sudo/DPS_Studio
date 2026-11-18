"""Small, centralized visual rules for the desktop shell."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QHoverEvent, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QToolButton, QWidget,
)

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
QMenu {
    background: #ffffff; color: #283d4c;
    border: 1px solid #c2cfd9; padding: 4px;
}
QMenu::item { background: transparent; color: #283d4c; padding: 5px 24px 5px 10px; }
QMenu::item:selected { background: #e6f1f8; color: #154c73; }
QMenu::item:disabled { background: transparent; color: #8a98a3; }
QMenu::separator { height: 1px; background: #e2e8ee; margin: 4px 6px; }
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
    selection-color: #0f3f5f;
}
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #3b799f; }
QComboBox, QComboBox:enabled {
    background: #ffffff; color: #283d4c; border: 1px solid #ced8e0;
    border-radius: 4px; min-height: 25px; padding: 2px 24px 2px 8px;
}
QComboBox:hover:enabled { background: #fbfdff; border-color: #8fa9bc; }
QComboBox:focus:enabled { background: #ffffff; border-color: #0b6fa4; }
QComboBox:on:enabled { background: #f4f9fd; border-color: #0b6fa4; }
QComboBox:disabled { background: #f1f4f6; color: #8a98a3; border-color: #dde4ea; }
QComboBox::drop-down { width: 19px; border: 0; }
QComboBox::down-arrow { width: 10px; height: 7px; image: url(__PDV_CHEVRON__); }
QComboBox QAbstractItemView {
    background: #ffffff; color: #283d4c; border: 1px solid #c2cfd9;
    padding: 3px; outline: 0; selection-background-color: #d2e7f5; selection-color: #0f3f5f;
}
QComboBox QAbstractItemView::item {
    background: #ffffff; color: #283d4c; min-height: 24px; padding: 4px 10px;
}
QComboBox QAbstractItemView::item:hover { background: #e6f1f8; color: #154c73; }
QComboBox QAbstractItemView::item:selected { background: #d2e7f5; color: #0f3f5f; }
QComboBox QAbstractItemView::item:selected:hover { background: #c2ddf0; color: #0b3450; }
QComboBox QAbstractItemView::item:disabled { background: #ffffff; color: #8a98a3; }
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
    application.setPalette(_light_palette(application.palette()))
    chevron = package_resource_path("gui", "icons", "chevron_down.svg").as_posix()
    application.setStyleSheet(APPLICATION_STYLE_SHEET.replace("__PDV_CHEVRON__", chevron))
    helper = application.findChild(_ComboPopupFilter, "comboPopupStyleFilter")
    if helper is None:
        helper = _ComboPopupFilter(application)
        helper.setObjectName("comboPopupStyleFilter")
        application.installEventFilter(helper)
    for widget in application.allWidgets():
        if isinstance(widget, QComboBox):
            _configure_combo_popup(widget)


def _light_palette(source: QPalette) -> QPalette:
    """Keep selection foreground/background paired in every palette group."""
    palette = QPalette(source)
    for role, color in (
        (QPalette.ColorRole.Window, "#ffffff"),
        (QPalette.ColorRole.Base, "#ffffff"),
        (QPalette.ColorRole.Button, "#ffffff"),
        (QPalette.ColorRole.Text, "#283d4c"),
        (QPalette.ColorRole.WindowText, "#283d4c"),
        (QPalette.ColorRole.ButtonText, "#283d4c"),
        (QPalette.ColorRole.Highlight, "#d2e7f5"),
        (QPalette.ColorRole.HighlightedText, "#0f3f5f"),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#8a98a3"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#ffffff"))
    return palette


class _ComboItemDelegate(QStyledItemDelegate):
    """Paint popup rows without native CE_ItemViewItem/CE_MenuItem fallbacks.

    Windows 11 and Fusion otherwise reinterpret hover, selection and disabled
    palettes differently. Keep model text, font, icons and check states, but own
    row surfaces and text drawing so the system dark scheme cannot wash them out.
    """

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        extra = 20
        if not item.icon.isNull():
            extra += max(16, item.decorationSize.width()) + 6
        if item.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator:
            extra += 22
        return QSize(item.fontMetrics.horizontalAdvance(item.text) + extra,
                     max(32, item.fontMetrics.height() + 8, item.decorationSize.height() + 8))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex) -> None:
        item = QStyleOptionViewItem(option)
        self.initStyleOption(item, index)
        enabled = bool(item.state & QStyle.StateFlag.State_Enabled) and bool(
            index.flags() & Qt.ItemFlag.ItemIsEnabled
        )
        selected = bool(item.state & QStyle.StateFlag.State_Selected)
        hovered = bool(item.state & QStyle.StateFlag.State_MouseOver)
        view = self.parent()
        if isinstance(view, QAbstractItemView):
            hover_index = view.property("comboHoveredIndex")
            if isinstance(hover_index, QModelIndex):
                hovered = hover_index == index
        background, foreground = "#ffffff", "#283d4c"
        if not enabled:
            foreground = "#8a98a3"
        elif selected and hovered:
            background, foreground = "#c2ddf0", "#0b3450"
        elif selected:
            background, foreground = "#d2e7f5", "#0f3f5f"
        elif hovered:
            background, foreground = "#e6f1f8", "#154c73"
        painter.save()
        painter.setClipRect(item.rect)
        painter.fillRect(item.rect, QColor(background))
        painter.setFont(item.font)
        painter.setPen(QColor(foreground))
        text_rect = item.rect.adjusted(10, 4, -10, -4)
        if item.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator:
            check_rect = QStyle.visualRect(item.direction, item.rect,
                                          QRect(text_rect.left(), text_rect.center().y() - 7, 14, 14))
            painter.drawRect(check_rect.adjusted(0, 0, -1, -1))
            if item.checkState != Qt.CheckState.Unchecked:
                painter.drawText(check_rect, Qt.AlignmentFlag.AlignCenter, "✓")
            text_rect.adjust(22, 0, 0, 0)
        if not item.icon.isNull():
            icon_size = max(16, item.decorationSize.width())
            icon_rect = QStyle.visualRect(item.direction, item.rect,
                                         QRect(text_rect.left(), text_rect.center().y() - icon_size // 2,
                                               icon_size, icon_size))
            item.icon.paint(painter, icon_rect)
            text_rect.adjust(icon_size + 6, 0, 0, 0)
        text_rect = QStyle.visualRect(item.direction, item.rect, text_rect)
        text = item.fontMetrics.elidedText(item.text, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, item.displayAlignment | Qt.AlignmentFlag.AlignVCenter, text)
        if enabled and item.state & QStyle.StateFlag.State_HasFocus:
            painter.fillRect(QRect(item.rect.left() + 2, item.rect.top() + 4,
                                   2, max(0, item.rect.height() - 8)), QColor("#0b6fa4"))
        painter.restore()


def _configure_combo_popup(combo: QComboBox) -> None:
    view = combo.view()
    if not isinstance(view.itemDelegate(), _ComboItemDelegate):
        view.setItemDelegate(_ComboItemDelegate(view))
    view.setPalette(_light_palette(view.palette()))
    view.setMouseTracking(True)
    view.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    view.viewport().setMouseTracking(True)
    view.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)


def _popup_combo(widget: QWidget) -> QComboBox | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QComboBox):
            return parent
        parent = parent.parentWidget()
    return None


def _fit_combo_popup(combo: QComboBox, popup: QWidget) -> None:
    """Measure the current model each time, then constrain the popup to its screen."""
    view = combo.view()
    screen = combo.screen()
    available = screen.availableGeometry().adjusted(4, 4, -4, -4)
    margins = view.contentsMargins()
    width = view.sizeHintForColumn(combo.modelColumn()) + margins.left() + margins.right() + 8
    if view.verticalScrollBar().isVisible():
        width += view.verticalScrollBar().sizeHint().width()
    width = min(max(combo.width(), width), available.width())
    popup.setMinimumWidth(width)
    popup.resize(width, min(popup.height(), available.height()))
    popup.move(max(available.left(), min(popup.x(), available.right() - popup.width() + 1)),
               max(available.top(), min(popup.y(), available.bottom() - popup.height() + 1)))


def _refresh_combo_hover_after_scroll(view: QAbstractItemView, viewport: QWidget) -> None:
    """Resolve the item under a stationary cursor after Qt handles the wheel."""
    try:
        viewport.setProperty("comboHoverUpdatePending", False)
        if not view.isVisible() or view.viewport() is not viewport:
            return
        position = viewport.mapFromGlobal(QCursor.pos())
        index = view.indexAt(position) if viewport.rect().contains(position) else QModelIndex()
        view.setProperty("comboHoveredIndex", index)
        viewport.update()
    except RuntimeError:
        # A popup or its viewport may have been destroyed before timer delivery.
        return


class _ComboPopupFilter(QObject):
    """Configure existing and future combos, including rebuilt table cell widgets."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            kind = event.type()
            if kind == QEvent.Type.Polish and isinstance(watched, QComboBox):
                _configure_combo_popup(watched)
            elif kind == QEvent.Type.Show and isinstance(watched, QWidget):
                if watched.isWindow() and watched.windowType() == Qt.WindowType.Popup:
                    combo = _popup_combo(watched)
                    if combo is not None:
                        _configure_combo_popup(combo)
                        combo.view().setProperty("comboHoveredIndex", QModelIndex())
                        _fit_combo_popup(combo, watched)
            elif kind in (QEvent.Type.HoverEnter, QEvent.Type.HoverMove,
                          QEvent.Type.MouseMove, QEvent.Type.Leave, QEvent.Type.Wheel) and isinstance(watched, QWidget):
                view = watched.parentWidget()
                if isinstance(view, QAbstractItemView) and isinstance(view.itemDelegate(), _ComboItemDelegate):
                    if kind == QEvent.Type.Wheel:
                        if not watched.property("comboHoverUpdatePending"):
                            watched.setProperty("comboHoverUpdatePending", True)
                            # The viewport context cancels delivery on destruction.
                            # Coalesce wheel bursts into one post-scroll update.
                            QTimer.singleShot(0, watched,
                                              lambda: _refresh_combo_hover_after_scroll(view, watched))
                    else:
                        # Do not synthesize MouseMove: WA_Hover widgets convert
                        # it back to HoverMove and recursively deliver events.
                        index = (view.indexAt(event.position().toPoint())
                                 if isinstance(event, (QHoverEvent, QMouseEvent)) else QModelIndex())
                        view.setProperty("comboHoveredIndex", index)
                        watched.update()
        except RuntimeError:
            # During application exit Qt can deliver events to C++ objects
            # whose Python wrappers still exist while the widgets are torn down.
            return False
        return False


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
