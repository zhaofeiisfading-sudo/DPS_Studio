from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from dps_studio.gui.app import translation_manager
from dps_studio.gui.data_controller import (
    ChannelImportSpec,
    DataImportController,
    SignalLoadRequest,
)
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.state import WorkflowState


def test_qapplication_can_be_created(qapp: QApplication) -> None:
    assert QApplication.instance() is qapp
    assert qapp.applicationDisplayName() == "PDV Studio"


def test_main_window_has_required_workstation_regions(qapp: QApplication) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.objectName() == "mainWindow"
        assert window.workflow_navigation.objectName() == "workflowNavigation"
        assert window.science_tabs.objectName() == "scienceTabs"
        assert window.parameter_stack.objectName() == "parameterStack"
        assert window.diagnostics_dock.objectName() == "diagnosticsDock"
        assert window.statusBar().objectName() == "mainStatusBar"
        assert window.science_tabs.count() == 5
        assert window.parameter_stack.count() == 6
        assert window.diagnostics_tabs.count() == 3
    finally:
        window.close()
        qapp.processEvents()


def test_initial_state_is_empty_and_analysis_actions_are_disabled(
    qapp: QApplication,
) -> None:
    window = MainWindow(translation_manager=translation_manager())
    try:
        assert window.workflow_state is WorkflowState.EMPTY
        assert window.action_open_data.isEnabled()
        assert not window.action_run_stft.isEnabled()
        assert not window.action_run_ridge.isEnabled()
        assert not window.action_velocity.isEnabled()
        assert not window.action_export.isEnabled()
        for row in range(1, 6):
            assert not window.select_workflow_step(row)
        for tab_index in range(1, window.science_tabs.count()):
            assert not window.science_tabs.isTabEnabled(tab_index)
    finally:
        window.close()
        qapp.processEvents()


def test_real_reader_keeps_source_and_channels_independent_and_switches_page(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    source = tmp_path / "two_channel.csv"
    source.write_text(
        "0,1,10,note-a\n1,2,20,note-b\n2,3,30,note-c\n",
        encoding="utf-8",
        newline="",
    )
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
    result = DataImportController().load(request)

    assert source.read_bytes() == before
    assert result.unselected_column_indices == (3,)
    assert result.records["pdv_channel_1"] is not result.records["pdv_channel_2"]
    np.testing.assert_array_equal(
        result.records["pdv_channel_1"].voltage_v,
        [1.0, 2.0, 3.0],
    )
    np.testing.assert_array_equal(
        result.records["pdv_channel_2"].voltage_v,
        [10.0, 20.0, 30.0],
    )
    assert not np.shares_memory(
        result.records["pdv_channel_1"].voltage_v,
        result.records["pdv_channel_2"].voltage_v,
    )

    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(result)
        assert window.workflow_state is WorkflowState.RANGE_DEFINED
        assert window.load_result is result
        assert window.select_workflow_step(1)
        assert window.parameter_stack.currentIndex() == 1
        assert window.select_workflow_step(2)
        assert source.read_bytes() == before
    finally:
        window.close()
        qapp.processEvents()


def test_import_dialog_exposes_explicit_si_conversion_controls(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    dialog = ImportSettingsDialog(tmp_path / "signal.csv")
    try:
        request = dialog.load_request()
        assert request.time_column == 0
        assert request.time_scale == 1.0
        assert tuple(channel.column_index for channel in request.channels) == (1, 2)
        assert tuple(channel.voltage_scale for channel in request.channels) == (1.0, 1.0)
    finally:
        dialog.close()
        qapp.processEvents()


def test_english_translation_covers_key_navigation(
    qapp: QApplication,
) -> None:
    manager = translation_manager()
    manager.install("en")
    window = MainWindow(translation_manager=manager)
    try:
        assert window.file_menu.title() == "File"
        assert window.settings_menu.title() == "Settings"
        assert window.help_menu.title() == "Help"
        assert window.science_tabs.tabText(0) == "Raw Signal"
        assert window.workflow_navigation.item(0).text() == "1  Data Import"
    finally:
        window.close()
        manager.install("zh_CN")
        qapp.processEvents()


def test_gui_core_dependency_direction_and_forbidden_imports() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    core_files = sorted((repository_root / "src" / "dps_studio" / "core").rglob("*.py"))
    gui_files = sorted((repository_root / "src" / "dps_studio" / "gui").rglob("*.py"))

    assert core_files
    assert gui_files
    for path in core_files:
        assert "dps_studio.gui" not in path.read_text(encoding="utf-8")
    forbidden = re.compile(
        r"^\s*(?:from|import)\s+(?:scripts|tests|notebooks|production_outputs)\b",
        re.MULTILINE,
    )
    for path in gui_files:
        source = path.read_text(encoding="utf-8")
        assert forbidden.search(source) is None
        assert re.search(r"\bif\s+language\s*==", source) is None
