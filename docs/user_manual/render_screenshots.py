"""Render the Chinese PDV Studio user-manual screenshots from the current GUI.

This helper is documentation-only. It reads ``docs/原始数据.csv`` and writes
only beneath ``docs/user_manual/``; it never edits the input data or production
source files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio.core.ridge import ManualFrequencyBoundary, ManualFrequencyRegion
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[2]
MANUAL_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = MANUAL_DIR / "screenshots"
EXPORT_DIR = MANUAL_DIR / "export_example_manual"
SOURCE_PATH = Path("docs") / "原始数据.csv"
CONFIG_PATH = ROOT / "configs" / "pdv_studio_defaults.toml"


def _wait_for_analysis(window: MainWindow, launch: Callable[[], bool]) -> None:
    """Wait for one normal background analysis to finish."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication is not initialized.")
    loop = QEventLoop()
    outcome: dict[str, object] = {"timed_out": False, "error": None}

    def failed(
        _generation_id: int,
        error_type: str,
        message: str,
        _traceback_text: str,
    ) -> None:
        outcome["error"] = f"{error_type}: {message}"
        loop.quit()

    def timed_out() -> None:
        outcome["timed_out"] = True
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(120_000, timed_out)
    if not launch():
        raise RuntimeError("The GUI rejected the requested analysis.")
    loop.exec()
    window._analysis_adapter.finished.disconnect(loop.quit)
    window._analysis_adapter.failed.disconnect(failed)
    if outcome["timed_out"]:
        raise TimeoutError("The GUI analysis did not finish in 120 seconds.")
    if outcome["error"] is not None:
        raise RuntimeError(str(outcome["error"]))
    if window._analysis_adapter.busy:
        raise RuntimeError("The background analysis remained busy.")
    app.processEvents()


