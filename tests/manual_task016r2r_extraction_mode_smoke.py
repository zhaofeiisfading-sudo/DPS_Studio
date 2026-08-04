"""Capture native Qt evidence for the TASK-016R2-R extraction-mode controls.

Run manually from the repository root.  The smoke test reads one raw CSV and
writes only ``artifacts/task016r2r``.  It verifies widget, button-group, model,
and worker-source state after real clicks on the Ridge controls.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer

from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.analysis_adapter import AnalysisResultSource
from dps_studio.gui.analysis_session import RidgeExtractionMode
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import (
    _AUTOMATIC_MODE_BUTTON_ID,
    _GUIDED_MODE_BUTTON_ID,
    MainWindow,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"
SOURCE_PATH = REPOSITORY_ROOT / "data" / "raw" / "20260607.csv"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task016r2r"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _wait(
    window: MainWindow,
    launch: Callable[[], bool],
    expected_source: AnalysisResultSource,
) -> None:
    loop = QEventLoop()
    outcome: dict[str, object] = {"timed_out": False, "error": None}

    def timeout() -> None:
        outcome["timed_out"] = True
        loop.quit()

    def failed(
        _generation_id: int,
        error_type: str,
        message: str,
        _traceback_text: str,
    ) -> None:
        outcome["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(90_000, timeout)
    if not launch():
        raise RuntimeError("The Ridge worker rejected the smoke-test request.")
    if window._pending_analysis_source is not expected_source:
        raise AssertionError(
            f"Expected worker source {expected_source}, got "
            f"{window._pending_analysis_source}."
        )
    loop.exec()
    if outcome["timed_out"]:
        raise TimeoutError("The Ridge smoke-test worker exceeded 90 seconds.")
    if outcome["error"] is not None:
        raise RuntimeError(str(outcome["error"]))
    if window._analysis_adapter.busy:
        raise RuntimeError("The Ridge worker remained busy after finishing.")


def _assert_mode(
    window: MainWindow,
    expected_mode: RidgeExtractionMode,
) -> None:
    automatic = expected_mode is RidgeExtractionMode.AUTOMATIC
    expected_button = (
        window.automatic_mode_radio if automatic else window.guided_mode_radio
    )
    expected_id = (
        _AUTOMATIC_MODE_BUTTON_ID if automatic else _GUIDED_MODE_BUTTON_ID
    )
    if window.ridge_extraction_mode is not expected_mode:
        raise AssertionError("The session extraction mode does not match the click.")
    if window.automatic_mode_radio.isChecked() is not automatic:
        raise AssertionError("Automatic radio checked state does not match the click.")
    if window.guided_mode_radio.isChecked() is automatic:
        raise AssertionError("Guided radio checked state does not match the click.")
    if window.ridge_mode_button_group.checkedId() != expected_id:
        raise AssertionError("QButtonGroup checked ID does not match the click.")
    if window.ridge_mode_button_group.checkedButton() is not expected_button:
        raise AssertionError("QButtonGroup checked button does not match the click.")


def _capture(window: MainWindow, filename: str) -> dict[str, int | str]:
    image = window.grab()
    path = OUTPUT_DIRECTORY / filename
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save native GUI screenshot: {path}")
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "width_px": image.width(),
        "height_px": image.height(),
    }


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source_hash_before = _sha256(SOURCE_PATH)
    configuration = load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    input_configuration = configuration.input
    loaded = DataImportController().load(
        SignalLoadRequest(
            path=SOURCE_PATH,
            time_column=input_configuration.time_column,
            channels=tuple(
                ChannelImportSpec(
                    channel_name,
                    column_index,
                    input_configuration.voltage_scales[channel_name],
                )
                for channel_name, column_index in (
                    input_configuration.voltage_columns.items()
                )
            ),
            delimiter=input_configuration.delimiter,
            has_header=input_configuration.has_header,
            encoding=input_configuration.encoding,
            time_scale=input_configuration.time_scale,
        )
    )
    application = create_application(sys.argv, language_code="zh_CN")
    if application.platformName() != "windows":
        raise RuntimeError("TASK-016R2-R requires native Windows Qt evidence.")
    settings = QSettings(
        str(OUTPUT_DIRECTORY / "extraction_mode_smoke.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    window = MainWindow(translation_manager=translation_manager(), settings=settings)
    screenshots: list[dict[str, int | str]] = []
    mode_trail: list[str] = []
    try:
        window.resize(1440, 900)
        window.show()
        window.set_loaded_result(loaded)
        window.set_analysis_configuration(configuration)
        window.analysis_range_panel.use_full_range()
        application.processEvents()
        _wait(window, window.run_stft_analysis, AnalysisResultSource.SPECTROGRAM)
        window.select_workflow_step(3)

        window.automatic_mode_radio.click()
        application.processEvents()
        _assert_mode(window, RidgeExtractionMode.AUTOMATIC)
        mode_trail.append("automatic")
        screenshots.append(_capture(window, "extraction_mode_automatic.png"))
        _wait(
            window,
            window.run_staged_automatic_analysis,
            AnalysisResultSource.AUTOMATIC,
        )

        stft = window.analysis_session.stft_results["pdv_channel_1"]
        window._ridge_constraint_changed(
            "pdv_channel_1",
            RidgeCorridorConstraint(
                control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
                control_frequencies_hz=np.asarray([0.63e9, 0.63e9]),
                half_width_hz=70.0e6,
            ),
        )
        window.guided_mode_radio.click()
        application.processEvents()
        _assert_mode(window, RidgeExtractionMode.GUIDED)
        mode_trail.append("guided")
        screenshots.append(_capture(window, "extraction_mode_guided.png"))
        _wait(window, window.run_guided_analysis, AnalysisResultSource.GUIDED)

        window.automatic_mode_radio.click()
        application.processEvents()
        _assert_mode(window, RidgeExtractionMode.AUTOMATIC)
        mode_trail.append("automatic")
        window.guided_mode_radio.click()
        application.processEvents()
        _assert_mode(window, RidgeExtractionMode.GUIDED)
        mode_trail.append("guided")
    finally:
        window.close()
        application.processEvents()

    source_hash_after = _sha256(SOURCE_PATH)
    if source_hash_before != source_hash_after:
        raise AssertionError("The raw source CSV changed during extraction-mode smoke.")
    summary = {
        "task": "TASK-016R2-R",
        "qt_platform": application.platformName(),
        "source": SOURCE_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "mode_trail": mode_trail,
        "screenshots": screenshots,
    }
    summary_path = OUTPUT_DIRECTORY / "extraction_mode_smoke_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
