"""Non-destructive analysis-range controls using SI seconds internally."""

from __future__ import annotations

import math

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dps_studio.gui.styles import configure_action_button_cursors


class AnalysisRangePanel(QWidget):
    """Synchronize a draft range in μs and emit only confirmed SI endpoints."""

    draft_range_changed = Signal(float, float)
    range_confirmed = Signal(float, float)
    current_view_requested = Signal()
    event_reference_confirmed = Signal(float)
    event_reference_cleared = Signal()
    candidate_detection_requested = Signal()
    candidate_adopt_requested = Signal(str, float)
    event_time_source_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bounds_s: tuple[float, float] | None = None
        self._confirmed_event_reference_s: float | None = None
        self._event_reference_draft_set = False
        self.candidate_buttons: dict[str, QPushButton] = {}
        self.candidate_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.form = form
        self.full_range_label = QLabel(self.tr("未加载数据"))
        self.full_range_label.setObjectName("fullRangeLabel")
        self.start_spin = self._time_spin("analysisStartTimeUs")
        self.end_spin = self._time_spin("analysisEndTimeUs")
        self.event_reference_spin = self._time_spin("eventReferenceTimeUs")
        self.event_reference_spin.setToolTip(
            self.tr(
                "手动事件参考使用实验绝对时间，必须位于当前分析范围内；"
                "事件参考完全可选。"
            )
        )
        form.addRow(self.tr("完整时间范围"), self.full_range_label)
        form.addRow(self.tr("分析起点"), self.start_spin)
        end_editor = QWidget()
        self.end_editor = end_editor
        end_layout = QHBoxLayout(end_editor)
        end_layout.setContentsMargins(0, 0, 0, 0)
        end_layout.addWidget(self.end_spin, 1)
        self.full_range_button = QPushButton(self.tr("重置"))
        self.full_range_button.setObjectName("resetFullAnalysisRangeButton")
        self.full_range_button.setToolTip(self.tr("重置为完整数据范围"))
        self.full_range_button.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        end_layout.addWidget(self.full_range_button)
        form.addRow(self.tr("分析终点"), end_editor)
        source_widget = QWidget()
        source_layout = QHBoxLayout(source_widget)
        source_layout.setContentsMargins(0, 0, 0, 0)
        self.unset_event_time_radio = QRadioButton(self.tr("不使用"))
        self.unset_event_time_radio.setObjectName("unsetEventTimeRadio")
        self.automatic_event_time_radio = QRadioButton(self.tr("自动候选"))
        self.automatic_event_time_radio.setObjectName("automaticEventTimeRadio")
        self.manual_event_time_radio = QRadioButton(self.tr("手动"))
        self.manual_event_time_radio.setObjectName("manualEventTimeRadio")
        self.event_time_button_group = QButtonGroup(self)
        self.event_time_button_group.setExclusive(True)
        self.event_time_button_group.addButton(self.unset_event_time_radio)
        self.event_time_button_group.addButton(self.automatic_event_time_radio)
        self.event_time_button_group.addButton(self.manual_event_time_radio)
        self.unset_event_time_radio.setChecked(True)
        source_layout.addWidget(self.unset_event_time_radio)
        source_layout.addWidget(self.automatic_event_time_radio)
        source_layout.addWidget(self.manual_event_time_radio)
        form.addRow(self.tr("事件参考（可选）"), source_widget)
        form.addRow(self.tr("手动起跳时间"), self.event_reference_spin)
        layout.addLayout(form)

        event_buttons = QHBoxLayout()
        # Hidden compatibility hook for older GUI automation; the production
        # workflow commits the manual value directly.
        self.apply_event_reference_button = QPushButton(
            self.tr("确认参考")
        )
        self.apply_event_reference_button.setObjectName(
            "confirmEventReferenceButton"
        )
        self.apply_event_reference_button.hide()
        self.detect_candidates_button = QPushButton(self.tr("检测候选"))
        self.detect_candidates_button.setObjectName("detectEventCandidatesButton")
        self.detect_candidates_button.setToolTip(
            self.tr("运行现有自动分析链以生成仅供参考的事件候选；不会自动确认。")
        )
        self.clear_event_reference_button = QPushButton(
            self.tr("清除")
        )
        self.clear_event_reference_button.setObjectName(
            "clearEventReferenceButton"
        )
        event_buttons.addWidget(self.detect_candidates_button)
        event_buttons.addWidget(self.clear_event_reference_button)
        layout.addLayout(event_buttons)

        self.event_reference_status_label = QLabel(self.tr("事件参考时刻未设置。"))
        self.event_reference_status_label.setObjectName(
            "eventReferenceStatusLabel"
        )
        self.event_reference_status_label.setWordWrap(True)
        layout.addWidget(self.event_reference_status_label)

        self.candidate_heading = QLabel(self.tr("推荐候选（仅供参考）"))
        self.candidate_heading.setObjectName("eventCandidateHeading")
        layout.addWidget(self.candidate_heading)
        self.candidate_layout = QVBoxLayout()
        layout.addLayout(self.candidate_layout)

        # Hidden compatibility hook; spin edits and drag release now commit.
        self.apply_button = QPushButton(self.tr("确认分析范围"), self)
        self.apply_button.setObjectName("confirmAnalysisRangeButton")
        self.apply_button.hide()

        self.status_label = QLabel(
            self.tr("图上范围与数值框双向同步；拖动释放或数值编辑即生效。")
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
        self.apply_event_reference_button.clicked.connect(
            self._confirm_event_reference
        )
        self.clear_event_reference_button.clicked.connect(
            self.event_reference_cleared
        )
        self.automatic_event_time_radio.toggled.connect(
            self._event_time_mode_toggled
        )
        self.unset_event_time_radio.toggled.connect(self._event_time_mode_toggled)
        self.manual_event_time_radio.toggled.connect(self._event_time_mode_toggled)
        self.detect_candidates_button.clicked.connect(
            self.candidate_detection_requested
        )
        self._set_enabled(False)

    def set_analysis_range_controls_visible(self, visible: bool) -> None:
        """Hide legacy time-crop controls while retaining event review controls."""
        range_widgets = (
            self.full_range_label,
            self.start_spin,
            self.end_editor,
            self.apply_button,
            self.status_label,
        )
        for widget in range_widgets:
            widget.setVisible(visible)
            label = self.form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)

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
            self.tr("拖动范围边界并释放，或直接编辑数值，即可写入分析范围。")
        )
        self.show_event_reference_unset(self.tr("事件参考时刻未设置。"))
        self.clear_detected_candidates()
        self._set_enabled(True)
        self.set_event_time_source("unset")

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
        self.clear_event_reference_button.setEnabled(
            not self.unset_event_time_radio.isChecked()
        )
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

    def set_event_time_source(self, source: str) -> None:
        """Synchronize Automatic/Manual controls without emitting a request."""
        if source not in {"unset", "automatic", "manual"}:
            raise ValueError("source must be 'unset', 'automatic', or 'manual'.")
        blockers = [
            QSignalBlocker(self.unset_event_time_radio),
            QSignalBlocker(self.automatic_event_time_radio),
            QSignalBlocker(self.manual_event_time_radio),
        ]
        manual = source == "manual"
        self.unset_event_time_radio.setChecked(source == "unset")
        self.automatic_event_time_radio.setChecked(source == "automatic")
        self.manual_event_time_radio.setChecked(manual)
        self.event_reference_spin.setEnabled(manual and self._bounds_s is not None)
        self.clear_event_reference_button.setEnabled(
            source != "unset" and self._confirmed_event_reference_s is not None
        )
        del blockers

    def set_detected_candidates(
        self,
        candidates_s: dict[str, float | None],
        compatibility_candidates_s: dict[str, float | None] | None = None,
    ) -> None:
        """Show recommended candidates while internal classifications stay hidden."""
        self.clear_detected_candidates()
        compatibility = compatibility_candidates_s or {}
        tooltip = self.tr(
            "该时刻来自稳健的事件级自动候选；仅供参考，必须由用户显式采用，"
            "不代表物理真值或已确认的冲击到时。"
        )
        for channel_name, candidate_s in candidates_s.items():
            compatibility_s = compatibility.get(channel_name)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            if candidate_s is None:
                if compatibility_s is None:
                    text = self.tr("{channel}：未检测到可采用的推荐候选").format(
                        channel=channel_name
                    )
                else:
                    text = self.tr(
                        "{channel}：未检测到可采用的推荐候选"
                    ).format(channel=channel_name)
                label = QLabel(text)
                if compatibility_s is not None:
                    label.setToolTip(
                        self.tr(
                            "详细诊断中存在较弱兼容候选 {value:.9f} μs；"
                            "它不满足推荐候选条件，不能在此采用。"
                        ).format(value=compatibility_s * 1e6)
                    )
                row_layout.addWidget(label)
            else:
                label = QLabel(
                    f"{channel_name}   {candidate_s * 1e6:.9f} μs"
                )
                label.setToolTip(tooltip)
                button = QPushButton(self.tr("选择候选"))
                button.setObjectName(f"adoptEventCandidate_{channel_name}")
                button.setToolTip(tooltip)
                button.clicked.connect(
                    lambda _checked=False, channel=channel_name, value=candidate_s: (
                        self.candidate_adopt_requested.emit(channel, value)
                    )
                )
                configure_action_button_cursors(button)
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
        """Reset and immediately commit the complete data range."""
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
            self.range_confirmed.emit(start, end)
            self.status_label.setText(
                self.tr("分析范围已更新：{start:.9f} – {end:.9f} μs").format(
                    start=start * 1e6,
                    end=end * 1e6,
                )
            )

    def _event_reference_draft_changed(self, _value_us: float) -> None:
        if self._bounds_s is None:
            return
        self._event_reference_draft_set = True
        self.event_reference_spin.setStyleSheet("border: 1px solid #0b6fa4;")
        self.apply_event_reference_button.setEnabled(True)
        if self.manual_event_time_radio.isChecked():
            self.event_reference_confirmed.emit(
                self.event_reference_spin.value() * 1e-6
            )

    def _confirm_event_reference(self) -> None:
        if self._bounds_s is None or not self._event_reference_draft_set:
            return
        self.set_event_time_source("manual")
        self.event_reference_confirmed.emit(
            self.event_reference_spin.value() * 1e-6
        )

    def _event_time_mode_toggled(self, checked: bool) -> None:
        if not checked or self._bounds_s is None:
            return
        manual = self.manual_event_time_radio.isChecked()
        self.event_reference_spin.setEnabled(manual)
        if manual:
            source = "manual"
        elif self.automatic_event_time_radio.isChecked():
            source = "automatic"
        else:
            source = "unset"
        self.event_time_source_changed.emit(source)
        if manual:
            self._event_reference_draft_set = True
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
        self.detect_candidates_button.setEnabled(enabled)
        self.event_reference_spin.setEnabled(
            enabled and self.manual_event_time_radio.isChecked()
        )
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
