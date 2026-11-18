"""Shared presentation and pointer readouts for scientific plots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QSize, Qt, Slot
from PySide6.QtGui import QColor, QFont, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QStyle, QStyleOptionComboBox, QToolButton,
    QVBoxLayout, QWidget,
)
from shiboken6 import Shiboken

from dps_studio.gui.icons import vector_icon


def style_plot_widget(plot_widget: Any, *, grid_alpha: float = 0.16) -> None:
    plot_widget.setBackground("#ffffff")
    font = QFont(plot_widget.font())
    font.setPointSize(9)
    for name in ("bottom", "left"):
        axis = plot_widget.getAxis(name)
        axis.setPen("#475569")
        axis.setTextPen("#475569")
        axis.setStyle(tickFont=font)
    plot_widget.showGrid(x=True, y=True, alpha=grid_alpha)


def create_plot_toolbar() -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    row.setContentsMargins(6, 3, 6, 3)
    return row


class PlotSelector(QComboBox):
    """Keep both ends of long channel names visible in a narrow plot header."""

    def __init__(self, compact_names: dict[str, str] | None = None) -> None:
        self._compact_names = compact_names or {}
        super().__init__()
        self.setMinimumWidth(32)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.currentTextChanged.connect(self.setToolTip)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        option = QStyleOptionComboBox()
        super().initStyleOption(option)
        option.rect = QRect(0, 0, hint.width(), hint.height())
        chrome = hint.width() - self._edit_field(option).width()
        metrics = self.fontMetrics()
        text_width = max((metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        hint.setWidth(max(hint.width(), text_width + chrome + 2))
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setWidth(min(64, hint.width()))
        return hint

    def _edit_field(self, option: QStyleOptionComboBox) -> QRect:
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, self,
        )

    def initStyleOption(self, option: QStyleOptionComboBox) -> None:  # noqa: N802
        super().initStyleOption(option)
        caption = option.currentText
        metrics = self.fontMetrics()
        width = self._edit_field(option).width()
        if metrics.horizontalAdvance(caption) > width:
            caption = self._compact_names.get(self.currentData(), caption)
            option.currentText = metrics.elidedText(caption, Qt.TextElideMode.ElideMiddle, max(0, width))


class _HudReadout(QLabel):
    def __init__(self, sample: str) -> None:
        super().__init__("—")
        self.setProperty("role", "hudReadout")
        self._sample = sample
        self._text = "—"
        self._tight = False
        self._wrapped = False

    def required_width(self, *, tight: bool, wrapped: bool = False) -> int:
        sample = self._format(self._sample, tight=tight, wrapped=wrapped)
        return max(self.fontMetrics().horizontalAdvance(line) for line in sample.splitlines()) + 10

    def adapt(self, *, tight: bool, wrapped: bool) -> None:
        self._tight, self._wrapped = tight, wrapped
        metrics = self.fontMetrics()
        # Reserve the readout even before hover so pointer motion never resizes the plot.
        self.setFixedWidth(self.required_width(tight=tight, wrapped=wrapped))
        self.setFixedHeight(metrics.lineSpacing() * (2 if wrapped else 1) + 7)
        self.show_coordinates(self._text)

    @staticmethod
    def _format(text: str, *, tight: bool, wrapped: bool) -> str:
        if tight:
            text = text.replace(" = ", "=")
        return text.replace(" · ", "\n") if wrapped else text

    def show_coordinates(self, text: str) -> None:
        self._text = text
        self.setText(self._format(text, tight=self._tight, wrapped=self._wrapped))


class PlotActionButton(QToolButton):
    """Preserve the action name for accessibility and compact icon-only presentation."""

    def __init__(self, title: str, icon: str, *, show_icon: bool = False) -> None:
        super().__init__()
        self.setProperty("plotAction", True)
        self.setText(title)
        self.setToolTip(title)
        self.setAccessibleName(title)
        self.setIcon(vector_icon(icon))
        self.setIconSize(QSize(14, 14))
        self.full_style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon if show_icon
                           else Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setToolButtonStyle(self.full_style)

    def full_width(self) -> int:
        if self.toolButtonStyle() == self.full_style:
            return self.sizeHint().width()
        metrics = self.fontMetrics()
        text_width = metrics.size(Qt.TextFlag.TextShowMnemonic, self.text()).width()
        width = self.sizeHint().width() + text_width + 2 * metrics.horizontalAdvance(" ")
        return width + (4 if self.full_style == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                        else -self.iconSize().width())


class _PlotToolbar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("plotToolbar", True)
        self.normal_spacing = 6

    def _adapt(self) -> None:
        row = self.layout()
        if row is None:
            return
        widgets = self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
        widths = []
        caption_width = 0
        caption_count = 0
        readout_saving = 0
        for widget in widgets:
            if isinstance(widget, QLabel) and widget.property("role") is None:
                caption_width += widget.sizeHint().width()
                caption_count += 1
            elif widget.isHidden():
                continue
            elif isinstance(widget, PlotActionButton):
                widths.append(widget.full_width())
            elif isinstance(widget, _HudReadout):
                widths.append(widget.required_width(tight=False))
                readout_saving = widths[-1] - widget.required_width(tight=True)
            elif isinstance(widget, QCheckBox) and widget.property("fullCaption"):
                widths.append(widget.fontMetrics().horizontalAdvance(str(widget.property("fullCaption"))) + 46)
            else:
                widths.append(widget.sizeHint().width())
        margins = row.contentsMargins()
        gaps = max(0, len(widths) + caption_count - 1)
        content_width = sum(widths) + caption_width + margins.left() + margins.right()
        tight = self.width() < content_width + gaps * self.normal_spacing
        tight_spacing = 2
        tight_width = content_width - readout_saving + gaps * tight_spacing
        hide_captions = self.width() < tight_width
        compact = self.width() < tight_width - caption_width - caption_count * tight_spacing
        row.setSpacing(tight_spacing if tight else self.normal_spacing)
        for widget in widgets:
            if isinstance(widget, PlotActionButton):
                widget.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if compact
                                          else widget.full_style)
            elif isinstance(widget, _HudReadout):
                widget.adapt(tight=tight, wrapped=compact)
            elif isinstance(widget, QLabel) and widget.property("role") is None:
                widget.setVisible(not hide_captions)
            elif isinstance(widget, QCheckBox) and widget.property("fullCaption"):
                widget.setText("" if compact else str(widget.property("fullCaption")))

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest:
            self._adapt()
        return super().event(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._adapt()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._adapt()


def add_plot_toolbar(layout: QVBoxLayout, *, spacing: int = 6) -> QHBoxLayout:
    strip = _PlotToolbar()
    strip.normal_spacing = spacing
    row = create_plot_toolbar()
    row.setSpacing(spacing)
    strip.setLayout(row)
    layout.addWidget(strip)
    return row


class PlotCrosshairHud(QObject):
    """Passive scene indicators. Plot coordinates stay in displayed axis units."""

    def __init__(
        self, plot_widget: Any, formatter: Callable[[float, float], str],
        *, width_sample: str = "t = -123.456 μs · v = -123.45 m/s",
    ) -> None:
        super().__init__(plot_widget)
        self._plot = plot_widget
        self._formatter = formatter
        self.crosshair_readout_label = _HudReadout(width_sample)
        color = QColor("#64748b")
        color.setAlpha(110)
        pen = pg.mkPen(color, width=1.0, style=Qt.PenStyle.DashLine)
        self.lines = tuple(pg.InfiniteLine(angle=angle, movable=False, pen=pen) for angle in (90, 0))
        for line in self.lines:
            line.setZValue(50)
            line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            line.setAcceptHoverEvents(False)
        self.reinstall()
        plot_widget.scene().sigMouseMoved.connect(self._move)
        plot_widget.viewport().installEventFilter(self)

    def reinstall(self) -> None:
        self.clear()
        for line in self.lines:
            if line not in self._plot.plotItem.items:
                self._plot.addItem(line, ignoreBounds=True)

    def clear(self) -> None:
        for line in self.lines:
            line.hide()
        self.crosshair_readout_label.show_coordinates("—")

    @Slot(QPointF)
    def _move(self, position: QPointF) -> None:
        view = self._plot.getViewBox()
        if not view.sceneBoundingRect().contains(position):
            self.clear()
            return
        point = view.mapSceneToView(position)
        for line, value in zip(self.lines, (point.x(), point.y()), strict=True):
            line.setValue(value)
            line.show()
        self.crosshair_readout_label.show_coordinates(self._formatter(point.x(), point.y()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() in (QEvent.Type.Leave, QEvent.Type.Hide)
                and Shiboken.isValid(self.crosshair_readout_label)
                and all(Shiboken.isValid(line) for line in self.lines)):
            self.clear()
        return False
