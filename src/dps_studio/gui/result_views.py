"""PyQtGraph views backed only by public core ``ChannelAnalysis`` arrays."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from numpy.typing import NDArray
from PySide6.QtCore import QSignalBlocker, QRectF, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dps_studio.core.export import ExportTimeOrigin
from dps_studio.core.quality import SignalState
from dps_studio.core.ridge import ManualFrequencyRegion, RidgeSearchConstraint
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import ChannelAnalysis
from dps_studio.gui.display_preferences import (
    DEFAULT_SPECTROGRAM_COLORMAP,
    normalize_spectrogram_colormap,
    spectrogram_colormap,
)
from dps_studio.gui.ridge_corridor import (
    RidgeCorridorController,
    draw_static_corridor,
)


FloatArray = NDArray[np.float64]
_COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")


def analysis_view_range_us(analysis: ChannelAnalysis) -> tuple[float, float]:
    """Return the confirmed analysis range in display microseconds."""
    detection = analysis.signal_detection_result
    start_s = detection.analysis_start_time_s
    end_s = detection.analysis_end_time_s
    if start_s is None:
        start_s = float(analysis.stft_result.time_s[0])
    if end_s is None:
        end_s = float(analysis.stft_result.time_s[-1])
    if start_s >= end_s:
        raise ValueError("Analysis view range must be strictly ordered.")
    return start_s * 1e6, end_s * 1e6


def finite_velocity_view_range(
    arrays: tuple[FloatArray, ...],
    *,
    padding_fraction: float = 0.075,
) -> tuple[float, float] | None:
    """Return a padded range from finite plotted values only."""
    finite_min = math.inf
    finite_max = -math.inf
    for values in arrays:
        finite = np.asarray(values, dtype=np.float64)
        finite = finite[np.isfinite(finite)]
        if finite.size:
            finite_min = min(finite_min, float(np.min(finite)))
            finite_max = max(finite_max, float(np.max(finite)))
    if not math.isfinite(finite_min) or not math.isfinite(finite_max):
        return None
    span = finite_max - finite_min
    padding = (
        span * padding_fraction
        if span > 0.0
        else max(abs(finite_min) * padding_fraction, 1.0)
    )
    return finite_min - padding, finite_max + padding


def finite_velocity_xy_view_range(
    series: tuple[tuple[FloatArray, FloatArray], ...],
    *,
    x_limits: tuple[float, float] | None = None,
    y_padding_fraction: float = 0.075,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return finite X bounds and padded Y bounds from visible plotted series."""
    finite_x: list[FloatArray] = []
    finite_y: list[FloatArray] = []
    for x_values, y_values in series:
        x = np.asarray(x_values, dtype=np.float64)
        y = np.asarray(y_values, dtype=np.float64)
        if x.shape != y.shape:
            raise ValueError("Velocity plot X and Y arrays must share one shape.")
        mask = np.isfinite(x) & np.isfinite(y)
        if x_limits is not None:
            tolerance = max(abs(x_limits[1] - x_limits[0]), 1.0) * 1.0e-12
            mask &= (x >= x_limits[0] - tolerance) & (
                x <= x_limits[1] + tolerance
            )
        if np.any(mask):
            finite_x.append(x[mask])
            finite_y.append(y[mask])
    if not finite_x:
        return None
    x_min = min(float(np.min(values)) for values in finite_x)
    x_max = max(float(np.max(values)) for values in finite_x)
    if x_min == x_max:
        x_padding = max(abs(x_min) * 0.01, 1.0e-6)
        x_min -= x_padding
        x_max += x_padding
    y_bounds = finite_velocity_view_range(
        tuple(finite_y),
        padding_fraction=y_padding_fraction,
    )
    if y_bounds is None:  # pragma: no cover - finite_y is non-empty by construction.
        return None
    return (x_min, x_max), y_bounds


def display_velocity_connector_points(
    analysis: ChannelAnalysis,
) -> tuple[FloatArray, FloatArray] | None:
    """Return a pre-event-to-first-formal display-only connector.

    No NaN is filled and no intermediate sample is synthesized for scientific
    data; this only joins two already available display endpoints.
    """
    reference_s = analysis.signal_detection_result.manual_event_reference_time_s
    if reference_s is None:
        return None
    time_s = analysis.stft_result.time_s
    display_velocity = analysis.display_velocity_m_s
    formal_velocity = analysis.corrected_velocity_m_s
    platform_indices = np.flatnonzero(
        (time_s < reference_s) & np.isfinite(display_velocity)
    )
    formal_indices = np.flatnonzero(
        (time_s >= reference_s) & np.isfinite(formal_velocity)
    )
    if platform_indices.size == 0 or formal_indices.size == 0:
        return None
    platform_index = int(platform_indices[-1])
    formal_index = int(formal_indices[0])
    return (
        np.asarray(
            [reference_s, time_s[formal_index]],
            dtype=np.float64,
        )
        * 1.0e6,
        np.asarray(
            [display_velocity[platform_index], formal_velocity[formal_index]],
            dtype=np.float64,
        ),
    )


def _fit_analysis_x(plot_widget: Any, analysis: ChannelAnalysis) -> None:
    start_us, end_us = analysis_view_range_us(analysis)
    plot_widget.setXRange(start_us, end_us, padding=0.0)


def relative_magnitude_db(
    analysis: ChannelAnalysis,
    *,
    floor_db: float,
) -> FloatArray:
    """Return exact ``20 log10(|spectrum| / max|spectrum|)`` display values."""
    return relative_stft_magnitude_db(analysis.stft_result, floor_db=floor_db)


def relative_stft_magnitude_db(
    stft_result: STFTResult,
    *,
    floor_db: float,
) -> FloatArray:
    """Return display-only relative magnitude for one reusable STFT result."""
    magnitude = np.abs(stft_result.spectrum)
    reference = float(np.max(magnitude))
    if reference <= 0.0:
        return np.full(magnitude.shape, floor_db, dtype=np.float64)
    with np.errstate(divide="ignore"):
        values = 20.0 * np.log10(magnitude / reference)
    return np.maximum(values, floor_db).astype(np.float64, copy=False)


def _set_image(
    image_item: Any,
    analysis: ChannelAnalysis,
    *,
    floor_db: float,
) -> FloatArray:
    return _set_stft_image(image_item, analysis.stft_result, floor_db=floor_db)


def _set_stft_image(
    image_item: Any,
    stft: STFTResult,
    *,
    floor_db: float,
) -> FloatArray:
    display = relative_stft_magnitude_db(stft, floor_db=floor_db)
    image_item.setImage(display, autoLevels=False, levels=(floor_db, 0.0))
    time_us = stft.time_s * 1e6
    frequency_ghz = stft.frequency_hz * 1e-9
    time_step = (
        float(np.median(np.diff(time_us))) if time_us.size > 1 else 1.0
    )
    frequency_step = (
        float(np.median(np.diff(frequency_ghz)))
        if frequency_ghz.size > 1
        else 1.0
    )
    image_item.setRect(
        QRectF(
            float(time_us[0] - 0.5 * time_step),
            float(frequency_ghz[0] - 0.5 * frequency_step),
            float(time_us[-1] - time_us[0] + time_step),
            float(frequency_ghz[-1] - frequency_ghz[0] + frequency_step),
        )
    )
    return display


