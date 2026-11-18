"""Display-only velocity construction with no formal-measurement mutation."""

from __future__ import annotations

import math
from dataclasses import replace
from numbers import Real

import numpy as np
from numpy.typing import NDArray
from scipy.signal import get_window  # type: ignore[import-untyped]

from dps_studio.core.physics import (
    VelocityCorrectionConfig,
    apply_velocity_corrections,
)
from dps_studio.core.quality import SignalDetectionResult, SignalState
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.ridge import assess_event_aware_ridge_continuity
from dps_studio.core.workflow.models import ChannelAnalysis, FloatArray


PRE_EVENT_DISPLAY_ORIGIN = "pre_event_display_platform"


def pre_event_interval(
    time: FloatArray, reference: float | None, start: float | None, end: float | None,
) -> NDArray[np.bool_]:
    """Frames before a resolved reference inside both the data and analysis range."""
    lower = max(time[0], start) if start is not None else time[0]
    upper = min(time[-1], end) if end is not None else time[-1]
    if reference is None or not lower <= reference <= upper:
        return np.zeros(time.shape, dtype=np.bool_)
    return np.asarray((time >= lower) & (time < reference), dtype=np.bool_)


def stationary_pre_event_evidence(
    stft: STFTResult, detection: SignalDetectionResult,
) -> NDArray[np.bool_]:
    """Test for quiet AC power within the active pre-reference prefix.

    Remove the windowed DC component (including its leakage into positive
    bins). Parseval power of the residual is proportional to windowed AC
    energy. Use the lower quartile of the diffuse AC powers as the noise reference.
    Allow at most a fourfold power increase (6 dB) and stop permanently at
    the first sustained measured run. This relative veto supports an explicit
    stationary prior; absolute rest cannot be inferred from a PDV noise floor.
    """
    mask = np.zeros(stft.time_s.shape, dtype=np.bool_)
    eligible = pre_event_interval(
        stft.time_s, detection.manual_event_reference_time_s,
        detection.analysis_start_time_s, detection.analysis_end_time_s,
    )
    if not eligible.any():
        return mask
    run = 0
    for i, state in enumerate(detection.signal_states):
        run = run + 1 if state is SignalState.MEASURED else 0
        if run >= detection.detection_config.minimum_consecutive_frames:
            eligible[i + 1 - run:] = False
            break
    indices = np.flatnonzero(eligible)
    if not indices.size:
        return mask
    window = get_window(stft.window_name, stft.window_length_samples)
    response = np.fft.rfft(window, n=stft.nfft) / window.sum()
    if response.size != stft.frequency_hz.size:
        # An incomplete spectrum cannot establish total AC power.
        return mask
    coeff = stft.spectrum[:, indices[0]:indices[-1] + 1]
    residual = coeff - response[:, None] * coeff[:1]
    power = np.abs(residual) ** 2
    power[1:(-1 if stft.nfft % 2 == 0 else None)] *= 2
    energy = power.sum(axis=0)
    # For a bin-centered sinusoid the peak-bin power fraction scales as
    # 1 / ENBW (in padded FFT bins). Reject a line consistent with at
    # least one quarter of total AC power, even in an all-active prefix.
    enbw_bins = stft.nfft * np.dot(window, window) / window.sum() ** 2
    diffuse = power.max(axis=0) * enbw_bins <= 0.25 * energy
    quiet_candidates = energy[diffuse]
    if quiet_candidates.size:
        mask[indices] = diffuse & (energy <= 4.0 * np.quantile(quiet_candidates, 0.25))
    return mask


