"""PyQtGraph editing for a channel-local manual frequency search region."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal

from dps_studio.core.ridge import (
    ManualFrequencyBoundary,
    ManualFrequencyRegion,
    RidgeConfigurationError,
    RidgeCorridorConstraint,
    RidgeSearchConstraint,
    evaluate_manual_frequency_region_bounds,
)
from dps_studio.core.time_frequency import STFTResult


BoundaryKind = Literal["upper", "lower"]

# Both editable and result views use this compact, theme-safe overlay palette.
# The fill intentionally remains very transparent so the spectrum stays legible.
_UPPER_COLOR = "#D55E00"
_LOWER_COLOR = "#0072B2"
_INVALID_COLOR = "#D62728"
_ALLOWED_FILL_RGBA = (0, 114, 178, 50)


class RidgeCorridorController(QObject):
    """Edit optional upper/lower search boundaries in physical coordinates.

    The historical class name is retained to avoid a broad internal rename of
    Guided session wiring. New constraints are always ``ManualFrequencyRegion``.
    """

    constraint_changed = Signal(str, object)
    constraint_cleared = Signal(str)
    drawing_state_changed = Signal(bool)
    message = Signal(str)

    def __init__(self, plot_widget: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plot_widget = plot_widget
        self._stft_result: STFTResult | None = None
        self._analysis_start_time_s: float | None = None
        self._analysis_end_time_s: float | None = None
        self._minimum_frequency_hz: float | None = None
        self._maximum_frequency_hz: float | None = None
        self._channel_name: str | None = None
        self._constraint: RidgeSearchConstraint | None = None
        self._constraint_before_drawing: RidgeSearchConstraint | None = None
        self._drawing = False
        self._active_boundary: BoundaryKind | None = None
        self._last_edited_boundary: BoundaryKind = "upper"
        self._draft_points: list[tuple[float, float]] = []
        self._invalid_draft = False
        self._draft_curve: Any | None = None
        self._boundary_rois: dict[BoundaryKind, Any] = {}
        self._roi: Any | None = None  # compatibility alias for earlier tests
        self._upper_curve: Any | None = None
        self._lower_curve: Any | None = None
        self._fill_item: Any | None = None
        self._updating_roi = False
        self._manual_region_visible = True
        self._plot_widget.scene().sigMouseClicked.connect(self._scene_clicked)

    @property
    def drawing(self) -> bool:
        return self._drawing

    @property
    def active_boundary(self) -> BoundaryKind | None:
        return self._active_boundary

    @property
    def invalid_draft(self) -> bool:
        return self._invalid_draft

    @property
    def constraint(self) -> RidgeSearchConstraint | None:
        return self._constraint

    @property
    def channel_name(self) -> str | None:
        return self._channel_name

    @property
    def upper_point_count(self) -> int:
        boundary = self._manual_region().upper_boundary
        if self._drawing and self._active_boundary == "upper":
            return len(self._draft_points)
        return 0 if boundary is None else boundary.control_point_count

    @property
    def lower_point_count(self) -> int:
        boundary = self._manual_region().lower_boundary
        if self._drawing and self._active_boundary == "lower":
            return len(self._draft_points)
        return 0 if boundary is None else boundary.control_point_count

    def set_context(
        self,
        channel_name: str,
        stft_result: STFTResult,
        constraint: RidgeSearchConstraint | None,
        *,
        analysis_start_time_s: float | None,
        analysis_end_time_s: float | None,
        minimum_frequency_hz: float | None = None,
        maximum_frequency_hz: float | None = None,
    ) -> None:
        """Attach physical axes and reconstruct the selected channel overlay."""
        self.cancel_drawing()
        self._remove_overlay()
        self._channel_name = channel_name
        self._stft_result = stft_result
        self._analysis_start_time_s = analysis_start_time_s
        self._analysis_end_time_s = analysis_end_time_s
        self._minimum_frequency_hz = (
            float(stft_result.frequency_hz[0])
            if minimum_frequency_hz is None
            else float(minimum_frequency_hz)
        )
        self._maximum_frequency_hz = (
            float(stft_result.frequency_hz[-1])
            if maximum_frequency_hz is None
            else float(maximum_frequency_hz)
        )
        self._constraint = constraint
        self._install_overlay()

    def detach_context(self) -> None:
        """Detach a cleared plot without emitting a scientific state change."""
        self.cancel_drawing()
        self._remove_overlay()
        self._stft_result = None
        self._analysis_start_time_s = None
        self._analysis_end_time_s = None
        self._minimum_frequency_hz = None
        self._maximum_frequency_hz = None
        self._channel_name = None
        self._constraint = None

    def set_manual_region_visible(self, visible: bool) -> None:
        """Show the allowed-region overlay only while manual mode is selected."""
        self._manual_region_visible = bool(visible)
        for item in (
            self._fill_item,
            self._upper_curve,
            self._lower_curve,
            *self._boundary_rois.values(),
        ):
            if item is not None:
                item.setVisible(self._manual_region_visible)
        if self._draft_curve is not None:
            self._draft_curve.setVisible(self._manual_region_visible)

    def begin_boundary(self, boundary: BoundaryKind) -> bool:
        """Begin a replacement polyline for one boundary."""
        if boundary not in ("upper", "lower"):
            raise ValueError("boundary must be 'upper' or 'lower'.")
        if self._stft_result is None or self._channel_name is None:
            self.message.emit(self.tr("当前通道没有可绘制的 STFT。"))
            return False
        if self._drawing:
            if self._active_boundary == boundary:
                return self.finish_drawing()
            self.cancel_drawing()
        self._constraint_before_drawing = self._constraint
        self._drawing = True
        self._active_boundary = boundary
        self._last_edited_boundary = boundary
        self._draft_points = []
        self._invalid_draft = False
        self._draft_curve = pg.PlotDataItem(
            pen=pg.mkPen(self._boundary_color(boundary), width=1.8),
            symbol="o",
            symbolSize=7,
            symbolBrush=self._boundary_color(boundary),
        )
        self._draft_curve.setZValue(22)
        self._draft_curve.setVisible(self._manual_region_visible)
        self._plot_widget.addItem(self._draft_curve)
        self._plot_widget.setCursor(Qt.CursorShape.CrossCursor)
        self.drawing_state_changed.emit(True)
        label = self.tr("上边界") if boundary == "upper" else self.tr("下边界")
        self.message.emit(
            self.tr("正在编辑{boundary}：请从左到右添加控制点。").format(
                boundary=label
            )
        )
        return True

    def finish_drawing(self) -> bool:
        """Finish editing; a zero/one-point preview never becomes a boundary."""
        if not self._drawing:
            return False
        if self._invalid_draft:
            self.message.emit(
                self.tr("人工上下边界发生交叉，请调整后重新分析。")
            )
            return False
        if len(self._draft_points) < 2:
            self._restore_pre_edit_constraint()
            self._end_drawing_state()
            self.message.emit(self.tr("少于两个控制点：未形成正式人工边界。"))
            return True
        self._commit_live_draft()
        if self._invalid_draft:
            return False
        self._end_drawing_state()
        self.message.emit(self.tr("人工边界已保存。"))
        return True

    def cancel_drawing(self) -> None:
        """Exit edit mode and restore the last confirmed constraint."""
        if not self._drawing:
            self._plot_widget.unsetCursor()
            return
        self._restore_pre_edit_constraint()
        self._end_drawing_state()
        self.message.emit(self.tr("已退出编辑；此前确认的人工边界已保留。"))

    def undo_last_point(self) -> bool:
        """Remove the latest point from the active or last-edited boundary."""
        if self._drawing:
            if not self._draft_points:
                return False
            self._draft_points.pop()
            self._invalid_draft = False
            self._refresh_draft()
            if len(self._draft_points) >= 2:
                self._commit_live_draft()
            else:
                self._restore_pre_edit_constraint()
            return True
        region = self._manual_region()
        boundary = self._boundary_from_region(region, self._last_edited_boundary)
        if boundary is None:
            other: BoundaryKind = (
                "lower" if self._last_edited_boundary == "upper" else "upper"
            )
            boundary = self._boundary_from_region(region, other)
            if boundary is None:
                return False
            self._last_edited_boundary = other
        if boundary.control_point_count <= 2:
            return self._replace_manual_boundary(
                self._last_edited_boundary,
                None,
                emit_change=True,
            )
        shortened = ManualFrequencyBoundary(
            control_times_s=boundary.control_times_s[:-1],
            control_frequencies_hz=boundary.control_frequencies_hz[:-1],
        )
        return self._replace_manual_boundary(
            self._last_edited_boundary,
            shortened,
            emit_change=True,
        )

    def clear_constraint(self, *, emit_change: bool = True) -> bool:
        """Clear upper and lower boundaries without touching data or results."""
        had_constraint = self._constraint is not None
        channel_name = self._channel_name
        self._discard_drawing_state()
        self._constraint = None
        self._remove_overlay()
        self._install_overlay()
        if emit_change and channel_name is not None and had_constraint:
            self.constraint_cleared.emit(channel_name)
        self.message.emit(self.tr("人工范围已清除；当前使用完整搜索频带。"))
        return had_constraint

    def _scene_clicked(self, event: Any) -> None:
        if not self._drawing or self._stft_result is None:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        scene_position = event.scenePos()
        view_box = self._plot_widget.plotItem.vb
        if not view_box.sceneBoundingRect().contains(scene_position):
            return
        point = self._clamped_si_point(view_box.mapSceneToView(scene_position))
        if self._draft_points and point[0] <= self._draft_points[-1][0]:
            self.message.emit(self.tr("控制点需要按时间从左到右添加。"))
            return
        self._draft_points.append(point)
        self._refresh_draft()
        if len(self._draft_points) >= 2:
            self._commit_live_draft()
        if event.double():
            self.finish_drawing()

    def _commit_live_draft(self) -> None:
        if self._active_boundary is None or len(self._draft_points) < 2:
            return
        try:
            boundary = ManualFrequencyBoundary(
                control_times_s=np.array(
                    [point[0] for point in self._draft_points],
                    dtype=np.float64,
                ),
                control_frequencies_hz=np.array(
                    [point[1] for point in self._draft_points],
                    dtype=np.float64,
                ),
            )
        except RidgeConfigurationError:
            self._invalid_draft = True
            self._refresh_draft()
            self.drawing_state_changed.emit(True)
            self.message.emit(self.tr("控制点需要按时间从左到右添加。"))
            return
        try:
            region = self._region_with_boundary(
                self._base_region_for_draft(),
                self._active_boundary,
                boundary,
            )
        except RidgeConfigurationError:
            self._invalid_draft = True
            self._refresh_draft()
            self.message.emit(
                self.tr("人工上下边界发生交叉，请调整后重新分析。")
            )
            self.drawing_state_changed.emit(True)
            return
        self._invalid_draft = False
        self._refresh_draft()
        self._replace_constraint(region, emit_change=True)

    def _replace_manual_boundary(
        self,
        kind: BoundaryKind,
        boundary: ManualFrequencyBoundary | None,
        *,
        emit_change: bool,
    ) -> bool:
        try:
            updated = self._region_with_boundary(
                self._manual_region(),
                kind,
                boundary,
            )
        except RidgeConfigurationError as exc:
            self.message.emit(str(exc))
            return False
        if updated.is_empty:
            return self.clear_constraint(emit_change=emit_change)
        self._replace_constraint(updated, emit_change=emit_change)
        return True

    def _replace_constraint(
        self,
        constraint: RidgeSearchConstraint,
        *,
        emit_change: bool,
    ) -> None:
        channel_name = self._channel_name
        self._constraint = constraint
        self._remove_overlay()
        self._install_overlay()
        if emit_change and channel_name is not None:
            self.constraint_changed.emit(channel_name, constraint)

    def _restore_pre_edit_constraint(self) -> None:
        prior = self._constraint_before_drawing
        current = self._constraint
        if prior is current:
            return
        if prior is None:
            channel_name = self._channel_name
            self._constraint = None
            self._remove_overlay()
            self._install_overlay()
            if channel_name is not None:
                self.constraint_cleared.emit(channel_name)
        else:
            self._replace_constraint(prior, emit_change=True)

    def _end_drawing_state(self) -> None:
        was_drawing = self._drawing
        if self._draft_curve is not None:
            self._plot_widget.removeItem(self._draft_curve)
        self._draft_curve = None
        self._draft_points = []
        self._invalid_draft = False
        self._drawing = False
        self._active_boundary = None
        self._constraint_before_drawing = None
        self._plot_widget.unsetCursor()
        self._remove_overlay()
        self._install_overlay()
        if was_drawing:
            self.drawing_state_changed.emit(False)

    def _discard_drawing_state(self) -> None:
        if self._draft_curve is not None:
            self._plot_widget.removeItem(self._draft_curve)
        was_drawing = self._drawing
        self._draft_curve = None
        self._draft_points = []
        self._invalid_draft = False
        self._drawing = False
        self._active_boundary = None
        self._constraint_before_drawing = None
        self._plot_widget.unsetCursor()
        if was_drawing:
            self.drawing_state_changed.emit(False)

    def _install_overlay(self) -> None:
        if self._stft_result is None:
            return
        region = self._manual_region()
        self._install_allowed_region(region)
        boundaries: tuple[
            tuple[BoundaryKind, ManualFrequencyBoundary | None], ...
        ] = (
            ("upper", region.upper_boundary),
            ("lower", region.lower_boundary),
        )
        for kind, boundary in boundaries:
            if boundary is not None and not (
                self._drawing and self._active_boundary == kind
            ):
                self._install_boundary_roi(kind, boundary)
        self.set_manual_region_visible(self._manual_region_visible)

    def _install_allowed_region(self, region: ManualFrequencyRegion) -> None:
        stft_result = self._require_stft_result()
        minimum, maximum = self._require_search_band()
        times_s = stft_result.time_s
        in_range = np.ones(times_s.shape, dtype=np.bool_)
        if self._analysis_start_time_s is not None:
            in_range &= times_s >= self._analysis_start_time_s
        if self._analysis_end_time_s is not None:
            in_range &= times_s <= self._analysis_end_time_s
        displayed_times_s = times_s[in_range]
        if displayed_times_s.size == 0:
            displayed_times_s = times_s
        lower_hz, upper_hz = evaluate_manual_frequency_region_bounds(
            region,
            displayed_times_s,
            minimum_frequency_hz=minimum,
            maximum_frequency_hz=maximum,
        )
        self._upper_curve = pg.PlotDataItem(
            displayed_times_s * 1.0e6,
            upper_hz * 1.0e-9,
            pen=pg.mkPen(_UPPER_COLOR, width=0.8),
        )
        self._lower_curve = pg.PlotDataItem(
            displayed_times_s * 1.0e6,
            lower_hz * 1.0e-9,
            pen=pg.mkPen(_LOWER_COLOR, width=0.8),
        )
        self._upper_curve.setZValue(8)
        self._lower_curve.setZValue(8)
        self._fill_item = pg.FillBetweenItem(
            self._lower_curve,
            self._upper_curve,
            brush=pg.mkBrush(*_ALLOWED_FILL_RGBA),
        )
        self._fill_item.setZValue(7)
        self._fill_item.setToolTip(self.tr("人工范围模式的有效候选谱峰搜索区域"))
        self._plot_widget.addItem(self._upper_curve)
        self._plot_widget.addItem(self._lower_curve)
        self._plot_widget.addItem(self._fill_item)

    def _install_boundary_roi(
        self,
        kind: BoundaryKind,
        boundary: ManualFrequencyBoundary,
    ) -> None:
        points = list(
            zip(
                boundary.control_times_s * 1.0e6,
                boundary.control_frequencies_hz * 1.0e-9,
            )
        )
        color = self._boundary_color(kind)
        roi = pg.PolyLineROI(
            points,
            closed=False,
            movable=False,
            maxBounds=self._roi_bounds(),
            pen=pg.mkPen(color, width=1.8),
            hoverPen=pg.mkPen(color, width=2.6),
        )
        roi.setZValue(18)
        roi.setToolTip(
            self.tr("人工上边界") if kind == "upper" else self.tr("人工下边界")
        )
        roi.sigRegionChangeFinished.connect(
            lambda *_args, kind=kind: self._roi_changed(kind)
        )
        self._boundary_rois[kind] = roi
        if self._roi is None:
            self._roi = roi
        self._plot_widget.addItem(roi)

    def _roi_changed(self, kind: BoundaryKind) -> None:
        if self._updating_roi or self._channel_name is None:
            return
        roi = self._boundary_rois.get(kind)
        if roi is None:
            return
        points: list[tuple[float, float]] = []
        for _handle, position in roi.getLocalHandlePositions():
            points.append(self._clamped_si_point(roi.mapToParent(position)))
        try:
            boundary = ManualFrequencyBoundary(
                control_times_s=np.array(
                    [point[0] for point in points], dtype=np.float64
                ),
                control_frequencies_hz=np.array(
                    [point[1] for point in points], dtype=np.float64
                ),
            )
            updated = self._region_with_boundary(
                self._manual_region(),
                kind,
                boundary,
            )
        except RidgeConfigurationError:
            self.message.emit(
                self.tr("移动被拒绝：请保持时间顺序且不要让上下边界交叉。")
            )
            QTimer.singleShot(0, self._restore_constraint_overlay)
            return
        self._last_edited_boundary = kind
        self._replace_constraint(updated, emit_change=True)

    def _restore_constraint_overlay(self) -> None:
        self._updating_roi = True
        try:
            self._remove_overlay()
            self._install_overlay()
        finally:
            self._updating_roi = False

    def _remove_overlay(self) -> None:
        for item in (
            self._fill_item,
            self._upper_curve,
            self._lower_curve,
            *self._boundary_rois.values(),
        ):
            if item is not None:
                try:
                    self._plot_widget.removeItem(item)
                except (RuntimeError, ValueError):
                    pass
        self._boundary_rois = {}
        self._roi = None
        self._upper_curve = None
        self._lower_curve = None
        self._fill_item = None

    def _refresh_draft(self) -> None:
        if self._draft_curve is None:
            return
        self._draft_curve.setData(
            [point[0] * 1.0e6 for point in self._draft_points],
            [point[1] * 1.0e-9 for point in self._draft_points],
        )
        color = (
            _INVALID_COLOR
            if self._invalid_draft
            else self._boundary_color(self._active_boundary or "upper")
        )
        self._draft_curve.setPen(pg.mkPen(color, width=2.0))
        self._draft_curve.setSymbolBrush(color)

    def _clamped_si_point(self, point: QPointF) -> tuple[float, float]:
        stft_result = self._require_stft_result()
        start_s = (
            float(stft_result.time_s[0])
            if self._analysis_start_time_s is None
            else self._analysis_start_time_s
        )
        end_s = (
            float(stft_result.time_s[-1])
            if self._analysis_end_time_s is None
            else self._analysis_end_time_s
        )
        time_s = float(np.clip(point.x() * 1.0e-6, start_s, end_s))
        frequency_hz = float(
            np.clip(
                point.y() * 1.0e9,
                float(stft_result.frequency_hz[0]),
                float(stft_result.frequency_hz[-1]),
            )
        )
        return time_s, frequency_hz

    def _roi_bounds(self) -> QRectF:
        stft_result = self._require_stft_result()
        start_s = (
            float(stft_result.time_s[0])
            if self._analysis_start_time_s is None
            else self._analysis_start_time_s
        )
        end_s = (
            float(stft_result.time_s[-1])
            if self._analysis_end_time_s is None
            else self._analysis_end_time_s
        )
        return QRectF(
            start_s * 1.0e6,
            float(stft_result.frequency_hz[0]) * 1.0e-9,
            (end_s - start_s) * 1.0e6,
            (
                float(stft_result.frequency_hz[-1])
                - float(stft_result.frequency_hz[0])
            )
            * 1.0e-9,
        )

    def _manual_region(self) -> ManualFrequencyRegion:
        constraint = self._constraint
        if isinstance(constraint, ManualFrequencyRegion):
            return constraint
        if isinstance(constraint, RidgeCorridorConstraint):
            return ManualFrequencyRegion(
                upper_boundary=ManualFrequencyBoundary(
                    constraint.control_times_s,
                    constraint.control_frequencies_hz + constraint.half_width_hz,
                ),
                lower_boundary=ManualFrequencyBoundary(
                    constraint.control_times_s,
                    np.maximum(
                        0.0,
                        constraint.control_frequencies_hz
                        - constraint.half_width_hz,
                    ),
                ),
            )
        return ManualFrequencyRegion()

    def _base_region_for_draft(self) -> ManualFrequencyRegion:
        prior = self._constraint_before_drawing
        current = self._constraint
        self._constraint = prior
        try:
            return self._manual_region()
        finally:
            self._constraint = current

    @staticmethod
    def _boundary_from_region(
        region: ManualFrequencyRegion,
        kind: BoundaryKind,
    ) -> ManualFrequencyBoundary | None:
        return region.upper_boundary if kind == "upper" else region.lower_boundary

    @staticmethod
    def _region_with_boundary(
        region: ManualFrequencyRegion,
        kind: BoundaryKind,
        boundary: ManualFrequencyBoundary | None,
    ) -> ManualFrequencyRegion:
        return ManualFrequencyRegion(
            upper_boundary=(
                boundary if kind == "upper" else region.upper_boundary
            ),
            lower_boundary=(
                boundary if kind == "lower" else region.lower_boundary
            ),
        )

    @staticmethod
    def _boundary_color(kind: BoundaryKind) -> str:
        return _UPPER_COLOR if kind == "upper" else _LOWER_COLOR

    def _require_stft_result(self) -> STFTResult:
        if self._stft_result is None:
            raise RuntimeError("No STFT result is attached to the manual editor.")
        return self._stft_result

    def _require_search_band(self) -> tuple[float, float]:
        if (
            self._minimum_frequency_hz is None
            or self._maximum_frequency_hz is None
        ):
            raise RuntimeError("No global search band is attached to the editor.")
        return self._minimum_frequency_hz, self._maximum_frequency_hz


def draw_static_corridor(
    plot_widget: Any,
    constraint: RidgeSearchConstraint,
    *,
    center_name: str,
    stft_result: STFTResult | None = None,
    minimum_frequency_hz: float | None = None,
    maximum_frequency_hz: float | None = None,
) -> tuple[Any, Any, Any]:
    """Draw a non-editable historical corridor or manual allowed region."""
    if isinstance(constraint, RidgeCorridorConstraint):
        time_us = constraint.control_times_s * 1.0e6
        center_ghz = constraint.control_frequencies_hz * 1.0e-9
        half_width_ghz = constraint.half_width_hz * 1.0e-9
        upper_values = center_ghz + half_width_ghz
        lower_values = center_ghz - half_width_ghz
        label_curve = plot_widget.plot(
            time_us,
            center_ghz,
            pen=pg.mkPen("#CC79A7", width=1.4),
            name=center_name,
        )
    else:
        if (
            stft_result is None
            or minimum_frequency_hz is None
            or maximum_frequency_hz is None
        ):
            raise ValueError(
                "Manual region rendering requires STFT and global search bounds."
            )
        time_s = stft_result.time_s
        lower_values, upper_values = evaluate_manual_frequency_region_bounds(
            constraint,
            time_s,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
        )
        time_us = time_s * 1.0e6
        upper_values = upper_values * 1.0e-9
        lower_values = lower_values * 1.0e-9
        label_curve = plot_widget.plot(
            [],
            [],
            pen=pg.mkPen(_UPPER_COLOR, width=1.4),
            name=center_name,
        )
    upper = pg.PlotDataItem(
        time_us,
        upper_values,
        pen=pg.mkPen(_UPPER_COLOR, width=1.0),
    )
    lower = pg.PlotDataItem(
        time_us,
        lower_values,
        pen=pg.mkPen(_LOWER_COLOR, width=1.0),
    )
    fill = pg.FillBetweenItem(
        lower,
        upper,
        brush=pg.mkBrush(*_ALLOWED_FILL_RGBA),
    )
    plot_widget.addItem(upper)
    plot_widget.addItem(lower)
    plot_widget.addItem(fill)
    if isinstance(constraint, ManualFrequencyRegion):
        for boundary, color in (
            (constraint.upper_boundary, _UPPER_COLOR),
            (constraint.lower_boundary, _LOWER_COLOR),
        ):
            if boundary is not None:
                plot_widget.plot(
                    boundary.control_times_s * 1.0e6,
                    boundary.control_frequencies_hz * 1.0e-9,
                    pen=pg.mkPen(color, width=1.8),
                    symbol="o",
                    symbolSize=5,
                    symbolBrush=color,
                )
    return fill, label_curve, (upper, lower)


__all__ = ["RidgeCorridorController", "draw_static_corridor"]
