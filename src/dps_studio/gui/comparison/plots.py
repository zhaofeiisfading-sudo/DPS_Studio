"""Linked time-frequency views, full tracks and original-voltage inspection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from dps_studio.core.stft_m4 import (
    DiffCategory,
    LocalComparisonWaveform,
    SpectrogramMap,
    StftM4ComparisonBundle,
    convert_frequency_for_display,
)
from dps_studio.core.stft_m4.waveform import Bool, Float

from .theme import AXIS_TEXT, COLORS, contrast_levels, spectrogram_lut

DIFFERENCES = (
    (DiffCategory.M4_ADDED_SUPPORTED, "新增有支持", "supported", "o"),
    (DiffCategory.M4_ADDED_AMBIGUOUS, "新增有争议", "ambiguous", "t"),
    (DiffCategory.BRANCH_DIFF_MINOR, "分歧 50–250", "minor", "d"),
    (DiffCategory.BRANCH_DIFF_MAJOR, "分歧 >250", "branch", "t1"),
    (DiffCategory.M4_DROPPED_WEAK, "拒收弱/缺证据", "weak", "s"),
    (DiffCategory.M4_DROPPED_STRONG_RISK, "疑似误伤", "risk", "x"),
)


class _ExactViewBox(pg.ViewBox):  # type: ignore[misc]
    def linkedViewChanged(self, view: Any, axis: int) -> None:  # noqa: N802
        # PyQtGraph's default aligns overlapping screen geometry by axis.
        # Copy both coordinates together even when notified on only one axis.
        if view is None or self.linksBlocked or view.linksBlocked:
            return
        x, y = view.viewRange()
        if self.viewRange() == [x, y]:
            return
        self.blockLink(True)
        try:
            self.setRange(xRange=x, yRange=y, padding=0)
        finally:
            self.blockLink(False)

def _plot(exact: bool = True) -> Any:
    view = _ExactViewBox() if exact else pg.ViewBox()
    plot = pg.PlotWidget(background="#ffffff", viewBox=view)
    plot.setMinimumSize(85, 42)
    plot.getPlotItem().setMenuEnabled(False)
    plot.hideButtons()
    plot.showGrid(x=True, y=True, alpha=.12)
    for side in ("left", "bottom"):
        axis = plot.getAxis(side)
        axis.setTextPen(AXIS_TEXT)
        axis.setPen("#a9bac9")
        axis.enableAutoSIPrefix(False)
    plot.getAxis("left").setWidth(70)
    plot.getAxis("bottom").setHeight(29)
    return plot


@dataclass(frozen=True, slots=True)
class Layers:
    final: bool = True
    rejected: bool = True
    candidates: bool = False
    secondary: bool = False
    matched: bool = False


class ComparisonPlots(QWidget):
    timeSelected = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.bundle: StftM4ComparisonBundle | None = None
        self._layout = "side"
        self._display = "overlay"
        self._contrast = "adaptive"
        self._background = "shared"
        self._layers = Layers()
        self.wavelength_m: float | None = None
        self._syncing = False
        self._selected_time_us: float | None = None
        self._categories = np.empty(0, dtype="U40")
        self._lut = spectrogram_lut()
        self._tracks: dict[Any, list[Any]] = {}
        self._range_initialized = False
        self.left_plot, self.right_plot, self.curve_plot = (_plot() for _ in range(3))
        self.linked_plots = (self.left_plot, self.right_plot, self.curve_plot)
        self.image_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.image_splitter.setChildrenCollapsible(False)
        self.left_title = QLabel("B1 · 512 点去均值 STFT")
        self.right_title = QLabel("M4 · 物理时长相位相干")
        self.right_title.setWordWrap(True)
        self.left_panel = self._section(self.left_title, self.left_plot)
        self.right_panel = self._section(self.right_title, self.right_plot)
        self.image_splitter.addWidget(self.left_panel)
        self.image_splitter.addWidget(self.right_panel)
        self.image_splitter.setStretchFactor(0, 1)
        self.image_splitter.setStretchFactor(1, 1)
        self.image_splitter.setSizes([600, 600])
        self.left_image, self.right_image = (pg.ImageItem(axisOrder="row-major") for _ in range(2))
        for plot, image in zip(self.linked_plots[:2], (self.left_image, self.right_image), strict=True):
            image.setLookupTable(self._lut)
            image.setZValue(-10)
            plot.addItem(image, ignoreBounds=True)
        self.legend = QLabel()
        self.legend.setStyleSheet("font-size:11px;color:#334155;padding:1px 3px;")
        self.color_scale = QLabel("共用 B1 色标")
        self.color_scale.setStyleSheet("font-size:11px;color:#405b70;padding:0 3px;")
        self.summary = QLabel("当前视野")
        self.summary.setStyleSheet("font-size:11px;color:#263746;padding:1px 3px;")
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(1)
        top_layout.addWidget(self.image_splitter, 1)
        top_layout.addWidget(self.color_scale)
        top_layout.addWidget(self.legend)
        self.middle = self._section(self.summary, self.curve_plot)
        self.sections = QSplitter(Qt.Orientation.Vertical)
        self.sections.setChildrenCollapsible(False)
        self.sections.addWidget(top)
        self.sections.addWidget(self.middle)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.sections)
        for plot in self.linked_plots:
            view = plot.getViewBox()
            view.disableAutoRange()
            if plot is not self.left_plot:
                plot.setXLink(self.left_plot)
                plot.setYLink(self.left_plot)
            view.sigRangeChanged.connect(self._sync_ranges)
            plot.scene().sigMouseClicked.connect(
                lambda event, source=plot: self._click(source, event)
            )
        self._cursors = [pg.InfiniteLine(angle=90, pen=pg.mkPen(COLORS["cursor"], width=1.4))
                         for _ in self.linked_plots]
        for plot, cursor in zip(self.linked_plots, self._cursors, strict=True):
            cursor.setZValue(30)
            plot.addItem(cursor, ignoreBounds=True)
            cursor.hide()
        self._render()

    @staticmethod
    def _section(title: QLabel, plot: QWidget) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(1)
        layout.addWidget(title)
        layout.addWidget(plot, 1)
        return panel

    def add_inspector(self, inspector: QWidget) -> None:
        self.sections.addWidget(inspector)
        self.sections.setStretchFactor(0, 45)
        self.sections.setStretchFactor(1, 22)
        self.sections.setStretchFactor(2, 33)
        self.sections.setSizes([290, 145, 218])

    def _sync_ranges(self, view: Any, _ranges: Any, _changed: Any) -> None:
        if self._syncing or view.linksBlocked:
            return
        self._syncing = True
        try:
            x, y = view.viewRange()
            for plot in self.linked_plots:
                other = plot.getViewBox()
                if other is not view and other.viewRange() != [x, y]:
                    other.setRange(xRange=x, yRange=y, padding=0)
        finally:
            self._syncing = False
        self._update_summary()

    def _click(self, plot: Any, event: Any) -> None:
        if (self.bundle is not None and event.button() == Qt.MouseButton.LeftButton
                and plot.getViewBox().sceneBoundingRect().contains(event.scenePos())):
            position = plot.getViewBox().mapSceneToView(event.scenePos())
            self.timeSelected.emit(float(position.x()) * 1e-6)

    def set_cursor(self, time_s: float | None) -> None:
        self._selected_time_us = None if time_s is None else time_s * 1e6
        for cursor in self._cursors:
            cursor.setVisible(time_s is not None)
            if self._selected_time_us is not None:
                cursor.setValue(self._selected_time_us)

    def _unit(self, values: Float) -> Float:
        return convert_frequency_for_display(values, confirmed_wavelength_m=self.wavelength_m)[0]

    def set_wavelength(self, wavelength_m: float | None) -> None:
        if self.wavelength_m == wavelength_m:
            return
        x, y = self.left_plot.viewRange()
        if self.wavelength_m is not None:
            y = [v / (self.wavelength_m * .5 * 1e9) for v in y]
        self.wavelength_m = wavelength_m
        if wavelength_m is not None:
            y = [v * (wavelength_m * .5 * 1e9) for v in y]
        self._render()
        if self._range_initialized:
            self.left_plot.setRange(xRange=x, yRange=y, padding=0)

    def set_bundle(self, bundle: StftM4ComparisonBundle | None) -> None:
        self.bundle = bundle
        self._categories = np.asarray(bundle.diff_categories if bundle else (), dtype="U40")
        self.set_cursor(None)
        self._render()
        self.reset_range()

    def set_options(self, layout: str, display: str, contrast: str,
                    background: str, layers: Layers) -> None:
        if layout != self._layout:
            self.image_splitter.setOrientation(
                Qt.Orientation.Vertical if layout == "stack" else Qt.Orientation.Horizontal
            )
            self.right_panel.setVisible(layout != "single")
            self.image_splitter.setSizes([600, 600])
        self._layout, self._display, self._contrast = layout, display, contrast
        self._background, self._layers = background, layers
        self._render()

    def reset_range(self) -> None:
        bundle = self.bundle
        self._range_initialized = bundle is not None and len(bundle.q) > 0
        if bundle is None or not len(bundle.q):
            return
        time = bundle.frame_time_s
        half = 64/bundle.sample_rate_hz
        y = self._unit(np.array([bundle.fmin_hz, bundle.fmax_hz]))
        self.left_plot.setRange(xRange=((time[0]-half)*1e6, (time[-1]+half)*1e6),
                                yRange=tuple(y), padding=0)

    def zoom(self, time_s: float, half_ns: float) -> None:
        self.left_plot.setXRange((time_s-half_ns*1e-9)*1e6, (time_s+half_ns*1e-9)*1e6,
                                 padding=0)

    def _raster(self, image: Any, raster: SpectrogramMap, levels: tuple[float, float]) -> None:
        if not raster.power_db.size or self.bundle is None:
            image.clear()
            return
        times = raster.time_s * 1e6
        dt = 128 / self.bundle.sample_rate_hz * 1e6
        y = self._unit(raster.frequency_hz)
        dy = float(np.diff(y)[0]) if len(y) > 1 else float(
            self._unit(np.array([self.bundle.sample_rate_hz/4096]))[0]
        )
        image.setImage(raster.power_db.T, autoLevels=False, levels=levels)
        image.setRect(QRectF(float(times[0]-dt/2), float(y[0]-dy/2), dt*len(times), dy*len(y)))

    def _render(self) -> None:
        bundle = self.bundle
        ylabel = "表观速度" if self.wavelength_m is not None else "频率"
        unit = "m/s" if self.wavelength_m is not None else "GHz"
        for plot in self.linked_plots:
            label = "速度" if plot is self.curve_plot and unit == "m/s" else ylabel
            plot.setLabel("left", label, units=unit, color=AXIS_TEXT)
            plot.setLabel("bottom", "时间", units="µs", color=AXIS_TEXT)
            for item in self._tracks.pop(plot, []):
                plot.removeItem(item)
            self._tracks[plot] = []
        self.left_title.setText("B1 · 512 点去均值 STFT" if self._layout != "single"
                                else "B1 共用时频底图 · B1 / M4 叠加")
        self.right_title.setText("M4 · 物理时长相位相干")
        legend = [
            ("b1", "━ B1"), ("m4", "━ M4"), ("matched", "━ 25.6 ns STFT"),
            ("secondary", "◆ M4 次支路"), ("supported", "● 新增有支持"),
            ("branch", "▲ 分歧 >250 MHz"), ("risk", "× 疑似误伤"), ("weak", "× 被拒点"),
        ]
        self.legend.setText("　".join(f'<span style="color:{COLORS[k]}">{label}</span>'
                                    for k, label in legend))
        if bundle is None:
            self.left_image.clear()
            self.right_image.clear()
            self.color_scale.setText("共用 B1 色标")
            self._update_summary()
            return
        raster = bundle.b1_spectrogram
        levels = contrast_levels(raster.power_db, self._contrast)
        self._raster(self.left_image, raster, levels)
        alternate = bundle.m4_coherent_map if self._background == "coherent" else None
        if alternate is None or self._layout == "single":
            self._raster(self.right_image, raster, levels)
            self.color_scale.setText(f"共用 B1 色标  {levels[0]:.1f} 至 {levels[1]:.1f} dB")
        else:
            other = contrast_levels(alternate.power_db, self._contrast)
            self._raster(self.right_image, alternate, other)
            self.right_title.setText("右底图 · M4 多尺度白化相干功率（独立量纲）")
            self.color_scale.setText(f"B1 色标  {levels[0]:.1f} 至 {levels[1]:.1f} dB"
                                     f"　　M4 白化响应  {other[0]:.1f} 至 {other[1]:.1f} dB")
        draw_b1, draw_m4 = self._display != "m4", self._display != "b1"
        for plot in self.linked_plots:
            both = plot is self.curve_plot or self._layout == "single"
            self._draw_tracks(plot, draw_b1 and (both or plot is self.left_plot),
                              draw_m4 and (both or plot is self.right_plot))
        self._update_summary()

    def _draw_tracks(self, plot: Any, b1: bool, m4: bool) -> None:
        bundle = self.bundle
        if bundle is None:
            return
        x = bundle.frame_time_s * 1e6
        layers = self._layers

        def draw(data: Float, color: str, *, line: bool = False, symbol: str = "o",
                 size: int = 4, pale: bool = False) -> None:
            y = self._unit(data)
            if not line:
                ok = np.isfinite(y)
                tx, y = x[ok], y[ok]
            else:
                tx = x
            if not len(tx):
                return
            stroke = COLORS[color]
            edge = "#0f172a" if pale and plot is self.curve_plot else stroke
            item = pg.PlotDataItem(
                tx, y, connect="finite", pen=pg.mkPen(stroke, width=1.6) if line else None,
                symbol=symbol, symbolSize=size, symbolPen=pg.mkPen(edge, width=1),
                symbolBrush=None if pale else pg.mkBrush(stroke),
            )
            plot.addItem(item, ignoreBounds=True)
            self._tracks[plot].append(item)

        if self._display == "difference":
            main = plot is self.curve_plot
            y0, y1 = self._unit(np.array([bundle.fmin_hz, bundle.fmax_hz]))
            for category, _, color, symbol in DIFFERENCES:
                mask = self._categories == category.value
                if main and mask.any():
                    shade = pg.mkColor(COLORS[color])
                    shade.setAlpha(24)
                    bar = pg.BarGraphItem(x=x[mask], width=128e6/bundle.sample_rate_hz,
                                          y0=y0, y1=y1, pen=None, brush=shade)
                    bar.setZValue(-5)
                    plot.addItem(bar, ignoreBounds=True)
                    self._tracks[plot].append(bar)
                if b1:
                    draw(np.where(mask, bundle.b1.accepted_hz, np.nan), color,
                         symbol=symbol, size=7)
                if m4:
                    draw(np.where(mask, bundle.m4.accepted_hz, np.nan), color,
                         symbol=symbol, size=7)
        for visible, key, estimate in ((b1, "b1", bundle.b1), (m4, "m4", bundle.m4)):
            if not visible:
                continue
            if layers.final:
                draw(estimate.accepted_hz, key, line=True, size=3)
            if layers.rejected:
                draw(np.where(estimate.rejected_mask, estimate.candidate_hz, np.nan),
                     "rejected" if plot is not self.curve_plot else key,
                     symbol="x", size=7, pale=True)
            if layers.candidates:
                draw(estimate.candidate_hz, key, size=3, pale=True)
        if m4 and layers.secondary:
            draw(bundle.m4.secondary_hz, "secondary", symbol="d", size=5)
        if layers.matched and bundle.matched_stft is not None:
            draw(bundle.matched_stft.accepted_hz, "matched", line=True, size=2)

    def _update_summary(self) -> None:
        bundle = self.bundle
        if bundle is None:
            self.summary.setText("当前视野")
            return
        x = bundle.frame_time_s * 1e6
        low, high = self.curve_plot.viewRange()[0]
        visible: Bool = (x >= low) & (x <= high)
        ylo, yhi = self.curve_plot.viewRange()[1]
        a, b = (self._unit(bundle.b1.accepted_hz), self._unit(bundle.m4.accepted_hz))
        visible &= ((a >= ylo) & (a <= yhi)) | ((b >= ylo) & (b <= yhi))

        def count(*cats: DiffCategory) -> int:
            return int(np.count_nonzero(visible & np.isin(self._categories, [c.value for c in cats])))

        agreed = count(DiffCategory.BOTH_AGREE)
        added = count(DiffCategory.M4_ADDED_SUPPORTED)
        maybe = count(DiffCategory.M4_ADDED_AMBIGUOUS)
        branch = count(DiffCategory.BRANCH_DIFF_MINOR, DiffCategory.BRANCH_DIFF_MAJOR)
        risk = count(DiffCategory.M4_DROPPED_STRONG_RISK)
        weak = count(DiffCategory.M4_DROPPED_WEAK)
        self.summary.setText(
            f"当前视野  ·  一致 {agreed}  ·  新增支持 {added}  ·  新增争议/CW {maybe}"
            f"  ·  分歧 >50 MHz {branch}  ·  疑似误伤 {risk}  ·  拒收弱/缺证据 {weak}"
        )


class WaveformPlot(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.plot = _plot(exact=False)
        self.plot.setLabel("bottom", "距所选帧", units="ns", color=AXIS_TEXT)
        self.plot.setLabel("left", "电压", units="V", color=AXIS_TEXT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

    def show_frame(self, waveform: LocalComparisonWaveform | None, *, raw: bool) -> None:
        self.plot.clear()
        if waveform is None:
            return
        center = waveform.center_time_s
        x = (waveform.time_s-center)*1e9
        if raw:
            self.plot.plot(x, waveform.voltage_v, pen=pg.mkPen(COLORS["raw_voltage"], width=1))
            self.plot.plot(x, waveform.baseline_v,
                           pen=pg.mkPen(COLORS["baseline"], style=Qt.PenStyle.DashLine))
            self.plot.plot((waveform.rail_time_s-center)*1e9, waveform.rail_voltage_v,
                           pen=None, symbol="o", symbolSize=4, symbolBrush=COLORS["rail"])
            for times, key in ((waveform.dc_step_time_s, "dc_step"),
                               (waveform.rail_exit_time_s, "rail")):
                for time_s in times:
                    self.plot.addItem(pg.InfiniteLine(
                        (time_s-center)*1e9, pen=pg.mkPen(COLORS[key], style=Qt.PenStyle.DashLine),
                    ))
        else:
            bounds = [(t-center)*1e9 for t in waveform.fit_window_s]
            window = pg.LinearRegionItem(bounds, movable=False, brush=(186, 230, 253, 110))
            window.setZValue(-8)
            self.plot.addItem(window, ignoreBounds=True)
            self.plot.plot(x, waveform.residual_v, pen=pg.mkPen(COLORS["residual"], width=1))
            short = (waveform.fit_time_s-center)*1e9
            for data, key, point in ((waveform.b1_fit_v, "b1", waveform.b1),
                                     (waveform.m4_fit_v, "m4", waveform.m4)):
                style = (Qt.PenStyle.SolidLine if np.isfinite(point.accepted_hz)
                         else Qt.PenStyle.DashLine)
                self.plot.plot(short, data, connect="finite",
                               pen=pg.mkPen(COLORS[key], width=1.6, style=style))
        self.plot.setXRange(-16., 16., padding=0)
        self.plot.enableAutoRange(axis="y")
