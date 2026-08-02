from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtWidgets import QApplication, QSizePolicy

from dps_studio.core.models import SignalRecord
from dps_studio.gui.app import translation_manager
from dps_studio.gui.display_preferences import (
    DEFAULT_SPECTROGRAM_COLORMAP,
    DisplayPreferences,
    SPECTROGRAM_COLORMAP_SETTINGS_KEY,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.raw_signal_view import RawSignalView
from dps_studio.gui.result_views import SpectrogramView, relative_magnitude_db


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _settings(path: Path) -> QSettings:
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.clear()
    settings.sync()
    return settings


def _display_analysis() -> Any:
    spectrum = np.array(
        [
            [1.0 + 0.0j, 0.5 + 0.0j, 0.25 + 0.0j, 0.125 + 0.0j],
            [0.8 + 0.2j, 0.4 + 0.1j, 0.2 + 0.05j, 0.1 + 0.025j],
            [0.6 + 0.0j, 0.3 + 0.0j, 0.15 + 0.0j, 0.075 + 0.0j],
        ],
        dtype=np.complex128,
    )
    return SimpleNamespace(
        stft_result=SimpleNamespace(
            spectrum=spectrum,
            time_s=np.linspace(1.0e-6, 4.0e-6, 4),
            frequency_hz=np.linspace(0.1e9, 0.3e9, 3),
        ),
        ridge_result=SimpleNamespace(
            minimum_frequency_hz=0.1e9,
            maximum_frequency_hz=0.3e9,
        ),
        signal_detection_result=SimpleNamespace(
            analysis_start_time_s=1.0e-6,
            analysis_end_time_s=4.0e-6,
        ),
    )


def test_colormaps_are_display_only_and_colorbar_matches_definition(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    preferences = DisplayPreferences(_settings(tmp_path / "display.ini"))
    assert preferences.spectrogram_colormap() == DEFAULT_SPECTROGRAM_COLORMAP

    view = SpectrogramView()
    analysis = _display_analysis()
    spectrum_before = analysis.stft_result.spectrum.copy()
    try:
        assert view.current_colormap_name == "viridis"
        view.set_analyses({"pdv": analysis}, relative_db_floor=-60.0)
        expected = relative_magnitude_db(analysis, floor_db=-60.0)
        np.testing.assert_array_equal(view.current_image_db, expected)
        image_before = view.current_image_db.copy()

        view.set_colormap("grayscale")
        assert view.current_colormap_name == "grayscale"
        np.testing.assert_array_equal(analysis.stft_result.spectrum, spectrum_before)
        np.testing.assert_array_equal(view.current_image_db, image_before)

        view.set_colormap("cividis")
        assert view.current_colormap_name == "cividis"
        np.testing.assert_array_equal(analysis.stft_result.spectrum, spectrum_before)
        np.testing.assert_array_equal(view.current_image_db, image_before)
        assert view.image_item.getLevels() == pytest.approx((-60.0, 0.0))
        assert view.color_bar.levels() == pytest.approx((-60.0, 0.0))
        assert view.color_bar.getAxis("left").labelText == "相对 STFT 幅值 (dB)"
        assert "SNR" not in view.color_bar.getAxis("left").labelText
        assert "20 log10(|STFT| / max|STFT|)" in view.color_bar.toolTip()
        assert "不是正式 SNR" in view.color_bar.toolTip()
        assert not view.color_bar.interactive
        assert view.color_bar.region is None
    finally:
        view.close()
        qapp.processEvents()


def test_colormap_persists_without_invalidating_science_result_state(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "colormap.ini")
    window = MainWindow(
        translation_manager=translation_manager(),
        settings=settings,
    )
    try:
        window.analysis_session.results_valid = True
        generation = window.analysis_session.generation_id
        window.spectrogram_view.colormap_combo.setCurrentIndex(
            window.spectrogram_view.colormap_combo.findData("cividis")
        )
        qapp.processEvents()
        assert settings.value(SPECTROGRAM_COLORMAP_SETTINGS_KEY) == "cividis"
        assert window.spectrogram_view.current_colormap_name == "cividis"
        assert window.ridge_view.current_colormap_name == "cividis"
        assert window.analysis_session.results_valid
        assert window.analysis_session.generation_id == generation
    finally:
        window.close()
        qapp.processEvents()

    restored = MainWindow(
        translation_manager=translation_manager(),
        settings=settings,
    )
    try:
        assert restored.spectrogram_view.current_colormap_name == "cividis"
        assert restored.spectrogram_view.colormap_combo.currentData() == "cividis"
    finally:
        restored.close()
        qapp.processEvents()


def test_analysis_boundaries_use_native_hover_hit_shape_and_resize_cursor(
    qapp: QApplication,
) -> None:
    time_s = np.linspace(1.0e-6, 5.0e-6, 128)
    voltage_v = np.linspace(-1.0, 1.0, 128)
    record = SignalRecord(time_s, voltage_v)
    time_before = record.time_s.copy()
    voltage_before = record.voltage_v.copy()
    view = RawSignalView()
    hover_states: list[bool] = []
    ranges: list[tuple[float, float]] = []
    view.analysis_boundary_hovered.connect(hover_states.append)
    view.analysis_region_changed.connect(
        lambda start, end: ranges.append((start, end))
    )
    try:
        view.resize(900, 500)
        view.show()
        view.set_records({"pdv": record})
        qapp.processEvents()
        for line in view.analysis_region.lines:
            assert line.hoverPen.widthF() == pytest.approx(4.0)
            assert line.pen.widthF() == pytest.approx(1.0)
            assert line.cursor().shape() is Qt.CursorShape.SizeHorCursor
            assert line.markers
            assert line.toolTip() == "拖动以调整分析范围"

        first_line = view.analysis_region.lines[0]
        scene_position = first_line.mapToScene(QPointF(0.0, 0.0))
        view._update_boundary_hover_state(scene_position)
        assert hover_states[-1] is True

        region_before_zoom = tuple(view.analysis_region.getRegion())
        view.plot_widget.setXRange(2.0, 3.0, padding=0.0)
        qapp.processEvents()
        assert tuple(view.analysis_region.getRegion()) == pytest.approx(
            region_before_zoom
        )

        view.analysis_region.setRegion((2.0, 4.0))
        qapp.processEvents()
        assert ranges[-1] == pytest.approx((2.0e-6, 4.0e-6))
        np.testing.assert_array_equal(record.time_s, time_before)
        np.testing.assert_array_equal(record.voltage_v, voltage_before)
    finally:
        view.close()
        qapp.processEvents()


def test_workspace_splitter_and_bottom_dock_are_programmatically_resizable(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(
        translation_manager=translation_manager(),
        settings=_settings(tmp_path / "resize.ini"),
    )
    try:
        window.resize(1440, 900)
        window.show()
        qapp.processEvents()
        splitter = window.workspace_splitter
        available = sum(splitter.sizes())
        first = [150, available - 390, 240]
        splitter.setSizes(first)
        qapp.processEvents()
        assert splitter.sizes() == first
        second = [300, available - 600, 300]
        splitter.setSizes(second)
        qapp.processEvents()
        assert splitter.sizes() == second
        assert splitter.handleWidth() >= 7
        assert all(not splitter.isCollapsible(index) for index in range(3))
        assert window.science_tabs.width() > 0
        for panel in (window.navigation_panel, window.parameter_panel):
            assert panel.minimumWidth() < panel.maximumWidth()
            assert panel.sizePolicy().horizontalPolicy() is QSizePolicy.Policy.Ignored

        window.resizeDocks(
            [window.diagnostics_dock],
            [170],
            Qt.Orientation.Vertical,
        )
        qapp.processEvents()
        small_height = window.diagnostics_dock.height()
        window.resizeDocks(
            [window.diagnostics_dock],
            [400],
            Qt.Orientation.Vertical,
        )
        qapp.processEvents()
        large_height = window.diagnostics_dock.height()
        assert small_height <= 180
        assert large_height >= 390
        assert large_height > small_height
    finally:
        window.close()
        qapp.processEvents()


def test_layout_settings_restore_reset_and_survive_language_change(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "layout.ini")
    manager = translation_manager()
    manager.install("zh_CN")
    first = MainWindow(translation_manager=manager, settings=settings)
    try:
        first.resize(1440, 900)
        first.show()
        qapp.processEvents()
        available = sum(first.workspace_splitter.sizes())
        first.workspace_splitter.setSizes([280, available - 570, 290])
        first.resizeDocks(
            [first.diagnostics_dock],
            [390],
            Qt.Orientation.Vertical,
        )
        qapp.processEvents()
        saved_left = first.workspace_splitter.sizes()[0]
        saved_right = first.workspace_splitter.sizes()[2]
        saved_bottom = first.diagnostics_dock.height()
    finally:
        first.close()
        qapp.processEvents()

    assert settings.contains("layout/main_window_geometry")
    assert settings.contains("layout/main_window_state")
    assert settings.contains("layout/workspace_splitter_state")
    assert settings.contains("layout/diagnostics_dock_height")

    manager.install("en")
    restored = MainWindow(translation_manager=manager, settings=settings)
    try:
        restored.show()
        qapp.processEvents()
        assert restored.view_menu.title() == "View"
        assert restored.workspace_splitter.sizes()[0] == saved_left
        assert restored.workspace_splitter.sizes()[2] == saved_right
        assert restored.diagnostics_dock.height() == saved_bottom
        assert (
            restored.spectrogram_view.color_bar.getAxis("left").labelText
            == "Relative STFT Magnitude (dB)"
        )

        restored.action_restore_default_layout.trigger()
        qapp.processEvents()
        reset_sizes = restored.workspace_splitter.sizes()
        assert reset_sizes[0] == 220
        assert reset_sizes[2] == 340
        assert reset_sizes[1] > 0
        assert restored.diagnostics_dock.height() == 210
        assert restored.diagnostics_dock.isVisible()
    finally:
        restored.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_invalid_old_layout_values_fall_back_without_crashing(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "invalid-layout.ini")
    settings.setValue("layout/main_window_geometry", b"invalid")
    settings.setValue("layout/main_window_state", b"invalid")
    settings.setValue("layout/workspace_splitter_state", b"invalid")
    settings.setValue("layout/diagnostics_dock_height", "not-an-int")
    window = MainWindow(
        translation_manager=translation_manager(),
        settings=settings,
    )
    try:
        window.show()
        qapp.processEvents()
        sizes = window.workspace_splitter.sizes()
        assert sizes[0] >= window.navigation_panel.minimumWidth()
        assert sizes[1] > 0
        assert sizes[2] >= window.parameter_panel.minimumWidth()
    finally:
        window.close()
        qapp.processEvents()


def test_gui_has_no_scripts_dependency_and_protected_paths_are_clean() -> None:
    for path in (REPOSITORY_ROOT / "src" / "dps_studio" / "gui").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from scripts" not in source
        assert "import scripts" not in source

    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "data/raw", "scripts", "outputs"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
