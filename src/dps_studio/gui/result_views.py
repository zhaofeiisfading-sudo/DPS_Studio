"""PyQtGraph views backed only by public core ``ChannelAnalysis`` arrays."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from numpy.typing import NDArray
from PySide6.QtCore import QSignalBlocker, QRectF, Signal
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

from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import ChannelAnalysis
from dps_studio.gui.display_preferences import (
    DEFAULT_SPECTROGRAM_COLORMAP,
    normalize_spectrogram_colormap,
    spectrogram_colormap,
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


def _fit_analysis_x(plot_widget: Any, analysis: ChannelAnalysis) -> None:
    start_us, end_us = analysis_view_range_us(analysis)
    plot_widget.setXRange(start_us, end_us, padding=0.0)


def relative_magnitude_db(
    analysis: ChannelAnalysis,
    *,
    floor_db: float,
) -> FloatArray:
    """Return exact ``20 log10(|spectrum| / max|spectrum|)`` display values."""
    magnitude = np.abs(analysis.stft_result.spectrum)
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
    stft = analysis.stft_result
    display = relative_magnitude_db(analysis, floor_db=floor_db)
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


def _add_search_band(plot_widget: Any, analysis: ChannelAnalysis) -> list[Any]:
    ridge = analysis.ridge_result
    lines = []
    for frequency_hz in (ridge.minimum_frequency_hz, ridge.maximum_frequency_hz):
        line = pg.InfiniteLine(
            pos=frequency_hz * 1e-9,
            angle=0,
            pen=pg.mkPen("#555555", width=1.0, style=pg.QtCore.Qt.DashLine),
        )
        plot_widget.addItem(line)
        lines.append(line)
    return lines


class _ChannelView(QWidget):
    """Small shared channel selector for independent analysis results."""

    plot_widget: Any

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analyses: Mapping[str, ChannelAnalysis] = {}
        self._floor_db = -60.0
        self.root_layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(self.tr("显示通道")))
        self.channel_combo = QComboBox()
        self.channel_combo.setObjectName("analysisChannelSelector")
        self.channel_combo.currentIndexChanged.connect(self._channel_changed)
        controls.addWidget(self.channel_combo)
        self.fit_analysis_range_button = QPushButton(
            self.tr("适合分析范围")
        )
        self.fit_analysis_range_button.setObjectName("fitAnalysisRangeButton")
        self.fit_analysis_range_button.clicked.connect(self.fit_analysis_range)
        controls.addWidget(self.fit_analysis_range_button)
        controls.addStretch(1)
        self.root_layout.addLayout(controls)

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
            self._render_channel(next(iter(analyses)), fit_view=True)

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

    def fit_analysis_range(self) -> None:
        """Restore X to the confirmed analysis range for the current channel."""
        channel_name = self.channel_combo.currentData()
        if isinstance(channel_name, str) and channel_name in self._analyses:
            self._fit_current_view(self._analyses[channel_name])

    def _fit_current_view(self, analysis: ChannelAnalysis) -> None:
        _fit_analysis_x(self.plot_widget, analysis)

    def _render_channel(self, channel_name: str, *, fit_view: bool) -> None:
        raise NotImplementedError

    def _clear_plot(self) -> None:
        raise NotImplementedError


class SpectrogramView(_ChannelView):
    """Render a channel's exact STFT coefficients as relative magnitude dB."""

    colormap_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self._search_lines: list[Any] = []

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
        analysis = self._analyses[channel_name]
        self.plot_widget.clear()
        self.plot_widget.addItem(self.image_item)
        self.current_image_db = _set_image(
            self.image_item,
            analysis,
            floor_db=self._floor_db,
        )
        self.color_bar.setLevels((self._floor_db, 0.0))
        self._search_lines = _add_search_band(self.plot_widget, analysis)
        if fit_view:
            self.plot_widget.autoRange()
            self._fit_current_view(analysis)

    def _clear_plot(self) -> None:
        self.plot_widget.clear()
        self.plot_widget.addItem(self.image_item)
        self.current_image_db = None
        self._search_lines = []


