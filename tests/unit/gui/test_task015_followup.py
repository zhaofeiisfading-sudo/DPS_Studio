from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.export import ResultAnalysisMode
from dps_studio.core.io import WHITESPACE_DELIMITER, SignalColumnError
from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml"


def _write_columns(path: Path, column_count: int, *, rows: int = 8) -> bytes:
    time = np.arange(rows, dtype=np.float64)
    values = np.column_stack(
        [time, *(time + float(index) for index in range(1, column_count))]
    )
    np.savetxt(path, values, delimiter=",", fmt="%.9g")
    return path.read_bytes()


@pytest.mark.parametrize(
    ("column_count", "expected_columns"),
    ((2, (1,)), (3, (1, 2)), (4, (1, 2, 3)), (6, (1, 2, 3))),
)
def test_dialog_initializes_signal_slots_from_actual_column_count(
    qapp: QApplication,
    tmp_path: Path,
    column_count: int,
    expected_columns: tuple[int, ...],
) -> None:
    source = tmp_path / f"{column_count}_columns.csv"
    before = _write_columns(source, column_count)
    dialog = ImportSettingsDialog(source)
    try:
        request = dialog.load_request()
        assert dialog.detected_column_count == column_count
        assert dialog.time_column_spin.maximum() == column_count - 1
        assert dialog.channel_3_column.maximum() == column_count - 1
        assert tuple(channel.column_index for channel in request.channels) == (
            expected_columns
        )
        result = DataImportController().load(request)
        assert result.channel_names == tuple(
            f"pdv_channel_{index}" for index in range(1, len(expected_columns) + 1)
        )
        assert result.unselected_column_indices == tuple(
            index
            for index in range(column_count)
            if index not in (0, *expected_columns)
        )
        assert source.read_bytes() == before
    finally:
        dialog.close()
        qapp.processEvents()


