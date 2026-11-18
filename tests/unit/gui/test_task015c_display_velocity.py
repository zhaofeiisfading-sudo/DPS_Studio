from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import PRE_EVENT_DISPLAY_ORIGIN
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


def test_event_confirmation_brings_stationary_platform_into_velocity_view(
    qapp: QApplication, tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    try:
        window.set_loaded_result(_event_signal_result(tmp_path))
        _run(window)
        assert window.analysis_session.event_reference_time_s is None
        view = window.velocity_view
        window.science_tabs.setCurrentWidget(view)
        qapp.processEvents()
        plot = view.plot_widget
        assert not hasattr(view, "pre_event_platform_curve")
        x_bounds = plot.viewRange()[0]
        plot.setYRange(50.0, 450.0, padding=0.0)
        y_bounds = plot.viewRange()[1]
        zoom_x = (x_bounds[0] + 0.01, x_bounds[1] - 0.01)
        plot.setXRange(*zoom_x, padding=0.0)
        view.display_curve.setDownsampling(ds=4)

        window.analysis_range_panel.event_reference_spin.setValue(554.668)
        window.analysis_range_panel.apply_event_reference_button.click()
        qapp.processEvents()

        assert window.analysis_session.event_reference_time_s == pytest.approx(554.668e-6)
        analysis = window.analysis_session.channel_analyses[view.channel_combo.currentData()]
        platform = np.asarray(analysis.velocity_origins) == PRE_EVENT_DISPLAY_ORIGIN
        assert platform.any()
        np.testing.assert_array_equal(view.display_curve.yData[platform], 0.0)
        current_x, current_y = plot.viewRange()
        assert current_x == pytest.approx(zoom_x)
        assert current_y[0] < 0.0 < current_y[1]
        assert current_y[1] == pytest.approx(y_bounds[1])

        # A new platform level just inside the upper edge still needs clearance.
        new_level = float(int(current_y[1])) - 1.0
        window.pre_event_display_velocity_spin.setValue(new_level)
        qapp.processEvents()

        np.testing.assert_array_equal(view.display_curve.yData[platform], new_level)
        updated_x, updated_y = plot.viewRange()
        assert updated_x == pytest.approx(zoom_x)
        assert updated_y[0] == pytest.approx(current_y[0])
        assert updated_y[1] > current_y[1]

        # The platform is offscreen when zoomed entirely past the reference.
        post_event_x = (554.70, 554.74)
        plot.setXRange(*post_event_x, padding=0.0)
        plot.setYRange(50.0, 450.0, padding=0.0)
        window.pre_event_display_velocity_spin.setValue(0.0)
        qapp.processEvents()
        current_x, current_y = plot.viewRange()
        assert current_x == pytest.approx(post_event_x)
        assert current_y == pytest.approx((50.0, 450.0))
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_gui_display_parameter_refreshes_without_new_stft(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager(),
                        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    try:
        assert window.pre_event_display_velocity_spin.value() == 0.0
        assert window.pre_event_display_velocity_spin.suffix() == " m/s"
        assert "不代表正式测得速度" in (
            window.pre_event_display_velocity_spin.toolTip()
        )
        assert "事件前平台速度" in {
            label.text() for label in window.findChildren(QLabel)
        }
        window.set_loaded_result(_event_signal_result(tmp_path))
        reference_s = 554.668e-6
        window.analysis_range_panel.event_reference_spin.setValue(
            reference_s * 1e6
        )
        window.analysis_range_panel.apply_event_reference_button.click()
        qapp.processEvents()
        assert window.analysis_session.event_reference_time_s == pytest.approx(
            reference_s
        )
        _run(window)

        generation = window.analysis_session.generation_id
        original = dict(window.analysis_session.channel_analyses)
        formal = {
            name: analysis.corrected_velocity_m_s.copy()
            for name, analysis in original.items()
        }
        continuous = {
            name: analysis.continuous_corrected_velocity_m_s.copy()
            for name, analysis in original.items()
        }
        apparent = {
            name: analysis.apparent_velocity_m_s.copy()
            for name, analysis in original.items()
        }
        stft_objects = {
            name: analysis.stft_result for name, analysis in original.items()
        }
        new_starts: list[int] = []
        window._analysis_adapter.started.connect(new_starts.append)

        window.pre_event_display_check.setChecked(True)
        qapp.processEvents()
        assert window.analysis_session.generation_id == generation
        assert window.analysis_session.results_valid
        assert not new_starts
        for name, analysis in window.analysis_session.channel_analyses.items():
            measured = np.fromiter(
                (
                    state is SignalState.MEASURED
                    for state in analysis.signal_detection_result.signal_states
                ),
                dtype=np.bool_,
            )
            pre_event = analysis.stft_result.time_s < reference_s
            post_event_invalid = (
                (analysis.stft_result.time_s >= reference_s) & ~measured
            )
            assert pre_event.any()
            assert post_event_invalid.any()
            assert np.equal(analysis.display_velocity_m_s[pre_event], 0.0).all()
            post_event_measured = measured & ~pre_event
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[post_event_measured],
                formal[name][post_event_measured],
            )
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[post_event_invalid],
                continuous[name][post_event_invalid],
            )
            np.testing.assert_array_equal(
                analysis.signal_detection_result.apparent_velocity_m_s,
                apparent[name],
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
            pre_event = analysis.stft_result.time_s < reference_s
            post_event_invalid = (
                (analysis.stft_result.time_s >= reference_s) & ~measured
            )
            assert np.equal(
                analysis.display_velocity_m_s[pre_event],
                12.5,
            ).all()
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[post_event_invalid],
                continuous[name][post_event_invalid],
            )
            np.testing.assert_array_equal(
                analysis.signal_detection_result.apparent_velocity_m_s,
                apparent[name],
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
        window.deleteLater()
        qapp.processEvents()


def test_english_pre_event_display_velocity_term(qapp: QApplication, tmp_path: Path) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager,
                        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    try:
        labels = {label.text() for label in window.findChildren(QLabel)}
        assert "Pre-event platform velocity" in labels
        assert window.velocity_view.display_velocity_check.text() == (
            "Show Diagnostic Curves"
        )
        assert window.pre_event_display_check.text() == "Enable"
    finally:
        window.close()
        window.deleteLater()
        manager.install("zh_CN")
        qapp.processEvents()


def test_gui_still_does_not_import_scripts() -> None:
    gui_root = Path(__file__).resolve().parents[3] / "src" / "dps_studio" / "gui"
    for source_path in gui_root.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert "from scripts" not in source
        assert "import scripts" not in source
