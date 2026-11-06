"""Repeatable visible-window acceptance, also runnable inside the frozen EXE."""
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
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.research_window import ResearchMainWindow


def _wait(predicate: Any, *, seconds: float = 900) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(15)
    if not predicate():
        raise TimeoutError("GUI worker did not finish before the acceptance deadline")
    QApplication.processEvents()


def exercise(window: ResearchMainWindow, source: Path, destination: Path) -> dict[str, Any]:
    with source.open("rb") as handle:
        before = hashlib.file_digest(handle, "sha256").hexdigest()
    columns = np.loadtxt(source, delimiter=",", ndmin=2, max_rows=1).shape[1]
    loaded = read_delimited_signals(source, time_column=0,
        voltage_columns={f"ch{index}": index for index in range(1, columns)})
    window.set_loaded_result(loaded)
    window.analysis_range_panel.use_full_range()
    QApplication.processEvents()
    assert window.run_automatic_analysis()
    _wait(lambda: not window._analysis_adapter.busy)
    assert window.analysis_session.automatic_results_available
    window.select_workflow_step(2)
    QApplication.processEvents()
    assert window.grab().save(str(destination / "01_classic_stft.png"))
    classic = {name: {"frames": len(analysis.stft_result.time_s),
                     "formal_valid": int(np.isfinite(analysis.refined_velocity_m_s).sum())}
               for name, analysis in window.analysis_session.channel_analyses.items()}
    window.mode_combo.setCurrentIndex(1)
    workspace = window.segment_workspace
    assert workspace.plan
    roi_start, roi_end = workspace.plan[0].start_s, workspace.plan[-1].end_s
    span = roi_end - roi_start
    for fraction in (.25, .5, .75):
        assert workspace.add_boundary(roi_start + span * fraction)
    # Exercise the actual button, numeric editor, table combos and queued worker.
    value = workspace.boundary_spin.value()
    workspace.boundary_spin.setValue(value + .0001)
    workspace.boundary_spin.setValue(value)
    for row, (stage, algorithm) in enumerate((("stationary", "stft"), ("onset", "dechirp"),
            ("acceleration", "varpro"), ("plateau", "clutter_varpro"))):
        stage_combo = workspace.table.cellWidget(row, 3)
        assert isinstance(stage_combo, QComboBox)
        stage_combo.setCurrentIndex(stage_combo.findData(stage))
        algorithm_combo = workspace.table.cellWidget(row, 4)
        assert isinstance(algorithm_combo, QComboBox)
        algorithm_combo.setCurrentIndex(algorithm_combo.findData(algorithm))
    QApplication.processEvents()
    assert window.grab().save(str(destination / "02_manual_gates.png"))
    QTest.mouseClick(workspace.run_button, Qt.MouseButton.LeftButton)
    _wait(lambda: not workspace.busy)
    channel = workspace.channel_combo.currentText()
    assert channel in workspace.results, workspace.status.text()
    result = workspace.results[channel]
    assert {"stft", "dechirp", "varpro", "clutter_varpro"} == set(result.algorithm_ids)
    assert all(row["error"] is None for row in result.metadata["algorithms"])
    assert window.grab().save(str(destination / "03_segmented_velocity.png"))
    workspace.field_combo.setCurrentIndex(2)
    workspace.candidate_check.setChecked(True)
    QApplication.processEvents()
    assert window.grab().save(str(destination / "04_segmented_frequency.png"))
    paths = workspace.export_to(destination / "exports")
    with paths[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    np.testing.assert_array_equal(np.array([float(row["absolute_time_s"]) for row in rows]), result.time_s)
    np.testing.assert_array_equal(np.array([float(row["corrected_velocity_m_s"]) for row in rows]),
                                  result.corrected_velocity_m_s)
    plan_path = destination / "segments.json"
    workspace.save_plan(plan_path)
    original = workspace.plan
    workspace.delete_boundary()
    assert channel not in workspace.results
    workspace.load_plan(plan_path)
    assert workspace.plan == original
    # Change the visible raw time ROI. This must update shared state, clip the
    # plan and stale old results, while algorithms retain the whole raw record.
    workspace.roi_button.setChecked(True)
    inner_start, inner_end = roi_start + .05 * span, roi_end - .05 * span
    workspace.raw_view.analysis_region.setRegion((inner_start * 1e6, inner_end * 1e6))
    workspace.raw_view.analysis_region.sigRegionChangeFinished.emit(workspace.raw_view.analysis_region)
    assert abs(workspace.plan[0].start_s - inner_start) < 1e-15
    assert abs(workspace.plan[-1].end_s - inner_end) < 1e-15
    assert not workspace.results
    workspace.roi_button.setChecked(False)
    # A second real queued run verifies editing does not retain stale curves.
    workspace.set_segment(0, algorithm="unobservable", stage="noise")
    assert workspace.run_analysis()
    _wait(lambda: not workspace.busy)
    assert channel in workspace.results
    updated = workspace.results[channel]
    assert all(row["error"] is None for row in updated.metadata["algorithms"])
    first = np.asarray(updated.segment_ids) == updated.segments[0].id
    assert np.isnan(updated.frequency_hz[first]).all()
    assert np.all((updated.time_s >= workspace.plan[0].start_s)
                  & (updated.time_s <= workspace.plan[-1].end_s))
    with source.open("rb") as handle:
        after = hashlib.file_digest(handle, "sha256").hexdigest()
    assert before == after
    modules = {name: str(module.__file__) for name, module in tuple(sys.modules.items())
               if name.startswith("dps_studio") and getattr(module, "__file__", None)}
    return {"passed": True, "source": str(source), "source_sha256": before,
            "raw_unchanged": before == after, "classic": classic,
            "segmented_frames": len(result.time_s), "segmented_valid": int(result.valid.sum()),
            "algorithm_errors": [row["error"] for row in result.metadata["algorithms"]],
            "edit_rerun_validated": True, "plan_roundtrip_validated": True,
            "roi_edit_and_invalidation_validated": True,
            "edited_roi_s": [workspace.plan[0].start_s, workspace.plan[-1].end_s],
            "export_roundtrip_validated": True, "qt_platform": QApplication.platformName(),
            "window_visible": window.isVisible(), "frozen": bool(getattr(sys, "frozen", False)),
            "executable": sys.executable, "settings_path": window._settings.fileName(),
            "module_paths": modules}


def run_smoke(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task011-smoke", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parsed, _ = parser.parse_known_args(arguments[1:])
    destination = parsed.task011_smoke.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    from dps_studio.gui.app import create_application, translation_manager

    app = create_application([], language_code="zh_CN")
    window = ResearchMainWindow(
        translation_manager=translation_manager(),
        settings=QSettings(str(destination / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(destination / "window_presets.json"))
    window.resize(1600, 1000)
    window.show()

    def run() -> None:
        exit_code = 0
        try:
            report = exercise(window, parsed.input.resolve(), destination)
        except Exception as exc:
            report = {"passed": False, "error": f"{type(exc).__name__}: {exc}",
                      "traceback": traceback.format_exc()}
            window.grab().save(str(destination / "failure.png"))
            exit_code = 1
        with (destination / "report.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        window.close()
        app.exit(exit_code)

    QTimer.singleShot(500, run)
    return app.exec()
