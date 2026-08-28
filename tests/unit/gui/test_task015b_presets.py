from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from dps_studio.core import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.workflow import analyze_configuration, analyze_profile
from dps_studio.gui.advanced_parameters_dialog import AdvancedParametersDialog
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.preset_repository import CUSTOM_PRESET_ID, PresetRepository
from dps_studio.gui.state import WorkflowState
from dps_studio.runtime_paths import application_resource_root


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_main_window_requests_the_application_resource_root(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dps_studio.gui.main_window as main_window_module

    expected = application_resource_root()
    calls: list[object] = []
    monkeypatch.setattr(
        main_window_module,
        "application_resource_root",
        lambda: calls.append(object()) or expected,
    )

    window = main_window_module.MainWindow()
    try:
        assert calls
        assert window._repository_root == expected
        assert window.analysis_session.run_configuration is not None
    finally:
        window.close()
        qapp.processEvents()


def _load_result(
    tmp_path: Path,
    *,
    sample_count: int = 4096,
    start_time_s: float = 1.0e-6,
    sample_interval_s: float = 1.0e-10,
) -> DelimitedSignalLoadResult:
    time_s = start_time_s + np.arange(sample_count) * sample_interval_s
    phase = 2.0 * np.pi * 0.5e9 * (time_s - time_s[0])
    records = {
        "pdv_channel_1": SignalRecord(time_s, np.sin(phase)),
        "pdv_channel_2": SignalRecord(time_s, 0.7 * np.sin(phase + 0.2)),
    }
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "user_selected.csv",
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


def test_startup_loads_traceable_balanced_defaults_without_data(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.workflow_state is WorkflowState.EMPTY
        assert window.profile_combo.currentData() is BALANCED_PROFILE
        assert window.profile_combo.currentText() == "平衡"
        assert window.profile_combo.count() == 5
        assert window.profile_combo.findData(CUSTOM_PRESET_ID) == -1
        assert window.vacuum_wavelength_spin.value() == pytest.approx(1550.0)
        assert window.analysis_session.run_configuration is not None
        assert window.analysis_session.run_configuration.vacuum_wavelength_m == (
            pytest.approx(1.55e-6)
        )
        assert window.window_length_spin.value() == (
            BALANCED_PROFILE.window_length_samples
        )
        assert window.overlap_spin.value() == BALANCED_PROFILE.overlap_samples
        assert window.nfft_spin.value() == BALANCED_PROFILE.nfft
        assert window.minimum_frequency_spin.value() == pytest.approx(
            BALANCED_PROFILE.minimum_frequency_hz * 1e-9
        )
        assert window.maximum_frequency_spin.value() == pytest.approx(
            BALANCED_PROFILE.maximum_frequency_hz * 1e-9
        )
        assert not window.run_analysis_button.isEnabled()
        assert window.run_analysis_button.toolTip() == "请先导入实验数据。"
        assert window.action_automatic in window.main_toolbar.actions()
        assert window.action_automatic in window.analysis_menu.actions()
        assert not hasattr(window, "load_config_button")
        assert not hasattr(window, "wavelength_confirm_check")
    finally:
        window.close()
        qapp.processEvents()


def test_editing_selected_preset_creates_custom_based_on_that_preset(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert not window.window_length_spin.isReadOnly()
        window.profile_combo.setCurrentIndex(1)
        qapp.processEvents()
        assert window.profile_combo.currentData() is HIGH_TIME_RESOLUTION_PROFILE
        assert window.window_length_spin.value() == (
            HIGH_TIME_RESOLUTION_PROFILE.window_length_samples
        )
        assert window.overlap_spin.value() == (
            HIGH_TIME_RESOLUTION_PROFILE.overlap_samples
        )
        assert window.hop_label.text().startswith(
            str(HIGH_TIME_RESOLUTION_PROFILE.hop_samples)
        )
        assert not window.window_length_spin.isReadOnly()
        window.nfft_spin.setValue(8192)
        qapp.processEvents()
        assert window.profile_combo.currentData() == CUSTOM_PRESET_ID
        assert window.profile_combo.currentText() == "自定义（基于 高时间分辨率）"
        run_configuration = window.analysis_session.run_configuration
        assert run_configuration is not None
        assert run_configuration.profile is None
        assert run_configuration.parameters.is_custom
        assert run_configuration.base_profile is HIGH_TIME_RESOLUTION_PROFILE
        assert run_configuration.parameters.nfft == 8192

        balanced_index = window.profile_combo.findData(BALANCED_PROFILE)
        assert balanced_index >= 0
        window.profile_combo.setCurrentIndex(balanced_index)
        qapp.processEvents()
        restored = window.analysis_session.run_configuration
        assert restored is not None
        assert restored.profile is BALANCED_PROFILE
        assert not restored.custom_status
        assert window.nfft_spin.value() == BALANCED_PROFILE.nfft
    finally:
        window.close()
        qapp.processEvents()


def test_data_import_builds_common_range_and_enables_shared_action(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    result = _load_result(tmp_path)
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(result)
        qapp.processEvents()
        assert window.workflow_state is WorkflowState.RANGE_DEFINED
        assert window.analysis_session.analysis_range is not None
        assert window.analysis_session.analysis_range.start_time_s == pytest.approx(
            result.records["pdv_channel_1"].start_time_s
        )
        assert window.analysis_session.analysis_range.end_time_s == pytest.approx(
            result.records["pdv_channel_1"].end_time_s
        )
        assert window.action_automatic.isEnabled()
        assert window.run_analysis_button.isEnabled()
        assert window.action_run_stft.isEnabled()
        assert window.action_automatic.toolTip() == (
            window.run_analysis_button.toolTip()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_configured_range_wins_only_when_fully_inside_data(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    result = _load_result(tmp_path)
    repository = PresetRepository.load_default(repository_root=REPOSITORY_ROOT)
    start = result.records["pdv_channel_1"].start_time_s + 10e-9
    end = start + 50e-9
    analysis = replace(
        repository.configuration.analysis,
        analysis_start_time_s=start,
        analysis_end_time_s=end,
    )
    configuration = replace(repository.configuration, analysis=analysis)
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_analysis_configuration(configuration)
        window.set_loaded_result(result)
        assert window.analysis_session.analysis_range is not None
        assert window.analysis_session.analysis_range.start_time_s == pytest.approx(start)
        assert window.analysis_session.analysis_range.end_time_s == pytest.approx(end)
    finally:
        window.close()
        qapp.processEvents()


def test_invalid_custom_parameters_block_analysis_with_reason(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load_result(tmp_path))
        window.overlap_spin.setValue(window.window_length_spin.value())
        qapp.processEvents()
        assert not window.run_analysis_button.isEnabled()
        assert not window.action_automatic.isEnabled()
        assert "hop_samples" in window.run_analysis_button.toolTip()

        window.overlap_spin.setValue(BALANCED_PROFILE.overlap_samples)
        window.maximum_frequency_spin.setValue(6.0)
        qapp.processEvents()
        assert window.maximum_frequency_spin.value() == pytest.approx(5.0)
        assert window.run_analysis_button.isEnabled()
    finally:
        window.close()
        qapp.processEvents()


def test_advanced_dialog_groups_only_real_parameter_categories(
    qapp: QApplication,
) -> None:
    repository = PresetRepository.load_default(repository_root=REPOSITORY_ROOT)
    window = MainWindow(translation_manager=translation_manager())
    try:
        run_configuration = window.analysis_session.run_configuration
        assert run_configuration is not None
        dialog = AdvancedParametersDialog(
            run_configuration,
            repository.configuration,
            window,
        )
        tabs = dialog.findChild(QTabWidget, "advancedParameterTabs")
        assert tabs is not None
        assert [tabs.tabText(index) for index in range(tabs.count())] == [
            "STFT",
            "脊线",
            "信号检测",
            "质量",
            "显示",
        ]
        dialog.close()
    finally:
        window.close()
        qapp.processEvents()


def test_main_window_does_not_duplicate_formal_profile_numbers() -> None:
    source = (
        REPOSITORY_ROOT / "src" / "dps_studio" / "gui" / "main_window.py"
    ).read_text(encoding="utf-8")
    assert "window_length_samples=768" not in source
    assert "overlap_samples=640" not in source
    assert "nfft=4096" not in source
    assert "1.55e-6" not in source
    assert "from scripts" not in source
    assert "import scripts" not in source


@pytest.mark.parametrize(
    "profile",
    [BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE],
)
def test_explicit_public_parameters_preserve_profile_numerics(
    profile: AnalysisProfile,
) -> None:
    formal_profile = profile
    sample_count = 3072
    time_s = np.arange(sample_count, dtype=np.float64) * 25e-12
    phase = 2.0 * np.pi * 0.65e9 * time_s
    record = SignalRecord(time_s, np.sin(phase))
    by_profile = analyze_profile(
        {"pdv": record},
        profile=formal_profile,
        vacuum_wavelength_m=1.55e-6,
    )["pdv"]
    by_values = analyze_configuration(
        {"pdv": record},
        window_length_samples=formal_profile.window_length_samples,
        overlap_samples=formal_profile.overlap_samples,
        nfft=formal_profile.nfft,
        window_name=formal_profile.window_name,
        minimum_frequency_hz=formal_profile.minimum_frequency_hz,
        maximum_frequency_hz=formal_profile.maximum_frequency_hz,
        vacuum_wavelength_m=1.55e-6,
        profile_name=formal_profile.profile_id.value,
    )["pdv"]
    np.testing.assert_array_equal(
        by_values.stft_result.time_s,
        by_profile.stft_result.time_s,
    )
    np.testing.assert_array_equal(
        by_values.stft_result.frequency_hz,
        by_profile.stft_result.frequency_hz,
    )
    np.testing.assert_array_equal(
        by_values.stft_result.spectrum,
        by_profile.stft_result.spectrum,
    )
    np.testing.assert_array_equal(
        by_values.refined_result.refined_frequency_hz,
        by_profile.refined_result.refined_frequency_hz,
    )
    np.testing.assert_array_equal(
        by_values.signal_detection_result.apparent_velocity_m_s,
        by_profile.signal_detection_result.apparent_velocity_m_s,
    )
    np.testing.assert_array_equal(
        by_values.display_velocity_m_s,
        by_profile.display_velocity_m_s,
    )
