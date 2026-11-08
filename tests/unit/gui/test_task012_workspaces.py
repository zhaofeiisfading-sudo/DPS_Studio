"""Behavior regressions for mode isolation, range intent, gates and scientific outputs."""
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
from dps_studio.core.segmentation import validate_plan
from dps_studio.gui.research_window import ResearchMainWindow
from dps_studio.gui.segment_workspace import RECOMMENDATIONS, STAGE_LABELS


def wait_idle(window: ResearchMainWindow, qapp: QApplication) -> None:
    deadline = monotonic() + 45
    while (window._analysis_adapter.busy or window.segment_workspace.busy) and monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    assert not window._analysis_adapter.busy and not window.segment_workspace.busy
    qapp.processEvents()


@pytest.fixture
def workstation(qapp: QApplication, tmp_path: Path) -> ResearchMainWindow:
    time = np.arange(8192) / 40e9
    rng = np.random.default_rng(12012)
    volts = .001 * rng.normal(size=len(time))
    volts[1024:] += .1 * np.cos(2 * np.pi * (700e6 * time[1024:] + 1e15 * time[1024:] ** 2))
    source = tmp_path / "acquisition.csv"
    np.savetxt(source, np.column_stack((time, volts, volts * .8)), delimiter=",")
    window = ResearchMainWindow(
        settings=QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path / "presets.json"))
    window.set_loaded_result(read_delimited_signals(source, time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2}))
    window.analysis_range_panel.use_full_range()
    window.resize(1400, 900)
    window.show()
    qapp.processEvents()
    return window


def classic(window: ResearchMainWindow, qapp: QApplication) -> None:
    assert window.run_automatic_analysis()
    wait_idle(window, qapp)
    assert window.analysis_session.automatic_results_available
    assert window.select_workflow_step(2)


