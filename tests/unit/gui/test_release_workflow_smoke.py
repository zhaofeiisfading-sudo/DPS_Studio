"""Release regressions: translated sidebar geometry and independent derivatives."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.release_workflow_smoke import _exercise, event_option_geometry


@pytest.mark.parametrize("language", ["zh_CN", "en"])
@pytest.mark.parametrize("width,height", [(1024, 640), (1366, 768)])
def test_event_labels_fit_translated_sidebar(qapp: QApplication, tmp_path: Path,
                                            language: str, width: int, height: int) -> None:
    manager = translation_manager()
    manager.install(language)
    window = MainWindow(translation_manager=manager,
        settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path / "presets.json"))
    try:
        window.resize(width, height)
        window.show()
        window.parameter_stack.setCurrentIndex(2)
        qapp.processEvents()
        geometry = event_option_geometry(window)
        assert all(row["width"] >= row["required_width"] and
                   row["height"] >= row["required_height"] for row in geometry), geometry
        if language == "en":
            assert window.analysis_range_panel.manual_event_time_radio.text() == "Manual"
        view = window.velocity_view
        window.science_tabs.setCurrentWidget(view)
        view.quantity_combo.setCurrentIndex(1)
        view.acceleration_method_combo.setCurrentIndex(1)
        qapp.processEvents()
        spin = view.acceleration_window_spin
        assert spin.width() >= spin.sizeHint().width()
        assert spin.mapTo(view, spin.rect().topRight()).x() <= view.width()
        assert view.acceleration_method_combo.width() >= view.acceleration_method_combo.sizeHint().width()
    finally:
        window.close()
        manager.install("zh_CN")


def test_gui_workflow_audits_real_sample_and_exports(qapp: QApplication, tmp_path: Path) -> None:
    window = MainWindow(
        settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path / "window_presets.json"))
    try:
        window.resize(1366, 768)
        window.show()
        source = Path(__file__).resolve().parents[3] / "data/reference/legacy_docs/原始数据.csv"
        report = _exercise(window, source, tmp_path)
        assert report["workflow_complete"] and report["input_unchanged"]
        assert len(report["builtin_derivative_audit"]) == 2
        assert all(not audit["physical_peak_validated"]
                   for audit in report["builtin_derivative_audit"].values())
    finally:
        window.close()
