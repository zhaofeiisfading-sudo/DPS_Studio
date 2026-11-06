"""Production workstation with one integrated manual-segmentation workspace."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QComboBox, QLabel

from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.analysis_session import AnalysisRange
from dps_studio.gui.segment_workspace import SegmentWorkspace


class ResearchMainWindow(MainWindow):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.setWindowTitle("PDV Studio · Research / Test · TASK-011")
        self.segment_workspace = SegmentWorkspace(self)
        self.segment_workspace.can_analyze = lambda: (
            self._parameters_valid and not self._analysis_adapter.busy)
        self.segment_tab_index = self.science_tabs.addTab(self.segment_workspace, "人工分段")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("researchAnalysisMode")
        self.mode_combo.addItem("经典 STFT", "classic")
        self.mode_combo.addItem("人工分段", "segmented")
        self.main_toolbar.addSeparator()
        self.main_toolbar.addWidget(QLabel("分析模式  "))
        self.main_toolbar.addWidget(self.mode_combo)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.segment_workspace.busy_changed.connect(self._segment_busy_changed)
        self.segment_workspace.roi_change_requested.connect(self._analysis_range_confirmed)
        self._apply_state()

    def _mode_changed(self, index: int) -> None:
        if index == 1:
            self.parameter_stack.setCurrentIndex(2)
            self._sync_segments()
            self.science_tabs.setCurrentWidget(self.segment_workspace)
        else:
            self.science_tabs.setCurrentWidget(self.raw_signal_view)

    def _science_tab_changed(self, index: int) -> None:
        super()._science_tab_changed(index)
        if hasattr(self, "mode_combo"):
            with QSignalBlocker(self.mode_combo):
                self.mode_combo.setCurrentIndex(1 if index == self.segment_tab_index else 0)
            if index == self.segment_tab_index:
                self.parameter_stack.setCurrentIndex(2)
                self._sync_segments()

    def _sync_segments(self) -> None:
        if hasattr(self, "segment_workspace"):
            roi = self.analysis_session.analysis_range
            band = None
            region = self.analysis_session.ridge_search_region
            if region is not None and self.analysis_session.stft_valid:
                # Production's visible t-f rectangle is the experimenter's ROI.
                # The older global time-range controls are hidden in v0.1.6.
                roi = AnalysisRange(region.time_start_s, region.time_end_s)
                band = (region.frequency_min_hz, region.frequency_max_hz)
            self.segment_workspace.set_context(
                self.analysis_session.records, roi,
                self.analysis_session.run_configuration,
                self.load_result.source_path if self.load_result else None,
                band,
            )

    def _refresh_export_controls(self) -> None:
        super()._refresh_export_controls()
        # Production can refresh physical postprocessing without invalidating
        # STFT. Segment results must also follow that shared configuration.
        self._sync_segments()

    def _apply_state(self) -> None:
        super()._apply_state()
        if hasattr(self, "segment_workspace"):
            self.science_tabs.setTabEnabled(self.segment_tab_index, bool(self.analysis_session.records))
            self._sync_segments()
            self.segment_workspace.run_button.setEnabled(
                bool(self.segment_workspace.plan) and self._parameters_valid
                and not self.segment_workspace.busy and not self._analysis_adapter.busy)
            if self.segment_workspace.busy:
                self._segment_busy_changed(True)

    def _segment_busy_changed(self, busy: bool) -> None:
        self.parameter_panel.setEnabled(not busy)
        self.navigation_panel.setEnabled(not busy)
        self.action_open_data.setEnabled(not busy)
        self.mode_combo.setEnabled(not busy)
        if busy:
            for action in (self.action_quick_analysis, self.action_full_automatic,
                           self.action_automatic, self.action_run_stft, self.action_guided,
                           self.action_export):
                action.setEnabled(False)
        else:
            self._apply_state()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.segment_workspace.busy or self._analysis_adapter.busy:
            self.statusBar().showMessage("分析仍在运行，完成后可以关闭窗口。")
            event.ignore()
            return
        super().closeEvent(event)
