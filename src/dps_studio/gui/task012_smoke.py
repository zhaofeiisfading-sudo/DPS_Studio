"""Visible, output-verifying desktop acceptance used by source and frozen builds."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QPoint, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio.core.export import ExportTimeOrigin
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics import WindowMaterial
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.core.segmentation import validate_plan
from dps_studio.gui.research_window import ResearchMainWindow


def wait_idle(window: ResearchMainWindow) -> None:
    deadline = time.monotonic() + 900
    while (window._analysis_adapter.busy or window.segment_workspace.busy) and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.02)  # Let the Python analysis worker acquire the GIL.
    assert not window._analysis_adapter.busy and not window.segment_workspace.busy, "worker timeout"
    QApplication.processEvents()


def exercise(window: ResearchMainWindow, source: Path, destination: Path) -> dict[str, Any]:
    def capture(name: str) -> None:
        QApplication.processEvents()
        QTest.qWait(80)
        assert window.grab().save(str(destination / f"{name}.png"))

    before = hashlib.sha256(source.read_bytes()).hexdigest()
    columns = np.loadtxt(source, delimiter=",", ndmin=2, max_rows=1).shape[1]
    loaded = read_delimited_signals(source, time_column=0,
        voltage_columns={f"pdv_channel_{i}": i for i in range(1, columns)})
    window.set_loaded_result(loaded)
    window.analysis_range_panel.use_full_range()
    assert window.run_stft_analysis()
    wait_idle(window)
    assert window.analysis_session.stft_valid
    assert window.run_automatic_analysis()
    wait_idle(window)
    assert window.analysis_session.automatic_results_available
    window.select_workflow_step(2)
    capture("01_classic_velocity")
    velocity = window.velocity_view
    velocity.fit_result_range()
    bounds = np.asarray(velocity.plot_widget.viewRange())
    QTest.mouseClick(window.analysis_range_panel.automatic_event_time_radio, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert window.science_tabs.currentWidget() is velocity
    np.testing.assert_allclose(velocity.plot_widget.viewRange(), bounds)
    assert window.run_event_candidate_detection()
    wait_idle(window)
    assert window.science_tabs.currentWidget() is velocity
    np.testing.assert_allclose(velocity.plot_widget.viewRange(), bounds)
    assert velocity.view_mode == "result"
    for i in range(velocity.channel_combo.count()):
        velocity.channel_combo.setCurrentIndex(i)
        assert velocity.channel_combo.currentData() in loaded.records
        assert velocity.channel_combo.currentText() == f"候选{i + 1}"
    velocity.quantity_combo.setCurrentIndex(1)
    assert velocity.acceleration_curve is not None
    capture("02_acceleration")
    velocity.quantity_combo.setCurrentIndex(0)
    first = next(iter(loaded.records))
    apparent = window.analysis_session.channel_analyses[first].apparent_velocity_m_s.copy()
    window.measurement_angle_spin.setValue(12.)
    window.window_material_combo.setCurrentIndex(window.window_material_combo.findData("none"))
    current = window.analysis_session.channel_analyses[first]
    np.testing.assert_array_equal(current.apparent_velocity_m_s, apparent)
    # Check the existing correction implementation via its independent array relation.
    mask = np.isfinite(current.corrected_velocity_m_s)
    np.testing.assert_allclose(current.corrected_velocity_m_s[mask], apparent[mask] / np.cos(np.deg2rad(12.)))
    window.window_material_combo.setCurrentIndex(window.window_material_combo.findData(WindowMaterial.LIF.value))
    assert window.analysis_session.channel_analyses[first].velocity_correction_result.config.window_correction_enabled
    window.analysis_session.set_export_time_origin(ExportTimeOrigin.ABSOLUTE)
    window._sync_export_time_origin_controls()
    (destination / "classic_export").mkdir()
    window._set_export_output_directory(destination / "classic_export")
    window.export_acceleration_check.setChecked(True)

    def acknowledge_export() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox):
                widget.accept()

    QTimer.singleShot(150, acknowledge_export)
    assert window._export_current_result()
    classic_paths = sorted((destination / "classic_export").rglob("*.csv"))
    assert classic_paths and list((destination / "classic_export").rglob("*.json"))
    window.select_workflow_step(2)
    window.mode_combo.setCurrentIndex(1)
    s = window.segment_workspace
    start, end = s.plan[0].start_s, s.plan[-1].end_s
    for fraction in (.25, .5, .75):
        assert s.add_boundary(start + (end - start) * fraction)
    for row, stage in enumerate(("stationary", "onset", "acceleration", "decline")):
        s.set_segment(row, stage=stage)
    assert s.plan[2].algorithm == "dechirp"
    s.set_segment(3, algorithm="varpro")
    s.set_segment(3, stage="rebound")
    assert s.plan[3].algorithm == "stft"
    s.set_segment(3, algorithm="varpro")
    assert s.plan[3].algorithm == "varpro"
    for index, key in enumerate(("raw", "stft", "classic", "result")):
        s.views.setCurrentIndex(index)
        if key == "classic":
            reference_x = s.reference_velocity.display_curve.getData()[0]  # type: ignore[union-attr]
            np.testing.assert_array_equal(reference_x,
                window.analysis_session.channel_analyses[str(s.channel_combo.currentData())].stft_result.time_s * 1e6)
        line = s._all_lines[key][0]
        value = start + (end - start) * (.24 + .001 * index)
        line.setValue(value * 1e6)
        line.sigPositionChangeFinished.emit(line)
        np.testing.assert_allclose(s.plan[0].end_s, value, rtol=1e-14, atol=1e-18)
        validate_plan(s.plan, start, end)
        capture(f"03_reference_{key}")
    s.views.setCurrentIndex(0)
    plan = s.plan
    s.delete_boundary()
    s.undo_edit()
    assert s.plan == plan
    s.save_plan(destination / "segments.json")
    s.load_plan(destination / "segments.json")
    for row, algorithm in enumerate(("low_glrt", "stft_short", "stft_long", "tone_refine")):
        s.set_segment(row, algorithm=algorithm)
    channel_reports = []
    for channel_index in range(s.channel_combo.count()):
        s.channel_combo.setCurrentIndex(channel_index)
        if channel_index:
            assert s.add_boundary(start + (end - start) * .5)
            s.set_segment(0, algorithm="stft_low")
            s.set_segment(1, stage="acceleration")
        channel = str(s.channel_combo.currentData())
        assert s.run_analysis()
        assert not window.mode_combo.isEnabled()
        assert not window.run_stft_analysis()
        wait_idle(window)
        assert channel in s.results, s.status.text()
        result = s.results[channel]
        assert not any(part["error"] for part in result.metadata["algorithms"])
        assert np.all(np.diff(result.time_s) > 0)
        channel_reports.append({"identity": channel, "frames": len(result.time_s),
            "valid": int(result.valid.sum()), "algorithms": sorted(set(result.algorithm_ids)),
            "truth": "UNAVAILABLE"})
    capture("04_segmented_result")
    previous_time_range = np.asarray(s.result_plot.viewRange()[0])
    s.field_combo.setCurrentIndex(2)
    np.testing.assert_allclose(s.result_plot.viewRange()[0], previous_time_range)
    active_result = s.results[str(s.channel_combo.currentData())]
    frequency = active_result.frequency_hz[np.isfinite(active_result.frequency_hz)] * 1e-9
    if frequency.size:
        y_bounds = s.result_plot.viewRange()[1]
        assert y_bounds[0] <= float(np.median(frequency)) <= y_bounds[1]
    capture("04b_segmented_frequency")
    s.field_combo.setCurrentIndex(0)
    paths = s.export_to(destination / "segmented_export")
    for csv_path in (path for path in paths if path.suffix == ".csv"):
        meta = json.loads(csv_path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        result = s.results[meta["channel"]]
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        np.testing.assert_array_equal([float(row["absolute_time_s"]) for row in rows], result.time_s)
        np.testing.assert_array_equal([float(row["frequency_hz"]) for row in rows], result.frequency_hz)
        np.testing.assert_array_equal([float(row["corrected_velocity_m_s"]) for row in rows], result.corrected_velocity_m_s)
        assert meta["source_sha256"] == before
    layout_reports = []
    for width, height in ((1024, 640), (1280, 800), (1600, 1000)):
        window.resize(width, height)
        QApplication.processEvents()
        capture(f"05_manual_{width}x{height}")
        active_plot = s._plots()[list(s._plots())[s.views.currentIndex()]]
        assert active_plot.width() >= 550
        assert active_plot.width() <= s.width()
        assert window.properties_stack.width() >= 280
        assert window.diagnostics_dock.height() < window.height() * .25
        button_top = s.run_button.mapTo(window, QPoint(0, 0))
        assert 0 <= button_top.y() < window.height() - s.run_button.height()
        assert 0 <= button_top.x() <= window.width() - s.run_button.width()
        layout_reports.append({"requested": [width, height], "actual": [window.width(), window.height()],
            "plot": [active_plot.width(), active_plot.height()],
            "sidebar": window.properties_stack.width(), "diagnostics": window.diagnostics_dock.height()})
    for _ in range(5):
        window.mode_combo.setCurrentIndex(0)
        QApplication.processEvents()
        assert window.science_tabs.currentWidget() is velocity
        window.mode_combo.setCurrentIndex(1)
        assert s.plan
    old_ids = tuple(s.results)
    s.move_boundary(0, start + (end - start) * .3)
    assert str(s.channel_combo.currentData()) not in s.results
    assert len(s.results) == len(old_ids) - 1
    window.mode_combo.setCurrentIndex(0)
    assert window.run_stft_analysis()
    wait_idle(window)
    assert window.analysis_session.stft_valid
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    import dps_studio.gui.research_window as research
    import dps_studio.core.segmentation as segmentation
    import dps_studio.algorithms.waveform.common as algorithms

    return {"passed": True, "frozen": bool(getattr(sys, "frozen", False)),
        "source": str(source), "source_sha256": before, "raw_unchanged": True,
        "qt_platform": QApplication.platformName(), "window_visible": window.isVisible(),
        "device_pixel_ratio": window.devicePixelRatioF(), "channels": channel_reports,
        "layouts": layout_reports, "mode_roundtrips": 5, "candidate_view_preserved": True,
        "gate_views": 4, "export_roundtrip": True, "physical_corrections": True,
        "classic_after_manual": True, "module_paths": {
            "gui": research.__file__, "segmentation": segmentation.__file__,
            "algorithms": algorithms.__file__}}


def run_smoke(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task012-smoke", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--hold", action="store_true", help="Keep the isolated acceptance window open for native input checks")
    args = parser.parse_args(arguments[1:])
    destination = args.task012_smoke.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    from dps_studio.gui.app import create_application

    app = create_application(arguments)
    window = ResearchMainWindow(
        settings=QSettings(str(destination / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(destination / "presets.json"))
    window.resize(1400, 900)
    window.show()

    def run() -> None:
        code = 0
        try:
            report = exercise(window, args.input.resolve(), destination)
        except Exception:
            code = 1
            report = {"passed": False, "traceback": traceback.format_exc(),
                      "frozen": bool(getattr(sys, "frozen", False))}
            window.grab().save(str(destination / "failure.png"))
        (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.hold or code:
            window.close()
            app.exit(code)

    QTimer.singleShot(500, run)
    return app.exec()
