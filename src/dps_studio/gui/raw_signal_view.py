"""PyQtGraph view of immutable raw time-voltage records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dps_studio.core.models import SignalRecord


class RawSignalView(QWidget):
    """Plot one or two channels with display-only μs and mV conversion."""

    cursor_position_changed = Signal(float, float, str)
    channel_selection_changed = Signal(str)

    _COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: Mapping[str, SignalRecord] = {}
        self._curves: dict[str, Any] = {}

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
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        layout.addWidget(self.plot_widget, 1)

    def set_records(self, records: Mapping[str, SignalRecord]) -> None:
        """Display records without mutating, smoothing, or combining them."""
        self._records = records
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(12, 12))
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
        self.plot_widget.enableAutoRange()
        self._emit_channel_selection()

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


__all__ = ["RawSignalView"]
