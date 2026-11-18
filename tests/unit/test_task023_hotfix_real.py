"""Real balanced-profile regressions through event selection, plotting and CSV export."""

import csv
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QEventLoop, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.workflow import PRE_EVENT_DISPLAY_ORIGIN, ChannelAnalysis
from dps_studio.core.workflow.acceleration import channel_acceleration
from dps_studio.gui.analysis_session import EventTimeSource
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.release_workflow_smoke import audit_derivative

ROOT = Path(__file__).resolve().parents[2]


def _check_export(window: MainWindow, directory: Path, analysis: ChannelAnalysis) -> None:
    directory.mkdir()
    window._set_export_output_directory(directory)
    assert window.export_include_pre_event_check.isChecked()
    assert not window.export_quality_passed_check.isChecked()
    assert window._export_current_result()

    concise, detail = sorted(directory.glob("*.csv"))
    with concise.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    np.testing.assert_array_equal([float(r["time_s"]) for r in rows], analysis.stft_result.time_s)
    np.testing.assert_array_equal([float(r["display_velocity_m_s"]) for r in rows],
                                  analysis.plot_velocity_m_s)
    with detail.open(encoding="utf-8", newline="") as handle:
        assert tuple(r["velocity_origin"] for r in csv.DictReader(handle)) == analysis.velocity_origins


@pytest.mark.parametrize(("filename", "column", "frames"), [
    ("20260607.csv", 1, 620), ("20260630-1.csv", 2, 1557),
])
def test_real_default_and_active_platform(filename: str, column: int, frames: int, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["task023", "-platform", "offscreen"])
    window = MainWindow(settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    name = f"pdv_channel_{column}"
    try:
        loaded = read_delimited_signals(
            ROOT / "data/raw" / filename, time_column=0, voltage_columns={name: column},
            delimiter=",", has_header=False, encoding="utf-8", time_scale=1.0,
            voltage_scales={name: 1.0},
        )
        window.set_loaded_result(loaded)
        panel = window.analysis_range_panel
        panel.use_full_range()
        loop = QEventLoop()
        window._analysis_adapter.finished.connect(loop.quit)
        window._analysis_adapter.failed.connect(loop.quit)
        QTimer.singleShot(30_000, loop, loop.quit)
        assert window.run_automatic_analysis()
        loop.exec()
        session = window.analysis_session
        assert session.results_valid
        original = session.channel_analyses[name]
        time = original.stft_result.time_s
        candidate = session.automatic_event_reference_times_s[name]
        assert candidate is not None and time[1] < candidate < time[-2]
        assert time.size == frames
        assert session.event_time_source is EventTimeSource.UNSET
        assert original.signal_detection_result.manual_event_reference_time_s is None
        assert PRE_EVENT_DISPLAY_ORIGIN not in original.velocity_origins
        assert np.isfinite(original.working_frequency_hz).all()
        assert np.isfinite(original.plot_velocity_m_s).all()
        np.testing.assert_array_equal(original.plot_velocity_m_s, original.continuous_corrected_velocity_m_s)
        assert np.any(original.plot_velocity_m_s[time < candidate] > 0.0)
        assert audit_derivative(original)["finite_derivatives"] == frames
        _check_export(window, tmp_path / "unset", original)

        view = window.velocity_view
        window.science_tabs.setCurrentWidget(view)
        assert not hasattr(view, "pre_event_platform_curve")
        assert window.pre_event_display_check.isChecked()
        for source in (EventTimeSource.AUTOMATIC, EventTimeSource.MANUAL):
            panel.unset_event_time_radio.click()
            x_bounds = (time[1] * 1e6, time[-2] * 1e6)
            view.plot_widget.setXRange(*x_bounds, padding=0)
            view.plot_widget.setYRange(50.0, 500.0, padding=0)
            if source is EventTimeSource.AUTOMATIC:
                panel.automatic_event_time_radio.click()
            else:
                panel.event_reference_spin.setValue(time[frames // 2] * 1e6)
                panel.apply_event_reference_button.click()
            app.processEvents()
            active = session.channel_analyses[name]
            reference = active.signal_detection_result.manual_event_reference_time_s
            assert session.event_time_source is source
            expected_reference = candidate if source is EventTimeSource.AUTOMATIC else time[frames // 2]
            assert reference == pytest.approx(expected_reference, rel=0.0, abs=1e-12)
            before = time < reference
            np.testing.assert_array_equal(np.asarray(active.velocity_origins) == PRE_EVENT_DISPLAY_ORIGIN, before)
            np.testing.assert_array_equal(active.continuous_corrected_velocity_m_s, original.plot_velocity_m_s)
            np.testing.assert_array_equal(active.plot_velocity_m_s, np.where(before, 0.0, original.plot_velocity_m_s))
            curve = view.display_curve
            np.testing.assert_array_equal(curve.yData, active.plot_velocity_m_s)
            pen = curve.opts["pen"]
            assert pen.color().name().upper() == "#6C5CE7"
            assert pen.widthF() == pytest.approx(2.2) and pen.style() == Qt.PenStyle.SolidLine
            assert curve.opts["connect"] == "finite"
            if view.display_connector is not None:
                assert view.display_connector.opts["pen"].color() == pen.color()
            x_range, y_range = view.plot_widget.viewRange()
            assert x_range == pytest.approx(x_bounds)
            assert y_range == pytest.approx([-37.5, 500.0])
            acceleration = channel_acceleration(active).acceleration_m_s2
            first_post = int(np.searchsorted(time, reference))
            np.testing.assert_array_equal(acceleration[:first_post - 1], 0.0)
            assert acceleration[first_post - 1] > 0.0
            assert audit_derivative(active)["finite_derivatives"] == frames
            _check_export(window, tmp_path / source.value, active)
    finally:
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
