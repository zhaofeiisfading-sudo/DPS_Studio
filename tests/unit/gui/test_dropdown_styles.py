"""Popup painting and geometry regressions against real Qt widgets and events."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QObject, QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QCursor, QHoverEvent, QImage, QPainter, QPalette, QStandardItemModel, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QMenu, QStyle, QStyledItemDelegate, QStyleFactory,
    QStyleOptionViewItem, QWidget,
)

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.research_window import ResearchMainWindow
from dps_studio.gui.styles import APPLICATION_STYLE_SHEET, apply_application_style
from dps_studio.gui import styles


def _pixels(image: QImage) -> np.ndarray:
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(rgba.constBits(), dtype=np.uint8).reshape(
        rgba.height(), rgba.width(), 4)[..., :3].copy()


def _rgb(value: str) -> np.ndarray:
    return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)])


def _show_popup(combo: QComboBox, app: QApplication) -> None:
    combo.showPopup()
    app.processEvents()
    assert QTest.qWaitForWindowExposed(combo.view().window(), 2000)
    app.processEvents()


def _contrast(first: np.ndarray, second: np.ndarray) -> float:
    def luminance(rgb: np.ndarray) -> float:
        channels = rgb / 255
        linear = np.where(channels <= .04045, channels / 12.92, ((channels + .055) / 1.055) ** 2.4)
        return float(linear @ np.array([.2126, .7152, .0722]))

    low, high = sorted((luminance(first), luminance(second)))
    return (high + .05) / (low + .05)


def _assert_row(image: QImage, background: str, foreground: str, *, disabled: bool = False) -> None:
    pixels = _pixels(image)
    bg, fg = _rgb(background), _rgb(foreground)
    assert np.count_nonzero(np.all(pixels == bg, axis=2)) > pixels.shape[0] * pixels.shape[1] * .55
    # Rasterized ink must survive; native Windows snapshots also cover glyph shaping.
    ink = np.max(np.abs(pixels.astype(int) - fg), axis=2) <= 18
    assert np.count_nonzero(ink) >= 12
    assert _contrast(bg, fg) >= (2.5 if disabled else 7)
    if background != "#ffffff":
        assert np.count_nonzero(np.all(pixels == 255, axis=2)) == 0


@pytest.fixture(params=[("Fusion", Qt.ColorScheme.Light), ("Fusion", Qt.ColorScheme.Dark),
                        ("windows11", Qt.ColorScheme.Light), ("windows11", Qt.ColorScheme.Dark)],
                ids=["fusion-light", "fusion-dark", "windows11-light", "windows11-dark"])
def themed_app(qapp: QApplication, request: pytest.FixtureRequest) -> Iterator[QApplication]:
    name, scheme = request.param
    if name.lower() not in [key.lower() for key in QStyleFactory.keys()]:
        pytest.skip(f"Qt style {name} is unavailable on this platform")
    original_style = qapp.style().objectName() or QStyleFactory.keys()[0]
    original_scheme = qapp.styleHints().colorScheme()
    qapp.setStyle(name)
    qapp.styleHints().setColorScheme(scheme)
    apply_application_style(qapp)
    qapp.processEvents()
    try:
        yield qapp
    finally:
        qapp.styleHints().setColorScheme(original_scheme)
        qapp.setStyle(original_style)
        apply_application_style(qapp)
        qapp.processEvents()


@pytest.fixture
def combo(themed_app: QApplication) -> Iterator[QComboBox]:
    widget = QComboBox()
    widget.addItems(["Normal 正常", "Hover 悬停", "Disabled 不可选", "Keyboard 键盘"])
    model = widget.model()
    assert isinstance(model, QStandardItemModel)
    model.item(2).setEnabled(False)
    widget.resize(180, 34)
    widget.show()
    _show_popup(widget, themed_app)
    try:
        yield widget
    finally:
        widget.hidePopup()
        widget.close()
        widget.deleteLater()
        themed_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_stylesheet_and_palette_contracts(qapp: QApplication) -> None:
    for selector in ("QComboBox:enabled", "QComboBox:hover:enabled", "QComboBox:on:enabled",
                     "QComboBox:focus:enabled", "QComboBox:disabled",
                     "QComboBox QAbstractItemView::item:hover",
                     "QComboBox QAbstractItemView::item:selected:hover",
                     "QComboBox QAbstractItemView::item:disabled", "selection-color: #0f3f5f",
                     "QMenu::item:selected", "QMenu::item:disabled", "QMenu::separator"):
        assert selector in APPLICATION_STYLE_SHEET
    assert APPLICATION_STYLE_SHEET.rindex("\nQMenu {") > APPLICATION_STYLE_SHEET.rindex("\nQWidget {")
    assert "QListWidget::item:hover" not in APPLICATION_STYLE_SHEET
    assert "QComboBox:on:enabled { background: #f4f9fd; border-color: #0b6fa4; }" in APPLICATION_STYLE_SHEET
    assert "QComboBox:focus:enabled { background: #ffffff; border-color: #0b6fa4; }" in APPLICATION_STYLE_SHEET
    assert "QComboBox:focus:enabled, QComboBox:on:enabled" not in APPLICATION_STYLE_SHEET
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        assert qapp.palette().color(group, QPalette.ColorRole.Highlight).name() == "#d2e7f5"
        assert qapp.palette().color(group, QPalette.ColorRole.HighlightedText).name() == "#0f3f5f"


def test_delegate_raster_states(combo: QComboBox, themed_app: QApplication, tmp_path: Path) -> None:
    view = combo.view()
    delegate = view.itemDelegate()
    view.setProperty("comboHoveredIndex", None)
    assert isinstance(delegate, QStyledItemDelegate)
    for label, flags, bg, fg, row in (
        ("normal", QStyle.StateFlag.State_Enabled, "#ffffff", "#283d4c", 1),
        ("hover", QStyle.StateFlag.State_MouseOver, "#e6f1f8", "#154c73", 1),
        ("selected", QStyle.StateFlag.State_Selected, "#d2e7f5", "#0f3f5f", 1),
        ("selected-hover", QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
         "#c2ddf0", "#0b3450", 1),
        ("keyboard-focus", QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus,
         "#d2e7f5", "#0f3f5f", 1),
        ("disabled-hover", QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver |
         QStyle.StateFlag.State_HasFocus, "#ffffff", "#8a98a3", 2),
    ):
        image = QImage(240, 36, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.magenta)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 240, 36)
        option.state = flags | QStyle.StateFlag.State_Enabled
        option.widget = view
        painter = QPainter(image)
        delegate.paint(painter, option, combo.model().index(row, 0))
        painter.end()
        _assert_row(image, bg, fg, disabled=row == 2)
        pixels = _pixels(image)
        cue = np.count_nonzero(np.all(pixels == _rgb("#0b6fa4"), axis=2))
        assert (cue > 0) == (label == "keyboard-focus")
        assert image.save(str(tmp_path / f"{label}.png"))


def _hover(combo: QComboBox, row: int, app: QApplication) -> QImage:
    view = combo.view()
    viewport = view.viewport()
    rect = view.visualRect(combo.model().index(row, 0))
    point = rect.center()
    QTest.mouseMove(viewport, point)
    position = QPointF(point)
    QApplication.sendEvent(viewport, QHoverEvent(
        QEvent.Type.HoverMove, position, QPointF(viewport.mapToGlobal(point)), QPointF()))
    app.processEvents()
    return viewport.grab(rect).toImage()


def test_hover_enter_highlights_immediately(combo: QComboBox, tmp_path: Path) -> None:
    view = combo.view()
    viewport = view.viewport()
    index = combo.model().index(1, 0)
    rect = view.visualRect(index)
    view.selectionModel().clearSelection()
    view.setProperty("comboHoveredIndex", QModelIndex())
    QApplication.sendEvent(viewport, QHoverEvent(
        QEvent.Type.HoverEnter, QPointF(rect.center()),
        QPointF(viewport.mapToGlobal(rect.center())), QPointF()))
    assert view.property("comboHoveredIndex") == index
    image = viewport.grab(rect).toImage()
    _assert_row(image, "#e6f1f8", "#154c73")
    assert image.save(str(tmp_path / "hover-enter.png"))


def test_disabled_style_option_mutes_enabled_model_item(combo: QComboBox, tmp_path: Path) -> None:
    view = combo.view()
    index = combo.model().index(1, 0)
    assert index.flags() & Qt.ItemFlag.ItemIsEnabled
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 240, 36)
    option.widget = view
    option.state = (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver |
                    QStyle.StateFlag.State_HasFocus)
    assert not option.state & QStyle.StateFlag.State_Enabled
    image = QImage(240, 36, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.magenta)
    painter = QPainter(image)
    view.itemDelegate().paint(painter, option, index)
    painter.end()
    _assert_row(image, "#ffffff", "#8a98a3", disabled=True)
    assert not np.any(np.all(_pixels(image) == _rgb("#0b6fa4"), axis=2))
    assert image.save(str(tmp_path / "disabled-option.png"))


def _wheel(viewport: QWidget, point: QPoint) -> None:
    QApplication.sendEvent(viewport, QWheelEvent(
        QPointF(point), QPointF(viewport.mapToGlobal(point)), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False))


def test_scroll_wheel_recomputes_hover_under_stationary_cursor(
    themed_app: QApplication, tmp_path: Path,
) -> None:
    combo = QComboBox()
    combo.addItems([f"Profile {i:03d} — 滚轮悬停" for i in range(100)])
    combo.resize(240, 34)
    combo.setMaxVisibleItems(6)
    view = combo.view()
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    original_cursor = QCursor.pos()
    try:
        combo.show()
        _show_popup(combo, themed_app)
        viewport = view.viewport()
        point = viewport.rect().center()
        global_point = viewport.mapToGlobal(point)
        QCursor.setPos(global_point)
        themed_app.processEvents()
        before_index = view.indexAt(point)
        assert before_index.isValid() and viewport.rect().contains(point)
        before_scroll = view.verticalScrollBar().value()
        view.setProperty("comboHoveredIndex", before_index)
        assert view.verticalScrollBar().maximum() > 0
        _wheel(viewport, point)
        _wheel(viewport, point)
        assert viewport.property("comboHoverUpdatePending")
        themed_app.processEvents()
        assert not viewport.property("comboHoverUpdatePending")
        assert QCursor.pos() == global_point
        assert viewport.rect().contains(viewport.mapFromGlobal(QCursor.pos()))
        assert view.verticalScrollBar().value() > before_scroll
        after_index = view.indexAt(viewport.mapFromGlobal(QCursor.pos()))
        assert after_index.isValid() and after_index != before_index
        assert view.property("comboHoveredIndex") == after_index
        selected = view.selectionModel().isSelected(after_index)
        image = viewport.grab(view.visualRect(after_index)).toImage()
        _assert_row(image, "#c2ddf0" if selected else "#e6f1f8",
                    "#0b3450" if selected else "#154c73")
        assert image.save(str(tmp_path / "wheel-hover.png"))
    finally:
        combo.hidePopup()
        combo.close()
        combo.deleteLater()
        themed_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCursor.setPos(original_cursor)


def test_popup_events_and_deferred_hover_survive_teardown(qapp: QApplication) -> None:
    from shiboken6 import delete

    combo = QComboBox()
    combo.addItems(["First", "Second"])
    combo.ensurePolished()
    view = combo.view()
    viewport = view.viewport()
    helper = qapp.findChild(QObject, "comboPopupStyleFilter")
    assert helper is not None
    _wheel(viewport, QPoint(10, 10))
    assert viewport.property("comboHoverUpdatePending")
    delete(combo)
    assert helper.eventFilter(viewport, QEvent(QEvent.Type.Leave)) is False
    styles._refresh_combo_hover_after_scroll(view, viewport)
    qapp.processEvents()


def test_live_hover_keyboard_and_disabled(combo: QComboBox, themed_app: QApplication,
                                         tmp_path: Path) -> None:
    view = combo.view()
    assert view.hasMouseTracking() and view.viewport().hasMouseTracking()
    assert view.viewport().testAttribute(Qt.WidgetAttribute.WA_Hover)
    hovered = _hover(combo, 1, themed_app)
    selected = view.selectionModel().isSelected(combo.model().index(1, 0))
    _assert_row(hovered, "#c2ddf0" if selected else "#e6f1f8",
                "#0b3450" if selected else "#154c73")
    assert hovered.save(str(tmp_path / "live-hover.png"))
    view.setCurrentIndex(combo.model().index(1, 0))
    view.selectionModel().select(combo.model().index(1, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    _assert_row(_hover(combo, 1, themed_app), "#c2ddf0", "#0b3450")
    # HoverMove must work by itself, without a MouseMove selecting that row.
    view.selectionModel().clearSelection()
    point = view.visualRect(combo.model().index(1, 0)).center()
    QApplication.sendEvent(view.viewport(), QHoverEvent(
        QEvent.Type.HoverMove, QPointF(point), QPointF(view.viewport().mapToGlobal(point)), QPointF()))
    themed_app.processEvents()
    _assert_row(view.viewport().grab(view.visualRect(combo.model().index(1, 0))).toImage(),
                "#e6f1f8", "#154c73")
    view.setCurrentIndex(combo.model().index(1, 0))
    view.selectionModel().select(combo.model().index(1, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    disabled = _hover(combo, 2, themed_app)
    _assert_row(disabled, "#ffffff", "#8a98a3", disabled=True)
    assert disabled.save(str(tmp_path / "live-disabled.png"))
    QTest.keyClick(view, Qt.Key.Key_Down)
    themed_app.processEvents()
    assert view.currentIndex().row() == 3  # Skip the disabled entry.
    QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
    view.setFocus(Qt.FocusReason.TabFocusReason)
    themed_app.processEvents()
    _assert_row(view.viewport().grab(view.visualRect(combo.model().index(3, 0))).toImage(),
                "#d2e7f5", "#0f3f5f")
    QTest.keyClick(view, Qt.Key.Key_Up)
    themed_app.processEvents()
    assert view.currentIndex().row() == 1
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert combo.currentIndex() == 1
    # Closed disabled state also has the specified text color.
    combo.setEnabled(False)
    themed_app.processEvents()
    assert combo.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == "#8a98a3"


@pytest.mark.parametrize("window_size", [(1024, 640), (1280, 720), (1366, 768)])
def test_narrow_popup_width_and_screen_edges(qapp: QApplication, window_size: tuple[int, int]) -> None:
    window = QWidget()
    window.resize(*window_size)
    combo = QComboBox(window)
    combo.setGeometry(window_size[0] - 110, window_size[1] - 70, 90, 32)
    combo.addItems(["均衡 STFT：用于含多个候选分支的人工分段研究对照",
                    "Long English analysis profile with explicit measurement quality diagnostics"])
    combo.addItems([f"Scrollable profile {i}" for i in range(80)])
    combo.setMaxVisibleItems(8)
    window.show()
    _show_popup(combo, qapp)
    try:
        view = combo.view()
        popup = view.window()
        available = combo.screen().availableGeometry()
        assert available.contains(popup.geometry())
        assert popup.width() >= combo.width()
        required = view.sizeHintForColumn(0)
        assert popup.width() >= min(required, available.width() - 8)
        assert view.viewport().width() >= min(required, available.width() - 40)
        # A later shorter model must not inherit the old large minimum width.
        combo.hidePopup()
        combo.clear()
        combo.addItem("Short")
        _show_popup(combo, qapp)
        assert combo.width() <= popup.width() < required
    finally:
        combo.hidePopup()
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_menu_surface_and_enabled_disabled_hover(themed_app: QApplication, tmp_path: Path) -> None:
    menu = QMenu()
    action = menu.addAction("Open 打开")
    disabled = menu.addAction("Disabled 禁用")
    disabled.setEnabled(False)
    menu.addSeparator()
    menu.popup(QPoint(40, 40))
    assert QTest.qWaitForWindowExposed(menu, 2000)
    themed_app.processEvents()
    try:
        menu.setActiveAction(action)
        QTest.mouseMove(menu, menu.actionGeometry(action).center())
        themed_app.processEvents()
        _assert_row(menu.grab(menu.actionGeometry(action)).toImage(), "#e6f1f8", "#154c73")
        QTest.mouseMove(menu, menu.actionGeometry(disabled).center())
        themed_app.processEvents()
        _assert_row(menu.grab(menu.actionGeometry(disabled)).toImage(), "#ffffff", "#8a98a3", disabled=True)
        assert menu.grab().toImage().pixelColor(2, 2).name() == "#ffffff"
        assert menu.grab().save(str(tmp_path / "menu.png"))
    finally:
        menu.close()
        menu.deleteLater()
        themed_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_rebuilt_table_combos_idempotence_and_validation(qapp: QApplication, tmp_path: Path) -> None:
    time = np.arange(4096) / 40e9
    source = tmp_path / "synthetic.csv"
    np.savetxt(source, np.column_stack((time, .1 * np.cos(2 * np.pi * 600e6 * time))), delimiter=",")
    window = ResearchMainWindow(
        settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path / "presets.json"))
    window.set_loaded_result(read_delimited_signals(source, time_column=0, voltage_columns={"ch1": 1}))
    window.analysis_range_panel.use_full_range()
    window.show()
    window.mode_combo.setCurrentIndex(1)
    qapp.processEvents()
    try:
        workspace = window.segment_workspace
        dialog = ImportSettingsDialog(source, window)
        dialog.ensurePolished()
        combos = window.findChildren(QComboBox)
        assert len(combos) >= 30
        for control in combos:
            control.ensurePolished()
            assert type(control.view().itemDelegate()).__name__ == "_ComboItemDelegate"
        dialog.close()
        workspace.add_boundary()
        qapp.processEvents()
        for row in range(workspace.table.rowCount()):
            for column in (3, 4):
                combo = workspace.table.cellWidget(row, column)
                assert isinstance(combo, QComboBox)
                _show_popup(combo, qapp)
                delegate = combo.view().itemDelegate()
                assert type(delegate).__name__ == "_ComboItemDelegate"
                apply_application_style(qapp)
                apply_application_style(qapp)
                assert combo.view().itemDelegate() is delegate
                assert len(combo.view().findChildren(type(delegate))) == 1
                combo.view().setCurrentIndex(combo.model().index(1, 0))
                _assert_row(_hover(combo, 1, qapp), "#c2ddf0", "#0b3450")
                combo.hidePopup()
        filters = [child for child in qapp.children() if child.objectName() == "comboPopupStyleFilter"]
        assert len(filters) == 1
        window._set_parameter_validation_state(False, "Invalid test parameters")
        assert "c62828" in window.nfft_spin.styleSheet()
        for combo in (window.window_name_combo, window.automatic_ridge_extraction_combo):
            assert "QComboBox {" in combo.styleSheet() and "c62828" in combo.styleSheet()
            _show_popup(combo, qapp)
            image = _pixels(combo.view().window().grab().toImage())
            assert not np.any(np.all(image == _rgb("#c62828"), axis=2))
            combo.hidePopup()
        window._set_parameter_validation_state(True, "")
        assert not window.window_name_combo.styleSheet()
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