def _add_search_band_limits(
    plot_widget: Any,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    *,
    movable: bool = False,
    frequency_bounds_hz: tuple[float, float] | None = None,
    finished: Any | None = None,
    lower_tooltip: str = "",
    upper_tooltip: str = "",
) -> list[Any]:
    lines = []
    bounds = (
        None
        if frequency_bounds_hz is None
        else tuple(value * 1.0e-9 for value in frequency_bounds_hz)
    )
    for index, frequency_hz in enumerate(
        (minimum_frequency_hz, maximum_frequency_hz)
    ):
        line = pg.InfiniteLine(
            pos=frequency_hz * 1e-9,
            angle=0,
            pen=pg.mkPen("#555555", width=1.0, style=pg.QtCore.Qt.DashLine),
            hoverPen=pg.mkPen("#D55E00", width=3.0),
            movable=movable,
            bounds=bounds,
        )
        line.setZValue(30)
        if movable:
            line.setCursor(Qt.CursorShape.SizeVerCursor)
            line.setToolTip(lower_tooltip if index == 0 else upper_tooltip)
            # InfiniteLine 0.14 includes marker size in its native boundingRect,
            # giving a generous device-pixel hit area without data-coordinate hacks.
            line.addMarker("<|>", position=0.06, size=7.0)
            if finished is not None:
                line.sigPositionChangeFinished.connect(
                    lambda _line, boundary=index: finished(boundary)
                )
        plot_widget.addItem(line)
        lines.append(line)
    return lines


