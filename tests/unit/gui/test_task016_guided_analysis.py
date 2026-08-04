from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QPointF, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "demo_dual_profile.toml"


def _load_result(tmp_path: Path) -> tuple[Any, Path, bytes]:
    sample_count = 4096
    time_s = 5.54e-4 + np.arange(sample_count, dtype=np.float64) * 25.0e-12
    relative = time_s - time_s[0]
    values = np.column_stack(
        (
            time_s,
            np.sin(2.0 * np.pi * 0.50e9 * relative),
            0.7 * np.sin(2.0 * np.pi * 0.54e9 * relative + 0.3),
        )
    )
    source = tmp_path / "task016_dual_channel.csv"
    np.savetxt(source, values, delimiter=",", fmt="%.17e")
    before = source.read_bytes()
    request = SignalLoadRequest(
        path=source,
        time_column=0,
        channels=(
            ChannelImportSpec("pdv_channel_1", 1, 1.0),
            ChannelImportSpec("pdv_channel_2", 2, 1.0),
        ),
        delimiter=",",
        has_header=False,
        encoding="utf-8",
        time_scale=1.0,
    )
    return DataImportController().load(request), source, before


def _window(qapp: QApplication, tmp_path: Path) -> tuple[MainWindow, Path, bytes]:
    result, source, before = _load_result(tmp_path)
    window = MainWindow(translation_manager=translation_manager())
    window.set_loaded_result(result)
    configuration = load_workflow_config(
        CONFIG_PATH,
        repository_root=REPOSITORY_ROOT,
    )
    window.set_analysis_configuration(configuration)
    window.analysis_range_panel.use_full_range()
    qapp.processEvents()
    return window, source, before


def _wait_for_run(window: MainWindow, launch: Any) -> None:
    loop = QEventLoop()
    timed_out = {"value": False}

    def timeout() -> None:
        timed_out["value"] = True
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(lambda *_args: loop.quit())
    QTimer.singleShot(15_000, timeout)
    assert launch()
    loop.exec()
    assert not timed_out["value"]
    assert not window._analysis_adapter.busy


def _corridor_for_current_analysis(window: MainWindow) -> RidgeCorridorConstraint:
    analysis = window.analysis_session.channel_analyses["pdv_channel_1"]
    time_s = analysis.stft_result.time_s
    return RidgeCorridorConstraint(
        control_times_s=np.array([time_s[2], time_s[-3]]),
        control_frequencies_hz=np.array([0.46e9, 0.54e9]),
        half_width_hz=60.0e6,
    )


