from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from dps_studio.core.export import ResultAnalysisMode
from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _window(qapp: QApplication, tmp_path: Path) -> tuple[MainWindow, Path, bytes]:
    sample_rate_hz = 40.0e9
    time_s = 5.54e-4 + np.arange(8192, dtype=np.float64) / sample_rate_hz
    relative_s = time_s - time_s[0]
    values = np.column_stack(
        (
            time_s,
            np.sin(2.0 * np.pi * 0.63e9 * relative_s),
            np.sin(2.0 * np.pi * 0.68e9 * relative_s + 0.2),
        )
    )
    source_path = tmp_path / "task017_dual_channel.csv"
    np.savetxt(source_path, values, delimiter=",", fmt="%.17e")
    source_before = source_path.read_bytes()
    loaded = DataImportController().load(
        SignalLoadRequest(
            path=source_path,
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
    window = MainWindow(translation_manager=translation_manager())
    window.set_loaded_result(loaded)
    window.set_analysis_configuration(
        load_workflow_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    )
    window.analysis_range_panel.use_full_range()
    qapp.processEvents()
    return window, source_path, source_before


def _wait(window: MainWindow, launch: Any) -> None:
    loop = QEventLoop()
    state: dict[str, object] = {"timed_out": False, "error": None}

    def timeout() -> None:
        state["timed_out"] = True
        loop.quit()

    def failed(_generation: int, error_type: str, message: str, _traceback: str) -> None:
        state["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(15_000, timeout)
    assert launch()
    loop.exec()
    assert state["timed_out"] is False
    assert state["error"] is None
    assert not window._analysis_adapter.busy


def test_export_controls_start_disabled_without_formal_results(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert not window.action_export.isEnabled()
        assert not window.export_button.isEnabled()
        assert not window.export_mode_combo.isEnabled()
        assert window.export_include_pre_event_check.isChecked()
        assert "没有可导出" in window.export_availability_label.text()
    finally:
        window.close()
        qapp.processEvents()


def test_export_controls_are_translated_in_english(qapp: QApplication) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        assert window.export_directory_button.text() == "Choose Export Directory…"
        assert window.action_export.text() == "Review & Export"
        assert window.export_button.text() == "Export Results"
        assert window.export_description_label.text() == (
            "Exports time–velocity data, diagnostic data, and analysis parameters."
        )
        assert window.export_include_pre_event_check.text() == (
            "Include pre-event display-only platform"
        )
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_toolbar_review_and_export_only_navigates_without_writing(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    window, _source_path, _source_before = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_automatic_analysis)
        export_parent = tmp_path / "exports"
        export_parent.mkdir()
        window.export_absolute_time_origin_radio.click()
        qapp.processEvents()
        window._set_export_output_directory(export_parent)
        before_paths = {path.name for path in export_parent.iterdir()}
        result_state = window.workflow_state
        calls: list[object] = []
        monkeypatch.setattr(
            "dps_studio.gui.main_window.export_formal_results",
            lambda *_args, **_kwargs: calls.append(object()),
        )

        window.action_export.trigger()
        qapp.processEvents()

        assert window.workflow_navigation.currentRow() == 5
        assert window.parameter_stack.currentIndex() == 5
        assert {path.name for path in export_parent.iterdir()} == before_paths
        assert not calls
        assert window.workflow_state is result_state
        assert window.analysis_session.automatic_results_available
    finally:
        window.close()
        qapp.processEvents()


def test_automatic_export_uses_current_selection_and_keeps_export_available(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    window, source_path, source_before = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_automatic_analysis)
        assert window.action_export.isEnabled()
        assert window.export_mode_combo.currentData() == "automatic"
        assert {
            window.export_channel_combo.itemData(index)
            for index in range(window.export_channel_combo.count())
        } == {"pdv_channel_1", "pdv_channel_2"}
        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *_args, **_kwargs: ""),
        )
        assert not window._export_current_result()

        export_parent = tmp_path / "exports"
        export_parent.mkdir()
        window.export_absolute_time_origin_radio.click()
        qapp.processEvents()
        window._set_export_output_directory(export_parent)
        assert window.export_button.isEnabled()
        success_messages: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "information",
            staticmethod(
                lambda _parent, _title, message: success_messages.append(message)
            ),
        )
        assert window._export_current_result()
        assert not list(export_parent.glob("pdv_studio_export_*"))
        metadata_path = export_parent / "task017_dual_channel_ch1_auto.metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["analysis_mode"] == "automatic"
        assert metadata["source_channel"] == "pdv_channel_1"
        analysis = window.analysis_session.channel_analyses["pdv_channel_1"]
        assert metadata["automatic_event_candidate_time_s"] == (
            analysis.stream_event_candidates.primary_candidate_time_s
        )
        assert metadata["compatibility_event_candidate_time_s"] == (
            analysis.signal_detection_result.detected_event_candidate_time_s
        )
        assert metadata["event_reference_time_s"] == (
            window.analysis_session.event_reference_time_s
        )
        assert metadata["event_reference_source"] == (
            window.analysis_session.event_reference_source
        )
        assert metadata["pre_event_display"]["included_in_csv"] is True
        assert len(tuple(export_parent.glob("*.metadata.json"))) == 1
        assert (export_parent / "task017_dual_channel_ch1_auto.csv").is_file()
        assert (export_parent / "task017_dual_channel_ch1_auto_detail.csv").is_file()
        assert success_messages
        assert "task017_dual_channel_ch1_auto.csv" in success_messages[-1]
        assert str(export_parent) in window.log_view.toPlainText()
        assert window.export_button.isEnabled()
        assert window._export_current_result()
        assert (export_parent / "task017_dual_channel_ch1_auto_2.csv").is_file()
        assert window.export_button.isEnabled()
        assert source_path.read_bytes() == source_before

        window.analysis_session.invalidate_results()
        window._sync_workflow_state_after_invalidation()
        assert not window.action_export.isEnabled()
        assert not window.export_button.isEnabled()
    finally:
        window.close()
        qapp.processEvents()


def test_guided_mode_selection_keeps_missing_channels_visible_but_safe(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window, _source_path, _source_before = _window(qapp, tmp_path)
    try:
        _wait(window, window.run_automatic_analysis)
        stft = window.analysis_session.stft_results["pdv_channel_1"]
        active_times = stft.time_s[
            (stft.time_s >= window.analysis_session.analysis_range.start_time_s)
            & (stft.time_s <= window.analysis_session.analysis_range.end_time_s)
        ]
        window._ridge_constraint_changed(
            "pdv_channel_1",
            RidgeCorridorConstraint(
                control_times_s=np.asarray([active_times[1], active_times[-2]]),
                control_frequencies_hz=np.asarray([0.63e9, 0.63e9]),
                half_width_hz=75.0e6,
            ),
        )
        _wait(window, window.run_guided_analysis)
        guided_index = window.export_mode_combo.findData(
            ResultAnalysisMode.GUIDED.value
        )
        assert guided_index >= 0
        window.export_mode_combo.setCurrentIndex(guided_index)
        qapp.processEvents()
        assert window.export_mode_combo.currentData() == "guided"
        assert window.export_channel_combo.count() == 2
        assert window.export_channel_combo.currentData() == "pdv_channel_1"

        window.export_channel_combo.setCurrentIndex(
            window.export_channel_combo.findData("pdv_channel_2")
        )
        qapp.processEvents()
        assert window.export_channel_combo.currentData() == "pdv_channel_2"
        assert not window.export_button.isEnabled()

        automatic_index = window.export_mode_combo.findData(
            ResultAnalysisMode.AUTOMATIC.value
        )
        window.export_mode_combo.setCurrentIndex(automatic_index)
        qapp.processEvents()
        assert {
            window.export_channel_combo.itemData(index)
            for index in range(window.export_channel_combo.count())
        } == {"pdv_channel_1", "pdv_channel_2"}
    finally:
        window.close()
        qapp.processEvents()