class _ChannelView(QWidget):
    """Small shared channel selector for independent analysis results."""

    plot_widget: Any
    channel_selection_changed = Signal(str)
    search_band_changed = Signal(float, float)
    search_region_changed = Signal(float, float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analyses: Mapping[str, ChannelAnalysis] = {}
        self._floor_db = -60.0
        self._view_analysis_range_s: tuple[float, float] | None = None
        self._view_search_band_hz: tuple[float, float] | None = None
        self._search_lines: list[Any] = []
        self._search_time_lines: list[Any] = []
        self._search_region_roi: Any | None = None
        self._search_frequency_grid_hz: FloatArray | None = None
        self._search_time_grid_s: FloatArray | None = None
        self._search_band_handles_enabled = True
        self._search_region_visible = False
        self._search_region_editable = False
        self.root_layout = QVBoxLayout(self)
        self.controls_layout = QHBoxLayout()
        self.controls_layout.addWidget(QLabel(self.tr("显示通道")))
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("analysisChannelSelector")
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        self.controls_layout.addWidget(self.channel_combo)
        self.fit_analysis_range_button = QPushButton(
            self.tr("适合分析范围")
        )
        self.fit_analysis_range_button.setObjectName("fitAnalysisRangeButton")
        self.fit_analysis_range_button.clicked.connect(self.fit_analysis_range)
        self.controls_layout.addWidget(self.fit_analysis_range_button)
        self.controls_layout.addStretch(1)
        self.root_layout.addLayout(self.controls_layout)

    def add_spectral_view_controls(self) -> None:
        """Add the two display-only frequency shortcuts used by STFT views."""
        self.fit_search_region_button = QPushButton(self.tr("适合搜索区域"))
        self.fit_search_region_button.setObjectName("fitSearchRegionButton")
        self.fit_search_region_button.clicked.connect(self.fit_search_region)
        self.show_full_spectrum_button = QPushButton(self.tr("显示完整频谱"))
        self.show_full_spectrum_button.setObjectName("showFullSpectrumButton")
        self.show_full_spectrum_button.clicked.connect(self.show_full_spectrum)
        self.controls_layout.insertWidget(
            self.controls_layout.count() - 1,
            self.fit_search_region_button,
        )
        self.controls_layout.insertWidget(
            self.controls_layout.count() - 1,
            self.show_full_spectrum_button,
        )

    def set_view_configuration(
        self,
        *,
        analysis_start_time_s: float,
        analysis_end_time_s: float,
        minimum_frequency_hz: float,
        maximum_frequency_hz: float,
    ) -> None:
        """Store display ranges without altering any scientific array."""
        self._view_analysis_range_s = (
            float(analysis_start_time_s),
            float(analysis_end_time_s),
        )
        self._view_search_band_hz = (
            float(minimum_frequency_hz),
            float(maximum_frequency_hz),
        )
        self._synchronize_search_lines()

    def _install_search_band_lines(self, stft_result: STFTResult) -> None:
        """Install a physical four-edge rectangle with generous native hit areas."""
        self._search_frequency_grid_hz = np.asarray(
            stft_result.frequency_hz,
            dtype=np.float64,
        )
        self._search_time_grid_s = np.asarray(stft_result.time_s, dtype=np.float64)
        if self._view_search_band_hz is None or self._view_analysis_range_s is None:
            self._search_lines = []
            self._search_time_lines = []
            self._search_region_roi = None
            return
        time_start_s, time_end_s = self._view_analysis_range_s
        frequency_min_hz, frequency_max_hz = self._view_search_band_hz
        full_rect = QRectF(
            float(stft_result.time_s[0]) * 1.0e6,
            float(stft_result.frequency_hz[0]) * 1.0e-9,
            float(stft_result.time_s[-1] - stft_result.time_s[0]) * 1.0e6,
            float(stft_result.frequency_hz[-1] - stft_result.frequency_hz[0])
            * 1.0e-9,
        )
        self._search_region_roi = pg.ROI(
            [time_start_s * 1.0e6, frequency_min_hz * 1.0e-9],
            [
                (time_end_s - time_start_s) * 1.0e6,
                (frequency_max_hz - frequency_min_hz) * 1.0e-9,
            ],
            pen=pg.mkPen("#0072B2", width=2.0),
            hoverPen=pg.mkPen("#D55E00", width=3.0),
            maxBounds=full_rect,
            movable=self._search_region_editable,
            resizable=False,
            rotatable=False,
        )
        self._search_region_roi.setZValue(20)
        self._search_region_roi.setToolTip(
            self.tr("拖动矩形内部可整体移动脊线搜索区域")
        )
        self._search_region_roi.sigRegionChangeFinished.connect(
            self._search_roi_finished
        )
        self.plot_widget.addItem(self._search_region_roi)
        self._search_lines = _add_search_band_limits(
            self.plot_widget,
            *self._view_search_band_hz,
            movable=True,
            frequency_bounds_hz=(
                float(stft_result.frequency_hz[0]),
                float(stft_result.frequency_hz[-1]),
            ),
            finished=self._search_boundary_finished,
            lower_tooltip=self.tr("拖动调整搜索频率下限"),
            upper_tooltip=self.tr("拖动调整搜索频率上限"),
        )
        time_bounds_us = (
            float(stft_result.time_s[0]) * 1.0e6,
            float(stft_result.time_s[-1]) * 1.0e6,
        )
        self._search_time_lines = []
        for index, time_s in enumerate(self._view_analysis_range_s):
            line = pg.InfiniteLine(
                pos=time_s * 1.0e6,
                angle=90,
                pen=pg.mkPen("#555555", width=1.0, style=pg.QtCore.Qt.DashLine),
                hoverPen=pg.mkPen("#D55E00", width=3.0),
                movable=self._search_region_editable,
                bounds=time_bounds_us,
            )
            line.setZValue(30)
            line.setCursor(Qt.CursorShape.SizeHorCursor)
            line.setToolTip(
                self.tr("拖动调整搜索时间起点")
                if index == 0
                else self.tr("拖动调整搜索时间终点")
            )
            line.addMarker("<|>", position=0.94, size=7.0)
            line.sigPositionChangeFinished.connect(
                lambda _line, boundary=index: self._search_time_boundary_finished(
                    boundary
                )
            )
            self.plot_widget.addItem(line)
            self._search_time_lines.append(line)
        self.set_search_region_interaction(
            visible=self._search_region_visible,
            editable=self._search_region_editable,
        )

    def dispose_search_region_interactions(self) -> None:
        """Disconnect transient graphics signals before redraw or window teardown."""
        for line in (*self._search_time_lines, *self._search_lines):
            try:
                line.sigPositionChangeFinished.disconnect()
            except (RuntimeError, TypeError):
                pass
        if self._search_region_roi is not None:
            try:
                self._search_region_roi.sigRegionChangeFinished.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._search_lines = []
        self._search_time_lines = []
        self._search_region_roi = None

    def set_search_band_handles_enabled(self, enabled: bool) -> None:
        """Compatibility switch used while editing a channel-local corridor."""
        self._search_band_handles_enabled = bool(enabled)
        active = self._search_region_editable and self._search_band_handles_enabled
        for line in (*self._search_time_lines, *self._search_lines):
            line.setVisible(self._search_region_visible and active)
            line.setMovable(active)
        if self._search_region_roi is not None:
            self._search_region_roi.translatable = active

    def set_search_region_interaction(self, *, visible: bool, editable: bool) -> None:
        """Control overlay presentation without changing its SI coordinates."""
        self._search_region_visible = bool(visible)
        self._search_region_editable = bool(editable)
        hit_targets = (*self._search_time_lines, *self._search_lines)
        for line in hit_targets:
            line.setVisible(self._search_region_visible and self._search_region_editable)
            line.setMovable(self._search_region_editable)
        if self._search_region_roi is not None:
            self._search_region_roi.setVisible(self._search_region_visible)
            self._search_region_roi.translatable = self._search_region_editable

    def _synchronize_search_lines(self) -> None:
        if (
            self._view_search_band_hz is None
            or self._view_analysis_range_s is None
            or len(self._search_lines) != 2
            or len(self._search_time_lines) != 2
        ):
            return
        blockers = [
            QSignalBlocker(line)
            for line in (*self._search_time_lines, *self._search_lines)
        ]
        self._search_time_lines[0].setPos(self._view_analysis_range_s[0] * 1.0e6)
        self._search_time_lines[1].setPos(self._view_analysis_range_s[1] * 1.0e6)
        self._search_lines[0].setPos(self._view_search_band_hz[0] * 1.0e-9)
        self._search_lines[1].setPos(self._view_search_band_hz[1] * 1.0e-9)
        del blockers
        if self._search_region_roi is not None:
            blocker = QSignalBlocker(self._search_region_roi)
            self._search_region_roi.setPos(
                self._view_analysis_range_s[0] * 1.0e6,
                self._view_search_band_hz[0] * 1.0e-9,
            )
            self._search_region_roi.setSize(
                (
                    (self._view_analysis_range_s[1] - self._view_analysis_range_s[0])
                    * 1.0e6,
                    (self._view_search_band_hz[1] - self._view_search_band_hz[0])
                    * 1.0e-9,
                )
            )
            del blocker

    def _search_boundary_finished(self, boundary: int) -> None:
        """Snap a drag to the current Hz grid and emit one ordered SI band."""
        grid = self._search_frequency_grid_hz
        if grid is None or grid.size < 2 or len(self._search_lines) != 2:
            return
        positions_hz = [float(line.value()) * 1.0e9 for line in self._search_lines]
        indices = [
            int(np.argmin(np.abs(grid - position_hz)))
            for position_hz in positions_hz
        ]
        if boundary == 0:
            indices[0] = min(indices[0], indices[1] - 1)
        else:
            indices[1] = max(indices[1], indices[0] + 1)
        indices[0] = max(0, min(indices[0], grid.size - 2))
        indices[1] = min(grid.size - 1, max(indices[1], indices[0] + 1))
        minimum_hz = float(grid[indices[0]])
        maximum_hz = float(grid[indices[1]])
        self._view_search_band_hz = minimum_hz, maximum_hz
        self._synchronize_search_lines()
        self.search_band_changed.emit(minimum_hz, maximum_hz)
        self._emit_search_region()

    def _search_time_boundary_finished(self, boundary: int) -> None:
        grid = self._search_time_grid_s
        if grid is None or grid.size < 2 or len(self._search_time_lines) != 2:
            return
        positions_s = [float(line.value()) * 1.0e-6 for line in self._search_time_lines]
        indices = [
            int(np.argmin(np.abs(grid - position_s))) for position_s in positions_s
        ]
        if boundary == 0:
            indices[0] = min(indices[0], indices[1] - 1)
        else:
            indices[1] = max(indices[1], indices[0] + 1)
        indices[0] = max(0, min(indices[0], grid.size - 2))
        indices[1] = min(grid.size - 1, max(indices[1], indices[0] + 1))
        self._view_analysis_range_s = float(grid[indices[0]]), float(grid[indices[1]])
        self._synchronize_search_lines()
        self._emit_search_region()

    def _search_roi_finished(self) -> None:
        roi = self._search_region_roi
        time_grid = self._search_time_grid_s
        frequency_grid = self._search_frequency_grid_hz
        if roi is None or time_grid is None or frequency_grid is None:
            return
        position = roi.pos()
        size = roi.size()
        start_s = float(position.x()) * 1.0e-6
        end_s = float(position.x() + size.x()) * 1.0e-6
        minimum_hz = float(position.y()) * 1.0e9
        maximum_hz = float(position.y() + size.y()) * 1.0e9
        time_indices = [
            int(np.argmin(np.abs(time_grid - value))) for value in (start_s, end_s)
        ]
        frequency_indices = [
            int(np.argmin(np.abs(frequency_grid - value)))
            for value in (minimum_hz, maximum_hz)
        ]
        time_indices[0] = max(0, min(time_indices[0], time_grid.size - 2))
        time_indices[1] = min(
            time_grid.size - 1, max(time_indices[1], time_indices[0] + 1)
        )
        frequency_indices[0] = max(
            0, min(frequency_indices[0], frequency_grid.size - 2)
        )
        frequency_indices[1] = min(
            frequency_grid.size - 1,
            max(frequency_indices[1], frequency_indices[0] + 1),
        )
        self._view_analysis_range_s = (
            float(time_grid[time_indices[0]]),
            float(time_grid[time_indices[1]]),
        )
        self._view_search_band_hz = (
            float(frequency_grid[frequency_indices[0]]),
            float(frequency_grid[frequency_indices[1]]),
        )
        self._synchronize_search_lines()
        self._emit_search_region()

    def _emit_search_region(self) -> None:
        if self._view_analysis_range_s is None or self._view_search_band_hz is None:
            return
        self.search_region_changed.emit(
            self._view_analysis_range_s[0],
            self._view_analysis_range_s[1],
            self._view_search_band_hz[0],
            self._view_search_band_hz[1],
        )

    def set_analyses(
        self,
        analyses: Mapping[str, ChannelAnalysis],
        *,
        relative_db_floor: float,
    ) -> None:
        """Store channel results and select the first independent channel."""
        self._analyses = analyses
        self._floor_db = float(relative_db_floor)
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        for channel_name in analyses:
            self.channel_combo.addItem(channel_name, channel_name)
        self.channel_combo.blockSignals(False)
        self.channel_combo.setEnabled(bool(analyses))
        if analyses:
            self.channel_combo.setCurrentIndex(0)
            channel_name = next(iter(analyses))
            self._render_channel(channel_name, fit_view=True)
            self.channel_selection_changed.emit(channel_name)

    def clear_results(self) -> None:
        """Remove old arrays after any upstream invalidation."""
        self._analyses = {}
        self.channel_combo.clear()
        self.channel_combo.setEnabled(False)
        self._clear_plot()

    def _channel_changed(self, _index: int) -> None:
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            self._render_channel(channel_name, fit_view=True)
            self.channel_selection_changed.emit(channel_name)

    def fit_analysis_range(self) -> None:
        """Restore X to the confirmed analysis range for the current channel."""
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            self._fit_current_view(self._analyses[channel_name])

    def _fit_current_view(self, analysis: ChannelAnalysis) -> None:
        if self._view_analysis_range_s is None:
            _fit_analysis_x(self.plot_widget, analysis)
            return
        self.plot_widget.setXRange(
            self._view_analysis_range_s[0] * 1.0e6,
            self._view_analysis_range_s[1] * 1.0e6,
            padding=0.0,
        )

    def fit_search_region(self) -> None:
        """Fit X to analysis range and Y to the scientific search band."""
        if self._view_analysis_range_s is not None:
            self.plot_widget.setXRange(
                self._view_analysis_range_s[0] * 1.0e6,
                self._view_analysis_range_s[1] * 1.0e6,
                padding=0.0,
            )
        if self._view_search_band_hz is not None:
            self.plot_widget.setYRange(
                self._view_search_band_hz[0] * 1.0e-9,
                self._view_search_band_hz[1] * 1.0e-9,
                padding=0.0,
            )

    def show_full_spectrum(self) -> None:
        """Restore the complete frequency extent of the current STFT."""
        stft_result = self._current_stft_result()
        if stft_result is None:
            return
        if self._view_analysis_range_s is not None:
            self.plot_widget.setXRange(
                self._view_analysis_range_s[0] * 1.0e6,
                self._view_analysis_range_s[1] * 1.0e6,
                padding=0.0,
            )
        self.plot_widget.setYRange(
            float(stft_result.frequency_hz[0]) * 1.0e-9,
            float(stft_result.frequency_hz[-1]) * 1.0e-9,
            padding=0.0,
        )

    def _current_stft_result(self) -> STFTResult | None:
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            return self._analyses[channel_name].stft_result
        return None

    def _render_channel(self, channel_name: str, *, fit_view: bool) -> None:
        raise NotImplementedError

    def _clear_plot(self) -> None:
        raise NotImplementedError


class SpectrogramView(_ChannelView):
    """Render a channel's exact STFT coefficients as relative magnitude dB."""

    colormap_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.add_spectral_view_controls()
        self.fit_analysis_range_button.setVisible(False)
        colormap_row = QHBoxLayout()
        colormap_row.addWidget(QLabel(self.tr("色图")))
        self.colormap_combo = QComboBox()
        self.colormap_combo.setObjectName("spectrogramColormapSelector")
        self.colormap_combo.addItem("Viridis", "viridis")
        self.colormap_combo.addItem("Cividis", "cividis")
        self.colormap_combo.addItem(self.tr("灰度"), "grayscale")
        self.colormap_combo.currentIndexChanged.connect(
            self._colormap_selected
        )
        colormap_row.addWidget(self.colormap_combo)
        colormap_row.addStretch(1)
        self.root_layout.addLayout(colormap_row)
        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("spectrogramPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("频率"), units="GHz")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.18)
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.plot_widget.addItem(self.image_item)
        self.current_colormap_name = DEFAULT_SPECTROGRAM_COLORMAP
        self.color_bar = pg.ColorBarItem(
            values=(self._floor_db, 0.0),
            width=20,
            colorMap=spectrogram_colormap(self.current_colormap_name),
            label=self.tr("相对 STFT 幅值 (dB)"),
            interactive=False,
            colorMapMenu=False,
        )
        self.color_bar.setObjectName("spectrogramColorBar")
        self.color_bar.setToolTip(
            self.tr(
                "20 log10(|STFT| / max|STFT|)；仅调整显示映射，"
                "不是正式 SNR。"
            )
        )
        self.color_bar.setImageItem(
            self.image_item,
            insert_in=self.plot_widget.plotItem,
        )
        self.root_layout.addWidget(self.plot_widget, 1)
        self.definition_label = QLabel(
            self.tr("显示定义：20 log10(|STFT| / 通道全局最大值)，不是正式 SNR。")
        )
        self.definition_label.setObjectName("spectrogramDefinitionLabel")
        self.root_layout.addWidget(self.definition_label)
        self.current_image_db: FloatArray | None = None
        self._corridors: Mapping[str, RidgeSearchConstraint] = {}
        self._stft_results: Mapping[str, STFTResult] = {}
        self.corridor_controller = RidgeCorridorController(
            self.plot_widget,
            self,
        )

    def set_stft_results(
        self,
        stft_results: Mapping[str, STFTResult],
        *,
        relative_db_floor: float,
    ) -> None:
        """Present independent STFT results before any ridge exists."""
        self.plot_widget.setTitle("")
        self._analyses = {}
        self._stft_results = stft_results
        self._floor_db = float(relative_db_floor)
        blocker = QSignalBlocker(self.channel_combo)
        self.channel_combo.clear()
        for channel_name in stft_results:
            self.channel_combo.addItem(channel_name, channel_name)
        self.channel_combo.setEnabled(bool(stft_results))
        del blocker
        if stft_results:
            channel_name = next(iter(stft_results))
            self.channel_combo.setCurrentIndex(0)
            self._render_channel(channel_name, fit_view=True)
            self.channel_selection_changed.emit(channel_name)

    def set_analyses(
        self,
        analyses: Mapping[str, ChannelAnalysis],
        *,
        relative_db_floor: float,
    ) -> None:
        self._stft_results = {
            name: analysis.stft_result for name, analysis in analyses.items()
        }
        super().set_analyses(analyses, relative_db_floor=relative_db_floor)

    def clear_results(self) -> None:
        self._stft_results = {}
        super().clear_results()

    def _channel_changed(self, _index: int) -> None:
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._stft_results:
            self._render_channel(channel_name, fit_view=True)
            self.channel_selection_changed.emit(channel_name)

    def _current_stft_result(self) -> STFTResult | None:
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str):
            return self._stft_results.get(channel_name)
        return None

    def fit_analysis_range(self) -> None:
        if self._view_analysis_range_s is not None:
            self.plot_widget.setXRange(
                self._view_analysis_range_s[0] * 1.0e6,
                self._view_analysis_range_s[1] * 1.0e6,
                padding=0.0,
            )

    def set_corridors(
        self,
        corridors: Mapping[str, RidgeSearchConstraint],
        *,
        refresh: bool = True,
    ) -> None:
        """Store channel-local constraints and refresh only the current overlay."""
        self._corridors = corridors
        if not refresh:
            return
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._stft_results:
            self._render_channel(channel_name, fit_view=False)

    def set_colormap(self, name: str) -> None:
        """Apply a display-only colormap without recomputing any array."""
        normalized = normalize_spectrogram_colormap(name)
        blocker = QSignalBlocker(self.colormap_combo)
        index = self.colormap_combo.findData(normalized)
        self.colormap_combo.setCurrentIndex(max(index, 0))
        del blocker
        self.current_colormap_name = normalized
        self.color_bar.setColorMap(spectrogram_colormap(normalized))

    def _colormap_selected(self, _index: int) -> None:
        name = self.colormap_combo.currentData()
        if not isinstance(name, str):
            return
        self.set_colormap(name)
        self.colormap_changed.emit(self.current_colormap_name)

    def _render_channel(self, channel_name: str, *, fit_view: bool) -> None:
        stft_result = self._stft_results[channel_name]
        self.dispose_search_region_interactions()
        self.plot_widget.clear()
        self.plot_widget.addItem(self.image_item)
        self.current_image_db = _set_stft_image(
            self.image_item,
            stft_result,
            floor_db=self._floor_db,
        )
        self.color_bar.setLevels((self._floor_db, 0.0))
        self._install_search_band_lines(stft_result)
        analysis = self._analyses.get(channel_name)
        analysis_start = (
            self._view_analysis_range_s[0]
            if self._view_analysis_range_s is not None
            else None
        )
        analysis_end = (
            self._view_analysis_range_s[1]
            if self._view_analysis_range_s is not None
            else None
        )
        self.corridor_controller.set_context(
            channel_name,
            stft_result,
            self._corridors.get(channel_name),
            analysis_start_time_s=analysis_start,
            analysis_end_time_s=analysis_end,
            minimum_frequency_hz=(
                self._view_search_band_hz[0]
                if self._view_search_band_hz is not None
                else float(stft_result.frequency_hz[0])
            ),
            maximum_frequency_hz=(
                self._view_search_band_hz[1]
                if self._view_search_band_hz is not None
                else float(stft_result.frequency_hz[-1])
            ),
        )
        if fit_view:
            self.plot_widget.autoRange()
            if analysis is not None:
                self._fit_current_view(analysis)
            elif self._view_analysis_range_s is not None:
                self.plot_widget.setXRange(
                    self._view_analysis_range_s[0] * 1.0e6,
                    self._view_analysis_range_s[1] * 1.0e6,
                    padding=0.0,
                )

    def _clear_plot(self) -> None:
        self.dispose_search_region_interactions()
        self.plot_widget.clear()
        self.plot_widget.addItem(self.image_item)
        self.plot_widget.setTitle(self.tr("尚未计算时频图"), color="#666666")
        self.current_image_db = None
        self._search_lines = []
        self._search_time_lines = []
        self._search_region_roi = None
        self._search_frequency_grid_hz = None
        self._search_time_grid_s = None
        self.corridor_controller.detach_context()


class RidgeView(_ChannelView):
    """Overlay candidate, refined, and formal quality-gated ridge arrays."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.add_spectral_view_controls()
        self.fit_analysis_range_button.setVisible(False)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel(self.tr("结果来源")))
        self.result_source_combo = QComboBox()
        self.result_source_combo.setObjectName("ridgeResultSourceSelector")
        self.result_source_combo.currentIndexChanged.connect(
            self._result_source_changed
        )
        source_row.addWidget(self.result_source_combo)
        source_row.addStretch(1)
        self.root_layout.addLayout(source_row)
        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("ridgePlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("频率"), units="GHz")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.18)
        self.root_layout.addWidget(self.plot_widget, 1)
        self.quality_label = QLabel(self.tr("尚无质量状态。"))
        self.quality_label.setObjectName("ridgeQualitySummary")
        self.root_layout.addWidget(self.quality_label)
        self.current_colormap_name = DEFAULT_SPECTROGRAM_COLORMAP
        self.image_item: Any | None = None
        self.candidate_curve: Any | None = None
        self.refined_curve: Any | None = None
        self.formal_curve: Any | None = None
        self._automatic_analyses: Mapping[str, ChannelAnalysis] = {}
        self._guided_analyses: Mapping[str, ChannelAnalysis] = {}
        self._corridors: Mapping[str, RidgeSearchConstraint] = {}
        self._corridor_items: tuple[Any, Any, Any] | None = None

    @property
    def result_source(self) -> str:
        source = self.result_source_combo.currentData()
        return source if isinstance(source, str) else "automatic"

    def set_analyses(
        self,
        analyses: Mapping[str, ChannelAnalysis],
        *,
        relative_db_floor: float,
    ) -> None:
        """Compatibility entry: install an automatic-only result set."""
        self.set_result_sets(
            analyses,
            {},
            corridors={},
            relative_db_floor=relative_db_floor,
        )

    def set_result_sets(
        self,
        automatic_analyses: Mapping[str, ChannelAnalysis],
        guided_analyses: Mapping[str, ChannelAnalysis],
        *,
        corridors: Mapping[str, RidgeSearchConstraint],
        relative_db_floor: float,
        fit_view: bool = True,
    ) -> None:
        """Install independent automatic/guided results with explicit switching."""
        previous = self.result_source
        self._automatic_analyses = automatic_analyses
        self._guided_analyses = guided_analyses
        self._corridors = corridors
        blocker = QSignalBlocker(self.result_source_combo)
        self.result_source_combo.clear()
        if automatic_analyses:
            self.result_source_combo.addItem(self.tr("自动结果"), "automatic")
        if guided_analyses:
            self.result_source_combo.addItem(self.tr("人工范围结果"), "guided")
        index = self.result_source_combo.findData(previous)
        self.result_source_combo.setCurrentIndex(max(index, 0))
        del blocker
        self._apply_result_source(
            relative_db_floor=relative_db_floor,
            fit_view=fit_view,
        )

    def clear_results(self) -> None:
        self._automatic_analyses = {}
        self._guided_analyses = {}
        self._corridors = {}
        self.result_source_combo.clear()
        super().clear_results()

    def _result_source_changed(self, _index: int) -> None:
        self._apply_result_source(relative_db_floor=self._floor_db, fit_view=True)

    def _apply_result_source(
        self,
        *,
        relative_db_floor: float,
        fit_view: bool,
    ) -> None:
        previous_range = self.plot_widget.plotItem.vb.viewRange()
        analyses = (
            self._guided_analyses
            if self.result_source == "guided"
            else self._automatic_analyses
        )
        super().set_analyses(
            analyses,
            relative_db_floor=relative_db_floor,
        )
        if analyses and not fit_view:
            self.plot_widget.setXRange(*previous_range[0], padding=0.0)
            self.plot_widget.setYRange(*previous_range[1], padding=0.0)

    def set_colormap(self, name: str) -> None:
        """Apply the spectrogram background preference without rerunning science."""
        self.current_colormap_name = normalize_spectrogram_colormap(name)
        if self.image_item is not None:
            self.image_item.setColorMap(
                spectrogram_colormap(self.current_colormap_name)
            )

    def _render_channel(self, channel_name: str, *, fit_view: bool) -> None:
        analysis = self._analyses[channel_name]
        self.dispose_search_region_interactions()
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(12, 12))
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.image_item.setColorMap(
            spectrogram_colormap(self.current_colormap_name)
        )
        self.plot_widget.addItem(self.image_item)
        _set_image(self.image_item, analysis, floor_db=self._floor_db)
        self._install_search_band_lines(analysis.stft_result)
        self._corridor_items = None
        if self.result_source == "guided":
            constraint = self._corridors.get(channel_name)
            if constraint is not None:
                self._corridor_items = draw_static_corridor(
                    self.plot_widget,
                    constraint,
                    center_name=(
                        self.tr("人工有效搜索区域")
                        if isinstance(constraint, ManualFrequencyRegion)
                        else self.tr("旧版脊线走廊")
                    ),
                    stft_result=analysis.stft_result,
                    minimum_frequency_hz=(
                        analysis.ridge_result.minimum_frequency_hz
                    ),
                    maximum_frequency_hz=(
                        analysis.ridge_result.maximum_frequency_hz
                    ),
                )
        time_us = analysis.stft_result.time_s * 1e6
        self.candidate_curve = self.plot_widget.plot(
            time_us,
            analysis.ridge_result.frequency_hz * 1e-9,
            pen=None,
            symbol="o",
            symbolSize=3,
            symbolBrush="#D55E00",
            name=self.tr("离散候选峰"),
        )
        self.refined_curve = self.plot_widget.plot(
            time_us,
            analysis.working_frequency_hz * 1e-9,
            pen=pg.mkPen("#F0E442", width=1.2),
            connect="finite",
            name=self.tr("工作脊线"),
        )
        formal_frequency = analysis.signal_detection_result.refined_frequency_hz
        self.formal_curve = self.plot_widget.plot(
            time_us,
            formal_frequency * 1e-9,
            pen=pg.mkPen("#009E73", width=2.0),
            connect="finite",
            name=self.tr("正式可信脊线"),
        )
        counts = Counter(
            state.name for state in analysis.signal_detection_result.signal_states
        )
        summary = ", ".join(f"{name}={count}" for name, count in counts.items())
        working_counts = Counter(source.name for source in analysis.working_source)
        working_summary = ", ".join(
            f"{name}={count}" for name, count in working_counts.items()
        )
        self.quality_label.setText(
            self.tr("逐帧质量状态：{summary}；工作点来源：{working}").format(
                summary=summary,
                working=working_summary,
            )
        )
        if fit_view:
            self.plot_widget.autoRange()
            self._fit_current_view(analysis)

    def _clear_plot(self) -> None:
        self.dispose_search_region_interactions()
        self.plot_widget.clear()
        self.quality_label.setText(self.tr("尚无质量状态。"))
        self.image_item = None
        self.candidate_curve = None
        self.refined_curve = None
        self.formal_curve = None
        self._corridor_items = None
        self._search_lines = []
        self._search_time_lines = []
        self._search_region_roi = None
        self._search_frequency_grid_hz = None
        self._search_time_grid_s = None


class VelocityView(_ChannelView):
    """Show formal apparent velocity and an optional display-only curve."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fit_analysis_range_button.setToolTip(
            self.tr("将视图恢复到当前设定的分析时间范围。")
        )
        self.fit_result_range_button = QPushButton(self.tr("适合结果范围"))
        self.fit_result_range_button.setObjectName("fitResultRangeButton")
        self.fit_result_range_button.setToolTip(
            self.tr("将视图适配到当前显示的有效速度结果。")
        )
        self.fit_result_range_button.clicked.connect(self.fit_result_range)
        self.controls_layout.insertWidget(
            self.controls_layout.count() - 1,
            self.fit_result_range_button,
        )
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel(self.tr("结果来源")))
        self.result_source_combo = QComboBox()
        self.result_source_combo.setObjectName("velocityResultSourceSelector")
        self.result_source_combo.currentIndexChanged.connect(
            self._result_source_changed
        )
        source_row.addWidget(self.result_source_combo)
        source_row.addStretch(1)
        self.root_layout.addLayout(source_row)
        option_row = QHBoxLayout()
        self.display_velocity_check = QCheckBox(
            self.tr("正式显示速度（含事件前平台约定）")
        )
        self.display_velocity_check.setObjectName("displayVelocityCheck")
        self.display_velocity_check.setChecked(False)
        self.display_velocity_check.toggled.connect(self._rerender)
        self._export_preview_mode = False
        self._display_velocity_before_export_preview = False
        option_row.addWidget(self.display_velocity_check)
        option_row.addStretch(1)
        self.root_layout.addLayout(option_row)
        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("velocityPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("速度"), units="m/s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.22)
        self.plot_widget.plotItem.hideButtons()
        self.root_layout.addWidget(self.plot_widget, 1)
        self.formal_curve: Any | None = None
        self.apparent_curve: Any | None = None
        self.corrected_curve: Any | None = None
        self.display_curve: Any | None = None
        self.display_connector: Any | None = None
        self.event_reference_line: Any | None = None
        self._time_origin = ExportTimeOrigin.EVENT
        self._automatic_analyses: Mapping[str, ChannelAnalysis] = {}
        self._guided_analyses: Mapping[str, ChannelAnalysis] = {}
        self._available_channel_names: tuple[str, ...] = ()
        self.source_notice = QLabel()
        self.source_notice.setObjectName("velocityResultSourceNotice")
        self.source_notice.setWordWrap(True)
        self.source_notice.hide()
        self.root_layout.addWidget(self.source_notice)

    @property
    def result_source(self) -> str:
        source = self.result_source_combo.currentData()
        return source if isinstance(source, str) else "automatic"

    def select_result_target(self, result_source: str, channel_name: str) -> bool:
        """Select an existing mode/channel for export preview without recomputing."""
        source_index = self.result_source_combo.findData(result_source)
        if source_index < 0:
            self._clear_plot()
            self.source_notice.setText(
                self.tr("当前没有{source}分析结果。").format(
                    source=result_source
                )
            )
            self.source_notice.show()
            return False
        source_blocker = QSignalBlocker(self.result_source_combo)
        self.result_source_combo.setCurrentIndex(source_index)
        del source_blocker
        self._apply_result_source(
            relative_db_floor=self._floor_db,
            fit_view=True,
        )
        channel_index = self.channel_combo.findData(channel_name)
        if channel_index < 0:
            self._clear_plot()
            self.source_notice.setText(
                self.tr("当前预览中没有通道：{channel}").format(
                    channel=channel_name
                )
            )
            self.source_notice.show()
            return False
        channel_blocker = QSignalBlocker(self.channel_combo)
        self.channel_combo.setCurrentIndex(channel_index)
        del channel_blocker
        self._channel_changed(channel_index)
        return channel_name in self._analyses

    def set_export_preview_mode(self, enabled: bool) -> None:
        """Show the simple export's display-velocity curve while reviewing."""
        if enabled == self._export_preview_mode:
            return
        self._export_preview_mode = enabled
        if enabled:
            self._display_velocity_before_export_preview = (
                self.display_velocity_check.isChecked()
            )
            self.display_velocity_check.setChecked(True)
            self.display_velocity_check.setEnabled(False)
            self.display_velocity_check.setToolTip(
                self.tr(
                    "复核与导出使用 display_velocity_m_s 作为简表速度列；"
                    "此处固定显示同一数组。"
                )
            )
            return
        self.display_velocity_check.setEnabled(True)
        self.display_velocity_check.setToolTip("")
        self.display_velocity_check.setChecked(
            self._display_velocity_before_export_preview
        )

    def set_analyses(
        self,
        analyses: Mapping[str, ChannelAnalysis],
        *,
        relative_db_floor: float,
    ) -> None:
        self.set_result_sets(
            analyses,
            {},
            relative_db_floor=relative_db_floor,
            available_channel_names=tuple(analyses),
        )

    def set_result_sets(
        self,
        automatic_analyses: Mapping[str, ChannelAnalysis],
        guided_analyses: Mapping[str, ChannelAnalysis],
        *,
        relative_db_floor: float,
        fit_view: bool = True,
        available_channel_names: tuple[str, ...] | None = None,
    ) -> None:
        previous = self.result_source
        self._automatic_analyses = automatic_analyses
        self._guided_analyses = guided_analyses
        self._available_channel_names = (
            tuple(available_channel_names)
            if available_channel_names is not None
            else tuple(dict.fromkeys((*automatic_analyses, *guided_analyses)))
        )
        blocker = QSignalBlocker(self.result_source_combo)
        self.result_source_combo.clear()
        if automatic_analyses:
            self.result_source_combo.addItem(self.tr("自动结果"), "automatic")
        if guided_analyses:
            self.result_source_combo.addItem(self.tr("人工范围结果"), "guided")
        index = self.result_source_combo.findData(previous)
        self.result_source_combo.setCurrentIndex(max(index, 0))
        del blocker
        self._apply_result_source(
            relative_db_floor=relative_db_floor,
            fit_view=fit_view,
        )

    def set_time_origin(self, time_origin: ExportTimeOrigin) -> None:
        """Select an absolute or event-relative display axis without mutation."""
        if not isinstance(time_origin, ExportTimeOrigin):
            raise TypeError("time_origin must be an ExportTimeOrigin.")
        if time_origin is self._time_origin:
            return
        self._time_origin = time_origin
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            self._render_channel(channel_name, fit_view=True)

    def clear_results(self) -> None:
        self._automatic_analyses = {}
        self._guided_analyses = {}
        self._available_channel_names = ()
        self.result_source_combo.clear()
        self.source_notice.clear()
        self.source_notice.hide()
        super().clear_results()

    def _result_source_changed(self, _index: int) -> None:
        self._apply_result_source(relative_db_floor=self._floor_db, fit_view=True)

    def _apply_result_source(
        self,
        *,
        relative_db_floor: float,
        fit_view: bool,
    ) -> None:
        previous_range = self.plot_widget.plotItem.vb.viewRange()
        analyses = (
            self._guided_analyses
            if self.result_source == "guided"
            else self._automatic_analyses
        )
        self._set_source_channels(
            analyses,
            relative_db_floor=relative_db_floor,
            fit_view=fit_view,
        )
        if analyses and not fit_view:
            self.plot_widget.setXRange(*previous_range[0], padding=0.0)
            self.plot_widget.setYRange(*previous_range[1], padding=0.0)

    def _set_source_channels(
        self,
        analyses: Mapping[str, ChannelAnalysis],
        *,
        relative_db_floor: float,
        fit_view: bool,
    ) -> None:
        """Keep all loaded channels selectable even when one source is absent."""
        previous_channel = self.channel_combo.currentData()
        self._analyses = analyses
        self._floor_db = float(relative_db_floor)
        blocker = QSignalBlocker(self.channel_combo)
        self.channel_combo.clear()
        for channel_name in self._available_channel_names:
            self.channel_combo.addItem(channel_name, channel_name)
        index = self.channel_combo.findData(previous_channel)
        self.channel_combo.setCurrentIndex(max(index, 0))
        self.channel_combo.setEnabled(bool(self._available_channel_names))
        del blocker
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in analyses:
            self._render_channel(channel_name, fit_view=fit_view)
            self.channel_selection_changed.emit(channel_name)
        elif isinstance(channel_name, str):
            self._render_missing_channel(channel_name)

    def _channel_changed(self, _index: int) -> None:
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            self._render_channel(channel_name, fit_view=True)
            self.channel_selection_changed.emit(channel_name)
        elif isinstance(channel_name, str):
            self._render_missing_channel(channel_name)

    def _render_missing_channel(self, channel_name: str) -> None:
        """Show a source-specific absence message without disabling Velocity."""
        source = self.result_source
        source_name = (
            self.tr("人工范围结果")
            if source == "guided"
            else self.tr("自动结果")
        )
        self.source_notice.setText(
            self.tr("当前通道尚无{source}：{channel}").format(
                source=source_name,
                channel=channel_name,
            )
        )
        self.source_notice.show()
        self._clear_plot()

    def refresh_display_results(
        self,
        analyses: Mapping[str, ChannelAnalysis],
    ) -> None:
        """Replace display-only arrays while preserving channel selection."""
        if self.result_source == "guided":
            self._guided_analyses = analyses
        else:
            self._automatic_analyses = analyses
        self._analyses = analyses
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in analyses:
            self._render_channel(channel_name, fit_view=False)

    def _rerender(self, _checked: bool) -> None:
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            self._render_channel(channel_name, fit_view=False)

    def _render_channel(self, channel_name: str, *, fit_view: bool) -> None:
        analysis = self._analyses[channel_name]
        self.source_notice.clear()
        self.source_notice.hide()
        previous_range = self.plot_widget.plotItem.vb.viewRange()
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(12, 12))
        reference_s = analysis.signal_detection_result.manual_event_reference_time_s
        event_relative = (
            self._time_origin is ExportTimeOrigin.EVENT and reference_s is not None
        )
        time_s = analysis.stft_result.time_s
        if event_relative:
            assert reference_s is not None
            time_s = time_s - reference_s
        time_us = time_s * 1e6
        self.plot_widget.setLabel(
            "bottom",
            self.tr("相对起跳时间") if event_relative else self.tr("时间"),
            units="μs",
        )
        self.apparent_curve = self.plot_widget.plot(
            time_us,
            analysis.apparent_velocity_m_s,
            pen=pg.mkPen("#0072B2", width=1.4, style=pg.QtCore.Qt.DashLine),
            connect="finite",
            name=self.tr("正式表观速度"),
        )
        self.corrected_curve = self.plot_widget.plot(
            time_us,
            analysis.corrected_velocity_m_s,
            pen=pg.mkPen("#D55E00", width=2.0),
            connect="finite",
            name=self.tr("正式修正速度"),
        )
        self.formal_curve = self.corrected_curve
        self.display_curve = None
        self.display_connector = None
        self.event_reference_line = None
        if self.display_velocity_check.isChecked():
            self.display_curve = self.plot_widget.plot(
                time_us,
                analysis.display_velocity_m_s,
                pen=pg.mkPen("#6C5CE7", width=2.0),
                connect="finite",
                name=self.tr("正式显示速度（含事件前平台约定）"),
            )
            connector = display_velocity_connector_points(analysis)
            if connector is not None:
                connector_time_us, connector_velocity_m_s = connector
                if event_relative:
                    assert reference_s is not None
                    connector_time_us = connector_time_us - reference_s * 1.0e6
                self.display_connector = self.plot_widget.plot(
                    connector_time_us,
                    connector_velocity_m_s,
                    pen=pg.mkPen(
                        "#6C5CE7",
                        width=1.0,
                        style=pg.QtCore.Qt.DashLine,
                    ),
                    connect="all",
                )
                self.display_connector.setToolTip(
                    self.tr("正式显示速度（含事件前平台约定）")
                )
        if fit_view:
            self.plot_widget.autoRange()
            self._fit_current_view(analysis)
        else:
            self.plot_widget.setXRange(*previous_range[0], padding=0.0)
            self.plot_widget.setYRange(*previous_range[1], padding=0.0)

    def _fit_current_view(self, analysis: ChannelAnalysis) -> None:
        x_bounds = self._analysis_view_range_us(analysis)
        self.plot_widget.setXRange(*x_bounds, padding=0.0)
        bounds = finite_velocity_xy_view_range(
            self._visible_velocity_series(),
            x_limits=x_bounds,
        )
        if bounds is not None:
            self.plot_widget.setYRange(*bounds[1], padding=0.0)

    def fit_result_range(self) -> None:
        """Fit both axes to finite data from only the currently visible curves."""
        bounds = finite_velocity_xy_view_range(self._visible_velocity_series())
        if bounds is None:
            return
        self.plot_widget.setXRange(*bounds[0], padding=0.0)
        self.plot_widget.setYRange(*bounds[1], padding=0.0)

    def _analysis_view_range_us(
        self,
        analysis: ChannelAnalysis,
    ) -> tuple[float, float]:
        if self._view_analysis_range_s is None:
            start_us, end_us = analysis_view_range_us(analysis)
        else:
            start_us = self._view_analysis_range_s[0] * 1.0e6
            end_us = self._view_analysis_range_s[1] * 1.0e6
        reference_s = analysis.signal_detection_result.manual_event_reference_time_s
        if self._time_origin is ExportTimeOrigin.EVENT and reference_s is not None:
            shift_us = reference_s * 1.0e6
            return start_us - shift_us, end_us - shift_us
        return start_us, end_us

    def _visible_velocity_series(
        self,
    ) -> tuple[tuple[FloatArray, FloatArray], ...]:
        curves = (self.apparent_curve, self.corrected_curve, self.display_curve)
        series: list[tuple[FloatArray, FloatArray]] = []
        for curve in curves:
            if curve is None or not curve.isVisible():
                continue
            x_values, y_values = curve.getData()
            if x_values is None or y_values is None:
                continue
            series.append(
                (
                    np.asarray(x_values, dtype=np.float64),
                    np.asarray(y_values, dtype=np.float64),
                )
            )
        return tuple(series)

    def _clear_plot(self) -> None:
        self.plot_widget.clear()
        self.formal_curve = None
        self.apparent_curve = None
        self.corrected_curve = None
        self.display_curve = None
        self.display_connector = None
        self.event_reference_line = None


