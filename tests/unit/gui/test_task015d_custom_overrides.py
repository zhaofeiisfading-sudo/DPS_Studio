from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from dps_studio.core import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.workflow import analyze_configuration
from dps_studio.gui.analysis_adapter import AnalysisRequest
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.preset_repository import CUSTOM_PRESET_ID


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _load_result(
    tmp_path: Path,
    *,
    sample_count: int = 4096,
    sample_interval_s: float = 1.0e-10,
) -> DelimitedSignalLoadResult:
    time_s = 1.0e-6 + np.arange(sample_count) * sample_interval_s
    phase = 2.0 * np.pi * 0.65e9 * (time_s - time_s[0])
    records = {
        "pdv_channel_1": SignalRecord(time_s, np.sin(phase)),
        "pdv_channel_2": SignalRecord(time_s, 0.8 * np.sin(phase + 0.3)),
    }
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "selected.csv",
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


def test_balanced_loads_all_fields_with_explicit_unchanged_provenance(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        configuration = window.analysis_session.run_configuration
        assert configuration is not None
        assert configuration.base_profile is BALANCED_PROFILE
        assert configuration.preset_name == "Balanced"
        assert not configuration.custom_status
        assert not configuration.custom_overrides
        assert configuration.final_run_configuration is configuration.parameters
        assert window.vacuum_wavelength_spin.value() == pytest.approx(1550.0)
        assert window.window_name_label.text() == BALANCED_PROFILE.window_name
        assert window.window_length_spin.value() == 768
        assert window.overlap_spin.value() == 640
        assert window.hop_label.text().startswith("128")
        assert window.nfft_spin.value() == 4096
        assert window.minimum_frequency_spin.value() == pytest.approx(0.05)
        assert window.maximum_frequency_spin.value() == pytest.approx(2.0)
    finally:
        window.close()
        qapp.processEvents()


def test_window_and_overlap_edits_create_custom_and_update_derived_hop(
    qapp: QApplication,
) -> None:
    original = (
        BALANCED_PROFILE.window_length_samples,
        BALANCED_PROFILE.overlap_samples,
        BALANCED_PROFILE.hop_samples,
    )
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.window_length_spin.setValue(1024)
        qapp.processEvents()
        configuration = window.analysis_session.run_configuration
        assert configuration is not None
        assert configuration.profile is None
        assert configuration.base_profile is BALANCED_PROFILE
        assert configuration.custom_overrides == {"window_length_samples": 1024}
        assert window.profile_combo.currentData() == CUSTOM_PRESET_ID
        assert window.profile_combo.currentText() == "自定义（基于 平衡）"
        assert window.hop_label.text().startswith("384")

        window.overlap_spin.setValue(768)
        qapp.processEvents()
        configuration = window.analysis_session.run_configuration
        assert configuration is not None
        assert configuration.parameters.hop_samples == 256
        assert configuration.custom_overrides == {
            "window_length_samples": 1024,
            "overlap_samples": 768,
        }
        assert original == (
            BALANCED_PROFILE.window_length_samples,
            BALANCED_PROFILE.overlap_samples,
            BALANCED_PROFILE.hop_samples,
        )
    finally:
        window.close()
        qapp.processEvents()


def test_reselect_and_restore_button_restore_immutable_preset(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.nfft_spin.setValue(8192)
        qapp.processEvents()
        assert window.profile_combo.currentData() == CUSTOM_PRESET_ID
        balanced_index = window.profile_combo.findData(BALANCED_PROFILE)
        assert balanced_index >= 0
        window.profile_combo.setCurrentIndex(balanced_index)
        qapp.processEvents()
        configuration = window.analysis_session.run_configuration
        assert configuration is not None
        assert configuration.profile is BALANCED_PROFILE
        assert window.nfft_spin.value() == BALANCED_PROFILE.nfft

        high_time_index = window.profile_combo.findData(HIGH_TIME_RESOLUTION_PROFILE)
        assert high_time_index >= 0
        window.profile_combo.setCurrentIndex(high_time_index)
        window.window_length_spin.setValue(640)
        qapp.processEvents()
        assert "高时间分辨率" in window.profile_combo.currentText()
        window.restore_preset_button.click()
        qapp.processEvents()
        configuration = window.analysis_session.run_configuration
        assert configuration is not None
        assert configuration.profile is HIGH_TIME_RESOLUTION_PROFILE
        assert window.window_length_spin.value() == 512
        assert window.overlap_spin.value() == 384
        assert window.hop_label.text().startswith("128")
    finally:
        window.close()
        qapp.processEvents()


def test_invalid_nfft_and_search_band_are_not_corrected_and_block_run(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load_result(tmp_path))
        window.nfft_spin.setValue(767)
        qapp.processEvents()
        assert window.nfft_spin.value() == 767
        assert not window.run_analysis_button.isEnabled()
        assert not window.parameter_error_label.isHidden()
        assert "nfft" in window.parameter_error_label.text()
        assert "c62828" in window.nfft_spin.styleSheet()

        window.nfft_spin.setValue(4095)
        window.maximum_frequency_spin.setValue(5.0)
        qapp.processEvents()
        assert window.nfft_spin.value() == 4095
        assert window.maximum_frequency_spin.value() == pytest.approx(5.0)
        assert not window.run_analysis_button.isEnabled()
        assert "STFT/Nyquist" in window.parameter_error_label.text()
    finally:
        window.close()
        qapp.processEvents()


def test_ui_units_and_captured_analysis_request_are_exact(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    captured: list[AnalysisRequest] = []

    def capture(request: AnalysisRequest) -> bool:
        captured.append(request)
        return True

    try:
        window.set_loaded_result(_load_result(tmp_path))
        window.vacuum_wavelength_spin.setValue(1064.0)
        window.window_length_spin.setValue(1024)
        window.overlap_spin.setValue(768)
        window.nfft_spin.setValue(4095)
        window.minimum_frequency_spin.setValue(0.125)
        window.maximum_frequency_spin.setValue(1.75)
        qapp.processEvents()
        monkeypatch.setattr(window._analysis_adapter, "start", capture)
        assert window.run_automatic_analysis()
        assert len(captured) == 1
        request = captured[0]
        final = request.configuration.final_run_configuration
        assert final.vacuum_wavelength_m == pytest.approx(1064.0e-9)
        assert final.window_length_samples == 1024
        assert final.overlap_samples == 768
        assert final.hop_samples == 256
        assert final.nfft == 4095
        assert final.minimum_frequency_hz == pytest.approx(0.125e9)
        assert final.maximum_frequency_hz == pytest.approx(1.75e9)
        assert dict(request.configuration.custom_overrides) == {
            "vacuum_wavelength_m": pytest.approx(1064.0e-9),
            "window_length_samples": 1024,
            "overlap_samples": 768,
            "nfft": 4095,
            "minimum_frequency_hz": pytest.approx(0.125e9),
            "maximum_frequency_hz": pytest.approx(1.75e9),
        }
    finally:
        window.close()
        qapp.processEvents()


def test_scientific_change_invalidates_but_display_only_change_does_not(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load_result(tmp_path))
        initial_generation = window.analysis_session.generation_id
        window.pre_event_display_velocity_spin.setValue(12.5)
        qapp.processEvents()
        assert window.analysis_session.generation_id == initial_generation
        window.vacuum_wavelength_spin.setValue(1551.0)
        qapp.processEvents()
        assert window.analysis_session.generation_id > initial_generation
        assert not window.analysis_session.results_valid
    finally:
        window.close()
        qapp.processEvents()


def test_two_channels_use_one_custom_scientific_configuration_independently() -> None:
    sample_count = 3072
    time_s = np.arange(sample_count, dtype=np.float64) * 25.0e-12
    records = {
        "channel_a": SignalRecord(time_s, np.sin(2.0 * np.pi * 0.6e9 * time_s)),
        "channel_b": SignalRecord(time_s, np.sin(2.0 * np.pi * 0.8e9 * time_s)),
    }
    analyses = analyze_configuration(
        records,
        window_length_samples=1024,
        overlap_samples=768,
        nfft=4095,
        window_name="hann",
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=1.5e9,
        vacuum_wavelength_m=1.064e-6,
        profile_name="custom_based_on_balanced",
    )
    assert tuple(analyses) == ("channel_a", "channel_b")
    assert analyses["channel_a"] is not analyses["channel_b"]
    for result in analyses.values():
        assert result.stft_result.window_length_samples == 1024
        assert result.stft_result.overlap_samples == 768
        assert result.stft_result.hop_samples == 256
        assert result.stft_result.nfft == 4095
        assert result.discrete_velocity_result.vacuum_wavelength_m == pytest.approx(
            1.064e-6
        )


def test_gui_edits_do_not_modify_preset_files_or_import_scripts(
    qapp: QApplication,
) -> None:
    before = hashlib.sha256(DEFAULT_CONFIG.read_bytes()).digest()
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.nfft_spin.setValue(8192)
        qapp.processEvents()
        assert hashlib.sha256(DEFAULT_CONFIG.read_bytes()).digest() == before
        gui_root = REPOSITORY_ROOT / "src" / "dps_studio" / "gui"
        forbidden = re.compile(r"^\s*(?:from|import)\s+scripts\b", re.MULTILINE)
        for source_path in gui_root.glob("*.py"):
            assert forbidden.search(source_path.read_text(encoding="utf-8")) is None
    finally:
        window.close()
        qapp.processEvents()


def test_english_custom_and_restore_labels(qapp: QApplication) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        window.nfft_spin.setValue(8192)
        qapp.processEvents()
        assert window.profile_combo.currentText() == "Custom (based on Balanced)"
        assert window.restore_preset_button.text() == "Restore Preset Values"
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()
