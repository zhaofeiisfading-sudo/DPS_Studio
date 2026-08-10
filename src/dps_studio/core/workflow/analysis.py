"""I/O-free formal numerical workflow for independent signal channels."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.event_candidates import (
    EventCandidateConfig,
    build_stream_event_candidates,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import convert_ridge_to_apparent_velocity
from dps_studio.core.quality import (
    SignalDetectionConfig,
    SignalState,
    detect_beat_signal,
)
from dps_studio.core.ridge import (
    EventAwareContinuityConfig,
    RefinedRidgeResult,
    RidgeCorridorConstraint,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeResult,
    assess_event_aware_ridge_continuity,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
    validate_ridge_corridor_for_stft,
)
from dps_studio.core.time_frequency import STFTResult, compute_stft
from dps_studio.core.workflow.display import build_display_velocity
from dps_studio.core.workflow.models import ChannelAnalysis, FloatArray
from dps_studio.core.workflow.quality_parameters import (
    derive_bin_guard_half_width_hz,
)


def compute_profile_stfts(
    records: Mapping[str, SignalRecord],
    *,
    profile: AnalysisProfile,
) -> Mapping[str, STFTResult]:
    """Compute reusable per-channel STFT results for one immutable profile."""
    if not isinstance(profile, AnalysisProfile):
        raise TypeError("profile must be an AnalysisProfile.")
    return compute_configuration_stfts(
        records,
        window_length_samples=profile.window_length_samples,
        overlap_samples=profile.overlap_samples,
        nfft=profile.nfft,
        window_name=profile.window_name,
    )


def compute_configuration_stfts(
    records: Mapping[str, SignalRecord],
    *,
    window_length_samples: int,
    overlap_samples: int,
    nfft: int,
    window_name: str,
) -> Mapping[str, STFTResult]:
    """Compute only STFT, without ridge, detection, or velocity work."""
    if not isinstance(records, Mapping) or not records:
        raise TypeError("records must be a non-empty mapping of SignalRecord values.")
    results: dict[str, STFTResult] = {}
    for channel_name, record in records.items():
        if not isinstance(channel_name, str) or not channel_name:
            raise TypeError("Every records key must be a non-empty string.")
        if not isinstance(record, SignalRecord):
            raise TypeError(f"records[{channel_name!r}] must be a SignalRecord.")
        results[channel_name] = compute_stft(
            record,
            window_length_samples=window_length_samples,
            overlap_samples=overlap_samples,
            nfft=nfft,
            window_name=window_name,
        )
    return MappingProxyType(results)


def analyze_profile(
    records: Mapping[str, SignalRecord],
    *,
    profile: AnalysisProfile,
    event_start_time_s: float | None = None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    manual_event_reference_time_s: float | None = None,
    vacuum_wavelength_m: float,
    detection_config: SignalDetectionConfig | None = None,
    event_candidate_config: EventCandidateConfig | None = None,
    background_guard_window_scale: float = 2.0,
    minimum_background_bin_count: int = 2,
    assume_pre_event_zero_for_display: bool = False,
    pre_event_display_velocity_m_s: float = 0.0,
    ridge_constraints: Mapping[str, RidgeCorridorConstraint] | None = None,
) -> Mapping[str, ChannelAnalysis]:
    """Analyze every channel independently with one formal profile."""
    if not isinstance(profile, AnalysisProfile):
        raise TypeError("profile must be an AnalysisProfile.")
    return analyze_configuration(
        records,
        window_length_samples=profile.window_length_samples,
        overlap_samples=profile.overlap_samples,
        nfft=profile.nfft,
        window_name=profile.window_name,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
        event_start_time_s=event_start_time_s,
        analysis_start_time_s=analysis_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        manual_event_reference_time_s=manual_event_reference_time_s,
        vacuum_wavelength_m=vacuum_wavelength_m,
        detection_config=detection_config,
        event_candidate_config=event_candidate_config,
        profile_name=profile.profile_id.value,
        background_guard_window_scale=background_guard_window_scale,
        minimum_background_bin_count=minimum_background_bin_count,
        assume_pre_event_zero_for_display=assume_pre_event_zero_for_display,
        pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
        ridge_constraints=ridge_constraints,
    )


def analyze_configuration(
    records: Mapping[str, SignalRecord],
    *,
    window_length_samples: int,
    overlap_samples: int,
    nfft: int,
    window_name: str,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    event_start_time_s: float | None = None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    manual_event_reference_time_s: float | None = None,
    vacuum_wavelength_m: float,
    detection_config: SignalDetectionConfig | None = None,
    event_candidate_config: EventCandidateConfig | None = None,
    profile_name: str = "custom",
    background_guard_window_scale: float = 2.0,
    minimum_background_bin_count: int = 2,
    assume_pre_event_zero_for_display: bool = False,
    pre_event_display_velocity_m_s: float = 0.0,
    ridge_constraints: Mapping[str, RidgeCorridorConstraint] | None = None,
) -> Mapping[str, ChannelAnalysis]:
    """Run STFT through continuity diagnostics without paths, plots, or writes."""
    stft_results = compute_configuration_stfts(
        records,
        window_length_samples=window_length_samples,
        overlap_samples=overlap_samples,
        nfft=nfft,
        window_name=window_name,
    )
    return analyze_stft_results(
        stft_results,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        event_start_time_s=event_start_time_s,
        analysis_start_time_s=analysis_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        manual_event_reference_time_s=manual_event_reference_time_s,
        vacuum_wavelength_m=vacuum_wavelength_m,
        detection_config=detection_config,
        event_candidate_config=event_candidate_config,
        profile_name=profile_name,
        background_guard_window_scale=background_guard_window_scale,
        minimum_background_bin_count=minimum_background_bin_count,
        assume_pre_event_zero_for_display=assume_pre_event_zero_for_display,
        pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
        ridge_constraints=ridge_constraints,
    )


def analyze_stft_results(
    stft_results: Mapping[str, STFTResult],
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    event_start_time_s: float | None = None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    manual_event_reference_time_s: float | None = None,
    vacuum_wavelength_m: float,
    detection_config: SignalDetectionConfig | None = None,
    event_candidate_config: EventCandidateConfig | None = None,
    profile_name: str = "custom",
    background_guard_window_scale: float = 2.0,
    minimum_background_bin_count: int = 2,
    assume_pre_event_zero_for_display: bool = False,
    pre_event_display_velocity_m_s: float = 0.0,
    ridge_constraints: Mapping[str, RidgeCorridorConstraint] | None = None,
) -> Mapping[str, ChannelAnalysis]:
    """Run post-STFT science while preserving the supplied STFT objects.

    A guided corridor defines a channel-local closed time domain.  Frames
    outside that domain are formally outside the guided analysis window and
    therefore remain NaN; they never fall back to the automatic ridge.
    """
    if not isinstance(stft_results, Mapping) or not stft_results:
        raise TypeError("stft_results must be a non-empty mapping of STFTResult values.")
    for channel_name, stft_result in stft_results.items():
        if not isinstance(channel_name, str) or not channel_name:
            raise TypeError("Every stft_results key must be a non-empty string.")
        if not isinstance(stft_result, STFTResult):
            raise TypeError(
                f"stft_results[{channel_name!r}] must be an STFTResult."
            )
    constraints = _validated_ridge_constraints(stft_results, ridge_constraints)
    if not math.isfinite(vacuum_wavelength_m) or vacuum_wavelength_m <= 0.0:
        raise ValueError("vacuum_wavelength_m must be finite and strictly positive.")
    manual_reference = _manual_reference(
        event_start_time_s=event_start_time_s,
        manual_event_reference_time_s=manual_event_reference_time_s,
    )
    analysis_start = _optional_finite_time(
        analysis_start_time_s,
        field_name="analysis_start_time_s",
    )
    analysis_end = _optional_finite_time(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )
    if (
        analysis_start is not None
        and analysis_end is not None
        and analysis_start > analysis_end
    ):
        raise ValueError(
            "analysis_start_time_s must not exceed analysis_end_time_s."
        )
    if detection_config is None:
        if (
            not math.isfinite(background_guard_window_scale)
            or background_guard_window_scale <= 0.0
        ):
            raise ValueError(
                "background_guard_window_scale must be finite and positive."
            )
        detection_config = SignalDetectionConfig()
    elif not isinstance(detection_config, SignalDetectionConfig):
        raise TypeError("detection_config must be a SignalDetectionConfig.")
    if event_candidate_config is None:
        event_candidate_config = EventCandidateConfig()
    elif not isinstance(event_candidate_config, EventCandidateConfig):
        raise TypeError("event_candidate_config must be an EventCandidateConfig.")
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("profile_name must be a non-empty string.")
    if not isinstance(assume_pre_event_zero_for_display, bool):
        raise TypeError("assume_pre_event_zero_for_display must be a boolean.")
    if (
        isinstance(minimum_background_bin_count, bool)
        or not isinstance(minimum_background_bin_count, int)
        or minimum_background_bin_count < 1
    ):
        raise ValueError("minimum_background_bin_count must be a positive integer.")

    analyses: dict[str, ChannelAnalysis] = {}
    for channel_name, stft_result in stft_results.items():
        ridge_constraint = constraints.get(channel_name)
        channel_analysis_start = analysis_start
        channel_analysis_end = analysis_end
        if ridge_constraint is not None:
            validate_ridge_corridor_for_stft(
                ridge_constraint,
                stft_result,
                minimum_frequency_hz=minimum_frequency_hz,
                maximum_frequency_hz=maximum_frequency_hz,
                analysis_start_time_s=analysis_start,
                analysis_end_time_s=analysis_end,
            )
            channel_analysis_start = ridge_constraint.start_time_s
            channel_analysis_end = ridge_constraint.end_time_s
        ridge_result = extract_peak_ridge(
            stft_result,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
            event_start_time_s=None,
            analysis_start_time_s=(
                channel_analysis_start if ridge_constraint is not None else None
            ),
            analysis_end_time_s=(
                channel_analysis_end if ridge_constraint is not None else None
            ),
            ridge_constraint=ridge_constraint,
        )
        refined_result = refine_peak_ridge_subbin(stft_result, ridge_result)
        provisional_discrete_velocity_result = convert_ridge_to_apparent_velocity(
            ridge_result,
            vacuum_wavelength_m=vacuum_wavelength_m,
        )
        frequency_spacing_hz = float(
            stft_result.frequency_hz[1] - stft_result.frequency_hz[0]
        )
        guard_hz = derive_bin_guard_half_width_hz(
            frequency_bin_spacing_hz=frequency_spacing_hz,
            peak_exclusion_half_width_bins=(
                detection_config.peak_exclusion_half_width_bins
            ),
        )
        spectral_quality_result = assess_ridge_spectral_quality(
            stft_result,
            refined_result,
            background_exclusion_half_width_hz=guard_hz,
            minimum_background_bin_count=minimum_background_bin_count,
        )
        signal_detection_result = detect_beat_signal(
            stft_result,
            refined_result,
            spectral_quality_result,
            detection_config=detection_config,
            vacuum_wavelength_m=vacuum_wavelength_m,
            analysis_start_time_s=channel_analysis_start,
            analysis_end_time_s=channel_analysis_end,
            manual_event_reference_time_s=manual_reference,
        )
        measured_mask = np.fromiter(
            (
                state is SignalState.MEASURED
                for state in signal_detection_result.signal_states
            ),
            dtype=np.bool_,
            count=stft_result.time_s.size,
        )
        formal_discrete_velocity_m_s = np.full(
            stft_result.time_s.shape,
            np.nan,
            dtype=np.float64,
        )
        formal_discrete_velocity_m_s[measured_mask] = (
            vacuum_wavelength_m
            * signal_detection_result.coarse_peak_frequency_hz[measured_mask]
            / 2.0
        )
        refined_velocity_m_s = (
            signal_detection_result.apparent_velocity_m_s.copy()
        )
        display_velocity_m_s, velocity_origins = build_display_velocity(
            stft_result.time_s,
            signal_detection_result.signal_states,
            refined_velocity_m_s,
            manual_event_reference_time_s=manual_reference,
            analysis_start_time_s=channel_analysis_start,
            analysis_end_time_s=channel_analysis_end,
            enable_pre_event_display=(
                assume_pre_event_zero_for_display
            ),
            pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
        )
        stream_event_candidates = build_stream_event_candidates(
            signal_detection_result,
            profile_name=profile_name,
            channel_name=channel_name,
            config=event_candidate_config,
        )
        continuity_result = assess_ridge_continuity(refined_result)
        continuity_event_time_s: float | None
        continuity_event_source: str | None
        if manual_reference is not None:
            continuity_event_time_s = manual_reference
            continuity_event_source = "manual_event_reference"
        else:
            continuity_event_time_s = stream_event_candidates.primary_candidate_time_s
            continuity_event_source = (
                "event_level_primary_candidate"
                if continuity_event_time_s is not None
                else None
            )
        event_aware_continuity_result = assess_event_aware_ridge_continuity(
            refined_result,
            event_reference_time_s=continuity_event_time_s,
            event_reference_source=continuity_event_source,
            stft_window_duration_s=(
                stft_result.window_length_samples / stft_result.sample_rate_hz
            ),
            config=EventAwareContinuityConfig(
                isolated_jump_threshold_hz=(
                    event_candidate_config.maximum_adjacent_frequency_step_hz
                ),
                neighbor_recovery_tolerance_hz=(
                    stft_result.sample_rate_hz / stft_result.window_length_samples
                ),
            ),
        )
        analyses[channel_name] = ChannelAnalysis(
            stft_result=stft_result,
            ridge_result=ridge_result,
            refined_result=refined_result,
            discrete_velocity_result=provisional_discrete_velocity_result,
            formal_discrete_velocity_m_s=formal_discrete_velocity_m_s,
            refined_velocity_m_s=refined_velocity_m_s,
            display_velocity_m_s=display_velocity_m_s,
            velocity_origins=velocity_origins,
            spectral_quality_result=spectral_quality_result,
            continuity_result=continuity_result,
            event_aware_continuity_result=event_aware_continuity_result,
            signal_detection_result=signal_detection_result,
            stream_event_candidates=stream_event_candidates,
        )
    return MappingProxyType(analyses)


def _validated_ridge_constraints(
    sources: Mapping[str, object],
    value: Mapping[str, RidgeCorridorConstraint] | None,
) -> Mapping[str, RidgeCorridorConstraint]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(
            "ridge_constraints must be a channel mapping or None."
        )
    constraints: dict[str, RidgeCorridorConstraint] = {}
    for channel_name, constraint in value.items():
        if not isinstance(channel_name, str) or not channel_name:
            raise TypeError("Every ridge constraint key must be a channel name.")
        if channel_name not in sources:
            raise ValueError(
                f"ridge_constraints contains unknown channel {channel_name!r}."
            )
        if not isinstance(constraint, RidgeCorridorConstraint):
            raise TypeError(
                f"ridge_constraints[{channel_name!r}] must be a "
                "RidgeCorridorConstraint."
            )
        constraints[channel_name] = constraint
    return MappingProxyType(constraints)


def _convert_refined_velocity(
    result: RefinedRidgeResult,
    *,
    vacuum_wavelength_m: float,
) -> FloatArray:
    if not isinstance(result, RefinedRidgeResult):
        raise TypeError("result must be a RefinedRidgeResult.")
    candidate_mask = np.fromiter(
        (flag is RidgeQualityFlag.CANDIDATE for flag in result.quality_flags),
        dtype=np.bool_,
        count=len(result.quality_flags),
    )
    refined_mask = np.fromiter(
        (
            status is RidgeRefinementStatus.REFINED
            for status in result.refinement_statuses
        ),
        dtype=np.bool_,
        count=len(result.refinement_statuses),
    )
    if np.all(~candidate_mask | refined_mask):
        refined_frequency_as_ridge = RidgeResult(
            time_s=result.time_s,
            frequency_hz=result.refined_frequency_hz,
            peak_magnitude=result.peak_magnitude,
            quality_flags=result.quality_flags,
            minimum_frequency_hz=result.minimum_frequency_hz,
            maximum_frequency_hz=result.maximum_frequency_hz,
            event_start_time_s=result.event_start_time_s,
            analysis_end_time_s=result.analysis_end_time_s,
            source_path=result.source_path,
        )
        converted = convert_ridge_to_apparent_velocity(
            refined_frequency_as_ridge,
            vacuum_wavelength_m=vacuum_wavelength_m,
        )
        return converted.apparent_velocity_m_s.copy()
    velocity_m_s = np.full(result.time_s.shape, np.nan, dtype=np.float64)
    for frame_index in np.flatnonzero(refined_mask):
        index = int(frame_index)
        refined_frequency_as_ridge = RidgeResult(
            time_s=result.time_s[index : index + 1],
            frequency_hz=result.refined_frequency_hz[index : index + 1],
            peak_magnitude=result.peak_magnitude[index : index + 1],
            quality_flags=(RidgeQualityFlag.CANDIDATE,),
            minimum_frequency_hz=result.minimum_frequency_hz,
            maximum_frequency_hz=result.maximum_frequency_hz,
            event_start_time_s=None,
            analysis_end_time_s=None,
            source_path=result.source_path,
        )
        converted = convert_ridge_to_apparent_velocity(
            refined_frequency_as_ridge,
            vacuum_wavelength_m=vacuum_wavelength_m,
        )
        velocity_m_s[index] = converted.apparent_velocity_m_s[0]
    return velocity_m_s


def _manual_reference(
    *,
    event_start_time_s: float | None,
    manual_event_reference_time_s: float | None,
) -> float | None:
    legacy = _optional_finite_time(
        event_start_time_s,
        field_name="event_start_time_s",
    )
    explicit = _optional_finite_time(
        manual_event_reference_time_s,
        field_name="manual_event_reference_time_s",
    )
    if legacy is not None and explicit is not None and legacy != explicit:
        raise ValueError(
            "event_start_time_s is a deprecated manual-reference alias and must "
            "match manual_event_reference_time_s when both are supplied."
        )
    return explicit if explicit is not None else legacy


def _optional_finite_time(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be finite or None.")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be finite or None.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} must be finite or None.")
    return converted


__all__ = [
    "analyze_configuration",
    "analyze_profile",
    "analyze_stft_results",
    "compute_configuration_stfts",
    "compute_profile_stfts",
]
