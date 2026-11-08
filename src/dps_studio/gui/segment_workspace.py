"""Manual time gates inside the mature PDV workstation."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QObject, QRunnable, QSignalBlocker, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabWidget,
    QFormLayout, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from dps_studio.core.models import SignalRecord
from dps_studio.core.export import ExportTimeOrigin
from dps_studio.core.segmentation import (
    EstimatorRequest, Segment, SegmentedResult, analyze_segments, default_pool, validate_plan,
)
from dps_studio.core.segmentation.export import export_segmented_results
from dps_studio.gui.analysis_session import AnalysisRange, AnalysisRunConfiguration
from dps_studio.gui.raw_signal_view import RawSignalView
from dps_studio.gui.result_views import SpectrogramView, VelocityView, finite_velocity_xy_view_range
from dps_studio.gui.workspace_ui import CollapsibleSection, channel_label

STAGE_LABELS = {"unknown": "未知", "stationary": "静止", "onset": "起跳",
                "acceleration": "加速", "plateau": "平台", "decline": "下降",
                "rebound": "回升", "weak_signal": "弱信号", "noise": "噪声干扰"}
RECOMMENDATIONS = {"acceleration": "dechirp"}
REASONS = {
    "acceleration": "连续强加速中 Dechirp 有条件收益；转折、多支路需对照 STFT/VarPro。",
    "onset": "起跳包含突变，保留 STFT 基准；窗内混合会限制时间定位。",
    "decline": "复杂下降以 STFT 为基准，可手动对照 VarPro；不预设模型胜出。",
    "rebound": "回升及转折以 STFT 为基准，可对照 VarPro。",
    "weak_signal": "弱信号可辨识性仍有限，保留 STFT 基准及质量标志。",
    "noise": "保留 STFT 候选与质量检查；杂散投影依赖背景假设，尚不适合默认使用。",
    "stationary": "静止是人工先验，不是零速测量；低频专项可手选，未检出拍频仍为 NaN。",
    "plateau": "STFT 为基准；稳定长段可手选长窗或正弦精修，边界和误标可能使其退化。",
}


def workflow_options(configuration: AnalysisRunConfiguration) -> dict[str, Any]:
    p = configuration.parameters
    return {
        "window_length_samples": p.window_length_samples,
        "overlap_samples": p.overlap_samples, "nfft": p.nfft, "window_name": p.window_name,
        "minimum_frequency_hz": p.minimum_frequency_hz,
        "maximum_frequency_hz": p.maximum_frequency_hz,
        "manual_event_reference_time_s": configuration.event_reference_time_s,
        "profile_name": p.provenance_name, "detection_config": configuration.detection_config,
        "event_candidate_config": configuration.event_candidate_config,
        "automatic_ridge_selection_config": configuration.automatic_ridge_selection_config,
        "background_guard_window_scale": configuration.background_guard_window_scale,
        "minimum_background_bin_count": configuration.minimum_background_bin_count,
    }


class _Signals(QObject):
    finished = Signal(int, str, object)
    failed = Signal(int, str)
    progress = Signal(str)


class _Worker(QRunnable):
    def __init__(self, revision: int, channel: str, request: EstimatorRequest,
                 plan: tuple[Segment, ...], configuration: AnalysisRunConfiguration) -> None:
        super().__init__()
        self.revision, self.channel, self.request = revision, channel, request
        self.plan, self.configuration = plan, configuration
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        try:
            result = analyze_segments(
                self.request, self.plan,
                correction_config=self.configuration.velocity_correction_config,
                progress=self.signals.progress.emit,
            )
            self.signals.finished.emit(self.revision, self.channel, result)
        except Exception as exc:
            self.signals.failed.emit(self.revision, f"{type(exc).__name__}: {exc}")


class SegmentWorkspace(QWidget):
    """Per-channel plans, draggable split lines, quality review and export."""

    busy_changed = Signal(bool)
    roi_change_requested = Signal(float, float)
    reference_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("manualSegmentWorkspace")
        self.records: Mapping[str, SignalRecord] = {}
        self.plans: dict[str, tuple[Segment, ...]] = {}
        self.results: dict[str, SegmentedResult] = {}
        self.lines: list[Any] = []
        self.revision = 0
        self.busy = False
        self.can_analyze: Callable[[], bool] = lambda: True
        self._configuration: AnalysisRunConfiguration | None = None
        self._roi: AnalysisRange | None = None
        self._source: Path | None = None
        self._frequency_band_hz: tuple[float, float] | None = None
        self._channel = ""
        self._worker: _Worker | None = None
        self._syncing = False
        self._algorithms = {algorithm.id: algorithm.label for algorithm in default_pool().algorithms}

        self.manual_choices: set[tuple[str, str]] = set()
        self._reference_signature: tuple[object, ...] = ()
        self._last_result_field = "corrected"
        self._channel_ranges: dict[str, dict[str, Any]] = {}
        self._reference_initialized: set[tuple[str, str]] = set()
        self._overlay_items: dict[str, list[Any]] = {}
        self._all_lines: dict[str, list[Any]] = {}
        self._label_callbacks: dict[str, Callable[..., None]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        toolbar = QHBoxLayout()
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("segmentChannelSelector")
        self.channel_combo.setMinimumWidth(110)
        self.add_button = QPushButton("新增分割线")
        self.add_button.setObjectName("addSegmentBoundary")
        self.roi_button = QPushButton("调整范围")
        self.roi_button.setObjectName("editSegmentRoi")
        self.roi_button.setCheckable(True)
        self.prepare_reference_button = QPushButton("计算 STFT 参考")
        self.prepare_reference_button.clicked.connect(self.reference_requested.emit)
        for widget in (self.channel_combo, self.add_button, self.roi_button, self.prepare_reference_button):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.views = QTabWidget()
        self.views.setDocumentMode(True)
        self.views.setObjectName("segmentReferenceTabs")
        self.views.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.raw_view = RawSignalView()
        self.raw_view.channel_combo.hide()
        for raw_label in self.raw_view.findChildren(QLabel):
            raw_label.hide()
        self.raw_view.analysis_region.setMovable(True)
        self.spectrogram = SpectrogramView()
        self.reference_velocity = VelocityView()
        self.reference_velocity.set_time_origin(ExportTimeOrigin.ABSOLUTE)
        for view in (self.spectrogram, self.reference_velocity):
            view.channel_combo.hide()
            first_item = view.controls_layout.itemAt(0)
            first_widget = first_item.widget() if first_item is not None else None
            if first_widget is not None:
                first_widget.hide()
        self.reference_velocity.result_source_combo.hide()
        self.reference_velocity.source_notice.setText("请先在经典工作区生成速度结果。")
        self.result_plot = pg.PlotWidget(background="w")
        self.result_plot.setObjectName("segmentedResultPlot")
        self.result_plot.setLabel("bottom", "绝对时间", units="μs")
        self.result_plot.showGrid(x=True, y=True, alpha=.15)
        self.views.addTab(self.raw_view, "原始信号")
        self.views.addTab(self.spectrogram, "STFT 参考")
        self.views.addTab(self.reference_velocity, "经典速度")
        self.views.addTab(self.result_plot, "分段结果")
        self.splitter.addWidget(self.views)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("manualSegmentTable")
        self.table.setHorizontalHeaderLabels(("区间", "起点 / μs", "终点 / μs", "阶段", "算法", "有效 / 总数"))
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.splitter.addWidget(self.table)
        self.splitter.setSizes([650, 105])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        layout.addWidget(self.splitter, 1)
        self.status = QLabel("导入数据后添加分割线。")
        self.status.setWordWrap(True)
        self.status.setObjectName("segmentStatus")
        layout.addWidget(self.status)

        self.properties = QWidget()
        self.properties.setObjectName("segmentProperties")
        properties_layout = QVBoxLayout(self.properties)
        properties_layout.setContentsMargins(0, 0, 0, 0)
        self.property_scroll = QScrollArea()
        self.property_scroll.setWidgetResizable(True)
        self.property_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        properties_layout.addWidget(self.property_scroll, 1)
        property_page = QWidget()
        property_page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        side = QVBoxLayout(property_page)
        side.setSpacing(8)
        self.interval_title = QLabel("当前区间")
        self.interval_title.setObjectName("sectionTitle")
        side.addWidget(self.interval_title)
        self.interval_combo = QComboBox()
        self.interval_combo.setObjectName("segmentIntervalSelector")
        side.addWidget(self.interval_combo)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.start_spin = QDoubleSpinBox()
        self.end_spin = QDoubleSpinBox()
        self.boundary_spin = QDoubleSpinBox()
        self.boundary_spin.setObjectName("segmentBoundaryTimeUs")
        for spin in (self.start_spin, self.end_spin, self.boundary_spin):
            spin.setDecimals(9)
            spin.setRange(-1e12, 1e12)
            spin.setSuffix(" μs")
            spin.setKeyboardTracking(False)
        self.stage_combo = QComboBox()
        self.stage_combo.setObjectName("segmentStage")
        for key, label in STAGE_LABELS.items():
            self.stage_combo.addItem(label, key)
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.setObjectName("segmentAlgorithm")
        for key, label in self._algorithms.items():
            self.algorithm_combo.addItem(label, key)
        form.addRow("起点", self.start_spin)
        form.addRow("终点", self.end_spin)
        form.addRow("阶段", self.stage_combo)
        form.addRow("当前算法", self.algorithm_combo)
        side.addLayout(form)
        self.recommendation_label = QLabel()
        self.recommendation_label.setWordWrap(True)
        self.recommendation_label.setObjectName("segmentRecommendation")
        side.addWidget(self.recommendation_label)
        self.use_recommendation_button = QPushButton("采用推荐算法")
        self.use_recommendation_button.clicked.connect(self._adopt_recommendation)
        side.addWidget(self.use_recommendation_button)
        self.boundary_combo = QComboBox()
        self.boundary_combo.setObjectName("segmentBoundarySelector")
        self.delete_button = QPushButton("删除所选分割线")
        self.delete_button.setToolTip("合并相邻区间并保留左区间的阶段、算法。可撤销。")
        self.undo_button = QPushButton("撤销当前通道编辑")
        self._history: dict[str, list[tuple[tuple[Segment, ...], set[tuple[str, str]]]]] = {}
        boundary_content = QWidget()
        boundary_form = QVBoxLayout(boundary_content)
        boundary_form.setContentsMargins(0, 0, 0, 0)
        for boundary_widget in (self.boundary_combo, self.boundary_spin, self.delete_button, self.undo_button):
            boundary_form.addWidget(boundary_widget)
        self.boundary_section = CollapsibleSection("分割线", boundary_content, expanded=True)
        side.addWidget(self.boundary_section)
        self.run_button = QPushButton("分析当前通道")
        self.run_button.setObjectName("runSegmentedAnalysis")
        self.run_button.setProperty("primary", True)
        self.export_button = QPushButton("导出分段结果…")
        self.export_button.setObjectName("exportSegmentedResults")
        properties_layout.addWidget(self.run_button)
        properties_layout.addWidget(self.export_button)
        self.field_combo = QComboBox()
        self.field_combo.addItem("校正速度", "corrected")
        self.field_combo.addItem("表观速度", "apparent")
        self.field_combo.addItem("拍频", "frequency")
        self.candidate_check = QCheckBox("显示候选点")
        self.candidate_check.setToolTip("未通过质量筛选的估计，只用于诊断。")
        side.addWidget(self.field_combo)
        side.addWidget(self.candidate_check)
        self.save_button = QPushButton("保存分段…")
        self.load_button = QPushButton("载入分段…")
        self.copy_button = QPushButton("应用到全部通道")
        plan_content = QWidget()
        plan_layout = QVBoxLayout(plan_content)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.save_button, self.load_button, self.copy_button):
            plan_layout.addWidget(widget)
        side.addWidget(CollapsibleSection("分段文件与通道", plan_content))
        side.addStretch(1)
        self.property_scroll.setWidget(property_page)
        self.channel_combo.currentIndexChanged.connect(
            lambda _index: self._select_channel(str(self.channel_combo.currentData() or "")))
        self.add_button.clicked.connect(lambda: self.add_boundary())
        self.delete_button.clicked.connect(self.delete_boundary)
        self.undo_button.clicked.connect(self.undo_edit)
        self.boundary_combo.currentIndexChanged.connect(self._boundary_selected)
        self.boundary_spin.valueChanged.connect(self._numeric_boundary_changed)
        self.interval_combo.currentIndexChanged.connect(self._interval_selected)
        self.stage_combo.currentIndexChanged.connect(lambda _index: self.set_segment(
            self.interval_combo.currentIndex(), stage=str(self.stage_combo.currentData())))
        self.algorithm_combo.currentIndexChanged.connect(lambda _index: self.set_segment(
            self.interval_combo.currentIndex(), algorithm=str(self.algorithm_combo.currentData())))
        self.start_spin.valueChanged.connect(lambda value: self._interval_edge_changed(True, value))
        self.end_spin.valueChanged.connect(lambda value: self._interval_edge_changed(False, value))
        self.run_button.clicked.connect(self.run_analysis)
        self.export_button.clicked.connect(self._choose_export)
        self.save_button.clicked.connect(self._save_plan_dialog)
        self.load_button.clicked.connect(self._load_plan_dialog)
        self.copy_button.clicked.connect(self.copy_plan_to_all)
        self.field_combo.currentIndexChanged.connect(self._plot_result)
        self.candidate_check.toggled.connect(self._plot_result)
        self.table.currentCellChanged.connect(self._select_segment)
        self.roi_button.toggled.connect(self._toggle_roi)
        self.roi_button.clicked.connect(
            lambda checked: self.views.setCurrentWidget(self.raw_view) if checked else None)
        self.raw_view.analysis_region_committed.connect(self.roi_change_requested.emit)
        self.result_plot.scene().sigMouseMoved.connect(self._result_cursor)
        self.views.currentChanged.connect(lambda _index: self._rebuild())
        for key, plot in self._plots().items():
            callback = partial(self._position_interval_labels, key)
            self._label_callbacks[key] = callback
            plot.plotItem.vb.sigRangeChanged.connect(callback)
        self._refresh_controls()

    @property
    def plan(self) -> tuple[Segment, ...]:
        return self.plans.get(self._channel, ())

    def _remember(self) -> None:
        history = self._history.setdefault(self._channel, [])
        snapshot = (self.plan, {choice for choice in self.manual_choices if choice[0] == self._channel})
        if not history or history[-1] != snapshot:
            history.append(snapshot)
        del history[:-64]

    def undo_edit(self) -> None:
        history = self._history.get(self._channel, [])
        if not history or self.busy:
            return
        self.plans[self._channel], choices = history.pop()
        self.manual_choices = {choice for choice in self.manual_choices if choice[0] != self._channel} | choices
        self._invalidate("已撤销分段编辑；请重新分析。")
        self._rebuild()

    def set_references(self, stft: Mapping[str, Any], analyses: Mapping[str, Any]) -> None:
        self._stft_references = dict(stft)
        self._analysis_references = dict(analyses)
        signature = (self._channel, *(id(value) for value in stft.values()),
                     *(id(value) for value in analyses.values()))
        if signature == self._reference_signature:
            return
        self._reference_signature = signature
        ranges = [plot.viewRange() for plot in self._plots().values()]
        selected_stft = {self._channel: stft[self._channel]} if self._channel in stft else {}
        selected_analysis = ({self._channel: analyses[self._channel]}
                             if self._channel in analyses else {})
        floor = self._configuration.relative_db_floor if self._configuration is not None else -60.
        self.spectrogram.set_stft_results(selected_stft, relative_db_floor=floor)
        self.reference_velocity.set_analyses(selected_analysis, relative_db_floor=floor)
        if not selected_analysis:
            self.reference_velocity.source_notice.setText("请先在经典工作区生成速度结果。")
            self.reference_velocity.source_notice.show()
        if self._roi is not None:
            self.spectrogram.set_view_configuration(
                analysis_start_time_s=self._roi.start_time_s,
                analysis_end_time_s=self._roi.end_time_s,
                minimum_frequency_hz=self._frequency_band_hz[0] if self._frequency_band_hz else 0.,
                maximum_frequency_hz=self._frequency_band_hz[1] if self._frequency_band_hz else 1e9)
        # Reference data can arrive asynchronously while a gate is being inspected.
        # Keep the active view; initialize previously empty reference plots only once.
        for (key, plot), bounds in zip(self._plots().items(), ranges):
            if key in ("raw", "result") or (self._channel, key) in self._reference_initialized:
                plot.setRange(xRange=bounds[0], yRange=bounds[1], padding=0)
            if (key == "stft" and selected_stft) or (key == "classic" and selected_analysis):
                self._reference_initialized.add((self._channel, key))
        self._draw_overlays()

    def _plots(self) -> dict[str, Any]:
        return {"raw": self.raw_view.plot_widget, "stft": self.spectrogram.plot_widget,
                "classic": self.reference_velocity.plot_widget, "result": self.result_plot}

    def _sync_boundary_items(self) -> None:
        for lines in self._all_lines.values():
            for index, line in enumerate(lines):
                if index < len(self.plan) - 1:
                    with QSignalBlocker(line):
                        line.setValue(self.plan[index].end_s * 1e6)
        for row, segment in enumerate(self.plan):
            for column, value in ((1, segment.start_s), (2, segment.end_s)):
                item = self.table.item(row, column)
                if item is not None:
                    item.setText(f"{value * 1e6:.9f}")
            for key, items in self._overlay_items.items():
                labels = [item for item in items if isinstance(item, pg.TextItem)]
                if row < len(labels):
                    labels[row].setPos((segment.start_s + segment.end_s) * .5e6,
                                       self._plots()[key].viewRange()[1][1])

    def _position_interval_labels(self, key: str, *_args: object) -> None:
        x_bounds, y_bounds = self._plots()[key].viewRange()
        labels = [item for item in self._overlay_items.get(key, []) if isinstance(item, pg.TextItem)]
        for label, segment in zip(labels, self.plan):
            left = max(segment.start_s * 1e6, x_bounds[0])
            right = min(segment.end_s * 1e6, x_bounds[1])
            label.setVisible(left <= right)
            label.setPos((left + right) * .5, y_bounds[1])

    def _retire_overlays(self, key: str) -> None:
        for item in self._overlay_items.pop(key, []):
            if isinstance(item, QObject):
                item.blockSignals(True)
                item.setParent(self)
                item.deleteLater()
            self._plots()[key].removeItem(item)

    def _draw_overlays(self) -> None:
        for key, plot in self._plots().items():
            self._retire_overlays(key)
            items: list[Any] = []
            lines: list[Any] = []
            for index, segment in enumerate(self.plan[:-1]):
                line = pg.InfiniteLine(
                    pos=segment.end_s * 1e6, angle=90, movable=not self.busy,
                    pen=pg.mkPen("#cb723b", width=1.5), hoverPen=pg.mkPen("#a74817", width=3),
                    label=f"分割线 {index + 1}",
                    labelOpts={"position": .12, "color": "#975024", "fill": "#ffffff"})
                line.setZValue(30)
                line.setCursor(Qt.CursorShape.SizeHorCursor)
                line.setToolTip(f"分割线 {index + 1}：区间 {index + 1} 与 {index + 2} 的边界")
                plot.addItem(line, ignoreBounds=True)
                line.sigPositionChanged.connect(lambda moved, i=index: self._line_moving(i, moved))
                line.sigPositionChangeFinished.connect(self._line_finished)
                line.sigClicked.connect(lambda _line, _event, i=index: self.boundary_combo.setCurrentIndex(i))
                items.append(line)
                lines.append(line)
            top = plot.viewRange()[1][1]
            for row, segment in enumerate(self.plan):
                label = pg.TextItem(
                    f"区间 {row + 1} · {STAGE_LABELS[segment.stage]}\n{self._algorithms[segment.algorithm]}",
                    color="#315268", fill=(255, 255, 255, 225), anchor=(.5, 0))
                label.setPos((segment.start_s + segment.end_s) * .5e6, top)
                label.setZValue(25)
                label.setToolTip(f"{segment.start_s * 1e6:.9g}–{segment.end_s * 1e6:.9g} μs")
                plot.addItem(label, ignoreBounds=True)
                items.append(label)
            self._overlay_items[key] = items
            self._all_lines[key] = lines
        self.lines = self._all_lines.get("raw", [])
        for key in self._plots():
            self._position_interval_labels(key)

    def _interval_selected(self, row: int) -> None:
        if self._syncing or not 0 <= row < len(self.plan):
            return
        segment = self.plan[row]
        self.interval_title.setText(f"区间 {row + 1}")
        with QSignalBlocker(self.table):
            self.table.selectRow(row)
        dt = self.records[self._channel].representative_sample_interval_s
        for spin, value in ((self.start_spin, segment.start_s), (self.end_spin, segment.end_s)):
            with QSignalBlocker(spin):
                spin.setRange(-1e12, 1e12)
                spin.setValue(value * 1e6)
                spin.setSingleStep(dt * 1e6)
        self.start_spin.setReadOnly(row == 0)
        self.end_spin.setReadOnly(row == len(self.plan) - 1)
        with QSignalBlocker(self.stage_combo), QSignalBlocker(self.algorithm_combo):
            self.stage_combo.setCurrentIndex(self.stage_combo.findData(segment.stage))
            self.algorithm_combo.setCurrentIndex(self.algorithm_combo.findData(segment.algorithm))
        algorithm = RECOMMENDATIONS.get(segment.stage, "stft")
        manual = (self._channel, segment.id) in self.manual_choices
        self.recommendation_label.setText(
            f"推荐：{self._algorithms[algorithm]}" + (" · 保留人工选择" if manual else " · 自动选择"))
        self.recommendation_label.setToolTip(REASONS.get(segment.stage, "稳定或未知区域以 STFT 为基准。"))
        self.use_recommendation_button.setEnabled(manual and not self.busy)

    def _interval_edge_changed(self, start: bool, value_us: float) -> None:
        row = self.interval_combo.currentIndex()
        boundary = row - 1 if start else row
        if not self._syncing and 0 <= boundary < len(self.plan) - 1:
            self.move_boundary(boundary, value_us * 1e-6)
            self._rebuild()

    def _adopt_recommendation(self) -> None:
        row = self.interval_combo.currentIndex()
        if 0 <= row < len(self.plan):
            self._remember()
            self.manual_choices.discard((self._channel, self.plan[row].id))
            self.set_segment(row, stage=self.plan[row].stage)
            self._interval_selected(row)

    def set_context(self, records: Mapping[str, SignalRecord], roi: AnalysisRange | None,
                    configuration: AnalysisRunConfiguration | None, source: Path | None,
                    frequency_band_hz: tuple[float, float] | None = None) -> None:
        new_data = tuple((key, id(record)) for key, record in records.items()) != tuple(
            (key, id(record)) for key, record in self.records.items())
        changed = (new_data or roi != self._roi or configuration != self._configuration
                   or frequency_band_hz != self._frequency_band_hz)
        if not changed:
            return
        previous_ranges = {key: plot.viewRange() for key, plot in self._plots().items()}
        if roi != self._roi:
            self._history.clear()
        old_plans = self.plans
        self.records, self._roi, self._configuration, self._source = records, roi, configuration, source
        self._frequency_band_hz = frequency_band_hz
        self.revision += 1
        self.results.clear()
        if new_data:
            self.plans = {}
            self.manual_choices.clear()
            self._history.clear()
            self._stft_references = {}
            self._analysis_references = {}
            self._channel_ranges.clear()
            self._reference_initialized.clear()
            self._channel = ""
        if roi is not None:
            for name in records:
                old = () if new_data else old_plans.get(name, ())
                if not old or old[0].start_s != roi.start_time_s or old[-1].end_s != roi.end_time_s:
                    # ROI changes preserve interval labels by overlap, with exact shared endpoints.
                    edges = [roi.start_time_s, *[s.end_s for s in old
                             if roi.start_time_s < s.end_s < roi.end_time_s], roi.end_time_s]
                    plan = []
                    for left, right in zip(edges, edges[1:]):
                        previous = next((s for s in old if s.start_s <= (left + right) / 2 < s.end_s), None)
                        plan.append(replace(previous, start_s=left, end_s=right) if previous else
                                    Segment(uuid4().hex[:12], left, right))
                    self.plans[name] = tuple(plan)
        with QSignalBlocker(self.channel_combo):
            self.channel_combo.clear()
            for name in records:
                self.channel_combo.addItem(channel_label(name), name)
            if self._channel in records:
                self.channel_combo.setCurrentIndex(self.channel_combo.findData(self._channel))
        self._select_channel(str(self.channel_combo.currentData() or ""))
        if not new_data:
            for key, plot in self._plots().items():
                plot.setRange(xRange=previous_ranges[key][0], yRange=previous_ranges[key][1], padding=0)
        self.status.setText("分段和参数已就绪；编辑后点击分析。" if roi else "请在原始信号页确认分析 ROI。")
        self._refresh_controls()

    def _select_channel(self, channel: str) -> None:
        if self._channel and self._channel in self.records:
            self._channel_ranges[self._channel] = {key: plot.viewRange() for key, plot in self._plots().items()}
        self._channel = channel
        self._reference_signature = ()
        self.raw_view.set_records({channel: self.records[channel]} if channel in self.records else {})
        self._toggle_roi(self.roi_button.isChecked())
        self._rebuild()
        self._plot_result()
        if self._roi is not None:
            self.raw_view.plot_widget.setXRange(self._roi.start_time_s * 1e6,
                                                self._roi.end_time_s * 1e6, padding=.02)
        self.set_references(getattr(self, "_stft_references", {}),
                            getattr(self, "_analysis_references", {}))
        for key, bounds in self._channel_ranges.get(channel, {}).items():
            self._plots()[key].setRange(xRange=bounds[0], yRange=bounds[1], padding=0)
        self._sync_boundary_items()

    def _toggle_roi(self, enabled: bool) -> None:
        if self._roi is not None:
            self.raw_view.set_analysis_region_s(self._roi.start_time_s, self._roi.end_time_s)
        self.raw_view.analysis_region.setVisible(enabled and self._roi is not None)

    def _invalidate(self, message: str = "分段已修改；请重新分析。") -> None:
        self.revision += 1
        self.results.pop(self._channel, None)
        for curve in self.result_plot.listDataItems():
            self.result_plot.removeItem(curve)
        self.status.setText(message)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 5)
            if item is not None:
                item.setText("—")
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        ready = bool(self.plan) and self._configuration is not None
        for button in (self.add_button, self.save_button, self.load_button, self.copy_button,
                       self.roi_button):
            button.setEnabled(ready and not self.busy)
        self.run_button.setEnabled(ready and not self.busy and self.can_analyze())
        self.delete_button.setEnabled(bool(self.lines) and not self.busy)
        self.boundary_combo.setEnabled(bool(self.lines) and not self.busy)
        self.boundary_spin.setEnabled(bool(self.lines) and not self.busy)
        self.table.setEnabled(not self.busy)
        self.channel_combo.setEnabled(not self.busy and bool(self.records))
        self.export_button.setEnabled(bool(self.results) and not self.busy)
        for editor in (self.interval_combo, self.stage_combo, self.algorithm_combo,
                       self.start_spin, self.end_spin):
            editor.setEnabled(ready and not self.busy)
        self.prepare_reference_button.setEnabled(bool(self.records) and not self.busy and self.can_analyze())
        self.undo_button.setEnabled(bool(self._history.get(self._channel)) and not self.busy)
        for lines in self._all_lines.values():
            for line in lines:
                line.setMovable(not self.busy)

    def _rebuild(self) -> None:
        selected_boundary = max(0, self.boundary_combo.currentIndex())
        selected_row = self.table.currentRow()
        table_blocker = QSignalBlocker(self.table)
        self._syncing = True
        self._draw_overlays()
        self.boundary_combo.clear()
        for index in range(max(0, len(self.plan) - 1)):
            self.boundary_combo.addItem(f"分割线 {index + 1}")
        with QSignalBlocker(self.interval_combo):
            self.interval_combo.clear()
            for row, segment in enumerate(self.plan):
                self.interval_combo.addItem(f"区间 {row + 1} · {STAGE_LABELS[segment.stage]}", segment.id)
            self.interval_combo.setCurrentIndex(min(max(selected_row, 0), len(self.plan) - 1))
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.plan))
        result = self.results.get(self._channel)
        for row, segment in enumerate(self.plan):
            counts = "—"
            if result is not None:
                indices = np.array(result.segment_ids) == segment.id
                counts = f"{int(result.valid[indices].sum())} / {int(indices.sum())}"
            for column, text in ((0, str(row + 1)), (1, f"{segment.start_s * 1e6:.9f}"),
                                 (2, f"{segment.end_s * 1e6:.9f}"), (5, counts)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
            stage = QComboBox()
            for key, label in STAGE_LABELS.items():
                stage.addItem(label, key)
            stage.setCurrentIndex(stage.findData(segment.stage))
            stage.currentIndexChanged.connect(lambda _index, r=row, combo=stage:
                                              self.set_segment(r, stage=str(combo.currentData())))
            self.table.setCellWidget(row, 3, stage)
            algorithm = QComboBox()
            for key, label in self._algorithms.items():
                algorithm.addItem(label, key)
            algorithm.setCurrentIndex(algorithm.findData(segment.algorithm))
            recommendation = RECOMMENDATIONS.get(segment.stage, "stft")
            algorithm.setToolTip(f"可选建议：{self._algorithms[recommendation]}；由实验员决定。\n"
                                 "Dechirp/VarPro 使用冻结研究参数和原始前缀事件门槛；\n"
                                 "Clutter VarPro 假设前缀静止杂波持续，可能移除目标信号。")
            algorithm.currentIndexChanged.connect(lambda _index, r=row, combo=algorithm:
                                                  self.set_segment(r, algorithm=str(combo.currentData())))
            self.table.setCellWidget(row, 4, algorithm)
        self._syncing = False
        self.boundary_combo.setCurrentIndex(min(selected_boundary, len(self.lines) - 1))
        if self.plan:
            self.table.selectRow(min(max(selected_row, 0), len(self.plan) - 1))
        self.table.resizeRowsToContents()
        del table_blocker
        self._boundary_selected(self.boundary_combo.currentIndex())
        self._interval_selected(self.interval_combo.currentIndex())
        self._refresh_controls()

    def set_segment(self, row: int, *, stage: str | None = None, algorithm: str | None = None) -> None:
        if self._syncing or not 0 <= row < len(self.plan):
            return
        if algorithm is not None and algorithm not in self._algorithms:
            raise ValueError("Unknown algorithm")
        current = self.plan[row]
        self._remember()
        if algorithm is not None:
            self.manual_choices.add((self._channel, current.id))
        chosen_stage = stage or current.stage
        chosen_algorithm = algorithm or current.algorithm
        if algorithm is None and stage is not None:
            # A deliberate stage edit starts a new recommendation decision.
            # Display refreshes never call this method and preserve overrides.
            self.manual_choices.discard((self._channel, current.id))
            chosen_algorithm = RECOMMENDATIONS.get(chosen_stage, "stft")
        updated = replace(current, stage=chosen_stage, algorithm=chosen_algorithm)
        if current == updated:
            self._interval_selected(self.interval_combo.currentIndex())
            return
        values = list(self.plan)
        values[row] = updated
        self.plans[self._channel] = tuple(values)
        self._invalidate()

        self._sync_boundary_items()
        # Keep the emitting combo alive. Replacing table widgets from their own
        # currentIndexChanged signal leaves native popup/editor artifacts.
        stage_combo = self.table.cellWidget(row, 3)
        algorithm_combo = self.table.cellWidget(row, 4)
        if isinstance(stage_combo, QComboBox):
            with QSignalBlocker(stage_combo):
                stage_combo.setCurrentIndex(stage_combo.findData(updated.stage))
        if isinstance(algorithm_combo, QComboBox):
            with QSignalBlocker(algorithm_combo):
                algorithm_combo.setCurrentIndex(algorithm_combo.findData(updated.algorithm))
            recommendation = RECOMMENDATIONS.get(updated.stage, "stft")
            algorithm_combo.setToolTip(f"可选建议：{self._algorithms[recommendation]}；由实验员决定。\n"
                                       "研究算法的前缀、事件与支路假设须结合频谱复核。")

        self._draw_overlays()
        with QSignalBlocker(self.interval_combo):
            self.interval_combo.setItemText(row, f"区间 {row + 1} · {STAGE_LABELS[updated.stage]}")
        self._interval_selected(self.interval_combo.currentIndex())

    def add_boundary(self, time_s: float | None = None) -> bool:
        if not self.plan or self._roi is None:
            return False
        row = max(0, self.table.currentRow())
        segment = self.plan[min(row, len(self.plan) - 1)]
        value = (segment.start_s + segment.end_s) / 2 if time_s is None else float(time_s)
        index = next((i for i, s in enumerate(self.plan) if s.start_s < value < s.end_s), None)
        if index is None:
            return False
        segment = self.plan[index]
        dt = self.records[self._channel].representative_sample_interval_s
        if min(value - segment.start_s, segment.end_s - value) < dt:
            self.status.setText("分割线需与相邻边界至少相隔一个采样间隔。")
            return False
        self._remember()
        values = list(self.plan)
        values[index:index + 1] = [replace(segment, end_s=value),
                                  replace(segment, id=uuid4().hex[:12], start_s=value)]
        if (self._channel, segment.id) in self.manual_choices:
            self.manual_choices.add((self._channel, values[index + 1].id))
        self.plans[self._channel] = tuple(values)
        self._invalidate()
        self._rebuild()
        self.boundary_combo.setCurrentIndex(index)
        self.table.selectRow(index + 1)
        return True

    def move_boundary(self, index: int, value_s: float) -> None:
        if self.busy or not np.isfinite(value_s) or not 0 <= index < len(self.plan) - 1:
            return
        values = list(self.plan)
        dt = self.records[self._channel].representative_sample_interval_s
        value = float(np.clip(value_s, values[index].start_s + dt, values[index + 1].end_s - dt))
        if value == values[index].end_s:
            return
        self._remember()
        values[index] = replace(values[index], end_s=value)
        values[index + 1] = replace(values[index + 1], start_s=value)
        self.plans[self._channel] = tuple(values)
        self._invalidate()
        self._sync_boundary_items()

    def delete_boundary(self) -> None:
        index = self.boundary_combo.currentIndex()
        if not 0 <= index < len(self.plan) - 1:
            return
        self._remember()
        values = list(self.plan)
        values[index:index + 2] = [replace(values[index], end_s=values[index + 1].end_s)]
        self.plans[self._channel] = tuple(values)
        self._invalidate("区段已合并，保留左段的阶段与算法；请重新分析。")
        self._rebuild()

    def _line_moving(self, index: int, moved: Any | None = None) -> None:
        if self._syncing:
            return
        self.move_boundary(index, float((moved or self.lines[index]).value()) * 1e-6)
        for lines in self._all_lines.values():
            for i, line in enumerate(lines):
                with QSignalBlocker(line):
                    line.setValue(self.plan[i].end_s * 1e6)
        self._interval_selected(self.interval_combo.currentIndex())
        self.boundary_combo.setCurrentIndex(index)
        self._boundary_selected(index)

    def _line_finished(self, _line: object) -> None:
        self._rebuild()

    def _boundary_selected(self, index: int) -> None:
        if self._syncing or not 0 <= index < len(self.plan) - 1:
            return
        dt = self.records[self._channel].representative_sample_interval_s
        with QSignalBlocker(self.boundary_spin):
            self.boundary_spin.setRange((self.plan[index].start_s + dt) * 1e6,
                                        (self.plan[index + 1].end_s - dt) * 1e6)
            self.boundary_spin.setSingleStep(dt * 1e6)
            self.boundary_spin.setValue(self.plan[index].end_s * 1e6)
        for lines in self._all_lines.values():
            for i, line in enumerate(lines):
                line.setBounds(((self.plan[i].start_s + dt) * 1e6,
                                (self.plan[i + 1].end_s - dt) * 1e6))

    def _numeric_boundary_changed(self, value_us: float) -> None:
        if not self._syncing:
            self.move_boundary(self.boundary_combo.currentIndex(), value_us * 1e-6)
            self._rebuild()

    def _select_segment(self, row: int, _column: int, _old_row: int, _old_column: int) -> None:
        if not self._syncing and row >= 0:
            with QSignalBlocker(self.interval_combo):
                self.interval_combo.setCurrentIndex(row)
            self._interval_selected(row)

    def copy_plan_to_all(self) -> None:
        source = self.plan
        manual_ids = {identity for channel, identity in self.manual_choices if channel == self._channel}
        for name in self.records:
            self.plans[name] = tuple(source)
            self.manual_choices = {choice for choice in self.manual_choices if choice[0] != name}
            self.manual_choices.update((name, identity) for identity in manual_ids)
        self.results.clear()
        self._invalidate("分段已应用到全部通道；各通道仍需独立分析。")

    def run_analysis(self) -> bool:
        if self.busy or self._roi is None or self._configuration is None or not self.plan:
            return False
        if not self.can_analyze():
            self.status.setText("当前参数不可用，或经典分析正在运行；请先完成检查。")
            return False
        configuration = self._configuration
        options = workflow_options(configuration)
        if self._frequency_band_hz is not None:
            options["minimum_frequency_hz"], options["maximum_frequency_hz"] = self._frequency_band_hz
        request = EstimatorRequest(self.records[self._channel], self._roi.start_time_s,
                                   self._roi.end_time_s, configuration.vacuum_wavelength_m,
                                   options)
        self.results.pop(self._channel, None)
        self.result_plot.clear()
        self.busy = True
        self._refresh_controls()
        self.busy_changed.emit(True)
        self.status.setText("正在分析；保留原始窗口上下文…")
        worker = _Worker(self.revision, self._channel, request, self.plan, configuration)
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        worker.signals.progress.connect(lambda name: self.status.setText(f"正在运行 {name}…"))
        self._worker = worker
        QThreadPool.globalInstance().start(worker)
        return True

    def _finished(self, revision: int, channel: str, value: object) -> None:
        self.busy = False
        self.busy_changed.emit(False)
        if revision != self.revision or not isinstance(value, SegmentedResult):
            self.status.setText("编辑或参数已变化，本次结果已丢弃；请重新分析。")
        else:
            self.results[channel] = value
            errors = [row for row in value.metadata["algorithms"] if row["error"]]
            self.status.setText(f"{channel_label(channel)} · {int(value.valid.sum())}/{len(value.time_s)} 点有效"
                                + (f" · {len(errors)} 段算法异常" if errors else ""))
            self.status.setToolTip("分割线处断线，缺失保留 NaN。科学质量标志随 CSV 导出。")
        self._rebuild()
        self._plot_result()
        if channel in self.results:
            self.views.setCurrentWidget(self.result_plot)
        self._refresh_controls()

    def _failed(self, _revision: int, message: str) -> None:
        self.busy = False
        self.busy_changed.emit(False)
        self.status.setText(f"分析失败：{message}")
        self._refresh_controls()

    def _plot_result(self, *_args: object) -> None:
        previous_range = self.result_plot.viewRange()
        had_data = bool(self.result_plot.listDataItems())
        self.result_plot.clear()
        result = self.results.get(self._channel)
        field = str(self.field_combo.currentData())
        field_changed = field != self._last_result_field
        self._last_result_field = field
        self.result_plot.setLabel("left", "拍频" if field == "frequency" else "速度",
                                  units="GHz" if field == "frequency" else "m/s")
        if result is None:
            self._draw_overlays()
            return
        values = (result.frequency_hz * 1e-9 if field == "frequency" else
                  result.apparent_velocity_m_s if field == "apparent" else result.corrected_velocity_m_s)
        colors = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")
        for index, segment in enumerate(result.segments):
            mask = np.asarray(result.segment_ids) == segment.id
            self.result_plot.plot(result.time_s[mask] * 1e6, values[mask],
                                  pen=pg.mkPen(colors[index % len(colors)], width=2),
                                  symbol="o", symbolSize=3, connect="finite")
            if segment.stage == "stationary" and field == "apparent":
                self.result_plot.plot([segment.start_s * 1e6, segment.end_s * 1e6], [0., 0.],
                    pen=pg.mkPen("#777777", width=1, style=Qt.PenStyle.DashLine),
                    name="人工静止先验（非测量）")
                label = pg.TextItem("人工静止先验 0 m/s（非测量）", color="#666666", anchor=(0, 1))
                label.setPos(segment.start_s * 1e6, 0.)
                self.result_plot.addItem(label)
        if self.candidate_check.isChecked():
            candidate = result.candidate_frequency_hz
            if field == "frequency":
                candidate = candidate * 1e-9
            elif field == "apparent":
                candidate = candidate * result.wavelength_m / 2
            else:
                # Candidate estimates stay raw apparent velocities; don't plot
                # them against a corrected-velocity axis.
                candidate = np.full(len(candidate), np.nan)
            self.result_plot.plot(result.time_s * 1e6, candidate, pen=None,
                                  symbol="x", symbolSize=4, symbolPen="#999999")
        if had_data:
            self.result_plot.setXRange(*previous_range[0], padding=0)
            if field_changed:
                series = tuple(curve.getData() for curve in self.result_plot.listDataItems())
                bounds = finite_velocity_xy_view_range(series, x_limits=tuple(previous_range[0]))
                if bounds is not None:
                    self.result_plot.setYRange(*bounds[1], padding=0)
            else:
                self.result_plot.setYRange(*previous_range[1], padding=0)
        else:
            self.result_plot.autoRange()
        self._draw_overlays()

    def _result_cursor(self, position: Any) -> None:
        result = self.results.get(self._channel)
        if result is None or not len(result.time_s):
            return
        if not self.result_plot.sceneBoundingRect().contains(position):
            return
        time_s = self.result_plot.plotItem.vb.mapSceneToView(position).x() * 1e-6
        index = int(np.clip(np.searchsorted(result.time_s, time_s), 0, len(result.time_s) - 1))
        if index and abs(result.time_s[index - 1] - time_s) < abs(result.time_s[index] - time_s):
            index -= 1
        self.status.setText(f"{result.time_s[index] * 1e6:.9f} μs · {result.algorithm_ids[index]} · "
                            f"{result.frequency_hz[index] * 1e-9:.6g} GHz · "
                            f"{result.corrected_velocity_m_s[index]:.6g} m/s · {result.quality[index]}")

    def export_to(self, destination: Path) -> tuple[Path, ...]:
        paths = export_segmented_results(self.results, destination, source_path=self._source)
        self.status.setText(f"已导出 {len(self.results)} 个通道")
        self.status.setToolTip(str(destination))
        return paths

    def _choose_export(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "选择导出位置（自动新建结果目录）")
        if not parent:
            return
        try:
            self.export_to(Path(parent) / f"PDV_TASK012_{datetime.now():%Y%m%d_%H%M%S_%f}")
        except Exception as exc:
            self.status.setText(f"导出失败：{exc}")

    def save_plan(self, path: Path) -> None:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"schema": "pdv-segment-plan/1", "source_path": str(self._source),
                       "roi_s": asdict(self._roi) if self._roi else None,
                       "manual_choices": sorted(self.manual_choices),
                       "channels": {key: [asdict(s) for s in plan] for key, plan in self.plans.items()}},
                      handle, ensure_ascii=False, indent=2, allow_nan=False)

    def load_plan(self, path: Path) -> None:
        if self._roi is None:
            raise ValueError("Confirm ROI before loading a plan")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != "pdv-segment-plan/1" or data.get("roi_s") != asdict(self._roi):
            raise ValueError("分段文件的格式或 ROI 与当前数据不一致")
        pending = {}
        for channel, rows in data["channels"].items():
            if channel not in self.records:
                raise ValueError(f"当前数据中没有通道 {channel}")
            plan = tuple(Segment(**row) for row in rows)
            validate_plan(plan, self._roi.start_time_s, self._roi.end_time_s)
            if any(segment.algorithm not in self._algorithms for segment in plan):
                raise ValueError("分段文件包含未注册算法")
            pending[channel] = plan
        self._remember()
        self.manual_choices = ({tuple(choice) for choice in data["manual_choices"]}
                               if "manual_choices" in data else
                               {(channel, segment.id) for channel, plan in pending.items() for segment in plan})
        self.plans.update(pending)
        self.results.clear()
        self._invalidate("分段已载入；请重新分析。")
        self._rebuild()

    def _save_plan_dialog(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "另存分段文件", "PDV_segments.json", "JSON (*.json)")
        if name:
            try:
                self.save_plan(Path(name))
                self.status.setText(f"已保存分段：{name}")
            except Exception as exc:
                self.status.setText(f"保存失败：{exc}")

    def _load_plan_dialog(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "载入分段文件", "", "JSON (*.json)")
        if name:
            try:
                self.load_plan(Path(name))
            except Exception as exc:
                self.status.setText(f"载入失败：{exc}")

    def dispose(self) -> None:
        """Disconnect plot-owned callbacks before Qt tears down their scenes."""
        if getattr(self, "_disposed", False):
            return
        self._disposed = True
        for key, callback in self._label_callbacks.items():
            self._plots()[key].plotItem.vb.sigRangeChanged.disconnect(callback)
        self._label_callbacks.clear()
        self.spectrogram.dispose_search_region_interactions()
        self.spectrogram.corridor_controller.detach_context()
        for key in self._plots():
            self._retire_overlays(key)
        self._all_lines.clear()
        self._overlay_items.clear()
        self.lines = []
        for plot in self._plots().values():
            plot.clear()
