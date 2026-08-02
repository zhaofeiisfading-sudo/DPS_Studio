"""Render TASK-015B screenshots through the ordinary default-parameter flow."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QToolButton  # noqa: E402

from dps_studio.core import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE  # noqa: E402
from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.gui.app import create_application, translation_manager  # noqa: E402
from dps_studio.gui.main_window import MainWindow  # noqa: E402
from dps_studio.gui.preset_repository import CUSTOM_PRESET_ID  # noqa: E402
from dps_studio.gui.state import WorkflowState  # noqa: E402


def _save(window: MainWindow, path: Path) -> None:
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Could not save {path}.")


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    output_root = Path(__file__).resolve().parent
    source_path = repository_root / "data" / "raw" / "20260607.csv"
    before_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()

    application = create_application([], language_code="zh_CN")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow(translation_manager=translation_manager())
    window.resize(1440, 900)
    window.show()
    application.processEvents()

    if window.profile_combo.currentData() is not BALANCED_PROFILE:
        raise RuntimeError("Balanced was not selected at startup.")
    if window.vacuum_wavelength_spin.value() != 1550.0:
        raise RuntimeError("The startup wavelength was not 1550 nm.")
    if window.window_length_spin.value() != BALANCED_PROFILE.window_length_samples:
        raise RuntimeError("The displayed Balanced parameters are inconsistent.")
    _save(window, output_root / "default_parameters_zh.png")

    loaded = read_delimited_signals(
        source_path,
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
        encoding="utf-8",
        time_scale=1.0,
        voltage_scales={"pdv_channel_1": 1.0, "pdv_channel_2": 1.0},
    )
    window.set_loaded_result(loaded)
    window.workflow_navigation.setCurrentRow(2)
    application.processEvents()
    if window.workflow_state is not WorkflowState.RANGE_DEFINED:
        raise RuntimeError("Data import did not establish a default range.")
    if not window.action_automatic.isEnabled():
        raise RuntimeError(window.action_automatic.toolTip())
    _save(window, output_root / "wavelength_visible_zh.png")

    loop = QEventLoop()
    failed: list[str] = []
    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(
        lambda _generation, error_type, message, _traceback: (
            failed.append(f"{error_type}: {message}"),
            loop.quit(),
        )
    )
    toolbar_buttons = [
        button
        for button in window.main_toolbar.findChildren(QToolButton)
        if button.defaultAction() is window.action_automatic
    ]
    if len(toolbar_buttons) != 1:
        raise RuntimeError("Automatic analysis QAction is not on the toolbar once.")
    toolbar_buttons[0].click()
    QTimer.singleShot(120_000, loop.quit)
    loop.exec()
    if failed:
        raise RuntimeError(failed[0])
    if window.workflow_state is not WorkflowState.RESULT_READY:
        raise RuntimeError("Real-data automatic analysis did not reach RESULT_READY.")

    for tab_index in (1, 2, 3, 4):
        if not window.science_tabs.isTabEnabled(tab_index):
            raise RuntimeError(f"Result tab {tab_index} was not enabled.")
        window.science_tabs.setCurrentIndex(tab_index)
        application.processEvents()
    window.science_tabs.setCurrentIndex(1)
    window.workflow_navigation.setCurrentRow(2)
    application.processEvents()
    _save(window, output_root / "result_ready_without_manual_config_zh.png")

    high_index = window.profile_combo.findData(HIGH_TIME_RESOLUTION_PROFILE)
    window.profile_combo.setCurrentIndex(high_index)
    application.processEvents()
    if window.analysis_session.results_valid:
        raise RuntimeError("Switching to High time resolution kept stale results.")
    balanced_index = window.profile_combo.findData(BALANCED_PROFILE)
    window.profile_combo.setCurrentIndex(balanced_index)
    custom_index = window.profile_combo.findData(CUSTOM_PRESET_ID)
    window.profile_combo.setCurrentIndex(custom_index)
    window.nfft_spin.setValue(8192)
    application.processEvents()
    run_configuration = window.analysis_session.run_configuration
    if run_configuration is None or run_configuration.parameters.nfft != 8192:
        raise RuntimeError("Custom GUI parameters did not reach the run input.")
    _save(window, output_root / "custom_parameters_zh.png")

    after_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if before_hash != after_hash:
        raise RuntimeError("The raw source hash changed during GUI acceptance.")
    print(f"state_before_custom={WorkflowState.RESULT_READY.name}")
    print(f"channels={','.join(loaded.channel_names)}")
    print(f"source_sha256={after_hash.upper()}")
    print(f"custom_nfft={run_configuration.parameters.nfft}")
    for filename in (
        "default_parameters_zh.png",
        "wavelength_visible_zh.png",
        "custom_parameters_zh.png",
        "result_ready_without_manual_config_zh.png",
    ):
        print(output_root / filename)
    window.close()
    application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
