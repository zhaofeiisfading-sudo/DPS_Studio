from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.ridge import ManualFrequencyRegion, RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _window(qapp: QApplication, tmp_path: Path) -> MainWindow:
    sample_rate_hz = 40.0e9
    time_s = 5.54e-4 + np.arange(4096, dtype=np.float64) / sample_rate_hz
    relative_s = time_s - time_s[0]
    values = np.column_stack(
        (
            time_s,
            np.sin(2.0 * np.pi * 0.63e9 * relative_s),
            np.sin(2.0 * np.pi * 0.68e9 * relative_s + 0.2),
        )
    )
    source = tmp_path / "task016r.csv"
    np.savetxt(source, values, delimiter=",", fmt="%.17e")
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
    window = MainWindow(translation_manager=translation_manager())
    window.set_loaded_result(DataImportController().load(request))
    window.set_analysis_configuration(
        load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    )
    window.analysis_range_panel.use_full_range()
    qapp.processEvents()
    return window


def _wait(window: MainWindow, launch: Any) -> None:
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


def _constraint(window: MainWindow, count: int = 2) -> RidgeCorridorConstraint:
    stft = window.analysis_session.stft_results["pdv_channel_1"]
    indices = np.linspace(4, stft.time_s.size - 5, count, dtype=int)
    return RidgeCorridorConstraint(
        control_times_s=stft.time_s[indices],
        control_frequencies_hz=np.full(count, 0.63e9),
        half_width_hz=70.0e6,
    )


def test_independent_stft_reaches_ready_and_view_shortcuts_are_display_only(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_stft_analysis)
        session = window.analysis_session
        assert session.stft_valid
        assert not session.results_valid
        assert window.workflow_state is WorkflowState.STFT_READY
        assert window.science_tabs.isTabEnabled(1)
        assert window.science_tabs.isTabEnabled(2)
        spectrum_before = session.stft_results["pdv_channel_1"].spectrum.copy()

        window.spectrogram_view.fit_search_region()
        x_range, y_range = window.spectrogram_view.plot_widget.viewRange()
        analysis_range = session.analysis_range
        configuration = session.run_configuration
        assert analysis_range is not None
        assert configuration is not None
        assert x_range == pytest.approx(
            [analysis_range.start_time_s * 1.0e6, analysis_range.end_time_s * 1.0e6]
        )
        assert y_range == pytest.approx(
            [
                configuration.parameters.minimum_frequency_hz * 1.0e-9,
                configuration.parameters.maximum_frequency_hz * 1.0e-9,
            ]
        )
        window.spectrogram_view.show_full_spectrum()
        _x_range, full_y = window.spectrogram_view.plot_widget.viewRange()
        stft = session.stft_results["pdv_channel_1"]
        assert full_y == pytest.approx(
            [stft.frequency_hz[0] * 1.0e-9, stft.frequency_hz[-1] * 1.0e-9]
        )
        np.testing.assert_array_equal(stft.spectrum, spectrum_before)
    finally:
        window.close()
        qapp.processEvents()


def test_guided_reuses_stft_auto_fits_once_and_is_local_nan(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_stft_analysis)
        session = window.analysis_session
        stft_identity = session.stft_results["pdv_channel_1"]
        window.guided_mode_radio.click()
        qapp.processEvents()
        expected_y = [
            session.run_configuration.parameters.minimum_frequency_hz * 1.0e-9,
            session.run_configuration.parameters.maximum_frequency_hz * 1.0e-9,
        ]
        assert window.spectrogram_view.plot_widget.viewRange()[1] == pytest.approx(
            expected_y
        )
        window.spectrogram_view.plot_widget.setYRange(0.4, 0.8, padding=0.0)
        window._ridge_constraint_changed("pdv_channel_1", _constraint(window))
        qapp.processEvents()
        assert window.spectrogram_view.plot_widget.viewRange()[1] == pytest.approx(
            [0.4, 0.8]
        )

        _wait(window, window.run_guided_analysis)
        assert session.stft_results["pdv_channel_1"] is stft_identity
        assert not session.results_valid
        assert set(session.guided_channel_analyses) == {"pdv_channel_1"}
        analysis = session.guided_channel_analyses["pdv_channel_1"]
        constraint = session.ridge_constraints["pdv_channel_1"]
        outside = (analysis.stft_result.time_s < constraint.start_time_s) | (
            analysis.stft_result.time_s > constraint.end_time_s
        )
        assert np.isnan(
            analysis.signal_detection_result.refined_frequency_hz[outside]
        ).all()
        assert np.isnan(
            analysis.signal_detection_result.apparent_velocity_m_s[outside]
        ).all()
    finally:
        window.close()
        qapp.processEvents()


def test_undo_and_clear_manual_region_preserve_stft_and_automatic(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_stft_analysis)
        _wait(window, window.run_staged_automatic_analysis)
        session = window.analysis_session
        automatic = session.channel_analyses
        stft = session.stft_results["pdv_channel_1"]
        controller = window.spectrogram_view.corridor_controller
        assert controller.begin_boundary("upper")
        four_points = _constraint(window, count=4)
        controller._draft_points = list(
            zip(
                four_points.control_times_s,
                four_points.control_frequencies_hz,
            )
        )
        controller._refresh_draft()
        controller._commit_live_draft()
        region = session.ridge_constraints["pdv_channel_1"]
        assert isinstance(region, ManualFrequencyRegion)
        assert region.upper_boundary is not None
        assert region.upper_boundary.control_point_count == 4
        window.undo_corridor_button.click()
        window.action_backspace_corridor.trigger()
        qapp.processEvents()
        region = session.ridge_constraints["pdv_channel_1"]
        assert isinstance(region, ManualFrequencyRegion)
        assert region.upper_boundary is not None
        assert region.upper_boundary.control_point_count == 2
        qapp.processEvents()
        assert session.stft_results["pdv_channel_1"] is stft
        assert session.channel_analyses is automatic
        assert session.results_valid

        window.clear_corridor_button.click()
        qapp.processEvents()
        assert not session.ridge_constraints
        assert controller.constraint is None
        assert controller._roi is None
        assert controller._upper_curve is not None
        assert controller._lower_curve is not None
        assert controller._fill_item is not None
        assert session.stft_results["pdv_channel_1"] is stft
        assert session.channel_analyses is automatic
        assert session.results_valid
    finally:
        window.close()
        qapp.processEvents()


def test_step_panels_and_1280_by_720_layout_use_scroll_areas(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.resize(1280, 720)
        window.show()
        qapp.processEvents()
        assert window.common_analysis_panel.parentWidget() is not window.parameter_panel
        assert window.stft_parameter_scroll.widgetResizable()
        assert window.ridge_parameter_scroll.widgetResizable()
        assert window.velocity_parameter_scroll.widgetResizable()
        assert window.action_guided not in window.main_toolbar.actions()
        assert window.compute_stft_button.text() == "计算时频图"
        assert window.edit_upper_boundary_button.text() == "编辑上边界"
        assert window.edit_lower_boundary_button.text() == "编辑下边界"
        assert window.undo_corridor_button.text() == "撤销上一点"
        assert window.clear_corridor_button.text() == "清除人工范围"
    finally:
        window.close()
        qapp.processEvents()
