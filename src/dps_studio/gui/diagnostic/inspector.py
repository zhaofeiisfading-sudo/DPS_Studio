"""Frame verdict, complete candidate comparison and raw-waveform microscope."""

from __future__ import annotations

from dataclasses import fields

import numpy as np
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.diagnostics import (
    CandidateEntry,
    DiagnosticBundle,
    LocalFrameEvidence,
    inspect_frame,
)

from .plots import LocalSpectrumPlot, LocalWaveformPlot
from .theme import METHOD_COLORS, number


def _candidate_detail(row: CandidateEntry) -> str:
    """Keep every original field and its precision available outside compact cells."""
    return "\n".join(f"{field.name}={getattr(row, field.name)!r}" for field in fields(row))


class FrameVerdictHeader(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)
        self.identity = QLabel("选择帧以检查局部原波形证据")
        self.identity.setWordWrap(True)
        self.identity.setStyleSheet("font-weight:600;")
        layout.addWidget(self.identity)
        grid = QGridLayout()
        grid.setSpacing(3)
        self.method_labels: dict[str, QLabel] = {}
        for i, (method, color) in enumerate(METHOD_COLORS.items()):
            label = QLabel()
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(100)
            label.setStyleSheet(f"border-left:3px solid {color};padding-left:4px;font-size:11px;")
            self.method_labels[method] = label
            grid.addWidget(label, i // 3, i % 3)
        layout.addLayout(grid)
        warning = QLabel(
            "⚠ S=True 仅证局部原波形正弦/调频支持，不自动确认物理主目标支路身份；"
            "多支路或弱信号时需结合轨迹连续性与实验先验确认。"
        )
        warning.setWordWrap(True)
        warning.setProperty("badge", "warning")
        warning.setStyleSheet("font-size:11px;")
        layout.addWidget(warning)

    def set_frame(self, bundle: DiagnosticBundle, index: int) -> None:
        time = float(bundle.common_times_s[index])
        q = int(bundle.common_sample_indices[index])
        self.identity.setText(
            f"帧 #{index} | q = {q} | 阶段: {bundle.frame_tags.stage[index]}\n"
            f"绝对时间 {time * 1e6:.4f} μs ({time:.9f} s) | 相对起点 "
            f"+{(time - bundle.time_s[0]) * 1e9:.1f} ns"
        )
        for method, label in self.method_labels.items():
            curve = bundle.curves.get(method)
            if curve is None:
                label.setText(f"{method} · 未计算")
            else:
                status = (
                    f"{'已选' if curve.selected[index] else '未选'} S{int(curve.s_supported[index])}"
                    if method in ("B+S", "S2")
                    else f"G{int(curve.g_accepted[index])} S{int(curve.s_supported[index])}"
                )
                label.setText(f"{method} {number(curve.frequency_hz[index] / 1e9, 3)} [{status}]")
            label.setToolTip(label.text() + " · 频率单位 GHz")


class CandidateComparisonTable(QTableWidget):
    candidateSelected = Signal(int)

    def __init__(self) -> None:
        super().__init__(0, 8)
        self.setHorizontalHeaderLabels(
            ["估计器", "簇", "频率(GHz)", "调频(G/μs)", "C/G/S", "选中", "R²(单/调)", "比/增/周"]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().hide()
        self.verticalHeader().setMinimumSectionSize(22)
        self.verticalHeader().setDefaultSectionSize(22)
        self.horizontalHeader().setMinimumSectionSize(18)
        for column in range(7):
            self.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.setStyleSheet(
            "QTableWidget {font-size:10px;} "
            "QTableWidget::item {padding:0 1px;} "
            "QHeaderView::section {padding:3px 1px;font-size:10px;}"
        )
        self.setMinimumHeight(170)
        self.currentCellChanged.connect(self._current_changed)
        self.rows: tuple[CandidateEntry, ...] = ()

    def _current_changed(self, row: int, _col: int, _previous: int, _previous_col: int) -> None:
        if 0 <= row < len(self.rows):
            self.candidateSelected.emit(row)

    def set_candidates(self, bundle: DiagnosticBundle, index: int) -> None:
        self.rows = bundle.candidates_by_frame[index]
        clusters = {c.cluster_id: c for c in bundle.clusters_by_frame[index]}
        with QSignalBlocker(self):
            self.setRowCount(len(self.rows))
            for i, row in enumerate(self.rows):
                estimator = {"matrix_pencil": "mp", "clutter_varpro": "clutter_vp"}.get(
                    row.estimator, row.estimator
                )
                selections = (["S2"] if row.s2_selected else []) + (
                    ["B+S"] if row.estimator == "B1" and row.s_supported else []
                )
                r2 = (
                    f"{number(row.raw_tone_r2, 2)}/{number(row.raw_chirp_r2, 2)}"
                    if np.isfinite([row.raw_tone_r2, row.raw_chirp_r2]).any()
                    else "—"
                )
                values = [
                    estimator + (f" #{row.native_rank}" if row.native_rank > 1 else ""),
                    str(row.cluster_id) if row.cluster_id >= 0 else "—",
                    number(row.frequency_hz / 1e9, 4),
                    number(row.chirp_hz_s / 1e15, 1),
                    f"{int(row.c_present)}/{int(row.g_accepted)}/{int(row.s_supported)}",
                    "+".join(selections) or "—",
                    r2,
                    f"{number(row.spectral_contrast_db, 1)}/{number(row.background_gain_db, 1)}/"
                    f"{number(row.cycles_256, 1)}",
                ]
                cluster = clusters.get(row.cluster_id)
                color = (
                    "#fff0f3"
                    if cluster and cluster.high_without_s
                    else "#eaf6ef"
                    if row.s2_selected or row.estimator == "B1" and row.s_supported
                    else "#fff4df"
                    if row.g_accepted and not row.s_supported
                    else "#eaf4fc"
                    if row.s_supported and not row.g_accepted
                    else "#ffffff"
                )
                detail = (
                    "frequency_hz / chirp_hz_s: SI；比/增: dB；周: 256点周期数\n"
                    + _candidate_detail(row)
                )
                for j, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setBackground(QColor(color))
                    item.setToolTip(detail)
                    self.setItem(i, j, item)
            self.clearSelection()
            self.setCurrentCell(-1, -1)


class CandidateReasonBox(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(90)
        self.setMaximumHeight(102)
        self.setStyleSheet("font-size:10px;background:#f8fafc;border:1px solid #d6dde3;")

    def set_candidate(self, bundle: DiagnosticBundle, index: int, row: CandidateEntry) -> None:
        cluster = next(
            (c for c in bundle.clusters_by_frame[index] if c.cluster_id == row.cluster_id), None
        )
        s_clusters = str(cluster.s_clusters_at_center) if cluster else "—"
        lines = [
            f"{row.estimator} · {row.verdict_code} · 簇 {row.cluster_id} | "
            f"S2_score={number(row.s2_score)} (votes={row.family_votes}, 竞争S簇={s_clusters})"
        ]
        finite_r2 = [value for value in (row.raw_tone_r2, row.raw_chirp_r2) if np.isfinite(value)]
        max_r2 = max(finite_r2, default=float("nan"))
        gates = (
            ("对比", row.spectral_contrast_db, 10.0, "dB", 1),
            ("增益", row.background_gain_db, 6.0, "dB", 1),
            ("周期", row.cycles_256, 1.0, "", 2),
            ("maxR²", max_r2, 0.2, "", 3),
        )
        lines.append(
            f"S判据({'通过' if row.s_supported else '未过'}): "
            + " | ".join(
                f"{'[过]' if np.isfinite(value) and value >= limit else '[未]'}{name}="
                f"{number(value, digits)}{unit}(≥{limit:.2f})"
                for name, value, limit, unit, digits in gates
            )
        )
        flags = []
        if any("Chirp 调频救回" in reason for reason in row.accept_reasons_zh):
            flags.append("Chirp 调频救回(Tone→Chirp)")
        if row.g_accepted and not row.s_supported:
            flags.append("[可疑] G=1无S")
        if row.s_supported and not row.g_accepted:
            flags.append("隐藏信号(S=1被G抑制)")
        if any(
            "DC" in reason or "直流" in reason
            for reason in (*row.accept_reasons_zh, *row.reject_reasons_zh)
        ):
            flags.append("DC泄漏提示")
        if cluster and cluster.high_without_s:
            flags.append("high_without_S")
        flags.append(f"G={int(row.g_accepted)} ({row.native_quality}, {row.run_status})")
        lines.append(" | ".join(flags))
        contributors = ",".join(cluster.s2_contributors) if cluster else ""
        extent = (
            f"{cluster.frequency_lo_hz / 1e9:.4f}–{cluster.frequency_hi_hz / 1e9:.4f} GHz"
            if cluster
            else "—"
        )
        lines.append(f"S2贡献: {contributors or '无'} | 簇范围 {extent}")
        self.setPlainText("\n".join(lines))
        self.setToolTip(
            self.toPlainText()
            + "\n\n"
            + _candidate_detail(row)
            + (f"\n{cluster!r}" if cluster else "")
        )


class FrameInspectorPanel(QWidget):
    focusChanged = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.bundle: DiagnosticBundle | None = None
        self.frame_index = 0
        self.focus: CandidateEntry | None = None
        self.evidence: LocalFrameEvidence | None = None
        self._preferred: tuple[str, int] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self.splitter)
        verdict = QWidget()
        upper = QVBoxLayout(verdict)
        upper.setContentsMargins(0, 0, 0, 0)
        upper.setSpacing(3)
        self.header = FrameVerdictHeader()
        self.table = CandidateComparisonTable()
        self.reason_box = CandidateReasonBox()
        upper.addWidget(self.header)
        upper.addWidget(self.table, 1)
        upper.addWidget(self.reason_box)
        self.splitter.addWidget(verdict)
        local = QWidget()
        local_layout = QVBoxLayout(local)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(2)
        controls = QHBoxLayout()
        self.waveform_mode_combo = QComboBox()
        self.waveform_mode_combo.addItem("去基线残差 + 拟合", "detrended")
        self.waveform_mode_combo.addItem("含DC原始电压 + 基线", "raw")
        self.window_combo = QComboBox()
        self.window_combo.addItem("256点 (S证据窗)", 256)
        self.window_combo.addItem("512点对比", 512)
        controls.addWidget(self.waveform_mode_combo, 1)
        controls.addWidget(self.window_combo)
        local_layout.addLayout(controls)
        self.waveform_plot = LocalWaveformPlot()
        self.spectrum_plot = LocalSpectrumPlot()
        local_layout.addWidget(self.waveform_plot, 1)
        self.splitter.addWidget(local)
        self.splitter.addWidget(self.spectrum_plot)
        self.splitter.setSizes([410, 190, 200])
        self.table.candidateSelected.connect(self.select_candidate)
        self.waveform_mode_combo.currentIndexChanged.connect(self.refresh_evidence)
        self.window_combo.currentIndexChanged.connect(self.refresh_evidence)

    def set_frame(self, bundle: DiagnosticBundle, index: int) -> None:
        self.bundle, self.frame_index = bundle, index
        self.header.set_frame(bundle, index)
        self.table.set_candidates(bundle, index)
        rows = self.table.rows
        if not rows:
            self.focus = None
            self.reason_box.setPlainText("当前帧无候选")
            return
        preferred = next(
            (i for i, c in enumerate(rows) if (c.estimator, c.native_rank) == self._preferred), None
        )
        if preferred is None:
            preferred = next((i for i, c in enumerate(rows) if c.s2_selected), None)
        if preferred is None:
            preferred = next(
                (i for i, c in enumerate(rows) if c.estimator == "B1" and c.c_present),
                next((i for i, c in enumerate(rows) if c.c_present), 0),
            )
        self.table.setCurrentCell(preferred, 0)

    def select_estimator(self, estimator: str, rank: int = 1) -> bool:
        for i, candidate in enumerate(self.table.rows):
            if (candidate.estimator, candidate.native_rank) == (estimator, rank):
                self.table.setCurrentCell(i, 0)
                return True
        return False

    def select_candidate(self, row: int) -> None:
        if self.bundle is None or not 0 <= row < len(self.table.rows):
            return
        self.focus = self.table.rows[row]
        self._preferred = self.focus.estimator, self.focus.native_rank
        self.reason_box.set_candidate(self.bundle, self.frame_index, self.focus)
        self.refresh_evidence()
        self.focusChanged.emit(self.focus)

    def refresh_evidence(self, _index: int = 0) -> None:
        bundle, focus = self.bundle, self.focus
        if bundle is None or focus is None:
            return
        self.evidence = inspect_frame(
            bundle.time_s,
            bundle.voltage_v,
            int(bundle.common_sample_indices[self.frame_index]),
            bundle.background_stop_index,
            focus_frequency_hz=focus.frequency_hz,
            focus_chirp_hz_s=focus.chirp_hz_s,
            focus_label=focus.estimator,
            fmin_hz=bundle.eval_fmin_hz,
            fmax_hz=bundle.eval_fmax_hz,
            window_width=int(self.window_combo.currentData()),
        )
        self.waveform_plot.set_evidence(self.evidence, str(self.waveform_mode_combo.currentData()))
        self.spectrum_plot.set_evidence(self.evidence, self.table.rows)

    def clear(self) -> None:
        self.bundle, self.focus, self.evidence = None, None, None
        self._preferred = None
        self.header.identity.setText("选择通道并计算诊断，或载入冻结共识栈。")
        for label in self.header.method_labels.values():
            label.clear()
        self.table.setRowCount(0)
        self.table.rows = ()
        self.reason_box.clear()
        for plot in (self.waveform_plot, self.spectrum_plot):
            plot.plot_widget.clear()
            plot.metric_label.clear()
            plot.evidence = None

    def dispose(self) -> None:
        self.waveform_plot.dispose()
        self.spectrum_plot.dispose()
