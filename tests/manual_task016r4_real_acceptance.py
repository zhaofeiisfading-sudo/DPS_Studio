"""Generate native Qt evidence for TASK-016R4 from the real PDV dataset.

Run manually from the repository root. The script reads ``data/raw`` only and
writes generated screenshots/JSON only below ``artifacts/task016r4``.
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
    manual_frequency_region_mask,
)
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.analysis_adapter import AnalysisResultSource
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPOSITORY_ROOT / "data" / "raw" / "20260607.csv"
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task016r4"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _array_sha256(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest().upper()


def _wait(
    window: MainWindow,
    launch: Callable[[], bool],
    expected_source: AnalysisResultSource,
) -> None:
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
        raise RuntimeError("The GUI rejected the acceptance analysis request.")
    if window._pending_analysis_source is not expected_source:
        raise AssertionError("The GUI selected an unexpected worker path.")
    loop.exec()
    if outcome["timed_out"]:
        raise TimeoutError("The native GUI analysis exceeded 90 seconds.")
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
    if kind == "upper":
        if not controller.begin_boundary("upper"):
            raise RuntimeError("Could not enter upper-boundary editing.")
    elif not controller.begin_boundary("lower"):
        raise RuntimeError("Could not enter lower-boundary editing.")
    controller._draft_points = points
    controller._refresh_draft()
    if not controller.finish_drawing():
        raise RuntimeError(f"Could not finish {kind} boundary editing.")


def _boundary_document(boundary: object) -> list[dict[str, float]]:
    if boundary is None:
        return []
    return [
        {"time_s": float(time_s), "frequency_hz": float(frequency_hz)}
        for time_s, frequency_hz in zip(
            boundary.control_times_s,
            boundary.control_frequencies_hz,
            strict=True,
        )
    ]


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source_hash_before = _sha256(SOURCE_PATH)
    configuration = load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    input_configuration = configuration.input
    loaded = DataImportController().load(
        SignalLoadRequest(
            path=SOURCE_PATH,
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
    application = create_application(sys.argv, language_code="zh_CN")
    if application.platformName() != "windows":
        raise RuntimeError("TASK-016R4 requires native Windows Qt evidence.")
    settings = QSettings(
        str(OUTPUT_DIRECTORY / "task016r4_acceptance.ini"),
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
        _wait(window, window.run_stft_analysis, AnalysisResultSource.SPECTROGRAM)
        _wait(
            window,
            window.run_staged_automatic_analysis,
            AnalysisResultSource.AUTOMATIC,
        )

        session = window.analysis_session
        channel_name = next(iter(session.stft_results))
        stft = session.stft_results[channel_name]
        stft_hash_before = _array_sha256(stft.spectrum)
        automatic_velocity_hash = _array_sha256(
            session.channel_analyses[
                channel_name
            ].signal_detection_result.apparent_velocity_m_s
        )
        time_axis = stft.time_s
        indices = np.linspace(
            int(time_axis.size * 0.20),
            int(time_axis.size * 0.80),
            4,
            dtype=np.int64,
        )
        upper_hz = (0.80e9, 0.80e9, 1.35e9, 1.35e9)
        lower_hz = (0.15e9, 0.15e9, 0.55e9, 0.55e9)

        window.select_workflow_step(3)
        window.guided_mode_radio.click()
        application.processEvents()
        _draw_boundary(
            window,
            "upper",
            [
                (float(time_axis[index]), frequency_hz)
                for index, frequency_hz in zip(indices, upper_hz, strict=True)
            ],
        )
        _draw_boundary(
            window,
            "lower",
            [
                (float(time_axis[index]), frequency_hz)
                for index, frequency_hz in zip(indices, lower_hz, strict=True)
            ],
        )
        application.processEvents()
        window.spectrogram_view.fit_search_region()
        application.processEvents()
        screenshots.append(_capture(window, "manual_frequency_region.png"))

        constraint = session.ridge_constraints[channel_name]
        if not isinstance(constraint, ManualFrequencyRegion):
            raise AssertionError("The GUI did not store a manual frequency region.")
        parameters = session.run_configuration.parameters
        mask = manual_frequency_region_mask(
            constraint,
            stft,
            minimum_frequency_hz=parameters.minimum_frequency_hz,
            maximum_frequency_hz=parameters.maximum_frequency_hz,
        )
        _wait(window, window.run_guided_analysis, AnalysisResultSource.GUIDED)
        guided = session.valid_guided_channel_analyses[channel_name]
        window.science_tabs.setCurrentWidget(window.velocity_view)
        guided_index = window.velocity_view.result_source_combo.findData("guided")
        if guided_index < 0:
            raise AssertionError("The Guided result source is missing in Velocity.")
        window.velocity_view.result_source_combo.setCurrentIndex(guided_index)
        application.processEvents()
        screenshots.append(_capture(window, "manual_frequency_velocity.png"))

        if stft_hash_before != _array_sha256(stft.spectrum):
            raise AssertionError("The manual mask modified the original STFT.")
        if automatic_velocity_hash != _array_sha256(
            session.channel_analyses[
                channel_name
            ].signal_detection_result.apparent_velocity_m_s
        ):
            raise AssertionError("The Guided run modified the Automatic result.")
        detection = guided.signal_detection_result
        summary = {
            "task": "TASK-016R4",
            "qt_platform": application.platformName(),
            "source": SOURCE_PATH.relative_to(REPOSITORY_ROOT).as_posix(),
            "source_sha256_before": source_hash_before,
            "source_sha256_after": _sha256(SOURCE_PATH),
            "channel": channel_name,
            "constraint_model": "manual_upper_lower_boundaries",
            "upper_boundary": _boundary_document(constraint.upper_boundary),
            "lower_boundary": _boundary_document(constraint.lower_boundary),
            "outside_manual_time_range": "global_search_band",
            "allowed_mask_true_bins": int(np.count_nonzero(mask)),
            "allowed_mask_total_bins": int(mask.size),
            "stft_sha256_before": stft_hash_before,
            "stft_sha256_after": _array_sha256(stft.spectrum),
            "automatic_velocity_sha256_before": automatic_velocity_hash,
            "automatic_velocity_sha256_after": _array_sha256(
                session.channel_analyses[
                    channel_name
                ].signal_detection_result.apparent_velocity_m_s
            ),
            "guided_finite_frequency_frames": int(
                np.count_nonzero(np.isfinite(detection.refined_frequency_hz))
            ),
            "guided_nan_frequency_frames": int(
                np.count_nonzero(np.isnan(detection.refined_frequency_hz))
            ),
            "screenshots": screenshots,
        }
    finally:
        window.close()
        application.processEvents()

    if source_hash_before != _sha256(SOURCE_PATH):
        raise AssertionError("The raw source CSV changed during acceptance.")
    summary_path = OUTPUT_DIRECTORY / "task016r4_acceptance_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