def test_guided_initial_state_requires_data_and_automatic_stft(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert not window.action_guided.isEnabled()
        assert not window.guided_mode_radio.isEnabled()
        assert not window.draw_corridor_button.isEnabled()
        assert not window.run_guided_button.isEnabled()
        assert "STFT" in window.guided_status_label.text()
        assert not window.spectrogram_view.corridor_controller.begin_drawing(
            half_width_hz=50.0e6
        )
    finally:
        window.close()
        qapp.processEvents()


def test_corridor_editing_stores_si_coordinates_and_is_channel_local(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, source, source_before = _window(qapp, tmp_path)
    try:
        _wait_for_run(window, window.run_automatic_analysis)
        assert window.action_guided.isEnabled()
        frequency_hz = window.analysis_session.channel_analyses[
            "pdv_channel_1"
        ].stft_result.frequency_hz
        assert window.corridor_half_width_spin.value() == pytest.approx(
            5.0 * (frequency_hz[1] - frequency_hz[0]) * 1.0e-6,
            abs=0.0005,
        )
        assert "不是实验标定或最佳值" in (
            window.corridor_half_width_spin.toolTip()
        )
        constraint = _corridor_for_current_analysis(window)
        automatic = window.analysis_session.channel_analyses
        automatic_spectrum = automatic["pdv_channel_1"].stft_result.spectrum.copy()
        controller = window.spectrogram_view.corridor_controller
        assert controller.begin_drawing(half_width_hz=constraint.half_width_hz)
        controller._draft_points = list(
            zip(
                constraint.control_times_s,
                constraint.control_frequencies_hz,
            )
        )
        controller._refresh_draft()
        assert controller.finish_drawing()
        qapp.processEvents()

        stored = window.analysis_session.ridge_constraints["pdv_channel_1"]
        np.testing.assert_array_equal(stored.control_times_s, constraint.control_times_s)
        np.testing.assert_array_equal(
            stored.control_frequencies_hz,
            constraint.control_frequencies_hz,
        )
        assert "pdv_channel_2" not in window.analysis_session.ridge_constraints
        assert window.analysis_session.results_valid
        assert window.analysis_session.channel_analyses is automatic

        times_before = stored.control_times_s.copy()
        frequencies_before = stored.control_frequencies_hz.copy()
        window.spectrogram_view.plot_widget.resize(990, 510)
        qapp.processEvents()
        after_resize = window.analysis_session.ridge_constraints["pdv_channel_1"]
        np.testing.assert_array_equal(after_resize.control_times_s, times_before)
        np.testing.assert_array_equal(
            after_resize.control_frequencies_hz,
            frequencies_before,
        )

        roi = controller._roi
        assert roi is not None
        first_handle = roi.handles[0]["item"]
        roi.movePoint(
            first_handle,
            QPointF(times_before[0] * 1.0e6 + 0.001, 0.47),
            finish=True,
        )
        qapp.processEvents()
        moved = window.analysis_session.ridge_constraints["pdv_channel_1"]
        assert moved.control_times_s[0] != times_before[0]
        assert moved.control_frequencies_hz[0] == pytest.approx(0.47e9)

        roi = controller._roi
        assert roi is not None
        midpoint = QPointF(
            float(np.mean(moved.control_times_s)) * 1.0e6,
            0.50,
        )
        roi.segmentClicked(roi.segments[0], pos=midpoint)
        qapp.processEvents()
        assert (
            window.analysis_session.ridge_constraints[
                "pdv_channel_1"
            ].control_point_count
            == 3
        )
        roi = controller._roi
        assert roi is not None
        roi.removeHandle(roi.handles[1]["item"])
        qapp.processEvents()
        assert (
            window.analysis_session.ridge_constraints[
                "pdv_channel_1"
            ].control_point_count
            == 2
        )
        np.testing.assert_array_equal(
            automatic["pdv_channel_1"].stft_result.spectrum,
            automatic_spectrum,
        )
        assert source.read_bytes() == source_before
    finally:
        window.close()
        qapp.processEvents()


def test_guided_results_are_background_computed_separate_and_stale_independently(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, source, source_before = _window(qapp, tmp_path)
    try:
        _wait_for_run(window, window.run_automatic_analysis)
        automatic = window.analysis_session.channel_analyses
        automatic_arrays = {
            name: analysis.signal_detection_result.apparent_velocity_m_s.copy()
            for name, analysis in automatic.items()
        }
        window._ridge_constraint_changed(
            "pdv_channel_1",
            _corridor_for_current_analysis(window),
        )
        _wait_for_run(window, window.run_guided_analysis)
        session = window.analysis_session
        assert session.results_valid
        assert session.guided_results_valid
        assert not session.guided_results_stale
        assert session.channel_analyses is automatic
        assert set(session.guided_channel_analyses) == {"pdv_channel_1"}
        assert window.ridge_view.result_source_combo.findData("guided") >= 0
        assert window.velocity_view.result_source_combo.findData("guided") >= 0
        assert any(key.startswith("automatic:") for key in window.comparison_view.curves)
        assert any(key.startswith("guided:") for key in window.comparison_view.curves)
        assert window.ridge_view.formal_curve.opts["connect"] == "finite"
        assert window.velocity_view.formal_curve.opts["connect"] == "finite"

        previous_guided = session.guided_channel_analyses
        previous_generation = session.generation_id
        window.corridor_half_width_spin.setValue(
            window.corridor_half_width_spin.value() + 5.0
        )
        qapp.processEvents()
        assert session.guided_results_stale
        assert not session.guided_results_valid
        assert session.guided_channel_analyses is previous_guided
        assert session.generation_id == previous_generation
        assert session.results_valid
        assert "重新运行引导分析" in window.guided_status_label.text()
        assert window.ridge_view.result_source_combo.findData("guided") == -1
        for name, analysis in session.channel_analyses.items():
            np.testing.assert_array_equal(
                analysis.signal_detection_result.apparent_velocity_m_s,
                automatic_arrays[name],
            )
        assert source.read_bytes() == source_before
    finally:
        window.close()
        qapp.processEvents()


def test_corridor_delete_does_not_invalidate_automatic_result(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, _source, _before = _window(qapp, tmp_path)
    try:
        _wait_for_run(window, window.run_automatic_analysis)
        automatic = window.analysis_session.channel_analyses
        window._ridge_constraint_changed(
            "pdv_channel_1",
            _corridor_for_current_analysis(window),
        )
        window._clear_current_corridor()
        qapp.processEvents()
        assert not window.analysis_session.ridge_constraints
        assert window.analysis_session.channel_analyses is automatic
        assert window.analysis_session.results_valid
    finally:
        window.close()
        qapp.processEvents()


def test_guided_terminology_is_translated_without_language_branches(
    qapp: QApplication,
) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        assert window.action_guided.text() == "Guided Analysis"
        assert window.draw_corridor_button.text() == "Draw / Edit Corridor"
        assert window.clear_corridor_button.text() == "Clear Corridor"
        assert any(
            label.text() == "Corridor Half Width"
            for label in window.findChildren(QLabel)
        )
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_gui_does_not_import_scripts_and_raw_data_is_untouched() -> None:
    gui_directory = REPOSITORY_ROOT / "src" / "dps_studio" / "gui"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in gui_directory.glob("*.py")
    )
    assert "scripts." not in source
