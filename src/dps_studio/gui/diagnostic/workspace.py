"""Diagnostic workspace and compact independent properties sidebar."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.diagnostics import (
    CandidateEntry,
    DiagnosticBundle,
    DiagnosticComputeMode,
    DiagnosticPreset,
    discover_presets,
    load_stage_segments,
)
from dps_studio.core.models import SignalRecord

from .inspector import FrameInspectorPanel
from .plots import (
    EvidenceTimelinePlot,
    RawVoltageStripPlot,
    SpectrogramDiagnosticPlot,
    legend_widget,
)
from .theme import METHOD_COLORS, STYLE, number
from .worker import DiagnosticRunner

FILTERS = (
    ("全部帧", "all"),
    ("起跳 (onset)", "onset"),
    ("快速下降 (decline)", "decline"),
    ("弱信号 (weak_signal)", "weak_signal"),
    ("算法分歧 >100MHz", "disagreement"),
    ("原生G通过但S拒绝", "g_without_s"),
    ("S2/Chirp 救回", "s2_rescued"),
    ("多支路竞争 (S簇>1)", "competing"),
    ("高共识缺S", "high_without_s"),
)


class ChannelSummaryCard(QGroupBox):
    def __init__(self) -> None:
        super().__init__("全通道方法对比总览")
        layout = QVBoxLayout(self)
        self.channel_label = QLabel("尚无诊断结果")
        self.channel_label.setWordWrap(True)
        layout.addWidget(self.channel_label)
        self.table = QTableWidget(6, 4)
        self.table.setHorizontalHeaderLabels(["方法", "C", "G", "S"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setFixedHeight(161)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.anomalies = QLabel()
        self.anomalies.setWordWrap(True)
        self.anomalies.setStyleSheet("font-size:11px;")
        layout.addWidget(self.anomalies)
        self.provenance = QLabel()
        self.provenance.setWordWrap(True)
        self.provenance.setStyleSheet("font-size:11px;color:#607587;")
        layout.addWidget(self.provenance)
        self.set_bundle(None)

    def set_bundle(self, bundle: DiagnosticBundle | None) -> None:
        for i, name in enumerate(METHOD_COLORS):
            curve = bundle.curves.get(name) if bundle else None
            values = [name] + (
                [
                    str(int(getattr(curve, field).sum()))
                    for field in ("c_present", "g_accepted", "s_supported")
                ]
                if curve
                else ["—"] * 3
            )
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.channel_label.setText(
            bundle.channel_name if bundle else "尚无诊断结果；逐通道计算，未算保持缺失"
        )
        if bundle:
            tags = bundle.frame_tags
            suspicious = sum(
                c.g_accepted and not c.s_supported
                for frame in bundle.candidates_by_frame
                for c in frame
            )
            high_clusters = sum(
                c.high_without_s for frame in bundle.clusters_by_frame for c in frame
            )
            s2, b1 = bundle.curves.get("S2"), bundle.curves.get("B1")
            added = str(int((s2.s_supported & ~b1.s_supported).sum())) if s2 and b1 else "—"
            self.anomalies.setText(
                f"分歧>100MHz 帧 {int(tags.disagreement_mask.sum())} · G无S点 {suspicious}\n"
                f"S2/Chirp 救回帧 {int(tags.s2_rescued_mask.sum())} · S2新增 {added}\n"
                f"多支路帧 {int(tags.competing_clusters_mask.sum())} · 高S1共识缺S簇 {high_clusters}"
            )
        else:
            self.anomalies.setText("C 候选 / G 原生通过 / S 原波形证据通过")
        self.provenance.setText(
            f"{bundle.compute_mode} · {number(float(bundle.summary_metrics.get('wall_s', 0)))} s\n"
            + (
                "TASK-018 stack_v1 冻结结果"
                if bundle.compute_mode == "precomputed_stack"
                else "本次原波形实时计算"
            )
            if bundle
            else "冻结结果与实时重算分别标明来源。"
        )
        self.provenance.setToolTip(bundle.provenance_note if bundle else "")


class DiagnosticPropertiesPanel(QScrollArea):
    presetLoadRequested = Signal(object)

    def __init__(self, repository_root: Path) -> None:
        super().__init__()
        self.setObjectName("diagnosticProperties")
        self.setWidgetResizable(True)
        self.setMinimumWidth(270)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet(STYLE)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 4, 6, 4)
        source_group = QGroupBox("真实算例预设与数据来源")
        source = QVBoxLayout(source_group)
        source.setSpacing(3)
        self.presets = discover_presets(repository_root)
        self.preset_combo = QComboBox()
        self.preset_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.preset_combo.setMinimumContentsLength(15)
        for preset in self.presets:
            self.preset_combo.addItem(f"{preset.channel_id} — {preset.highlight_zh}", preset)
            self.preset_combo.setItemData(
                self.preset_combo.count() - 1, preset.highlight_zh, Qt.ItemDataRole.ToolTipRole
            )
        if not self.presets:
            self.preset_combo.addItem("未发现本地真实算例，可导入 CSV / DAT")
            self.preset_combo.setEnabled(False)
        self.load_preset_button = QPushButton("载入所选真实算例")
        self.load_preset_button.setEnabled(bool(self.presets))
        self.load_preset_button.clicked.connect(self.request_preset)
        self.source_label = QLabel("尚未导入：选择真实算例或使用文件菜单导入 CSV / DAT。")
        self.source_label.setWordWrap(True)
        self.channel_combo = QComboBox()
        self.background_label = QLabel("背景前缀：待载入")
        self.background_label.setWordWrap(True)
        for widget in (
            self.preset_combo,
            self.load_preset_button,
            self.source_label,
            self.channel_combo,
            self.background_label,
        ):
            source.addWidget(widget)
        layout.addWidget(source_group)
        engine_group = QGroupBox("诊断计算引擎")
        engine = QVBoxLayout(engine_group)
        engine.setSpacing(3)
        self.prefer_frozen_checkbox = QCheckBox("优先加载冻结共识栈（若可用）")
        self.prefer_frozen_checkbox.setChecked(True)
        self.frozen_label = QLabel("预设载入时可自动附加 TASK-018 冻结结果。")
        self.frozen_label.setWordWrap(True)
        self.frozen_button = QPushButton("加载当前通道冻结共识栈")
        self.fast_button = QPushButton("快速实时诊断\n5 条方法曲线")
        self.fast_button.setToolTip(
            "强制实时重算 B0 / B1 / B+S / Dechirp / VarPro；不使用冻结结果。"
        )
        self.full_button = QPushButton("完整实时 S2\n8 估计器共识栈")
        self.cancel_button = QPushButton("取消计算")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.stage_label = QLabel("等待诊断")
        self.stage_label.setWordWrap(True)
        for engine_widget in (self.prefer_frozen_checkbox, self.frozen_label, self.frozen_button):
            engine.addWidget(engine_widget)
        actions = QHBoxLayout()
        actions.addWidget(self.fast_button)
        actions.addWidget(self.full_button)
        engine.addLayout(actions)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.cancel_button)
        progress_row.addWidget(self.progress_bar, 1)
        engine.addLayout(progress_row)
        engine.addWidget(self.stage_label)
        layout.addWidget(engine_group)
        self.summary = ChannelSummaryCard()
        layout.addWidget(self.summary)
        self.session_summary = QLabel()
        self.session_summary.setWordWrap(True)
        layout.addWidget(self.session_summary)
        layout.addStretch()
        self.setWidget(body)

    def request_preset(self) -> None:
        preset = self.preset_combo.currentData()
        if isinstance(preset, DiagnosticPreset):
            self.presetLoadRequested.emit(preset)


class DiagnosticWorkspace(QWidget):
    presetLoadRequested = Signal(object)
    busyChanged = Signal(bool)
    channelChanged = Signal()
    bundleChanged = Signal(object)

    def __init__(self, repository_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diagnosticWorkspace")
        self.setStyleSheet(STYLE)
        self.repository_root = repository_root
        self.records: dict[str, SignalRecord] = {}
        self.source_path: Path | None = None
        self.bundles: dict[str, DiagnosticBundle] = {}
        self.bundle: DiagnosticBundle | None = None
        self.frame_index = 0
        self._context_key: object = None
        self._disposed = False
        self.external_busy = False
        self.properties = DiagnosticPropertiesPanel(repository_root)
        self.channel_combo = self.properties.channel_combo
        self.runner = DiagnosticRunner(self)
        self.runner.busyChanged.connect(self._busy_changed)
        self.runner.progress.connect(self._progress)
        self.runner.finished.connect(self._computed)
        self.runner.cancelled.connect(self._cancelled)
        self.runner.failed.connect(self._failed)
        self.properties.presetLoadRequested.connect(self.presetLoadRequested)
        self.properties.fast_button.clicked.connect(
            lambda: self.start_compute(DiagnosticComputeMode.FAST_CORE)
        )
        self.properties.full_button.clicked.connect(
            lambda: self.start_compute(DiagnosticComputeMode.FULL_S2)
        )
        self.properties.frozen_button.clicked.connect(self.load_frozen)
        self.properties.cancel_button.clicked.connect(self.cancel_compute)
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(4)
        self._build_controls(layout)
        self.onboarding = QLabel("载入真实算例，或从文件菜单导入 CSV / DAT；选择通道后运行诊断。")
        self.onboarding.setProperty("badge", "info")
        banner = QHBoxLayout()
        banner.addWidget(self.onboarding, 1)
        self.showcase_button = QPushButton("一键载入真实算例")
        self.showcase_button.setEnabled(bool(self.properties.presets))
        self.showcase_button.clicked.connect(self.properties.request_preset)
        banner.addWidget(self.showcase_button)
        layout.addLayout(banner)
        self.canvas_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas_splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_layout.addWidget(legend_widget())
        self.time_splitter = QSplitter(Qt.Orientation.Vertical)
        self.raw_plot = RawVoltageStripPlot()
        self.spectrogram = SpectrogramDiagnosticPlot()
        self.timeline = EvidenceTimelinePlot()
        for plot in (self.raw_plot, self.spectrogram, self.timeline):
            self.time_splitter.addWidget(plot)
            plot.timeClicked.connect(self._plot_clicked)
        # Native ViewBox links have their own re-entrancy guard. No reciprocal callbacks.
        self.raw_plot.plot_widget.setXLink(self.spectrogram.plot_widget)
        self.timeline.plot_widget.setXLink(self.spectrogram.plot_widget)
        self.time_splitter.setSizes([130, 420, 175])
        left_layout.addWidget(self.time_splitter, 1)
        self.inspector = FrameInspectorPanel()
        self.inspector.focusChanged.connect(self._focus_changed)
        self.canvas_splitter.addWidget(left)
        self.canvas_splitter.addWidget(self.inspector)
        self.canvas_splitter.setSizes([720, 560])
        self.canvas_splitter.setStretchFactor(0, 6)
        self.canvas_splitter.setStretchFactor(1, 4)
        layout.addWidget(self.canvas_splitter, 1)
        self._refresh_controls()

    @property
    def busy(self) -> bool:
        return self.runner.busy

    @property
    def active_channel(self) -> str:
        return str(self.channel_combo.currentData() or "")

    def _build_controls(self, layout: QVBoxLayout) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(94)
        body = QWidget()
        controls = QVBoxLayout(body)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        first, second = QHBoxLayout(), QHBoxLayout()
        first.setSpacing(5)
        controls.addLayout(first)
        controls.addLayout(second)
        self.backdrop_combo = QComboBox()
        self.backdrop_combo.addItem("去均值 512 STFT (默认)", "demeaned")
        self.backdrop_combo.addItem("传统原始 1024 STFT (可见DC泄漏)", "raw")
        self.contrast_combo = QComboBox()
        for text, key in (
            ("自适应高动态 (P55–P99.7)", "adaptive"),
            ("弱信号增强 (P65–P98.5)", "weak"),
            ("全动态 (Min–Max)", "full"),
        ):
            self.contrast_combo.addItem(text, key)
        first.addWidget(self.backdrop_combo)
        first.addWidget(self.contrast_combo)
        self.method_buttons: dict[str, QToolButton] = {}
        for name, color in METHOD_COLORS.items():
            button = QToolButton()
            button.setText("● " + name)
            button.setToolTip(
                {
                    "B0": "传统 STFT",
                    "B1": "去均值短窗 STFT",
                    "B+S": "B1 + 原波形证据",
                    "S2": "共识栈",
                }.get(name, name)
            )
            button.setCheckable(True)
            button.setChecked(True)
            button.setStyleSheet(f"color:{color};font-weight:600;")
            button.toggled.connect(self._display_changed)
            self.method_buttons[name] = button
            first.addWidget(button)
        self.rejected_checkbox = QCheckBox("显示被拒/未选候选")
        self.rejected_checkbox.setToolTip("显示被拒/未选候选 (C=1)")
        self.rejected_checkbox.setChecked(True)
        self.cloud_checkbox = QCheckBox("全估计器点云")
        self.band_combo = QComboBox()
        self.band_combo.addItem("0–10 GHz 视野", False)
        self.band_combo.addItem("主带 0–6.2 GHz", True)
        for widget in (self.rejected_checkbox, self.cloud_checkbox, self.band_combo):
            first.addWidget(widget)
        self.filter_combo = QComboBox()
        for text, key in FILTERS:
            self.filter_combo.addItem(text, key)
        second.addWidget(self.filter_combo)
        self.previous_key_button = QPushButton("< 上一关键帧")
        self.next_key_button = QPushButton("下一关键帧 >")
        self.key_counter = QLabel("0 / 0")
        self.previous_frame_button = QPushButton("< -1帧")
        self.next_frame_button = QPushButton("+1帧 >")
        self.zoom_button = QPushButton("局部放大 ±120 ns")
        self.reset_button = QPushButton("全局复位")
        for navigation_widget in (
            self.previous_key_button,
            self.key_counter,
            self.next_key_button,
            self.previous_frame_button,
            self.next_frame_button,
            self.zoom_button,
            self.reset_button,
        ):
            second.addWidget(navigation_widget)
        self.metric_combo = QComboBox()
        self.metric_combo.addItem("Tone R² vs Chirp R²", "r2")
        self.metric_combo.addItem("对比度 dB vs 背景增益 dB", "spectral")
        second.addWidget(self.metric_combo)
        second.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.backdrop_combo.currentIndexChanged.connect(self._display_changed)
        self.contrast_combo.currentIndexChanged.connect(self._display_changed)
        self.rejected_checkbox.toggled.connect(self._display_changed)
        self.cloud_checkbox.toggled.connect(self._display_changed)
        self.band_combo.currentIndexChanged.connect(self._display_changed)
        self.metric_combo.currentIndexChanged.connect(self._timeline_changed)
        self.filter_combo.currentIndexChanged.connect(self._filter_changed)
        self.previous_key_button.clicked.connect(lambda: self.jump_key(-1))
        self.next_key_button.clicked.connect(lambda: self.jump_key(1))
        self.previous_frame_button.clicked.connect(lambda: self.select_frame(self.frame_index - 1))
        self.next_frame_button.clicked.connect(lambda: self.select_frame(self.frame_index + 1))
        self.zoom_button.clicked.connect(self.zoom_local)
        self.reset_button.clicked.connect(self.reset_view)

    def set_context(self, records: Mapping[str, SignalRecord], source_path: Path | None) -> None:
        key = (source_path, tuple((name, id(record)) for name, record in records.items()))
        if key == self._context_key:
            return
        self._context_key = key
        self.records, self.source_path = dict(records), source_path
        self.bundles.clear()
        previous = self.active_channel
        with QSignalBlocker(self.channel_combo):
            self.channel_combo.clear()
            for name in records:
                self.channel_combo.addItem(name, name)
            index = self.channel_combo.findData(previous)
            self.channel_combo.setCurrentIndex(max(0, index))
        self._channel_changed()

    def _matching_preset(self) -> DiagnosticPreset | None:
        if self.source_path is None:
            return None
        return next(
            (
                p
                for p in self.properties.presets
                if p.channel_id == self.active_channel
                and (self.repository_root / p.relative_path).resolve() == self.source_path.resolve()
            ),
            None,
        )

    def frozen_available(self) -> bool:
        preset = self._matching_preset()
        base = self.repository_root / "artifacts/TASK-018/data/stack_v1"
        return preset is not None and all(
            (base / f"{preset.channel_id}__{kind}.csv.gz").is_file()
            for kind in ("candidates", "curves", "peaks")
        )

    def _channel_changed(self, _index: int = 0) -> None:
        self._clear_canvas()
        record = self.records.get(self.active_channel)
        p = self.properties
        available = self.frozen_available()
        p.prefer_frozen_checkbox.setChecked(available if record else bool(p.presets))
        p.frozen_label.setText(
            "TASK-018 stack_v1 可用；冻结 S / 共识标签，非本次实时计算。"
            if available
            else "当前通道无匹配冻结栈；可实时计算。"
        )
        p.source_label.setText(
            f"{self.source_path.name if self.source_path else '当前导入'}\n"
            f"{record.sample_count:,} 点 · {record.sample_rate_hz / 1e9:.4g} GSa/s"
            if record
            else "尚未载入数据。可选择真实算例或导入 CSV / DAT。"
        )
        p.source_label.setToolTip(str(self.source_path or ""))
        stages = (
            load_stage_segments(self.active_channel, self.repository_root)
            if self._matching_preset()
            else ()
        )
        p.background_label.setText(
            "TASK-017 视觉起跳前缀"
            if any(s.stage == "onset" for s in stages)
            else "TASK-018 固定前缀控制 min(N//20,2048)\n静默性未经视觉确认"
        )
        cached = self.bundles.get(self.active_channel)
        if cached:
            self.set_bundle(cached)
        self._refresh_controls()
        self.channelChanged.emit()

    def _clear_canvas(self) -> None:
        self.bundle = None
        self.inspector.clear()
        for plot in (self.raw_plot, self.spectrogram, self.timeline):
            plot.plot_widget.clear()
            plot.cursor = None
        self.spectrogram.bundle = None
        self.spectrogram.method_items = {}
        self.spectrogram.cloud_items = []
        self.properties.summary.set_bundle(None)

    def start_compute(
        self, mode: DiagnosticComputeMode = DiagnosticComputeMode.FAST_CORE, *, frozen: bool = False
    ) -> bool:
        if self.busy or self.external_busy or self._disposed:
            return False
        record = self.records.get(self.active_channel)
        if record is None:
            return False
        stages = (
            load_stage_segments(self.active_channel, self.repository_root)
            if self._matching_preset()
            else ()
        )
        return self.runner.start(
            record,
            self.active_channel,
            self.source_path,
            mode,
            stages,
            self.repository_root,
            frozen=frozen,
        )

    def load_frozen(self) -> bool:
        return self.frozen_available() and self.start_compute(frozen=True)

    def cancel_compute(self) -> None:
        self.runner.cancel()
        self.properties.cancel_button.setEnabled(False)
        self.properties.stage_label.setText("正在取消；等待当前估计器返回并退出线程。")

    def _busy_changed(self, busy: bool) -> None:
        self.properties.progress_bar.setRange(0, 0 if busy else 100)
        if not busy:
            self.properties.progress_bar.setValue(100 if self.bundle else 0)
        self._refresh_controls()
        self.busyChanged.emit(busy)

    def _progress(self, stage: str) -> None:
        self.properties.stage_label.setText("运行中 · " + stage)

    def _computed(self, result: DiagnosticBundle) -> None:
        if self._disposed:
            return
        # A programmatic file replacement can bypass the disabled Open action.
        record = self.records.get(result.channel_name)
        if (
            record is None
            or result.source_path != self.source_path
            or not np.array_equal(result.time_s, record.time_s)
            or not np.array_equal(result.voltage_v, record.voltage_v)
        ):
            self.properties.stage_label.setText("数据已变化；本次结果已丢弃。")
            return
        self.bundles[result.channel_name] = result
        if result.channel_name == self.active_channel:
            self.set_bundle(result)
        self.properties.stage_label.setText("完成 · " + result.compute_mode)

    def _cancelled(self) -> None:
        self.properties.stage_label.setText("已取消；未发布部分计算结果。")

    def _failed(self, message: str) -> None:
        self.properties.stage_label.setText("诊断失败：" + message)
        self.properties.stage_label.setToolTip(message)

    def set_bundle(self, bundle: DiagnosticBundle) -> None:
        self.bundle = bundle
        self.frame_index = 0
        self.bundles[bundle.channel_name] = bundle
        self.raw_plot.set_bundle(bundle)
        self.spectrogram.set_bundle(bundle)
        self._timeline_changed()
        self.properties.summary.set_bundle(bundle)
        self.onboarding.hide()
        self.showcase_button.hide()
        self._display_changed()
        self.select_frame(0)
        self.reset_view()
        self._refresh_controls()
        self.bundleChanged.emit(bundle)

    def _display_changed(self, _value: object = None) -> None:
        if self.bundle is None:
            return
        self.spectrogram.set_backdrop(
            str(self.backdrop_combo.currentData()), str(self.contrast_combo.currentData())
        )
        self.spectrogram.set_overlays(
            {name for name, button in self.method_buttons.items() if button.isChecked()},
            self.rejected_checkbox.isChecked(),
            self.cloud_checkbox.isChecked(),
        )
        self.spectrogram.set_band(bool(self.band_combo.currentData()))

    def _timeline_changed(self, _index: int = 0) -> None:
        if self.bundle is not None:
            estimator = self.inspector.focus.estimator if self.inspector.focus else "B1"
            self.timeline.set_bundle(self.bundle, str(self.metric_combo.currentData()), estimator)
            self.timeline.select_time(float(self.bundle.common_times_s[self.frame_index]))

    def _focus_changed(self, focus: CandidateEntry) -> None:
        self.spectrogram.select_frame(self.frame_index, focus)
        if self.bundle and "S2" not in self.bundle.curves:
            self._timeline_changed()

    def select_frame(self, index: int) -> None:
        if self.bundle is None:
            return
        self.frame_index = min(max(0, index), len(self.bundle.common_times_s) - 1)
        self.raw_plot.select_frame(self.bundle, self.frame_index)
        self.timeline.select_time(float(self.bundle.common_times_s[self.frame_index]))
        self.inspector.set_frame(self.bundle, self.frame_index)
        self.spectrogram.select_frame(self.frame_index, self.inspector.focus)
        self._update_counter()

    def select_sample(self, sample_index: int) -> None:
        if self.bundle:
            self.select_frame(int(np.argmin(abs(self.bundle.common_sample_indices - sample_index))))

    def _plot_clicked(self, time_s: float, frequency_ghz: float) -> None:
        if self.bundle is None:
            return
        self.select_frame(self.bundle.frame_index_for_time(time_s))
        if self.sender() is self.spectrogram:
            rows = self.inspector.table.rows
            valid = [
                (i, abs(c.raw_frequency_hz / 1e9 - frequency_ghz))
                for i, c in enumerate(rows)
                if np.isfinite(c.raw_frequency_hz)
            ]
            if valid:
                i, delta = min(valid, key=lambda x: x[1])
                if delta <= 0.2:
                    self.inspector.table.setCurrentCell(i, 0)

    def filtered_indices(self) -> list[int]:
        if self.bundle is None:
            return []
        category = str(self.filter_combo.currentData())
        return (
            list(range(len(self.bundle.common_times_s)))
            if category == "all"
            else self.bundle.indices_for_filter(category)
        )

    def _filter_changed(self, _index: int = 0) -> None:
        indices = self.filtered_indices()
        if indices:
            self.select_frame(min(indices, key=lambda i: abs(i - self.frame_index)))
        self._update_counter()

    def _update_counter(self) -> None:
        indices = self.filtered_indices()
        position = indices.index(self.frame_index) + 1 if self.frame_index in indices else 0
        self.key_counter.setText(f"{position} / {len(indices)}")
        self.previous_key_button.setEnabled(bool(indices))
        self.next_key_button.setEnabled(bool(indices))

    def jump_key(self, direction: int) -> None:
        indices = self.filtered_indices()
        if not indices:
            return
        if direction > 0:
            target = next((i for i in indices if i > self.frame_index), indices[0])
        else:
            target = next((i for i in reversed(indices) if i < self.frame_index), indices[-1])
        self.select_frame(target)

    def zoom_local(self) -> None:
        if self.bundle:
            t = float(self.bundle.common_times_s[self.frame_index]) * 1e6
            self.spectrogram.plot_widget.setXRange(t - 0.12, t + 0.12, padding=0)

    def reset_view(self) -> None:
        if self.bundle:
            self.spectrogram.plot_widget.setXRange(
                self.bundle.time_s[0] * 1e6, self.bundle.time_s[-1] * 1e6, padding=0
            )

    def _refresh_controls(self) -> None:
        busy = self.busy or self.external_busy
        loaded = bool(self.records)
        p = self.properties
        for button in (p.fast_button, p.full_button):
            button.setEnabled(loaded and not busy)
        p.frozen_button.setEnabled(self.frozen_available() and not busy)
        p.cancel_button.setEnabled(self.busy)
        p.channel_combo.setEnabled(loaded and not busy)
        p.preset_combo.setEnabled(bool(p.presets) and not busy)
        p.load_preset_button.setEnabled(bool(p.presets) and not busy)
        p.prefer_frozen_checkbox.setEnabled(not busy)
        self.showcase_button.setEnabled(bool(p.presets) and not busy)
        self.onboarding.setVisible(self.bundle is None)
        self.showcase_button.setVisible(not loaded)
        p.session_summary.setText(
            "\n".join(
                f"{name}: {self.bundles[name].compute_mode if name in self.bundles else '未计算'}"
                for name in self.records
            )
        )
        for widget in (
            self.previous_frame_button,
            self.next_frame_button,
            self.zoom_button,
            self.reset_button,
            self.filter_combo,
        ):
            widget.setEnabled(self.bundle is not None)
        self._update_counter()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.runner.dispose()
        self.inspector.dispose()
        for plot in (self.raw_plot, self.spectrogram, self.timeline):
            plot.dispose()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.dispose()
        super().closeEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.DeferredDelete and hasattr(self, "runner"):
            self.dispose()
        return super().event(event)
