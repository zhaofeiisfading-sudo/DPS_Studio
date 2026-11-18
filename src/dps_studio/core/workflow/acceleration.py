"""One derivative source policy shared by plots and formal exports."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from dps_studio.core.physics.acceleration import (
    VelocityDerivative, differentiate_velocity, local_linear_acceleration,
)
from dps_studio.core.physics import velocity_correction_metadata
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics.dechirp import DechirpResult, DechirpSettings, estimate_dechirp
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow.display import pre_event_interval
from dps_studio.core.workflow.models import ChannelAnalysis, FloatArray, WorkingRidgeSource


def dechirp_seed_frequencies(analysis: ChannelAnalysis) -> FloatArray:
    """Original diagnostic peak seeds and pre-reference exclusion for raw chirp fits."""
    detection = analysis.signal_detection_result
    excluded = np.array([
        state in (SignalState.OUTSIDE_ANALYSIS_WINDOW, SignalState.UNASSESSED,
                  SignalState.NO_DETECTABLE_BEAT)
        or source is WorkingRidgeSource.INTERPOLATED
        for state, source in zip(detection.signal_states, analysis.working_source, strict=True)
    ])
    if analysis.pre_event_display_enabled:
        excluded |= pre_event_interval(
            detection.time_s, detection.manual_event_reference_time_s,
            detection.analysis_start_time_s, detection.analysis_end_time_s,
        )
    # These are initial guesses for a raw-voltage fit, including diagnostic
    # peaks at frames without a measured velocity. Keep the original
    # refined-then-coarse seeding independent of the measured working ridge.
    refined = analysis.refined_result.refined_frequency_hz
    seed = np.where(np.isfinite(refined), refined, analysis.ridge_result.frequency_hz)
    return np.where(excluded, np.nan, seed)


def channel_dechirp(
    record: SignalRecord, analysis: ChannelAnalysis, *,
    settings: DechirpSettings = DechirpSettings(),
    cancelled: Callable[[], bool] | None = None,
) -> DechirpResult:
    """Fit raw windows at the selected ridge's frame centers without differentiating it."""
    detection = analysis.signal_detection_result
    event_boundaries = tuple(x for x in (
        detection.manual_event_reference_time_s,
        detection.detected_event_candidate_time_s,
        analysis.ridge_result.event_start_time_s,
    ) if x is not None)
    return estimate_dechirp(
        record, analysis.stft_result.time_s,
        dechirp_seed_frequencies(analysis),
        vacuum_wavelength_m=analysis.discrete_velocity_result.vacuum_wavelength_m,
        settings=settings, boundaries_s=event_boundaries,
        analysis_range_s=(
            detection.analysis_start_time_s if detection.analysis_start_time_s is not None
            else record.start_time_s,
            detection.analysis_end_time_s if detection.analysis_end_time_s is not None
            else record.end_time_s,
        ),
        cancelled=cancelled,
    )


def channel_acceleration(
    analysis: ChannelAnalysis, *, window_s: float | None = None,
) -> VelocityDerivative:
    """Differentiate contiguous measured corrected velocities without bridging gaps."""
    mask = np.asarray([
        state is SignalState.MEASURED and source is not WorkingRidgeSource.INTERPOLATED
        for state, source in zip(analysis.signal_detection_result.signal_states,
                                 analysis.working_source, strict=True)
    ], dtype=np.bool_)
    if window_s is not None:
        return local_linear_acceleration(analysis.stft_result.time_s, analysis.plot_velocity_m_s,
                                         valid_mask=mask, window_s=window_s)
    return differentiate_velocity(analysis.stft_result.time_s, analysis.plot_velocity_m_s, valid_mask=mask)


def acceleration_metadata(analysis: ChannelAnalysis) -> dict[str, object]:
    """Snapshot the actual input and numerical conventions without inference."""
    return {
        "input_velocity_type": "display_velocity_m_s",
        "input_velocity_chain": "measured apparent -> angle -> window",
        "input_is_signed": analysis.discrete_velocity_result.is_signed,
        "interpretation": "numerical time derivative of reconstructed unsigned speed; not a direction-resolved vector acceleration",
        "method": "finite_difference_nonuniform_central_3point",
        "units": {"time": "s", "velocity": "m/s", "acceleration": "m/s^2"},
        "endpoints": "first-order one-sided secant; two-point runs share secant; singleton NaN",
        "invalid_segments": "all non-measured frames and nonfinite velocities excluded; no bridging",
        "quality": "original input-point signal_state, ridge_quality_flag, working_source and velocity_origin retained; stencil restricted to contiguous measured frames; finite derivative is not confidence",
        "preprocessing": "none; no smoothing, interpolation, fitting or resampling",
        "limits": "noise and speed jumps amplified; temporal resolving power limited by velocity reconstruction window; peaks unvalidated",
        "velocity_reconstruction_window_samples": analysis.stft_result.window_length_samples,
        "velocity_reconstruction_window_s": analysis.stft_result.window_length_samples / analysis.stft_result.sample_rate_hz,
        "frame_interval_s": analysis.stft_result.hop_samples / analysis.stft_result.sample_rate_hz,
        "overlap_samples": analysis.stft_result.overlap_samples,
        "velocity_correction": velocity_correction_metadata(analysis.working_velocity_correction_result),
    }
