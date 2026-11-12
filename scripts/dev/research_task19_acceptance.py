"""Compare the Production GUI against a frozen checkout on three raw records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QWidget

from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.core.workflow.acceleration import channel_acceleration
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import DataImportController
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def wait_for_idle(window: MainWindow) -> None:
    deadline = monotonic() + 120
    while window._analysis_adapter.busy or getattr(window, "_import_busy", False):
        if monotonic() > deadline:
            raise TimeoutError("Production GUI did not finish the requested operation.")
        loop = QEventLoop()
        QTimer.singleShot(60, loop.quit)
        loop.exec()
    QTest.qWait(70)


def fingerprint(value: Any) -> dict[str, Any]:
    array = np.asarray(value)
    finite = array[np.isfinite(array)]
    return {
        "shape": array.shape,
        "dtype": str(array.dtype),
        "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        "finite": int(finite.size),
    }


def capture(widget: QWidget, destination: Path) -> dict[str, Any]:
    """Capture a visible native window through the active platform's screen API."""
    widget.raise_()
    widget.activateWindow()
    QTest.qWait(280)
    handle = widget.windowHandle()
    assert handle is not None and handle.isExposed()
    screen = widget.screen()
    pixmap = screen.grabWindow(int(widget.winId()))
    assert not pixmap.isNull() and pixmap.save(str(destination))
    return {
        "logical_size": (widget.width(), widget.height()),
        "pixels": (pixmap.width(), pixmap.height()),
        "dpr": pixmap.devicePixelRatio(),
        "dpi": screen.logicalDotsPerInch(),
    }


