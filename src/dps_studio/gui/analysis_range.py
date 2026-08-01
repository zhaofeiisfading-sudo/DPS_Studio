"""Non-destructive analysis-range controls using SI seconds internally."""

from __future__ import annotations

import math

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AnalysisRangePanel(QWidget):
    """Synchronize a draft range in μs and emit only confirmed SI endpoints."""

    draft_range_changed = Signal(float, float)
    range_confirmed = Signal(float, float)
    current_view_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bounds_s: tuple[float, float] | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.full_range_label = QLabel(self.tr("未加载数据"))
        self.full_range_label.setObjectName("fullRangeLabel")
        self.start_spin = self._time_spin("analysisStartTimeUs")
        self.end_spin = self._time_spin("analysisEndTimeUs")
        form.addRow(self.tr("完整时间范围"), self.full_range_label)
        form.addRow(self.tr("分析起点"), self.start_spin)
        form.addRow(self.tr("分析终点"), self.end_spin)
        layout.addLayout(form)

        self.apply_button = QPushButton(self.tr("确认分析范围"))
        self.apply_button.setObjectName("confirmAnalysisRangeButton")
        self.full_range_button = QPushButton(self.tr("使用完整范围"))
        self.full_range_button.setObjectName("useFullRangeButton")
        self.current_view_button = QPushButton(self.tr("使用当前显示范围"))
        self.current_view_button.setObjectName("useCurrentViewButton")
        layout.addWidget(self.apply_button)
        layout.addWidget(self.full_range_button)
        layout.addWidget(self.current_view_button)

        self.status_label = QLabel(
            self.tr("图上范围与数值框双向同步；只有确认后才用于分析。")
        )
        self.status_label.setObjectName("plannedNotice")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.start_spin.valueChanged.connect(self._draft_changed)
        self.end_spin.valueChanged.connect(self._draft_changed)
        self.apply_button.clicked.connect(self.confirm_draft)
        self.full_range_button.clicked.connect(self.use_full_range)
        self.current_view_button.clicked.connect(self.current_view_requested)
        self._set_enabled(False)

    @property
    def bounds_s(self) -> tuple[float, float] | None:
        """Return current data bounds in seconds."""
        return self._bounds_s

    @property
    def draft_range_s(self) -> tuple[float, float] | None:
        """Return the displayed draft in seconds without confirming it."""
        if self._bounds_s is None:
            return None
        return self.start_spin.value() * 1e-6, self.end_spin.value() * 1e-6

    def set_data_bounds(self, start_time_s: float, end_time_s: float) -> None:
        """Set common record bounds and initialize an unconfirmed full draft."""
        self._validate_range(start_time_s, end_time_s)
        self._bounds_s = float(start_time_s), float(end_time_s)
        start_us = start_time_s * 1e6
        end_us = end_time_s * 1e6
        for spin in (self.start_spin, self.end_spin):
            blocker = QSignalBlocker(spin)
            spin.setRange(start_us, end_us)
            del blocker
        self.set_draft_range_s(start_time_s, end_time_s, emit=False)
        self.full_range_label.setText(f"{start_us:.9f} – {end_us:.9f} μs")
        self.status_label.setText(
            self.tr("请选择并确认分析范围；当前显示范围不会自动写入。")
        )
        self._set_enabled(True)

    def clear(self) -> None:
        """Clear bounds when a source is removed."""
        self._bounds_s = None
        self.full_range_label.setText(self.tr("未加载数据"))
        self._set_enabled(False)

    def set_draft_range_s(
        self,
        start_time_s: float,
        end_time_s: float,
        *,
        emit: bool = True,
    ) -> None:
        """Update μs controls from an SI range, clamped to loaded bounds."""
        if self._bounds_s is None:
            return
        lower, upper = self._bounds_s
        start = max(lower, min(float(start_time_s), upper))
        end = max(lower, min(float(end_time_s), upper))
        if start >= end:
            return
        start_blocker = QSignalBlocker(self.start_spin)
        end_blocker = QSignalBlocker(self.end_spin)
        self.start_spin.setValue(start * 1e6)
        self.end_spin.setValue(end * 1e6)
        del start_blocker, end_blocker
        self._set_valid(True)
        if emit:
            self.draft_range_changed.emit(start, end)

    def confirm_range_s(self, start_time_s: float, end_time_s: float) -> bool:
        """Set and confirm one bounded range, returning whether it was valid."""
        if self._bounds_s is None:
            return False
        lower, upper = self._bounds_s
        start = max(lower, float(start_time_s))
        end = min(upper, float(end_time_s))
        if not math.isfinite(start) or not math.isfinite(end) or start >= end:
            self._set_valid(False)
            return False
        self.set_draft_range_s(start, end)
        self.range_confirmed.emit(start, end)
        self.status_label.setText(
            self.tr("分析范围已确认：{start:.9f} – {end:.9f} μs").format(
                start=start * 1e6,
                end=end * 1e6,
            )
        )
        return True

    def confirm_draft(self) -> None:
        """Confirm the numeric draft after validating strict endpoint order."""
        draft = self.draft_range_s
        if draft is not None:
            self.confirm_range_s(*draft)

    def use_full_range(self) -> None:
        """Confirm the full common data range."""
        if self._bounds_s is not None:
            self.confirm_range_s(*self._bounds_s)

    def _draft_changed(self, _value: float) -> None:
        draft = self.draft_range_s
        if draft is None:
            return
        start, end = draft
        valid = start < end
        self._set_valid(valid)
        if valid:
            self.draft_range_changed.emit(start, end)

    def _set_valid(self, valid: bool) -> None:
        self.apply_button.setEnabled(valid and self._bounds_s is not None)
        style = "" if valid else "border: 1px solid #b94040;"
        self.start_spin.setStyleSheet(style)
        self.end_spin.setStyleSheet(style)

    def _set_enabled(self, enabled: bool) -> None:
        self.start_spin.setEnabled(enabled)
        self.end_spin.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        self.full_range_button.setEnabled(enabled)
        self.current_view_button.setEnabled(enabled)

    @staticmethod
    def _validate_range(start_time_s: float, end_time_s: float) -> None:
        if (
            not math.isfinite(start_time_s)
            or not math.isfinite(end_time_s)
            or start_time_s >= end_time_s
        ):
            raise ValueError("Data bounds must be finite and strictly ordered.")

    @staticmethod
    def _time_spin(object_name: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName(object_name)
        spin.setDecimals(9)
        spin.setSuffix(" μs")
        spin.setKeyboardTracking(False)
        return spin


__all__ = ["AnalysisRangePanel"]
