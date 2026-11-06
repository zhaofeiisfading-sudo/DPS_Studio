"""Real QWidget integration: editing, reruns, stale work and export."""
from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.analysis_session import AnalysisRange
from dps_studio.gui.research_window import ResearchMainWindow
from dps_studio.gui.segment_workspace import SegmentWorkspace


def wait_for(workspace: SegmentWorkspace, qapp: QApplication) -> None:
    deadline = monotonic() + 30
    while workspace.busy and monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert not workspace.busy


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> ResearchMainWindow:
    time = np.arange(4096) / 40e9
    rng = np.random.default_rng(110)
    y = .001 * rng.normal(size=len(time))
    y[512:] += .1 * np.cos(2 * np.pi * 600e6 * time[512:])
    path = tmp_path / "raw.csv"
    np.savetxt(path, np.column_stack((time, y, .8 * y)), delimiter=",")
    w = ResearchMainWindow(settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path / "presets.json"))
    w.set_loaded_result(read_delimited_signals(path, time_column=0, voltage_columns={"ch1": 1, "ch2": 2}))
    w.analysis_range_panel.use_full_range()
    w.show()
    w.mode_combo.setCurrentIndex(1)
    qapp.processEvents()
    return w


def test_edit_drag_numeric_delete_and_per_channel_plan(window: ResearchMainWindow, qapp: QApplication) -> None:
    workspace = window.segment_workspace
    assert "Research / Test" in window.windowTitle()
    assert window.mode_stack.currentWidget() is workspace
    assert window.properties_stack.currentWidget() is workspace.properties
    assert len(workspace.plan) == 1
    QTest.mouseClick(workspace.add_button, Qt.MouseButton.LeftButton)
    assert len(workspace.plan) == 2
    assert workspace.lines[0].movable
    workspace.lines[0].setValue(40e-3)
    workspace.lines[0].sigPositionChangeFinished.emit(workspace.lines[0])
    qapp.processEvents()
    assert workspace.plan[0].end_s == pytest.approx(40e-9)
    workspace.boundary_spin.setValue(45e-3)
    assert workspace.plan[0].end_s == pytest.approx(45e-9)
    workspace.set_segment(1, stage="acceleration", algorithm="dechirp")
    workspace.channel_combo.setCurrentText("ch2")
    assert len(workspace.plan) == 1
    workspace.channel_combo.setCurrentText("ch1")
    assert workspace.plan[1].algorithm == "dechirp"
    workspace.delete_boundary()
    assert len(workspace.plan) == 1 and workspace.plan[0].algorithm == "stft"


def test_background_result_export_edit_invalidation_and_rerun(
        window: ResearchMainWindow, qapp: QApplication, tmp_path: Path) -> None:
    workspace = window.segment_workspace
    workspace.add_boundary()
    workspace.set_segment(1, algorithm="varpro", stage="plateau")
    QTest.mouseClick(workspace.run_button, Qt.MouseButton.LeftButton)
    wait_for(workspace, qapp)
    assert "ch1" in workspace.results
    result = workspace.results["ch1"]
    assert {"stft", "varpro"} == set(result.algorithm_ids)
    assert result.valid.any()
    paths = workspace.export_to(tmp_path / "export")
    assert len(paths) == 2
    assert json.loads(paths[1].read_text(encoding="utf-8"))["mode"] == "research_test_segmented"
    workspace.move_boundary(0, 60e-9)
    assert not workspace.results and not workspace.export_button.isEnabled()
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    assert "ch1" in workspace.results
    window.mode_combo.setCurrentIndex(0)
    assert window.science_tabs.currentWidget() is window.raw_signal_view


def test_plan_save_load_and_changed_roi_validation(
        window: ResearchMainWindow, tmp_path: Path) -> None:
    workspace = window.segment_workspace
    workspace.add_boundary()
    workspace.set_segment(1, stage="noise", algorithm="unobservable")
    workspace.save_plan(tmp_path / "plan.json")
    before = workspace.plan
    workspace.delete_boundary()
    workspace.load_plan(tmp_path / "plan.json")
    assert workspace.plan == before
    with pytest.raises(FileExistsError):
        workspace.save_plan(tmp_path / "plan.json")
    window._analysis_range_confirmed(10e-9, 90e-9)
    with pytest.raises(ValueError, match="ROI"):
        workspace.load_plan(tmp_path / "plan.json")


