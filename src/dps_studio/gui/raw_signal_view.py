"""PyQtGraph view of immutable raw time-voltage records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dps_studio.core.models import SignalRecord


class RawSignalView(QWidget):
    """Plot one or two channels with display-only μs and mV conversion."""

    cursor_position_changed = Signal(float, float, str)
    channel_selection_changed = Signal(str)
    analysis_region_changed = Signal(float, float)
    analysis_boundary_hovered = Signal(bool)

    _COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: Mapping[str, SignalRecord] = {}
        self._curves: dict[str, Any] = {}
        self._data_bounds_s: tuple[float, float] | None = None
        self._boundary_hovered = False

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(self.tr("显示通道")))
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("rawChannelSelector")
        self.channel_combo.addItem(self.tr("全部通道"), "__all__")
        self.channel_combo.setEnabled(False)
        self.channel_combo.currentIndexChanged.connect(self._update_visible_curves)
        controls.addWidget(self.channel_combo)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("rawSignalPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("电压"), units="mV")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.22)
        self.plot_widget.addLegend(offset=(12, 12))
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.analysis_region = pg.LinearRegionItem(
            orientation=pg.LinearRegionItem.Vertical,
            brush=pg.mkBrush(11, 111, 164, 35),
            pen=pg.mkPen("#0b6fa4", width=1.0),
            hoverPen=pg.mkPen("#d55e00", width=4.0),
            movable=True,
        )
        self.analysis_region.setObjectName("analysisTimeRegion")
        self.analysis_region.setZValue(20)
        self.analysis_region.setVisible(False)
        self.analysis_region.sigRegionChanged.connect(self._on_region_changed)
        boundary_tooltip = self.tr("拖动以调整分析范围")
        for line in self.analysis_region.lines:
            line.setCursor(Qt.CursorShape.SizeHorCursor)
            line.setToolTip(boundary_tooltip)
            line.addMarker("<|>", position=0.94, size=6.0)
        self.plot_widget.addItem(self.analysis_region)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        layout.addWidget(self.plot_widget, 1)

    def set_records(self, records: Mapping[str, SignalRecord]) -> None:
        """Display records without mutating, smoothing, or combining them."""
        self._records = records
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(12, 12))
        self.plot_widget.addItem(self.analysis_region)
        self._curves.clear()
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        self.channel_combo.addItem(self.tr("全部通道"), "__all__")
        for index, (channel_name, record) in enumerate(records.items()):
            curve = self.plot_widget.plot(
                record.time_s * 1e6,
                record.voltage_v * 1e3,
                pen=pg.mkPen(self._COLORS[index % len(self._COLORS)], width=1.0),
                name=channel_name,
                connect="finite",
            )
            self._curves[channel_name] = curve
            self.channel_combo.addItem(channel_name, channel_name)
        self.channel_combo.setCurrentIndex(0)
        self.channel_combo.setEnabled(bool(records))
        self.channel_combo.blockSignals(False)
        self.plot_widget.autoRange()
        if records:
            start_time_s = max(record.start_time_s for record in records.values())
            end_time_s = min(record.end_time_s for record in records.values())
            if start_time_s >= end_time_s:
                raise ValueError("Loaded channels do not share a common time range.")
            self._data_bounds_s = float(start_time_s), float(end_time_s)
            self.analysis_region.setBounds(
                (start_time_s * 1e6, end_time_s * 1e6)
            )
            self.set_analysis_region_s(start_time_s, end_time_s)
            self.analysis_region.setVisible(True)
            self.plot_widget.setXRange(
                start_time_s * 1e6,
                end_time_s * 1e6,
                padding=0.02,
            )
        else:
            self._data_bounds_s = None
            self.analysis_region.setVisible(False)
        self._emit_channel_selection()

    def set_analysis_region_s(self, start_time_s: float, end_time_s: float) -> None:
        """Set the graphical draft using SI seconds."""
        if self._data_bounds_s is None:
            return
        lower, upper = self._data_bounds_s
        start = max(lower, min(float(start_time_s), upper))
        end = max(lower, min(float(end_time_s), upper))
        if start >= end:
            return
        self.analysis_region.blockSignals(True)
        self.analysis_region.setRegion((start * 1e6, end * 1e6))
        self.analysis_region.blockSignals(False)

    def current_view_range_s(self) -> tuple[float, float]:
        """Return the visible x range, clamped to the full data bounds."""
        if self._data_bounds_s is None:
            raise RuntimeError("No data are loaded.")
        visible_us = self.plot_widget.plotItem.vb.viewRange()[0]
        lower, upper = self._data_bounds_s
        start = max(lower, float(visible_us[0]) * 1e-6)
        end = min(upper, float(visible_us[1]) * 1e-6)
        if start >= end:
            return self._data_bounds_s
        return start, end

    def _update_visible_curves(self, _index: int) -> None:
        selected = str(self.channel_combo.currentData())
        for channel_name, curve in self._curves.items():
            curve.setVisible(selected == "__all__" or selected == channel_name)
        self._emit_channel_selection()

    def _emit_channel_selection(self) -> None:
        selected = str(self.channel_combo.currentData())
        label = self.tr("全部通道") if selected == "__all__" else selected
        self.channel_selection_changed.emit(label)

    def _on_mouse_moved(self, position: object) -> None:
        self._update_boundary_hover_state(position)
        if not self._records:
            return
        point = self.plot_widget.plotItem.vb.mapSceneToView(position)
        selected = str(self.channel_combo.currentData())
        channel_name = (
            next(iter(self._records)) if selected == "__all__" else selected
        )
        self.cursor_position_changed.emit(
            float(point.x()) * 1e-6,
            float(point.y()) * 1e-3,
            channel_name,
        )

    def _update_boundary_hover_state(self, scene_position: object) -> None:
        """Use each native InfiniteLine hit shape to report boundary proximity."""
        hovered = False
        if self.analysis_region.isVisible():
            for line in self.analysis_region.lines:
                local_position = line.mapFromScene(scene_position)
                if line.boundingRect().contains(local_position):
                    hovered = True
                    break
        if hovered == self._boundary_hovered:
            return
        self._boundary_hovered = hovered
        self.analysis_boundary_hovered.emit(hovered)

    def _on_region_changed(self) -> None:
        if self._data_bounds_s is None:
            return
        start_us, end_us = self.analysis_region.getRegion()
        lower, upper = self._data_bounds_s
        start = max(lower, float(start_us) * 1e-6)
        end = min(upper, float(end_us) * 1e-6)
        if start < end:
            self.analysis_region_changed.emit(start, end)


__all__ = ["RawSignalView"]
