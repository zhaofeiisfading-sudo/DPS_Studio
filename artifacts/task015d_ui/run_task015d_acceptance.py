"""Run TASK-015D real-data GUI acceptance from explicit input paths."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont

from dps_studio.core import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.workflow import ChannelAnalysis, load_workflow_config
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.preset_repository import CUSTOM_PRESET_ID
from dps_studio.gui.state import WorkflowState


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _run(window: MainWindow) -> dict[str, ChannelAnalysis]:
    loop = QEventLoop()
    failures: list[str] = []
    timed_out = {"value": False}

    def finished(_value: object) -> None:
        loop.quit()

    def failed(
        _generation: int,
        error_type: str,
        message: str,
        _traceback: str,
    ) -> None:
        failures.append(f"{error_type}: {message}")
        loop.quit()

    def timeout() -> None:
        timed_out["value"] = True
        loop.quit()

    window._analysis_adapter.finished.connect(finished)
    window._analysis_adapter.failed.connect(failed)
    if not window.run_automatic_analysis():
        raise RuntimeError(window.analysis_status_label.text())
    QTimer.singleShot(120_000, timeout)
    loop.exec()
    window._analysis_adapter.finished.disconnect(finished)
    window._analysis_adapter.failed.disconnect(failed)
    if timed_out["value"]:
        raise TimeoutError("GUI analysis did not finish within 120 seconds.")
    if failures:
        raise RuntimeError(failures[-1])
    if window.workflow_state is not WorkflowState.RESULT_READY:
        raise RuntimeError("GUI analysis did not reach RESULT_READY.")
    return dict(window.analysis_session.channel_analyses)


def _save(window: MainWindow, path: Path) -> None:
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Could not save {path}.")


def _metadata(analyses: dict[str, ChannelAnalysis]) -> dict[str, dict[str, object]]:
    return {
        channel_name: {
            "window_name": analysis.stft_result.window_name,
            "window_length_samples": analysis.stft_result.window_length_samples,
            "overlap_samples": analysis.stft_result.overlap_samples,
            "hop_samples": analysis.stft_result.hop_samples,
            "nfft": analysis.stft_result.nfft,
            "minimum_frequency_hz": analysis.ridge_result.minimum_frequency_hz,
            "maximum_frequency_hz": analysis.ridge_result.maximum_frequency_hz,
            "vacuum_wavelength_m": (
                analysis.discrete_velocity_result.vacuum_wavelength_m
            ),
        }
        for channel_name, analysis in analyses.items()
    }


def _assert_display_semantics(analyses: dict[str, ChannelAnalysis]) -> None:
    for analysis in analyses.values():
        np.testing.assert_array_equal(
            analysis.display_velocity_m_s,
            analysis.signal_detection_result.apparent_velocity_m_s,
        )


def main() -> int:
    arguments = _arguments()
    config_path = arguments.config.resolve()
    data_path = arguments.data.resolve()
    output_root = arguments.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    raw_hash_before = hashlib.sha256(data_path.read_bytes()).hexdigest()
    configuration = load_workflow_config(
        config_path,
        repository_root=config_path.parents[1],
    )
    loaded = read_delimited_signals(
        data_path,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    )

    application = create_application([], language_code="zh_CN")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow(translation_manager=translation_manager())
    window.set_analysis_configuration(configuration)
    window.set_loaded_result(loaded)
    window.resize(1440, 900)
    window.show()
    application.processEvents()

    if window.profile_combo.currentData() is not BALANCED_PROFILE:
        raise RuntimeError("Balanced was not selected from the real configuration.")
    balanced = _run(window)
    _assert_display_semantics(balanced)
    balanced_spectrum = {
        channel_name: analysis.stft_result.spectrum.copy()
        for channel_name, analysis in balanced.items()
    }
    balanced_formal = {
        channel_name: analysis.signal_detection_result.apparent_velocity_m_s.copy()
        for channel_name, analysis in balanced.items()
    }
    window.workflow_navigation.setCurrentRow(2)
    window.science_tabs.setCurrentIndex(1)
    application.processEvents()
    _save(window, output_root / "balanced_unchanged.png")

    window.nfft_spin.setValue(8192)
    application.processEvents()
    run_configuration = window.analysis_session.run_configuration
    if (
        window.profile_combo.currentData() != CUSTOM_PRESET_ID
        or run_configuration is None
        or run_configuration.base_profile is not BALANCED_PROFILE
        or dict(run_configuration.custom_overrides) != {"nfft": 8192}
    ):
        raise RuntimeError("The GUI did not create Custom based on Balanced.")
    custom = _run(window)
    _assert_display_semantics(custom)
    for analysis in custom.values():
        if analysis.stft_result.nfft != 8192:
            raise RuntimeError("Custom nfft did not reach STFT metadata.")
        if analysis.stft_result.window_length_samples != 768:
            raise RuntimeError("Unchanged Balanced window was not retained.")
    window.workflow_navigation.setCurrentRow(2)
    window.science_tabs.setCurrentIndex(1)
    application.processEvents()
    _save(window, output_root / "custom_based_on_balanced.png")

    window.restore_preset_button.click()
    application.processEvents()
    restored_configuration = window.analysis_session.run_configuration
    if (
        restored_configuration is None
        or restored_configuration.profile is not BALANCED_PROFILE
        or restored_configuration.custom_status
    ):
        raise RuntimeError("Restore Preset Values did not restore Balanced.")
    restored = _run(window)
    _assert_display_semantics(restored)
    for channel_name, analysis in restored.items():
        np.testing.assert_array_equal(
            analysis.stft_result.spectrum,
            balanced_spectrum[channel_name],
        )
        np.testing.assert_array_equal(
            analysis.signal_detection_result.apparent_velocity_m_s,
            balanced_formal[channel_name],
        )
    window.workflow_navigation.setCurrentRow(2)
    window.science_tabs.setCurrentIndex(1)
    application.processEvents()
    _save(window, output_root / "restored_balanced.png")

    high_index = window.profile_combo.findData(HIGH_TIME_RESOLUTION_PROFILE)
    window.profile_combo.setCurrentIndex(high_index)
    application.processEvents()
    high = _run(window)
    _assert_display_semantics(high)
    for analysis in high.values():
        if analysis.stft_result.window_length_samples != 512:
            raise RuntimeError("High time resolution window metadata is incorrect.")
        if analysis.stft_result.overlap_samples != 384:
            raise RuntimeError("High time resolution overlap metadata is incorrect.")
        if analysis.stft_result.nfft != 4096:
            raise RuntimeError("High time resolution nfft metadata is incorrect.")
    window.workflow_navigation.setCurrentRow(2)
    window.science_tabs.setCurrentIndex(1)
    application.processEvents()
    _save(window, output_root / "high_time_resolution.png")

    window.nfft_spin.setValue(511)
    application.processEvents()
    if window.nfft_spin.value() != 511:
        raise RuntimeError("Invalid nfft was silently corrected.")
    if window.run_analysis_button.isEnabled():
        raise RuntimeError("Invalid nfft did not disable automatic analysis.")
    if window.parameter_error_label.isHidden():
        raise RuntimeError("Invalid nfft did not expose the validation error.")
    _save(window, output_root / "invalid_parameters_blocked.png")

    raw_hash_after = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if raw_hash_after != raw_hash_before:
        raise RuntimeError("The raw source hash changed during acceptance.")
    summary = {
        "source": str(data_path),
        "source_sha256": raw_hash_after.upper(),
        "balanced": _metadata(balanced),
        "custom_based_on_balanced": _metadata(custom),
        "restored_balanced": _metadata(restored),
        "high_time_resolution": _metadata(high),
        "balanced_restored_exactly": True,
        "formal_display_semantics_unchanged": True,
        "invalid_nfft_preserved_and_blocked": 511,
    }
    (output_root / "acceptance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    window.close()
    application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
