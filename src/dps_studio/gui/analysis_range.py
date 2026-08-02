"""Non-destructive analysis-range controls using SI seconds internally."""

from __future__ import annotations

import math

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
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
    event_reference_confirmed = Signal(float)
    event_reference_cleared = Signal()
    candidate_adopt_requested = Signal(str, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bounds_s: tuple[float, float] | None = None
        self._confirmed_event_reference_s: float | None = None
        self._event_reference_draft_set = False
        self.candidate_buttons: dict[str, QPushButton] = {}
        self.candidate_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.full_range_label = QLabel(self.tr("未加载数据"))
        self.full_range_label.setObjectName("fullRangeLabel")
        self.start_spin = self._time_spin("analysisStartTimeUs")
        self.end_spin = self._time_spin("analysisEndTimeUs")
        self.event_reference_spin = self._time_spin("eventReferenceTimeUs")
        self.event_reference_spin.setToolTip(
            self.tr(
                "事件参考只用于显示与人工复核；必须显式确认，并位于当前数据和"
                "分析范围内。"
            )
        )
        form.addRow(self.tr("完整时间范围"), self.full_range_label)
        form.addRow(self.tr("分析起点"), self.start_spin)
        form.addRow(self.tr("分析终点"), self.end_spin)
        form.addRow(self.tr("事件参考时刻"), self.event_reference_spin)
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

        event_buttons = QHBoxLayout()
        self.apply_event_reference_button = QPushButton(
            self.tr("确认事件参考时刻")
        )
        self.apply_event_reference_button.setObjectName(
            "confirmEventReferenceButton"
        )
        self.clear_event_reference_button = QPushButton(
            self.tr("清除事件参考")
        )
        self.clear_event_reference_button.setObjectName(
            "clearEventReferenceButton"
        )
        event_buttons.addWidget(self.apply_event_reference_button)
        event_buttons.addWidget(self.clear_event_reference_button)
        layout.addLayout(event_buttons)

        self.event_reference_status_label = QLabel(self.tr("事件参考时刻未设置。"))
        self.event_reference_status_label.setObjectName(
            "eventReferenceStatusLabel"
        )
        self.event_reference_status_label.setWordWrap(True)
        layout.addWidget(self.event_reference_status_label)

        self.candidate_heading = QLabel(self.tr("检测候选（仅供参考）"))
        self.candidate_heading.setObjectName("eventCandidateHeading")
        layout.addWidget(self.candidate_heading)
        self.candidate_layout = QVBoxLayout()
        layout.addLayout(self.candidate_layout)

        self.status_label = QLabel(
            self.tr("图上范围与数值框双向同步；只有确认后才用于分析。")
        )
        self.status_label.setObjectName("plannedNotice")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.start_spin.valueChanged.connect(self._draft_changed)
        self.end_spin.valueChanged.connect(self._draft_changed)
        self.event_reference_spin.valueChanged.connect(
            self._event_reference_draft_changed
        )
        self.apply_button.clicked.connect(self.confirm_draft)
        self.full_range_button.clicked.connect(self.use_full_range)
        self.current_view_button.clicked.connect(self.current_view_requested)
        self.apply_event_reference_button.clicked.connect(
            self._confirm_event_reference
        )
        self.clear_event_reference_button.clicked.connect(
            self.event_reference_cleared
        )
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
        reference_blocker = QSignalBlocker(self.event_reference_spin)
        self.event_reference_spin.setRange(start_us, end_us)
        self.event_reference_spin.setValue(start_us)
        self.event_reference_spin.clear()
        del reference_blocker
        self.set_draft_range_s(start_time_s, end_time_s, emit=False)
        self.full_range_label.setText(f"{start_us:.9f} – {end_us:.9f} μs")
        self.status_label.setText(
            self.tr("请选择并确认分析范围；当前显示范围不会自动写入。")
        )
        self.show_event_reference_unset(self.tr("事件参考时刻未设置。"))
        self.clear_detected_candidates()
        self._set_enabled(True)

    def clear(self) -> None:
        """Clear bounds when a source is removed."""
        self._bounds_s = None
        self.full_range_label.setText(self.tr("未加载数据"))
        self.show_event_reference_unset(self.tr("事件参考时刻未设置。"))
        self.clear_detected_candidates()
        self._set_enabled(False)

    @property
    def confirmed_event_reference_s(self) -> float | None:
        """Return the last reference accepted by the owning window/session."""
        return self._confirmed_event_reference_s

    def show_event_reference(
        self,
        value_s: float,
        *,
        source_text: str,
    ) -> None:
        """Present one already validated SI reference without emitting it."""
        if self._bounds_s is None:
            return
        lower, upper = self._bounds_s
        if not math.isfinite(value_s) or not lower <= value_s <= upper:
            raise ValueError("Event reference must stay inside loaded data.")
        blocker = QSignalBlocker(self.event_reference_spin)
        self.event_reference_spin.setValue(value_s * 1e6)
        del blocker
        self._confirmed_event_reference_s = float(value_s)
        self._event_reference_draft_set = True
        self.event_reference_spin.setStyleSheet("")
        self.apply_event_reference_button.setEnabled(True)
        self.clear_event_reference_button.setEnabled(True)
        self.event_reference_status_label.setText(
            self.tr("事件参考已确认：{value:.9f} μs；来源：{source}").format(
                value=value_s * 1e6,
                source=source_text,
            )
        )

    def show_event_reference_unset(self, reason: str) -> None:
        """Present an explicit unset/invalid state without inventing a value."""
        self._confirmed_event_reference_s = None
        self._event_reference_draft_set = False
        blocker = QSignalBlocker(self.event_reference_spin)
        self.event_reference_spin.clear()
        del blocker
        self.event_reference_spin.setStyleSheet("border: 1px solid #b98224;")
        self.apply_event_reference_button.setEnabled(False)
        self.clear_event_reference_button.setEnabled(False)
        self.event_reference_status_label.setText(reason)

    def set_detected_candidates(
        self,
        candidates_s: dict[str, float | None],
    ) -> None:
        """Show independent spectral candidates with explicit adoption buttons."""
        self.clear_detected_candidates()
        tooltip = self.tr(
            "该时刻来自谱信号检测，只是候选参考，不代表已经确认的冲击到时。"
        )
        for channel_name, candidate_s in candidates_s.items():
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            if candidate_s is None:
                label = QLabel(
                    self.tr("{channel}：未检测到候选").format(
                        channel=channel_name
                    )
                )
                row_layout.addWidget(label)
            else:
                label = QLabel(f"{channel_name}   {candidate_s * 1e6:.9f} μs")
                label.setToolTip(tooltip)
                button = QPushButton(self.tr("采用该候选"))
                button.setObjectName(f"adoptEventCandidate_{channel_name}")
                button.setToolTip(tooltip)
                button.clicked.connect(
                    lambda _checked=False, channel=channel_name, value=candidate_s: (
                        self.candidate_adopt_requested.emit(channel, value)
                    )
                )
                row_layout.addWidget(label)
                row_layout.addWidget(button)
                self.candidate_buttons[channel_name] = button
            row_layout.addStretch(1)
            self.candidate_labels[channel_name] = label
            self.candidate_layout.addWidget(row)

    def clear_detected_candidates(self) -> None:
        """Remove candidates whenever results no longer match the session."""
        while self.candidate_layout.count():
            item = self.candidate_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.candidate_buttons.clear()
        self.candidate_labels.clear()

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

    def _event_reference_draft_changed(self, _value_us: float) -> None:
        if self._bounds_s is None:
            return
        self._event_reference_draft_set = True
        self.event_reference_spin.setStyleSheet("border: 1px solid #0b6fa4;")
        self.apply_event_reference_button.setEnabled(True)
        self.event_reference_status_label.setText(
            self.tr("事件参考草稿尚未确认；当前不会用于显示平台。")
        )

    def _confirm_event_reference(self) -> None:
        if self._bounds_s is None or not self._event_reference_draft_set:
            return
        self.event_reference_confirmed.emit(
            self.event_reference_spin.value() * 1e-6
        )

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
        self.event_reference_spin.setEnabled(enabled)
        self.apply_event_reference_button.setEnabled(
            enabled and self._event_reference_draft_set
        )
        self.clear_event_reference_button.setEnabled(
            enabled and self._confirmed_event_reference_s is not None
        )

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
