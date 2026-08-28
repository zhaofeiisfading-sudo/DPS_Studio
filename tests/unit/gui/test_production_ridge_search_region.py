from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.workflow import compute_configuration_stfts
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _event_result(tmp_path: Path) -> DelimitedSignalLoadResult:
    sample_count = 8192
    interval_s = 25.0e-12
    time_s = 744.0e-6 + np.arange(sample_count, dtype=np.float64) * interval_s
    onset_s = time_s[0] + 60.0e-9
    active = time_s >= onset_s
    phase = 2.0 * np.pi * 0.65e9 * (time_s - onset_s)
    voltage_v = np.zeros_like(time_s)
    voltage_v[active] = np.sin(phase[active])
    records = {"pdv_channel_1": SignalRecord(time_s, voltage_v)}
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "experiment.csv",
        records=records,
        row_count=sample_count,
        column_count=2,
        channel_names=tuple(records),
        header=None,
        time_column_index=0,
        voltage_column_indices={"pdv_channel_1": 1},
        unselected_column_indices=(),
        delimiter=",",
        encoding="utf-8",
    )


def _wait_for_analysis(window: MainWindow, launch: Callable[[], object]) -> None:
    loop = QEventLoop()
    failures: list[str] = []
    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(
        lambda _generation, error_type, message, _traceback: (
            failures.append(f"{error_type}: {message}"),
            loop.quit(),
        )
    )
    launch()
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()
    assert not failures
    assert not window._analysis_adapter.busy


def _accept_stft(window: MainWindow) -> None:
    configuration = window.analysis_session.run_configuration
    assert configuration is not None
    parameters = configuration.parameters
    stfts = compute_configuration_stfts(
        window.analysis_session.records,
        window_length_samples=parameters.window_length_samples,
        overlap_samples=parameters.overlap_samples,
        nfft=parameters.nfft,
        window_name=parameters.window_name,
    )
    assert window.analysis_session.accept_stft_results(
        generation_id=window.analysis_session.generation_id,
        stft_results=stfts,
    )
    window._finish_stft_presentation()