def build_display_velocity(
    time_s: FloatArray,
    signal_states: tuple[SignalState, ...],
    continuous_corrected_velocity_m_s: FloatArray,
    *,
    manual_event_reference_time_s: float | None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    enable_pre_event_display: bool,
    pre_event_display_velocity_m_s: float = 0.0,
    stationary_pre_event_mask: NDArray[np.bool_] | None = None,
) -> tuple[FloatArray, tuple[str, ...]]:
    """Build the final plotting array from an explicit optional event reference.

    Measured values take precedence. A display-only constraint requires an
    explicit stationary mask. Missing evidence leaves non-measured frames NaN.
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
    continuous = np.asarray(continuous_corrected_velocity_m_s, dtype=np.float64)
    states = tuple(signal_states)
    if time.ndim != 1 or continuous.shape != time.shape or len(states) != time.size:
        raise ValueError(
            "time_s, signal_states, and continuous velocity must share one axis."
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

    prefix = pre_event_interval(time, manual_reference, analysis_start, analysis_end)
    stationary = np.zeros(time.shape, dtype=np.bool_)
    if stationary_pre_event_mask is not None:
        stationary = np.asarray(stationary_pre_event_mask)
        if stationary.dtype != np.bool_ or stationary.shape != time.shape:
            raise ValueError("stationary_pre_event_mask must be boolean and match time_s.")
    display = np.full(time.shape, np.nan)
    origins = [state.value for state in states]
    for index, state in enumerate(states):
        if state is SignalState.MEASURED:
            display[index] = continuous[index]
        elif (
            enable_pre_event_display and prefix[index]
            and state not in (SignalState.OUTSIDE_ANALYSIS_WINDOW, SignalState.UNASSESSED)
            and stationary[index]
        ):
            display[index] = platform_velocity
            origins[index] = PRE_EVENT_DISPLAY_ORIGIN
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
        analysis.corrected_velocity_m_s,
        stationary_pre_event_mask=stationary_pre_event_evidence(
            analysis.stft_result, detection,
        ) if enable_pre_event_display else None,
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
        pre_event_display_enabled=enable_pre_event_display,
    )


def configure_channel_velocity_correction(
    analysis: ChannelAnalysis,
    *,
    velocity_correction_config: VelocityCorrectionConfig,
    vacuum_wavelength_m: float,
    enable_pre_event_display: bool,
    pre_event_display_velocity_m_s: float,
) -> ChannelAnalysis:
    """Rebuild only correction and display fields from stored apparent velocity."""
    if not isinstance(analysis, ChannelAnalysis):
        raise TypeError("analysis must be a ChannelAnalysis.")
    if not isinstance(velocity_correction_config, VelocityCorrectionConfig):
        raise TypeError(
            "velocity_correction_config must be a VelocityCorrectionConfig."
        )
    correction = apply_velocity_corrections(
        analysis.apparent_velocity_m_s,
        config=velocity_correction_config,
        vacuum_wavelength_m=vacuum_wavelength_m,
    )
    updated = replace(
        analysis,
        velocity_correction_result=correction,
        working_velocity_correction_result=correction,
    )
    return configure_channel_display_velocity(
        updated,
        enable_pre_event_display=enable_pre_event_display,
        pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
    )


def configure_channel_event_reference(
    analysis: ChannelAnalysis,
    *,
    event_reference_time_s: float | None,
    event_reference_source: str | None = None,
    enable_pre_event_display: bool,
    pre_event_display_velocity_m_s: float,
) -> ChannelAnalysis:
    """Update display/review and diagnostic reference metadata only."""
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
    if reference is None:
        continuity_reference = None
        continuity_source = None
    else:
        continuity_reference = reference
        continuity_source = (
            event_reference_source.strip()
            if isinstance(event_reference_source, str)
            and event_reference_source.strip()
            else "display_event_reference"
        )
    continuity = assess_event_aware_ridge_continuity(
        analysis.refined_result,
        event_reference_time_s=continuity_reference,
        event_reference_source=continuity_source,
        stft_window_duration_s=(
            analysis.event_aware_continuity_result.stft_window_duration_s
        ),
        config=analysis.event_aware_continuity_result.config,
    )
    updated = replace(
        analysis,
        signal_detection_result=detection,
        event_aware_continuity_result=continuity,
    )
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
    "configure_channel_velocity_correction",
]
