"""PyQtGraph view of immutable raw time-voltage records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget,
)

from dps_studio.core.models import SignalRecord
from dps_studio.gui.icons import vector_icon
from dps_studio.gui.plot_chrome import (
    PlotActionButton, PlotCrosshairHud, PlotSelector, add_plot_toolbar, style_plot_widget,
)


class _RawCurve(pg.PlotDataItem):  # type: ignore[misc]
    """Clip painting to the viewport while exposing every original display-unit sample."""

    def getData(self) -> tuple[Any, Any]:  # noqa: N802 - pyqtgraph API
        return cast(tuple[Any, Any], self.getOriginalDataset())


class RawSignalView(QWidget):
    """Plot loaded channels with display-only μs and mV conversion."""

    open_data_requested = Signal()
    cursor_position_changed = Signal(float, float, str)
    channel_selection_changed = Signal(str)
    analysis_region_changed = Signal(float, float)
    analysis_region_committed = Signal(float, float)
    analysis_boundary_hovered = Signal(bool)

    _COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: Mapping[str, SignalRecord] = {}
        self._curves: dict[str, Any] = {}
        self._data_bounds_s: tuple[float, float] | None = None
        self._boundary_hovered = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 6, 7, 5)
        controls = add_plot_toolbar(layout, spacing=8)
        controls.setContentsMargins(8, 6, 8, 4)
        controls.addWidget(QLabel(self.tr("显示通道")))
        self.channel_combo = PlotSelector()
        self.channel_combo.setObjectName("rawChannelSelector")
        self.channel_combo.addItem(self.tr("全部通道"), "__all__")
        self.channel_combo.setEnabled(False)
        self.channel_combo.currentIndexChanged.connect(self._update_visible_curves)
        controls.addWidget(self.channel_combo)
        fit_button = PlotActionButton(self.tr("全部波形"), "fit_view", show_icon=True)
        fit_button.clicked.connect(self._fit_waveform)
        controls.addWidget(fit_button)
        controls.addStretch(1)
        self.dataset_badge = QLabel()
        self.dataset_badge.setProperty("role", "badge")
        self.dataset_badge.hide()
        controls.addWidget(self.dataset_badge)

        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("rawSignalPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("电压"), units="mV")
        style_plot_widget(self.plot_widget)
        self.hud = PlotCrosshairHud(self.plot_widget, lambda x, y: f"t = {x:.6g} μs · V = {y:.5g} mV")
        self.crosshair_readout_label = self.hud.crosshair_readout_label
        controls.addWidget(self.crosshair_readout_label)
        self.plot_widget.addLegend(offset=(12, 12))
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.setToolTip(self.tr("滚轮缩放，拖动平移；蓝色边界限定分析范围。"))
        self.analysis_region = pg.LinearRegionItem(
            orientation=pg.LinearRegionItem.Vertical,
            brush=pg.mkBrush(11, 111, 164, 15),
            pen=pg.mkPen("#0b6fa4", width=1.0),
            hoverPen=pg.mkPen("#d55e00", width=4.0),
            movable=True,
        )
        self.analysis_region.setObjectName("analysisTimeRegion")
        self.analysis_region.setZValue(20)
        self.analysis_region.setVisible(False)
        self.analysis_region.sigRegionChanged.connect(self._on_region_changed)
        self.analysis_region.sigRegionChangeFinished.connect(
            self._on_region_change_finished
        )
        boundary_tooltip = self.tr("拖动以调整分析范围")
        for line in self.analysis_region.lines:
            line.setCursor(Qt.CursorShape.SizeHorCursor)
            line.setToolTip(boundary_tooltip)
            line.addMarker("<|>", position=0.94, size=6.0)
        self.plot_widget.addItem(self.analysis_region)
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self.plot_widget)
        self.empty_state_overlay = QWidget()
        self.empty_state_overlay.setObjectName("rawWelcomeOverlay")
        center = QVBoxLayout(self.empty_state_overlay)
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card = QFrame()
        card.setMaximumWidth(480)
        card.setProperty("welcomeCard", True)
        content = QVBoxLayout(card)
        content.setContentsMargins(18, 16, 18, 16)
        content.setSpacing(8)
        emblem = QLabel()
        emblem.setPixmap(vector_icon("waveform", "#0f5c8a").pixmap(32, 32))
        title = QLabel(self.tr("导入 PDV 原始波形"))
        title.setObjectName("rawWelcomeTitle")
        subtitle = QLabel(self.tr("支持 CSV / DAT / TXT 分隔文本 · 可将文件直接拖拽到窗口"))
        subtitle.setWordWrap(True)
        for label in (emblem, title, subtitle):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content.addWidget(label)
        self.welcome_open_button = QPushButton(self.tr("选择并导入数据…"))
        self.welcome_open_button.setProperty("variant", "primary")
        self.welcome_open_button.clicked.connect(self.open_data_requested)
        content.addWidget(self.welcome_open_button, 0, Qt.AlignmentFlag.AlignHCenter)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        for step in (self.tr("① 列与单位"), self.tr("② 时频与频带"),
                     self.tr("③ 脊线与速度/加速度"), self.tr("④ 复核与导出")):
            chip = QLabel(step)
            chip.setProperty("role", "workflowChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setWordWrap(True)
            chips.addWidget(chip)
        content.addLayout(chips)
        center.addWidget(card)
        stack.addWidget(self.empty_state_overlay)
        stack.setCurrentWidget(self.empty_state_overlay)
        layout.addLayout(stack, 1)

    def _fit_waveform(self) -> None:
        self.plot_widget.autoRange()

    def set_records(self, records: Mapping[str, SignalRecord]) -> None:
        """Display records without mutating, smoothing, or combining them."""
        self._records = records
        self.empty_state_overlay.setVisible(not records)
        self.dataset_badge.setVisible(bool(records))
        self.plot_widget.clear()
        self.hud.reinstall()
        self.plot_widget.addLegend(offset=(12, 12))
        self.plot_widget.addItem(self.analysis_region)
        self._curves.clear()
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        self.channel_combo.addItem(self.tr("全部通道"), "__all__")
        for index, (channel_name, record) in enumerate(records.items()):
            curve = _RawCurve(
                record.time_s * 1e6,
                record.voltage_v * 1e3,
                pen=pg.mkPen(self._COLORS[index % len(self._COLORS)], width=1.0),
                name=channel_name,
                connect="finite",
            )
            self.plot_widget.addItem(curve)
            curve.setClipToView(True)
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
        if self._records:
            records = self._records.values() if selected == "__all__" else (self._records[selected],)
            summaries = dict.fromkeys(self.tr("{count:,} 点 · {rate:g} GS/s").format(
                count=record.time_s.size, rate=record.sample_rate_hz / 1e9,
            ) for record in records)
            self.dataset_badge.setText(" / ".join(summaries))
        label = self.tr("全部通道") if selected == "__all__" else selected
        self.channel_selection_changed.emit(label)

    def _on_mouse_moved(self, position: object) -> None:
        self._update_boundary_hover_state(position)
        if not self._records or not self.plot_widget.getViewBox().sceneBoundingRect().contains(position):
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
        region = self._current_region_s()
        if region is not None:
            self.analysis_region_changed.emit(*region)

    def _on_region_change_finished(self) -> None:
        region = self._current_region_s()
        if region is not None:
            self.analysis_region_committed.emit(*region)

    def _current_region_s(self) -> tuple[float, float] | None:
        if self._data_bounds_s is None:
            return None
        start_us, end_us = self.analysis_region.getRegion()
        lower, upper = self._data_bounds_s
        start = max(lower, float(start_us) * 1e-6)
        end = min(upper, float(end_us) * 1e-6)
        if start < end:
            return start, end
        return None


__all__ = ["RawSignalView"]