def _capture(widget: object, filename: str) -> dict[str, object]:
    """Capture a visible QWidget-like object without touching the source data."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication is not initialized.")
    app.processEvents()
    image = widget.grab()  # type: ignore[attr-defined]
    path = SCREENSHOT_DIR / filename
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {path}")
    return {"file": path.relative_to(MANUAL_DIR).as_posix(), "width_px": image.width(), "height_px": image.height()}


def _loaded_result() -> object:
    configuration = load_workflow_config(CONFIG_PATH, repository_root=ROOT)
    return DataImportController().load(
        SignalLoadRequest(
            path=SOURCE_PATH,
            time_column=configuration.input.time_column,
            channels=tuple(
                ChannelImportSpec(
                    name,
                    column,
                    configuration.input.voltage_scales[name],
                )
                for name, column in configuration.input.voltage_columns.items()
            ),
            delimiter=",",
            has_header=False,
            encoding="utf-8",
            time_scale=1.0,
        )
    )


def main() -> int:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    application = create_application(sys.argv, language_code="zh_CN")
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/NotoSansSC-VF.ttf")
    font_families = QFontDatabase.applicationFontFamilies(font_id)
    application.setFont(QFont(font_families[0] if font_families else "Noto Sans SC", 9))

    # Capture the real import dialog with the current parser controls.
    import_dialog = ImportSettingsDialog(SOURCE_PATH)
    import_dialog.resize(1000, 900)
    import_dialog.show()
    import_dialog.scroll_area.verticalScrollBar().setValue(0)
    application.processEvents()
    screenshots: list[dict[str, object]] = []
    screenshots.append(_capture(import_dialog, "02_import_dialog.png"))
    import_dialog.close()

    settings = QSettings(
        str(MANUAL_DIR / "screenshot_settings.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    window = MainWindow(translation_manager=translation_manager(), settings=settings)
    window.resize(1440, 900)
    window.show()
    loaded = _loaded_result()
    configuration = load_workflow_config(CONFIG_PATH, repository_root=ROOT)
    window.set_loaded_result(loaded)
    window.set_analysis_configuration(configuration)
    window.analysis_range_panel.use_full_range()
    application.processEvents()

    # Initial state and raw signal are both captured from the loaded real GUI.
    screenshots.insert(0, _capture(window, "01_main_window.png"))
    window.raw_signal_view.channel_combo.setCurrentIndex(1)
    application.processEvents()
    screenshots.append(_capture(window, "03_raw_signal.png"))

    # Quick Analysis intentionally stops at the search-region checkpoint.
    _wait_for_analysis(window, window.run_quick_analysis)
    window.select_workflow_step(1)
    window.science_tabs.setCurrentWidget(window.spectrogram_view)
    window.spectrogram_view.set_search_region_interaction(visible=False, editable=False)
    application.processEvents()
    screenshots.append(_capture(window, "04_spectrogram.png"))
    window.spectrogram_view.set_search_region_interaction(visible=True, editable=True)
    # Make the distinction between the display view and the science region
    # visible without changing the raw data. These are genuine GUI controls.
    window.ridge_time_start_spin.setValue(554.2)
    window.ridge_time_end_spin.setValue(555.7)
    window.maximum_frequency_spin.setValue(2.5)
    window.spectrogram_view.fit_search_region()
    application.processEvents()
    screenshots.append(_capture(window, "05_search_region.png"))

    # Continue the automatic path and show the actual ridge layers.
    _wait_for_analysis(window, window.confirm_search_region_and_continue)
    window.select_workflow_step(1)
    window.science_tabs.setCurrentWidget(window.ridge_view)
    application.processEvents()
    screenshots.append(_capture(window, "06_automatic_ridge.png"))

    # Build a visible Guided corridor using the public current constraint type.
    window._activate_guided_analysis()
    active_times = window.analysis_session.stft_results["pdv_channel_1"].time_s
    active_times = active_times[
        (active_times >= window.analysis_session.analysis_range.start_time_s)
        & (active_times <= window.analysis_session.analysis_range.end_time_s)
    ]
    if active_times.size < 8:
        raise RuntimeError("The screenshot data did not yield enough STFT frames.")
    control_times = np.asarray(
        [active_times[1], active_times[len(active_times) // 3], active_times[-2]],
        dtype=np.float64,
    )
    corridor = ManualFrequencyRegion(
        upper_boundary=ManualFrequencyBoundary(
            control_times_s=control_times,
            control_frequencies_hz=np.asarray([1.15e9, 1.25e9, 1.05e9], dtype=np.float64),
        ),
        lower_boundary=ManualFrequencyBoundary(
            control_times_s=control_times,
            control_frequencies_hz=np.asarray([0.10e9, 0.20e9, 0.10e9], dtype=np.float64),
        ),
    )
    window._ridge_constraint_changed("pdv_channel_1", corridor)
    window.spectrogram_view.fit_search_region()
    application.processEvents()
    screenshots.append(_capture(window, "07_guided.png"))
    _wait_for_analysis(window, window.run_guided_analysis)

    # Velocity page: retain LiF defaults, show the visible final curve and its controls.
    window.select_workflow_step(2)
    window.science_tabs.setCurrentWidget(window.velocity_view)
    window.lif_parameter_toggle.setChecked(True)
    application.processEvents()
    screenshots.append(_capture(window, "08_velocity.png"))

    # Event reference is optional; adopt the displayed automatic candidate for the export example.
    window.analysis_range_panel.automatic_event_time_radio.click()
    application.processEvents()
    screenshots.append(_capture(window, "09_event_reference.png"))

    # Review/export page with event-relative time selected. Suppress the modal success dialog.
    window.select_workflow_step(3)
    window.export_event_time_origin_radio.setChecked(True)
    window._set_export_output_directory(EXPORT_DIR)
    application.processEvents()
    screenshots.append(_capture(window, "10_export.png"))
    old_information = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *_args, **_kwargs: None)  # type: ignore[method-assign]
    try:
        if not window._export_current_result():
            raise RuntimeError("The real GUI export did not complete.")
    finally:
        QMessageBox.information = old_information  # type: ignore[method-assign]

    # A post-export review screen keeps the file list and successful status visible.
    application.processEvents()
    screenshots.append(_capture(window, "11_export_complete.png"))

    # The language preference takes effect after restart, so create a second
    # real main window with the English translator installed.
    window.close()
    application.processEvents()
    create_application([], language_code="en")
    english_settings = QSettings(
        str(MANUAL_DIR / "english_settings.ini"),
        QSettings.Format.IniFormat,
    )
    english_settings.clear()
    english_window = MainWindow(
        translation_manager=translation_manager(),
        settings=english_settings,
    )
    english_window.resize(1440, 900)
    english_window.show()
    english_window.set_loaded_result(loaded)
    english_window.set_analysis_configuration(configuration)
    english_window.analysis_range_panel.use_full_range()
    application.processEvents()
    screenshots.append(_capture(english_window, "12_english.png"))
    english_window.close()
    application.processEvents()

    manifest = {
        "source": str(SOURCE_PATH),
        "config": str(CONFIG_PATH.relative_to(ROOT)),
        "screenshots": screenshots,
        "export_files": sorted(path.name for path in EXPORT_DIR.iterdir() if path.is_file()),
    }
    (MANUAL_DIR / "screenshot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