def test_mode_switch_preserves_classic_page_zoom_outputs_and_independent_sidebar(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    classic(w, qapp)
    before = w.analysis_session.channel_analyses["pdv_channel_1"].plot_velocity_m_s.copy()
    w.velocity_view.plot_widget.setRange(xRange=(.03, .12), yRange=(300, 900), padding=0)
    bounds = np.asarray(w.velocity_view.plot_widget.viewRange())
    for _ in range(8):
        w.mode_combo.setCurrentIndex(1)
        qapp.processEvents()
        assert w.mode_stack.currentWidget() is w.segment_workspace
        assert w.properties_stack.currentWidget() is w.segment_workspace.properties
        assert not w.navigation_panel.isVisible()
        assert all(w.science_tabs.tabText(i) != "人工分段" for i in range(w.science_tabs.count()))
        for index in range(4):
            w.segment_workspace.views.setCurrentIndex(index)
            qapp.processEvents()
            assert w.segmented_mode
        w.mode_combo.setCurrentIndex(0)
        qapp.processEvents()
        assert w.science_tabs.currentWidget() is w.velocity_view
        assert w.properties_stack.currentWidget() is w.parameter_panel
        assert w.run_analysis_button.isEnabled()
        np.testing.assert_allclose(w.velocity_view.plot_widget.viewRange(), bounds)
    np.testing.assert_array_equal(w.analysis_session.channel_analyses["pdv_channel_1"].plot_velocity_m_s, before)
    assert w.run_stft_analysis()
    wait_idle(w, qapp)
    assert w.analysis_session.stft_valid


def test_candidate_radio_and_detection_keep_page_zoom_and_formal_arrays(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    classic(w, qapp)
    before = w.analysis_session.channel_analyses["pdv_channel_1"].apparent_velocity_m_s.copy()
    w.velocity_view.plot_widget.setRange(xRange=(.04, .16), yRange=(100, 1100), padding=0)
    bounds = np.asarray(w.velocity_view.plot_widget.viewRange())
    QTest.mouseClick(w.analysis_range_panel.automatic_event_time_radio, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert w.science_tabs.currentWidget() is w.velocity_view
    assert w.workflow_navigation.currentRow() == 2
    np.testing.assert_allclose(w.velocity_view.plot_widget.viewRange(), bounds)
    assert w.run_event_candidate_detection()
    wait_idle(w, qapp)
    assert w.science_tabs.currentWidget() is w.velocity_view
    np.testing.assert_allclose(w.velocity_view.plot_widget.viewRange(), bounds)
    np.testing.assert_array_equal(w.analysis_session.channel_analyses["pdv_channel_1"].apparent_velocity_m_s, before)


@pytest.mark.parametrize("mode", ["analysis", "result", "custom"])
def test_range_intent_survives_correction_redraw_channel_and_reanalysis(
        workstation: ResearchMainWindow, qapp: QApplication, mode: str) -> None:
    w = workstation
    classic(w, qapp)
    view = w.velocity_view
    if mode == "result":
        QTest.mouseClick(view.fit_result_range_button, Qt.MouseButton.LeftButton)
    elif mode == "analysis":
        QTest.mouseClick(view.fit_analysis_range_button, Qt.MouseButton.LeftButton)
    else:
        view.plot_widget.setRange(xRange=(.05, .1), yRange=(400, 800), padding=0)
        view.plot_widget.plotItem.vb.sigRangeChangedManually.emit([True, True])
    bounds = np.asarray(view.plot_widget.viewRange())
    w.measurement_angle_spin.setValue(15.)
    qapp.processEvents()
    assert view.view_mode == mode
    np.testing.assert_allclose(view.plot_widget.viewRange(), bounds)
    view.channel_combo.setCurrentIndex(1)
    assert view.view_mode == mode
    if mode == "custom":
        np.testing.assert_allclose(view.plot_widget.viewRange(), bounds)
    assert w.run_automatic_analysis()
    wait_idle(w, qapp)
    assert view.view_mode == mode
    if mode == "custom":
        np.testing.assert_allclose(view.plot_widget.viewRange(), bounds)
    assert view.fit_result_range_button.isChecked() == (mode == "result")


def test_stage_recommendations_manual_override_survive_gates_channels_and_save(
        workstation: ResearchMainWindow, tmp_path: Path) -> None:
    w = workstation
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    for stage in STAGE_LABELS:
        s.set_segment(0, stage=stage)
        assert s.plan[0].algorithm == RECOMMENDATIONS.get(stage, "stft")
    s.set_segment(0, stage="acceleration")
    assert s.plan[0].algorithm == "dechirp"
    s.set_segment(0, algorithm="varpro")
    s.set_segment(0, stage="plateau")
    assert s.plan[0].algorithm == RECOMMENDATIONS.get("plateau", "stft")
    s.set_segment(0, algorithm="varpro")
    assert s.plan[0].algorithm == "varpro"
    assert "保留人工" in s.recommendation_label.text()
    assert s.add_boundary(100e-9)
    assert all(segment.algorithm == "varpro" for segment in s.plan)
    s.channel_combo.setCurrentIndex(1)
    assert len(s.plan) == 1 and s.plan[0].algorithm == "stft"
    s.channel_combo.setCurrentIndex(0)
    assert len(s.plan) == 2 and s.plan[1].algorithm == "varpro"
    path = tmp_path / "segments.json"
    s.save_plan(path)
    s.delete_boundary()
    assert len(s.plan) == 1
    s.undo_edit()
    assert len(s.plan) == 2 and s.plan[1].algorithm == "varpro"
    s.load_plan(path)
    s.interval_combo.setCurrentIndex(1)
    s.set_segment(1, stage="noise")
    assert s.plan[1].algorithm == "stft"
    s._adopt_recommendation()
    assert s.plan[1].algorithm == "stft"


def test_mirror_boundary_drag_clamps_and_keeps_ids_and_properties(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    s = workstation.segment_workspace
    workstation.mode_combo.setCurrentIndex(1)
    for value in (50e-9, 100e-9, 150e-9):
        assert s.add_boundary(value)
    s.set_segment(1, stage="acceleration")
    s.set_segment(2, stage="decline", algorithm="varpro")
    identities = [segment.id for segment in s.plan]
    for view_index, key in enumerate(("raw", "stft", "classic", "result")):
        s.views.setCurrentIndex(view_index)
        line = s._all_lines[key][1]
        line.setValue(.105 + view_index * .002)
        line.sigPositionChangeFinished.emit(line)
        qapp.processEvents()
        validate_plan(s.plan, s._roi.start_time_s, s._roi.end_time_s)
        assert [segment.id for segment in s.plan] == identities
        assert s.plan[1].algorithm == "dechirp" and s.plan[2].algorithm == "varpro"
        for lines in s._all_lines.values():
            assert lines[1].value() == pytest.approx(s.plan[1].end_s * 1e6)
    s.move_boundary(1, 1.)
    assert s.plan[1].end_s < s.plan[2].end_s
    validate_plan(s.plan, s._roi.start_time_s, s._roi.end_time_s)
    assert not s.add_boundary(s.plan[1].end_s)
    s.interval_combo.setCurrentIndex(2)
    s.start_spin.setValue(.115)
    assert s.plan[1].end_s == pytest.approx(115e-9)
    assert s.plan[2].start_s == s.plan[1].end_s


def test_async_segment_run_interlocks_classic_and_export_keeps_identity(
        workstation: ResearchMainWindow, qapp: QApplication, tmp_path: Path) -> None:
    w = workstation
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    s.add_boundary(100e-9)
    s.set_segment(1, stage="acceleration")
    assert s.run_analysis()
    assert not w.mode_combo.isEnabled()
    assert not w.run_stft_analysis()
    w.mode_combo.setCurrentIndex(0)
    assert w.segmented_mode
    wait_idle(w, qapp)
    assert "pdv_channel_1" in s.results
    result = s.results["pdv_channel_1"]
    assert set(result.algorithm_ids) == {"stft", "dechirp"}
    assert np.all(np.diff(result.time_s) > 0)
    assert result.valid.any()
    paths = s.export_to(tmp_path / "export")
    metadata = json.loads(paths[-1].read_text(encoding="utf-8"))
    assert "pdv_channel_1" in paths[0].name
    assert metadata["mode"] == "research_test_segmented"
    assert s.channel_combo.currentText() == "候选1"
    assert s.channel_combo.currentData() == "pdv_channel_1"
    s.move_boundary(0, 90e-9)
    assert not s.results and not s.export_button.isEnabled()


def test_compact_diagnostics_and_experiment_disclosure_do_not_change_configuration(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    before = w.analysis_session.run_configuration
    assert not w.experiment_section.toggle.isChecked()
    w.experiment_section.toggle.setChecked(True)
    w.experiment_section.toggle.setChecked(False)
    assert w.analysis_session.run_configuration == before
    w.mode_combo.setCurrentIndex(1)
    for width, height in ((1024, 640), (1280, 800), (1600, 1000)):
        w.resize(width, height)
        qapp.processEvents()
        assert w.segment_workspace.raw_view.plot_widget.width() >= 550
        assert w.properties_stack.width() >= 280
        assert w.diagnostics_dock.height() < height * .23
        assert w.segment_workspace.run_button.isVisible()
        assert w.segment_workspace.export_button.isVisible()
    w.diagnostics_toggle.setChecked(True)
    qapp.processEvents()
    assert w.diagnostics_dock.height() >= 180


def test_channel_undo_does_not_erase_other_channel_manual_selection(
        workstation: ResearchMainWindow) -> None:
    s = workstation.segment_workspace
    s.set_segment(0, stage="acceleration")
    s.add_boundary(100e-9)
    s.channel_combo.setCurrentIndex(1)
    s.set_segment(0, algorithm="varpro")
    second_id = s.plan[0].id
    s.channel_combo.setCurrentIndex(0)
    s.undo_edit()
    assert ("pdv_channel_2", second_id) in s.manual_choices
    s.channel_combo.setCurrentIndex(1)
    assert s.plan[0].algorithm == "varpro"
    s.set_segment(0, stage="noise")
    assert s.plan[0].algorithm == "stft"


def test_manual_reference_reuses_cache_and_preserves_classic_result_and_channel_zoom(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    classic(w, qapp)
    before = w.analysis_session.channel_analyses["pdv_channel_1"]
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    QTest.mouseClick(s.prepare_reference_button, Qt.MouseButton.LeftButton)
    assert not w._analysis_adapter.busy
    assert s.views.currentWidget() is s.spectrogram
    assert w.analysis_session.channel_analyses["pdv_channel_1"] is before
    s.raw_view.plot_widget.setRange(xRange=(.04, .09), yRange=(-100, 100), padding=0)
    bounds = s.raw_view.plot_widget.viewRange()
    s.channel_combo.setCurrentIndex(1)
    s.channel_combo.setCurrentIndex(0)
    np.testing.assert_allclose(s.raw_view.plot_widget.viewRange(), bounds)


@pytest.mark.parametrize("mode", ["full", "search", "custom"])
def test_spectral_view_choice_survives_bounds_edits_and_redraw(
        workstation: ResearchMainWindow, qapp: QApplication, mode: str) -> None:
    w = workstation
    classic(w, qapp)
    view = w.spectrogram_view
    if mode == "full":
        view.show_full_spectrum()
    elif mode == "search":
        view.fit_search_region()
    else:
        view.plot_widget.setRange(xRange=(.02, .15), yRange=(.2, 2.), padding=0)
        view.plot_widget.plotItem.vb.sigRangeChangedManually.emit([True, True])
    previous = np.asarray(view.plot_widget.viewRange())
    w.minimum_frequency_spin.setValue(.1)
    qapp.processEvents()
    assert w.science_tabs.currentWidget() is w.velocity_view
    assert view.spectral_view_mode == mode
    if mode == "custom":
        np.testing.assert_allclose(view.plot_widget.viewRange(), previous)
    elif mode == "full":
        assert view.plot_widget.viewRange()[1][1] >= 19.
    else:
        assert view.plot_widget.viewRange()[1][0] == pytest.approx(.1)


def test_friendly_import_labels_keep_default_identity_and_explicit_custom_names(
        workstation: ResearchMainWindow) -> None:
    from dps_studio.gui.import_dialog import ImportSettingsDialog

    assert workstation.load_result is not None
    dialog = ImportSettingsDialog(workstation.load_result.source_path)
    try:
        assert dialog.channel_1_name.text() == "候选1"
        assert dialog.load_request().channels[0].name == "pdv_channel_1"
        dialog.channel_1_name.setText("探头A")
        assert dialog.load_request().channels[0].name == "探头A"
    finally:
        dialog.close()


def test_repeated_native_roi_replacement_and_workspace_disposal(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    import gc

    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QSignalSpy

    from dps_studio.core.ridge import RidgeCorridorConstraint

    w = workstation
    classic(w, qapp)
    stft = w.analysis_session.stft_results["pdv_channel_1"]
    corridor = RidgeCorridorConstraint(
        control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
        control_frequencies_hz=np.asarray([700e6, 700e6]), half_width_hz=70e6)
    w._ridge_constraint_changed("pdv_channel_1", corridor)
    controller = w.spectrogram_view.corridor_controller
    spy = QSignalSpy(controller.constraint_changed)
    for index in range(24):
        roi = controller._boundary_rois["upper"]
        roi.setPos([0, .001 if index % 2 else -.001], finish=False)
        roi.sigRegionChangeFinished.emit(roi)
        qapp.processEvents()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()
        assert controller.constraint is not None
        assert w.analysis_session.ridge_constraints["pdv_channel_1"] == controller.constraint
    assert spy.count() == 24
    s = w.segment_workspace
    assert s.add_boundary(100e-9)
    w.close()
    assert not s.lines and not s._all_lines
    assert s.spectrogram.corridor_controller.channel_name is None


def test_repeated_window_rebuild_with_native_frequency_rois(
        workstation: ResearchMainWindow, qapp: QApplication, tmp_path: Path) -> None:
    import gc

    from PySide6.QtCore import QEvent

    from dps_studio.core.ridge import RidgeCorridorConstraint

    classic(workstation, qapp)
    loaded = workstation.load_result
    assert loaded is not None
    stfts = workstation.analysis_session.stft_results
    for index in range(10):
        w = ResearchMainWindow(
            settings=QSettings(str(tmp_path / f"rebuild_{index}.ini"), QSettings.Format.IniFormat),
            window_preset_repository=WindowPresetRepository(tmp_path / f"presets_{index}.json"))
        w.set_loaded_result(loaded)
        w.analysis_session.accept_stft_results(generation_id=w.analysis_session.generation_id, stft_results=stfts)
        w._finish_stft_presentation()
        for name, stft in stfts.items():
            corridor = RidgeCorridorConstraint(
                control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
                control_frequencies_hz=np.asarray([700e6, 700e6]), half_width_hz=70e6)
            w._ridge_constraint_changed(name, corridor)
        for channel in range(2):
            w.spectrogram_view.channel_combo.setCurrentIndex(channel)
            w.mode_combo.setCurrentIndex(1)
            w.mode_combo.setCurrentIndex(0)
        w.close()
        assert not w.segment_workspace._all_lines
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        del w
        gc.collect()


def test_copy_plan_to_all_copies_algorithm_selection_origin(workstation: ResearchMainWindow) -> None:
    s = workstation.segment_workspace
    s.set_segment(0, algorithm="varpro")
    s.copy_plan_to_all()
    s._adopt_recommendation()
    assert s.plan[0].algorithm == "stft"
    s.copy_plan_to_all()
    s.channel_combo.setCurrentIndex(1)
    s.set_segment(0, stage="acceleration")
    assert s.plan[0].algorithm == "dechirp"


def test_status_channel_follows_active_workspace_and_view(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    classic(w, qapp)
    w.velocity_view.channel_combo.setCurrentIndex(1)
    assert w.status_channel.text() == "通道：候选2"
    w.mode_combo.setCurrentIndex(1)
    assert w.status_channel.text() == "通道：候选1"
    w.mode_combo.setCurrentIndex(0)
    assert w.status_channel.text() == "通道：候选2"
    assert w.status_state.text() == "结果就绪"


def test_interval_annotations_follow_zoom_and_reference_uses_configured_db_floor(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    from dataclasses import replace

    import pyqtgraph as pg

    w = workstation
    classic(w, qapp)
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    assert s.add_boundary(100e-9)
    plot = s.raw_view.plot_widget
    plot.setRange(xRange=(.03, .07), yRange=(-10, 10), padding=0)
    qapp.processEvents()
    labels = [item for item in s._overlay_items["raw"] if isinstance(item, pg.TextItem)]
    assert labels[0].isVisible() and not labels[1].isVisible()
    assert labels[0].pos().x() == pytest.approx(.05)
    assert labels[0].pos().y() == pytest.approx(10.)
    assert s._configuration is not None
    s.set_context(s.records, s._roi, replace(s._configuration, relative_db_floor=-48.), s._source, s._frequency_band_hz)
    s.set_references(w.analysis_session.stft_results, w.analysis_session.channel_analyses)
    assert s.spectrogram._floor_db == -48.


def test_mouse_drag_split_line_updates_plan_and_survives_native_release(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    from PySide6.QtCore import QPointF

    w = workstation
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    assert s.add_boundary(100e-9)
    qapp.processEvents()
    plot = s.raw_view.plot_widget
    viewbox = plot.plotItem.vb
    start = plot.mapFromScene(viewbox.mapViewToScene(QPointF(.1, 0)))
    end = plot.mapFromScene(viewbox.mapViewToScene(QPointF(.115, 0)))
    QTest.mousePress(plot.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(plot.viewport(), end, delay=30)
    QTest.mouseRelease(plot.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    qapp.processEvents()
    assert s.plan[0].end_s > 105e-9
    assert s.plan[0].end_s == s.plan[1].start_s
    for lines in s._all_lines.values():
        assert lines[0].value() == pytest.approx(s.plan[0].end_s * 1e6)


def test_quantity_switch_preserves_time_zoom_and_fits_the_new_physical_unit(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    classic(w, qapp)
    view = w.velocity_view
    view.plot_widget.setRange(xRange=(.04, .12), yRange=(400, 900), padding=0)
    view.plot_widget.plotItem.vb.sigRangeChangedManually.emit([True, True])
    for quantity in (1, 0):
        view.quantity_combo.setCurrentIndex(quantity)
        qapp.processEvents()
        np.testing.assert_allclose(view.plot_widget.viewRange()[0], [.04, .12])
        assert view.view_mode == "custom"
        curve = view.acceleration_curve if quantity else view.display_curve
        time, values = curve.getData()
        finite = values[(time >= .04) & (time <= .12) & np.isfinite(values)]
        assert finite.size
        y = view.plot_widget.viewRange()[1]
        assert y[0] <= float(np.median(finite)) <= y[1]


def test_manual_velocity_reference_and_boundaries_share_absolute_time_after_event_adoption(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    classic(w, qapp)
    w._event_reference_confirmed(40e-9)
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    assert s.add_boundary(100e-9)
    s.views.setCurrentWidget(s.reference_velocity)
    time, _values = s.reference_velocity.display_curve.getData()
    np.testing.assert_array_equal(time,
        w.analysis_session.channel_analyses["pdv_channel_1"].stft_result.time_s * 1e6)
    assert s._all_lines["classic"][0].value() == pytest.approx(.1)


def test_segmented_frequency_and_velocity_fields_use_their_own_y_units(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    assert s.run_analysis()
    wait_idle(w, qapp)
    result = s.results["pdv_channel_1"]
    previous_x = np.asarray(s.result_plot.viewRange()[0])
    for field in (2, 0):
        s.field_combo.setCurrentIndex(field)
        qapp.processEvents()
        values = result.frequency_hz * 1e-9 if field == 2 else result.corrected_velocity_m_s
        finite = values[np.isfinite(values)]
        assert finite.size
        y = s.result_plot.viewRange()[1]
        assert y[0] <= float(np.median(finite)) <= y[1]
        np.testing.assert_allclose(s.result_plot.viewRange()[0], previous_x)


def test_computing_manual_stft_reference_does_not_replace_edited_roi_or_plan(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    assert s.add_boundary(80e-9)
    s.set_segment(1, stage="acceleration", algorithm="varpro")
    s.roi_change_requested.emit(20e-9, 160e-9)
    before = s.plan
    assert s.run_analysis()
    wait_idle(w, qapp)
    original_result = s.results["pdv_channel_1"]
    QTest.mouseClick(s.prepare_reference_button, Qt.MouseButton.LeftButton)
    wait_idle(w, qapp)
    assert w.analysis_session.stft_valid
    assert s.plan == before
    assert s.results["pdv_channel_1"] is original_result
    assert s.plan[0].start_s == 20e-9 and s.plan[-1].end_s == 160e-9
    for _ in range(3):
        w.mode_combo.setCurrentIndex(0)
        w.mode_combo.setCurrentIndex(1)
        assert s.plan == before


def test_edit_range_button_opens_the_raw_reference_inside_manual_mode(
        workstation: ResearchMainWindow, qapp: QApplication) -> None:
    w = workstation
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    s.views.setCurrentIndex(2)
    QTest.mouseClick(s.roi_button, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert w.segmented_mode and s.views.currentWidget() is s.raw_view
    assert s.raw_view.analysis_region.isVisible()