def test_dialog_allows_arbitrary_source_columns_and_ignores_disabled_slots(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "six_columns.csv"
    _write_columns(source, 6)
    dialog = ImportSettingsDialog(source)
    try:
        dialog.time_column_spin.setValue(5)
        dialog.channel_1_column.setValue(0)
        dialog.channel_2_column.setValue(2)
        dialog.channel_3_column.setValue(4)
        dialog.channel_2_enabled.setChecked(False)
        dialog.channel_2_name.clear()
        assert not dialog.channel_2_row.isEnabled()
        assert dialog.validation_error() is None

        request = dialog.load_request()
        assert tuple(channel.column_index for channel in request.channels) == (0, 4)
        result = DataImportController().load(request)
        assert result.unselected_column_indices == (1, 2, 3)
    finally:
        dialog.close()
        qapp.processEvents()


def test_preview_reports_tentative_header_and_short_column_samples(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "header.csv"
    source.write_text(
        "Time,PDV_A,PDV_B\n0,1,2\n1,3,4\n2,5,6\n",
        encoding="utf-8",
        newline="",
    )
    dialog = ImportSettingsDialog(source)
    try:
        assert dialog.detected_column_count == 3
        assert dialog.header_check.isChecked()
        preview = dialog.column_preview_label.text()
        assert "Time" in preview
        assert "PDV_A" in preview
        assert "1" in preview
    finally:
        dialog.close()
        qapp.processEvents()


def test_whitespace_preview_request_and_controller_share_one_mode(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "production.dat"
    source.write_text(
        "  -1.0e-6   4.2e2\n\t-0.5e-6\t  4.3e2\n",
        encoding="utf-8",
        newline="",
    )

    dialog = ImportSettingsDialog(source)
    try:
        assert dialog.detected_column_count == 2
        assert dialog.delimiter_combo.currentData() == WHITESPACE_DELIMITER
        assert "空白字符" in dialog.delimiter_combo.currentText()
        assert dialog.validation_error() is None

        request = dialog.load_request()
        assert request.delimiter == WHITESPACE_DELIMITER
        result = DataImportController().load(request)
        assert result.column_count == 2
        assert result.row_count == 2
        assert result.delimiter == WHITESPACE_DELIMITER
        np.testing.assert_array_equal(
            result.records["pdv_channel_1"].time_s,
            [-1.0e-6, -0.5e-6],
        )
        np.testing.assert_array_equal(
            result.records["pdv_channel_1"].voltage_v,
            [420.0, 430.0],
        )
    finally:
        dialog.close()
        qapp.processEvents()


def test_import_dialog_offers_explicit_delimiter_modes(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "signal.csv"
    source.write_text("0,1\n1,2\n", encoding="utf-8", newline="")
    dialog = ImportSettingsDialog(source)
    try:
        available_modes = {
            dialog.delimiter_combo.itemData(index)
            for index in range(dialog.delimiter_combo.count())
        }
        assert {None, ",", "\t", WHITESPACE_DELIMITER, ";", "custom"} <= (
            available_modes
        )

        whitespace_index = dialog.delimiter_combo.findData(WHITESPACE_DELIMITER)
        dialog.delimiter_combo.setCurrentIndex(whitespace_index)
        assert dialog.load_request().delimiter == WHITESPACE_DELIMITER
    finally:
        dialog.close()
        qapp.processEvents()


def test_dialog_rejects_missing_duplicate_and_time_signal_mappings(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "four_columns.csv"
    _write_columns(source, 4)
    dialog = ImportSettingsDialog(source)
    try:
        for enabled in (
            dialog.channel_1_enabled,
            dialog.channel_2_enabled,
            dialog.channel_3_enabled,
        ):
            enabled.setChecked(False)
        assert "至少" in (dialog.validation_error() or "")

        dialog.channel_1_enabled.setChecked(True)
        dialog.channel_2_enabled.setChecked(True)
        dialog.channel_1_column.setValue(1)
        dialog.channel_2_column.setValue(1)
        assert "不能重复" in (dialog.validation_error() or "")

        dialog.channel_2_column.setValue(2)
        dialog.channel_2_name.setText(dialog.channel_1_name.text())
        assert "名称不能重复" in (dialog.validation_error() or "")

        dialog.channel_2_name.setText("pdv_channel_2")
        dialog.time_column_spin.setValue(1)
        assert "不能同时" in (dialog.validation_error() or "")
    finally:
        dialog.close()
        qapp.processEvents()


def test_import_mapping_semantics_are_translated_in_english(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "english_two_columns.csv"
    _write_columns(source, 2)
    manager = translation_manager()
    manager.install("en")
    dialog = ImportSettingsDialog(source)
    try:
        assert dialog.channel_1_enabled.text() == "Import Signal 1"
        whitespace_index = dialog.delimiter_combo.findData(WHITESPACE_DELIMITER)
        assert dialog.delimiter_combo.itemText(whitespace_index) == (
            "Whitespace (spaces / tabs)"
        )
        assert "Detected 2 columns" in dialog.structure_status_label.text()
        for enabled in (
            dialog.channel_1_enabled,
            dialog.channel_2_enabled,
            dialog.channel_3_enabled,
        ):
            enabled.setChecked(False)
        assert dialog.validation_error() == "Enable at least one signal column."
    finally:
        dialog.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_controller_rejects_invalid_gui_mappings_and_reader_rejects_range(
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_columns.csv"
    _write_columns(source, 2)
    common: dict[str, Any] = {
        "path": source,
        "time_column": 0,
        "delimiter": ",",
        "has_header": False,
        "encoding": "utf-8",
        "time_scale": 1.0,
    }
    with pytest.raises(ValueError, match="unique"):
        DataImportController().load(
            SignalLoadRequest(
                channels=(
                    ChannelImportSpec("duplicate", 1, 1.0),
                    ChannelImportSpec("duplicate", 2, 1.0),
                ),
                **common,
            )
        )
    with pytest.raises(ValueError, match="time column"):
        DataImportController().load(
            SignalLoadRequest(
                channels=(ChannelImportSpec("signal", 0, 1.0),),
                **common,
            )
        )
    with pytest.raises(SignalColumnError, match="column 9"):
        DataImportController().load(
            SignalLoadRequest(
                channels=(ChannelImportSpec("signal", 9, 1.0),),
                **common,
            )
        )


def _analysis_window(
    qapp: QApplication,
    tmp_path: Path,
    *,
    channel_count: int = 2,
) -> MainWindow:
    sample_rate_hz = 40.0e9
    time_s = 5.54e-4 + np.arange(8192, dtype=np.float64) / sample_rate_hz
    relative_s = time_s - time_s[0]
    signals = [
        np.sin(2.0 * np.pi * (0.61e9 + index * 0.04e9) * relative_s + index * 0.1)
        for index in range(channel_count)
    ]
    source = tmp_path / f"navigation_{channel_count}_channels.csv"
    np.savetxt(
        source,
        np.column_stack((time_s, *signals)),
        delimiter=",",
        fmt="%.17e",
    )
    loaded = DataImportController().load(
        SignalLoadRequest(
            path=source,
            time_column=0,
            channels=tuple(
                ChannelImportSpec(f"pdv_channel_{index + 1}", index + 1, 1.0)
                for index in range(channel_count)
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
    return window


def _wait_for_analysis(window: MainWindow, launch: Callable[[], bool]) -> None:
    loop = QEventLoop()
    state: dict[str, str | bool | None] = {"timeout": False, "error": None}

    def timeout() -> None:
        state["timeout"] = True
        loop.quit()

    def failed(
        _generation: int,
        error_type: str,
        message: str,
        _traceback: str,
    ) -> None:
        state["error"] = f"{error_type}: {message}"
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(failed)
    QTimer.singleShot(20_000, timeout)
    assert launch()
    loop.exec()
    assert state == {"timeout": False, "error": None}


def test_clicking_empty_import_step_opens_existing_flow(
    qapp: QApplication,
    monkeypatch: Any,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    calls: list[bool] = []
    try:
        monkeypatch.setattr(window, "_open_data", lambda: calls.append(True))
        item = window.workflow_navigation.item(0)
        assert item is not None
        window.workflow_navigation.itemClicked.emit(item)
        assert calls == [True]
        assert window.science_tabs.currentWidget() is window.raw_signal_view
    finally:
        window.close()
        qapp.processEvents()


def test_workflow_navigation_changes_tabs_once_at_semantic_boundaries(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _analysis_window(qapp, tmp_path)
    try:
        window.science_tabs.setCurrentIndex(0)
        assert not window.select_workflow_step(1)
        window.science_tabs.setCurrentWidget(window.spectrogram_view)
        assert window.science_tabs.currentWidget() is window.spectrogram_view
        assert not window.analysis_session.stft_valid
        _wait_for_analysis(window, window.run_stft_analysis)
        assert window.analysis_session.stft_valid
        assert window.select_workflow_step(0)
        assert window.science_tabs.currentWidget() is window.spectrogram_view

        assert window.select_workflow_step(1)
        assert window.science_tabs.currentWidget() is window.spectrogram_view

        _wait_for_analysis(window, window.run_staged_automatic_analysis)
        assert window.science_tabs.currentWidget() is window.ridge_view

        assert window.select_workflow_step(2)
        assert window.science_tabs.currentWidget() is window.velocity_view

        window.science_tabs.setCurrentWidget(window.raw_signal_view)
        transitions: list[int] = []
        window.science_tabs.currentChanged.connect(transitions.append)
        _wait_for_analysis(window, window.run_automatic_analysis)
        assert transitions == [3]
    finally:
        window.close()
        qapp.processEvents()


def test_review_step_export_target_drives_velocity_preview_and_clears_missing_guided(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    window = _analysis_window(qapp, tmp_path)
    try:
        _wait_for_analysis(window, window.run_automatic_analysis)
        stft = window.analysis_session.stft_results["pdv_channel_1"]
        window._ridge_constraint_changed(
            "pdv_channel_1",
            RidgeCorridorConstraint(
                control_times_s=np.asarray([stft.time_s[1], stft.time_s[-2]]),
                control_frequencies_hz=np.asarray([0.61e9, 0.61e9]),
                half_width_hz=75.0e6,
            ),
        )
        _wait_for_analysis(window, window.run_guided_analysis)
        assert window.select_workflow_step(3)
        assert window.science_tabs.currentWidget() is window.velocity_view

        automatic_index = window.export_mode_combo.findData(
            ResultAnalysisMode.AUTOMATIC.value
        )
        window.export_mode_combo.setCurrentIndex(automatic_index)
        for channel_name in ("pdv_channel_1", "pdv_channel_2"):
            window.export_channel_combo.setCurrentIndex(
                window.export_channel_combo.findData(channel_name)
            )
            qapp.processEvents()
            assert window.velocity_view.result_source == "automatic"
            assert window.velocity_view.channel_combo.currentData() == channel_name
            assert window.velocity_view.formal_curve is None
            assert window.velocity_view.display_curve is not None
            _, display_y = window.velocity_view.display_curve.getData()
            np.testing.assert_array_equal(
                display_y,
                window.analysis_session.channel_analyses[
                    channel_name
                ].display_velocity_m_s,
            )

        guided_index = window.export_mode_combo.findData(
            ResultAnalysisMode.GUIDED.value
        )
        window.export_mode_combo.setCurrentIndex(guided_index)
        window.export_channel_combo.setCurrentIndex(
            window.export_channel_combo.findData("pdv_channel_1")
        )
        qapp.processEvents()
        assert window.velocity_view.result_source == "guided"
        assert window.velocity_view.channel_combo.currentData() == "pdv_channel_1"
        assert window.velocity_view.formal_curve is None
        assert window.velocity_view.display_curve is not None

        window.export_channel_combo.setCurrentIndex(
            window.export_channel_combo.findData("pdv_channel_2")
        )
        qapp.processEvents()
        assert window.velocity_view.result_source == "guided"
        assert window.velocity_view.channel_combo.currentData() == "pdv_channel_2"
        assert window.velocity_view.formal_curve is None
        assert "尚无" in window.velocity_view.source_notice.text()
        assert not window.export_button.isEnabled()
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("channel_count", (1, 3))
def test_single_and_three_channel_analysis_and_preview_remain_independent(
    qapp: QApplication,
    tmp_path: Path,
    channel_count: int,
) -> None:
    window = _analysis_window(qapp, tmp_path, channel_count=channel_count)
    try:
        _wait_for_analysis(window, window.run_automatic_analysis)
        expected_channels = tuple(
            f"pdv_channel_{index + 1}" for index in range(channel_count)
        )
        assert tuple(window.analysis_session.channel_analyses) == expected_channels
        assert window.select_workflow_step(3)
        target_channel = expected_channels[-1]
        window.export_channel_combo.setCurrentIndex(
            window.export_channel_combo.findData(target_channel)
        )
        qapp.processEvents()
        assert window.export_channel_combo.currentData() == target_channel
        assert window.velocity_view.channel_combo.currentData() == target_channel
        assert window.velocity_view.formal_curve is None
    finally:
        window.close()
        qapp.processEvents()
