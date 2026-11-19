"""Classic, segmented, diagnostic and comparison workspaces sharing immutable scientific inputs."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QComboBox, QLabel, QSizePolicy, QStackedWidget, QToolButton

from dps_studio.core.diagnostics import DiagnosticPreset, load_raw_channel_result
from dps_studio.core.io import SignalIOError
from dps_studio.gui.analysis_session import (
    AnalysisRange,
    AnalysisRunConfiguration,
    RidgeSearchRegion,
)
from dps_studio.gui.comparison import ComparisonWorkspace
from dps_studio.gui.diagnostic import DiagnosticWorkspace
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.segment_workspace import SegmentWorkspace
from dps_studio.gui.styles import configure_action_button_cursors
from dps_studio.gui.workspace_ui import channel_label


class ResearchMainWindow(MainWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.setWindowTitle("PDV Studio · Research / Test · TASK-024")
        self.segment_workspace = SegmentWorkspace(self)
        self.diagnostic_workspace = DiagnosticWorkspace(
            repository_root=self._repository_root, parent=self
        )
        self.comparison_workspace = ComparisonWorkspace(self._repository_root, self)
        self._segment_roi_override: AnalysisRange | None = None
        self.segment_workspace.can_analyze = lambda: (
            self._parameters_valid
            and not self._analysis_adapter.busy
            and not self.diagnostic_workspace.busy
            and not self.comparison_workspace.busy
        )
        self.mode_stack = QStackedWidget()
        self.mode_stack.setObjectName("analysisWorkspaceStack")
        self.workspace_splitter.replaceWidget(1, self.mode_stack)
        self.mode_stack.addWidget(self.science_tabs)
        self.mode_stack.addWidget(self.segment_workspace)
        self.mode_stack.addWidget(self.diagnostic_workspace)
        self.mode_stack.addWidget(self.comparison_workspace)
        self.properties_stack = QStackedWidget()
        self.properties_stack.setObjectName("workspacePropertiesStack")
        self.workspace_splitter.replaceWidget(2, self.properties_stack)
        self.properties_stack.addWidget(self.parameter_panel)
        self.properties_stack.addWidget(self.segment_workspace.properties)
        self.properties_stack.addWidget(self.diagnostic_workspace.properties)
        self.properties_stack.addWidget(self.comparison_workspace.properties)
        for widget in (self.mode_stack, self.properties_stack):
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.properties_stack.setMinimumWidth(280)
        self.navigation_panel.setMinimumWidth(140)
        self.navigation_panel.setMaximumWidth(200)
        self.workspace_splitter.setSizes([150, 980, 310])
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("researchAnalysisMode")
        self.mode_combo.addItem("经典 STFT", "classic")
        self.mode_combo.addItem("人工分段", "segmented")
        self.mode_combo.addItem(self.tr("波形与支路诊断"), "diagnostic")
        self.mode_combo.addItem("STFT vs M4 对比", "stft_m4_compare")
        self.mode_combo.setMinimumWidth(150)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addWidget(QLabel("  工作区  "))
        self.main_toolbar.addWidget(self.mode_combo)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.segment_workspace.busy_changed.connect(self._segment_busy_changed)
        self.diagnostic_workspace.busyChanged.connect(self._classic_busy_changed)
        self.diagnostic_workspace.presetLoadRequested.connect(self._load_diagnostic_preset)
        self.diagnostic_workspace.channelChanged.connect(self._sync_active_channel)
        self.comparison_workspace.busyChanged.connect(self._classic_busy_changed)
        self.comparison_workspace.channel_combo.currentIndexChanged.connect(self._sync_active_channel)
        self.comparison_workspace.stateChanged.connect(self._comparison_state_changed)
        self.comparison_workspace.openFileRequested.connect(self.action_open_data.trigger)
        self.comparison_workspace.presetLoadRequested.connect(self._load_comparison_preset)
        self.segment_workspace.roi_change_requested.connect(self._segment_range_confirmed)
        self.segment_workspace.reference_requested.connect(self._prepare_segment_reference)
        self._analysis_adapter.busy_changed.connect(self._classic_busy_changed)
        self.science_tabs.currentChanged.connect(self._sync_active_channel)
        for view in (
            self.raw_signal_view,
            self.spectrogram_view,
            self.ridge_view,
            self.velocity_view,
        ):
            view.channel_selection_changed.connect(self._sync_active_channel)
        self.segment_workspace.channel_combo.currentIndexChanged.connect(self._sync_active_channel)
        self.status_unsaved.hide()
        self._classic_sizes: list[int] = [150, 980, 310]
        self._manual_sizes: list[int] = [0, 1130, 310]
        self._diagnostic_sizes: list[int] = [0, 1190, 265]
        self._comparison_sizes: list[int] = [0, 1034, 342]
        self._dock_visible_before_diagnostic: bool | None = None
        self._previous_mode_index = 0
        self.diagnostics_toggle = QToolButton()
        self.diagnostics_toggle.setText("诊断与数据")
        self.diagnostics_toggle.setCheckable(True)
        self.diagnostics_toggle.toggled.connect(self._toggle_diagnostics)
        self.diagnostics_dock.setTitleBarWidget(self.diagnostics_toggle)
        self.diagnostics_tabs.setMinimumHeight(0)
        self.resizeDocks([self.diagnostics_dock], [86], Qt.Orientation.Vertical)
        configure_action_button_cursors(self)
        self._apply_state()

    @property
    def segmented_mode(self) -> bool:
        return hasattr(self, "mode_combo") and self.mode_combo.currentData() == "segmented"

    @property
    def diagnostic_mode(self) -> bool:
        return hasattr(self, "mode_combo") and self.mode_combo.currentData() == "diagnostic"

    @property
    def comparison_mode(self) -> bool:
        return hasattr(self, "mode_combo") and self.mode_combo.currentData() == "stft_m4_compare"

    def _mode_changed(self, index: int) -> None:
        if (
            self.segment_workspace.busy
            or self._analysis_adapter.busy
            or self.diagnostic_workspace.busy
            or self.comparison_workspace.busy
        ):
            with QSignalBlocker(self.mode_combo):
                self.mode_combo.setCurrentIndex(self.mode_stack.currentIndex())
            return
        if self._previous_mode_index == 0:
            self._classic_sizes = self.workspace_splitter.sizes()
        elif self._previous_mode_index == 1:
            self._manual_sizes = self.workspace_splitter.sizes()
        elif self._previous_mode_index == 2:
            self._diagnostic_sizes = self.workspace_splitter.sizes()
        else:
            self._comparison_sizes = self.workspace_splitter.sizes()
        if index >= 2 and self._previous_mode_index < 2:
            self._dock_visible_before_diagnostic = self.diagnostics_dock.isVisible()
            self.diagnostics_dock.hide()
        elif index < 2 and self._previous_mode_index >= 2:
            self._restore_diagnostics_dock()
        self._previous_mode_index = index
        if index in (1, 2, 3):
            self._cancel_corridor_drawing()
        if index == 1:
            self._sync_segments()
            self.mode_stack.setCurrentWidget(self.segment_workspace)
            self.properties_stack.setCurrentWidget(self.segment_workspace.properties)
            self.navigation_panel.hide()
            self.workspace_splitter.setSizes(self._manual_sizes)
        elif index == 2:
            self._sync_diagnostic()
            self.mode_stack.setCurrentWidget(self.diagnostic_workspace)
            self.properties_stack.setCurrentWidget(self.diagnostic_workspace.properties)
            self.navigation_panel.hide()
            self.workspace_splitter.setSizes(self._diagnostic_sizes)
        elif index == 3:
            self.mode_stack.setCurrentWidget(self.comparison_workspace)
            self.properties_stack.setCurrentWidget(self.comparison_workspace.properties)
            self.navigation_panel.hide()
            self.workspace_splitter.setSizes(self._comparison_sizes)
        else:
            self.mode_stack.setCurrentWidget(self.science_tabs)
            self.properties_stack.setCurrentWidget(self.parameter_panel)
            self.navigation_panel.show()
            self.workspace_splitter.setSizes(self._classic_sizes)
        self._apply_state()

    def _sync_diagnostic(self) -> None:
        if hasattr(self, "diagnostic_workspace"):
            self.diagnostic_workspace.set_context(
                self.analysis_session.records,
                self.load_result.source_path if self.load_result else None,
            )

    def _sync_comparison(self) -> None:
        self.comparison_workspace.set_context(
            self.analysis_session.records,
            self.load_result.source_path if self.load_result else None,
        )

    def _load_comparison_preset(self, preset: DiagnosticPreset) -> None:
        if self.comparison_workspace.busy or not self.mode_combo.isEnabled():
            return
        try:
            result = load_raw_channel_result(preset, self._repository_root)
            self.set_loaded_result(result)
        except (OSError, ValueError, SignalIOError) as exc:
            self.comparison_workspace.properties.stage_label.setText(f"算例载入失败 · {exc}")

    def _comparison_state_changed(self, text: str) -> None:
        if self.comparison_mode:
            self.status_state.setText(text)
            self.status_state.setToolTip(text)
            self._sync_active_channel()

    def _load_diagnostic_preset(self, preset: DiagnosticPreset) -> None:
        if (
            self.segment_workspace.busy
            or self._analysis_adapter.busy
            or self.diagnostic_workspace.busy
            or self.comparison_workspace.busy
        ):
            return
        prefer_frozen = self.diagnostic_workspace.properties.prefer_frozen_checkbox.isChecked()
        try:
            result = load_raw_channel_result(preset, self._repository_root)
            self.mode_combo.setCurrentIndex(2)
            self.set_loaded_result(result)
            self._sync_diagnostic()
            self.diagnostic_workspace.properties.prefer_frozen_checkbox.setChecked(prefer_frozen)
            if prefer_frozen and self.diagnostic_workspace.frozen_available():
                self.diagnostic_workspace.load_frozen()
        except (OSError, ValueError) as exc:
            self.diagnostic_workspace.properties.stage_label.setText(f"算例载入失败：{exc}")

    def _toggle_diagnostics(self, expanded: bool) -> None:
        self.resizeDocks(
            [self.diagnostics_dock], [240 if expanded else 86], Qt.Orientation.Vertical
        )

    def _restore_diagnostics_dock(self) -> None:
        if self._dock_visible_before_diagnostic is not None:
            self.diagnostics_dock.setVisible(self._dock_visible_before_diagnostic)
            self._dock_visible_before_diagnostic = None

    def _prepare_segment_reference(self) -> None:
        if not self._analysis_adapter.busy and not self.segment_workspace.busy:
            self.segment_workspace.views.setCurrentWidget(self.segment_workspace.spectrogram)
            if self.analysis_session.stft_valid:
                self._sync_segments()
            else:
                self._segment_roi_override = self.segment_workspace._roi
                self._quick_analysis_waiting = False
                self.run_stft_analysis()
                self._pending_navigation_tab = None

    def _segment_range_confirmed(self, start_s: float, end_s: float) -> None:
        self._segment_roi_override = AnalysisRange(start_s, end_s)
        super()._analysis_range_confirmed(start_s, end_s)

    def _analysis_range_confirmed(self, start_time_s: float, end_time_s: float) -> None:
        if hasattr(self, "segment_workspace") and not self.segmented_mode:
            self._segment_roi_override = None
        super()._analysis_range_confirmed(start_time_s, end_time_s)

    def _apply_ridge_search_region(self, region: RidgeSearchRegion) -> None:
        if hasattr(self, "segment_workspace") and not self.segmented_mode:
            self._segment_roi_override = None
        super()._apply_ridge_search_region(region)

    def _analysis_request_ready(self) -> tuple[AnalysisRunConfiguration, AnalysisRange] | None:
        if (
            self._analysis_adapter.busy
            or (hasattr(self, "segment_workspace") and self.segment_workspace.busy)
            or (hasattr(self, "diagnostic_workspace") and self.diagnostic_workspace.busy)
            or (hasattr(self, "comparison_workspace") and self.comparison_workspace.busy)
        ):
            return None
        return super()._analysis_request_ready()

    def run_stft_analysis(self) -> bool:
        if (
            self._analysis_adapter.busy
            or (hasattr(self, "segment_workspace") and self.segment_workspace.busy)
            or (hasattr(self, "diagnostic_workspace") and self.diagnostic_workspace.busy)
            or (hasattr(self, "comparison_workspace") and self.comparison_workspace.busy)
        ):
            return False
        return super().run_stft_analysis()

    def _sync_segments(self) -> None:
        if not hasattr(self, "segment_workspace"):
            return
        if tuple(
            (name, id(record)) for name, record in self.analysis_session.records.items()
        ) != tuple((name, id(record)) for name, record in self.segment_workspace.records.items()):
            self._segment_roi_override = None
        roi = self.analysis_session.analysis_range
        configuration = self.analysis_session.run_configuration
        band = (
            (
                configuration.parameters.minimum_frequency_hz,
                configuration.parameters.maximum_frequency_hz,
            )
            if configuration is not None
            else None
        )
        region = self.analysis_session.ridge_search_region
        if region is not None and self.analysis_session.stft_valid:
            roi = AnalysisRange(region.time_start_s, region.time_end_s)
            band = (region.frequency_min_hz, region.frequency_max_hz)
        if self._segment_roi_override is not None:
            roi = self._segment_roi_override
        self.segment_workspace.set_context(
            self.analysis_session.records,
            roi,
            self.analysis_session.run_configuration,
            self.load_result.source_path if self.load_result else None,
            band,
        )
        self.segment_workspace.set_references(
            self.analysis_session.stft_results if self.analysis_session.stft_valid else {},
            self.analysis_session.valid_guided_channel_analyses
            if self.velocity_view.result_source == "guided"
            else self.analysis_session.channel_analyses,
        )

    def _refresh_export_controls(self) -> None:
        super()._refresh_export_controls()
        self._sync_segments()

    def _apply_state(self) -> None:
        page = self.science_tabs.currentIndex() if hasattr(self, "science_tabs") else 0
        super()._apply_state()
        if not hasattr(self, "segment_workspace"):
            return
        if self.analysis_session.records:
            for index in range(self.science_tabs.count()):
                self.science_tabs.setTabEnabled(index, True)
            self.science_tabs.setCurrentIndex(page)
        self._sync_segments()
        self._sync_diagnostic()
        self._sync_comparison()
        busy = (
            self.segment_workspace.busy
            or self._analysis_adapter.busy
            or self.diagnostic_workspace.busy
            or self.comparison_workspace.busy
        )
        self.mode_combo.setEnabled(not busy)
        self.diagnostic_workspace.external_busy = (
            self.segment_workspace.busy or self._analysis_adapter.busy or self.comparison_workspace.busy
        )
        self.comparison_workspace.set_external_busy(
            self.segment_workspace.busy or self._analysis_adapter.busy or self.diagnostic_workspace.busy
        )
        self.diagnostic_workspace._refresh_controls()
        self.segment_workspace._refresh_controls()
        self.parameter_panel.setEnabled(not busy)
        self.navigation_panel.setEnabled(not busy)
        self.action_open_data.setEnabled(not busy)
        if self.segmented_mode or self.diagnostic_mode or self.comparison_mode or busy:
            self.run_analysis_button.setEnabled(False)
            for action in (
                self.action_quick_analysis,
                self.action_full_automatic,
                self.action_automatic,
                self.action_run_stft,
                self.action_guided,
                self.action_run_ridge,
                self.action_export,
            ):
                action.setEnabled(False)
        labels = {
            "empty": "待导入",
            "data_loaded": "数据已载入",
            "range_defined": "范围已确认",
            "stft_ready": "时频图就绪",
            "ridge_ready": "脊线就绪",
            "result_ready": "结果就绪",
        }
        self.status_state.setText(labels[self.workflow_state.value])
        self.status_state.setToolTip(self.workflow_state.name)
        self._comparison_state_changed(self.comparison_workspace.state_text)
        self._sync_active_channel()

    def _sync_active_channel(self, _value: object = None) -> None:
        view = (
            self.comparison_workspace
            if self.comparison_mode
            else self.diagnostic_workspace
            if self.diagnostic_mode
            else self.segment_workspace
            if self.segmented_mode
            else self.science_tabs.currentWidget()
        )
        combo = getattr(view, "channel_combo", None)
        identity = combo.currentData() if combo is not None else None
        label = (
            "全部通道"
            if identity == "__all__"
            else channel_label(identity)
            if isinstance(identity, str)
            else "—"
        )
        self.status_channel.setText(f"通道：{label}")

    def _segment_busy_changed(self, _busy: bool) -> None:
        self._apply_state()

    def _classic_busy_changed(self, _busy: bool) -> None:
        self._apply_state()

    def _event_time_source_changed(self, source: str) -> None:
        page = self.science_tabs.currentIndex()
        row = self.workflow_navigation.currentRow()
        view = self.velocity_view.plot_widget.viewRange()
        super()._event_time_source_changed(source)
        with QSignalBlocker(self.workflow_navigation):
            self.workflow_navigation.setCurrentRow(row)
        self.parameter_stack.setCurrentIndex(max(row, 0))
        self.science_tabs.setCurrentIndex(page)
        self.velocity_view.plot_widget.setRange(xRange=view[0], yRange=view[1], padding=0)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.segment_workspace.busy or self._analysis_adapter.busy:
            self.statusBar().showMessage("分析仍在运行，完成后可以关闭窗口。")
            event.ignore()
            return
        self.segment_workspace.dispose()
        self.diagnostic_workspace.dispose()
        self.comparison_workspace.dispose()
        self._restore_diagnostics_dock()
        super().closeEvent(event)
