"""PyQtGraph ridge-corridor editing in physical plot coordinates."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal

from dps_studio.core.ridge import RidgeConfigurationError, RidgeCorridorConstraint
from dps_studio.core.time_frequency import STFTResult


class RidgeCorridorController(QObject):
    """Edit at most one corridor for the current channel with ``PolyLineROI``.

    PyQtGraph owns only the visual handles. Every completed edit is immediately
    converted to an immutable core constraint in seconds and hertz.
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
        self._channel_name: str | None = None
        self._constraint: RidgeCorridorConstraint | None = None
        self._half_width_hz = 50.0e6
        self._drawing = False
        self._draft_points: list[tuple[float, float]] = []
        self._constraint_before_drawing: RidgeCorridorConstraint | None = None
        self._roi: Any | None = None
        self._upper_curve: Any | None = None
        self._lower_curve: Any | None = None
        self._fill_item: Any | None = None
        self._draft_curve: Any | None = None
        self._updating_roi = False
        self._plot_widget.scene().sigMouseClicked.connect(self._scene_clicked)

    @property
    def drawing(self) -> bool:
        return self._drawing

    @property
    def constraint(self) -> RidgeCorridorConstraint | None:
        return self._constraint

    @property
    def channel_name(self) -> str | None:
        return self._channel_name

    def set_context(
        self,
        channel_name: str,
        stft_result: STFTResult,
        constraint: RidgeCorridorConstraint | None,
        *,
        analysis_start_time_s: float | None,
        analysis_end_time_s: float | None,
    ) -> None:
        """Attach the current physical axes and reconstruct its visual overlay."""
        self.cancel_drawing()
        self._remove_overlay()
        self._channel_name = channel_name
        self._stft_result = stft_result
        self._analysis_start_time_s = analysis_start_time_s
        self._analysis_end_time_s = analysis_end_time_s
        self._constraint = constraint
        if constraint is not None:
            self._half_width_hz = constraint.half_width_hz
            self._install_overlay(constraint)

    def detach_context(self) -> None:
        """Detach a cleared plot without emitting a scientific state change."""
        self.cancel_drawing()
        self._remove_overlay()
        self._stft_result = None
        self._analysis_start_time_s = None
        self._analysis_end_time_s = None
        self._channel_name = None
        self._constraint = None

    def begin_drawing(self, *, half_width_hz: float) -> bool:
        """Start click-to-place drawing while retaining any prior result."""
        if self._stft_result is None or self._channel_name is None:
            self.message.emit(self.tr("当前通道没有可绘制的 STFT。"))
            return False
        try:
            self._half_width_hz = self._validated_half_width(half_width_hz)
        except ValueError as exc:
            self.message.emit(str(exc))
            return False
        self.cancel_drawing()
        self._constraint_before_drawing = self._constraint
        self._drawing = True
        self._draft_points = []
        self._draft_curve = pg.PlotDataItem(
            pen=pg.mkPen("#CC79A7", width=1.3, style=Qt.PenStyle.DashLine),
            symbol="o",
            symbolSize=6,
            symbolBrush="#CC79A7",
        )
        self._draft_curve.setZValue(20)
        self._plot_widget.addItem(self._draft_curve)
        self.drawing_state_changed.emit(True)
        self.message.emit(
            self.tr("左键添加少量控制点；双击、Enter 或运行时结束绘制。")
        )
        return True

    def finish_drawing(self) -> bool:
        """Validate draft points, store SI coordinates, and emit one constraint."""
        if not self._drawing:
            return False
        if len(self._draft_points) < 2:
            self.message.emit(self.tr("脊线走廊至少需要两个控制点。"))
            return False
        ordered = sorted(self._draft_points, key=lambda value: value[0])
        times = np.array([point[0] for point in ordered], dtype=np.float64)
        frequencies = np.array([point[1] for point in ordered], dtype=np.float64)
        if np.any(np.diff(times) <= 0.0):
            self.message.emit(self.tr("控制点时间必须严格递增且不能重合。"))
            return False
        try:
            constraint = RidgeCorridorConstraint(
                control_times_s=times,
                control_frequencies_hz=frequencies,
                half_width_hz=self._half_width_hz,
            )
        except RidgeConfigurationError as exc:
            self.message.emit(str(exc))
            return False
        self.cancel_drawing()
        self._replace_constraint(constraint, emit_change=True)
        return True

    def undo_last_point(self) -> bool:
        """Remove the most recently added point without touching STFT state."""
        if self._drawing and self._draft_points:
            self._draft_points.pop()
            self._refresh_draft()
            if len(self._draft_points) >= 2:
                self._commit_live_draft()
            elif self._constraint_before_drawing is not None:
                self._replace_constraint(
                    self._constraint_before_drawing,
                    emit_change=True,
                )
            elif self._constraint is not None:
                channel_name = self._channel_name
                self._constraint = None
                self._remove_overlay()
                if channel_name is not None:
                    self.constraint_cleared.emit(channel_name)
            return True
        if self._constraint is None:
            return False
        if self._constraint.control_point_count <= 2:
            return self.clear_constraint(emit_change=True)
        updated = RidgeCorridorConstraint(
            control_times_s=self._constraint.control_times_s[:-1],
            control_frequencies_hz=self._constraint.control_frequencies_hz[:-1],
            half_width_hz=self._constraint.half_width_hz,
        )
        self._replace_constraint(updated, emit_change=True)
        return True

    def cancel_drawing(self) -> None:
        if self._draft_curve is not None:
            self._plot_widget.removeItem(self._draft_curve)
        was_drawing = self._drawing
        self._draft_curve = None
        self._draft_points = []
        self._drawing = False
        self._constraint_before_drawing = None
        if was_drawing:
            self.drawing_state_changed.emit(False)

    def set_half_width_hz(self, half_width_hz: float) -> bool:
        """Update the uniform half width without changing control coordinates."""
        try:
            width = self._validated_half_width(half_width_hz)
        except ValueError as exc:
            self.message.emit(str(exc))
            return False
        self._half_width_hz = width
        if self._constraint is None:
            return False
        updated = RidgeCorridorConstraint(
            control_times_s=self._constraint.control_times_s,
            control_frequencies_hz=self._constraint.control_frequencies_hz,
            half_width_hz=width,
        )
        self._constraint = updated
        self._refresh_band(updated)
        if self._channel_name is not None:
            self.constraint_changed.emit(self._channel_name, updated)
        return True

    def clear_constraint(self, *, emit_change: bool = True) -> bool:
        """Remove the current channel's complete corridor."""
        self.cancel_drawing()
        if self._constraint is None:
            return False
        channel_name = self._channel_name
        self._constraint = None
        self._remove_overlay()
        if emit_change and channel_name is not None:
            self.constraint_cleared.emit(channel_name)
        return True

    def _scene_clicked(self, event: Any) -> None:
        if not self._drawing or self._stft_result is None:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        scene_position = event.scenePos()
        view_box = self._plot_widget.plotItem.vb
        if not view_box.sceneBoundingRect().contains(scene_position):
            return
        view_position = view_box.mapSceneToView(scene_position)
        point = self._clamped_si_point(view_position)
        if not self._draft_points or point != self._draft_points[-1]:
            self._draft_points.append(point)
            self._refresh_draft()
            if len(self._draft_points) >= 2:
                self._commit_live_draft()
        if event.double():
            self.finish_drawing()

    def _clamped_si_point(self, point: QPointF) -> tuple[float, float]:
        stft_result = self._require_stft_result()
        start_s = self._analysis_start_time_s
        end_s = self._analysis_end_time_s
        if start_s is None:
            start_s = float(stft_result.time_s[0])
        if end_s is None:
            end_s = float(stft_result.time_s[-1])
        time_s = float(np.clip(point.x() * 1.0e-6, start_s, end_s))
        frequency_hz = float(
            np.clip(
                point.y() * 1.0e9,
                float(stft_result.frequency_hz[0]),
                float(stft_result.frequency_hz[-1]),
            )
        )
        return time_s, frequency_hz

    def _refresh_draft(self) -> None:
        if self._draft_curve is None:
            return
        self._draft_curve.setData(
            [point[0] * 1.0e6 for point in self._draft_points],
            [point[1] * 1.0e-9 for point in self._draft_points],
        )

    def _commit_live_draft(self) -> None:
        ordered = sorted(self._draft_points, key=lambda value: value[0])
        if len(ordered) < 2 or any(
            right[0] <= left[0] for left, right in zip(ordered, ordered[1:])
        ):
            return
        constraint = RidgeCorridorConstraint(
            control_times_s=np.array([point[0] for point in ordered]),
            control_frequencies_hz=np.array([point[1] for point in ordered]),
            half_width_hz=self._half_width_hz,
        )
        self._replace_constraint(constraint, emit_change=True)

    def _replace_constraint(
        self,
        constraint: RidgeCorridorConstraint,
        *,
        emit_change: bool,
    ) -> None:
        channel_name = self._channel_name
        self._constraint = constraint
        self._half_width_hz = constraint.half_width_hz
        self._remove_overlay()
        self._install_overlay(constraint)
        if emit_change and channel_name is not None:
            self.constraint_changed.emit(channel_name, constraint)

    def _install_overlay(self, constraint: RidgeCorridorConstraint) -> None:
        stft_result = self._require_stft_result()
        points = list(
            zip(
                constraint.control_times_s * 1.0e6,
                constraint.control_frequencies_hz * 1.0e-9,
            )
        )
        start_s = self._analysis_start_time_s
        end_s = self._analysis_end_time_s
        if start_s is None:
            start_s = float(stft_result.time_s[0])
        if end_s is None:
            end_s = float(stft_result.time_s[-1])
        minimum_ghz = float(stft_result.frequency_hz[0]) * 1.0e-9
        maximum_ghz = float(stft_result.frequency_hz[-1]) * 1.0e-9
        bounds = QRectF(
            start_s * 1.0e6,
            minimum_ghz,
            (end_s - start_s) * 1.0e6,
            maximum_ghz - minimum_ghz,
        )
        self._roi = pg.PolyLineROI(
            points,
            closed=False,
            movable=False,
            maxBounds=bounds,
            pen=pg.mkPen("#CC79A7", width=1.6),
            hoverPen=pg.mkPen("#D55E00", width=2.2),
        )
        self._roi.setZValue(15)
        self._roi.sigRegionChangeFinished.connect(self._roi_changed)
        self._plot_widget.addItem(self._roi)
        boundary_pen = pg.mkPen("#CC79A7", width=0.9)
        self._upper_curve = pg.PlotDataItem(pen=boundary_pen)
        self._lower_curve = pg.PlotDataItem(pen=boundary_pen)
        self._upper_curve.setZValue(9)
        self._lower_curve.setZValue(9)
        self._fill_item = pg.FillBetweenItem(
            self._lower_curve,
            self._upper_curve,
            brush=pg.mkBrush(204, 121, 167, 45),
        )
        self._fill_item.setZValue(8)
        self._plot_widget.addItem(self._upper_curve)
        self._plot_widget.addItem(self._lower_curve)
        self._plot_widget.addItem(self._fill_item)
        self._refresh_band(constraint)

    def _roi_changed(self) -> None:
        if self._updating_roi or self._roi is None or self._channel_name is None:
            return
        points: list[tuple[float, float]] = []
        for _handle, position in self._roi.getLocalHandlePositions():
            mapped = self._roi.mapToParent(position)
            points.append(self._clamped_si_point(mapped))
        if len(points) < 2:
            self.clear_constraint(emit_change=True)
            return
        try:
            updated = RidgeCorridorConstraint(
                control_times_s=np.array([point[0] for point in points]),
                control_frequencies_hz=np.array([point[1] for point in points]),
                half_width_hz=self._half_width_hz,
            )
        except RidgeConfigurationError as exc:
            self.message.emit(str(exc))
            if self._constraint is not None:
                QTimer.singleShot(0, self._restore_constraint_overlay)
            return
        self._constraint = updated
        self._refresh_band(updated)
        self.constraint_changed.emit(self._channel_name, updated)

    def _restore_constraint_overlay(self) -> None:
        if self._constraint is None:
            return
        self._updating_roi = True
        try:
            self._replace_constraint(self._constraint, emit_change=False)
        finally:
            self._updating_roi = False

    def _refresh_band(self, constraint: RidgeCorridorConstraint) -> None:
        if self._upper_curve is None or self._lower_curve is None:
            return
        time_us = constraint.control_times_s * 1.0e6
        center_ghz = constraint.control_frequencies_hz * 1.0e-9
        half_width_ghz = constraint.half_width_hz * 1.0e-9
        self._upper_curve.setData(time_us, center_ghz + half_width_ghz)
        self._lower_curve.setData(time_us, center_ghz - half_width_ghz)

    def _remove_overlay(self) -> None:
        roi = self._roi
        if roi is not None:
            try:
                roi.sigRegionChangeFinished.disconnect(self._roi_changed)
            except (RuntimeError, TypeError):
                pass
        for item in (self._fill_item, self._upper_curve, self._lower_curve, roi):
            if item is not None:
                self._plot_widget.removeItem(item)
        self._roi = None
        self._upper_curve = None
        self._lower_curve = None
        self._fill_item = None

    def _require_stft_result(self) -> STFTResult:
        if self._stft_result is None:
            raise RuntimeError("No STFT result is attached to the corridor editor.")
        return self._stft_result

    @staticmethod
    def _validated_half_width(value: float) -> float:
        converted = float(value)
        if not np.isfinite(converted) or converted <= 0.0:
            raise ValueError("Corridor half width must be finite and positive.")
        return converted


def draw_static_corridor(
    plot_widget: Any,
    constraint: RidgeCorridorConstraint,
    *,
    center_name: str,
) -> tuple[Any, Any, Any]:
    """Draw a non-editable corridor band for a guided result view."""
    time_us = constraint.control_times_s * 1.0e6
    center_ghz = constraint.control_frequencies_hz * 1.0e-9
    half_width_ghz = constraint.half_width_hz * 1.0e-9
    boundary_pen = pg.mkPen("#CC79A7", width=0.9)
    upper = pg.PlotDataItem(time_us, center_ghz + half_width_ghz, pen=boundary_pen)
    lower = pg.PlotDataItem(time_us, center_ghz - half_width_ghz, pen=boundary_pen)
    fill = pg.FillBetweenItem(lower, upper, brush=pg.mkBrush(204, 121, 167, 45))
    plot_widget.addItem(upper)
    plot_widget.addItem(lower)
    plot_widget.addItem(fill)
    center = plot_widget.plot(
        time_us,
        center_ghz,
        pen=pg.mkPen("#CC79A7", width=1.4),
        name=center_name,
    )
    return fill, center, (upper, lower)


__all__ = ["RidgeCorridorController", "draw_static_corridor"]