class ComparisonView(QWidget):
    """Overlay independent formal velocities without fusion or selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analyses: Mapping[str, ChannelAnalysis] = {}
        self._series: dict[str, ChannelAnalysis] = {}
        self._checks: dict[str, QCheckBox] = {}
        self.curves: dict[str, Any] = {}
        layout = QVBoxLayout(self)
        fit_row = QHBoxLayout()
        self.fit_analysis_range_button = QPushButton(
            self.tr("适合分析范围")
        )
        self.fit_analysis_range_button.setObjectName(
            "fitComparisonAnalysisRangeButton"
        )
        self.fit_analysis_range_button.clicked.connect(self.fit_analysis_range)
        fit_row.addWidget(self.fit_analysis_range_button)
        fit_row.addStretch(1)
        layout.addLayout(fit_row)
        self.controls = QHBoxLayout()
        layout.addLayout(self.controls)
        self.notice = QLabel()
        self.notice.setObjectName("comparisonResultNotice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)
        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("comparisonPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("表观速度"), units="m/s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.22)
        layout.addWidget(self.plot_widget, 1)

    def set_analyses(self, analyses: Mapping[str, ChannelAnalysis]) -> None:
        """Plot each real channel separately and expose visibility controls."""
        self.set_result_sets(analyses, {})

    def set_result_sets(
        self,
        automatic_analyses: Mapping[str, ChannelAnalysis],
        guided_analyses: Mapping[str, ChannelAnalysis],
    ) -> None:
        """Compare sources without claiming either result is more correct."""
        self.clear_results()
        self._analyses = automatic_analyses or guided_analyses
        self.plot_widget.addLegend(offset=(12, 12))
        series: list[tuple[str, str, ChannelAnalysis]] = []
        for channel_name, analysis in automatic_analyses.items():
            series_key = (
                f"automatic:{channel_name}" if guided_analyses else channel_name
            )
            label = (
                self.tr("{channel} — 自动结果").format(channel=channel_name)
                if guided_analyses
                else channel_name
            )
            series.append(
                (
                    series_key,
                    label,
                    analysis,
                )
            )
        for channel_name, analysis in guided_analyses.items():
            series.append(
                (
                    f"guided:{channel_name}",
                    self.tr("{channel} — 人工范围结果").format(
                        channel=channel_name
                    ),
                    analysis,
                )
            )
        for index, (series_key, label, analysis) in enumerate(series):
            check = QCheckBox(label)
            check.setChecked(True)
            self.controls.addWidget(check)
            curve = self.plot_widget.plot(
                analysis.stft_result.time_s * 1e6,
                analysis.corrected_velocity_m_s,
                pen=pg.mkPen(_COLORS[index % len(_COLORS)], width=1.8),
                connect="finite",
                name=label,
            )
            check.toggled.connect(curve.setVisible)
            self._checks[series_key] = check
            self.curves[series_key] = curve
            self._series[series_key] = analysis
        self.controls.addStretch(1)
        if len(series) == 1:
            self.notice.setText(self.tr("当前只有一个可比较结果。"))
            self.notice.show()
        else:
            self.notice.clear()
            self.notice.hide()
        self.plot_widget.autoRange()
        self.fit_analysis_range()

    def fit_analysis_range(self) -> None:
        """Restore analysis X and finite visible-channel velocity Y ranges."""
        if not self._analyses:
            return
        _fit_analysis_x(self.plot_widget, next(iter(self._analyses.values())))
        arrays = tuple(
            analysis.corrected_velocity_m_s
            for series_key, analysis in self._series.items()
            if self._checks[series_key].isChecked()
        )
        bounds = finite_velocity_view_range(arrays)
        if bounds is not None:
            self.plot_widget.setYRange(*bounds, padding=0.0)

    def clear_results(self) -> None:
        """Remove every stale channel curve and visibility control."""
        self._analyses = {}
        self._series.clear()
        self.plot_widget.clear()
        while self.controls.count():
            item = self.controls.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._checks.clear()
        self.curves.clear()
        self.notice.clear()
        self.notice.hide()


class QualitySummaryWidget(QWidget):
    """Tabulate per-channel formal state and diagnostic counts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.notice = QLabel(self.tr("尚未运行分析；当前没有正式质量结果。"))
        self.notice.setObjectName("qualityNotice")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("qualitySummaryTable")
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("通道"),
                self.tr("信号状态计数"),
                self.tr("MEASURED 帧"),
                self.tr("NaN 帧"),
                self.tr("频谱质量状态"),
                self.tr("连续性诊断"),
                self.tr("通道警告"),
            ]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

    def set_analyses(self, analyses: Mapping[str, ChannelAnalysis]) -> None:
        """Summarize only actual core flags and arrays."""
        self.table.setRowCount(len(analyses))
        for row, (channel_name, analysis) in enumerate(analyses.items()):
            detection = analysis.signal_detection_result
            state_counts = Counter(state.name for state in detection.signal_states)
            measured_count = state_counts.get(SignalState.MEASURED.name, 0)
            nan_count = int(np.count_nonzero(np.isnan(detection.apparent_velocity_m_s)))
            spectral_counts = Counter(
                status.name
                for status in analysis.spectral_quality_result.assessment_statuses
            )
            continuity_counts = Counter(
                status.name for status in analysis.continuity_result.continuity_statuses
            )
            warnings = []
            if measured_count == 0:
                warnings.append(self.tr("无 MEASURED 帧"))
            if nan_count:
                warnings.append(
                    self.tr("{count} 帧正式速度为 NaN").format(count=nan_count)
                )
            values = (
                channel_name,
                self._format_counts(state_counts),
                str(measured_count),
                str(nan_count),
                self._format_counts(spectral_counts),
                self._format_counts(continuity_counts),
                "; ".join(warnings) if warnings else self.tr("无额外警告"),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.notice.setText(
            self.tr("下表直接统计 public core 返回的逐帧状态和诊断枚举。")
        )

    def clear_results(self, message: str | None = None) -> None:
        """Clear stale quality statistics and show an explicit reason."""
        self.table.setRowCount(0)
        self.notice.setText(
            message
            if message is not None
            else self.tr("尚未运行分析；当前没有正式质量结果。")
        )

    @staticmethod
    def _format_counts(counts: Counter[str]) -> str:
        return ", ".join(f"{name}={count}" for name, count in counts.items())


__all__ = [
    "ComparisonView",
    "display_velocity_connector_points",
    "QualitySummaryWidget",
    "RidgeView",
    "SpectrogramView",
    "VelocityView",
    "analysis_view_range_us",
    "finite_velocity_xy_view_range",
    "finite_velocity_view_range",
    "relative_magnitude_db",
]