def test_navigation_never_computes_stft_and_cached_plot_is_reused(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    starts: list[int] = []
    window._analysis_adapter.started.connect(starts.append)
    try:
        window.set_loaded_result(_event_result(tmp_path))
        assert window.select_workflow_step(1)
        qapp.processEvents()
        assert starts == []
        assert not window.analysis_session.stft_valid
        assert window.science_tabs.currentWidget() is window.spectrogram_view

        _accept_stft(window)
        cached = next(iter(window.analysis_session.stft_results.values()))
        window.select_workflow_step(0)
        window.select_workflow_step(1)
        qapp.processEvents()
        assert starts == []
        assert window.spectrogram_view.current_image_db is not None
        assert next(iter(window.analysis_session.stft_results.values())) is cached
    finally:
        window.close()


def test_quick_analysis_waits_for_region_then_continues_to_velocity(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_event_result(tmp_path))
        _wait_for_analysis(window, window.action_quick_analysis.trigger)
        assert window.analysis_session.stft_valid
        assert not window.analysis_session.channel_analyses
        assert window.workflow_state is WorkflowState.STFT_READY
        assert window.workflow_navigation.currentRow() == 2
        assert window.analysis_session.ridge_search_region is not None
        assert window.spectrogram_view._search_region_roi.isVisible()

        _wait_for_analysis(window, window.confirm_search_region_button.click)
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert window.analysis_session.automatic_results_available
        assert window.workflow_navigation.currentRow() == 3
        assert window.science_tabs.currentWidget() is window.velocity_view
        region = window.analysis_session.ridge_search_region
        assert region is not None
        analysis = next(iter(window.analysis_session.channel_analyses.values()))
        assert analysis.ridge_result.minimum_frequency_hz == pytest.approx(
            region.frequency_min_hz
        )
        assert analysis.ridge_result.maximum_frequency_hz == pytest.approx(
            region.frequency_max_hz
        )
        assert (
            analysis.signal_detection_result.analysis_start_time_s
            == pytest.approx(region.time_start_s)
        )
        assert (
            analysis.signal_detection_result.analysis_end_time_s
            == pytest.approx(region.time_end_s)
        )
        for assessment in analysis.stream_event_candidates.segment_assessments:
            assert assessment.segment.start_time_s >= region.time_start_s
            assert assessment.segment.end_time_s <= region.time_end_s
    finally:
        window.close()


def test_full_automatic_is_secondary_and_skips_region_checkpoint(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_event_result(tmp_path))
        toolbar_actions = window.main_toolbar.actions()
        assert window.action_quick_analysis in toolbar_actions
        assert window.action_full_automatic not in toolbar_actions
        assert window.action_full_automatic in window.analysis_menu.actions()
        _wait_for_analysis(window, window.action_full_automatic.trigger)
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert window.analysis_session.ridge_search_region is not None
        assert window.workflow_navigation.currentRow() == 3
    finally:
        window.close()


def test_four_edges_and_numeric_inputs_share_si_region(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_event_result(tmp_path))
        _accept_stft(window)
        window.select_workflow_step(2)
        view = window.spectrogram_view
        stft = next(iter(window.analysis_session.stft_results.values()))

        view._search_time_lines[0].setPos(float(stft.time_s[5]) * 1.0e6)
        view._search_time_boundary_finished(0)
        assert window.analysis_session.ridge_search_region.time_start_s == pytest.approx(
            stft.time_s[5]
        )

        view._search_time_lines[1].setPos(float(stft.time_s[-5]) * 1.0e6)
        view._search_time_boundary_finished(1)
        assert window.analysis_session.ridge_search_region.time_end_s == pytest.approx(
            stft.time_s[-5]
        )

        view._search_lines[0].setPos(float(stft.frequency_hz[15]) * 1.0e-9)
        view._search_boundary_finished(0)
        assert (
            window.analysis_session.ridge_search_region.frequency_min_hz
            == pytest.approx(stft.frequency_hz[15])
        )

        view._search_lines[1].setPos(float(stft.frequency_hz[500]) * 1.0e-9)
        view._search_boundary_finished(1)
        region = window.analysis_session.ridge_search_region
        assert region is not None
        assert region.frequency_max_hz == pytest.approx(stft.frequency_hz[500])
        assert window.ridge_time_start_spin.value() * 1.0e-6 == pytest.approx(
            region.time_start_s
        )
        assert window.minimum_frequency_spin.value() * 1.0e9 == pytest.approx(
            region.frequency_min_hz
        )

        before = region
        window.ridge_time_start_spin.setValue(region.time_end_s * 1.0e6)
        qapp.processEvents()
        assert window.analysis_session.ridge_search_region == before
        window.minimum_frequency_spin.setValue(region.frequency_max_hz * 1.0e-9)
        qapp.processEvents()
        assert window.analysis_session.ridge_search_region == before
    finally:
        window.close()


def test_region_change_preserves_stft_and_stales_results(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_event_result(tmp_path))
        _wait_for_analysis(window, window.action_full_automatic.trigger)
        stft = next(iter(window.analysis_session.stft_results.values()))
        region = window.analysis_session.ridge_search_region
        assert region is not None
        grid = stft.frequency_hz
        new_minimum = float(grid[np.searchsorted(grid, region.frequency_min_hz) + 1])
        window.minimum_frequency_spin.setValue(new_minimum * 1.0e-9)
        qapp.processEvents()
        assert window.analysis_session.stft_valid
        assert next(iter(window.analysis_session.stft_results.values())) is stft
        assert not window.analysis_session.automatic_results_available
        assert window.workflow_state is WorkflowState.STFT_READY
        assert not window.action_export.isEnabled()
    finally:
        window.close()
