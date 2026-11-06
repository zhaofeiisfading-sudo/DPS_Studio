"""Manual time gates inside the mature PDV workstation."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QObject, QRunnable, QSignalBlocker, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation import (
    EstimatorRequest, Segment, SegmentedResult, analyze_segments, default_pool, validate_plan,
)
from dps_studio.core.segmentation.export import export_segmented_results
from dps_studio.gui.analysis_session import AnalysisRange, AnalysisRunConfiguration
from dps_studio.gui.raw_signal_view import RawSignalView

STAGE_LABELS = {"unknown": "未知", "stationary": "静止", "onset": "起跳",
                "acceleration": "加速", "plateau": "平台", "decline": "下降",
                "rebound": "回升", "weak_signal": "弱信号", "noise": "噪声"}
RECOMMENDATIONS = {"acceleration": "dechirp", "onset": "dechirp", "rebound": "varpro",
                   "weak_signal": "varpro", "noise": "unobservable"}


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        toolbar = QHBoxLayout()
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("segmentChannelSelector")
        self.add_button = QPushButton("新增分割线")
        self.add_button.setObjectName("addSegmentBoundary")
        self.delete_button = QPushButton("删除分割线")
        self.boundary_combo = QComboBox()
        self.boundary_combo.setMinimumWidth(90)
        self.boundary_spin = QDoubleSpinBox()
        self.boundary_spin.setObjectName("segmentBoundaryTimeUs")
        self.boundary_spin.setDecimals(9)
        self.boundary_spin.setSuffix(" μs")
        self.boundary_spin.setKeyboardTracking(False)
        self.boundary_spin.setMinimumWidth(135)
        self.roi_button = QPushButton("ROI 范围")
        self.roi_button.setObjectName("editSegmentRoi")
        self.roi_button.setCheckable(True)
        self.roi_button.setToolTip("拖动蓝色范围的两端，松开确认分析 ROI；原始数据和窗口上下文保留。")
        for widget in (self.channel_combo, self.add_button, self.delete_button,
                       self.boundary_combo, self.boundary_spin, self.roi_button):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.raw_view = RawSignalView()
        # The channel selector above owns the active per-channel plan.
        self.raw_view.channel_combo.hide()
        for label in self.raw_view.findChildren(QLabel):
            label.hide()
        self.raw_view.analysis_region.setMovable(True)
        self.splitter.addWidget(self.raw_view)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("manualSegmentTable")
        self.table.setHorizontalHeaderLabels(("区段", "起点 / μs", "终点 / μs", "阶段", "算法", "有效 / 总数"))
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(120)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.splitter.addWidget(self.table)
        self.result_plot = pg.PlotWidget(background="w")
        self.result_plot.setObjectName("segmentedResultPlot")
        self.result_plot.setLabel("bottom", "绝对时间", units="μs")
        self.result_plot.showGrid(x=True, y=True, alpha=.2)
        self.result_plot.setXLink(self.raw_view.plot_widget)
        self.splitter.addWidget(self.result_plot)
        self.splitter.setSizes([260, 160, 250])
        layout.addWidget(self.splitter, 1)

        actions = QHBoxLayout()
        self.run_button = QPushButton("分析当前通道")
        self.run_button.setObjectName("runSegmentedAnalysis")
        self.run_button.setProperty("primary", True)
        self.export_button = QPushButton("导出结果…")
        self.export_button.setObjectName("exportSegmentedResults")
        self.save_button = QPushButton("保存分段…")
        self.load_button = QPushButton("载入分段…")
        self.copy_button = QPushButton("应用到全部通道")
        self.field_combo = QComboBox()
        self.field_combo.addItem("校正速度", "corrected")
        self.field_combo.addItem("表观速度", "apparent")
        self.field_combo.addItem("拍频", "frequency")
        self.candidate_check = QCheckBox("显示候选点")
        self.candidate_check.setToolTip("灰色点未必通过质量门槛；不能作为已确认速度。")
        for action_widget in (self.run_button, self.export_button, self.field_combo, self.candidate_check):
            actions.addWidget(action_widget)
        actions.addStretch(1)
        layout.addLayout(actions)
        files = QHBoxLayout()
        for button in (self.save_button, self.load_button, self.copy_button):
            files.addWidget(button)
        files.addStretch(1)
        layout.addLayout(files)
        self.status = QLabel("导入数据并确认 ROI 后，可添加分割线。")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.channel_combo.currentTextChanged.connect(self._select_channel)
        self.add_button.clicked.connect(lambda: self.add_boundary())
        self.delete_button.clicked.connect(self.delete_boundary)
        self.boundary_combo.currentIndexChanged.connect(self._boundary_selected)
        self.boundary_spin.valueChanged.connect(self._numeric_boundary_changed)
        self.run_button.clicked.connect(self.run_analysis)
        self.export_button.clicked.connect(self._choose_export)
        self.save_button.clicked.connect(self._save_plan_dialog)
        self.load_button.clicked.connect(self._load_plan_dialog)
        self.copy_button.clicked.connect(self.copy_plan_to_all)
        self.field_combo.currentIndexChanged.connect(self._plot_result)
        self.candidate_check.toggled.connect(self._plot_result)
        self.table.currentCellChanged.connect(self._select_segment)
        self.roi_button.toggled.connect(self._toggle_roi)
        self.raw_view.analysis_region_committed.connect(self.roi_change_requested.emit)
        self.result_plot.scene().sigMouseMoved.connect(self._result_cursor)
        self._refresh_controls()

    @property
    def plan(self) -> tuple[Segment, ...]:
        return self.plans.get(self._channel, ())

    def set_context(self, records: Mapping[str, SignalRecord], roi: AnalysisRange | None,
                    configuration: AnalysisRunConfiguration | None, source: Path | None,
                    frequency_band_hz: tuple[float, float] | None = None) -> None:
        new_data = tuple((key, id(record)) for key, record in records.items()) != tuple(
            (key, id(record)) for key, record in self.records.items())
        changed = (new_data or roi != self._roi or configuration != self._configuration
                   or frequency_band_hz != self._frequency_band_hz)
        if not changed:
            return
        old_plans = self.plans
        self.records, self._roi, self._configuration, self._source = records, roi, configuration, source
        self._frequency_band_hz = frequency_band_hz
        self.revision += 1
        self.results.clear()
        if new_data:
            self.plans = {}
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
                        plan.append(Segment(uuid4().hex[:12], left, right,
                                            previous.stage if previous else "unknown",
                                            previous.algorithm if previous else "stft"))
                    self.plans[name] = tuple(plan)
        with QSignalBlocker(self.channel_combo):
            self.channel_combo.clear()
            self.channel_combo.addItems(list(records))
            if self._channel in records:
                self.channel_combo.setCurrentText(self._channel)
        self._select_channel(self.channel_combo.currentText())
        self.status.setText("分段和参数已就绪；编辑后点击分析。" if roi else "请在原始信号页确认分析 ROI。")
        self._refresh_controls()

    def _select_channel(self, channel: str) -> None:
        self._channel = channel
        self.raw_view.set_records({channel: self.records[channel]} if channel in self.records else {})
        self._toggle_roi(self.roi_button.isChecked())
        self._rebuild()
        self._plot_result()
        if self._roi is not None:
            self.raw_view.plot_widget.setXRange(self._roi.start_time_s * 1e6,
                                                self._roi.end_time_s * 1e6, padding=.02)

    def _toggle_roi(self, enabled: bool) -> None:
        if self._roi is not None:
            self.raw_view.set_analysis_region_s(self._roi.start_time_s, self._roi.end_time_s)
        self.raw_view.analysis_region.setVisible(enabled and self._roi is not None)

    def _invalidate(self, message: str = "分段已修改；请重新分析。") -> None:
        self.revision += 1
        self.results.pop(self._channel, None)
        self.result_plot.clear()
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

    def _rebuild(self) -> None:
        selected_boundary = max(0, self.boundary_combo.currentIndex())
        selected_row = self.table.currentRow()
        table_blocker = QSignalBlocker(self.table)
        self._syncing = True
        for line in self.lines:
            self.raw_view.plot_widget.removeItem(line)
        self.lines.clear()
        self.boundary_combo.clear()
        for index, segment in enumerate(self.plan[:-1]):
            line = pg.InfiniteLine(pos=segment.end_s * 1e6, angle=90, movable=True,
                                   pen=pg.mkPen("#D55E00", width=2),
                                   hoverPen=pg.mkPen("#D55E00", width=4), label=str(index + 1),
                                   labelOpts={"position": .92, "color": "#9d4000", "fill": "#ffffff"})
            line.setZValue(30)
            line.setCursor(Qt.CursorShape.SizeHorCursor)
            self.raw_view.plot_widget.addItem(line)
            line.sigPositionChanged.connect(lambda _line, i=index: self._line_moving(i))
            line.sigPositionChangeFinished.connect(lambda _line, i=index: self._line_finished(i))
            line.sigClicked.connect(lambda _line, _event, i=index: self.boundary_combo.setCurrentIndex(i))
            self.lines.append(line)
            self.boundary_combo.addItem(f"分割线 {index + 1}")
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
        if self.plan and selected_row >= 0:
            self.table.selectRow(min(selected_row, len(self.plan) - 1))
        self.table.resizeRowsToContents()
        del table_blocker
        self._boundary_selected(self.boundary_combo.currentIndex())
        self._refresh_controls()

    def set_segment(self, row: int, *, stage: str | None = None, algorithm: str | None = None) -> None:
        if self._syncing or not 0 <= row < len(self.plan):
            return
        if algorithm is not None and algorithm not in self._algorithms:
            raise ValueError("Unknown algorithm")
        current = self.plan[row]
        updated = replace(current, stage=stage or current.stage, algorithm=algorithm or current.algorithm)
        if current == updated:
            return
        values = list(self.plan)
        values[row] = updated
        self.plans[self._channel] = tuple(values)
        self._invalidate()
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
        values = list(self.plan)
        values[index:index + 1] = [replace(segment, end_s=value),
                                  replace(segment, id=uuid4().hex[:12], start_s=value)]
        self.plans[self._channel] = tuple(values)
        self._invalidate()
        self._rebuild()
        self.boundary_combo.setCurrentIndex(index)
        self.table.selectRow(index + 1)
        return True

    def move_boundary(self, index: int, value_s: float) -> None:
        if not 0 <= index < len(self.plan) - 1:
            return
        values = list(self.plan)
        dt = self.records[self._channel].representative_sample_interval_s
        value = float(np.clip(value_s, values[index].start_s + dt, values[index + 1].end_s - dt))
        if value == values[index].end_s:
            return
        values[index] = replace(values[index], end_s=value)
        values[index + 1] = replace(values[index + 1], start_s=value)
        self.plans[self._channel] = tuple(values)
        self._invalidate()

    def delete_boundary(self) -> None:
        index = self.boundary_combo.currentIndex()
        if not 0 <= index < len(self.plan) - 1:
            return
        values = list(self.plan)
        values[index:index + 2] = [replace(values[index], end_s=values[index + 1].end_s)]
        self.plans[self._channel] = tuple(values)
        self._invalidate("区段已合并，保留左段的阶段与算法；请重新分析。")
        self._rebuild()

    def _line_moving(self, index: int) -> None:
        if self._syncing:
            return
        self.move_boundary(index, float(self.lines[index].value()) * 1e-6)
        self.boundary_combo.setCurrentIndex(index)
        self._boundary_selected(index)

    def _line_finished(self, _index: int) -> None:
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
        for i, line in enumerate(self.lines):
            line.setBounds(((self.plan[i].start_s + dt) * 1e6,
                            (self.plan[i + 1].end_s - dt) * 1e6))

    def _numeric_boundary_changed(self, value_us: float) -> None:
        if not self._syncing:
            self.move_boundary(self.boundary_combo.currentIndex(), value_us * 1e-6)
            self._rebuild()

    def _select_segment(self, row: int, _column: int, _old_row: int, _old_column: int) -> None:
        if not self._syncing and self.lines:
            self.boundary_combo.setCurrentIndex(min(max(row, 0), len(self.lines) - 1))

    def copy_plan_to_all(self) -> None:
        for name in self.records:
            self.plans[name] = tuple(self.plan)
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
            self.status.setText(f"{channel}：{int(value.valid.sum())} / {len(value.time_s)} 点有效；"
                                f"{len(errors)} 段算法异常。边界处断线，缺失保留 NaN。")
        self._rebuild()
        self._plot_result()
        self._refresh_controls()

    def _failed(self, _revision: int, message: str) -> None:
        self.busy = False
        self.busy_changed.emit(False)
        self.status.setText(f"分析失败：{message}")
        self._refresh_controls()

    def _plot_result(self, *_args: object) -> None:
        self.result_plot.clear()
        result = self.results.get(self._channel)
        field = str(self.field_combo.currentData())
        self.result_plot.setLabel("left", "拍频" if field == "frequency" else "速度",
                                  units="GHz" if field == "frequency" else "m/s")
        if result is None:
            return
        values = (result.frequency_hz * 1e-9 if field == "frequency" else
                  result.apparent_velocity_m_s if field == "apparent" else result.corrected_velocity_m_s)
        colors = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")
        for index, segment in enumerate(result.segments):
            mask = np.asarray(result.segment_ids) == segment.id
            self.result_plot.plot(result.time_s[mask] * 1e6, values[mask],
                                  pen=pg.mkPen(colors[index % len(colors)], width=2),
                                  symbol="o", symbolSize=3, connect="finite")
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
        self.result_plot.enableAutoRange(axis=pg.ViewBox.YAxis)

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
        self.status.setText(f"已导出 {len(self.results)} 个通道：{destination}")
        return paths

    def _choose_export(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "选择导出位置（自动新建结果目录）")
        if not parent:
            return
        try:
            self.export_to(Path(parent) / f"PDV_TASK011_{datetime.now():%Y%m%d_%H%M%S_%f}")
        except Exception as exc:
            self.status.setText(f"导出失败：{exc}")

    def save_plan(self, path: Path) -> None:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"schema": "pdv-segment-plan/1", "source_path": str(self._source),
                       "roi_s": asdict(self._roi) if self._roi else None,
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
