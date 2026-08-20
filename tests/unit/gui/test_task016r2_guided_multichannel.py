from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.analysis_adapter import AnalysisResultSource
from dps_studio.gui.analysis_session import RidgeExtractionMode
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import (
    _AUTOMATIC_MODE_BUTTON_ID,
    _GUIDED_MODE_BUTTON_ID,
    MainWindow,
)
from dps_studio.gui.state import WorkflowState


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _window(qapp: QApplication, tmp_path: Path) -> MainWindow:
    sample_rate_hz = 40.0e9
    time_s = 5.54e-4 + np.arange(8192, dtype=np.float64) / sample_rate_hz
    relative_s = time_s - time_s[0]
    values = np.column_stack(
        (
            time_s,
            np.sin(2.0 * np.pi * 0.63e9 * relative_s),
            np.sin(2.0 * np.pi * 0.68e9 * relative_s + 0.2),
        )
    )
    source = tmp_path / "task016r2_dual_channel.csv"
    np.savetxt(source, values, delimiter=",", fmt="%.17e")
    loaded = DataImportController().load(
        SignalLoadRequest(
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
    )
    window = MainWindow(translation_manager=translation_manager())
    window.set_loaded_result(loaded)
    window.set_analysis_configuration(
        load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    )
    window.analysis_range_panel.use_full_range()
    qapp.processEvents()
    return window


def _wait(
    window: MainWindow,
    launch: Any,
    *,
    expected_source: AnalysisResultSource | None = None,
) -> None:
    loop = QEventLoop()
    state = {"timed_out": False, "error": None}

    def timeout() -> None:
        state["timed_out"] = True
        loop.quit()

    def failed(_generation: int, error_type: str, message: str, _traceback: str) -> None:
        state["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(15_000, timeout)
    assert launch()
    if expected_source is not None:
        assert window._pending_analysis_source is expected_source
    loop.exec()
    assert not state["timed_out"]
    assert state["error"] is None
    assert not window._analysis_adapter.busy


def _select_spectrogram_channel(
    window: MainWindow,
    channel_name: str,
) -> None:
    selector = window.spectrogram_view.channel_combo
    index = selector.findData(channel_name)
    assert index >= 0
    selector.setCurrentIndex(index)


def _constraint(
    window: MainWindow,
    channel_name: str,
    frequency_hz: float,
) -> RidgeCorridorConstraint:
    stft = window.analysis_session.stft_results[channel_name]
    return RidgeCorridorConstraint(
        control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
        control_frequencies_hz=np.asarray([frequency_hz, frequency_hz]),
        half_width_hz=70.0e6,
    )


def test_guided_channels_are_independent_and_runs_target_displayed_channel(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_stft_analysis)
        session = window.analysis_session
        channel_1_stft = session.stft_results["pdv_channel_1"]
        channel_2_stft = session.stft_results["pdv_channel_2"]

        window.guided_mode_radio.click()
        qapp.processEvents()
        assert window.ridge_extraction_mode is RidgeExtractionMode.GUIDED
        assert window.guided_channel_label.text() == "pdv_channel_1"
        corridor_1 = _constraint(window, "pdv_channel_1", 0.63e9)
        window._ridge_constraint_changed("pdv_channel_1", corridor_1)
        _wait(window, window.run_guided_analysis)
        guided_1 = session.guided_channel_analyses["pdv_channel_1"]
        assert set(session.valid_guided_channel_analyses) == {"pdv_channel_1"}
        assert not session.results_valid
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert window.science_tabs.isTabEnabled(3)
        assert window.science_tabs.isTabEnabled(4)
        assert window.velocity_view.result_source_combo.count() == 1
        assert window.velocity_view.result_source == "guided"
        assert window.comparison_view.notice.text() == "当前只有一个可比较结果。"
        assert not window.comparison_view.notice.isHidden()

        _select_spectrogram_channel(window, "pdv_channel_2")
        qapp.processEvents()
        controller = window.spectrogram_view.corridor_controller
        assert window.guided_channel_label.text() == "pdv_channel_2"
        assert controller.channel_name == "pdv_channel_2"
        assert controller.constraint is None
        assert "pdv_channel_2" not in session.ridge_constraints

        corridor_2 = _constraint(window, "pdv_channel_2", 0.68e9)
        window._ridge_constraint_changed("pdv_channel_2", corridor_2)
        _wait(window, window.run_guided_analysis)
        assert set(session.guided_channel_analyses) == {
            "pdv_channel_1",
            "pdv_channel_2",
        }
        assert set(session.valid_guided_channel_analyses) == {
            "pdv_channel_1",
            "pdv_channel_2",
        }
        assert session.guided_channel_analyses["pdv_channel_1"] is guided_1
        assert session.stft_results["pdv_channel_1"] is channel_1_stft
        assert session.stft_results["pdv_channel_2"] is channel_2_stft
        assert not session.results_valid
        assert len(window.comparison_view.curves) == 2
        assert window.comparison_view.notice.text() == ""
        assert window.comparison_view.notice.isHidden()

        _select_spectrogram_channel(window, "pdv_channel_1")
        qapp.processEvents()
        assert controller.constraint is corridor_1
        assert window.upper_boundary_point_count_label.text() == "2"
        assert window.lower_boundary_point_count_label.text() == "2"
        assert "旧版走廊" in window.corridor_state_label.text()

        _select_spectrogram_channel(window, "pdv_channel_2")
        changed_2 = RidgeCorridorConstraint(
            control_times_s=corridor_2.control_times_s,
            control_frequencies_hz=corridor_2.control_frequencies_hz,
            half_width_hz=75.0e6,
        )
        window._ridge_constraint_changed("pdv_channel_2", changed_2)
        qapp.processEvents()
        assert session.ridge_constraints["pdv_channel_1"] is corridor_1
        assert session.guided_result_is_valid("pdv_channel_1")
        assert session.guided_result_is_stale("pdv_channel_2")
        assert set(session.valid_guided_channel_analyses) == {"pdv_channel_1"}
        assert session.stft_results["pdv_channel_1"] is channel_1_stft
        assert not session.results_valid

        window.clear_corridor_button.click()
        qapp.processEvents()
        assert "pdv_channel_2" not in session.ridge_constraints
        assert session.ridge_constraints["pdv_channel_1"] is corridor_1
        assert session.guided_result_is_valid("pdv_channel_1")
        assert session.stft_results["pdv_channel_2"] is channel_2_stft
    finally:
        window.close()
        qapp.processEvents()


def test_guided_only_velocity_source_keeps_missing_channel_selectable(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_stft_analysis)
        window.guided_mode_radio.click()
        window._ridge_constraint_changed(
            "pdv_channel_1",
            _constraint(window, "pdv_channel_1", 0.63e9),
        )
        _wait(window, window.run_guided_analysis)
        view = window.velocity_view
        assert view.result_source_combo.count() == 1
        assert view.result_source == "guided"
        assert view.channel_combo.count() == 2
        channel_2_index = view.channel_combo.findData("pdv_channel_2")
        assert channel_2_index >= 0
        view.channel_combo.setCurrentIndex(channel_2_index)
        qapp.processEvents()
        assert "当前通道尚无人工范围结果" in view.source_notice.text()
        assert not view.source_notice.isHidden()
        assert view.formal_curve is None
    finally:
        window.close()
        qapp.processEvents()


def test_extraction_mode_controls_keep_widget_group_model_and_run_path_aligned(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        group = window.ridge_mode_button_group
        assert window.automatic_mode_radio.isChecked()
        assert not window.guided_mode_radio.isChecked()
        assert group.checkedId() == _AUTOMATIC_MODE_BUTTON_ID
        assert group.checkedButton() is window.automatic_mode_radio
        assert window.ridge_extraction_mode is RidgeExtractionMode.AUTOMATIC

        _wait(window, window.run_stft_analysis)
        window._ridge_constraint_changed(
            "pdv_channel_1",
            _constraint(window, "pdv_channel_1", 0.63e9),
        )
        for button, expected_id, expected_mode, run_handler, expected_source in (
            (
                window.guided_mode_radio,
                _GUIDED_MODE_BUTTON_ID,
                RidgeExtractionMode.GUIDED,
                window.run_guided_analysis,
                AnalysisResultSource.GUIDED,
            ),
            (
                window.automatic_mode_radio,
                _AUTOMATIC_MODE_BUTTON_ID,
                RidgeExtractionMode.AUTOMATIC,
                window.run_staged_automatic_analysis,
                AnalysisResultSource.AUTOMATIC,
            ),
            (
                window.guided_mode_radio,
                _GUIDED_MODE_BUTTON_ID,
                RidgeExtractionMode.GUIDED,
                window.run_guided_analysis,
                AnalysisResultSource.GUIDED,
            ),
            (
                window.automatic_mode_radio,
                _AUTOMATIC_MODE_BUTTON_ID,
                RidgeExtractionMode.AUTOMATIC,
                window.run_staged_automatic_analysis,
                AnalysisResultSource.AUTOMATIC,
            ),
            (
                window.guided_mode_radio,
                _GUIDED_MODE_BUTTON_ID,
                RidgeExtractionMode.GUIDED,
                window.run_guided_analysis,
                AnalysisResultSource.GUIDED,
            ),
        ):
            button.click()
            qapp.processEvents()
            assert button.isChecked()
            assert group.checkedId() == expected_id
            assert group.checkedButton() is button
            assert window.ridge_extraction_mode is expected_mode
            assert window.automatic_mode_radio.isChecked() is (
                expected_mode is RidgeExtractionMode.AUTOMATIC
            )
            assert window.guided_mode_radio.isChecked() is (
                expected_mode is RidgeExtractionMode.GUIDED
            )
            assert window.automatic_ridge_panel.isHidden() is (
                expected_mode is RidgeExtractionMode.GUIDED
            )
            assert window.guided_ridge_panel.isHidden() is (
                expected_mode is RidgeExtractionMode.AUTOMATIC
            )
            _wait(
                window,
                run_handler,
                expected_source=expected_source,
            )
        assert window.analysis_session.guided_results_available
        assert window.analysis_session.results_valid
    finally:
        window.close()
        qapp.processEvents()


def test_display_connector_is_guided_only_presentation_and_preserves_formal_data(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_stft_analysis)
        session = window.analysis_session
        stft = session.stft_results["pdv_channel_1"]
        session.set_event_reference_time_s(float(stft.time_s[12]))
        session.set_display_velocity_configuration(
            enabled=True,
            pre_event_display_velocity_m_s=0.0,
        )
        window.guided_mode_radio.click()
        window._ridge_constraint_changed(
            "pdv_channel_1",
            RidgeCorridorConstraint(
                control_times_s=np.asarray([stft.time_s[3], stft.time_s[-4]]),
                control_frequencies_hz=np.asarray([0.63e9, 0.63e9]),
                half_width_hz=70.0e6,
            ),
        )
        _wait(window, window.run_guided_analysis)
        window._refresh_result_source_views()
        guided_index = window.velocity_view.result_source_combo.findData("guided")
        window.velocity_view.result_source_combo.setCurrentIndex(guided_index)
        analysis = session.valid_guided_channel_analyses["pdv_channel_1"]
        formal_before = (
            analysis.signal_detection_result.apparent_velocity_m_s.copy()
        )
        window.velocity_view.display_velocity_check.setChecked(True)
        qapp.processEvents()
        connector = window.velocity_view.display_connector
        assert connector is not None
        connector_time_us, connector_velocity_m_s = connector.getData()
        finite_indices = np.flatnonzero(
            np.isfinite(analysis.signal_detection_result.apparent_velocity_m_s)
            & (analysis.stft_result.time_s >= session.event_reference_time_s)
        )
        assert finite_indices.size > 0
        first = int(finite_indices[0])
        assert connector_time_us[0] == pytest.approx(0.0)
        assert connector_time_us[1] == pytest.approx(
            (
                analysis.stft_result.time_s[first]
                - session.event_reference_time_s
            )
            * 1.0e6
        )
        assert connector_velocity_m_s[1] == pytest.approx(
            analysis.signal_detection_result.apparent_velocity_m_s[first]
        )
        np.testing.assert_array_equal(
            analysis.signal_detection_result.apparent_velocity_m_s,
            formal_before,
        )

        window.velocity_view.display_velocity_check.setChecked(False)
        qapp.processEvents()
        assert window.velocity_view.display_curve is None
        assert window.velocity_view.display_connector is None
        np.testing.assert_array_equal(
            analysis.signal_detection_result.apparent_velocity_m_s,
            formal_before,
        )
    finally:
        window.close()
        qapp.processEvents()
