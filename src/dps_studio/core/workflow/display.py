"""Display-only velocity construction with no formal-measurement mutation."""

from __future__ import annotations

import math
from dataclasses import replace
from numbers import Real

import numpy as np

from dps_studio.core.quality import SignalState
from dps_studio.core.workflow.models import ChannelAnalysis, FloatArray


PRE_EVENT_DISPLAY_ORIGIN = "configured_pre_event_display_velocity_only"


def build_display_velocity(
    time_s: FloatArray,
    signal_states: tuple[SignalState, ...],
    formal_apparent_velocity_m_s: FloatArray,
    *,
    manual_event_reference_time_s: float | None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    enable_pre_event_display: bool,
    pre_event_display_velocity_m_s: float = 0.0,
) -> tuple[FloatArray, tuple[str, ...]]:
    """Build a separate display array from an explicit event reference.

    A formal ``MEASURED`` frame always retains its formal apparent velocity.
    Only non-measured frames inside the explicit analysis range and strictly
    before ``manual_event_reference_time_s`` receive the configured
    display-only platform. Every post-event invalid frame remains NaN. A
    reference outside the active analysis/data domain produces no platform.
    """
    if not isinstance(enable_pre_event_display, bool):
        raise TypeError("enable_pre_event_display must be a boolean.")
    platform_velocity = _finite_velocity(pre_event_display_velocity_m_s)
    manual_reference = _optional_finite_reference(
        manual_event_reference_time_s,
        field_name="manual_event_reference_time_s",
    )
    analysis_start = _optional_finite_reference(
        analysis_start_time_s,
        field_name="analysis_start_time_s",
    )
    analysis_end = _optional_finite_reference(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )
    time = np.asarray(time_s, dtype=np.float64)
    formal = np.asarray(formal_apparent_velocity_m_s, dtype=np.float64)
    states = tuple(signal_states)
    if time.ndim != 1 or formal.shape != time.shape or len(states) != time.size:
        raise ValueError(
            "time_s, signal_states, and formal velocity must share one axis."
        )
    if not np.all(np.isfinite(time)):
        raise ValueError("time_s must contain only finite values.")
    if time.size == 0:
        raise ValueError("time_s must not be empty.")
    if not all(isinstance(state, SignalState) for state in states):
        raise TypeError("signal_states must contain only SignalState values.")
    if (
        analysis_start is not None
        and analysis_end is not None
        and analysis_start > analysis_end
    ):
        raise ValueError(
            "analysis_start_time_s must not exceed analysis_end_time_s."
        )

    display_start = (
        analysis_start if analysis_start is not None else float(time[0])
    )
    display_end = analysis_end if analysis_end is not None else float(time[-1])
    reference_is_active = (
        manual_reference is not None
        and display_start <= manual_reference <= display_end
        and float(time[0]) <= manual_reference <= float(time[-1])
    )

    display = formal.copy()
    origins: list[str] = []
    for index, state in enumerate(states):
        if state is SignalState.MEASURED:
            origins.append("quality_gated_measurement")
        elif (
            enable_pre_event_display
            and reference_is_active
            and time[index] >= display_start
            and time[index] < manual_reference
            and time[index] <= display_end
        ):
            display[index] = platform_velocity
            origins.append(PRE_EVENT_DISPLAY_ORIGIN)
        elif state is SignalState.OUTSIDE_ANALYSIS_WINDOW:
            origins.append("outside_analysis_window")
        else:
            origins.append(state.value)
    return display, tuple(origins)


def configure_channel_display_velocity(
    analysis: ChannelAnalysis,
    *,
    enable_pre_event_display: bool,
    pre_event_display_velocity_m_s: float,
) -> ChannelAnalysis:
    """Return ``analysis`` with only its display-only fields rebuilt."""
    if not isinstance(analysis, ChannelAnalysis):
        raise TypeError("analysis must be a ChannelAnalysis.")
    detection = analysis.signal_detection_result
    display, origins = build_display_velocity(
        detection.time_s,
        detection.signal_states,
        detection.apparent_velocity_m_s,
        manual_event_reference_time_s=(
            detection.manual_event_reference_time_s
        ),
        analysis_start_time_s=detection.analysis_start_time_s,
        analysis_end_time_s=detection.analysis_end_time_s,
        enable_pre_event_display=enable_pre_event_display,
        pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
    )
    return replace(
        analysis,
        display_velocity_m_s=display,
        velocity_origins=origins,
    )


def configure_channel_event_reference(
    analysis: ChannelAnalysis,
    *,
    event_reference_time_s: float | None,
    enable_pre_event_display: bool,
    pre_event_display_velocity_m_s: float,
) -> ChannelAnalysis:
    """Update display/review reference metadata without changing formal arrays."""
    if not isinstance(analysis, ChannelAnalysis):
        raise TypeError("analysis must be a ChannelAnalysis.")
    reference = _optional_finite_reference(
        event_reference_time_s,
        field_name="event_reference_time_s",
    )
    detection = replace(
        analysis.signal_detection_result,
        manual_event_reference_time_s=reference,
    )
    updated = replace(analysis, signal_detection_result=detection)
    return configure_channel_display_velocity(
        updated,
        enable_pre_event_display=enable_pre_event_display,
        pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
    )


def _finite_velocity(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("pre_event_display_velocity_m_s must be a finite number.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("pre_event_display_velocity_m_s must be finite.")
    return converted


def _optional_finite_reference(
    value: object,
    *,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be finite or None.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} must be finite or None.")
    return converted


__all__ = [
    "PRE_EVENT_DISPLAY_ORIGIN",
    "build_display_velocity",
    "configure_channel_event_reference",
    "configure_channel_display_velocity",
]
