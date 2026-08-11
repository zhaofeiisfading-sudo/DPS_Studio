from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import AutomaticRidgeExtractionMode
from dps_studio.core.workflow import analyze_configuration
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow


def _load_result(tmp_path: Path) -> DelimitedSignalLoadResult:
    sample_rate_hz = 5.0e9
    sample_count = 2048
    time_s = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    records = {
        "pdv_channel_1": SignalRecord(
            time_s,
            np.sin(2.0 * np.pi * 200.0e6 * time_s),
        ),
        "pdv_channel_2": SignalRecord(
            time_s,
            np.sin(2.0 * np.pi * 240.0e6 * time_s),
        ),
    }
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "task018c.csv",
        records=records,
        row_count=sample_count,
        column_count=3,
        channel_names=tuple(records),
        header=None,
        time_column_index=0,
        voltage_column_indices={"pdv_channel_1": 1, "pdv_channel_2": 2},
        unselected_column_indices=(),
        delimiter=",",
        encoding="utf-8",
    )


def _accept_current_results(window: MainWindow) -> None:
    session = window.analysis_session
    configuration = session.run_configuration
    analysis_range = session.analysis_range
    assert configuration is not None
    assert analysis_range is not None
    parameters = configuration.parameters
    analyses = analyze_configuration(
        session.records,
        window_length_samples=parameters.window_length_samples,
        overlap_samples=parameters.overlap_samples,
        nfft=parameters.nfft,
        window_name=parameters.window_name,
        minimum_frequency_hz=parameters.minimum_frequency_hz,
        maximum_frequency_hz=parameters.maximum_frequency_hz,
        analysis_start_time_s=analysis_range.start_time_s,
        analysis_end_time_s=analysis_range.end_time_s,
        vacuum_wavelength_m=configuration.vacuum_wavelength_m,
        detection_config=configuration.detection_config,
        event_candidate_config=configuration.event_candidate_config,
        automatic_ridge_selection_config=(
            configuration.automatic_ridge_selection_config
        ),
    )
    assert session.accept_results(
        generation_id=session.generation_id,
        analyses=analyses,
    )


def test_default_and_available_window_and_automatic_modes(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.window_name_combo.currentData() == "hann"
        assert [
            window.window_name_combo.itemData(index)
            for index in range(window.window_name_combo.count())
        ] == ["hann", "hamming", "blackman", "blackmanharris", "boxcar"]
        assert window.automatic_ridge_extraction_combo.currentData() == (
            AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED.value
        )
        assert [
            window.automatic_ridge_extraction_combo.itemData(index)
            for index in range(window.automatic_ridge_extraction_combo.count())
        ] == [
            AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED.value,
            AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK.value,
        ]
    finally:
        window.close()
        qapp.processEvents()


def test_window_change_invalidates_stft_guided_and_all_downstream_results(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load_result(tmp_path))
        _accept_current_results(window)
        session = window.analysis_session
        assert session.stft_valid and session.results_valid
        blackman_harris_index = window.window_name_combo.findData(
            "blackmanharris"
        )
        window.window_name_combo.setCurrentIndex(blackman_harris_index)
        qapp.processEvents()

        assert session.run_configuration is not None
        assert session.run_configuration.parameters.window_name == "blackmanharris"
        assert not session.stft_valid
        assert not session.results_valid
        assert not session.guided_results_valid
        assert not session.channel_analyses
        assert not session.guided_channel_analyses
    finally:
        window.close()
        qapp.processEvents()


def test_profile_change_restores_hann_after_explicit_window_override(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.window_name_combo.setCurrentIndex(
            window.window_name_combo.findData("hamming")
        )
        qapp.processEvents()
        assert window.analysis_session.run_configuration is not None
        assert (
            window.analysis_session.run_configuration.parameters.window_name
            == "hamming"
        )
        high_time_index = next(
            index
            for index in range(window.profile_combo.count())
            if getattr(window.profile_combo.itemData(index), "profile_id", None)
            is not None
            and window.profile_combo.itemData(index).profile_id.value
            == "high_time_resolution"
        )
        window.profile_combo.setCurrentIndex(high_time_index)
        qapp.processEvents()
        assert window.window_name_combo.currentData() == "hann"
        assert window.analysis_session.run_configuration.parameters.window_name == "hann"
    finally:
        window.close()
        qapp.processEvents()


def test_automatic_mode_change_preserves_stft_but_invalidates_downstream(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load_result(tmp_path))
        _accept_current_results(window)
        session = window.analysis_session
        stft_before = session.stft_results
        legacy_index = window.automatic_ridge_extraction_combo.findData(
            AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK.value
        )
        window.automatic_ridge_extraction_combo.setCurrentIndex(legacy_index)
        qapp.processEvents()

        assert session.run_configuration is not None
        assert session.run_configuration.automatic_ridge_selection_config.mode is (
            AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK
        )
        assert session.stft_valid
        assert session.stft_results is stft_before
        assert not session.results_valid
        assert not session.channel_analyses
        assert not session.guided_results_valid
    finally:
        window.close()
        qapp.processEvents()
