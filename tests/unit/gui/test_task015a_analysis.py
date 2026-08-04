from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QFileIconProvider

from dps_studio.core.analysis_profiles import AnalysisProfileId
from dps_studio.core.models import SignalRecord
from dps_studio.core.workflow import ChannelAnalysis, load_workflow_config
from dps_studio.gui import analysis_adapter, native_icons
from dps_studio.gui.analysis_adapter import (
    AnalysisRequest,
    AnalysisRunResult,
    AutomaticAnalysisAdapter,
)
from dps_studio.gui.analysis_range import AnalysisRangePanel
from dps_studio.gui.analysis_session import AnalysisRange, AnalysisSession
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.raw_signal_view import RawSignalView
from dps_studio.gui.result_views import relative_magnitude_db
from dps_studio.gui.state import WorkflowState


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "demo_dual_profile.toml"


def _configuration() -> Any:
    return load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)


def _synthetic_load_result(tmp_path: Path) -> tuple[Any, bytes]:
    sample_count = 4096
    time_s = 5.54e-4 + np.arange(sample_count, dtype=np.float64) * 25e-12
    phase = 2.0 * np.pi * 0.5e9 * (time_s - time_s[0])
    values = np.column_stack((time_s, np.sin(phase), 0.7 * np.sin(phase + 0.3)))
    source = tmp_path / "two_channel_pdv.csv"
    np.savetxt(source, values, delimiter=",", fmt="%.17e")
    before = source.read_bytes()
    request = SignalLoadRequest(
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
    return DataImportController().load(request), before


def _prepare_window(
    qapp: QApplication,
    tmp_path: Path,
) -> tuple[MainWindow, bytes]:
    result, source_before = _synthetic_load_result(tmp_path)
    window = MainWindow(translation_manager=translation_manager())
    window.set_loaded_result(result)
    window.set_analysis_configuration(_configuration())
    window.analysis_range_panel.use_full_range()
    qapp.processEvents()
    return window, source_before


def _run_window_analysis(window: MainWindow) -> None:
    loop = QEventLoop()
    timed_out = {"value": False}

    def timeout() -> None:
        timed_out["value"] = True
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(lambda *_args: loop.quit())
    QTimer.singleShot(10_000, timeout)
    assert window.run_automatic_analysis()
    loop.exec()
    assert not timed_out["value"]


def test_native_directory_icon_has_fallback_and_toolbar_is_compact(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_icon(_self: QFileIconProvider, _info: object) -> object:
        raise RuntimeError("simulated shell icon failure")

    monkeypatch.setattr(QFileIconProvider, "icon", fail_icon)
    assert not native_icons.native_directory_icon().isNull()
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.main_toolbar.iconSize().width() == 20
        assert window.main_toolbar.iconSize().height() == 20
        assert window.action_open_data.text() == "打开数据…"
    finally:
        window.close()
        qapp.processEvents()


def test_analysis_range_uses_seconds_internally_and_clamps_to_bounds(
    qapp: QApplication,
) -> None:
    panel = AnalysisRangePanel()
    received: list[tuple[float, float]] = []
    panel.range_confirmed.connect(lambda start, end: received.append((start, end)))
    try:
        panel.set_data_bounds(1e-6, 5e-6)
        assert panel.start_spin.value() == pytest.approx(1.0)
        assert panel.end_spin.value() == pytest.approx(5.0)
        assert panel.confirm_range_s(-10e-6, 3e-6)
        assert received[-1] == pytest.approx((1e-6, 3e-6))
        assert panel.draft_range_s == pytest.approx((1e-6, 3e-6))
        assert not panel.confirm_range_s(4e-6, 3e-6)
    finally:
        panel.close()
        qapp.processEvents()


def test_raw_signal_region_and_numeric_draft_are_bidirectional(
    qapp: QApplication,
) -> None:
    record = SignalRecord(
        np.linspace(1e-6, 5e-6, 128),
        np.linspace(-1.0, 1.0, 128),
    )
    view = RawSignalView()
    emitted: list[tuple[float, float]] = []
    view.analysis_region_changed.connect(
        lambda start, end: emitted.append((start, end))
    )
    try:
        view.set_records(MappingProxyType({"pdv": record}))
        view.analysis_region.setRegion((2.0, 4.0))
        qapp.processEvents()
        assert emitted[-1] == pytest.approx((2e-6, 4e-6))
        view.set_analysis_region_s(-1.0, 10.0)
        start_us, end_us = view.analysis_region.getRegion()
        assert start_us == pytest.approx(1.0)
        assert end_us == pytest.approx(5.0)
    finally:
        view.close()
        qapp.processEvents()


def test_background_adapter_calls_public_workflow_outside_gui_thread(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SignalRecord(np.arange(1024) * 1e-10, np.ones(1024))
    records = MappingProxyType({"a": record, "b": record})
    session = AnalysisSession(records=records)
    configuration = _configuration()
    session.set_workflow_configuration(
        configuration,
        profile=configuration.analysis.profiles[0],
    )
    observed: dict[str, object] = {}

    def fake_analyze_profile(
        received: Mapping[str, SignalRecord],
        **_kwargs: object,
    ) -> Mapping[str, ChannelAnalysis]:
        observed["channels"] = tuple(received)
        observed["thread"] = QThread.currentThread()
        return MappingProxyType({})

    monkeypatch.setattr(analysis_adapter, "analyze_profile", fake_analyze_profile)
    assert session.run_configuration is not None
    adapter = AutomaticAnalysisAdapter()
    loop = QEventLoop()
    result_holder: list[AnalysisRunResult] = []

    def finished(value: object) -> None:
        assert isinstance(value, AnalysisRunResult)
        result_holder.append(value)
        loop.quit()

    adapter.finished.connect(finished)
    request = AnalysisRequest(
        session.generation_id,
        records,
        AnalysisRange(record.start_time_s, record.end_time_s),
        session.run_configuration,
    )
    assert adapter.start(request)
    assert not adapter.start(request)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert result_holder
    assert observed["channels"] == ("a", "b")
    assert observed["thread"] is not qapp.thread()
    assert not adapter.busy


def test_full_gui_analysis_uses_real_core_arrays_and_reaches_result_ready(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, source_before = _prepare_window(qapp, tmp_path)
    try:
        assert window.workflow_state is WorkflowState.RANGE_DEFINED
        assert window.run_analysis_button.isEnabled()
        _run_window_analysis(window)
        assert window.workflow_state is WorkflowState.RESULT_READY
        assert window.analysis_session.results_valid
        analyses = window.analysis_session.channel_analyses
        assert tuple(analyses) == ("pdv_channel_1", "pdv_channel_2")
        assert all(window.science_tabs.isTabEnabled(index) for index in range(5))

        current = analyses["pdv_channel_1"]
        expected_image = relative_magnitude_db(current, floor_db=-60.0)
        np.testing.assert_array_equal(
            window.spectrogram_view.current_image_db,
            expected_image,
        )
        assert window.ridge_view.formal_curve is not None
        _ridge_x, ridge_y = window.ridge_view.formal_curve.getData()
        np.testing.assert_array_equal(
            ridge_y,
            current.signal_detection_result.refined_frequency_hz * 1e-9,
        )
        assert window.ridge_view.formal_curve.opts["connect"] == "finite"
        assert window.velocity_view.formal_curve is not None
        _velocity_x, velocity_y = window.velocity_view.formal_curve.getData()
        np.testing.assert_array_equal(
            velocity_y,
            current.signal_detection_result.apparent_velocity_m_s,
        )
        assert set(window.comparison_view.curves) == set(analyses)
        assert not window.velocity_view.corrected_velocity_control.isEnabled()
        assert window.quality_summary.table.rowCount() == 2
        assert all(not record.time_s.flags.writeable for record in window.load_result.records.values())
        assert all(
            not record.voltage_v.flags.writeable
            for record in window.load_result.records.values()
        )
        assert window.load_result.source_path.read_bytes() == source_before
        generation = window.analysis_session.generation_id
        window.vacuum_wavelength_spin.setValue(1550.12)
        qapp.processEvents()
        assert window.analysis_session.generation_id > generation
        assert not window.analysis_session.results_valid
        assert window.workflow_state is WorkflowState.STFT_READY
        assert window.analysis_session.run_configuration is not None
        assert window.analysis_session.run_configuration.vacuum_wavelength_m == (
            pytest.approx(1.55012e-6)
        )
    finally:
        window.close()
        qapp.processEvents()


def test_confirmed_range_change_invalidates_and_hides_old_results(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, _source_before = _prepare_window(qapp, tmp_path)
    try:
        _run_window_analysis(window)
        start, end = window.analysis_session.data_bounds_s()
        assert window.analysis_range_panel.confirm_range_s(start, end - 1e-9)
        assert window.workflow_state is WorkflowState.RANGE_DEFINED
        assert not window.analysis_session.results_valid
        assert window.spectrogram_view.current_image_db is None
        assert not window.science_tabs.isTabEnabled(1)
        assert "重新" in window.analysis_status_label.text()
    finally:
        window.close()
        qapp.processEvents()


def test_profile_change_invalidates_and_hides_old_results(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, _source_before = _prepare_window(qapp, tmp_path)
    try:
        _run_window_analysis(window)
        # This fixture intentionally loads configs/demo_dual_profile.toml.
        assert window.profile_combo.count() == 2
        assert (
            window.profile_combo.itemData(1).profile_id
            is AnalysisProfileId.HIGH_TIME_RESOLUTION
        )
        window.profile_combo.setCurrentIndex(1)
        qapp.processEvents()
        assert window.workflow_state is WorkflowState.RANGE_DEFINED
        assert not window.analysis_session.results_valid
        assert window.spectrogram_view.current_image_db is None
        assert not window.science_tabs.isTabEnabled(1)
    finally:
        window.close()
        qapp.processEvents()


def test_background_failure_restores_operable_window(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _source_before = _prepare_window(qapp, tmp_path)

    def fail_analysis(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated analysis failure")

    monkeypatch.setattr(analysis_adapter, "analyze_profile", fail_analysis)
    loop = QEventLoop()
    window._analysis_adapter.failed.connect(lambda *_args: loop.quit())
    try:
        assert window.run_automatic_analysis()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        assert not window._analysis_adapter.busy
        assert window.workflow_state is WorkflowState.RANGE_DEFINED
        assert "RuntimeError" in window.analysis_status_label.text()
        assert window.run_analysis_button.isEnabled()
    finally:
        window.close()
        qapp.processEvents()


def test_gui_imports_no_scripts_and_adapter_uses_public_workflow() -> None:
    gui_root = REPOSITORY_ROOT / "src" / "dps_studio" / "gui"
    forbidden = re.compile(r"^\s*(?:from|import)\s+scripts\b", re.MULTILINE)
    for source_path in gui_root.glob("*.py"):
        assert forbidden.search(source_path.read_text(encoding="utf-8")) is None
    adapter_source = (gui_root / "analysis_adapter.py").read_text(encoding="utf-8")
    assert "analyze_configuration," in adapter_source
    assert "analyze_profile," in adapter_source


def test_repository_raw_data_hash_is_stable_during_gui_tests() -> None:
    source = REPOSITORY_ROOT / "data" / "raw" / "20260607.csv"
    assert hashlib.sha256(source.read_bytes()).hexdigest().upper() == (
        "AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353"
    )


def test_english_translation_covers_new_range_and_analysis_controls(
    qapp: QApplication,
) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        assert window.analysis_range_panel.apply_button.text() == (
            "Confirm Analysis Range"
        )
        assert window.run_analysis_button.text() == "Compute Spectrogram"
        assert "1550 nm" in window.vacuum_wavelength_spin.toolTip()
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()
