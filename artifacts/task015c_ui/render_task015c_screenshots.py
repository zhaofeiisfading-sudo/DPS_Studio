"""Render TASK-015C display-only acceptance screenshots from user-selected data."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.quality import SignalState
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="User-selected real PDV CSV path; no data path is built into the GUI.",
    )
    return parser.parse_args()


def _save(window: MainWindow, path: Path) -> None:
    if not window.grab().save(str(path), "PNG"):
        raise RuntimeError(f"Could not save {path}.")


def _measured_mask(states: tuple[SignalState, ...]) -> np.ndarray:
    return np.fromiter(
        (state is SignalState.MEASURED for state in states),
        dtype=np.bool_,
        count=len(states),
    )


def _assert_display_semantics(
    window: MainWindow,
    *,
    expected_platform_m_s: float,
    formal_snapshots: dict[str, np.ndarray],
    stft_objects: dict[str, object],
) -> tuple[int, int]:
    total_pre_event = 0
    total_post_event_invalid = 0
    for channel_name, analysis in window.analysis_session.channel_analyses.items():
        detection = analysis.signal_detection_result
        reference_s = detection.manual_event_reference_time_s
        if reference_s is None:
            raise RuntimeError("Real acceptance has no manual event reference.")
        measured = _measured_mask(detection.signal_states)
        pre_event = (detection.time_s < reference_s) & ~measured
        post_event_invalid = (detection.time_s >= reference_s) & ~measured
        if not pre_event.any() or not post_event_invalid.any():
            raise RuntimeError(
                f"{channel_name} lacks required pre/post invalid acceptance frames."
            )
        if not np.equal(
            analysis.display_velocity_m_s[pre_event],
            expected_platform_m_s,
        ).all():
            raise RuntimeError(f"{channel_name} has an incorrect pre-event platform.")
        if not np.isnan(detection.apparent_velocity_m_s[pre_event]).all():
            raise RuntimeError(f"{channel_name} formal pre-event velocity was filled.")
        if not np.isnan(
            analysis.display_velocity_m_s[post_event_invalid]
        ).all():
            raise RuntimeError(f"{channel_name} post-event invalid frames were filled.")
        np.testing.assert_array_equal(
            analysis.display_velocity_m_s[measured],
            detection.apparent_velocity_m_s[measured],
        )
        np.testing.assert_array_equal(
            detection.apparent_velocity_m_s,
            formal_snapshots[channel_name],
        )
        if analysis.stft_result is not stft_objects[channel_name]:
            raise RuntimeError(f"{channel_name} STFT was recomputed or replaced.")
        total_pre_event += int(np.count_nonzero(pre_event))
        total_post_event_invalid += int(np.count_nonzero(post_event_invalid))
    return total_pre_event, total_post_event_invalid


def main() -> int:
    arguments = _arguments()
    source_path = arguments.data.resolve()
    output_root = Path(__file__).resolve().parent
    before_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    loaded = read_delimited_signals(
        source_path,
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
        encoding="utf-8",
        time_scale=1.0,
        voltage_scales={"pdv_channel_1": 1.0, "pdv_channel_2": 1.0},
    )

    application = create_application([], language_code="zh_CN")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow(translation_manager=translation_manager())
    window.resize(1440, 900)
    window.set_loaded_result(loaded)
    window.show()
    application.processEvents()

    loop = QEventLoop()
    failures: list[str] = []
    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(
        lambda _generation, error_type, message, _traceback: (
            failures.append(f"{error_type}: {message}"),
            loop.quit(),
        )
    )
    if not window.run_automatic_analysis():
        raise RuntimeError(window.analysis_status_label.text())
    QTimer.singleShot(120_000, loop.quit)
    loop.exec()
    if failures:
        raise RuntimeError(failures[0])
    if window.workflow_state is not WorkflowState.RESULT_READY:
        raise RuntimeError("Real-data analysis did not reach RESULT_READY.")

    generation = window.analysis_session.generation_id
    formal_snapshots = {
        channel_name: analysis.signal_detection_result.apparent_velocity_m_s.copy()
        for channel_name, analysis in window.analysis_session.channel_analyses.items()
    }
    stft_objects = {
        channel_name: analysis.stft_result
        for channel_name, analysis in window.analysis_session.channel_analyses.items()
    }
    started_after_result: list[int] = []
    window._analysis_adapter.started.connect(started_after_result.append)
    window.workflow_navigation.setCurrentRow(4)
    window.science_tabs.setCurrentIndex(3)
    window.velocity_view.display_velocity_check.setChecked(True)
    application.processEvents()
    pre_count, post_invalid_count = _assert_display_semantics(
        window,
        expected_platform_m_s=0.0,
        formal_snapshots=formal_snapshots,
        stft_objects=stft_objects,
    )
    window.velocity_view.plot_widget.setXRange(553.95, 554.75, padding=0.0)
    window.velocity_view.plot_widget.setYRange(-5.0, 30.0, padding=0.0)
    application.processEvents()
    _save(window, output_root / "pre_event_display_zero_zh.png")

    window.pre_event_display_velocity_spin.setValue(12.5)
    application.processEvents()
    _assert_display_semantics(
        window,
        expected_platform_m_s=12.5,
        formal_snapshots=formal_snapshots,
        stft_objects=stft_objects,
    )
    _save(window, output_root / "pre_event_display_nonzero_zh.png")

    window.velocity_view.plot_widget.enableAutoRange()
    application.processEvents()
    _save(window, output_root / "formal_vs_display_zh.png")

    window.pre_event_display_velocity_spin.setValue(0.0)
    application.processEvents()
    _assert_display_semantics(
        window,
        expected_platform_m_s=0.0,
        formal_snapshots=formal_snapshots,
        stft_objects=stft_objects,
    )
    if window.analysis_session.generation_id != generation:
        raise RuntimeError("Display-only edits changed the analysis generation.")
    if started_after_result:
        raise RuntimeError("Display-only edits started a new background analysis.")
    after_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if before_hash != after_hash:
        raise RuntimeError("The raw source hash changed during GUI acceptance.")

    print(f"state={window.workflow_state.name}")
    print(f"channels={','.join(window.analysis_session.channel_analyses)}")
    print(f"pre_event_display_frame_count={pre_count}")
    print(f"post_event_invalid_frame_count={post_invalid_count}")
    print(f"generation_unchanged={generation}")
    print(f"background_restarts={len(started_after_result)}")
    print(f"source_sha256={after_hash.upper()}")
    for filename in (
        "pre_event_display_zero_zh.png",
        "pre_event_display_nonzero_zh.png",
        "formal_vs_display_zh.png",
    ):
        print(output_root / filename)
    window.close()
    application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