def test_repeated_numeric_edits_keep_selected_boundary_and_neighbors(window: ResearchMainWindow) -> None:
    workspace = window.segment_workspace
    for value in (25e-9, 50e-9, 75e-9):
        assert workspace.add_boundary(value)
    assert workspace.boundary_combo.currentIndex() == 2
    workspace.boundary_spin.setValue(.076)
    workspace.boundary_spin.setValue(.074)
    assert workspace.boundary_combo.currentIndex() == 2
    assert workspace.plan[0].end_s == 25e-9
    assert workspace.plan[1].end_s == 50e-9
    assert workspace.plan[2].end_s == pytest.approx(74e-9)


def test_late_result_is_discarded_when_context_changes(window: ResearchMainWindow, qapp: QApplication) -> None:
    workspace = window.segment_workspace
    assert workspace.run_analysis()
    workspace.revision += 1
    wait_for(workspace, qapp)
    assert not workspace.results
    assert "丢弃" in workspace.status.text()


def test_physical_parameter_change_invalidates_segment_results(
        window: ResearchMainWindow, qapp: QApplication) -> None:
    workspace = window.segment_workspace
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    assert workspace.results
    window.measurement_angle_spin.setValue(25.)
    qapp.processEvents()
    assert not workspace.results


def test_worker_exception_keeps_window_alive_and_allows_retry(
        window: ResearchMainWindow, qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    from dps_studio.gui import segment_workspace
    from dps_studio.core.segmentation import analyze_segments

    original = analyze_segments

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected worker error")

    monkeypatch.setattr(segment_workspace, "analyze_segments", fail)
    workspace = window.segment_workspace
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    assert "injected worker error" in workspace.status.text()
    assert window.isVisible() and workspace.run_button.isEnabled()
    monkeypatch.setattr(segment_workspace, "analyze_segments", original)
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    assert workspace.results


def test_graphical_raw_roi_updates_shared_plan_and_invalidates_result(
        window: ResearchMainWindow, qapp: QApplication) -> None:
    workspace = window.segment_workspace
    workspace.add_boundary(50e-9)
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    assert workspace.results
    QTest.mouseClick(workspace.roi_button, Qt.MouseButton.LeftButton)
    assert workspace.raw_view.analysis_region.isVisible()
    workspace.raw_view.analysis_region.setRegion((.02, .08))
    workspace.raw_view.analysis_region.sigRegionChangeFinished.emit(workspace.raw_view.analysis_region)
    qapp.processEvents()
    assert window.analysis_session.analysis_range == AnalysisRange(20e-9, 80e-9)
    assert workspace.plan[0].start_s == pytest.approx(20e-9)
    assert workspace.plan[-1].end_s == pytest.approx(80e-9)
    assert len(workspace.plan) == 2 and not workspace.results
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    result = workspace.results["ch1"]
    assert np.all((result.time_s >= 20e-9) & (result.time_s <= 80e-9))
    assert len(window.analysis_session.records["ch1"].time_s) == 4096


def test_production_rectangle_time_and_frequency_are_inherited(
        window: ResearchMainWindow, qapp: QApplication) -> None:
    assert window.run_stft_analysis()
    deadline = monotonic() + 30
    while window._analysis_adapter.busy and monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert window.analysis_session.stft_valid
    stft = window.analysis_session.stft_results["ch1"]
    left, right = float(stft.time_s[3]), float(stft.time_s[-4])
    window.spectrogram_view.search_region_changed.emit(left, right, 300e6, 900e6)
    window.mode_combo.setCurrentIndex(1)
    workspace = window.segment_workspace
    assert workspace.plan[0].start_s == left
    assert workspace.plan[-1].end_s == right
    assert workspace._frequency_band_hz == (300e6, 900e6)
    assert workspace.run_analysis()
    wait_for(workspace, qapp)
    result = workspace.results["ch1"]
    assert result.metadata["workflow_options"]["minimum_frequency_hz"] == 300e6
    assert result.metadata["workflow_options"]["maximum_frequency_hz"] == 900e6
    assert np.all((result.time_s >= left) & (result.time_s <= right))
    assert np.all((result.frequency_hz[result.valid] >= 300e6)
                  & (result.frequency_hz[result.valid] <= 900e6))


def test_editing_does_not_reenable_analysis_after_shared_validation_fails(
        window: ResearchMainWindow) -> None:
    workspace = window.segment_workspace
    window._parameters_valid = False
    window._apply_state()
    assert workspace.add_boundary()
    assert not workspace.run_button.isEnabled()
    assert not workspace.run_analysis()
    assert "参数不可用" in workspace.status.text()
