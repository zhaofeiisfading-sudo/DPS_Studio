"""Regression coverage for QComboBox popup hover/selection styling and readability."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QStyledItemDelegate

from dps_studio.gui.app import translation_manager
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.styles import APPLICATION_STYLE_SHEET


def _relative_luminance(color: QColor) -> float:
    """Compute WCAG relative luminance for sRGB contrast checks."""
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    lum_a = _relative_luminance(foreground)
    lum_b = _relative_luminance(background)
    bright, dark = max(lum_a, lum_b), min(lum_a, lum_b)
    return (bright + 0.05) / (dark + 0.05)


def _grab_popup_image(
    qapp: QApplication,
    combo: QComboBox,
    hover_row: int | None = None,
) -> tuple[QImage, tuple[int, int, int, int]]:
    """Open a combo popup, optionally hover a row, and return image + row box."""
    combo.showPopup()
    qapp.processEvents()
    view = combo.view()
    viewport = view.viewport()
    target_row = 0 if hover_row is None else hover_row
    rect = view.visualRect(combo.model().index(target_row, 0))
    if hover_row is not None:
        local_pos = QPointF(rect.center())
        global_pos = viewport.mapToGlobal(rect.center())
        qapp.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.Type.MouseMove,
                local_pos,
                global_pos,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        qapp.processEvents()
    popup_window = view.window()
    image = popup_window.grab().toImage()
    dpr = image.devicePixelRatio()
    top_left = viewport.mapTo(popup_window, rect.topLeft())
    bottom_right = viewport.mapTo(popup_window, rect.bottomRight())
    bounds = (
        int(top_left.x() * dpr),
        int(top_left.y() * dpr),
        int(bottom_right.x() * dpr),
        int(bottom_right.y() * dpr),
    )
    return image, bounds


def test_global_style_configures_all_combobox_popups_including_dialogs(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    source = tmp_path / "sample.csv"
    source.write_text("0,1,2\n1,3,4\n", encoding="utf-8")
    dialog = ImportSettingsDialog(source, parent=window)
    dynamic_dialog = QDialog()
    dynamic_combo = QComboBox(dynamic_dialog)
    dynamic_combo.addItems(["选项 A", "Option B"])
    try:
        dynamic_dialog.show()
        qapp.processEvents()
        all_combos = [
            *window.findChildren(QComboBox),
            *dialog.findChildren(QComboBox),
            dynamic_combo,
        ]
        assert all_combos
        for combo in all_combos:
            assert combo.property("comboBoxPopupConfigured") is True
            assert isinstance(combo.itemDelegate(), QStyledItemDelegate)
            palette = combo.view().palette()
            assert palette.color(QPalette.ColorRole.Base) == QColor("#ffffff")
            assert palette.color(QPalette.ColorRole.Text) == QColor("#1b2a3b")
            assert palette.color(QPalette.ColorRole.HighlightedText) == QColor("#102a43")
            assert (
                _contrast_ratio(
                    palette.color(QPalette.ColorRole.HighlightedText),
                    palette.color(QPalette.ColorRole.Highlight),
                )
                >= 7.0
            )
    finally:
        dynamic_dialog.close()
        dialog.close()
        window.close()


def test_stylesheet_defines_combobox_and_menu_item_states() -> None:
    for selector in (
        "QComboBox QAbstractItemView {",
        "QComboBox QAbstractItemView::item {",
        "QComboBox QAbstractItemView::item:selected {",
        "QComboBox QAbstractItemView::item:hover:enabled",
        "QComboBox QAbstractItemView::item:pressed:enabled",
        "QComboBox QAbstractItemView::item:disabled",
        "QMenu::item:selected {",
        "QMenuBar::item:selected {",
    ):
        assert selector in APPLICATION_STYLE_SHEET


def test_combobox_popup_hover_selected_and_disabled_items_remain_legible(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.resize(1366, 768)
        window.show()
        qapp.processEvents()
        combo = window.window_name_combo

        # Hover Chinese label ("矩形窗（Boxcar）") and verify background + dark text contrast.
        image, (x0, y0, x1, y1) = _grab_popup_image(qapp, combo, hover_row=4)
        try:
            bg = image.pixelColor(max(x0 + 4, x1 - 12), (y0 + y1) // 2)
            assert bg == QColor("#d2e5f3")
            darkest = QColor("#ffffff")
            for x in range(x0 + 6, min(x1 - 6, x0 + 180)):
                for y in range(y0 + 3, y1 - 3):
                    pixel = image.pixelColor(x, y)
                    if _relative_luminance(pixel) < _relative_luminance(darkest):
                        darkest = pixel
            assert _contrast_ratio(darkest, bg) >= 7.0
        finally:
            combo.hidePopup()

        # Hovering a disabled item must not paint the enabled hover highlight.
        model = combo.model()
        item = model.item(1)  # type: ignore[attr-defined]
        item.setEnabled(False)
        try:
            disabled_image, (dx0, dy0, dx1, dy1) = _grab_popup_image(qapp, combo, hover_row=1)
            try:
                disabled_bg = disabled_image.pixelColor(
                    max(dx0 + 4, dx1 - 12),
                    (dy0 + dy1) // 2,
                )
                assert disabled_bg == QColor("#ffffff")
            finally:
                combo.hidePopup()
        finally:
            item.setEnabled(True)
    finally:
        window.close()


def test_validation_error_border_does_not_leak_to_combobox_popup(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.resize(1366, 768)
        window.show()
        qapp.processEvents()
        combo = window.window_name_combo
        window._set_parameter_validation_state(False, "invalid")
        assert "c62828" in combo.styleSheet()
        image, _ = _grab_popup_image(qapp, combo, hover_row=2)
        try:
            top_border_color = image.pixelColor(image.width() // 2, 0)
            assert top_border_color != QColor("#c62828")
        finally:
            combo.hidePopup()
            window._set_parameter_validation_state(True, "")
    finally:
        window.close()


def test_narrow_combobox_popup_expands_for_long_chinese_labels(
    qapp: QApplication,
) -> None:
    dialog = QDialog()
    combo = QComboBox(dialog)
    combo.setFixedWidth(98)
    combo.addItems(["伏 (V)", "毫伏 (mV)", "空白字符（空格 / Tab）长标签校验"])
    try:
        dialog.show()
        qapp.processEvents()
        combo.showPopup()
        qapp.processEvents()
        view = combo.view()
        popup = view.window()
        assert popup.width() >= view.sizeHintForColumn(0)
        combo.hidePopup()
    finally:
        dialog.close()
