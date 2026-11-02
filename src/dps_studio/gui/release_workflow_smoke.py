"""Explicit, isolated GUI verification usable inside the frozen Windows EXE."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio import __version__
from dps_studio.core.physics.window_presets import WindowPresetRepository, is_builtin_window
from dps_studio.core.workflow.acceleration import channel_acceleration
from dps_studio.core.workflow.models import ChannelAnalysis
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.release_smoke import loaded_runtime_paths


def event_option_geometry(window: MainWindow) -> list[dict[str, Any]]:
    panel = window.analysis_range_panel
    return [
        {"text": radio.text(), "width": radio.width(), "required_width": radio.sizeHint().width(),
         "height": radio.height(), "required_height": radio.sizeHint().height()}
        for radio in (panel.unset_event_time_radio, panel.automatic_event_time_radio,
                      panel.manual_event_time_radio)
    ]


def audit_derivative(analysis: ChannelAnalysis) -> dict[str, Any]:
    """Independently evaluate secants and nonuniform central stencils in SI."""
    time = analysis.stft_result.time_s
    velocity = analysis.plot_velocity_m_s
    eligible = [
        np.isfinite(value) and state.value not in {"no_detectable_beat", "outside_analysis_window"}
        and source.value not in {"interpolated", "outside_analysis_window", "no_allowed_finite_bin"}
        and origin != "configured_pre_event_display_velocity_only"
        for value, state, source, origin in zip(velocity,
            analysis.signal_detection_result.signal_states, analysis.working_source,
            analysis.velocity_origins, strict=True)
    ]
    expected = np.full(time.shape, np.nan)
    for index in range(time.size):
        if not eligible[index]:
            continue
        left = index > 0 and eligible[index - 1]
        right = index + 1 < time.size and eligible[index + 1]
        if left and right:
            hl, hr = time[index] - time[index - 1], time[index + 1] - time[index]
            expected[index] = (
                hr / (hl + hr) * ((velocity[index] - velocity[index - 1]) / hl)
                + hl / (hl + hr) * ((velocity[index + 1] - velocity[index]) / hr)
            )
        elif left:
            expected[index] = (velocity[index] - velocity[index - 1]) / (time[index] - time[index - 1])
        elif right:
            expected[index] = (velocity[index + 1] - velocity[index]) / (time[index + 1] - time[index])
    actual = channel_acceleration(analysis).acceleration_m_s2
    np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-3, equal_nan=True)
    peak = int(np.nanargmax(np.abs(actual)))
    neighbors = list(range(max(0, peak - 1), min(time.size, peak + 2)))
    return {"rows": time.size, "finite_derivatives": int(np.isfinite(actual).sum()),
            "maximum_absolute_error_m_s2": float(np.nanmax(np.abs(actual - expected))),
            "peak_index": peak, "peak_m_s2": float(actual[peak]),
            "independent_peak_m_s2": float(expected[peak]),
            "neighbor_time_s": time[neighbors].tolist(),
            "neighbor_velocity_m_s": velocity[neighbors].tolist(),
            "neighbor_dt_s": np.diff(time[neighbors]).tolist(),
            "peak_signal_state": analysis.signal_detection_result.signal_states[peak].value,
            "physical_peak_validated": False}


def _dismiss_message() -> None:
    modal = QApplication.activeModalWidget()
    if isinstance(modal, QMessageBox):
        modal.accept()


def _exercise(window: MainWindow, source: Path, destination: Path) -> dict[str, Any]:
    from dps_studio.gui.data_controller import DataImportController
    from dps_studio.gui.import_dialog import ImportSettingsDialog

    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    dialog = ImportSettingsDialog(source)
    loaded = DataImportController().load(dialog.load_request())
    dialog.close()
    window.set_loaded_result(loaded)
    window.analysis_range_panel.use_full_range()
    loop = QEventLoop()
    failures: list[str] = []
    def failed(*args: object) -> None:
        failures.append(str(args))
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(30000)
    assert window.run_automatic_analysis()
    loop.exec()
    timer.stop()
    assert not failures and not window._analysis_adapter.busy, failures
    window.select_workflow_step(2)
    window.science_tabs.setCurrentWidget(window.velocity_view)
    QApplication.processEvents()
    assert window.grab().save(str(destination / "velocity.png"))
    view = window.velocity_view
    view.quantity_combo.setCurrentIndex(1)
    audits = {name: audit_derivative(analysis)
              for name, analysis in window.analysis_session.channel_analyses.items()}
    builtin_velocity = {name: analysis.plot_velocity_m_s.copy()
                        for name, analysis in window.analysis_session.channel_analyses.items()}
    window.lif_parameter_toggle.setChecked(True)
    window.lif_b1_spin.setValue(.8)
    editor = window.window_preset_editor
    assert not is_builtin_window(editor.model)
    editor.name_edit.setText("发布验证窗口")
    assert editor.save_current(), editor.status.text()
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("builtin"))
    assert window.lif_b1_spin.value() == .7895
    editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("user:发布验证窗口"))
    assert window.lif_b1_spin.value() == .8
    export_dir = destination / "exports"
    export_dir.mkdir()
    window.export_absolute_time_origin_radio.click()
    window.export_acceleration_check.setChecked(True)
    window._set_export_output_directory(export_dir)
    corrected_audits = {}
    for name, analysis in window.analysis_session.channel_analyses.items():
        assert not np.allclose(builtin_velocity[name], analysis.plot_velocity_m_s, equal_nan=True)
        view.channel_combo.setCurrentIndex(view.channel_combo.findData(name))
        actual = channel_acceleration(analysis).acceleration_m_s2
        assert view.acceleration_curve is not None
        plotted = np.asarray(view.acceleration_curve.getData()[1], dtype=np.float64)
        np.testing.assert_allclose(plotted, actual * 1e-9, equal_nan=True)
        assert view.plot_widget.getAxis("left").autoSIPrefixScale == 1.
        corrected_audits[name] = audit_derivative(analysis)
        window.export_channel_combo.setCurrentIndex(window.export_channel_combo.findData(name))
        QTimer.singleShot(100, _dismiss_message)
        assert window._export_current_result()
    metadata_paths = list(export_dir.glob("*.metadata.json"))
    assert len(metadata_paths) == len(corrected_audits)
    for metadata_path in metadata_paths:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        acceleration = metadata["acceleration_export"]
        assert acceleration["velocity_correction"]["window"]["configuration_name"] == "发布验证窗口"
        assert metadata["dps_studio_version"] == __version__
        with (export_dir / acceleration["csv_file"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert acceleration["units"] == {"time": "s", "velocity": "m/s", "acceleration": "m/s^2"}
        channel = metadata["source_channel"]
        analysis = window.analysis_session.channel_analyses[channel]
        np.testing.assert_allclose([float(row["acceleration_m_s2"]) for row in rows],
            channel_acceleration(analysis).acceleration_m_s2, equal_nan=True)
    window.select_workflow_step(2)
    window.velocity_parameter_scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    assert window.grab().save(str(destination / "acceleration.png"))
    window.velocity_parameter_scroll.ensureWidgetVisible(editor)
    QApplication.processEvents()
    assert window.grab().save(str(destination / "presets.png"))
    view.acceleration_method_combo.setCurrentIndex(1)
    view.acceleration_window_spin.setValue(50)
    fit_dir = destination / "fit_exports"
    fit_dir.mkdir()
    window._set_export_output_directory(fit_dir)
    window.export_acceleration_fit_check.setChecked(True)
    for name, analysis in window.analysis_session.channel_analyses.items():
        view.channel_combo.setCurrentIndex(view.channel_combo.findData(name))
        expected = channel_acceleration(analysis, window_s=view.local_fit_window_s).acceleration_m_s2
        assert view.acceleration_curve is not None
        plotted = np.asarray(view.acceleration_curve.getData()[1], dtype=np.float64)
        np.testing.assert_array_equal(plotted, expected * 1e-9)
        window.export_channel_combo.setCurrentIndex(window.export_channel_combo.findData(name))
        QTimer.singleShot(100, _dismiss_message)
        assert window._export_current_result()
    for metadata_path in fit_dir.glob("*.metadata.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        fit = metadata["acceleration_local_fit"]
        assert np.isclose(fit["window_s"], 50e-9, rtol=1e-12, atol=0)
        analysis = window.analysis_session.channel_analyses[metadata["source_channel"]]
        with (fit_dir / fit["csv_file"]).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for column, fit_window in (("acceleration_m_s2", None),
                                   ("local_linear_acceleration_m_s2", fit["window_s"])):
            np.testing.assert_allclose([float(row[column]) for row in rows],
                channel_acceleration(analysis, window_s=fit_window).acceleration_m_s2,
                equal_nan=True)
    window.select_workflow_step(2)
    window.velocity_parameter_scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    assert window.grab().save(str(destination / "local_fit.png"))
    for index in (0, 1, 2):
        window.science_tabs.setCurrentIndex(index)
        QApplication.processEvents()
        assert window.grab().save(str(destination / f"page_{index}.png"))
    window.science_tabs.setCurrentWidget(view)
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    return {"input_sha256": source_hash, "input_unchanged": True,
            "raw_samples": {key: record.time_s.size for key, record in loaded.records.items()},
            "builtin_derivative_audit": audits, "custom_derivative_audit": corrected_audits,
            "workflow_complete": True, "export_directory": str(export_dir),
            "local_fit_plot_and_export_match": True, "fit_window_s": 50e-9}


def run_workflow_smoke(arguments: list[str]) -> int:
    """Run only when explicitly requested; never use the real user's settings."""
    from dps_studio.gui.app import create_application, translation_manager

    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-smoke-test", type=Path, required=True)
    parser.add_argument("--workflow-input", type=Path)
    parser.add_argument("--workflow-restart", action="store_true")
    parser.add_argument("--workflow-layout-only", action="store_true")
    parser.add_argument("--workflow-language", default="zh_CN")
    parser.add_argument("--workflow-width", type=int, default=1366)
    parser.add_argument("--workflow-height", type=int, default=768)
    args = parser.parse_args(arguments[1:])
    report_path: Path = args.workflow_smoke_test
    destination = report_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    application = create_application([], language_code=args.workflow_language)
    application.setQuitOnLastWindowClosed(False)
    window = MainWindow(translation_manager=translation_manager(),
        settings=QSettings(str(destination / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(destination / "window_presets.json"))
    window.resize(args.workflow_width, args.workflow_height)
    window.show()

    def execute() -> None:
        report: dict[str, Any] = {}
        exit_code = 0
        try:
            if args.workflow_restart:
                editor = window.window_preset_editor
                editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("user:发布验证窗口"))
                assert editor.model.configuration_name == "发布验证窗口" and editor.model.b1 == .8
                report["restart_parameters_recovered"] = True
            elif not args.workflow_layout_only:
                if args.workflow_input is None:
                    raise ValueError("--workflow-input is required for a complete workflow")
                report.update(_exercise(window, args.workflow_input, destination))
            window.parameter_stack.setCurrentIndex(2)
            window.velocity_parameter_scroll.verticalScrollBar().setValue(0)
            QApplication.processEvents()
            geometry = event_option_geometry(window)
            assert all(row["width"] >= row["required_width"] and
                       row["height"] >= row["required_height"] for row in geometry), geometry
            assert window.grab().save(str(destination / (report_path.stem + ".png")))
            handle = window.windowHandle()
            report.update(status="PASS", version=__version__, gui_version=application.applicationVersion(),
                event_loop_entered=True, window_visible=window.isVisible(),
                window_exposed=handle is not None and handle.isExposed(),
                qt_platform=application.platformName(), event_option_geometry=geometry,
                language=args.workflow_language, device_pixel_ratio=window.devicePixelRatioF(),
                window_size=[window.width(), window.height()], executable=sys.executable,
                frozen=bool(getattr(sys, "frozen", False)), runtime_paths=loaded_runtime_paths(),
                settings_directory=str(destination))
        except Exception as exc:
            import traceback
            report.update(status="FAIL", error=str(exc), traceback=traceback.format_exc())
            exit_code = 1
        with report_path.open("x", encoding="utf-8") as report_file:
            json.dump(report, report_file, ensure_ascii=False, indent=2)
        window.close()
        application.exit(exit_code)

    QTimer.singleShot(500, execute)
    return application.exec()
