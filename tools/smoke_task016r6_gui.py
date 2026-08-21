"""Run TASK-016R6 real-data GUI coverage and Working/Formal smoke checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.quality import SignalState
from dps_studio.core.ridge import (
    ManualFrequencyBoundary,
    ManualFrequencyRegion,
    RidgeRefinementStatus,
)
from dps_studio.core.workflow import WorkingRidgeSource
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load(source: Path) -> object:
    return DataImportController().load(
        SignalLoadRequest(
            path=source,
            time_column=0,
            channels=(
                ChannelImportSpec("pdv_channel_1", 1, 1.0),
                ChannelImportSpec("pdv_channel_2", 2, 1.0),
            ),
            delimiter=",",
            has_header=False,
            encoding="utf-8",
            time_scale=1.0,
        )
    )


def _wait(window: MainWindow, launch: Any) -> None:
    loop = QEventLoop()
    state: dict[str, object] = {"timed_out": False, "error": None}

    def timed_out() -> None:
        state["timed_out"] = True
        loop.quit()

    def failed(
        _generation: int,
        error_type: str,
        message: str,
        _detail: str,
    ) -> None:
        state["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(60_000, timed_out)
    if not launch():
        raise RuntimeError("GUI rejected an analysis request.")
    loop.exec()
    if state["timed_out"] or state["error"] is not None:
        raise RuntimeError(f"GUI analysis failed: {state}")


def _metrics(analysis: Any, *, event_time_s: float | None) -> dict[str, object]:
    states = np.asarray(analysis.signal_detection_result.signal_states, dtype=object)
    working = np.isfinite(analysis.working_frequency_hz)
    formal = np.isfinite(
        analysis.signal_detection_result.refined_frequency_hz
    )
    analysis_frames = np.fromiter(
        (state is not SignalState.OUTSIDE_ANALYSIS_WINDOW for state in states),
        dtype=np.bool_,
        count=states.size,
    )
    low_quality_working = working & np.fromiter(
        (state is not SignalState.MEASURED for state in states),
        dtype=np.bool_,
        count=states.size,
    )
    fallback = np.fromiter(
        (
            source
            in {
                WorkingRidgeSource.DISCRETE_FALLBACK,
                WorkingRidgeSource.LOW_CONFIDENCE_FALLBACK,
            }
            for source in analysis.working_source
        ),
        dtype=np.bool_,
        count=states.size,
    )
    refined = np.fromiter(
        (
            status is RidgeRefinementStatus.REFINED
            for status in analysis.refined_result.refinement_statuses
        ),
        dtype=np.bool_,
        count=states.size,
    ) & working
    pre_event = np.zeros(states.size, dtype=np.bool_)
    platform_complete: bool | None = None
    if event_time_s is not None:
        pre_event = analysis_frames & (analysis.stft_result.time_s < event_time_s)
        platform_complete = bool(
            pre_event.any()
            and np.equal(analysis.display_velocity_m_s[pre_event], 0.0).all()
        )
    analysis_count = int(np.count_nonzero(analysis_frames))
    working_count = int(np.count_nonzero(working & analysis_frames))
    formal_count = int(np.count_nonzero(formal & analysis_frames))
    fallback_count = int(np.count_nonzero(fallback & analysis_frames))
    return {
        "analysis_frames": analysis_count,
        "working_finite_frames": working_count,
        "working_coverage": working_count / analysis_count,
        "formal_finite_frames": formal_count,
        "formal_coverage": formal_count / analysis_count,
        "fallback_frames": fallback_count,
        "fallback_ratio": fallback_count / analysis_count,
        "refined_frames": int(np.count_nonzero(refined & analysis_frames)),
        "quality_fail_but_working_frames": int(
            np.count_nonzero(low_quality_working & analysis_frames)
        ),
        "hard_unavailable_frames": int(
            np.count_nonzero(analysis_frames & ~working)
        ),
        "formal_gate_consistent": bool(
            np.array_equal(
                formal,
                np.fromiter(
                    (state is SignalState.MEASURED for state in states),
                    dtype=np.bool_,
                    count=states.size,
                ),
            )
        ),
        "working_velocity_conversion_exact": bool(
            np.array_equal(
                analysis.working_velocity_m_s,
                analysis.working_frequency_hz
                * analysis.discrete_velocity_result.vacuum_wavelength_m
                / 2.0,
                equal_nan=True,
            )
        ),
        "pre_event_platform_complete": platform_complete,
        "pre_event_frame_count": int(np.count_nonzero(pre_event)),
        "working_source_counts": {
            source.value: analysis.working_source.count(source)
            for source in WorkingRidgeSource
        },
        "quality_state_counts": {
            state.value: analysis.signal_detection_result.signal_states.count(state)
            for state in SignalState
        },
    }


def _save_window(
    app: QApplication,
    window: MainWindow,
    path: Path,
) -> None:
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    if not window.grab().save(str(path)):
        raise RuntimeError(f"Could not save GUI screenshot {path}.")


def _smoke_source(
    app: QApplication,
    source: Path,
    output_directory: Path,
    *,
    case_name: str,
    run_guided: bool,
) -> dict[str, object]:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_load(source))
        window.analysis_range_panel.use_full_range()
        app.processEvents()
        _wait(window, window.run_automatic_analysis)
        if window.workflow_state is not WorkflowState.RESULT_READY:
            raise RuntimeError("One-click analysis did not reach RESULT_READY.")
        session = window.analysis_session
        analyses = session.channel_analyses
        if set(analyses) != {"pdv_channel_1", "pdv_channel_2"}:
            raise RuntimeError("One-click analysis did not retain both channels.")
        event_s = session.resolved_event_time_s("pdv_channel_1")
        shared_event = all(
            session.resolved_event_time_s(name) == event_s for name in analyses
        )
        window.science_tabs.setCurrentWidget(window.ridge_view)
        _save_window(
            app,
            window,
            output_directory / f"{case_name}_automatic_working_formal.png",
        )
        result: dict[str, object] = {
            "source": source.name,
            "workflow_state": window.workflow_state.name,
            "event_time_s": event_s,
            "event_source": session.resolved_event_source("pdv_channel_1"),
            "ch1_event_shared_across_channels": shared_event,
            "automatic": {
                name: _metrics(analysis, event_time_s=event_s)
                for name, analysis in analyses.items()
            },
            "yellow_curve_is_working_ridge": bool(
                np.array_equal(
                    window.ridge_view.refined_curve.yData,
                    analyses["pdv_channel_1"].working_frequency_hz * 1.0e-9,
                    equal_nan=True,
                )
            ),
            "green_curve_is_formal_ridge": bool(
                np.array_equal(
                    window.ridge_view.formal_curve.yData,
                    analyses[
                        "pdv_channel_1"
                    ].signal_detection_result.refined_frequency_hz
                    * 1.0e-9,
                    equal_nan=True,
                )
            ),
            "working_display_enabled_by_default": (
                window.velocity_view.display_velocity_check.isChecked()
            ),
        }
        if run_guided:
            stft = analyses["pdv_channel_1"].stft_result
            time_bounds = np.asarray([stft.time_s[0], stft.time_s[-1]])
            region = ManualFrequencyRegion(
                lower_boundary=ManualFrequencyBoundary(
                    control_times_s=time_bounds,
                    control_frequencies_hz=np.asarray([0.05e9, 0.05e9]),
                ),
                upper_boundary=ManualFrequencyBoundary(
                    control_times_s=time_bounds,
                    control_frequencies_hz=np.asarray([2.0e9, 2.0e9]),
                ),
            )
            window.guided_mode_radio.click()
            window._ridge_constraint_changed("pdv_channel_1", region)
            app.processEvents()
            _wait(window, window.run_guided_analysis)
            guided = session.guided_channel_analyses["pdv_channel_1"]
            window.science_tabs.setCurrentWidget(window.ridge_view)
            _save_window(
                app,
                window,
                output_directory / f"{case_name}_guided_working_formal.png",
            )
            result["guided"] = _metrics(guided, event_time_s=event_s)
            result["guided_uses_shared_event"] = (
                guided.signal_detection_result.manual_event_reference_time_s
                == event_s
            )
        return result
    finally:
        window.close()
        app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    output_directory = arguments.output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    repository_root = Path(__file__).resolve().parents[1]
    raw_directory = repository_root / "data" / "raw"
    sources = {
        "good": raw_directory / "20260607.csv",
        "bad": raw_directory / "20260630-1.csv",
    }
    raw_files = sorted(path for path in raw_directory.iterdir() if path.is_file())
    hashes_before = {path.name: _sha256(path) for path in raw_files}
    app = create_application([])
    results = {
        name: _smoke_source(
            app,
            source,
            output_directory,
            case_name=name,
            run_guided=name == "bad",
        )
        for name, source in sources.items()
    }
    hashes_after = {path.name: _sha256(path) for path in raw_files}
    summary = {
        "command_semantics": (
            "Windows Qt QApplication through the same MainWindow used by "
            "python -m dps_studio.gui"
        ),
        "raw_hashes_unchanged": hashes_before == hashes_after,
        "cases": results,
    }
    (output_directory / "task016r6_smoke_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    raise SystemExit(main())
