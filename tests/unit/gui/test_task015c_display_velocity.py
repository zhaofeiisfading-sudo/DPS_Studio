from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.result_views import display_velocity_connector_points
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
        assert view.pre_event_platform_curve is None
        x_bounds, y_bounds = plot.viewRange()
        assert y_bounds[0] > 50.0
        zoom_x = (x_bounds[0] + 0.01, x_bounds[1] - 0.01)
        plot.setXRange(*zoom_x, padding=0.0)

        window.analysis_range_panel.event_reference_spin.setValue(554.668)
        window.analysis_range_panel.apply_event_reference_button.click()
        qapp.processEvents()

        assert window.analysis_session.event_reference_time_s == pytest.approx(554.668e-6)
        assert view.pre_event_platform_curve is not None
        assert view.pre_event_platform_curve.dataBounds(1) == (0.0, 0.0)
        current_x, current_y = plot.viewRange()
        assert current_x == pytest.approx(zoom_x)
        assert current_y[0] < 0.0 < current_y[1]
        assert current_y[1] == pytest.approx(y_bounds[1])

        # A new platform level just inside the upper edge still needs clearance.
        new_level = float(int(current_y[1])) - 1.0
        window.pre_event_display_velocity_spin.setValue(new_level)
        qapp.processEvents()

        assert view.pre_event_platform_curve.dataBounds(1) == (new_level, new_level)
        updated_x, updated_y = plot.viewRange()
        assert updated_x == pytest.approx(zoom_x)
        assert updated_y[0] == pytest.approx(current_y[0])
        assert updated_y[1] > current_y[1]
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
            platform = np.asarray(analysis.velocity_origins) == "pre_event_display_platform"
            assert platform.any()
            assert pre_event[platform].all()
            assert np.equal(analysis.display_velocity_m_s[platform], 0.0).all()
            assert np.isnan(analysis.display_velocity_m_s[pre_event & ~platform & ~measured]).all()
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[measured],
                formal[name][measured],
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
            platform = np.asarray(analysis.velocity_origins) == "pre_event_display_platform"
            assert platform.any()
            assert pre_event[platform].all()
            assert np.equal(
                analysis.display_velocity_m_s[platform],
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

        selected = window.analysis_session.channel_analyses[window.velocity_view.channel_combo.currentData()]
        np.testing.assert_array_equal(window.velocity_view.display_curve.yData, selected.corrected_velocity_m_s)
        stationary = np.asarray(selected.velocity_origins) == "pre_event_display_platform"
        curve = window.velocity_view.pre_event_platform_curve
        assert curve.opts["connect"] == "finite"
        np.testing.assert_array_equal(np.isfinite(curve.yData), stationary)
        assert "未确定" in window.velocity_view.source_notice.text()

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

def test_connector_requires_adjacent_stationary_and_measured_frames(tmp_path: Path) -> None:
    from dps_studio.core.workflow import analyze_configuration

    record = _event_signal_result(tmp_path).records["pdv_channel_1"]
    analysis = analyze_configuration(
        {"pdv": record}, window_length_samples=256, overlap_samples=128, nfft=1024,
        window_name="hann", minimum_frequency_hz=50e6, maximum_frequency_hz=6e9,
        vacuum_wavelength_m=1.55e-6,
    )["pdv"]
    time = analysis.stft_result.time_s
    first = int(np.flatnonzero(np.isfinite(analysis.corrected_velocity_m_s))[0])
    assert first >= 2
    origins = list(analysis.velocity_origins)
    origins[first - 1] = "pre_event_display_platform"
    display = analysis.plot_velocity_m_s.copy()
    display[first - 1] = 0.0
    active = replace(
        analysis, velocity_origins=tuple(origins), display_velocity_m_s=display,
        signal_detection_result=replace(analysis.signal_detection_result,
                                        manual_event_reference_time_s=float(time[first])),
    )
    connector = display_velocity_connector_points(active)
    assert connector is not None
    np.testing.assert_array_equal(connector[0], time[first - 1:first + 1] * 1e6)
    np.testing.assert_array_equal(connector[1], [0.0, analysis.corrected_velocity_m_s[first]])
    origins[first - 2:first] = ["pre_event_display_platform", "ambiguous_peak"]
    display[first - 2:first] = [0.0, np.nan]
    assert display_velocity_connector_points(
        replace(active, velocity_origins=tuple(origins), display_velocity_m_s=display)
    ) is None