def compare_baseline(baseline: Path, output: Path) -> None:
    """Compare byte fingerprints and all metadata except the export timestamp."""
    def read(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    assert read(baseline / "results.json") == read(output / "results.json")
    metadata = sorted(path.relative_to(baseline) for path in baseline.glob("*/*.metadata.json"))
    assert len(metadata) == 3
    assert metadata == sorted(path.relative_to(output) for path in output.glob("*/*.metadata.json"))
    for path in metadata:
        old, new = read(baseline / path), read(output / path)
        old.pop("exported_at_utc")
        new.pop("exported_at_utc")
        assert old == new, path
    (output / "parity.json").write_text(json.dumps({
        "baseline": str(baseline.resolve()),
        "array_and_csv_fingerprints_equal": True,
        "metadata_equal_except": ["exported_at_utc"],
        "metadata_files": [path.as_posix() for path in metadata],
    }, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Production checkout containing the original data")
    parser.add_argument("output", type=Path)
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--english", action="store_true")
    parser.add_argument("--baseline", type=Path, help="Assert parity with a prior run")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = create_application([], language_code="en" if args.english else "zh_CN")
    if args.desktop and app.platformName() != "windows":
        raise RuntimeError(f"Desktop capture requires windows, got {app.platformName()!r}.")
    screenshots: dict[str, Any] = {}
    results: dict[str, Any] = {}
    settings = QSettings(str(output / "layout.ini"), QSettings.Format.IniFormat)
    window = MainWindow(
        settings=settings, translation_manager=translation_manager(),
        window_preset_repository=WindowPresetRepository(output / "presets.json"),
    )
    window.show()
    QTest.qWait(120)
    notice = QMessageBox.information

    def shot(name: str, widget: QWidget = window) -> None:
        if args.desktop:
            screenshots[name] = capture(widget, output / f"{name}.png")

    try:
        shot("01_start")
        for index, (file, channel) in enumerate((
            ("20260607.csv", "pdv_channel_1"),
            ("20260630-1.csv", "pdv_channel_2"),
            ("20260701.csv", "pdv_channel_1"),
        )):
            source = args.root.resolve() / "data" / "raw" / file
            dialog = ImportSettingsDialog(source, window)
            dialog.show()
            QTest.qWait(50)
            assert dialog.validation_error() is None, dialog.validation_error()
            if index == 0:
                shot("02_import", dialog)
                if hasattr(window, "_start_import"):
                    dialog.channel_1_column.setValue(0)
                    dialog._validate_and_accept()
                    assert dialog.isVisible()
                    shot("02b_invalid_mapping", dialog)
                    dialog.channel_1_column.setValue(1)
            request = dialog.load_request()
            dialog.accept()
            if hasattr(window, "_start_import"):
                assert window._start_import(request)
                wait_for_idle(window)
                load = window.load_result
                assert load is not None and load.source_path == source
            else:
                load = DataImportController().load(request)
                window.set_loaded_result(load)
            assert window.select_workflow_step(0)
            if index == 0:
                shot("03_stft_parameters")
            window.compute_stft_button.click()
            wait_for_idle(window)
            assert window.analysis_session.stft_valid
            if index == 0:
                shot("04_spectrogram")
            assert window.confirm_search_region_and_continue()
            wait_for_idle(window)
            assert window.workflow_state is WorkflowState.RESULT_READY
            assert window.select_workflow_step(2)
            window.velocity_view.channel_combo.setCurrentIndex(
                window.velocity_view.channel_combo.findData(channel)
            )
            if index == 0:
                shot("05_velocity")
                window.diagnostics_dock.show()
                shot("05b_diagnostics")
                window.diagnostics_dock.hide()
            session = window.analysis_session
            analysis = session.channel_analyses[channel]
            stft = analysis.stft_result
            np.testing.assert_array_equal(stft.time_s, session.stft_results[channel].time_s)
            report: dict[str, Any] = {
                "rows": load.row_count, "columns": load.column_count,
                "channel": channel, "mapped_channels": load.channel_names,
                "sample_rate_hz": stft.sample_rate_hz,
                "window": [stft.window_name, stft.window_length_samples, stft.overlap_samples,
                           stft.hop_samples, stft.nfft],
                "time_s": fingerprint(stft.time_s),
                "frequency_hz": fingerprint(stft.frequency_hz),
                "stft_spectrum": fingerprint(stft.spectrum),
                "apparent_m_s": fingerprint(analysis.apparent_velocity_m_s),
                "working_m_s": fingerprint(analysis.plot_velocity_m_s),
                "signal_state_counts": {
                    str(state): analysis.signal_detection_result.signal_states.count(state)
                    for state in set(analysis.signal_detection_result.signal_states)
                },
            }
            velocity: Any = window.velocity_view  # Historical and current source both supported.
            window.measurement_angle_spin.setValue(15)
            for material, coefficient in (("none", None), ("LiF", None), ("LiF", 0.82)):
                window.window_material_combo.setCurrentIndex(
                    window.window_material_combo.findData(material)
                )
                if coefficient is not None:
                    window.lif_b1_spin.setValue(coefficient)
                analysis = session.channel_analyses[channel]
                name = "custom" if coefficient else material
                report[name] = {
                    "corrected_m_s": fingerprint(analysis.corrected_velocity_m_s),
                    "working_m_s": fingerprint(analysis.plot_velocity_m_s),
                    "raw_acceleration": fingerprint(channel_acceleration(analysis).acceleration_m_s2),
                    "fit_acceleration": fingerprint(
                        channel_acceleration(analysis, window_s=50e-9).acceleration_m_s2
                    ),
                }
            if index == 0:
                window.lif_parameter_toggle.setChecked(True)
                shot("06_correction")
                window.lif_parameter_toggle.setChecked(False)
            acceleration: Any = getattr(window, "acceleration_view", None)
            if acceleration is None:
                velocity.quantity_combo.setCurrentIndex(1)
                acceleration = velocity
            else:
                window.science_tabs.setCurrentWidget(acceleration)
                acceleration.select_result_target("automatic", channel)
            acceleration.fit_result_range()
            if index == 0:
                shot("07_acceleration")
            x, y = acceleration.acceleration_curve.getData()
            np.testing.assert_array_equal(x, stft.time_s * 1e6)
            np.testing.assert_array_equal(
                y, channel_acceleration(analysis).acceleration_m_s2 * 1e-9,
            )
            assert window.select_workflow_step(3)
            window.export_channel_combo.setCurrentIndex(window.export_channel_combo.findData(channel))
            window.export_acceleration_check.setChecked(True)
            window.export_acceleration_fit_check.setChecked(True)
            destination = output / source.stem
            destination.mkdir()
            window._set_export_output_directory(destination)
            if index == 0:
                shot("08_export")
                window.resize(1040, 665)
                shot("09_narrow")
                window.showMaximized()
                shot("10_maximized")
                window.showNormal()
            QMessageBox.information = staticmethod(  # type: ignore[assignment,method-assign]
                lambda *_args: QMessageBox.StandardButton.Ok,
            )
            assert window._export_current_result()
            for path in sorted(destination.glob("*.csv")):
                with path.open(encoding="utf-8") as handle:
                    header = handle.readline().strip()
                    rows = sum(1 for _ in handle)
                report[path.name] = {
                    "header": header, "rows": rows,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            results[file] = report
            window.measurement_angle_spin.setValue(0)
            window.lif_b1_spin.setValue(0.7895)
    finally:
        QMessageBox.information = notice  # type: ignore[method-assign]
        window.close()
    (output / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8",
    )
    (output / "desktop.json").write_text(
        json.dumps({"platform": app.platformName(), "shots": screenshots}, indent=2),
        encoding="utf-8",
    )
    if args.baseline is not None:
        compare_baseline(args.baseline, output)


if __name__ == "__main__":
    main()