class RidgeView(_ChannelView):
    """Overlay candidate, refined, and formal quality-gated ridge arrays."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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

    def set_colormap(self, name: str) -> None:
        """Apply the spectrogram background preference without rerunning science."""
        self.current_colormap_name = normalize_spectrogram_colormap(name)
        if self.image_item is not None:
            self.image_item.setColorMap(
                spectrogram_colormap(self.current_colormap_name)
            )

    def _render_channel(self, channel_name: str, *, fit_view: bool) -> None:
        analysis = self._analyses[channel_name]
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(12, 12))
        self.image_item = pg.ImageItem(axisOrder="row-major")
        self.image_item.setColorMap(
            spectrogram_colormap(self.current_colormap_name)
        )
        self.plot_widget.addItem(self.image_item)
        _set_image(self.image_item, analysis, floor_db=self._floor_db)
        _add_search_band(self.plot_widget, analysis)
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
            analysis.refined_result.refined_frequency_hz * 1e-9,
            pen=pg.mkPen("#F0E442", width=1.2),
            connect="finite",
            name=self.tr("亚频点精修脊线"),
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
        self.quality_label.setText(
            self.tr("逐帧质量状态：{summary}").format(summary=summary)
        )
        if fit_view:
            self.plot_widget.autoRange()
            self._fit_current_view(analysis)

    def _clear_plot(self) -> None:
        self.plot_widget.clear()
        self.quality_label.setText(self.tr("尚无质量状态。"))
        self.image_item = None
        self.candidate_curve = None
        self.refined_curve = None
        self.formal_curve = None


class VelocityView(_ChannelView):
    """Show formal apparent velocity and an optional display-only curve."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        option_row = QHBoxLayout()
        self.display_velocity_check = QCheckBox(self.tr("显示速度（非正式结果）"))
        self.display_velocity_check.setObjectName("displayVelocityCheck")
        self.display_velocity_check.setChecked(False)
        self.display_velocity_check.toggled.connect(self._rerender)
        option_row.addWidget(self.display_velocity_check)
        self.corrected_velocity_control = QPushButton(self.tr("窗口修正尚未接入"))
        self.corrected_velocity_control.setObjectName("correctedVelocityControl")
        self.corrected_velocity_control.setEnabled(False)
        option_row.addWidget(self.corrected_velocity_control)
        option_row.addStretch(1)
        self.root_layout.addLayout(option_row)
        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("velocityPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("表观速度"), units="m/s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.22)
        self.root_layout.addWidget(self.plot_widget, 1)
        self.formal_curve: Any | None = None
        self.display_curve: Any | None = None

    def refresh_display_results(
        self,
        analyses: Mapping[str, ChannelAnalysis],
    ) -> None:
        """Replace display-only arrays while preserving channel selection."""
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
        previous_range = self.plot_widget.plotItem.vb.viewRange()
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(12, 12))
        time_us = analysis.stft_result.time_s * 1e6
        formal_velocity = analysis.signal_detection_result.apparent_velocity_m_s
        self.formal_curve = self.plot_widget.plot(
            time_us,
            formal_velocity,
            pen=pg.mkPen("#0072B2", width=2.0),
            connect="finite",
            name=self.tr("正式表观速度"),
        )
        self.display_curve = None
        if self.display_velocity_check.isChecked():
            self.display_curve = self.plot_widget.plot(
                time_us,
                analysis.display_velocity_m_s,
                pen=pg.mkPen("#777777", width=1.2, style=pg.QtCore.Qt.DashLine),
                connect="finite",
                name=self.tr("显示速度（仅显示）"),
            )
        if fit_view:
            self.plot_widget.autoRange()
            self._fit_current_view(analysis)
        else:
            self.plot_widget.setXRange(*previous_range[0], padding=0.0)
            self.plot_widget.setYRange(*previous_range[1], padding=0.0)

    def _fit_current_view(self, analysis: ChannelAnalysis) -> None:
        super()._fit_current_view(analysis)
        arrays = [analysis.signal_detection_result.apparent_velocity_m_s]
        if self.display_velocity_check.isChecked():
            arrays.append(analysis.display_velocity_m_s)
        bounds = finite_velocity_view_range(tuple(arrays))
        if bounds is not None:
            self.plot_widget.setYRange(*bounds, padding=0.0)

    def _clear_plot(self) -> None:
        self.plot_widget.clear()
        self.formal_curve = None
        self.display_curve = None


class ComparisonView(QWidget):
    """Overlay independent formal velocities without fusion or selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._analyses: Mapping[str, ChannelAnalysis] = {}
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
        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setObjectName("comparisonPlot")
        self.plot_widget.setLabel("bottom", self.tr("时间"), units="μs")
        self.plot_widget.setLabel("left", self.tr("表观速度"), units="m/s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.22)
        layout.addWidget(self.plot_widget, 1)

    def set_analyses(self, analyses: Mapping[str, ChannelAnalysis]) -> None:
        """Plot each real channel separately and expose visibility controls."""
        self.clear_results()
        self._analyses = analyses
        self.plot_widget.addLegend(offset=(12, 12))
        for index, (channel_name, analysis) in enumerate(analyses.items()):
            check = QCheckBox(channel_name)
            check.setChecked(True)
            self.controls.addWidget(check)
            curve = self.plot_widget.plot(
                analysis.stft_result.time_s * 1e6,
                analysis.signal_detection_result.apparent_velocity_m_s,
                pen=pg.mkPen(_COLORS[index % len(_COLORS)], width=1.8),
                connect="finite",
                name=channel_name,
            )
            check.toggled.connect(curve.setVisible)
            self._checks[channel_name] = check
            self.curves[channel_name] = curve
        self.controls.addStretch(1)
        self.plot_widget.autoRange()
        self.fit_analysis_range()

    def fit_analysis_range(self) -> None:
        """Restore analysis X and finite visible-channel velocity Y ranges."""
        if not self._analyses:
            return
        _fit_analysis_x(self.plot_widget, next(iter(self._analyses.values())))
        arrays = tuple(
            analysis.signal_detection_result.apparent_velocity_m_s
            for channel_name, analysis in self._analyses.items()
            if self._checks[channel_name].isChecked()
        )
        bounds = finite_velocity_view_range(arrays)
        if bounds is not None:
            self.plot_widget.setYRange(*bounds, padding=0.0)

    def clear_results(self) -> None:
        """Remove every stale channel curve and visibility control."""
        self._analyses = {}
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
    "QualitySummaryWidget",
    "RidgeView",
    "SpectrogramView",
    "VelocityView",
    "analysis_view_range_us",
    "finite_velocity_view_range",
    "relative_magnitude_db",
]
