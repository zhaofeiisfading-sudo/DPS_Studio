"""Linked SI-to-display views and local evidence plots, without data alteration."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dps_studio.core.diagnostics import (
    CandidateEntry,
    DiagnosticBundle,
    LocalFrameEvidence,
    StageSegment,
)

from .theme import (
    ANOMALIES,
    ESTIMATOR_COLORS,
    METHOD_COLORS,
    STAGE_COLORS,
    contrast_levels,
    number,
    spectrogram_lut,
)


class PlotPanel(QWidget):
    timeClicked = Signal(float, float)

    def __init__(self, title: str, ylabel: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.root_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight:600;color:#263746;padding:2px 5px;")
        layout.addWidget(self.title)
        self.plot_widget = pg.PlotWidget(background="#ffffff")
        self.plot_widget.setMinimumSize(120, 75)
        self.plot_widget.setLabel("left", ylabel)
        self.plot_widget.setLabel("bottom", "时间 (μs)")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.12)
        self.plot_widget.setMenuEnabled(False)
        for axis in ("left", "bottom"):
            self.plot_widget.getAxis(axis).setPen("#9cabb6")
            self.plot_widget.getAxis(axis).setTextPen("#263746")
            self.plot_widget.getAxis(axis).enableAutoSIPrefix(False)
        self.plot_widget.getAxis("left").setWidth(58)
        layout.addWidget(self.plot_widget)
        self.plot_widget.scene().sigMouseClicked.connect(self._clicked)
        self.cursor: Any = None

    def _clicked(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        vb = self.plot_widget.plotItem.vb
        if vb.sceneBoundingRect().contains(event.scenePos()):
            point = vb.mapSceneToView(event.scenePos())
            self.timeClicked.emit(float(point.x()) * 1e-6, float(point.y()))

    def add_cursor(self) -> None:
        self.cursor = pg.InfiniteLine(pen=pg.mkPen("#0ea5e9", width=1.5), movable=False)
        self.cursor.setZValue(30)
        self.plot_widget.addItem(self.cursor)

    def select_time(self, time_s: float) -> None:
        if self.cursor is not None:
            self.cursor.setPos(time_s * 1e6)

    def dispose(self) -> None:
        self.plot_widget.scene().sigMouseClicked.disconnect(self._clicked)
        self.plot_widget.setXLink(None)
        self.plot_widget.clear()


class RawVoltageStripPlot(PlotPanel):
    def __init__(self) -> None:
        super().__init__("01  原始电压 · 阶段与证据窗", "电压 (V)")
        self.evidence_region: Any = None
        self.background_line: Any = None
        self._stage_labels: list[tuple[StageSegment, Any]] = []
        self.plot_widget.plotItem.vb.sigRangeChanged.connect(self._position_stage_labels)

    def set_bundle(self, bundle: DiagnosticBundle) -> None:
        self.plot_widget.clear()
        self._stage_labels = []
        # Ordered extrema per bucket preserve transients instead of striding them away.
        n = len(bundle.time_s)
        step = max(1, int(np.ceil(n / 5000)))
        indices: list[int] = []
        for start in range(0, n, step):
            chunk = bundle.voltage_v[start : start + step]
            indices.extend(
                sorted(
                    {
                        start,
                        start + int(np.argmin(chunk)),
                        start + int(np.argmax(chunk)),
                        min(n - 1, start + step - 1),
                    }
                )
            )
        self.plot_widget.plot(
            bundle.time_s[indices] * 1e6,
            bundle.voltage_v[indices],
            pen=pg.mkPen("#51687b", width=0.8),
            connect="finite",
        )
        for stage in bundle.stages:
            color = STAGE_COLORS.get(stage.stage, "#f1f5f9")
            band = pg.LinearRegionItem(
                (stage.start_s * 1e6, stage.end_s * 1e6),
                movable=False,
                brush=pg.mkBrush(color),
                pen=pg.mkPen(None),
            )
            band.setZValue(-5)
            self.plot_widget.addItem(band)
            tag = pg.TextItem(
                stage.stage, anchor=(0.5, 0), color="#526473", fill=(255, 255, 255, 210)
            )
            tag.setToolTip(f"{stage.segment_id}: {stage.visual_evidence}")
            self.plot_widget.addItem(tag, ignoreBounds=True)
            self._stage_labels.append((stage, tag))
        cutoff = min(bundle.background_stop_index, n - 1)
        self.background_line = pg.InfiniteLine(
            bundle.time_s[cutoff] * 1e6,
            pen=pg.mkPen("#64748b", style=Qt.PenStyle.DashLine),
            label="静默背景截止",
            labelOpts={"position": 0.2, "color": "#64748b"},
        )
        self.plot_widget.addItem(self.background_line)
        self.evidence_region = pg.LinearRegionItem(
            (0, 0), movable=False, brush=(14, 165, 233, 40), pen=pg.mkPen("#7cb8df")
        )
        self.evidence_region.setZValue(5)
        self.plot_widget.addItem(self.evidence_region)
        self.add_cursor()

    def _position_stage_labels(self, *_args: object) -> None:
        bounds = self.plot_widget.viewRange()
        lo, hi = bounds[0]
        span = max(hi - lo, 1e-12)
        pixels = max(1, self.plot_widget.viewport().width() - 70)
        for stage, label in self._stage_labels:
            start, stop = max(lo, stage.start_s * 1e6), min(hi, stage.end_s * 1e6)
            # Labels fit entirely inside their visible, non-overlapping stage interval.
            label.setVisible((stop - start) / span * pixels >= max(45, len(stage.stage) * 6))
            label.setPos((start + stop) / 2, bounds[1][1] - 0.04 * (bounds[1][1] - bounds[1][0]))

    def dispose(self) -> None:
        self.plot_widget.plotItem.vb.sigRangeChanged.disconnect(self._position_stage_labels)
        super().dispose()

    def select_frame(self, bundle: DiagnosticBundle, index: int) -> None:
        q = int(bundle.common_sample_indices[index])
        self.select_time(float(bundle.common_times_s[index]))
        self.evidence_region.setRegion(
            (
                bundle.time_s[max(0, q - 128)] * 1e6,
                bundle.time_s[min(len(bundle.time_s) - 1, q + 127)] * 1e6,
            )
        )


class SpectrogramDiagnosticPlot(PlotPanel):
    def __init__(self) -> None:
        super().__init__("02  共同原始时频底图 · C / G / S / 选择", "频率 (GHz)")
        self.image: Any = None
        self.method_items: dict[str, list[Any]] = {}
        self.frame_markers: Any = None
        self.focus_marker: Any = None
        self.bundle: DiagnosticBundle | None = None
        self.cloud_items: list[Any] = []

    def set_bundle(self, bundle: DiagnosticBundle) -> None:
        self.bundle = bundle
        self.plot_widget.clear()
        self.method_items = {}
        self.cloud_items = []
        self.image = pg.ImageItem(axisOrder="row-major")
        self.image.setLookupTable(spectrogram_lut())
        self.image.setZValue(-10)
        self.plot_widget.addItem(self.image)
        for value, text in (
            (bundle.eval_fmin_hz / 1e9, "50 MHz"),
            (bundle.eval_fmax_hz / 1e9, "6.00 GHz 评估上限"),
        ):
            self.plot_widget.addItem(
                pg.InfiniteLine(
                    value,
                    angle=0,
                    pen=pg.mkPen("#71859a", style=Qt.PenStyle.DashLine),
                    label=text,
                    labelOpts={"position": 0.85, "color": "#526473"},
                )
            )
        for name, curve in bundle.curves.items():
            color = METHOD_COLORS[name]
            derived = name in ("B+S", "S2")
            good = curve.selected if derived else curve.g_accepted & curve.s_supported
            y = np.where(good, curve.frequency_hz / 1e9, np.nan)
            any_good = bool(np.isfinite(y).any())
            line = self.plot_widget.plot(
                curve.time_s * 1e6 if any_good else [],
                y if any_good else [],
                connect="finite",
                pen=pg.mkPen(color, width=2.2 if derived else 1.2),
                symbol="star" if name == "S2" else "o",
                symbolSize=5,
                symbolBrush=color,
                symbolPen=color,
            )
            items = [line]
            if not derived:
                mask = curve.c_present & curve.g_accepted & ~curve.s_supported
                items.append(
                    self.plot_widget.plot(
                        curve.time_s[mask] * 1e6,
                        curve.frequency_hz[mask] / 1e9,
                        pen=None,
                        symbol="d",
                        symbolSize=7,
                        symbolPen=pg.mkPen("#d97706", width=1.2),
                        symbolBrush=None,
                    )
                )
            rejected = curve.c_present & (~curve.selected if derived else ~curve.g_accepted)
            # S-without-G uses +; rejected rings remain visible by default.
            hidden_signal = rejected & curve.s_supported if not derived else np.zeros_like(rejected)
            for mask, symbol in (
                (rejected & ~hidden_signal, "x" if derived else "o"),
                (hidden_signal, "+"),
            ):
                item = self.plot_widget.plot(
                    curve.time_s[mask] * 1e6,
                    curve.proposal_hz[mask] / 1e9,
                    pen=None,
                    symbol=symbol,
                    symbolSize=5,
                    symbolPen=pg.mkPen(color, width=0.8),
                    symbolBrush=None,
                )
                item.setOpacity(0.4)
                item.setProperty("rejected", True)
                items.append(item)
            self.method_items[name] = items
        extras = [
            c
            for row in bundle.candidates_by_frame
            for c in row
            if c.estimator not in ("B0", "B1", "dechirp", "varpro") and c.c_present
        ]
        cloud = self.plot_widget.plot(
            [c.time_s * 1e6 for c in extras],
            [c.frequency_hz / 1e9 for c in extras],
            pen=None,
            symbol="o",
            symbolSize=3,
            symbolPen=None,
            symbolBrush=(111, 84, 150, 60),
        )
        self.cloud_items.append(cloud)
        self.frame_markers = pg.ScatterPlotItem(
            size=11, pen=pg.mkPen("#0ea5e9", width=1.5), brush=None
        )
        self.focus_marker = pg.ScatterPlotItem(
            size=18, pen=pg.mkPen("#111827", width=2.5), brush=None, symbol="o"
        )
        self.frame_markers.setZValue(40)
        self.focus_marker.setZValue(41)
        self.plot_widget.addItem(self.frame_markers)
        self.plot_widget.addItem(self.focus_marker)
        self.add_cursor()
        self.set_backdrop("demeaned", "adaptive")
        self.set_band(False)

    def set_backdrop(self, backdrop: str, contrast: str) -> None:
        self.title.setText(
            "02  传统原始 1024 STFT 底图 (无去均值，可见DC泄漏) · C / G / S / 选择"
            if backdrop == "raw"
            else "02  去均值 512 STFT 底图 (抑制直流偏置) · C / G / S / 选择"
        )
        if self.bundle is None:
            return
        layer = (
            self.bundle.raw_spectrogram if backdrop == "raw" else self.bundle.demeaned_spectrogram
        )
        times, freq = layer.time_s * 1e6, layer.frequency_hz / 1e9
        dt = (
            float(times[1] - times[0]) if len(times) > 1 else 128 / self.bundle.sample_rate_hz * 1e6
        )
        df = float(freq[1] - freq[0]) if len(freq) > 1 else 0.001
        self.image.setImage(
            layer.power_db, autoLevels=False, levels=contrast_levels(layer.power_db, contrast)
        )
        self.image.setRect(
            QRectF(
                float(times[0] - dt / 2), float(freq[0] - df / 2), dt * len(times), df * len(freq)
            )
        )
        self.title.setToolTip(layer.label + "；颜色仅改变显示对比度，不改变功率或候选。")

    def set_overlays(self, methods: set[str], rejected: bool, cloud: bool) -> None:
        for name, items in self.method_items.items():
            for item in items:
                item.setVisible(name in methods and (rejected or not item.property("rejected")))
        for item in self.cloud_items:
            item.setVisible(cloud)

    def set_band(self, main_band: bool) -> None:
        self.plot_widget.setYRange(0, 6.2 if main_band else 10, padding=0)

    def select_frame(self, index: int, focus: CandidateEntry | None) -> None:
        if self.bundle is None:
            return
        time = float(self.bundle.common_times_s[index])
        self.select_time(time)
        # Raw out-of-band frequencies are context, never promoted into in-band C/S.
        valid = [
            c for c in self.bundle.candidates_by_frame[index] if np.isfinite(c.raw_frequency_hz)
        ]
        self.frame_markers.setData(
            x=[time * 1e6] * len(valid), y=[c.raw_frequency_hz / 1e9 for c in valid]
        )
        hz = focus.raw_frequency_hz if focus is not None else np.nan
        self.focus_marker.setData(
            x=[time * 1e6] if np.isfinite(hz) else [], y=[hz / 1e9] if np.isfinite(hz) else []
        )


class EvidenceTimelinePlot(PlotPanel):
    def __init__(self) -> None:
        super().__init__("03  原波形证据 · 异常时间线", "R²")
        legend = QWidget()
        row = QHBoxLayout(legend)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(8)
        self.curve_legend_labels = [QLabel(), QLabel()]
        for curve_label, text, color in zip(
            self.curve_legend_labels, ("Tone R²", "Chirp R²"), ("#0284c7", "#be123c")
        ):
            curve_label.setText("—— " + text)
            curve_label.setStyleSheet(f"color:{color};font-size:10px;")
            row.addWidget(curve_label)
        for _, label, color in ANOMALIES:
            badge = QLabel("▼ " + label)
            badge.setStyleSheet(f"color:{color};font-size:10px;")
            row.addWidget(badge)
        row.addStretch()
        self.root_layout.insertWidget(1, legend)

    def set_bundle(self, bundle: DiagnosticBundle, mode: str, estimator: str = "B1") -> None:
        self.plot_widget.clear()
        rows: list[CandidateEntry | None] = []
        for frame in bundle.candidates_by_frame:
            selected = next((c for c in frame if c.s2_selected), None)
            rows.append(selected or next((c for c in frame if c.estimator == estimator), None))
        fields = (
            (("raw_tone_r2", "Tone R²", "#0284c7"), ("raw_chirp_r2", "Chirp R²", "#be123c"))
            if mode == "r2"
            else (
                ("spectral_contrast_db", "对比度 dB", "#0284c7"),
                ("background_gain_db", "背景增益 dB", "#059669"),
            )
        )
        t = bundle.common_times_s * 1e6
        for legend_label, (field, label, color) in zip(self.curve_legend_labels, fields):
            legend_label.setText("—— " + label)
            legend_label.setStyleSheet(f"color:{color};font-size:10px;")
            self.plot_widget.plot(
                t,
                [getattr(c, field) if c else np.nan for c in rows],
                pen=pg.mkPen(color, width=1.2),
                connect="finite",
                name=label,
            )
        for threshold in (0.2,) if mode == "r2" else (10.0, 6.0):
            self.plot_widget.addItem(
                pg.InfiniteLine(
                    threshold,
                    angle=0,
                    pen=pg.mkPen("#94a3b8", style=Qt.PenStyle.DashLine),
                    label=f"R²={threshold:.2f}" if mode == "r2" else f"{threshold:g} dB",
                    labelOpts={"position": 0.9, "color": "#64748b"},
                )
            )
        top = 1.05 if mode == "r2" else 45.0
        spacing = 0.08 if mode == "r2" else 4.0
        for i, (field, label, color) in enumerate(ANOMALIES):
            mask = getattr(bundle.frame_tags, field)
            self.plot_widget.plot(
                t[mask],
                np.full(int(mask.sum()), top + i * spacing),
                pen=None,
                symbol="t",
                symbolSize=6,
                symbolPen=None,
                symbolBrush=color,
                name=label,
            )
        self.plot_widget.setLabel("left", "R²" if mode == "r2" else "证据 (dB)")
        self.title.setText("03  " + " / ".join(x[1] for x in fields) + " · 异常彩色标记")
        self.title.setToolTip(" | ".join(f"{label} ({color})" for _, label, color in ANOMALIES))
        self.add_cursor()


class LocalWaveformPlot(PlotPanel):
    def __init__(self) -> None:
        super().__init__("局部原波形与拟合", "电压(V)")
        self.plot_widget.getAxis("left").setWidth(52)
        self.metric_label = QLabel()
        self.metric_label.setWordWrap(True)
        self.root_layout.addWidget(self.metric_label)
        self.evidence: LocalFrameEvidence | None = None

    def set_evidence(self, evidence: LocalFrameEvidence, mode: str) -> None:
        self.evidence = evidence
        self.plot_widget.clear()
        self.plot_widget.setLabel("bottom", "相对帧中心 (ns)")
        t = evidence.tau_s * 1e9
        raw = mode == "raw"
        self.plot_widget.plot(
            t,
            evidence.raw_voltage_v if raw else evidence.detrended_v,
            pen=pg.mkPen("#334d62", width=1.3),
        )
        if raw:
            self.plot_widget.plot(
                t, evidence.baseline_v, pen=pg.mkPen("#94a3b8", style=Qt.PenStyle.DashLine)
            )
        self.plot_widget.plot(
            t,
            evidence.tone_fit_raw_v if raw else evidence.tone_fit_detrended_v,
            pen=pg.mkPen("#0284c7", width=1.5, style=Qt.PenStyle.DashLine),
        )
        self.plot_widget.plot(
            t,
            evidence.chirp_fit_raw_v if raw else evidence.chirp_fit_detrended_v,
            pen=pg.mkPen("#be123c", width=1.6),
        )
        self.metric_label.setText(
            f"DC={number(evidence.dc_offset_v, 4)} V · 基线跨度={number(evidence.baseline_span_v, 4)} V\n"
            f"Tone R²={number(evidence.raw_tone_r2, 3)} · Chirp R²={number(evidence.raw_chirp_r2, 3)}"
            f" · 周期={number(evidence.cycles_256)}"
            + (" · 当前选中候选无带内频率" if not np.isfinite(evidence.focus_frequency_hz) else "")
        )
        self.plot_widget.autoRange()


class LocalSpectrumPlot(PlotPanel):
    def __init__(self) -> None:
        super().__init__("局部功率谱与背景阈值 · FFT 功率 (dB re 1 V²)，非每Hz密度", "功率 / dB")
        self.title.setToolTip("FFT 功率 (dB re 1 V²)，非每Hz密度")
        self.plot_widget.getAxis("left").setWidth(46)
        self.metric_label = QLabel()
        self.metric_label.setWordWrap(True)
        self.root_layout.addWidget(self.metric_label)
        self.evidence: LocalFrameEvidence | None = None
        self._badges: list[tuple[Any, float, int]] = []
        self._spectrum_y_hi: float | None = None
        vb = self.plot_widget.plotItem.vb
        vb.sigRangeChanged.connect(self._position_badges)
        vb.sigResized.connect(self._position_badges)

    def _add_badge(
        self, text: str, frequency_ghz: float, lane: int, *, focus: bool = False
    ) -> None:
        badge = pg.TextItem(
            text,
            anchor=(0.5, 1),
            color="#111827" if focus else "#334155",
            fill=(255, 255, 255, 220),
            border="#111827" if focus else "#cbd5e1",
        )
        font = self.font()
        font.setPixelSize(10)
        font.setBold(focus)
        badge.setFont(font)
        badge.textItem.document().setDocumentMargin(0)
        badge.updateTextPos()
        badge.setZValue(45 if focus else 40)
        self.plot_widget.addItem(badge, ignoreBounds=True)
        self._badges.append((badge, frequency_ghz, lane))

    def _position_badges(self, *_args: object) -> None:
        """Pack actual text rectangles inside headroom, including after resize/zoom."""
        if self._spectrum_y_hi is None or not self._badges:
            return
        vb = self.plot_widget.plotItem.vb
        bounds = vb.sceneBoundingRect().adjusted(3, 2, -3, -2)
        top = max(bounds.top(), vb.mapViewToScene(QPointF(0, self._spectrum_y_hi + 22)).y() + 1)
        bottom = min(
            bounds.bottom(), vb.mapViewToScene(QPointF(0, self._spectrum_y_hi + 1)).y() - 1
        )
        placed: list[QRectF] = []
        for badge, frequency, lane in self._badges:
            rect = badge.textItem.boundingRect()
            width, height = rect.width(), rect.height()
            preferred_x = vb.mapViewToScene(QPointF(frequency, 0)).x()
            # The focus badge is packed first; other pills avoid its full rectangle.
            choices: list[tuple[float, QRectF]] = []
            for offset in range(4):
                y = self._spectrum_y_hi + (19, 13, 7, 2)[(lane + offset) % 4]
                base = max(top + height, min(bottom, vb.mapViewToScene(QPointF(0, y)).y()))
                xs = [preferred_x]
                for other in placed:
                    xs.extend((other.left() - width / 2 - 3, other.right() + width / 2 + 3))
                for x in xs:
                    x = max(bounds.left() + width / 2, min(bounds.right() - width / 2, x))
                    candidate = QRectF(x - width / 2, base - height, width, height)
                    if not any(candidate.adjusted(-2, -1, 2, 1).intersects(p) for p in placed):
                        choices.append((abs(x - preferred_x) + offset * 12, candidate))
            if choices:
                _, position = min(choices, key=lambda item: item[0])
                placed.append(position)
                badge.setPos(vb.mapSceneToView(QPointF(position.center().x(), position.bottom())))

    def dispose(self) -> None:
        vb = self.plot_widget.plotItem.vb
        vb.sigRangeChanged.disconnect(self._position_badges)
        vb.sigResized.disconnect(self._position_badges)
        self._badges = []
        super().dispose()

    def set_evidence(
        self, ev: LocalFrameEvidence, rows: tuple[CandidateEntry, ...], display_fmax: float = 8e9
    ) -> None:
        self.evidence = ev
        self._badges = []
        self._spectrum_y_hi = None
        self.plot_widget.clear()
        self.plot_widget.setLabel("bottom", "频率 (GHz)")
        f = ev.spectrum_freq_hz / 1e9
        for y, color, style in (
            (ev.local_psd_db, "#334d62", Qt.PenStyle.SolidLine),
            (ev.background_psd_db, "#94a3b8", Qt.PenStyle.DashLine),
            (ev.background_psd_db + 6, "#d97706", Qt.PenStyle.DotLine),
        ):
            self.plot_widget.plot(
                f, y, pen=pg.mkPen(color, width=1.2, style=style), connect="finite"
            )
        band = (f >= 0.05) & (f <= 8) & np.isfinite(ev.local_psd_db)
        if band.any():
            ref = float(np.median(ev.local_psd_db[band])) + 10
            self.plot_widget.addItem(
                pg.InfiniteLine(
                    ref,
                    angle=0,
                    pen=pg.mkPen("#64748b", style=Qt.PenStyle.DashLine),
                    label="median +10 dB",
                    labelOpts={"position": 0.84, "color": "#64748b"},
                )
            )
        finite_rows = sorted(
            (row for row in rows if np.isfinite(row.raw_frequency_hz)),
            key=lambda row: row.raw_frequency_hz,
        )
        groups: list[list[CandidateEntry]] = []
        for row in finite_rows:
            self.plot_widget.addItem(
                pg.InfiniteLine(
                    row.raw_frequency_hz / 1e9,
                    pen=pg.mkPen(ESTIMATOR_COLORS.get(row.estimator, "#9c8aaa"), width=0.8),
                    label=None,
                )
            )
            if not groups or row.raw_frequency_hz - groups[-1][0].raw_frequency_hz > 0.06e9:
                groups.append([])
            groups[-1].append(row)
        if np.isfinite(ev.focus_frequency_hz):
            self.plot_widget.addItem(
                pg.InfiniteLine(
                    ev.focus_frequency_hz / 1e9, pen=pg.mkPen("#111827", width=2.2), label=None
                )
            )
        self.metric_label.setText(
            f"contrast={number(ev.spectral_contrast_db)} dB · gain={number(ev.background_gain_db)} dB\n"
            f"strongest_peak={number(ev.strongest_peak_hz / 1e9, 3)} GHz · "
            f"competitor={number(ev.strongest_competitor_hz / 1e9, 3)} GHz"
        )
        visible = (f >= 0) & (f <= display_fmax / 1e9)
        powers = np.concatenate((ev.local_psd_db[visible], ev.background_psd_db[visible]))
        powers = powers[np.isfinite(powers)]
        if powers.size:
            y_lo, y_hi = float(powers.min()), float(powers.max())
            self.plot_widget.setYRange(y_lo - 4.0, y_hi + 22.0, padding=0)
            self._spectrum_y_hi = y_hi
            if np.isfinite(ev.focus_frequency_hz):
                self._add_badge(
                    "[聚焦] " + ev.focus_label, ev.focus_frequency_hz / 1e9, 0, focus=True
                )
            previous, lane = -np.inf, 0
            for group in groups:
                frequency = float(np.mean([row.raw_frequency_hz for row in group])) / 1e9
                lane = (lane + 1) % 4 if frequency - previous < 0.55 else 0
                label = ",".join(
                    {"matrix_pencil": "mp", "clutter_varpro": "clutter_vp"}.get(
                        row.estimator, row.estimator
                    )
                    + (f"#{row.native_rank}" if row.native_rank > 1 else "")
                    for row in group
                )
                self._add_badge(label, frequency, lane)
                previous = frequency
        else:
            self.plot_widget.autoRange()
        self.plot_widget.setXRange(0, display_fmax / 1e9, padding=0)
        self._position_badges()


def legend_widget() -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(4, 0, 4, 0)
    for text, color in (
        ("● G∩S / 已选", "#245b82"),
        ("◇ G无S", "#d97706"),
        ("○/× 未选C", "#64748b"),
        ("+ S无G", "#0284c7"),
    ):
        label = QLabel(text)
        label.setStyleSheet(f"color:{color};font-size:11px;")
        layout.addWidget(label)
    layout.addStretch()
    return widget
