"""Run read-only TASK-015C-R cross-file diagnostics and GUI acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from dps_studio.core.io import DelimitedSignalLoadResult, read_delimited_signals
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import (  # noqa: E402
    ChannelAnalysis,
    analyze_profile,
    load_workflow_config,
)
from dps_studio.gui.app import create_application, translation_manager  # noqa: E402
from dps_studio.gui.main_window import MainWindow  # noqa: E402
from dps_studio.gui.state import WorkflowState  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data", type=Path, action="append", required=True)
    parser.add_argument("--reference-data", type=Path, required=True)
    parser.add_argument("--new-data", type=Path, required=True)
    return parser.parse_args()


def _load(path: Path) -> DelimitedSignalLoadResult:
    return read_delimited_signals(
        path.resolve(),
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
        encoding="utf-8",
        time_scale=1.0,
        voltage_scales={"pdv_channel_1": 1.0, "pdv_channel_2": 1.0},
    )


def _default_range(
    configuration: Any,
    loaded: DelimitedSignalLoadResult,
) -> tuple[float, float]:
    start_s = max(record.start_time_s for record in loaded.records.values())
    end_s = min(record.end_time_s for record in loaded.records.values())
    configured_start = configuration.analysis.analysis_start_time_s
    configured_end = configuration.analysis.analysis_end_time_s
    if (
        configured_start is not None
        and configured_end is not None
        and start_s <= configured_start < configured_end <= end_s
    ):
        return configured_start, configured_end
    return float(start_s), float(end_s)


def _validated_reference(
    configuration: Any,
    loaded: DelimitedSignalLoadResult,
    analysis_range: tuple[float, float],
) -> float | None:
    reference = configuration.analysis.event_reference_time_s
    if reference is None:
        return None
    start_s = max(record.start_time_s for record in loaded.records.values())
    end_s = min(record.end_time_s for record in loaded.records.values())
    if (
        start_s <= reference <= end_s
        and analysis_range[0] <= reference <= analysis_range[1]
    ):
        return float(reference)
    return None


def _analyze(
    configuration: Any,
    loaded: DelimitedSignalLoadResult,
    analysis_range: tuple[float, float],
    reference_s: float | None,
) -> dict[str, ChannelAnalysis]:
    return dict(
        analyze_profile(
            loaded.records,
            profile=configuration.analysis.default_profile,
            analysis_start_time_s=analysis_range[0],
            analysis_end_time_s=analysis_range[1],
            manual_event_reference_time_s=reference_s,
            vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
            detection_config=configuration.quality.signal_detection,
            event_candidate_config=configuration.event_candidate,
            background_guard_window_scale=(
                configuration.quality.background_guard_window_scale
            ),
            minimum_background_bin_count=(
                configuration.quality.minimum_background_bin_count
            ),
            assume_pre_event_zero_for_display=True,
            pre_event_display_velocity_m_s=(
                configuration.plot.pre_event_display_velocity_m_s
            ),
        )
    )


def _diagnostic_row(
    filename: str,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    full_range: tuple[float, float],
    analysis_range: tuple[float, float],
    reference_s: float | None,
    jump_threshold_hz: float,
) -> dict[str, object]:
    detection = analysis.signal_detection_result
    counts = Counter(state.name for state in detection.signal_states)
    finite_velocity = detection.apparent_velocity_m_s[
        np.isfinite(detection.apparent_velocity_m_s)
    ]
    finite_contrast = detection.peak_to_background_db[
        np.isfinite(detection.peak_to_background_db)
    ]
    absolute_steps = analysis.continuity_result.absolute_frequency_step_hz
    finite_steps = absolute_steps[np.isfinite(absolute_steps)]
    candidate = detection.detected_event_candidate_time_s
    return {
        "file": filename,
        "channel": channel_name,
        "full_range_us": [full_range[0] * 1e6, full_range[1] * 1e6],
        "analysis_range_us": [
            analysis_range[0] * 1e6,
            analysis_range[1] * 1e6,
        ],
        "event_reference_us": None if reference_s is None else reference_s * 1e6,
        "event_reference_valid": reference_s is not None,
        "candidate_time_us": None if candidate is None else candidate * 1e6,
        "measured": counts.get("MEASURED", 0),
        "nan": int(np.count_nonzero(np.isnan(detection.apparent_velocity_m_s))),
        "no_detectable": counts.get("NO_DETECTABLE_BEAT", 0),
        "ambiguous": counts.get("AMBIGUOUS_PEAK", 0),
        "band_boundary": counts.get("PEAK_AT_BAND_BOUNDARY", 0),
        "unstable": counts.get("UNSTABLE_DETECTION", 0),
        "insufficient_cycles": counts.get("INSUFFICIENT_CYCLES", 0),
        "refinement_failed": counts.get("REFINEMENT_FAILED", 0),
        "outside": counts.get("OUTSIDE_ANALYSIS_WINDOW", 0),
        "finite_velocity_min_m_s": (
            None if not finite_velocity.size else float(np.min(finite_velocity))
        ),
        "finite_velocity_max_m_s": (
            None if not finite_velocity.size else float(np.max(finite_velocity))
        ),
        "median_peak_to_background_db": (
            None if not finite_contrast.size else float(np.median(finite_contrast))
        ),
        "large_ridge_step_count": int(
            np.count_nonzero(finite_steps > jump_threshold_hz)
        ),
        "maximum_ridge_step_mhz": (
            None if not finite_steps.size else float(np.max(finite_steps) * 1e-6)
        ),
        "signal_states": dict(sorted(counts.items())),
    }


def _format_range(values: object) -> str:
    start, end = values
    return f"{start:.6f}–{end:.6f}"


def _format_optional(value: object, suffix: str = "") -> str:
    if value is None:
        return "unset"
    return f"{float(value):.6f}{suffix}"


def _write_diagnostics(
    rows: list[dict[str, object]],
    output_root: Path,
) -> None:
    (output_root / "cross_file_diagnostic.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    header = (
        "| file | channel | analysis range (µs) | candidate (µs) | MEASURED | "
        "NO_DETECTABLE | AMBIGUOUS | BAND_BOUNDARY | UNSTABLE | "
        "finite velocity range (m/s) |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    body = []
    for row in rows:
        minimum = row["finite_velocity_min_m_s"]
        maximum = row["finite_velocity_max_m_s"]
        velocity_range = (
            "none"
            if minimum is None or maximum is None
            else f"{float(minimum):.3f}–{float(maximum):.3f}"
        )
        body.append(
            "| {file} | {channel} | {analysis} | {candidate} | {measured} | "
            "{no_detectable} | {ambiguous} | {band_boundary} | {unstable} | "
            "{velocity} |".format(
                file=row["file"],
                channel=row["channel"],
                analysis=_format_range(row["analysis_range_us"]),
                candidate=_format_optional(row["candidate_time_us"]),
                measured=row["measured"],
                no_detectable=row["no_detectable"],
                ambiguous=row["ambiguous"],
                band_boundary=row["band_boundary"],
                unstable=row["unstable"],
                velocity=velocity_range,
            )
        )
    (output_root / "cross_file_diagnostic.md").write_text(
        header + "\n".join(body) + "\n",
        encoding="utf-8",
    )


def _spectrogram_overview(
    analyses_by_file: dict[str, dict[str, ChannelAnalysis]],
    output_root: Path,
) -> None:
    fig, axes = plt.subplots(
        len(analyses_by_file),
        2,
        figsize=(13.0, 10.0),
        constrained_layout=True,
        squeeze=False,
    )
    for row_index, (filename, analyses) in enumerate(analyses_by_file.items()):
        for column_index, (channel_name, analysis) in enumerate(analyses.items()):
            axis = axes[row_index, column_index]
            spectrum = np.abs(analysis.stft_result.spectrum)
            reference = float(np.max(spectrum))
            with np.errstate(divide="ignore"):
                display = 20.0 * np.log10(spectrum / reference)
            display = np.maximum(display, -60.0)
            time_us = analysis.stft_result.time_s * 1e6
            frequency_ghz = analysis.stft_result.frequency_hz * 1e-9
            axis.imshow(
                display,
                origin="lower",
                aspect="auto",
                interpolation="nearest",
                extent=(
                    float(time_us[0]),
                    float(time_us[-1]),
                    float(frequency_ghz[0]),
                    float(frequency_ghz[-1]),
                ),
                vmin=-60.0,
                vmax=0.0,
                cmap="viridis",
            )
            formal = analysis.signal_detection_result.refined_frequency_hz * 1e-9
            axis.plot(time_us, formal, color="#ffcc00", linewidth=0.7)
            axis.set_ylim(0.0, 2.0)
            axis.set_title(f"{filename} / {channel_name}", fontsize=8)
            axis.set_xlabel("Time (µs)")
            axis.set_ylabel("Frequency (GHz)")
    fig.savefig(output_root / "cross_file_spectrogram_overview.png", dpi=160)
    plt.close(fig)


def _diagnostic_table(rows: list[dict[str, object]], output_root: Path) -> None:
    widget = QWidget()
    widget.setWindowTitle("TASK-015C-R 跨实验诊断（相同 Balanced 配置）")
    layout = QVBoxLayout(widget)
    layout.addWidget(
        QLabel(
            "只读诊断：相同 10/3 dB、guard bins、minimum frames/cycles 与搜索频带；未调参"
        )
    )
    headers = [
        "文件",
        "通道",
        "完整范围 (µs)",
        "分析范围 (µs)",
        "参考 (µs)",
        "候选 (µs)",
        "MEASURED",
        "NO_DETECTABLE",
        "AMBIGUOUS",
        "BAND_BOUNDARY",
        "UNSTABLE",
        "有限速度 (m/s)",
        ">100 MHz 跳步",
    ]
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    for row_index, row in enumerate(rows):
        minimum = row["finite_velocity_min_m_s"]
        maximum = row["finite_velocity_max_m_s"]
        velocity = (
            "none"
            if minimum is None or maximum is None
            else f"{float(minimum):.1f}–{float(maximum):.1f}"
        )
        values = (
            row["file"],
            row["channel"],
            _format_range(row["full_range_us"]),
            _format_range(row["analysis_range_us"]),
            _format_optional(row["event_reference_us"]),
            _format_optional(row["candidate_time_us"]),
            row["measured"],
            row["no_detectable"],
            row["ambiguous"],
            row["band_boundary"],
            row["unstable"],
            velocity,
            row["large_ridge_step_count"],
        )
        for column_index, value in enumerate(values):
            table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    layout.addWidget(table)
    widget.resize(2300, 720)
    widget.show()
    QApplication.processEvents()
    if not widget.grab().save(str(output_root / "cross_file_diagnostic.png"), "PNG"):
        raise RuntimeError("Could not save cross-file diagnostic screenshot.")
    widget.close()


def _run_window(window: MainWindow) -> None:
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
        raise RuntimeError(failures[-1])
    if window.workflow_state is not WorkflowState.RESULT_READY:
        raise RuntimeError("GUI analysis did not reach RESULT_READY.")


def _assert_platform(window: MainWindow) -> int:
    reference_s = window.analysis_session.event_reference_time_s
    analysis_range = window.analysis_session.analysis_range
    if reference_s is None or analysis_range is None:
        raise RuntimeError("Acceptance requires a confirmed event reference/range.")
    platform_count = 0
    for analysis in window.analysis_session.channel_analyses.values():
        detection = analysis.signal_detection_result
        measured = np.fromiter(
            (state is SignalState.MEASURED for state in detection.signal_states),
            dtype=np.bool_,
            count=len(detection.signal_states),
        )
        pre_event = (
            (detection.time_s >= analysis_range.start_time_s)
            & (detection.time_s < reference_s)
            & ~measured
        )
        before_analysis = detection.time_s < analysis_range.start_time_s
        post_invalid = (detection.time_s >= reference_s) & ~measured
        if not pre_event.any():
            raise RuntimeError("No pre-event display frames were available.")
        if not np.equal(analysis.display_velocity_m_s[pre_event], 0.0).all():
            raise RuntimeError("Pre-event display platform is incorrect.")
        if not np.isnan(analysis.display_velocity_m_s[before_analysis]).all():
            raise RuntimeError("Display platform leaked before analysis start.")
        if not np.isnan(analysis.display_velocity_m_s[post_invalid]).all():
            raise RuntimeError("Post-event invalid frames were filled.")
        platform_count += int(np.count_nonzero(pre_event))
    return platform_count


def _save_window(window: MainWindow, output_path: Path) -> None:
    if not window.grab().save(str(output_path), "PNG"):
        raise RuntimeError(f"Could not save {output_path}.")


def _gui_acceptance(
    reference_data: Path,
    new_data: Path,
    output_root: Path,
) -> dict[str, object]:
    application = create_application([], language_code="zh_CN")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    window = MainWindow(translation_manager=translation_manager())
    window.resize(1440, 900)
    window.show()

    window.set_loaded_result(_load(reference_data))
    application.processEvents()
    if window.analysis_session.event_reference_time_s != 554.668e-6:
        raise RuntimeError("Original experiment did not retain 554.668 µs.")
    _run_window(window)
    window.velocity_view.display_velocity_check.setChecked(True)
    application.processEvents()
    original_platform_count = _assert_platform(window)

    window.set_loaded_result(_load(new_data))
    application.processEvents()
    if window.analysis_session.event_reference_time_s is not None:
        raise RuntimeError("Old reference leaked into the new experiment.")
    window.workflow_navigation.setCurrentRow(1)
    window.science_tabs.setCurrentIndex(0)
    window.analysis_range_scroll.ensureWidgetVisible(
        window.analysis_range_panel.event_reference_status_label
    )
    application.processEvents()
    _save_window(window, output_root / "event_reference_invalid_new_file.png")

    _run_window(window)
    analyses = window.analysis_session.channel_analyses
    if any(
        np.isfinite(analysis.display_velocity_m_s).any()
        and not np.array_equal(
            analysis.display_velocity_m_s,
            analysis.signal_detection_result.apparent_velocity_m_s,
            equal_nan=True,
        )
        for analysis in analyses.values()
    ):
        raise RuntimeError("Unset reference unexpectedly produced a platform.")
    formal_snapshots = {
        name: analysis.signal_detection_result.apparent_velocity_m_s.copy()
        for name, analysis in analyses.items()
    }
    stft_objects = {name: analysis.stft_result for name, analysis in analyses.items()}
    analysis_range = window.analysis_session.analysis_range
    if analysis_range is None:
        raise RuntimeError("New experiment has no analysis range.")
    manual_reference_s = analysis_range.start_time_s + 0.35 * (
        analysis_range.end_time_s - analysis_range.start_time_s
    )
    window.analysis_range_panel.event_reference_spin.setValue(
        manual_reference_s * 1e6
    )
    window.analysis_range_panel.apply_event_reference_button.click()
    application.processEvents()
    if window.analysis_session.event_reference_time_s != manual_reference_s:
        raise RuntimeError("Manual event reference was not accepted.")
    new_platform_count = _assert_platform(window)
    for name, analysis in window.analysis_session.channel_analyses.items():
        np.testing.assert_array_equal(
            analysis.signal_detection_result.apparent_velocity_m_s,
            formal_snapshots[name],
        )
        if analysis.stft_result is not stft_objects[name]:
            raise RuntimeError("Manual reference caused an STFT rerun/replacement.")
    window.workflow_navigation.setCurrentRow(1)
    window.science_tabs.setCurrentIndex(0)
    window.analysis_range_scroll.ensureWidgetVisible(
        window.analysis_range_panel.event_reference_spin
    )
    application.processEvents()
    _save_window(window, output_root / "event_reference_manual_new_file.png")

    window.workflow_navigation.setCurrentRow(4)
    window.science_tabs.setCurrentIndex(3)
    window.velocity_view.fit_analysis_range_button.click()
    application.processEvents()
    expected_x = [
        analysis_range.start_time_s * 1e6,
        analysis_range.end_time_s * 1e6,
    ]
    actual_x = window.velocity_view.plot_widget.plotItem.vb.viewRange()[0]
    np.testing.assert_allclose(actual_x, expected_x, rtol=0.0, atol=1e-6)
    _save_window(window, output_root / "velocity_fit_analysis_range.png")
    window.close()
    application.processEvents()
    return {
        "original_platform_frames": original_platform_count,
        "new_manual_platform_frames": new_platform_count,
        "new_manual_reference_us": manual_reference_s * 1e6,
        "new_analysis_range_us": expected_x,
    }


def main() -> int:
    arguments = _arguments()
    output_root = Path(__file__).resolve().parent
    output_root.mkdir(parents=True, exist_ok=True)
    configuration = load_workflow_config(
        arguments.config.resolve(),
        repository_root=arguments.config.resolve().parents[1],
    )
    hashes_before = {
        path.resolve(): hashlib.sha256(path.resolve().read_bytes()).hexdigest()
        for path in arguments.data
    }
    rows: list[dict[str, object]] = []
    analyses_by_file: dict[str, dict[str, ChannelAnalysis]] = {}
    for path in arguments.data:
        loaded = _load(path)
        full_range = (
            max(record.start_time_s for record in loaded.records.values()),
            min(record.end_time_s for record in loaded.records.values()),
        )
        analysis_range = _default_range(configuration, loaded)
        reference_s = _validated_reference(
            configuration,
            loaded,
            analysis_range,
        )
        analyses = _analyze(configuration, loaded, analysis_range, reference_s)
        analyses_by_file[path.name] = analyses
        for channel_name, analysis in analyses.items():
            rows.append(
                _diagnostic_row(
                    path.name,
                    channel_name,
                    analysis,
                    full_range=full_range,
                    analysis_range=analysis_range,
                    reference_s=reference_s,
                    jump_threshold_hz=(
                        configuration.event_candidate.maximum_adjacent_frequency_step_hz
                    ),
                )
            )
    _write_diagnostics(rows, output_root)
    _spectrogram_overview(analyses_by_file, output_root)
    gui_summary = _gui_acceptance(
        arguments.reference_data.resolve(),
        arguments.new_data.resolve(),
        output_root,
    )
    application = create_application([], language_code="zh_CN")
    application.setFont(QFont("Microsoft YaHei UI", 9))
    _diagnostic_table(rows, output_root)
    application.processEvents()
    hashes_after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in hashes_before
    }
    if hashes_after != hashes_before:
        raise RuntimeError("A raw data hash changed during acceptance.")
    print(json.dumps(gui_summary, ensure_ascii=False, indent=2))
    print(output_root / "cross_file_diagnostic.md")
    print(output_root / "cross_file_diagnostic.json")
    print(output_root / "cross_file_spectrogram_overview.png")
    for filename in (
        "event_reference_invalid_new_file.png",
        "event_reference_manual_new_file.png",
        "velocity_fit_analysis_range.png",
        "cross_file_diagnostic.png",
    ):
        print(output_root / filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
