"""Independent acceleration plot with explicit waveform-fit and derivative modes."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from typing import Any

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget,
)

from dps_studio.core.models import SignalRecord
from dps_studio.core.physics.dechirp import DechirpResult, DechirpSettings
from dps_studio.core.physics.window_presets import window_configuration_name
from dps_studio.core.workflow import ChannelAnalysis
from dps_studio.core.workflow.acceleration import channel_acceleration, channel_dechirp
from dps_studio.gui.result_views import (
    FloatArray, _KinematicView, finite_velocity_xy_view_range,
)

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdv-dechirp")
_Request = tuple[SignalRecord, ChannelAnalysis, DechirpSettings]


class AccelerationView(_KinematicView):
    def __init__(self) -> None:
        super().__init__()
        self._records: Mapping[str, SignalRecord] = {}
        self._pending: tuple[_Request, Future[DechirpResult], Event] | None = None
        self._cached: tuple[_Request, DechirpResult] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll_dechirp)
        self.acceleration_curve: Any | None = None
        self.acceleration_notice = QLabel()
        self.acceleration_notice.setWordWrap(True)
        self.root_layout.addWidget(self.acceleration_notice)
        self.diagnostic_velocity_check.hide()
        self.plot_widget.setObjectName("accelerationPlot")

        self.method_combo = QComboBox()
        self.method_combo.addItem(self.tr("速度差分"), "velocity_derivative")
        self.method_combo.addItem(self.tr("Dechirp 直接估计"), "dechirp")
        method_row = QHBoxLayout()
        method_row.addWidget(self.method_combo)
        fit_visible = QPushButton(self.tr("适合可见区"))
        fit_visible.clicked.connect(self._fit_visible)
        method_row.addWidget(fit_visible)
        self.settings_toggle = QPushButton(self.tr("算法设置"))
        self.settings_toggle.setCheckable(True)
        method_row.addWidget(self.settings_toggle)
        method_row.addStretch()
        self.root_layout.insertLayout(2, method_row)

        self.acceleration_method_combo = QComboBox()
        self.acceleration_method_combo.addItem(self.tr("原始差分"), "raw")
        self.acceleration_method_combo.addItem(self.tr("局部线性拟合"), "local_linear")
        self.acceleration_window_spin = QDoubleSpinBox()
        self.acceleration_window_spin.setDecimals(3)
        self.acceleration_window_spin.setRange(0.001, 1000000)
        self.acceleration_window_spin.setValue(50)
        self.acceleration_window_spin.setSuffix(" ns")
        self.acceleration_window_spin.setKeyboardTracking(False)

        self.dechirp_samples_spin = QSpinBox()
        self.dechirp_samples_spin.setRange(64, 2048)
        self.dechirp_samples_spin.setSingleStep(128)
        self.dechirp_samples_spin.setValue(512)
        self.dechirp_samples_spin.setKeyboardTracking(False)
        self.dechirp_rate_spin = QDoubleSpinBox()
        self.dechirp_rate_spin.setRange(.01, 100)
        self.dechirp_rate_spin.setValue(1)
        self.dechirp_rate_spin.setSuffix(" ×10¹⁷ Hz/s")
        self.dechirp_rate_spin.setKeyboardTracking(False)
        self.dechirp_r2_spin = QDoubleSpinBox()
        self.dechirp_r2_spin.setRange(.05, .99)
        self.dechirp_r2_spin.setValue(.5)
        self.dechirp_r2_spin.setKeyboardTracking(False)
        self._settings_panel = QWidget()
        form = QFormLayout(self._settings_panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        for label, field in (
            (self.tr("差分方式"), self.acceleration_method_combo),
            (self.tr("局部拟合窗口"), self.acceleration_window_spin),
            (self.tr("波形窗口采样点"), self.dechirp_samples_spin),
            (self.tr("斜率搜索上限"), self.dechirp_rate_spin),
            (self.tr("最低拟合 R²"), self.dechirp_r2_spin),
        ):
            form.addRow(label, field)
        self._settings_form = form
        self.root_layout.insertWidget(3, self._settings_panel)
        self._settings_panel.hide()
        self.settings_toggle.toggled.connect(self._settings_panel.setVisible)
        self.method_combo.currentIndexChanged.connect(self._settings_changed)
        self.acceleration_method_combo.currentIndexChanged.connect(self._settings_changed)
        self.acceleration_window_spin.valueChanged.connect(self._settings_changed)
        self.dechirp_samples_spin.valueChanged.connect(self._settings_changed)
        self.dechirp_rate_spin.valueChanged.connect(self._settings_changed)
        self.dechirp_r2_spin.valueChanged.connect(self._settings_changed)
        self._settings_changed()
        self._set_acceleration_axis()

    @property
    def local_fit_window_s(self) -> float | None:
        if self.acceleration_method_combo.currentData() == "local_linear":
            return float(self.acceleration_window_spin.value()) * 1e-9
        return None

    @property
    def dechirp_settings(self) -> DechirpSettings:
        return DechirpSettings(self.dechirp_samples_spin.value(),
                               self.dechirp_rate_spin.value() * 1e17,
                               self.dechirp_r2_spin.value())

    def set_records(self, records: Mapping[str, SignalRecord]) -> None:
        self._records = records

    def cached_dechirp(
        self, record: SignalRecord, analysis: ChannelAnalysis,
    ) -> DechirpResult | None:
        key = (record, analysis, self.dechirp_settings)
        if self._cached is not None and self._cached[0] == key:
            return self._cached[1]
        return None

    def _settings_changed(self, _value: float = 0) -> None:
        dechirp = self.method_combo.currentData() == "dechirp"
        self._settings_form.setRowVisible(self.acceleration_method_combo, not dechirp)
        self._settings_form.setRowVisible(
            self.acceleration_window_spin, not dechirp and self.local_fit_window_s is not None,
        )
        for control in (self.dechirp_samples_spin, self.dechirp_rate_spin, self.dechirp_r2_spin):
            self._settings_form.setRowVisible(control, dechirp)
        channel = self.channel_combo.currentData()
        if isinstance(channel, str) and channel in self._analyses:
            self._render_channel(channel, fit_view=False)
            self._fit_visible()

    def _set_acceleration_axis(self) -> None:
        self.plot_widget.setLabel("left", self.tr("加速度"), units="10⁹ m/s²")
        axis = self.plot_widget.getAxis("left")
        axis.setSIPrefixEnableRanges(())
        axis.enableAutoSIPrefix(False)

    def _plot_quantity(self, analysis: ChannelAnalysis, time_us: FloatArray) -> None:
        self._set_acceleration_axis()
        self.acceleration_curve = None
        self.acceleration_notice.clear()
        self.plot_widget.addItem(
            pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#8a9aaa", width=1)),
            ignoreBounds=True,
        )
        if self.method_combo.currentData() == "dechirp":
            record = self._records.get(self.channel_combo.currentData())
            if record is None:
                self.cancel_dechirp()
                self.acceleration_notice.setText(self.tr("没有可用的原始波形。"))
                return
            cached = self.cached_dechirp(record, analysis)
            if cached is not None:
                self.cancel_dechirp()
                counts = Counter(cached.flags)
                self._draw(time_us, cached.apparent_acceleration_m_s2, "#0072B2", points=True)
                self.acceleration_notice.setText(self.tr(
                    "表观加速度 · {count}/{total} 点通过拟合检查"
                ).format(count=counts["accepted"], total=time_us.size))
                self.acceleration_notice.setToolTip(
                    self.tr("不应用角度或窗口修正。") + "\n"
                    + "\n".join(f"{key}: {count}" for key, count in sorted(counts.items()))
                )
            else:
                self.acceleration_notice.setText(self.tr("正在拟合原始波形…"))
                self.acceleration_notice.setToolTip("")
                if self.isVisible():
                    self._request_dechirp(record, analysis)
            return
        self.cancel_dechirp()
        derivative = channel_acceleration(analysis, window_s=self.local_fit_window_s)
        self._draw(time_us, derivative.acceleration_m_s2, "#007a72")
        config = analysis.working_velocity_correction_result.config
        source = (window_configuration_name(config.lif_model)
                  if config.window_correction_enabled else self.tr("无窗口修正"))
        self.acceleration_notice.setText(self.tr(
            "来源：最终速度（无符号） · {source} · 观测角 {angle:g}°"
        ).format(source=source, angle=math.degrees(config.measurement_angle_rad))
            + " · " + self.tr("{count}/{total} 点可计算").format(
                count=int(np.isfinite(derivative.acceleration_m_s2).sum()), total=time_us.size,
            ))
        self.acceleration_notice.setToolTip(self.tr(
            "无效区与显示平台留空。有限差分值不代表质量通过。"
        ))

    def _draw(
        self, time_us: FloatArray, acceleration: FloatArray, color: str, *, points: bool = False,
    ) -> None:
        self.acceleration_curve = self.plot_widget.plot(
            time_us, acceleration * 1e-9, pen=pg.mkPen(color, width=1.5), connect="finite",
            symbol="o" if points or np.isfinite(acceleration).sum() == 1 else None,
            symbolSize=4, symbolBrush=color, symbolPen=None,
        )

    def _request_dechirp(self, record: SignalRecord, analysis: ChannelAnalysis) -> None:
        key = (record, analysis, self.dechirp_settings)
        if self._pending is not None and self._pending[0] == key:
            return
        self.cancel_dechirp()
        stop = Event()
        future = _POOL.submit(channel_dechirp, record, analysis,
                              settings=key[2], cancelled=stop.is_set)
        self._pending = key, future, stop
        self._timer.start()

    def _poll_dechirp(self) -> None:
        if self._pending is None or not self._pending[1].done():
            return
        key, future, _ = self._pending
        self._pending = None
        self._timer.stop()
        try:
            self._cached = key, future.result()
        except (ValueError, RuntimeError, ArithmeticError) as exc:
            self.acceleration_notice.setText(self.tr("波形拟合失败：{reason}").format(reason=exc))
            return
        self._rerender(False)
        self._fit_visible()

    def cancel_dechirp(self) -> None:
        self._timer.stop()
        if self._pending is not None:
            _, future, stop = self._pending
            stop.set()
            future.cancel()
            self._pending = None

    def _visible_velocity_series(self) -> tuple[tuple[FloatArray, FloatArray], ...]:
        if self.acceleration_curve is None:
            return ()
        x, y = self.acceleration_curve.getData()
        return ((x, y),)

    def _fit_visible(self) -> None:
        lower, upper = self.plot_widget.getViewBox().viewRange()[0]
        bounds = finite_velocity_xy_view_range(
            self._visible_velocity_series(), x_limits=(lower, upper),
        )
        if bounds is not None:
            self.plot_widget.setYRange(*bounds[1], padding=0.0)

    def _clear_plot(self) -> None:
        super()._clear_plot()
        self.cancel_dechirp()
        self._cached = None
        self.acceleration_curve = None
        self.acceleration_notice.clear()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt virtual API
        super().showEvent(event)
        if self.method_combo.currentData() == "dechirp" and self.acceleration_curve is None:
            self._rerender(False)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt virtual API
        self.cancel_dechirp()
        super().hideEvent(event)
