"""I/O-free formal numerical workflow for independent signal channels."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

import numpy as np

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.event_candidates import (
    EventCandidateConfig,
    build_stream_event_candidates,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import (
    VelocityCorrectionConfig,
    apply_velocity_corrections,
    convert_ridge_to_apparent_velocity,
)
from dps_studio.core.quality import (
    SignalDetectionConfig,
    SignalState,
    detect_beat_signal,
)
from dps_studio.core.ridge import (
    AutomaticRidgeSelectionConfig,
    ContinuityReselectionConfig,
    EventAwareContinuityConfig,
    LocalPeakCandidateConfig,
    ManualFrequencyRegion,
    RefinedRidgeResult,
    RidgeCorridorConstraint,
    RidgeSearchConstraint,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeResult,
    RidgeSelectionOrigin,
    assess_event_aware_ridge_continuity,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
    extract_local_peak_candidates,
    extract_peak_ridge,
    manual_frequency_region_mask,
    refine_peak_ridge_subbin,
    reselect_isolated_jump_candidates,
    select_automatic_ridge,
    validate_manual_frequency_region_for_stft,
    validate_ridge_corridor_for_stft,
)
from dps_studio.core.time_frequency import STFTResult, compute_stft
from dps_studio.core.workflow.display import build_display_velocity
from dps_studio.core.workflow.models import (
    ChannelAnalysis,
    FloatArray,
    WorkingRidgeSource,
)
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
    ridge_constraints: Mapping[str, RidgeSearchConstraint] | None = None,
    local_peak_candidate_config: LocalPeakCandidateConfig | None = None,
    continuity_reselection_config: ContinuityReselectionConfig | None = None,
    automatic_ridge_selection_config: AutomaticRidgeSelectionConfig | None = None,
    velocity_correction_config: VelocityCorrectionConfig | None = None,
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
        local_peak_candidate_config=local_peak_candidate_config,
        continuity_reselection_config=continuity_reselection_config,
        automatic_ridge_selection_config=automatic_ridge_selection_config,
        velocity_correction_config=velocity_correction_config,
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
    ridge_constraints: Mapping[str, RidgeSearchConstraint] | None = None,
    local_peak_candidate_config: LocalPeakCandidateConfig | None = None,
    continuity_reselection_config: ContinuityReselectionConfig | None = None,
    automatic_ridge_selection_config: AutomaticRidgeSelectionConfig | None = None,
    velocity_correction_config: VelocityCorrectionConfig | None = None,
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
        local_peak_candidate_config=local_peak_candidate_config,
        continuity_reselection_config=continuity_reselection_config,
        automatic_ridge_selection_config=automatic_ridge_selection_config,
        velocity_correction_config=velocity_correction_config,
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
    ridge_constraints: Mapping[str, RidgeSearchConstraint] | None = None,
    local_peak_candidate_config: LocalPeakCandidateConfig | None = None,
    continuity_reselection_config: ContinuityReselectionConfig | None = None,
    automatic_ridge_selection_config: AutomaticRidgeSelectionConfig | None = None,
    velocity_correction_config: VelocityCorrectionConfig | None = None,
) -> Mapping[str, ChannelAnalysis]:
    """Run post-STFT science while preserving the supplied STFT objects.

    Legacy corridors retain their closed-time-domain semantics. New manual
    boundaries contract the candidate-search band across the full analysis
    time range using constant endpoint extension. The supplied STFT objects are
    never modified.
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
    if velocity_correction_config is None:
        velocity_correction_config = VelocityCorrectionConfig()
    elif not isinstance(velocity_correction_config, VelocityCorrectionConfig):
        raise TypeError(
            "velocity_correction_config must be a VelocityCorrectionConfig."
        )
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
    automatic_config_supplied = automatic_ridge_selection_config is not None
    if automatic_ridge_selection_config is None:
        automatic_ridge_selection_config = AutomaticRidgeSelectionConfig()
    elif not isinstance(
        automatic_ridge_selection_config,
        AutomaticRidgeSelectionConfig,
    ):
        raise TypeError(
            "automatic_ridge_selection_config must be an "
            "AutomaticRidgeSelectionConfig."
        )
    if local_peak_candidate_config is None:
        local_peak_candidate_config = LocalPeakCandidateConfig(
            maximum_candidates_per_frame=(
                automatic_ridge_selection_config.top_k_candidates
            )
        )
    elif not isinstance(local_peak_candidate_config, LocalPeakCandidateConfig):
        raise TypeError(
            "local_peak_candidate_config must be a LocalPeakCandidateConfig."
        )
    if continuity_reselection_config is None:
        continuity_reselection_config = ContinuityReselectionConfig(
            minimum_peak_to_background_db=(
                automatic_ridge_selection_config.minimum_candidate_peak_to_background_db
            ),
            minimum_peak_to_competitor_db=(
                automatic_ridge_selection_config.minimum_candidate_relative_to_strongest_db
            ),
            maximum_neighbor_distance_hz=(
                automatic_ridge_selection_config.recovery_tolerance_hz
            ),
        )
    elif not isinstance(
        continuity_reselection_config, ContinuityReselectionConfig
    ):
        raise TypeError(
            "continuity_reselection_config must be a ContinuityReselectionConfig."
        )
    if automatic_config_supplied and (
        local_peak_candidate_config.maximum_candidates_per_frame
        != automatic_ridge_selection_config.top_k_candidates
        or continuity_reselection_config.minimum_peak_to_background_db
        != automatic_ridge_selection_config.minimum_candidate_peak_to_background_db
        or continuity_reselection_config.minimum_peak_to_competitor_db
        != automatic_ridge_selection_config.minimum_candidate_relative_to_strongest_db
        or continuity_reselection_config.maximum_neighbor_distance_hz
        != automatic_ridge_selection_config.recovery_tolerance_hz
    ):
        raise ValueError(
            "Legacy candidate/reselection arguments must match the explicit "
            "automatic_ridge_selection_config when both are supplied."
        )

    analyses: dict[str, ChannelAnalysis] = {}
    for channel_name, stft_result in stft_results.items():
        ridge_constraint = constraints.get(channel_name)
        channel_analysis_start = analysis_start
        channel_analysis_end = analysis_end
        allowed_search_mask = None
        if isinstance(ridge_constraint, RidgeCorridorConstraint):
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
        elif isinstance(ridge_constraint, ManualFrequencyRegion):
            validate_manual_frequency_region_for_stft(
                ridge_constraint,
                stft_result,
                minimum_frequency_hz=minimum_frequency_hz,
                maximum_frequency_hz=maximum_frequency_hz,
                analysis_start_time_s=analysis_start,
                analysis_end_time_s=analysis_end,
            )
            allowed_search_mask = manual_frequency_region_mask(
                ridge_constraint,
                stft_result,
                minimum_frequency_hz=minimum_frequency_hz,
                maximum_frequency_hz=maximum_frequency_hz,
            )
        strongest_ridge_result = extract_peak_ridge(
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
            ridge_constraint=(
                ridge_constraint
                if isinstance(ridge_constraint, RidgeCorridorConstraint)
                else None
            ),
            allowed_search_mask=allowed_search_mask,
        )
        strongest_refined_result = refine_peak_ridge_subbin(
            stft_result,
            strongest_ridge_result,
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
        strongest_spectral_quality_result = assess_ridge_spectral_quality(
            stft_result,
            strongest_refined_result,
            background_exclusion_half_width_hz=guard_hz,
            minimum_background_bin_count=minimum_background_bin_count,
        )
        strongest_signal_detection_result = detect_beat_signal(
            stft_result,
            strongest_refined_result,
            strongest_spectral_quality_result,
            detection_config=detection_config,
            vacuum_wavelength_m=vacuum_wavelength_m,
            analysis_start_time_s=channel_analysis_start,
            analysis_end_time_s=channel_analysis_end,
            manual_event_reference_time_s=manual_reference,
        )
        strongest_stream_event_candidates = build_stream_event_candidates(
            strongest_signal_detection_result,
            profile_name=profile_name,
            channel_name=channel_name,
            config=event_candidate_config,
        )
        selection_event_time_s: float | None
        selection_event_source: str | None
        if manual_reference is not None:
            selection_event_time_s = manual_reference
            selection_event_source = "manual_event_reference"
        else:
            selection_event_time_s = (
                strongest_stream_event_candidates.primary_candidate_time_s
            )
            selection_event_source = (
                "event_level_primary_candidate"
                if selection_event_time_s is not None
                else None
            )
        continuity_config = EventAwareContinuityConfig(
            isolated_jump_threshold_hz=(
                event_candidate_config.maximum_adjacent_frequency_step_hz
            ),
            neighbor_recovery_tolerance_hz=(
                stft_result.sample_rate_hz / stft_result.window_length_samples
            ),
        )
        strongest_event_aware_continuity_result = (
            assess_event_aware_ridge_continuity(
                strongest_refined_result,
                event_reference_time_s=selection_event_time_s,
                event_reference_source=selection_event_source,
                stft_window_duration_s=(
                    stft_result.window_length_samples
                    / stft_result.sample_rate_hz
                ),
                config=continuity_config,
            )
        )
        local_peak_candidates = None
        experimental_reselection_result = None
        if not isinstance(ridge_constraint, RidgeCorridorConstraint):
            local_peak_candidates = extract_local_peak_candidates(
                stft_result,
                minimum_frequency_hz=minimum_frequency_hz,
                maximum_frequency_hz=maximum_frequency_hz,
                background_exclusion_half_width_hz=guard_hz,
                minimum_background_bin_count=minimum_background_bin_count,
                config=local_peak_candidate_config,
                allowed_search_mask=allowed_search_mask,
            )
            experimental_reselection_result = reselect_isolated_jump_candidates(
                strongest_refined_result,
                local_peak_candidates,
                strongest_event_aware_continuity_result,
                config=continuity_reselection_config,
            )
        ridge_result, refined_result, automatic_selection_result = (
            select_automatic_ridge(
                strongest_ridge_result,
                strongest_refined_result,
                candidates=local_peak_candidates,
                reselection=experimental_reselection_result,
                config=automatic_ridge_selection_config,
                effective_recovery_tolerance_hz=(
                    continuity_config.neighbor_recovery_tolerance_hz
                    if automatic_ridge_selection_config.recovery_tolerance_hz
                    is None
                    else automatic_ridge_selection_config.recovery_tolerance_hz
                ),
            )
        )
        provisional_discrete_velocity_result = convert_ridge_to_apparent_velocity(
            ridge_result,
            vacuum_wavelength_m=vacuum_wavelength_m,
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
            ridge_selection_origins=automatic_selection_result.origins,
            minimum_continuity_candidate_relative_to_strongest_db=(
                automatic_ridge_selection_config.minimum_candidate_relative_to_strongest_db
            ),
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
            provisional_discrete_velocity_result.apparent_velocity_m_s[
                measured_mask
            ]
        )
        refined_velocity_m_s = signal_detection_result.apparent_velocity_m_s.copy()
        velocity_correction_result = apply_velocity_corrections(
            refined_velocity_m_s,
            config=velocity_correction_config,
            vacuum_wavelength_m=vacuum_wavelength_m,
        )
        working_frequency_hz, working_source = _build_working_ridge(
            refined_result,
            signal_detection_result.signal_states,
            automatic_selection_result.origins,
        )
        working_velocity_m_s = (
            working_frequency_hz * vacuum_wavelength_m / 2.0
        )
        working_velocity_correction_result = apply_velocity_corrections(
            working_velocity_m_s,
            config=velocity_correction_config,
            vacuum_wavelength_m=vacuum_wavelength_m,
        )
        stream_event_candidates = build_stream_event_candidates(
            signal_detection_result,
            profile_name=profile_name,
            channel_name=channel_name,
            config=event_candidate_config,
        )
        resolved_event_time_s = (
            manual_reference
            if manual_reference is not None
            else stream_event_candidates.primary_candidate_time_s
        )
        if resolved_event_time_s is not None:
            signal_detection_result = replace(
                signal_detection_result,
                manual_event_reference_time_s=resolved_event_time_s,
            )
        display_velocity_m_s, velocity_origins = build_display_velocity(
            stft_result.time_s,
            signal_detection_result.signal_states,
            velocity_correction_result.corrected_velocity_m_s,
            manual_event_reference_time_s=resolved_event_time_s,
            analysis_start_time_s=channel_analysis_start,
            analysis_end_time_s=channel_analysis_end,
            enable_pre_event_display=assume_pre_event_zero_for_display,
            pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
        )
        continuity_result = assess_ridge_continuity(refined_result)
        continuity_event_time_s: float | None
        continuity_event_source: str | None
        if manual_reference is not None:
            continuity_event_time_s = resolved_event_time_s
            continuity_event_source = "manual_event_reference"
        else:
            continuity_event_time_s = resolved_event_time_s
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
            config=continuity_config,
        )
        analyses[channel_name] = ChannelAnalysis(
            stft_result=stft_result,
            ridge_result=ridge_result,
            refined_result=refined_result,
            discrete_velocity_result=provisional_discrete_velocity_result,
            formal_discrete_velocity_m_s=formal_discrete_velocity_m_s,
            refined_velocity_m_s=refined_velocity_m_s,
            velocity_correction_result=velocity_correction_result,
            working_frequency_hz=working_frequency_hz,
            working_source=working_source,
            working_velocity_m_s=working_velocity_m_s,
            working_velocity_correction_result=(
                working_velocity_correction_result
            ),
            display_velocity_m_s=display_velocity_m_s,
            velocity_origins=velocity_origins,
            spectral_quality_result=spectral_quality_result,
            continuity_result=continuity_result,
            event_aware_continuity_result=event_aware_continuity_result,
            signal_detection_result=signal_detection_result,
            stream_event_candidates=stream_event_candidates,
            automatic_ridge_selection_result=automatic_selection_result,
            local_peak_candidates=local_peak_candidates,
            experimental_reselection_result=experimental_reselection_result,
        )
    return MappingProxyType(analyses)


