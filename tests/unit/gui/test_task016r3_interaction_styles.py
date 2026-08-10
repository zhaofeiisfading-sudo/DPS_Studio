"""Regression coverage for TASK-016R3 action-control interaction feedback."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QToolButton

from dps_studio.gui.analysis_range import AnalysisRangePanel
from dps_studio.gui.analysis_session import RidgeExtractionMode
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import (
    _AUTOMATIC_MODE_BUTTON_ID,
    _GUIDED_MODE_BUTTON_ID,
    MainWindow,
)
from dps_studio.gui.styles import APPLICATION_STYLE_SHEET


def test_shared_styles_keep_button_hierarchy_and_navigation_contract() -> None:
    """Keep action feedback centralized without restyling workflow navigation."""
    assert "QPushButton:hover:enabled" in APPLICATION_STYLE_SHEET
    assert "QPushButton:pressed:enabled" in APPLICATION_STYLE_SHEET
    assert "QPushButton:focus:enabled" in APPLICATION_STYLE_SHEET
    assert "QPushButton:disabled" in APPLICATION_STYLE_SHEET
    assert "QPushButton:default:hover:enabled" in APPLICATION_STYLE_SHEET
    assert "QPushButton:default:pressed:enabled" in APPLICATION_STYLE_SHEET
    assert "background: #edf0f2;" in APPLICATION_STYLE_SHEET
    assert "background: #07577f;" in APPLICATION_STYLE_SHEET
    assert "QRadioButton:hover:unchecked" in APPLICATION_STYLE_SHEET
    assert "QRadioButton:hover:checked" in APPLICATION_STYLE_SHEET
    assert "QRadioButton::indicator:checked" in APPLICATION_STYLE_SHEET
    assert "QListWidget::item:selected" in APPLICATION_STYLE_SHEET
    assert "QListWidget::item:hover" not in APPLICATION_STYLE_SHEET


def test_action_cursor_tracks_enabled_state_without_changing_controls(
    qapp: QApplication,
) -> None:
    """Use a click cursor only for available action controls, not input fields."""
    window = MainWindow(translation_manager=translation_manager())
    try:
        secondary = window.cancel_analysis_button
        primary = window.compute_stft_button
        assert not secondary.isEnabled()
        assert not primary.isEnabled()
        assert secondary.cursor().shape() is Qt.CursorShape.ArrowCursor
        assert primary.cursor().shape() is Qt.CursorShape.ArrowCursor

        secondary.setEnabled(True)
        primary.setEnabled(True)
        qapp.processEvents()
        assert secondary.cursor().shape() is Qt.CursorShape.PointingHandCursor
        assert primary.cursor().shape() is Qt.CursorShape.PointingHandCursor

        primary.setEnabled(False)
        qapp.processEvents()
        assert primary.cursor().shape() is Qt.CursorShape.ArrowCursor
        assert (
            window.profile_combo.cursor().shape()
            is not Qt.CursorShape.PointingHandCursor
        )
        assert (
            window.vacuum_wavelength_spin.cursor().shape()
            is not Qt.CursorShape.PointingHandCursor
        )
        toolbar_buttons = window.main_toolbar.findChildren(QToolButton)
        assert toolbar_buttons
        for button in toolbar_buttons:
            expected_cursor = (
                Qt.CursorShape.PointingHandCursor
                if button.isEnabled()
                else Qt.CursorShape.ArrowCursor
            )
            assert button.cursor().shape() is expected_cursor

        group = window.ridge_mode_button_group
        assert window.workflow_navigation.currentRow() == 0
        assert window.automatic_mode_radio.isChecked()
        assert not window.guided_mode_radio.isChecked()
        assert group.checkedId() == _AUTOMATIC_MODE_BUTTON_ID
        assert group.checkedButton() is window.automatic_mode_radio
        assert window.ridge_extraction_mode is RidgeExtractionMode.AUTOMATIC
        assert group.button(_GUIDED_MODE_BUTTON_ID) is window.guided_mode_radio
    finally:
        window.close()
        qapp.processEvents()


def test_range_action_signal_and_dynamic_candidate_cursor_remain_available(
    qapp: QApplication,
) -> None:
    """Preserve right-panel action signals and configure dynamically added actions."""
    panel = AnalysisRangePanel()
    received: list[tuple[float, float]] = []
    panel.range_confirmed.connect(lambda start, end: received.append((start, end)))
    try:
        panel.set_data_bounds(1e-6, 5e-6)
        panel.full_range_button.click()
        assert received == [(1e-6, 5e-6)]

        panel.set_detected_candidates({"pdv_channel_1": 2e-6})
        candidate_button = panel.candidate_buttons["pdv_channel_1"]
        assert candidate_button.cursor().shape() is Qt.CursorShape.PointingHandCursor
        candidate_button.setEnabled(False)
        qapp.processEvents()
        assert candidate_button.cursor().shape() is Qt.CursorShape.ArrowCursor
    finally:
        panel.close()
        qapp.processEvents()
