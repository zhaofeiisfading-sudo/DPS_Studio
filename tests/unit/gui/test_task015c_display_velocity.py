from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def _event_signal_result(tmp_path: Path) -> DelimitedSignalLoadResult:
    sample_count = 8192
    time_s = 554.58e-6 + np.arange(sample_count, dtype=np.float64) * 25e-12
    reference_s = 554.668e-6
    active = (time_s >= reference_s) & (time_s < reference_s + 80e-9)
    phase = 2.0 * np.pi * 0.5e9 * (time_s - reference_s)
    first = np.zeros(sample_count, dtype=np.float64)
    second = np.zeros(sample_count, dtype=np.float64)
    first[active] = np.sin(phase[active])
    second[active] = 0.7 * np.sin(phase[active] + 0.3)
    records = {
        "pdv_channel_1": SignalRecord(time_s, first),
        "pdv_channel_2": SignalRecord(time_s, second),
    }
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "user_selected_event_signal.csv",
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


def _run(window: MainWindow) -> None:
    loop = QEventLoop()
    failures: list[str] = []
    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(
        lambda _generation, error_type, message, _traceback: (
            failures.append(f"{error_type}: {message}"),
            loop.quit(),
        )
    )
    assert window.run_automatic_analysis()
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    assert not failures
    assert window.workflow_state is WorkflowState.RESULT_READY


def test_gui_display_parameter_refreshes_without_new_stft(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.pre_event_display_velocity_spin.value() == 0.0
        assert window.pre_event_display_velocity_spin.suffix() == " m/s"
        assert "不修改正式表观速度" in (
            window.pre_event_display_velocity_spin.toolTip()
        )
        assert "事件前显示速度" in {
            label.text() for label in window.findChildren(QLabel)
        }
        window.set_loaded_result(_event_signal_result(tmp_path))
        _run(window)

        generation = window.analysis_session.generation_id
        original = dict(window.analysis_session.channel_analyses)
        formal = {
            name: analysis.signal_detection_result.apparent_velocity_m_s.copy()
            for name, analysis in original.items()
        }
        stft_objects = {
            name: analysis.stft_result for name, analysis in original.items()
        }
        new_starts: list[int] = []
        window._analysis_adapter.started.connect(new_starts.append)

        window.velocity_view.display_velocity_check.setChecked(True)
        qapp.processEvents()
        assert window.analysis_session.generation_id == generation
        assert window.analysis_session.results_valid
        assert not new_starts
        reference_s = 554.668e-6
        for name, analysis in window.analysis_session.channel_analyses.items():
            measured = np.fromiter(
                (
                    state is SignalState.MEASURED
                    for state in analysis.signal_detection_result.signal_states
                ),
                dtype=np.bool_,
            )
            pre_event = (analysis.stft_result.time_s < reference_s) & ~measured
            post_event_invalid = (
                (analysis.stft_result.time_s >= reference_s) & ~measured
            )
            assert pre_event.any()
            assert post_event_invalid.any()
            assert np.equal(analysis.display_velocity_m_s[pre_event], 0.0).all()
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[measured],
                formal[name][measured],
            )
            assert np.isnan(
                analysis.display_velocity_m_s[post_event_invalid]
            ).all()
            np.testing.assert_array_equal(
                analysis.signal_detection_result.apparent_velocity_m_s,
                formal[name],
            )
            assert analysis.stft_result is stft_objects[name]

        window.pre_event_display_velocity_spin.setValue(12.5)
        qapp.processEvents()
        assert window.analysis_session.generation_id == generation
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert not new_starts
        for name, analysis in window.analysis_session.channel_analyses.items():
            measured = np.fromiter(
                (
                    state is SignalState.MEASURED
                    for state in analysis.signal_detection_result.signal_states
                ),
                dtype=np.bool_,
            )
            pre_event = (analysis.stft_result.time_s < reference_s) & ~measured
            post_event_invalid = (
                (analysis.stft_result.time_s >= reference_s) & ~measured
            )
            assert np.equal(
                analysis.display_velocity_m_s[pre_event],
                12.5,
            ).all()
            assert np.isnan(
                analysis.display_velocity_m_s[post_event_invalid]
            ).all()
            np.testing.assert_array_equal(
                analysis.signal_detection_result.apparent_velocity_m_s,
                formal[name],
            )
            assert analysis.stft_result is stft_objects[name]
        assert window.velocity_view.display_curve is not None
        assert window.velocity_view.display_curve.opts["connect"] == "finite"

        window.pre_event_display_velocity_spin.setValue(0.0)
        qapp.processEvents()
        assert window.analysis_session.generation_id == generation
        assert not new_starts
    finally:
        window.close()
        qapp.processEvents()


def test_english_pre_event_display_velocity_term(qapp: QApplication) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        labels = {label.text() for label in window.findChildren(QLabel)}
        assert "Pre-event Display Velocity" in labels
        assert window.velocity_view.display_velocity_check.text() == (
            "Display Velocity (Non-formal Result)"
        )
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_gui_still_does_not_import_scripts() -> None:
    gui_root = Path(__file__).resolve().parents[3] / "src" / "dps_studio" / "gui"
    for source_path in gui_root.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert "from scripts" not in source
        assert "import scripts" not in source
