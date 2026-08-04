"""Generate TASK-016R2 real-data validation metrics and native Qt evidence.

Run this module manually from the repository root.  It reads ``data/raw`` only,
writes generated evidence only below ``artifacts/task016r2``, and verifies the
raw-file SHA-256 digests before and after the acceptance run.
"""

from __future__ import annotations

import gc
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import (
    analyze_stft_results,
    compute_profile_stfts,
    load_workflow_config,
)
from dps_studio.gui.analysis_session import RidgeExtractionMode
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RAW_DIRECTORY = REPOSITORY_ROOT / "data" / "raw"
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task016r2"
EXPECTED_PROFILE_PARAMETERS = {
    "very_high_time_resolution_experimental": (256, 128, 128, 4096),
    "high_time_resolution": (512, 384, 128, 4096),
    "balanced": (768, 640, 128, 4096),
    "high_frequency_resolution": (1024, 896, 128, 4096),
    "very_high_frequency_resolution_experimental": (2048, 1920, 128, 4096),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load(path: Path, configuration: object) -> object:
    input_configuration = configuration.input
    return DataImportController().load(
        SignalLoadRequest(
            path=path,
            time_column=input_configuration.time_column,
            channels=tuple(
                ChannelImportSpec(
                    channel_name,
                    column_index,
                    input_configuration.voltage_scales[channel_name],
                )
                for channel_name, column_index in (
                    input_configuration.voltage_columns.items()
                )
            ),
            delimiter=input_configuration.delimiter,
            has_header=input_configuration.has_header,
            encoding=input_configuration.encoding,
            time_scale=input_configuration.time_scale,
        )
    )


def _analyze_stft(
    configuration: object,
    profile: AnalysisProfile,
    stft_results: Mapping[str, object],
) -> Mapping[str, object]:
    start_s = max(float(stft.time_s[0]) for stft in stft_results.values())
    end_s = min(float(stft.time_s[-1]) for stft in stft_results.values())
    return analyze_stft_results(
        stft_results,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
        analysis_start_time_s=start_s,
        analysis_end_time_s=end_s,
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        profile_name=profile.profile_id.value,
        background_guard_window_scale=(
            configuration.quality.background_guard_window_scale
        ),
        minimum_background_bin_count=(
            configuration.quality.minimum_background_bin_count
        ),
    )


def _profile_metrics(
    source: Path,
    loaded: object,
    configuration: object,
    profile: AnalysisProfile,
) -> dict[str, object]:
    expected = EXPECTED_PROFILE_PARAMETERS[profile.profile_id.value]
    actual = (
        profile.window_length_samples,
        profile.overlap_samples,
        profile.hop_samples,
        profile.nfft,
    )
    if actual != expected:
        raise AssertionError(
            f"Profile {profile.profile_id.value} parameters {actual} != {expected}."
        )
    started = time.perf_counter()
    stft_results = compute_profile_stfts(loaded.records, profile=profile)
    analyses = _analyze_stft(configuration, profile, stft_results)
    elapsed_s = time.perf_counter() - started
    channels: dict[str, object] = {}
    for channel_name, analysis in analyses.items():
        stft = analysis.stft_result
        sample_interval_s = float(np.median(np.diff(loaded.records[channel_name].time_s)))
        sample_rate_hz = 1.0 / sample_interval_s
        if stft.hop_samples != profile.hop_samples or stft.nfft != profile.nfft:
            raise AssertionError(f"STFT metadata disagrees with {profile.profile_id.value}.")
        channels[channel_name] = {
            "shape": list(stft.spectrum.shape),
            "frame_count": int(stft.time_s.size),
            "frequency_bin_count": int(stft.frequency_hz.size),
            "frequency_grid_spacing_hz": float(stft.frequency_hz[1] - stft.frequency_hz[0]),
            "sample_rate_hz": sample_rate_hz,
            "window": stft.window_name,
            "window_length_samples": stft.window_length_samples,
            "overlap_samples": stft.overlap_samples,
            "hop_samples": stft.hop_samples,
            "nfft": stft.nfft,
            "window_duration_s": profile.window_length_samples / sample_rate_hz,
            "finite_window_frequency_scale_hz": sample_rate_hz / profile.window_length_samples,
            "formal_finite_frame_count": int(
                np.count_nonzero(
                    np.isfinite(analysis.signal_detection_result.apparent_velocity_m_s)
                )
            ),
        }
    return {
        "source": source.relative_to(REPOSITORY_ROOT).as_posix(),
        "profile": profile.profile_id.value,
        "parameters": {
            "window_length_samples": profile.window_length_samples,
            "overlap_samples": profile.overlap_samples,
            "hop_samples": profile.hop_samples,
            "nfft": profile.nfft,
            "search_band_hz": [profile.minimum_frequency_hz, profile.maximum_frequency_hz],
        },
        "elapsed_s": elapsed_s,
        "channels": channels,
    }


def _wait(window: MainWindow, launch: Callable[[], bool]) -> None:
    loop = QEventLoop()
    outcome: dict[str, object] = {"timed_out": False, "error": None}

    def timeout() -> None:
        outcome["timed_out"] = True
        loop.quit()

    def failed(
        _generation_id: int,
        error_type: str,
        message: str,
        _traceback_text: str,
    ) -> None:
        outcome["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(90_000, timeout)
    if not launch():
        raise RuntimeError("The GUI rejected an acceptance run.")
    loop.exec()
    if outcome["timed_out"]:
        raise TimeoutError("The GUI run exceeded 90 seconds.")
    if outcome["error"] is not None:
        raise RuntimeError(str(outcome["error"]))
    if window._analysis_adapter.busy:
        raise RuntimeError("The background GUI worker stayed busy.")


def _capture(
    window: MainWindow,
    filename: str,
    *,
    include_popups: bool = False,
) -> dict[str, int | str]:
    application = create_application([])
    application.processEvents()
    if include_popups:
        popup = window.profile_combo.view()
        if not popup.isVisible():
            raise RuntimeError("The native profile popup did not become visible.")
        image = popup.grab()
    else:
        image = window.grab()
    path = OUTPUT_DIRECTORY / filename
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {path}")
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "width_px": image.width(),
        "height_px": image.height(),
    }


def _create_corridor(
    window: MainWindow,
    channel_name: str,
    frequency_offset_hz: float,
) -> RidgeCorridorConstraint:
    stft = window.analysis_session.stft_results[channel_name]
    fractions = (0.12, 0.30, 0.50, 0.68, 0.86)
    indices = [int(stft.time_s.size * fraction) for fraction in fractions]
    return RidgeCorridorConstraint(
        control_times_s=np.asarray([stft.time_s[index] for index in indices]),
        control_frequencies_hz=(
            np.asarray([0.10, 0.73, 0.72, 0.30, 0.85]) * 1.0e9
            + frequency_offset_hz
        ),
        half_width_hz=70.0e6,
    )


def _select_spectrogram_channel(window: MainWindow, channel_name: str) -> None:
    selector = window.spectrogram_view.channel_combo
    index = selector.findData(channel_name)
    if index < 0:
        raise RuntimeError(f"No STFT channel selector entry for {channel_name}.")
    selector.setCurrentIndex(index)


def _select_result_source(combo: object, source: str) -> None:
    index = combo.findData(source)  # type: ignore[attr-defined]
    if index < 0:
        raise RuntimeError(f"Result source is unavailable: {source}")
    combo.setCurrentIndex(index)  # type: ignore[attr-defined]


def _gui_acceptance(
    application: object,
    loaded: object,
    configuration: object,
) -> tuple[dict[str, object], list[dict[str, int | str]]]:
    settings = QSettings(
        str(OUTPUT_DIRECTORY / "task016r2_acceptance.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    window = MainWindow(translation_manager=translation_manager(), settings=settings)
    screenshots: list[dict[str, int | str]] = []
    try:
        window.resize(1440, 900)
        window.show()
        window.set_loaded_result(loaded)
        window.set_analysis_configuration(configuration)
        window.analysis_range_panel.use_full_range()
        application.processEvents()
        _wait(window, window.run_stft_analysis)

        window.select_workflow_step(2)
        application.processEvents()
        window.profile_combo.showPopup()
        application.processEvents()
        screenshots.append(
            _capture(window, "five_presets_zh.png", include_popups=True)
        )
        window.profile_combo.hidePopup()

        window.select_workflow_step(3)
        window.automatic_mode_radio.click()
        application.processEvents()
        if window.ridge_extraction_mode is not RidgeExtractionMode.AUTOMATIC:
            raise AssertionError("Automatic radio did not select AUTOMATIC mode.")
        screenshots.append(_capture(window, "mode_automatic_zh.png"))

        window.guided_mode_radio.click()
        application.processEvents()
        if window.ridge_extraction_mode is not RidgeExtractionMode.GUIDED:
            raise AssertionError("Guided radio did not select GUIDED mode.")
        screenshots.append(_capture(window, "mode_guided_zh.png"))

        session = window.analysis_session
        stft_ch1 = session.stft_results["pdv_channel_1"]
        session.set_event_reference_time_s(float(stft_ch1.time_s[stft_ch1.time_s.size // 2]))
        session.set_display_velocity_configuration(
            enabled=True,
            pre_event_display_velocity_m_s=0.0,
        )
        corridor_ch1 = _create_corridor(window, "pdv_channel_1", 0.0)
        window._ridge_constraint_changed("pdv_channel_1", corridor_ch1)
        application.processEvents()
        screenshots.append(_capture(window, "guided_channel1_corridor_zh.png"))
        _wait(window, window.run_guided_analysis)
        if set(session.valid_guided_channel_analyses) != {"pdv_channel_1"}:
            raise AssertionError("First Guided run did not retain its channel-local result.")
        if session.automatic_results_available:
            raise AssertionError("Guided-only acceptance unexpectedly produced Automatic data.")
        if window.workflow_state is not WorkflowState.RESULT_READY:
            raise AssertionError("Guided-only formal result did not unlock result pages.")

        _select_spectrogram_channel(window, "pdv_channel_2")
        corridor_ch2 = _create_corridor(window, "pdv_channel_2", 0.0)
        window._ridge_constraint_changed("pdv_channel_2", corridor_ch2)
        application.processEvents()
        screenshots.append(_capture(window, "guided_channel2_corridor_zh.png"))
        _wait(window, window.run_guided_analysis)
        if set(session.valid_guided_channel_analyses) != {
            "pdv_channel_1",
            "pdv_channel_2",
        }:
            raise AssertionError("Second Guided run replaced an independent result.")
        if not window.science_tabs.isTabEnabled(3) or not window.science_tabs.isTabEnabled(4):
            raise AssertionError("Guided-only result did not enable Velocity and Comparison.")

        window.science_tabs.setCurrentWidget(window.velocity_view)
        _select_result_source(window.velocity_view.result_source_combo, "guided")
        velocity_channel_index = window.velocity_view.channel_combo.findData(
            "pdv_channel_2"
        )
        if velocity_channel_index < 0:
            raise RuntimeError("Guided Velocity lacks the second loaded channel.")
        window.velocity_view.channel_combo.setCurrentIndex(velocity_channel_index)
        window.velocity_view.display_velocity_check.setChecked(True)
        application.processEvents()
        screenshots.append(_capture(window, "guided_only_velocity_zh.png"))

        analysis = session.valid_guided_channel_analyses["pdv_channel_2"]
        formal_before = analysis.signal_detection_result.apparent_velocity_m_s.copy()
        connector = window.velocity_view.display_connector
        if connector is None:
            raise AssertionError("Display-only pre-event connector was not drawn.")
        connector_time_us, connector_velocity_m_s = connector.getData()
        if connector_time_us.size != 2 or connector_velocity_m_s.size != 2:
            raise AssertionError("Display-only connector must contain exactly two points.")
        finite_after_reference = np.flatnonzero(
            np.isfinite(analysis.signal_detection_result.apparent_velocity_m_s)
            & (analysis.stft_result.time_s >= session.event_reference_time_s)
        )
        if finite_after_reference.size == 0:
            raise AssertionError("No formal Guided velocity exists after the selected reference.")
        first = int(finite_after_reference[0])
        if not np.isclose(connector_time_us[0], session.event_reference_time_s * 1.0e6):
            raise AssertionError("Connector point A does not use the event reference time.")
        if not np.isclose(connector_time_us[1], analysis.stft_result.time_s[first] * 1.0e6):
            raise AssertionError("Connector point B is not the first formal Guided point.")
        if not np.isclose(
            connector_velocity_m_s[1],
            analysis.signal_detection_result.apparent_velocity_m_s[first],
        ):
            raise AssertionError("Connector point B does not use the formal velocity.")
        np.testing.assert_array_equal(
            analysis.signal_detection_result.apparent_velocity_m_s,
            formal_before,
        )
        connector_center_us = float(np.mean(connector_time_us))
        connector_minimum_m_s = float(np.min(connector_velocity_m_s))
        connector_maximum_m_s = float(np.max(connector_velocity_m_s))
        window.velocity_view.plot_widget.setXRange(
            connector_center_us - 0.025,
            connector_center_us + 0.025,
            padding=0.0,
        )
        window.velocity_view.plot_widget.setYRange(
            connector_minimum_m_s - 4.0,
            connector_maximum_m_s + 4.0,
            padding=0.0,
        )
        application.processEvents()
        screenshots.append(_capture(window, "pre_event_display_connector_zh.png"))
        window.velocity_view.display_velocity_check.setChecked(False)
        application.processEvents()
        if window.velocity_view.display_connector is not None:
            raise AssertionError("Connector remained after display-only rendering was disabled.")
        np.testing.assert_array_equal(
            analysis.signal_detection_result.apparent_velocity_m_s,
            formal_before,
        )

        window.science_tabs.setCurrentWidget(window.comparison_view)
        application.processEvents()
        screenshots.append(_capture(window, "guided_only_comparison_zh.png"))
        if window.comparison_view.notice.text():
            raise AssertionError("Comparison showed a one-result notice for two Guided channels.")

        return (
            {
                "qt_platform": application.platformName(),
                "mode_switches": {
                    "automatic_mode": window.automatic_mode_radio.isChecked(),
                    "guided_mode": window.guided_mode_radio.isChecked(),
                    "session_mode": window.ridge_extraction_mode.value,
                },
                "guided_valid_channels": list(session.valid_guided_channel_analyses),
                "automatic_results_available": session.automatic_results_available,
                "workflow_state": window.workflow_state.name,
                "velocity_source": window.velocity_view.result_source,
                "velocity_channel_selector_count": window.velocity_view.channel_combo.count(),
                "comparison_series_count": len(window.comparison_view.curves),
                "connector_points": {
                    "time_us": connector_time_us.tolist(),
                    "velocity_m_s": connector_velocity_m_s.tolist(),
                    "formal_array_unchanged": True,
                    "hidden_when_display_disabled": True,
                },
            },
            screenshots,
        )
    finally:
        window.close()
        application.processEvents()


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    raw_paths = sorted(RAW_DIRECTORY.glob("*.csv"))
    if len(raw_paths) != 4:
        raise RuntimeError(f"Expected four raw CSV files, found {len(raw_paths)}.")
    hashes_before = {path.name: _sha256(path) for path in raw_paths}
    configuration = load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    if tuple(profile.profile_id.value for profile in configuration.analysis.profiles) != tuple(
        EXPECTED_PROFILE_PARAMETERS
    ):
        raise AssertionError("The five registered profile IDs/order do not match TASK-016R2.")

    profile_runs: list[dict[str, object]] = []
    loaded_first = None
    for source in raw_paths:
        loaded = _load(source, configuration)
        if loaded_first is None:
            loaded_first = loaded
        for profile in configuration.analysis.profiles:
            profile_runs.append(_profile_metrics(source, loaded, configuration, profile))
            gc.collect()
    if loaded_first is None:
        raise RuntimeError("No raw CSV could be loaded.")

    application = create_application(sys.argv, language_code="zh_CN")
    gui_acceptance, screenshots = _gui_acceptance(application, loaded_first, configuration)
    hashes_after = {path.name: _sha256(path) for path in raw_paths}
    if hashes_before != hashes_after:
        raise AssertionError("A raw CSV changed during TASK-016R2 acceptance.")
    summary = {
        "task": "TASK-016R2",
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "raw_hashes_unchanged": True,
        "profile_runs": profile_runs,
        "gui_acceptance": gui_acceptance,
        "screenshots": screenshots,
    }
    summary_path = OUTPUT_DIRECTORY / "acceptance_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
