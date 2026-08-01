"""Render TASK-015A acceptance screenshots from the real Qt workstation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.core.workflow import load_workflow_config  # noqa: E402
from dps_studio.gui.app import create_application, translation_manager  # noqa: E402
from dps_studio.gui.main_window import MainWindow  # noqa: E402


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    output_root = Path(__file__).resolve().parent
    configuration = load_workflow_config(
        repository_root / "configs" / "demo_dual_profile.toml",
        repository_root=repository_root,
    )
    before_hash = hashlib.sha256(configuration.input.path.read_bytes()).hexdigest()
    loaded = read_delimited_signals(
        configuration.input.path,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    )

    application = create_application([], language_code="zh_CN")
    window = MainWindow(translation_manager=translation_manager())
    window.resize(1440, 900)
    window.set_loaded_result(loaded)
    window.set_analysis_configuration(configuration)
    window.analysis_range_panel.confirm_range_s(
        configuration.analysis.analysis_start_time_s,
        configuration.analysis.analysis_end_time_s,
    )
    window.wavelength_confirm_check.setChecked(True)
    window.show()
    application.processEvents()

    loop = QEventLoop()
    failed: list[str] = []
    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(
        lambda _generation, error_type, message, _traceback: (
            failed.append(f"{error_type}: {message}"),
            loop.quit(),
        )
    )
    if not window.run_automatic_analysis():
        raise RuntimeError(window.analysis_status_label.text())
    QTimer.singleShot(120_000, loop.quit)
    loop.exec()
    if failed:
        raise RuntimeError(failed[0])
    if not window.analysis_session.results_valid:
        raise RuntimeError("The real-data analysis did not produce current results.")

    captures = (
        ("main_window_native_icon_zh.png", 0, 0),
        ("real_spectrogram_zh.png", 1, 2),
        ("real_ridge_zh.png", 2, 3),
        ("real_velocity_zh.png", 3, 4),
        ("real_comparison_zh.png", 4, 5),
    )
    for filename, tab_index, workflow_row in captures:
        window.science_tabs.setCurrentIndex(tab_index)
        window.workflow_navigation.setCurrentRow(workflow_row)
        application.processEvents()
        destination = output_root / filename
        if not window.grab().save(str(destination), "PNG"):
            raise RuntimeError(f"Could not save {destination}.")

    after_hash = hashlib.sha256(configuration.input.path.read_bytes()).hexdigest()
    if before_hash != after_hash:
        raise RuntimeError("The raw source hash changed during GUI acceptance.")
    print(f"state={window.workflow_state.name}")
    print(f"channels={','.join(window.analysis_session.channel_analyses)}")
    print(f"source_sha256={after_hash.upper()}")
    for filename, _tab_index, _workflow_row in captures:
        print(output_root / filename)
    window.close()
    application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
