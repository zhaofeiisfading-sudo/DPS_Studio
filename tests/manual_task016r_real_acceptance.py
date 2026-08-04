"""Generate TASK-016R real-data metrics and screenshots from the actual Qt GUI.

Run manually from the repository root. Outputs are restricted to
``artifacts/task016r``; raw data is read-only and hash-verified.
"""

from __future__ import annotations

import gc
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer

from dps_studio.core.analysis_profiles import (
    AnalysisProfile,
    build_analysis_run_parameters,
)
from dps_studio.core.workflow import (
    analyze_profile,
    analyze_stft_results,
    compute_profile_stfts,
    load_workflow_config,
)
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RAW_DIRECTORY = REPOSITORY_ROOT / "data" / "raw"
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task016r"


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
                    name,
                    column,
                    input_configuration.voltage_scales[name],
                )
                for name, column in input_configuration.voltage_columns.items()
            ),
            delimiter=input_configuration.delimiter,
            has_header=input_configuration.has_header,
            encoding=input_configuration.encoding,
            time_scale=input_configuration.time_scale,
        )
    )


def _post_stft(configuration: object, profile: AnalysisProfile, stft: object) -> object:
    records = stft
    start_s = max(float(value.time_s[0]) for value in records.values())
    end_s = min(float(value.time_s[-1]) for value in records.values())
    return analyze_stft_results(
        records,
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


def _wait(window: MainWindow, launch: Callable[[], bool]) -> None:
    loop = QEventLoop()
    outcome: dict[str, object] = {"timeout": False, "error": None}

    def timeout() -> None:
        outcome["timeout"] = True
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
    QTimer.singleShot(60_000, timeout)
    if not launch():
        raise RuntimeError("The GUI rejected an acceptance run.")
    loop.exec()
    if outcome["timeout"]:
        raise TimeoutError("The GUI run exceeded 60 seconds.")
    if outcome["error"] is not None:
        raise RuntimeError(str(outcome["error"]))


def _capture(window: MainWindow, filename: str) -> dict[str, int | str]:
    application = create_application([])
    application.processEvents()
    image = window.grab()
    path = OUTPUT_DIRECTORY / filename
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {path}")
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "width_px": image.width(),
        "height_px": image.height(),
    }


