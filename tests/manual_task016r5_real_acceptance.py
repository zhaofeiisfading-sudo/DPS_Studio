"""Generate native Windows Qt evidence for TASK-016R5 with real PDV data.

The script reads two existing ``data/raw`` files without modifying them and
writes only five screenshots plus one compact JSON summary under
``artifacts/task016r5``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer

from dps_studio.core.ridge import (
    ManualFrequencyRegion,
    evaluate_manual_frequency_region_bounds,
    manual_frequency_region_mask,
)
from dps_studio.core.workflow import load_workflow_config
from dps_studio.core.workflow import PRE_EVENT_DISPLAY_ORIGIN
from dps_studio.gui.analysis_adapter import AnalysisResultSource
from dps_studio.gui.analysis_session import EventTimeSource
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"
NORMAL_SOURCE = REPOSITORY_ROOT / "data" / "raw" / "20260607.csv"
COMPLEX_SOURCE = REPOSITORY_ROOT / "data" / "raw" / "20260630-1.csv"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task016r5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _array_sha256(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    return hashlib.sha256(contiguous.tobytes()).hexdigest().upper()


def _load(source_path: Path) -> object:
    configuration = load_workflow_config(
        CONFIG_PATH,
        repository_root=REPOSITORY_ROOT,
    )
    input_configuration = configuration.input
    return DataImportController().load(
        SignalLoadRequest(
            path=source_path,
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


def _wait(
    window: MainWindow,
    launch: Callable[[], bool],
    expected_source: AnalysisResultSource,
) -> None:
    loop = QEventLoop()
    outcome: dict[str, object] = {"timed_out": False, "error": None}

    def completed() -> None:
        loop.quit()

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

    window._analysis_adapter.finished.connect(completed)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(120_000, timeout)
    try:
        if not launch():
            raise RuntimeError("The GUI rejected the acceptance analysis request.")
        if window._pending_analysis_source is not expected_source:
            raise AssertionError("The GUI selected an unexpected worker path.")
        loop.exec()
    finally:
        window._analysis_adapter.finished.disconnect(completed)
        window._analysis_adapter.failed.disconnect(failed)
    if outcome["timed_out"]:
        raise TimeoutError("The native GUI analysis exceeded 120 seconds.")
    if outcome["error"] is not None:
        raise RuntimeError(str(outcome["error"]))


def _capture(window: MainWindow, filename: str) -> dict[str, int | str]:
    image = window.grab()
    path = OUTPUT_DIRECTORY / filename
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save native GUI screenshot: {path}")
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "width_px": image.width(),
        "height_px": image.height(),
    }


def _draw_boundary(
    window: MainWindow,
    kind: str,
    points: list[tuple[float, float]],
) -> None:
    controller = window.spectrogram_view.corridor_controller
    if kind not in {"upper", "lower"}:
        raise ValueError("kind must be upper or lower")
    if not controller.begin_boundary(kind):
        raise RuntimeError(f"Could not enter {kind}-boundary editing.")
    if window.spectrogram_view._search_band_handles_enabled:
        raise AssertionError("Search handles remained enabled during editing.")
    if any(line.isVisible() for line in window.spectrogram_view._search_lines):
        raise AssertionError("A search handle remained visible during editing.")
    controller._draft_points = points
    controller._refresh_draft()
    if not controller.finish_drawing():
        raise RuntimeError(f"Could not finish {kind}-boundary editing.")
    if not window.spectrogram_view._search_band_handles_enabled:
        raise AssertionError("Search handles were not restored after editing.")
    if not all(line.isVisible() for line in window.spectrogram_view._search_lines):
        raise AssertionError("A search handle stayed hidden after editing.")


def _set_source(window: MainWindow, source_path: Path) -> None:
    configuration = load_workflow_config(
        CONFIG_PATH,
        repository_root=REPOSITORY_ROOT,
    )
    window.set_loaded_result(_load(source_path))
    window.set_analysis_configuration(configuration)
    window.analysis_range_panel.use_full_range()
    window.velocity_view.display_velocity_check.setChecked(True)


def _boundary_points(
    time_s: np.ndarray,
    fractions: tuple[float, ...],
    frequencies_hz: tuple[float, ...],
) -> list[tuple[float, float]]:
    indices = np.asarray(
        [round((time_s.size - 1) * fraction) for fraction in fractions],
        dtype=np.int64,
    )
    return [
        (float(time_s[index]), frequency_hz)
        for index, frequency_hz in zip(indices, frequencies_hz, strict=True)
    ]


def _assert_full_grid_semantics(
    region: ManualFrequencyRegion,
    time_s: np.ndarray,
    frequency_hz: np.ndarray,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lower_hz, upper_hz = evaluate_manual_frequency_region_bounds(
        region,
        time_s,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
    )
    mask = (
        (frequency_hz[:, np.newaxis] >= lower_hz[np.newaxis, :])
        & (frequency_hz[:, np.newaxis] <= upper_hz[np.newaxis, :])
    )
    if not np.all(lower_hz <= upper_hz):
        raise AssertionError("The evaluated manual bounds cross on the STFT grid.")
    return lower_hz, upper_hz, mask


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source_hashes_before = {
        source.name: _sha256(source) for source in (NORMAL_SOURCE, COMPLEX_SOURCE)
    }
    application = create_application(sys.argv, language_code="zh_CN")
    if application.platformName() != "windows":
        raise RuntimeError("TASK-016R5 requires native Windows Qt evidence.")
    settings = QSettings(
        str(OUTPUT_DIRECTORY / "task016r5_acceptance.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    window = MainWindow(translation_manager=translation_manager(), settings=settings)
    screenshots: list[dict[str, int | str]] = []
    evidence: dict[str, object] = {}
    try:
        window.resize(1600, 950)
        window.show()

        _set_source(window, NORMAL_SOURCE)
        application.processEvents()
        _wait(window, window.run_stft_analysis, AnalysisResultSource.SPECTROGRAM)
        _wait(
            window,
            window.run_staged_automatic_analysis,
            AnalysisResultSource.AUTOMATIC,
        )
        normal_session = window.analysis_session
        normal_channel = next(iter(normal_session.stft_results))
        normal_stft = normal_session.stft_results[normal_channel]
        parameters = normal_session.run_configuration.parameters

        window.science_tabs.setCurrentWidget(window.velocity_view)
        window.guided_mode_radio.click()
        application.processEvents()
        if window.science_tabs.currentWidget() is not window.spectrogram_view:
            raise AssertionError("Manual mode did not switch to the spectrogram.")
        fitted_range = window.spectrogram_view.plot_widget.plotItem.vb.viewRange()
        window.spectrogram_view.plot_widget.setXRange(-20.0, -10.0, padding=0.0)
        custom_range = window.spectrogram_view.plot_widget.plotItem.vb.viewRange()
        window._sync_guided_panel()
        application.processEvents()
        if window.spectrogram_view.plot_widget.plotItem.vb.viewRange() != custom_range:
            raise AssertionError("A routine refresh stole the user's custom zoom.")
        window.science_tabs.setCurrentWidget(window.velocity_view)
        window.automatic_mode_radio.click()
        application.processEvents()
        if window.science_tabs.currentWidget() is not window.spectrogram_view:
            raise AssertionError("Automatic mode did not switch to the spectrogram.")
        window.guided_mode_radio.click()
        application.processEvents()

        upper_points = _boundary_points(
            normal_stft.time_s,
            (0.25, 0.55, 0.78),
            (0.85e9, 1.15e9, 1.35e9),
        )
        _draw_boundary(window, "upper", upper_points)
        application.processEvents()
        upper_region = normal_session.ridge_constraints[normal_channel]
        if not isinstance(upper_region, ManualFrequencyRegion):
            raise AssertionError("Upper-only region was not stored in the core model.")
        lower_hz, upper_hz, expected_mask = _assert_full_grid_semantics(
            upper_region,
            normal_stft.time_s,
            normal_stft.frequency_hz,
            parameters.minimum_frequency_hz,
            parameters.maximum_frequency_hz,
        )
        actual_mask = manual_frequency_region_mask(
            upper_region,
            normal_stft,
            minimum_frequency_hz=parameters.minimum_frequency_hz,
            maximum_frequency_hz=parameters.maximum_frequency_hz,
        )
        np.testing.assert_array_equal(actual_mask, expected_mask)
        if upper_hz[0] != upper_points[0][1] or upper_hz[-1] != upper_points[-1][1]:
            raise AssertionError("Upper endpoints were not constant-extended.")
        if not np.all(lower_hz == parameters.minimum_frequency_hz):
            raise AssertionError("Missing lower boundary did not use global f_min.")
        window.spectrogram_view.fit_search_region()
        application.processEvents()
        screenshots.append(_capture(window, "normal_upper_only.png"))

        window.spectrogram_view.corridor_controller.clear_constraint()
        lower_points = _boundary_points(
            normal_stft.time_s,
            (0.18, 0.48, 0.70),
            (0.12e9, 0.25e9, 0.45e9),
        )
        _draw_boundary(window, "lower", lower_points)
        application.processEvents()
        lower_region = normal_session.ridge_constraints[normal_channel]
        if not isinstance(lower_region, ManualFrequencyRegion):
            raise AssertionError("Lower-only region was not stored in the core model.")
        lower_hz, upper_hz, expected_mask = _assert_full_grid_semantics(
            lower_region,
            normal_stft.time_s,
            normal_stft.frequency_hz,
            parameters.minimum_frequency_hz,
            parameters.maximum_frequency_hz,
        )
        np.testing.assert_array_equal(
            manual_frequency_region_mask(
                lower_region,
                normal_stft,
                minimum_frequency_hz=parameters.minimum_frequency_hz,
                maximum_frequency_hz=parameters.maximum_frequency_hz,
            ),
            expected_mask,
        )
        if lower_hz[0] != lower_points[0][1] or lower_hz[-1] != lower_points[-1][1]:
            raise AssertionError("Lower endpoints were not constant-extended.")
        if not np.all(upper_hz == parameters.maximum_frequency_hz):
            raise AssertionError("Missing upper boundary did not use global f_max.")
        window.spectrogram_view.fit_search_region()
        application.processEvents()
        screenshots.append(_capture(window, "normal_lower_only.png"))

        start_s, end_s = normal_session.analysis_range.start_time_s, (
            normal_session.analysis_range.end_time_s
        )
        automatic_reference_s = normal_session.event_reference_time_s
        manual_reference_s = 0.5 * (start_s + end_s)
        panel = window.analysis_range_panel
        panel.event_reference_spin.setValue(manual_reference_s * 1.0e6)
        panel.manual_event_time_radio.click()
        application.processEvents()
        if normal_session.event_time_source is not EventTimeSource.MANUAL:
            raise AssertionError("Manual event source was not activated.")
        if normal_session.event_reference_time_s != manual_reference_s:
            raise AssertionError("Manual event time was not stored in SI seconds.")
        window.select_workflow_step(0)
        application.processEvents()
        screenshots.append(_capture(window, "data_range_manual_event.png"))
        panel.automatic_event_time_radio.click()
        application.processEvents()
        if normal_session.event_time_source is not EventTimeSource.AUTOMATIC:
            raise AssertionError("Automatic event source was not restored.")
        if normal_session.event_reference_time_s != automatic_reference_s:
            raise AssertionError("Automatic event time was not restored.")
        evidence["normal"] = {
            "source": NORMAL_SOURCE.relative_to(REPOSITORY_ROOT).as_posix(),
            "channel": normal_channel,
            "upper_only_constant_extension_hz": [
                upper_points[0][1],
                upper_points[-1][1],
            ],
            "lower_only_constant_extension_hz": [
                lower_points[0][1],
                lower_points[-1][1],
            ],
            "mode_fit_view_range": fitted_range,
            "manual_event_time_s": manual_reference_s,
            "restored_automatic_event_time_s": automatic_reference_s,
        }

        _set_source(window, COMPLEX_SOURCE)
        application.processEvents()
        _wait(window, window.run_stft_analysis, AnalysisResultSource.SPECTROGRAM)
        _wait(
            window,
            window.run_staged_automatic_analysis,
            AnalysisResultSource.AUTOMATIC,
        )
        complex_session = window.analysis_session
        complex_channel = next(iter(complex_session.stft_results))
        complex_stft = complex_session.stft_results[complex_channel]
        complex_parameters = complex_session.run_configuration.parameters
        automatic_analysis = complex_session.channel_analyses[complex_channel]
        automatic_hash = _array_sha256(automatic_analysis.apparent_velocity_m_s)
        complex_reference_s = complex_session.resolved_event_time_s(complex_channel)
        if complex_reference_s is None:
            raise AssertionError("The complex real dataset produced no event reference.")

        window.guided_mode_radio.click()
        application.processEvents()
        _draw_boundary(
            window,
            "lower",
            _boundary_points(
                complex_stft.time_s,
                (0.08, 0.42, 0.66),
                (0.08e9, 0.15e9, 0.32e9),
            ),
        )
        _draw_boundary(
            window,
            "upper",
            _boundary_points(
                complex_stft.time_s,
                (0.30, 0.62, 0.92),
                (1.75e9, 1.85e9, 1.95e9),
            ),
        )
        application.processEvents()
        complex_region = complex_session.ridge_constraints[complex_channel]
        if not isinstance(complex_region, ManualFrequencyRegion):
            raise AssertionError("The mismatched boundary region was not stored.")
        lower_hz, upper_hz, expected_mask = _assert_full_grid_semantics(
            complex_region,
            complex_stft.time_s,
            complex_stft.frequency_hz,
            complex_parameters.minimum_frequency_hz,
            complex_parameters.maximum_frequency_hz,
        )
        np.testing.assert_array_equal(
            manual_frequency_region_mask(
                complex_region,
                complex_stft,
                minimum_frequency_hz=complex_parameters.minimum_frequency_hz,
                maximum_frequency_hz=complex_parameters.maximum_frequency_hz,
            ),
            expected_mask,
        )
        window.spectrogram_view.fit_search_region()
        application.processEvents()
        screenshots.append(_capture(window, "complex_mismatched_boundaries.png"))

        _wait(window, window.run_guided_analysis, AnalysisResultSource.GUIDED)
        guided_analysis = complex_session.valid_guided_channel_analyses[complex_channel]
        if _array_sha256(
            complex_session.channel_analyses[complex_channel].apparent_velocity_m_s
        ) != automatic_hash:
            raise AssertionError("The Manual run modified the Automatic result.")
        reference_after_s = complex_session.resolved_event_time_s(complex_channel)
        if reference_after_s != complex_reference_s:
            raise AssertionError("The Manual run changed the automatic event time.")
        pre_event = guided_analysis.signal_detection_result.time_s < complex_reference_s
        if not np.any(pre_event):
            raise AssertionError("The complex dataset has no pre-event frames.")
        np.testing.assert_array_equal(
            guided_analysis.signal_detection_result.time_s,
            automatic_analysis.signal_detection_result.time_s,
        )
        display_only = np.asarray(
            [
                origin == PRE_EVENT_DISPLAY_ORIGIN
                for origin in guided_analysis.velocity_origins
            ],
            dtype=np.bool_,
        )
        display_only &= pre_event
        if not np.any(display_only):
            raise AssertionError("The Manual result has no display-only platform.")
        np.testing.assert_array_equal(
            guided_analysis.display_velocity_m_s[display_only],
            0.0,
        )
        if window.velocity_view.event_reference_line is not None:
            raise AssertionError("The velocity t=0 reference line still exists.")
        window.select_workflow_step(3)
        window.science_tabs.setCurrentWidget(window.velocity_view)
        guided_index = window.velocity_view.result_source_combo.findData("guided")
        if guided_index < 0:
            raise AssertionError("The Manual result is unavailable in Velocity.")
        window.velocity_view.result_source_combo.setCurrentIndex(guided_index)
        application.processEvents()
        screenshots.append(_capture(window, "complex_manual_pre_event_platform.png"))
        evidence["complex"] = {
            "source": COMPLEX_SOURCE.relative_to(REPOSITORY_ROOT).as_posix(),
            "channel": complex_channel,
            "full_stft_frame_count": int(complex_stft.time_s.size),
            "allowed_mask_frame_count": int(expected_mask.shape[1]),
            "lower_first_last_hz": [float(lower_hz[0]), float(lower_hz[-1])],
            "upper_first_last_hz": [float(upper_hz[0]), float(upper_hz[-1])],
            "resolved_event_time_s": complex_reference_s,
            "pre_event_platform_frame_count": int(np.count_nonzero(pre_event)),
            "pre_event_display_only_frame_count": int(
                np.count_nonzero(display_only)
            ),
            "automatic_apparent_velocity_sha256_before": automatic_hash,
            "automatic_apparent_velocity_sha256_after": _array_sha256(
                complex_session.channel_analyses[
                    complex_channel
                ].apparent_velocity_m_s
            ),
            "velocity_event_reference_line": None,
        }
    finally:
        window.close()
        application.processEvents()

    source_hashes_after = {
        source.name: _sha256(source) for source in (NORMAL_SOURCE, COMPLEX_SOURCE)
    }
    if source_hashes_after != source_hashes_before:
        raise AssertionError("A raw source changed during native GUI acceptance.")
    summary = {
        "task": "TASK-016R5",
        "qt_platform": application.platformName(),
        "source_sha256_before": source_hashes_before,
        "source_sha256_after": source_hashes_after,
        "workflow_steps": [
            window.workflow_navigation.item(index).text() for index in range(5)
        ],
        "parameter_stack_count": window.parameter_stack.count(),
        "evidence": evidence,
        "screenshots": screenshots,
    }
    summary_path = OUTPUT_DIRECTORY / "task016r5_acceptance_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