def _build_working_ridge(
    refined_result: RefinedRidgeResult,
    signal_states: tuple[SignalState, ...],
    selection_origins: tuple[RidgeSelectionOrigin, ...],
) -> tuple[FloatArray, tuple[WorkingRidgeSource, ...]]:
    """Choose one same-frame production point without relaxing Formal gates."""
    frame_count = refined_result.time_s.size
    if len(signal_states) != frame_count or len(selection_origins) != frame_count:
        raise ValueError(
            "Working ridge inputs must share the refined ridge time axis."
        )
    frequency_hz = np.full(frame_count, np.nan, dtype=np.float64)
    sources: list[WorkingRidgeSource] = []
    for index, flag in enumerate(refined_result.quality_flags):
        discrete_frequency = refined_result.discrete_frequency_hz[index]
        if signal_states[index] is SignalState.OUTSIDE_ANALYSIS_WINDOW or flag in {
            RidgeQualityFlag.PRE_EVENT,
            RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW,
        }:
            sources.append(WorkingRidgeSource.OUTSIDE_ANALYSIS_WINDOW)
            continue
        if flag is not RidgeQualityFlag.CANDIDATE or not np.isfinite(
            discrete_frequency
        ):
            sources.append(WorkingRidgeSource.NO_ALLOWED_FINITE_BIN)
            continue

        refined_frequency = refined_result.refined_frequency_hz[index]
        refinement_succeeded = (
            refined_result.refinement_statuses[index]
            is RidgeRefinementStatus.REFINED
            and np.isfinite(refined_frequency)
        )
        if not refinement_succeeded:
            frequency_hz[index] = discrete_frequency
            sources.append(WorkingRidgeSource.DISCRETE_FALLBACK)
            continue

        frequency_hz[index] = refined_frequency
        if signal_states[index] is not SignalState.MEASURED:
            sources.append(WorkingRidgeSource.LOW_CONFIDENCE_FALLBACK)
        elif (
            selection_origins[index]
            is RidgeSelectionOrigin.CONTINUITY_ASSISTED_ALTERNATIVE
        ):
            sources.append(WorkingRidgeSource.CONTINUITY_SELECTED)
        else:
            sources.append(WorkingRidgeSource.REFINED)
    return frequency_hz, tuple(sources)


def _validated_ridge_constraints(
    sources: Mapping[str, object],
    value: Mapping[str, RidgeSearchConstraint] | None,
) -> Mapping[str, RidgeSearchConstraint]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(
            "ridge_constraints must be a channel mapping or None."
        )
    constraints: dict[str, RidgeSearchConstraint] = {}
    for channel_name, constraint in value.items():
        if not isinstance(channel_name, str) or not channel_name:
            raise TypeError("Every ridge constraint key must be a channel name.")
        if channel_name not in sources:
            raise ValueError(
                f"ridge_constraints contains unknown channel {channel_name!r}."
            )
        if not isinstance(
            constraint,
            (RidgeCorridorConstraint, ManualFrequencyRegion),
        ):
            raise TypeError(
                f"ridge_constraints[{channel_name!r}] must be a "
                "RidgeCorridorConstraint or ManualFrequencyRegion."
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
