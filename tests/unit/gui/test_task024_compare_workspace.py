"""Real signal and real Qt event-loop coverage for the fourth Research workspace."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic, perf_counter, sleep

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.stft_m4 import DiffCategory
from dps_studio.gui.comparison import ComparisonWorkspace
from dps_studio.gui.research_window import ResearchMainWindow

ROOT = Path(__file__).resolve().parents[3]


def _wait(qapp: QApplication, workspace: ComparisonWorkspace, timeout: float = 120.) -> None:
    deadline = monotonic()+timeout
    while workspace.busy and monotonic() < deadline:
        qapp.processEvents()
        sleep(.005)
    assert not workspace.busy, workspace.state_text


def _load(name: str) -> None:
    assert (ROOT / "data/raw" / name).is_file()


def test_real_comparison_workspace(qapp: QApplication) -> None:
    name = "20260630-1.csv"
    _load(name)
    window = ResearchMainWindow()
    window.resize(1366, 768)
    window.show()
    qapp.processEvents()
    assert [window.mode_combo.itemData(i) for i in range(4)] == [
        "classic", "segmented", "diagnostic", "stft_m4_compare",
    ]
    dock_visible = window.diagnostics_dock.isVisible()
    window.mode_combo.setCurrentIndex(3)
    workspace = window.comparison_workspace
    properties = workspace.properties
    assert (properties.fmin_spin.decimals(), properties.fmax_spin.decimals()) == (1, 1)
    assert properties.wavelength_nm.decimals() == 3
    assert window.mode_stack.currentWidget() is workspace
    assert window.properties_stack.currentWidget() is properties
    assert not window.diagnostics_dock.isVisible() and not window.navigation_panel.isVisible()
    window.set_loaded_result(read_delimited_signals(ROOT / "data/raw" / name,
                                                    time_column=0, voltage_columns={"ch1": 1, "ch2": 2}))
    assert workspace.channel_combo.count() == 2
    progress: list[int] = []
    workspace.stateChanged.connect(lambda _value: progress.append(properties.progress_bar.value()))
    properties.matched_checkbox.setChecked(True)
    properties.compute_button.click()
    assert workspace.busy and not window.mode_combo.isEnabled()
    assert not window.action_open_data.isEnabled() and not properties.channel_combo.isEnabled()
    window.mode_combo.setCurrentIndex(0)
    assert window.mode_combo.currentIndex() == 3
    _wait(qapp, workspace)
    bundle = workspace.bundle
    assert bundle is not None and bundle.channel_name == "ch1" and bundle.matched_stft is not None
    assert progress == sorted(progress) and progress[-1] == 100 and len(set(progress)) >= 10
    assert "对比就绪" in window.status_state.text()
    published = properties.method_table.item(0, 2)
    assert published is not None and int(published.text()) == np.isfinite(bundle.m4.accepted_hz).sum()
    last_col = properties.method_table.horizontalHeader()
    assert last_col.length() <= properties.method_table.viewport().width()
    panel = properties.widget()
    assert panel is not None and panel.width() <= properties.viewport().width()
    plots = workspace.plots
    x, y = plots.left_plot.viewRange()
    assert y == [bundle.fmin_hz/1e9, bundle.fmax_hz/1e9]
    for plot in plots.linked_plots:
        assert plot.viewRange() == [x, y]
    np.testing.assert_array_equal(plots.left_image.image, plots.right_image.image)
    np.testing.assert_array_equal(plots.left_image.getLevels(), plots.right_image.getLevels())
    for index in (0, 1, 2, 0):
        workspace.layout_combo.setCurrentIndex(index)
        qapp.processEvents()
        assert plots.right_panel.isVisible() == (index != 2)
        if index != 2:
            assert plots.image_splitter.orientation() == (
                Qt.Orientation.Vertical if index == 1 else Qt.Orientation.Horizontal
            )
        for i, plot in enumerate(plots.linked_plots):
            x0 = 747.0 + i*.01
            limits = [[x0, x0+.1], [.1+i*.05, .9+i*.05]]
            plot.setRange(xRange=limits[0], yRange=limits[1], padding=0)
            qapp.processEvents()
            assert all(other.viewRange() == limits for other in plots.linked_plots)
    workspace.background_combo.setCurrentIndex(1)
    assert "独立量纲" in plots.right_title.text()
    workspace.background_combo.setCurrentIndex(0)
    for mode in ("b1", "m4", "overlay", "difference"):
        workspace.view_buttons[mode].click()
        assert workspace.view_buttons[mode].isChecked()
    for box in workspace.layer_boxes:
        assert box.isEnabled()
        box.setChecked(not box.isChecked())
        box.setChecked(not box.isChecked())
    assert workspace.layer_boxes[1].isChecked()
    workspace.region_combo.setCurrentIndex(workspace.region_combo.findData("m4_dropped_strong_risk"))
    assert workspace.selected_frame in workspace._frames()
    workspace.next_button.click()
    assert workspace.frame_counter.text().startswith("2 /")
    workspace.zoom_selected(30.)
    assert plots.left_plot.viewRange()[0][1]-plots.left_plot.viewRange()[0][0] == pytest.approx(.06)
    i = int(np.argmin(abs(bundle.frame_time_s-747.026015e-6)))
    time_us = bundle.frame_time_s[i]*1e6
    view = plots.left_plot.getViewBox()
    view.setRange(xRange=(time_us-.05, time_us+.05), yRange=(.1, .9), padding=0)
    qapp.processEvents()
    scene = view.mapViewToScene(QPointF(time_us, .5))
    target = plots.left_plot.mapFromScene(scene)
    QTest.mouseClick(plots.left_plot.viewport(), Qt.MouseButton.LeftButton, pos=target)
    qapp.processEvents()
    assert workspace.selected_frame == i
    inspected = workspace.inspector.current
    assert inspected is not None
    assert inspected.category is DiffCategory.M4_DROPPED_STRONG_RISK
    assert inspected.reason.value == "pre_edge_side_veto"
    assert "前侧" in workspace.inspector.decision.text()
    inspector = workspace.inspector
    assert "┄ M4 拟合" in inspector.waveform_legend.text()
    inspector.waveform_mode_combo.setCurrentIndex(1)
    assert "触轨退出" in inspector.waveform_legend.text()
    assert all(inspector.waveform.plot.getAxis(side).labelStyle["color"] == "#263746"
               for side in ("left", "bottom"))
    assert not workspace.unit_combo.model().flags(workspace.unit_combo.model().index(1, 0)) & (
        Qt.ItemFlag.ItemIsEnabled
    )
    properties.confirm_wavelength.setChecked(True)
    properties.wavelength_nm.setValue(1550.)
    old = plots.left_plot.viewRange()[1]
    workspace.unit_combo.setCurrentIndex(1)
    for plot in (plots.left_plot, plots.right_plot):
        assert plot.getAxis("left").label.toPlainText() == "表观速度 (m/s)"
    assert plots.curve_plot.getAxis("left").label.toPlainText() == "速度 (m/s)"
    np.testing.assert_allclose(plots.left_plot.viewRange()[1], np.array(old)*775.)
    properties.confirm_wavelength.setChecked(False)
    assert workspace.unit_combo.currentData() == "frequency"
    np.testing.assert_allclose(plots.left_plot.viewRange()[1], old)
    window.mode_combo.setCurrentIndex(2)
    assert not window.diagnostics_dock.isVisible()
    window.mode_combo.setCurrentIndex(0)
    assert window.diagnostics_dock.isVisible() == dock_visible
    assert window.navigation_panel.isVisible()
    window.close()


def test_cancel_and_portable_external_load(qapp: QApplication, tmp_path: Path) -> None:
    name = "20201211m.dat"
    _load(name)
    workspace = ComparisonWorkspace(tmp_path)
    workspace.show()
    assert not workspace.properties.preset_combo.isEnabled()
    external = tmp_path / name
    external.write_bytes((ROOT / "data/raw" / name).read_bytes())
    result = read_delimited_signals(external, time_column=0, voltage_columns={"external": 1})
    workspace.set_context(result.records, result.source_path)
    assert workspace.start()
    deadline = monotonic()+15
    while workspace.properties.progress_bar.value() < 24 and monotonic() < deadline:
        qapp.processEvents()
        sleep(.005)
    assert workspace.busy and workspace.properties.progress_bar.value() >= 24
    started = perf_counter()
    workspace.properties.cancel_button.click()
    _wait(qapp, workspace)
    assert perf_counter()-started < .25
    assert workspace.bundle is None and "已取消" in workspace.state_text
    assert workspace.properties.compute_button.isEnabled()
    assert workspace.start()
    _wait(qapp, workspace)
    bundle = workspace.bundle
    assert bundle is not None and bundle.source_path == external
    workspace.dispose()
    workspace.close()
    workspace.deleteLater()


def test_compare_capture_cli(tmp_path: Path) -> None:
    source = ROOT / "data/raw/20201211m.dat"
    _load(source.name)
    spec = tmp_path / "capture.json"
    spec.write_text(json.dumps({
        "input": str(source), "channel": "20201211m_ch1",
        "report": "report.json",
        "captures": [
            {"screenshot": "display.png", "size": [1366, 768], "layout": "single",
             "frame_index": 10, "time_range_us": [107.5, 107.6],
             "display": "difference", "background": "shared"},
        ],
    }), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    process = subprocess.run(
        [sys.executable, "-B", "-m", "dps_studio.gui", "--compare-capture-spec", str(spec)],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False, timeout=90,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["event_loop_entered"] and report["mode"] == "stft_m4_compare"
    shot = report["captures"][0]
    assert shot["selected_frame"] == 10
    assert shot["window_visible"] and set(shot["frame_evidence"]) == {"b1", "m4"}
    assert shot["view_ranges"][0][0] == [107.5, 107.6]
    assert shot["left_levels_db"] == shot["right_levels_db"]
    assert shot["view_ranges"].count(shot["view_ranges"][0]) == 3
    assert (tmp_path / "display.png").read_bytes().startswith(b"\x89PNG")
