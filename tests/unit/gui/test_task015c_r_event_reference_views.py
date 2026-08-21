from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dps_studio.core import EventCandidateConfig
from dps_studio.core.io import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.analysis_session import AnalysisRange, AnalysisSession
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.result_views import finite_velocity_view_range
from dps_studio.gui.state import WorkflowState


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _configuration() -> object:
    return load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)


def _record(start_s: float, end_s: float) -> SignalRecord:
    return SignalRecord(
        np.linspace(start_s, end_s, 128, dtype=np.float64),
        np.zeros(128, dtype=np.float64),
    )


def _shifted_event_result(tmp_path: Path) -> DelimitedSignalLoadResult:
    sample_count = 8192
    start_s = 744.0e-6
    time_s = start_s + np.arange(sample_count, dtype=np.float64) * 25e-12
    onset_s = start_s + 100e-9
    active = (time_s >= onset_s) & (time_s < onset_s + 80e-9)
    phase = 2.0 * np.pi * 0.5e9 * (time_s - onset_s)
    first = np.zeros(sample_count, dtype=np.float64)
    second = np.zeros(sample_count, dtype=np.float64)
    first[active] = np.sin(phase[active])
    second[active] = 0.7 * np.sin(phase[active] + 0.3)
    records = {
        "pdv_channel_1": SignalRecord(time_s, first),
        "pdv_channel_2": SignalRecord(time_s, second),
    }
    return DelimitedSignalLoadResult(
        source_path=tmp_path / "shifted_experiment.csv",
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


def _assert_view_x(
    view: object,
    expected_start_us: float,
    expected_end_us: float,
) -> None:
    plot_widget = view.plot_widget
    actual = plot_widget.plotItem.vb.viewRange()[0]
    assert actual == pytest.approx(
        [expected_start_us, expected_end_us],
        abs=1e-6,
    )


def test_general_configuration_keeps_event_reference_unset_for_every_file() -> None:
    configuration = _configuration()
    session = AnalysisSession()
    session.set_workflow_configuration(
        configuration,
        profile=configuration.analysis.default_profile,
    )

    shifted = _record(744e-6, 749e-6)
    session.load_records(source_path=Path("shifted.csv"), records={"pdv": shifted})
    assert session.event_reference_time_s is None
    assert session.rejected_event_reference_time_s is None
    session.set_analysis_range(AnalysisRange(744e-6, 749e-6))
    assert session.set_event_reference_time_s(746e-6)
    assert session.event_reference_time_s == pytest.approx(746e-6)

    original_domain = _record(553.96025426e-6, 555.96022926e-6)
    session.load_records(
        source_path=Path("original.csv"),
        records={"pdv": original_domain},
    )
    assert session.event_reference_time_s is None
    assert session.event_reference_source is None


def test_gui_reference_candidates_and_result_view_fit(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        result = _shifted_event_result(tmp_path)
        window.set_loaded_result(result)
        qapp.processEvents()
        assert window.analysis_session.event_reference_time_s is None
        assert window.analysis_range_panel.confirmed_event_reference_s is None
        reference_status = window.analysis_range_panel.event_reference_status_label.text()
        assert "自动起跳时间尚未生成" in reference_status
        assert "554.668" not in reference_status

        full_start_s, full_end_s = window.analysis_session.data_bounds_s()
        analysis_start_s = full_start_s + 20e-9
        analysis_end_s = full_end_s - 20e-9
        assert window.analysis_range_panel.confirm_range_s(
            analysis_start_s,
            analysis_end_s,
        )
        manual_reference_s = full_start_s + 60e-9
        window.analysis_range_panel.event_reference_spin.setValue(
            manual_reference_s * 1e6
        )
        window.analysis_range_panel.apply_event_reference_button.click()
        window.velocity_view.display_velocity_check.setChecked(True)
        qapp.processEvents()
        assert window.analysis_session.event_reference_time_s == pytest.approx(
            manual_reference_s
        )

        _run(window)
        analyses = window.analysis_session.channel_analyses
        assert window.analysis_session.event_reference_time_s == pytest.approx(
            manual_reference_s
        )
        assert all(
            analysis.event_aware_continuity_result.event_reference_time_s
            == pytest.approx(manual_reference_s)
            for analysis in analyses.values()
        )
        assert all(
            analysis.event_aware_continuity_result.event_reference_source == "manual"
            for analysis in analyses.values()
        )
        assert window.analysis_session.set_event_reference_time_s(
            manual_reference_s,
            source="manual_review",
        )
        analyses = window.analysis_session.channel_analyses
        assert all(
            analysis.event_aware_continuity_result.event_reference_source
            == "manual_review"
            for analysis in analyses.values()
        )
        assert set(window.analysis_range_panel.candidate_buttons) == set(analyses)
        candidate_tooltip = next(
            iter(window.analysis_range_panel.candidate_buttons.values())
        ).toolTip()
        assert "必须由用户显式采用" in candidate_tooltip

        expected_start_us = analysis_start_s * 1e6
        expected_end_us = analysis_end_s * 1e6
        for view in (
            window.spectrogram_view,
            window.ridge_view,
            window.comparison_view,
        ):
            _assert_view_x(view, expected_start_us, expected_end_us)
        _assert_view_x(
            window.velocity_view,
            (analysis_start_s - manual_reference_s) * 1e6,
            (analysis_end_s - manual_reference_s) * 1e6,
        )

        raw_x = window.raw_signal_view.plot_widget.plotItem.vb.viewRange()[0]
        assert raw_x[0] <= full_start_s * 1e6
        assert raw_x[1] >= full_end_s * 1e6
        assert raw_x[1] - raw_x[0] > expected_end_us - expected_start_us

        first_name = next(iter(analyses))
        first = analyses[first_name]
        expected_y = finite_velocity_view_range(
            (
                first.signal_detection_result.apparent_velocity_m_s,
                first.display_velocity_m_s,
            )
        )
        assert expected_y is not None
        actual_y = window.velocity_view.plot_widget.plotItem.vb.viewRange()[1]
        assert actual_y == pytest.approx(expected_y)

        formal = {
            name: analysis.signal_detection_result.apparent_velocity_m_s.copy()
            for name, analysis in analyses.items()
        }
        generation = window.analysis_session.generation_id
        first_button = window.analysis_range_panel.candidate_buttons[first_name]
        candidate_s = analyses[first_name].stream_event_candidates.primary_candidate_time_s
        assert candidate_s is not None
        first_button.click()
        qapp.processEvents()
        assert window.analysis_session.event_reference_time_s == pytest.approx(
            candidate_s
        )
        assert window.analysis_session.event_reference_source == (
            f"user_adopted:automatic_primary:{first_name}"
        )
        assert window.analysis_session.generation_id == generation
        for name, analysis in window.analysis_session.channel_analyses.items():
            np.testing.assert_array_equal(
                analysis.signal_detection_result.apparent_velocity_m_s,
                formal[name],
            )
            measured = np.fromiter(
                (
                    state is SignalState.MEASURED
                    for state in analysis.signal_detection_result.signal_states
                ),
                dtype=np.bool_,
            )
            pre_event = (
                (analysis.stft_result.time_s >= analysis_start_s)
                & (analysis.stft_result.time_s < candidate_s)
                & ~measured
            )
            before_analysis = analysis.stft_result.time_s < analysis_start_s
            post_event_invalid = (
                (analysis.stft_result.time_s >= candidate_s) & ~measured
            )
            assert pre_event.any()
            assert np.equal(analysis.display_velocity_m_s[pre_event], 0.0).all()
            assert np.isnan(
                analysis.display_velocity_m_s[before_analysis]
            ).all()
            assert np.isnan(
                analysis.display_velocity_m_s[post_event_invalid]
            ).all()

        manual_x = (expected_start_us + 0.01, expected_start_us + 0.03)
        manual_y = (-2.0, 2.0)
        window.velocity_view.plot_widget.setXRange(*manual_x, padding=0.0)
        window.velocity_view.plot_widget.setYRange(*manual_y, padding=0.0)
        window.pre_event_display_velocity_spin.setValue(12.5)
        qapp.processEvents()
        view_range = window.velocity_view.plot_widget.plotItem.vb.viewRange()
        assert view_range[0] == pytest.approx(manual_x)
        assert view_range[1] == pytest.approx(manual_y)

        window.velocity_view.fit_analysis_range_button.click()
        _assert_view_x(
            window.velocity_view,
            (analysis_start_s - candidate_s) * 1e6,
            (analysis_end_s - candidate_s) * 1e6,
        )
        current = window.analysis_session.channel_analyses[first_name]
        expected_refit_y = finite_velocity_view_range(
            (
                current.signal_detection_result.apparent_velocity_m_s,
                current.display_velocity_m_s,
            )
        )
        assert window.velocity_view.plot_widget.plotItem.vb.viewRange()[
            1
        ] == pytest.approx(expected_refit_y)

        window.velocity_view.plot_widget.setXRange(*manual_x, padding=0.0)
        window.velocity_view.channel_combo.setCurrentIndex(1)
        qapp.processEvents()
        _assert_view_x(
            window.velocity_view,
            (analysis_start_s - candidate_s) * 1e6,
            (analysis_end_s - candidate_s) * 1e6,
        )
    finally:
        window.close()
        qapp.processEvents()


def test_one_click_uses_ch1_shared_event_and_working_curves(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_shifted_event_result(tmp_path))
        window.analysis_range_panel.use_full_range()
        qapp.processEvents()

        _run(window)
        session = window.analysis_session
        analyses = session.channel_analyses
        ch1 = analyses["pdv_channel_1"]
        expected_event_s = ch1.stream_event_candidates.primary_candidate_time_s
        expected_source_fragment = "automatic_formal_event"
        if expected_event_s is None:
            expected_event_s = (
                ch1.signal_detection_result.detected_event_candidate_time_s
            )
            expected_source_fragment = "automatic_low_confidence_fallback"
        assert expected_event_s is not None
        assert set(session.automatic_event_reference_times_s.values()) == {
            expected_event_s
        }
        assert all(
            session.resolved_event_time_s(name) == pytest.approx(expected_event_s)
            for name in analyses
        )
        assert all(
            expected_source_fragment in (session.resolved_event_source(name) or "")
            for name in analyses
        )
        assert all(
            analysis.signal_detection_result.manual_event_reference_time_s
            == pytest.approx(expected_event_s)
            for analysis in analyses.values()
        )
        for analysis in analyses.values():
            pre_event = analysis.stft_result.time_s < expected_event_s
            assert pre_event.any()
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[pre_event],
                0.0,
            )
            assert np.isfinite(analysis.working_frequency_hz[pre_event]).all()

        np.testing.assert_array_equal(
            window.ridge_view.refined_curve.yData,
            analyses["pdv_channel_1"].working_frequency_hz * 1e-9,
        )
        np.testing.assert_array_equal(
            window.ridge_view.formal_curve.yData,
            analyses[
                "pdv_channel_1"
            ].signal_detection_result.refined_frequency_hz
            * 1e-9,
        )
        assert window.velocity_view.display_velocity_check.isChecked()

        manual_event_s = expected_event_s + 2.0e-9
        assert session.set_event_reference_time_s(
            manual_event_s,
            source="manual_task016r6",
        )
        _run(window)
        assert session.event_reference_time_s == pytest.approx(manual_event_s)
        assert session.event_reference_source == "manual_task016r6"
        assert all(
            analysis.signal_detection_result.manual_event_reference_time_s
            == pytest.approx(manual_event_s)
            for analysis in session.channel_analyses.values()
        )
    finally:
        window.close()
        qapp.processEvents()


def test_one_click_marks_existing_ch1_detector_candidate_as_event_fallback(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(_shifted_event_result(tmp_path))
        session = window.analysis_session
        assert session.run_configuration is not None
        session.run_configuration = replace(
            session.run_configuration,
            event_candidate_config=EventCandidateConfig(
                minimum_segment_frames=100,
            ),
        )
        window.analysis_range_panel.use_full_range()
        qapp.processEvents()

        _run(window)
        ch1 = session.channel_analyses["pdv_channel_1"]
        assert ch1.stream_event_candidates.primary_candidate_time_s is None
        fallback_s = (
            ch1.signal_detection_result.detected_event_candidate_time_s
        )
        assert fallback_s is not None
        assert set(session.automatic_event_reference_times_s.values()) == {
            fallback_s
        }
        assert all(
            "automatic_low_confidence_fallback:pdv_channel_1"
            == session.resolved_event_source(name)
            for name in session.channel_analyses
        )
        for analysis in session.channel_analyses.values():
            pre_event = analysis.stft_result.time_s < fallback_s
            assert pre_event.any()
            np.testing.assert_array_equal(
                analysis.display_velocity_m_s[pre_event],
                0.0,
            )
    finally:
        window.close()
        qapp.processEvents()


def test_english_reference_and_fit_terms(qapp: QApplication) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        labels = {label.text() for label in window.findChildren(QLabel)}
        assert "Event time" in labels
        assert "Manual event time" in labels
        assert window.spectrogram_view.fit_analysis_range_button.text() == (
            "Fit Analysis Range"
        )
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_cross_file_raw_hashes_and_gui_script_boundary_are_stable() -> None:
    expected = {
        "20260607.csv": (
            "AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353"
        ),
        "20260630-1.csv": (
            "203B182E477E1E08214551977A00313EAF6F17A71391D83875F6F879DC3A0A74"
        ),
        "20260630-2.csv": (
            "C0C31B2990EAE228B21594276D030B83600A7DDB98C1953842E4CB80C17FA261"
        ),
        "20260701.csv": (
            "5CCB6530E0CC715E4A7A81327C625FCE267A8B3473C0487479366EAD9D9A952A"
        ),
    }
    for filename, expected_hash in expected.items():
        data = (REPOSITORY_ROOT / "data" / "raw" / filename).read_bytes()
        assert hashlib.sha256(data).hexdigest().upper() == expected_hash

    gui_root = REPOSITORY_ROOT / "src" / "dps_studio" / "gui"
    for source_path in gui_root.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert "from scripts" not in source
        assert "import scripts" not in source
