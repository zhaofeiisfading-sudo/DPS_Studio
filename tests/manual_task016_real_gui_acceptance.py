"""Generate TASK-016 acceptance evidence from the real Qt GUI and raw PDV data.

This module is intentionally not named ``test_*.py``.  Run it manually from the
repository root; it writes only to ``artifacts/task016_guided`` and never edits
the source CSV.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QEventLoop, QSettings, QTimer

from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "demo_dual_profile.toml"
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "task016_guided"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _wait_for_analysis(window: MainWindow, launch: Callable[[], bool]) -> None:
    loop = QEventLoop()
    outcome: dict[str, object] = {"timeout": False, "error": None}

    def timed_out() -> None:
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
    QTimer.singleShot(60_000, timed_out)
    if not launch():
        raise RuntimeError("The GUI rejected the requested analysis run.")
    loop.exec()
    if outcome["timeout"]:
        raise TimeoutError("The GUI analysis did not finish within 60 seconds.")
    if outcome["error"] is not None:
        raise RuntimeError(str(outcome["error"]))
    if window._analysis_adapter.busy:
        raise RuntimeError("The background adapter remained busy after completion.")


def _capture(window: MainWindow, filename: str) -> dict[str, int | str]:
    application = create_application([])
    application.processEvents()
    image = window.grab()
    path = OUTPUT_DIRECTORY / filename
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save the Qt screenshot: {path}")
    return {
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "width_px": image.width(),
        "height_px": image.height(),
    }


def _select_result_source(combo: object, source: str) -> None:
    index = combo.findData(source)  # type: ignore[attr-defined]
    if index < 0:
        raise RuntimeError(f"Result source is unavailable: {source}")
    combo.setCurrentIndex(index)  # type: ignore[attr-defined]


def main() -> int:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    application = create_application(sys.argv, language_code="zh_CN")
    settings = QSettings(
        str(OUTPUT_DIRECTORY / "task016_acceptance.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    configuration = load_workflow_config(
        CONFIG_PATH,
        repository_root=REPOSITORY_ROOT,
    )
    input_configuration = configuration.input
    source = input_configuration.path
    source_hash_before = _sha256(source)
    loaded = DataImportController().load(
        SignalLoadRequest(
            path=source,
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
    original_arrays = {
        channel_name: (record.time_s.copy(), record.voltage_v.copy())
        for channel_name, record in loaded.records.items()
    }

    window = MainWindow(
        translation_manager=translation_manager(),
        settings=settings,
    )
    try:
        window.resize(1440, 900)
        window.show()
        window.set_loaded_result(loaded)
        window.set_analysis_configuration(configuration)
        window.analysis_range_panel.use_full_range()
        application.processEvents()
        _wait_for_analysis(window, window.run_automatic_analysis)

        automatic = window.analysis_session.automatic_channel_analyses
        automatic_identity = id(automatic)
        automatic_candidate = automatic[
            "pdv_channel_1"
        ].ridge_result.frequency_hz.copy()
        automatic_spectrum = automatic[
            "pdv_channel_1"
        ].stft_result.spectrum.copy()

        target_corridor = RidgeCorridorConstraint(
            control_times_s=np.array(
                [554.58, 554.72, 555.18, 555.38, 555.58, 555.72, 555.93]
            )
            * 1.0e-6,
            control_frequencies_hz=np.array(
                [0.10, 0.73, 0.72, 0.27, 0.16, 0.86, 0.87]
            )
            * 1.0e9,
            half_width_hz=70.0e6,
        )
        window._activate_guided_analysis()
        window._ridge_constraint_changed("pdv_channel_1", target_corridor)
        window.science_tabs.setCurrentWidget(window.spectrogram_view)
        application.processEvents()
        screenshots: list[dict[str, int | str]] = [
            _capture(window, "corridor_editing_zh.png")
        ]

        _wait_for_analysis(window, window.run_guided_analysis)
        guided = window.analysis_session.guided_channel_analyses
        target_analysis = guided["pdv_channel_1"]
        target_times = target_analysis.stft_result.time_s
        target_active = (
            (target_times >= target_corridor.start_time_s)
            & (target_times <= target_corridor.end_time_s)
        )
        candidate_difference_count = int(
            np.count_nonzero(
                ~np.isclose(
                    automatic_candidate[target_active],
                    target_analysis.ridge_result.frequency_hz[target_active],
                    equal_nan=True,
                )
            )
        )

        window.science_tabs.setCurrentWidget(window.ridge_view)
        _select_result_source(window.ridge_view.result_source_combo, "guided")
        application.processEvents()
        screenshots.append(_capture(window, "guided_ridge_zh.png"))

        window.science_tabs.setCurrentWidget(window.velocity_view)
        _select_result_source(window.velocity_view.result_source_combo, "guided")
        application.processEvents()
        screenshots.append(_capture(window, "guided_velocity_zh.png"))

        window.science_tabs.setCurrentWidget(window.comparison_view)
        application.processEvents()
        screenshots.append(_capture(window, "automatic_vs_guided_zh.png"))

        window.spectrogram_view.corridor_controller.set_half_width_hz(75.0e6)
        application.processEvents()
        stale_after_edit = window.analysis_session.guided_results_stale
        automatic_valid_after_edit = window.analysis_session.results_valid

        no_peak_corridor = RidgeCorridorConstraint(
            control_times_s=np.array([554.65e-6, 555.75e-6]),
            control_frequencies_hz=np.array([1.30e9, 1.30e9]),
            half_width_hz=12.0e6,
        )
        window._ridge_constraint_changed("pdv_channel_1", no_peak_corridor)
        _wait_for_analysis(window, window.run_guided_analysis)
        no_peak_analysis = window.analysis_session.guided_channel_analyses[
            "pdv_channel_1"
        ]
        no_peak_times = no_peak_analysis.stft_result.time_s
        no_peak_active = (
            (no_peak_times >= no_peak_corridor.start_time_s)
            & (no_peak_times <= no_peak_corridor.end_time_s)
        )
        no_peak_formal = (
            no_peak_analysis.signal_detection_result.refined_frequency_hz[
                no_peak_active
            ]
        )
        no_peak_velocity = (
            no_peak_analysis.signal_detection_result.apparent_velocity_m_s[
                no_peak_active
            ]
        )
        if np.any(np.isfinite(no_peak_formal)) or np.any(
            np.isfinite(no_peak_velocity)
        ):
            raise AssertionError(
                "The deliberately empty/noise corridor produced a formal result."
            )
        window.science_tabs.setCurrentWidget(window.ridge_view)
        _select_result_source(window.ridge_view.result_source_combo, "guided")
        application.processEvents()
        screenshots.append(_capture(window, "no_peak_corridor_nan_zh.png"))

        for channel_name, record in loaded.records.items():
            original_time, original_voltage = original_arrays[channel_name]
            np.testing.assert_array_equal(record.time_s, original_time)
            np.testing.assert_array_equal(record.voltage_v, original_voltage)
        np.testing.assert_array_equal(
            automatic["pdv_channel_1"].stft_result.spectrum,
            automatic_spectrum,
        )
        if id(window.analysis_session.automatic_channel_analyses) != (
            automatic_identity
        ):
            raise AssertionError("Guided analysis replaced the automatic mapping.")
        source_hash_after = _sha256(source)
        if source_hash_after != source_hash_before:
            raise AssertionError("The real source CSV changed during acceptance.")

        summary = {
            "qt_platform": application.platformName(),
            "source": source.relative_to(REPOSITORY_ROOT).as_posix(),
            "source_sha256_before": source_hash_before,
            "source_sha256_after": source_hash_after,
            "channels": list(loaded.records),
            "automatic_frame_count": int(
                automatic["pdv_channel_1"].stft_result.time_s.size
            ),
            "target_corridor_active_frames": int(np.count_nonzero(target_active)),
            "target_candidate_difference_count": candidate_difference_count,
            "target_guided_formal_finite_count": int(
                np.count_nonzero(
                    np.isfinite(
                        target_analysis.signal_detection_result.refined_frequency_hz[
                            target_active
                        ]
                    )
                )
            ),
            "stale_after_constraint_edit": stale_after_edit,
            "automatic_valid_after_constraint_edit": automatic_valid_after_edit,
            "no_peak_active_frames": int(np.count_nonzero(no_peak_active)),
            "no_peak_formal_finite_count": int(
                np.count_nonzero(np.isfinite(no_peak_formal))
            ),
            "no_peak_velocity_finite_count": int(
                np.count_nonzero(np.isfinite(no_peak_velocity))
            ),
            "screenshots": screenshots,
        }
        (OUTPUT_DIRECTORY / "acceptance_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        window.close()
        application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
