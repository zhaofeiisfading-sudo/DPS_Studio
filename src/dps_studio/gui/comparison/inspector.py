"""One-frame readout of raw evidence and the recorded M4 decision."""
from __future__ import annotations

from math import isfinite

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QSizePolicy,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from dps_studio.core.stft_m4 import DiffCategory, LocalComparisonWaveform
from dps_studio.core.stft_m4.models import CATEGORY_ZH, REASON_ZH, PointEvidence

from .plots import WaveformPlot
from .theme import COLORS


def number(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}" if isfinite(value) else "—"


def _readout(point: PointEvidence, frequency_scale: float) -> tuple[str, ...]:
    return (
        number(point.accepted_hz*frequency_scale),
        number(point.candidate_hz*frequency_scale),
        f"{point.chirp_hz_s:.2e}" if isfinite(point.chirp_hz_s) else "—",
        f"{number(point.raw_tone_r2_64ns)} / {number(point.raw_chirp_r2_64ns)}",
        f"{number(point.raw_chirp_r2_256ns)} / {number(point.split_half_coherence_256ns)}",
        number(point.local_center_snr_32ns, 1),
        f"{number(point.verification_window_ns, 1)} / {number(point.verification_snr_db, 1)}",
        number(point.secondary_hz*frequency_scale) + (" · CW" if point.persistent_cw_overlap else ""),
    )


class ComparisonInspector(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.current: LocalComparisonWaveform | None = None
        self._wavelength_m: float | None = None
        self.waveform = WaveformPlot()
        self.waveform_mode_combo = QComboBox()
        self.waveform_mode_combo.addItems(("去趋势残差 + B1/M4 拟合", "原始电压 + 阶跃/触轨"))
        self.waveform_mode_combo.currentIndexChanged.connect(self._draw_waveform)
        waveform_header = QHBoxLayout()
        waveform_header.setContentsMargins(0, 0, 0, 0)
        self.frame_label = QLabel("原波形 · 点击时间图选帧")
        self.waveform_legend = QLabel()
        self.waveform_legend.setStyleSheet("font-size:11px;")
        waveform_header.addWidget(self.frame_label)
        waveform_header.addWidget(self.waveform_legend, 1)
        waveform_header.addWidget(self.waveform_mode_combo)
        wave_panel = QWidget()
        layout = QVBoxLayout(wave_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(waveform_header)
        layout.addWidget(self.waveform, 1)

        self.decision = QLabel("单帧证据")
        self.decision.setWordWrap(True)
        self.decision.setStyleSheet("font-size:11px;padding:2px 4px;")
        self.table = QTableWidget(8, 3)
        self.table.setHorizontalHeaderLabels(("原波形证据", "B1", "M4"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setMinimumSectionSize(15)
        self.table.verticalHeader().setDefaultSectionSize(16)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in (1, 2):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet("QTableWidget {font-size:11px;} QHeaderView::section {padding:2px;}")
        self.table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.table.setMinimumSize(0, 40)
        self.physical_note = QLabel("波形拟合可支持振荡。支路归属需结合实验证据。")
        self.physical_note.setWordWrap(True)
        self.physical_note.setStyleSheet("font-size:11px;color:#475569;")
        evidence_panel = QWidget()
        layout = QVBoxLayout(evidence_panel)
        layout.setContentsMargins(3, 0, 1, 0)
        layout.setSpacing(1)
        layout.addWidget(self.decision)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.physical_note)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(wave_panel)
        split.addWidget(evidence_panel)
        split.setSizes([560, 400])
        split.setStretchFactor(0, 56)
        split.setStretchFactor(1, 44)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split)
        self.show_frame(None)

    def show_frame(self, waveform: LocalComparisonWaveform | None) -> None:
        self.current = waveform
        self._draw_waveform()
        self._draw_evidence()

    def set_wavelength(self, wavelength_m: float | None) -> None:
        self._wavelength_m = wavelength_m
        self._draw_evidence()

    def _draw_waveform(self) -> None:
        value = self.current
        self.frame_label.setText("原波形 · 点击时间图选帧" if value is None else
                                f"原波形 · {value.center_time_s*1e6:.6f} µs")
        raw = self.waveform_mode_combo.currentIndex() == 1
        legend: tuple[tuple[str, str], ...]
        if raw:
            legend = (("raw_voltage", "━ 原电压"), ("baseline", "┄ 基线"),
                      ("dc_step", "┊ 阶跃"), ("rail", "┊ 触轨退出 · ● 触轨点"))
        elif value is not None:
            b1 = "━" if isfinite(value.b1.accepted_hz) else "┄"
            m4 = "━" if isfinite(value.m4.accepted_hz) else "┄"
            legend = (("residual", "━ 原残差"), ("b1", f"{b1} B1 拟合"), ("m4", f"{m4} M4 拟合"))
        else:
            legend = ()
        self.waveform_legend.setText(" &nbsp; ".join(
            f'<span style="color:{COLORS[key]}">{label}</span>' for key, label in legend
        ))
        self.waveform_legend.setVisible(value is not None)
        self.waveform.show_frame(value, raw=raw)

    def _draw_evidence(self) -> None:
        frame = self.current
        wave = self._wavelength_m
        unit = "GHz" if wave is None else "m/s"
        scale = 1e-9 if wave is None else wave/2
        titles = (f"最终发布 ({unit})", f"原始候选 ({unit})", "调频率 (Hz/s)",
                  "6.4 ns R² 正弦 / 调频", "25.6 ns R² / 分半相干",
                  "中心 SNR (dB)", "验证窗 (ns) / SNR (dB)", f"次支路 ({unit})")
        rows = (("—",)*len(titles),)*2 if frame is None else (
            _readout(frame.b1, scale), _readout(frame.m4, scale),
        )
        for row, cells in enumerate(zip(titles, *rows, strict=True)):
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if frame is not None and column == 1:
                    item.setToolTip(frame.b1.quality_flag)
                self.table.setItem(row, column, item)
        if frame is None:
            self.decision.setText("单帧证据")
            self.decision.setStyleSheet("font-size:11px;padding:2px 4px;")
            return
        color = {
            DiffCategory.M4_ADDED_SUPPORTED: COLORS["supported"],
            DiffCategory.M4_ADDED_AMBIGUOUS: COLORS["ambiguous"],
            DiffCategory.M4_DROPPED_STRONG_RISK: COLORS["risk"],
            DiffCategory.BRANCH_DIFF_MAJOR: COLORS["branch"],
        }.get(frame.category, "#334155")
        self.decision.setText(f"{CATEGORY_ZH[frame.category]}  |  {REASON_ZH[frame.reason]}")
        self.decision.setToolTip(
            f"{frame.reason.value}\nB1 · {frame.b1.quality_flag}\n"
            f"±16 ns · 触轨 {len(frame.rail_time_s)} 点 · DC 阶跃 {len(frame.dc_step_time_s)} 处"
            f" · 触轨退出 {len(frame.rail_exit_time_s)} 处"
        )
        self.decision.setStyleSheet(f"font-size:11px;font-weight:600;color:{color};padding:2px 4px;")