def _profile_metrics(
    source: Path,
    loaded: object,
    configuration: object,
    profile: AnalysisProfile,
) -> dict[str, object]:
    started = time.perf_counter()
    build_analysis_run_parameters(
        base_profile=profile,
        base_vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
    ).validate_for_records(loaded.records)
    stft = compute_profile_stfts(loaded.records, profile=profile)
    analyses = _post_stft(configuration, profile, stft)
    elapsed_s = time.perf_counter() - started
    channels = {}
    for name, analysis in analyses.items():
        result = analysis.stft_result
        channels[name] = {
            "shape": list(result.spectrum.shape),
            "frame_count": int(result.time_s.size),
            "frequency_bin_count": int(result.frequency_hz.size),
            "frequency_grid_spacing_hz": float(
                result.frequency_hz[1] - result.frequency_hz[0]
            ),
            "window": result.window_name,
            "window_length_samples": result.window_length_samples,
            "overlap_samples": result.overlap_samples,
            "hop_samples": result.hop_samples,
            "nfft": result.nfft,
            "search_band_hz": [
                analysis.ridge_result.minimum_frequency_hz,
                analysis.ridge_result.maximum_frequency_hz,
            ],
            "formal_finite_frame_count": int(
                np.count_nonzero(
                    np.isfinite(
                        analysis.signal_detection_result.apparent_velocity_m_s
                    )
                )
            ),
        }
    return {
        "source": source.relative_to(REPOSITORY_ROOT).as_posix(),
        "profile": profile.profile_id.value,
        "elapsed_s": elapsed_s,
        "channels": channels,
    }


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    raw_paths = sorted(RAW_DIRECTORY.glob("*.csv"))
    hashes_before = {path.name: _sha256(path) for path in raw_paths}
    configuration = load_workflow_config(
        CONFIG_PATH,
        repository_root=REPOSITORY_ROOT,
    )

    profile_runs: list[dict[str, object]] = []
    real_regressions: list[dict[str, object]] = []
    loaded_first = None
    for source in raw_paths:
        loaded = _load(source, configuration)
        if loaded_first is None:
            loaded_first = loaded
        for profile in configuration.analysis.profiles:
            profile_runs.append(
                _profile_metrics(source, loaded, configuration, profile)
            )
            gc.collect()
        if source.name in {"20260607.csv", "20260630-2.csv"}:
            profile = configuration.analysis.default_profile
            staged_stft = compute_profile_stfts(loaded.records, profile=profile)
            staged = _post_stft(configuration, profile, staged_stft)
            one_click = analyze_profile(
                loaded.records,
                profile=profile,
                analysis_start_time_s=max(
                    float(result.time_s[0]) for result in staged_stft.values()
                ),
                analysis_end_time_s=min(
                    float(result.time_s[-1]) for result in staged_stft.values()
                ),
                vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
                detection_config=configuration.quality.signal_detection,
                event_candidate_config=configuration.event_candidate,
                background_guard_window_scale=(
                    configuration.quality.background_guard_window_scale
                ),
                minimum_background_bin_count=(
                    configuration.quality.minimum_background_bin_count
                ),
            )
            identical = all(
                np.array_equal(
                    staged[name].signal_detection_result.apparent_velocity_m_s,
                    one_click[name].signal_detection_result.apparent_velocity_m_s,
                    equal_nan=True,
                )
                for name in staged
            )
            real_regressions.append(
                {"source": source.name, "staged_equals_one_click": identical}
            )
            del staged_stft, staged, one_click
            gc.collect()

    if loaded_first is None:
        raise RuntimeError("No real CSV files were found.")

    startup_started = time.perf_counter()
    application = create_application(sys.argv, language_code="zh_CN")
    settings = QSettings(
        str(OUTPUT_DIRECTORY / "task016r_acceptance.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    window = MainWindow(translation_manager=translation_manager(), settings=settings)
    window.resize(1440, 900)
    window.show()
    application.processEvents()
    startup_to_shown_s = time.perf_counter() - startup_started

    screenshots: list[dict[str, int | str]] = []
    try:
        window.set_loaded_result(loaded_first)
        window.set_analysis_configuration(configuration)
        window.analysis_range_panel.use_full_range()
        _wait(window, window.run_stft_analysis)
        window.select_workflow_step(2)
        window.science_tabs.setCurrentWidget(window.spectrogram_view)
        application.processEvents()
        screenshots.append(_capture(window, "stft_panel_clean_zh.png"))

        window.spectrogram_view.show_full_spectrum()
        application.processEvents()
        screenshots.append(_capture(window, "spectrogram_full_range_zh.png"))
        window.spectrogram_view.fit_search_region()
        application.processEvents()
        screenshots.append(
            _capture(window, "spectrogram_fit_search_region_zh.png")
        )

        stft_identity = id(window.analysis_session.stft_results["pdv_channel_1"])
        _wait(window, window.run_staged_automatic_analysis)
        automatic_identity = id(window.analysis_session.channel_analyses)
        window.guided_mode_radio.click()
        application.processEvents()
        screenshots.append(_capture(window, "ridge_guided_clean_panel_zh.png"))

        stft_result = window.analysis_session.stft_results["pdv_channel_1"]
        indices = np.array(
            [
                int(stft_result.time_s.size * fraction)
                for fraction in (0.12, 0.30, 0.50, 0.68, 0.86)
            ],
            dtype=int,
        )
        frequencies_hz = np.array([0.10, 0.73, 0.72, 0.30, 0.85]) * 1.0e9
        controller = window.spectrogram_view.corridor_controller
        controller.begin_drawing(half_width_hz=70.0e6)
        controller._draft_points = list(
            zip(stft_result.time_s[indices], frequencies_hz)
        )
        controller._refresh_draft()
        controller._commit_live_draft()
        application.processEvents()
        screenshots.append(_capture(window, "corridor_boundaries_zh.png"))
        controller.undo_last_point()
        application.processEvents()
        screenshots.append(_capture(window, "corridor_undo_zh.png"))
        controller._draft_points.append(
            (float(stft_result.time_s[indices[-1]]), float(frequencies_hz[-1]))
        )
        controller._refresh_draft()
        controller._commit_live_draft()

        _wait(window, window.run_guided_analysis)
        window.science_tabs.setCurrentWidget(window.ridge_view)
        guided_index = window.ridge_view.result_source_combo.findData("guided")
        window.ridge_view.result_source_combo.setCurrentIndex(guided_index)
        window.ridge_view.fit_search_region()
        application.processEvents()
        screenshots.append(_capture(window, "guided_local_domain_zh.png"))

        window.science_tabs.setCurrentWidget(window.comparison_view)
        application.processEvents()
        screenshots.append(_capture(window, "automatic_vs_guided_zh.png"))

        window.resize(1280, 720)
        window.select_workflow_step(3)
        window.science_tabs.setCurrentWidget(window.spectrogram_view)
        application.processEvents()
        screenshots.append(_capture(window, "layout_1280x720_zh.png"))

        guided_analysis = window.analysis_session.guided_channel_analyses[
            "pdv_channel_1"
        ]
        constraint = window.analysis_session.ridge_constraints["pdv_channel_1"]
        outside = (
            (guided_analysis.stft_result.time_s < constraint.start_time_s)
            | (guided_analysis.stft_result.time_s > constraint.end_time_s)
        )
        guided_outside_frequency_nan = bool(
            np.isnan(
                guided_analysis.signal_detection_result.refined_frequency_hz[
                    outside
                ]
            ).all()
        )
        guided_outside_velocity_nan = bool(
            np.isnan(
                guided_analysis.signal_detection_result.apparent_velocity_m_s[
                    outside
                ]
            ).all()
        )
        window.clear_corridor_button.click()
        application.processEvents()
        gui_acceptance = {
            "stft_identity_preserved": (
                id(window.analysis_session.stft_results["pdv_channel_1"])
                == stft_identity
            ),
            "automatic_identity_preserved": (
                id(window.analysis_session.channel_analyses) == automatic_identity
            ),
            "guided_outside_frequency_nan": guided_outside_frequency_nan,
            "guided_outside_velocity_nan": guided_outside_velocity_nan,
            "clear_removed_session_constraint": (
                "pdv_channel_1" not in window.analysis_session.ridge_constraints
            ),
            "clear_preserved_stft": window.analysis_session.stft_valid,
            "clear_preserved_automatic": window.analysis_session.results_valid,
        }
    finally:
        window.close()
        application.processEvents()

    hashes_after = {path.name: _sha256(path) for path in raw_paths}
    summary = {
        "task": "TASK-016R",
        "startup_to_main_window_shown_s": startup_to_shown_s,
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "raw_hashes_unchanged": hashes_before == hashes_after,
        "profile_runs": profile_runs,
        "real_staged_regressions": real_regressions,
        "gui_acceptance": gui_acceptance,
        "screenshots": screenshots,
    }
    (OUTPUT_DIRECTORY / "acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
