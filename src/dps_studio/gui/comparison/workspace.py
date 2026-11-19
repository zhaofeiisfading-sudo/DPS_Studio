"""Research workspace, calculation settings and difference navigation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

import numpy as np
from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from dps_studio.core.diagnostics import DiagnosticPreset, discover_presets
from dps_studio.core.models import SignalRecord
from dps_studio.core.stft_m4 import Estimate, StftM4ComparisonBundle, inspect_frame_waveform
from dps_studio.core.stft_m4.waveform import Float
from dps_studio.gui.diagnostic.worker import _hold_collection, _release_collection

from .inspector import ComparisonInspector, number
from .plots import DIFFERENCES, ComparisonPlots, Layers
from .theme import COLORS, STYLE
from .worker import ComparisonWorker


def _choices(items: Iterable[tuple[str, str]]) -> QComboBox:
    combo = QComboBox()
    for label, key in items:
        combo.addItem(label, key)
    return combo


def _choice_item(combo: QComboBox, index: int) -> QStandardItem:
    item = cast(QStandardItemModel, combo.model()).item(index)
    assert item is not None
    return item


def _tool(text: str, tooltip: str = "") -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tooltip)
    return button


def _card(title: str, layout: QVBoxLayout) -> QVBoxLayout:
    box = QGroupBox(title)
    content = QVBoxLayout(box)
    content.setContentsMargins(8, 6, 8, 8)
    content.setSpacing(4)
    layout.addWidget(box)
    return content


def _spin(minimum: float, maximum: float, default: float, *, decimals: int = 3) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setDecimals(decimals)
    field.setRange(minimum, maximum)
    field.setValue(default)
    field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    field.setMinimumWidth(72)
    return field


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class ComparisonPropertiesPanel(QScrollArea):
    openFileRequested = Signal()
    presetLoadRequested = Signal(object)
    wavelengthChanged = Signal()

    def __init__(self, repository_root: Path | None) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        panel = QWidget()
        panel.setObjectName("comparisonProperties")
        panel.setStyleSheet(STYLE)
        panel.setMinimumWidth(0)
        self.setWidget(panel)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(7, 1, 7, 6)
        outer.setSpacing(5)
        data = _card("数据与通道", outer)
        self.open_button = QPushButton("打开数据文件 (CSV/DAT/TXT)…")
        self.open_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.open_button.clicked.connect(self.openFileRequested)
        data.addWidget(self.open_button)
        self.preset_combo = _choices((("选择本地算例…", ""),))
        self.preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        presets: tuple[DiagnosticPreset, ...] = ()
        if repository_root is not None and (repository_root / "data/raw").is_dir():
            try:
                presets = discover_presets(repository_root)
            except (OSError, ValueError):
                self.preset_combo.setToolTip("本地算例无法读取。可通过打开数据文件导入。")
        for preset in presets:
            self.preset_combo.addItem(preset.channel_id, preset)
        self.preset_combo.setEnabled(bool(presets))
        self.preset_combo.activated.connect(self._load_preset)
        data.addWidget(self.preset_combo if presets else _label("本地算例不可用，可打开外部数据文件。"))
        self.channel_combo = QComboBox()
        self.channel_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.record_label = _label("等待载入")
        data.addWidget(self.channel_combo)
        data.addWidget(self.record_label)

        calculation = _card("计算控制", outer)
        band = QGridLayout()
        self.fmin_spin = _spin(.1, 1e6, 50., decimals=1)
        self.fmax_spin = _spin(.1, 1e6, 6000., decimals=1)
        band.addWidget(QLabel("f min (MHz)"), 0, 0)
        band.addWidget(QLabel("f max (MHz)"), 0, 1)
        band.addWidget(self.fmin_spin, 1, 0)
        band.addWidget(self.fmax_spin, 1, 1)
        calculation.addLayout(band)
        self.matched_checkbox = QCheckBox("同时计算 25.6 ns 等时长 STFT")
        calculation.addWidget(self.matched_checkbox)
        self.compute_button = QPushButton("一键计算 B1 vs M4 对比")
        self.compute_button.setObjectName("computeComparison")
        self.compute_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.compute_button.setMinimumWidth(164)
        self.cancel_button = QToolButton()
        self.cancel_button.setText("取消计算")
        buttons = QHBoxLayout()
        buttons.addWidget(self.compute_button, 1)
        buttons.addWidget(self.cancel_button)
        calculation.addLayout(buttons)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setValue(0)
        calculation.addWidget(self.progress_bar)
        self.stage_label = _label("等待数据")
        calculation.addWidget(self.stage_label)

        units = _card("单位与真空波长", outer)
        self.confirm_wavelength = QCheckBox("已确认可靠真空波长")
        self.confirm_wavelength.setToolTip("启用法向反射的无符号表观速度 v = λ₀f/2。")
        self.wavelength_nm = _spin(0., 1e9, 0.)
        self.wavelength_nm.setSpecialValueText("请输入真空波长")
        self.wavelength_nm.setSuffix(" nm")
        self.wavelength_nm.setEnabled(False)
        self.confirm_wavelength.toggled.connect(self.wavelength_nm.setEnabled)
        self.confirm_wavelength.toggled.connect(self.wavelengthChanged)
        self.wavelength_nm.valueChanged.connect(self.wavelengthChanged)
        units.addWidget(self.confirm_wavelength)
        units.addWidget(self.wavelength_nm)
        self.physics_label = _label("表观速度 · 法向反射 v = λ₀f/2\n未做窗口/角度修正")
        self.physics_label.setStyleSheet("background:#eef5fa;color:#245576;padding:3px;")
        units.addWidget(self.physics_label)

        summary = _card("全通道统计", outer)
        self.method_table = QTableWidget(7, 4)
        self.method_table.setHorizontalHeaderLabels(("指标", "B1", "M4", "25.6 ns"))
        self.method_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.method_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.method_table.verticalHeader().hide()
        self.method_table.verticalHeader().setMinimumSectionSize(15)
        self.method_table.verticalHeader().setDefaultSectionSize(17)
        header = self.method_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.method_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.method_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.method_table.setFixedHeight(146)
        self.method_table.setStyleSheet("QTableWidget {font-size:11px;} QHeaderView::section {padding:2px;}")
        summary.addWidget(self.method_table)
        differences = QGridLayout()
        self.difference_labels = []
        for i, (_, label, key, _) in enumerate(DIFFERENCES):
            item = _label(label)
            item.setStyleSheet(f"font-size:11px;color:{COLORS[key]};")
            self.difference_labels.append(item)
            differences.addWidget(item, i//2, i%2)
        summary.addLayout(differences)
        outer.addStretch()
        self.set_summary(None)
        self.set_controls(ready=False, busy=False)

    @Slot(int)
    def _load_preset(self, index: int) -> None:
        preset = self.preset_combo.itemData(index)
        if isinstance(preset, DiagnosticPreset):
            self.presetLoadRequested.emit(preset)
        self.preset_combo.setCurrentIndex(0)

    def set_controls(self, *, ready: bool, busy: bool, external_busy: bool = False) -> None:
        locked = busy or external_busy
        self.compute_button.setEnabled(ready and not locked)
        self.cancel_button.setEnabled(busy)
        self.open_button.setEnabled(not locked)
        self.preset_combo.setEnabled(self.preset_combo.count() > 1 and not locked)
        self.channel_combo.setEnabled(ready and not locked)
        for widget in (self.fmin_spin, self.fmax_spin, self.matched_checkbox):
            widget.setEnabled(not locked)

    @property
    def confirmed_wavelength_m(self) -> float | None:
        value = self.wavelength_nm.value()
        return value*1e-9 if self.confirm_wavelength.isChecked() and value > 0. else None

    @Slot(int, str)
    def set_progress(self, percent: int, text: str) -> None:
        self.progress_bar.setValue(percent)
        self.stage_label.setText(text)

    def set_summary(self, bundle: StftM4ComparisonBundle | None) -> None:
        titles = ("发布", "拒收 / 未发", "跳变 >250", "6.4 ns R²", "25.6 ns R²",
                  "分半相干", "耗时 (s)")

        def metrics(result: Estimate | None, elapsed: float | None) -> tuple[str, ...]:
            if result is None or elapsed is None:
                return ("—",) * len(titles)

            def median(values: Float) -> str:
                finite = values[np.isfinite(values) & np.isfinite(result.accepted_hz)]
                return number(float(np.median(finite)), 2) if finite.size else "—"

            published = int(np.isfinite(result.accepted_hz).sum())
            rejected = int(result.rejected_mask.sum())
            jumps = int((abs(np.diff(result.accepted_hz)) > 250e6).sum())
            return (str(published), f"{rejected}/{len(result.sample_index)-published}", str(jumps),
                    median(result.raw.raw_chirp_r2_64ns), median(result.raw.raw_chirp_r2_256ns),
                    median(result.raw.split_half_coherence_256ns), number(elapsed, 2))

        columns = (metrics(None, None),)*3 if bundle is None else (
            metrics(bundle.b1, bundle.b1_wall_s), metrics(bundle.m4, bundle.m4_wall_s),
            metrics(bundle.matched_stft, bundle.matched_stft_wall_s),
        )
        for row, values in enumerate(zip(titles, *columns, strict=True)):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if row == 2:
                    item.setToolTip("相邻发布帧频差 >250 MHz")
                if row in (3, 4, 5):
                    item.setToolTip("发布帧上有限证据的中位数")
                self.method_table.setItem(row, column, item)
        counts = bundle.diff_categories if bundle is not None else ()
        for label_widget, (category, label, _, _) in zip(self.difference_labels, DIFFERENCES, strict=True):
            label_widget.setText(f"{label}  {counts.count(category)}" if bundle else f"{label}  —")


class ComparisonWorkspace(QWidget):
    openFileRequested = Signal()
    presetLoadRequested = Signal(object)
    busyChanged = Signal(bool)
    stateChanged = Signal(str)
    finished = Signal(object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, repository_root: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("comparisonWorkspace")
        self.setStyleSheet(STYLE)
        self.properties = ComparisonPropertiesPanel(repository_root)
        self.properties.openFileRequested.connect(self.openFileRequested)
        self.properties.presetLoadRequested.connect(self.presetLoadRequested)
        self.properties.compute_button.clicked.connect(self.start)
        self.properties.cancel_button.clicked.connect(self.cancel)
        self.properties.wavelengthChanged.connect(self._units_changed)
        self.channel_combo = self.properties.channel_combo
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self.records: dict[str, SignalRecord] = {}
        self.source_path: Path | None = None
        self.bundle: StftM4ComparisonBundle | None = None
        self.selected_frame: int | None = None
        self._worker: ComparisonWorker | None = None
        self._external_busy = False
        self._disposed = False
        self._nav: dict[str, tuple[int, ...]] = {}
        self._state = "等待数据"
        self.plots = ComparisonPlots()
        self.inspector = ComparisonInspector()
        self.plots.add_inspector(self.inspector)
        self.plots.timeSelected.connect(self.select_time)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 4, 5, 4)
        outer.setSpacing(4)
        outer.addLayout(self._display_toolbar())
        outer.addLayout(self._navigation_toolbar())
        outer.addWidget(self.plots, 1)
        self._units_changed()
        self._update_navigation()

    def _display_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        self.layout_combo = _choices((("左右并排", "side"), ("上下并排", "stack"), ("单图叠加", "single")))
        self.view_group = QButtonGroup(self)
        self.view_buttons = {}
        row.addWidget(self.layout_combo)
        for key, label in (("b1", "仅 B1"), ("m4", "仅 M4"), ("overlay", "叠加对比"),
                           ("difference", "差异高亮")):
            button = _tool(label)
            button.setCheckable(True)
            self.view_group.addButton(button)
            self.view_buttons[key] = button
            button.clicked.connect(self._redraw)
            row.addWidget(button)
        self.view_buttons["overlay"].setChecked(True)
        self.unit_combo = _choices((("频率 (GHz)", "frequency"), ("速度 (m/s)", "velocity")))
        self.contrast_combo = _choices((("自适应", "adaptive"), ("弱信号增强", "weak"), ("全动态", "full")))
        self.contrast_combo.setToolTip("自适应 P55–P99.7 · 弱信号增强 P65–P98.5 · 全动态最小—最大")
        self.background_combo = _choices((("统一 B1 底图", "shared"), ("左 B1 / 右 M4 响应", "coherent")))
        self.background_combo.setToolTip("统一 B1 STFT 锁定两图色标。M4 白化响应使用独立量纲。")
        for combo in (self.unit_combo, self.contrast_combo, self.background_combo):
            row.addWidget(combo)
        self.unit_combo.currentIndexChanged.connect(self._units_changed)
        for combo in (self.layout_combo, self.contrast_combo, self.background_combo):
            combo.currentIndexChanged.connect(self._redraw)
        row.addStretch()
        return row

    def _navigation_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        self.layer_boxes = [QCheckBox(name) for name in (
            "最终选中", "被拒点 (×)", "原始候选", "次支路", "25.6 ns STFT",
        )]
        for i, box in enumerate(self.layer_boxes):
            box.setChecked(i < 2)
            box.toggled.connect(self._redraw)
            row.addWidget(box)
        self.layer_boxes[-1].setEnabled(False)
        self.layer_boxes[-1].setToolTip("在计算控制中选择同时计算等时长 STFT。")
        self.region_combo = _choices((("关注区域", ""),))
        self.region_combo.setMinimumContentsLength(8)
        self.region_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.region_combo.setMaximumWidth(126)
        self.region_combo.currentIndexChanged.connect(self._region_changed)
        row.addSpacing(4)
        row.addWidget(self.region_combo)
        self.prev_button, self.next_button = _tool("‹", "上一帧"), _tool("›", "下一帧")
        self.frame_counter = QLabel("0 / 0")
        self.prev_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button.clicked.connect(lambda: self._navigate(1))
        row.addWidget(self.prev_button)
        row.addWidget(self.frame_counter)
        row.addWidget(self.next_button)
        for width, name in ((120., "放大 ±120 ns"), (30., "精细 ±30 ns")):
            button = _tool(name)
            button.clicked.connect(lambda _checked=False, half=width: self.zoom_selected(half))
            row.addWidget(button)
        reset = _tool("全局复位")
        reset.clicked.connect(self.plots.reset_range)
        row.addWidget(reset)
        row.addStretch()
        return row

    @property
    def busy(self) -> bool:
        return self._worker is not None

    @property
    def state_text(self) -> str:
        return self._state

    def set_external_busy(self, busy: bool) -> None:
        self._external_busy = busy
        self._refresh_controls()

    def set_context(self, records: Mapping[str, SignalRecord], source_path: Path | None = None) -> None:
        if self.busy or (self.source_path == source_path and records == self.records):
            return
        self.records, self.source_path = dict(records), source_path
        with QSignalBlocker(self.channel_combo):
            self.channel_combo.clear()
            for name in self.records:
                self.channel_combo.addItem(name, name)
        self._channel_changed()

    def _set_state(self, text: str, *, percent: int | None = None) -> None:
        self._state = text
        self.properties.set_progress(
            self.properties.progress_bar.value() if percent is None else percent, text,
        )
        self.stateChanged.emit(text)

    @Slot()
    def _channel_changed(self) -> None:
        self._set_bundle(None)
        record = self.records.get(str(self.channel_combo.currentData()))
        if record is None:
            self.properties.record_label.setText("等待载入")
            self._set_state("等待数据", percent=0)
        else:
            self.properties.record_label.setText(
                f"{record.sample_rate_hz/1e9:.4g} GS/s · {record.sample_count:,} 点"
                f" · {record.duration_s*1e6:.4g} µs"
            )
            self._set_state("数据已载入 · 可计算", percent=0)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        self.properties.set_controls(ready=bool(self.records), busy=self.busy,
                                     external_busy=self._external_busy)

    @Slot()
    def start(self) -> bool:
        channel = str(self.channel_combo.currentData())
        record = self.records.get(channel)
        if record is None or self.busy or self._external_busy or self._disposed:
            return False
        panel = self.properties
        worker = ComparisonWorker(record, channel, self.source_path, panel.fmin_spin.value()*1e6,
                                  panel.fmax_spin.value()*1e6, panel.matched_checkbox.isChecked())
        worker.progress.connect(self._progress)
        worker.finished.connect(self._retire)
        _hold_collection()
        self._worker = worker
        self._set_state("准备对比计算", percent=0)
        self._refresh_controls()
        self.busyChanged.emit(True)
        worker.start()
        return True

    @Slot(int, str)
    def _progress(self, percent: int, stage: str) -> None:
        if self._worker is not None and not self._worker.cancel_event.is_set():
            self._set_state(stage, percent=percent)

    @Slot()
    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel_event.set()
            self._set_state("正在取消")
            self.properties.cancel_button.setEnabled(False)

    @Slot()
    def _retire(self) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.wait()
        result = worker.result
        error = worker.error
        cancelled = worker.cancel_event.is_set()
        if cancelled:
            self._set_state("计算已取消", percent=0)
        elif error is not None:
            self._set_state(f"计算失败 · {error}", percent=0)
        elif result is not None:
            self._set_bundle(result)
            band = f"{result.fmin_hz/1e6:g}–{result.fmax_hz/1e6:g} MHz"
            self._set_state(f"对比就绪 · {band}", percent=100)
        self._worker = None
        worker.deleteLater()
        _release_collection()
        self._refresh_controls()
        self.busyChanged.emit(False)
        if cancelled:
            self.cancelled.emit()
        elif error is not None:
            self.failed.emit(error)
        elif result is not None:
            self.finished.emit(result)

    def dispose(self) -> None:
        self._disposed = True
        worker = self._worker
        if worker is not None:
            worker.cancel_event.set()
            worker.wait()
            worker.deleteLater()
            self._worker = None
            _release_collection()

    def _set_bundle(self, bundle: StftM4ComparisonBundle | None) -> None:
        self.bundle = bundle
        self.selected_frame = None
        self.inspector.show_frame(None)
        self.plots.set_bundle(bundle)
        self.properties.set_summary(bundle)
        self.layer_boxes[-1].setEnabled(bundle is not None and bundle.matched_stft is not None)
        _choice_item(self.background_combo, 1).setEnabled(bundle is not None and bundle.m4_coherent_map is not None)
        if bundle is None or bundle.m4_coherent_map is None:
            self.background_combo.setCurrentIndex(0)
        self._nav.clear()
        with QSignalBlocker(self.region_combo):
            self.region_combo.clear()
            self.region_combo.addItem("关注区域", "")
            for region in bundle.interesting_regions if bundle else ():
                if region.kind not in self._nav:
                    kind = region.kind
                    label = {
                        "m4_added_supported": "M4 新增支持",
                        "branch_diff_major": "大频差分歧",
                        "m4_dropped_strong_risk": "疑似误伤",
                        "precursor_or_ambiguous": "前驱或争议",
                        "onset_or_step": "起跳／阶跃",
                        "rapid_chirp": "急变调频",
                    }.get(kind, region.title_zh)
                    self.region_combo.addItem(label, kind)
                    _choice_item(self.region_combo, self.region_combo.count()-1).setToolTip(
                        region.title_zh
                    )
                self._nav[region.kind] = (*self._nav.get(region.kind, ()), *region.frame_indices)
        if bundle is not None and len(bundle.q):
            first_group = self.region_combo.findData("all_diff")
            if first_group >= 0:
                with QSignalBlocker(self.region_combo):
                    self.region_combo.setCurrentIndex(first_group)
            self.select_frame(self._frames()[0] if self._frames() else 0)
        else:
            self._update_navigation()

    @Slot()
    def _redraw(self) -> None:
        display = next(key for key, button in self.view_buttons.items() if button.isChecked())
        self.plots.set_options(
            str(self.layout_combo.currentData()), display, str(self.contrast_combo.currentData()),
            str(self.background_combo.currentData()), Layers(*(box.isChecked() for box in self.layer_boxes)),
        )

    @Slot()
    def _units_changed(self) -> None:
        wavelength = self.properties.confirmed_wavelength_m
        velocity = _choice_item(self.unit_combo, 1)
        velocity.setEnabled(wavelength is not None)
        tip = "请在右侧确认并输入正的真空波长。" if wavelength is None else "表观速度 · 未做窗口/角度修正"
        velocity.setToolTip(tip)
        self.unit_combo.setToolTip(tip)
        if wavelength is None:
            with QSignalBlocker(self.unit_combo):
                self.unit_combo.setCurrentIndex(0)
        applied = wavelength if self.unit_combo.currentData() == "velocity" else None
        self.plots.set_wavelength(applied)
        self.inspector.set_wavelength(applied)

    @Slot(float)
    def select_time(self, time_s: float) -> None:
        if self.bundle is not None and len(self.bundle.q):
            index = int(np.argmin(abs(self.bundle.frame_time_s-time_s)))
            self.select_frame(index)

    def select_frame(self, index: int) -> None:
        if self.bundle is None or not 0 <= index < len(self.bundle.q):
            return
        self.selected_frame = index
        waveform = inspect_frame_waveform(self.bundle, index)
        self.plots.set_cursor(waveform.center_time_s)
        self.inspector.show_frame(waveform)
        self._update_navigation()

    def zoom_selected(self, half_ns: float) -> None:
        if self.bundle is not None and self.selected_frame is not None:
            self.plots.zoom(float(self.bundle.frame_time_s[self.selected_frame]), half_ns)

    def _frames(self) -> tuple[int, ...]:
        return self._nav.get(str(self.region_combo.currentData()), ())

    @Slot()
    def _region_changed(self) -> None:
        frames = self._frames()
        if frames:
            self.select_frame(frames[0])
            self.zoom_selected(120)
        else:
            self._update_navigation()

    def _update_navigation(self) -> None:
        frames = self._frames()
        frame = self.selected_frame
        position = frames.index(frame)+1 if frame is not None and frame in frames else 0
        self.frame_counter.setText(f"{position} / {len(frames)}")
        self.prev_button.setEnabled(bool(frames))
        self.next_button.setEnabled(bool(frames))

    def _navigate(self, step: int) -> None:
        frames = self._frames()
        if frames:
            frame = self.selected_frame
            start = frames.index(frame) if frame is not None and frame in frames else (-1 if step > 0 else 0)
            self.select_frame(frames[(start+step) % len(frames)])
            self.zoom_selected(120.)
