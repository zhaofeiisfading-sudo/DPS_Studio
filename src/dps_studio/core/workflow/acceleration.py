"""One derivative source policy shared by plots and formal exports."""

from __future__ import annotations

import numpy as np

from dps_studio.core.physics.acceleration import (
    VelocityDerivative, differentiate_velocity, local_linear_acceleration,
)
from dps_studio.core.physics import velocity_correction_metadata
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow.display import PRE_EVENT_DISPLAY_ORIGIN
from dps_studio.core.workflow.models import ChannelAnalysis, WorkingRidgeSource


def channel_acceleration(
    analysis: ChannelAnalysis, *, window_s: float | None = None,
) -> VelocityDerivative:
    """Derivative of the final displayed speed; exclude known nonphysical gaps.

    Low quality finite working values remain eligible with their original
    provenance. Known no-beat/masked/interpolated values and display-only
    platforms are excluded. No confidence or uncertainty is manufactured.
    """
    invalid_states = {SignalState.OUTSIDE_ANALYSIS_WINDOW, SignalState.NO_DETECTABLE_BEAT}
    invalid_sources = {
        WorkingRidgeSource.OUTSIDE_ANALYSIS_WINDOW,
        WorkingRidgeSource.NO_ALLOWED_FINITE_BIN,
        WorkingRidgeSource.INTERPOLATED,
    }
    mask = np.asarray([
        state not in invalid_states
        and source not in invalid_sources
        and origin != PRE_EVENT_DISPLAY_ORIGIN
        for state, source, origin in zip(
            analysis.signal_detection_result.signal_states,
            analysis.working_source,
            analysis.velocity_origins,
            strict=True,
        )
    ], dtype=np.bool_)
    if window_s is not None:
        return local_linear_acceleration(analysis.stft_result.time_s, analysis.plot_velocity_m_s,
                                         valid_mask=mask, window_s=window_s)
    return differentiate_velocity(analysis.stft_result.time_s, analysis.plot_velocity_m_s, valid_mask=mask)


def acceleration_metadata(analysis: ChannelAnalysis) -> dict[str, object]:
    """Snapshot the actual input and numerical conventions without inference."""
    return {
        "input_velocity_type": "display_velocity_m_s",
        "input_velocity_chain": "working apparent -> angle -> window -> display convention",
        "input_is_signed": analysis.discrete_velocity_result.is_signed,
        "interpretation": "numerical time derivative of reconstructed unsigned speed; not a direction-resolved vector acceleration",
        "method": "finite_difference_nonuniform_central_3point",
        "units": {"time": "s", "velocity": "m/s", "acceleration": "m/s^2"},
        "endpoints": "first-order one-sided secant; two-point runs share secant; singleton NaN",
        "invalid_segments": "NaN/Inf, no_detectable_beat, outside, interpolated, unavailable bin and display-only platform excluded; no bridging",
        "quality": "original input-point signal_state, ridge_quality_flag, working_source and velocity_origin retained; stencil may include low-quality neighbors; finite derivative is not confidence",
        "preprocessing": "none; no smoothing, interpolation, fitting or resampling",
        "limits": "noise and speed jumps amplified; temporal resolving power limited by velocity reconstruction window; peaks unvalidated",
        "velocity_reconstruction_window_samples": analysis.stft_result.window_length_samples,
        "velocity_reconstruction_window_s": analysis.stft_result.window_length_samples / analysis.stft_result.sample_rate_hz,
        "frame_interval_s": analysis.stft_result.hop_samples / analysis.stft_result.sample_rate_hz,
        "overlap_samples": analysis.stft_result.overlap_samples,
        "velocity_correction": velocity_correction_metadata(analysis.working_velocity_correction_result),
    }
