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
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeResult,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import compute_stft
from dps_studio.core.workflow.models import ChannelAnalysis, FloatArray
from dps_studio.core.workflow.quality_parameters import (
    derive_bin_guard_half_width_hz,
)


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
) -> Mapping[str, ChannelAnalysis]:
    """Run STFT through continuity diagnostics without paths, plots, or writes."""
    if not isinstance(records, Mapping) or not records:
        raise TypeError("records must be a non-empty mapping of SignalRecord values.")
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
    for channel_name, record in records.items():
        if not isinstance(channel_name, str) or not channel_name:
            raise TypeError("Every records key must be a non-empty string.")
        if not isinstance(record, SignalRecord):
            raise TypeError(f"records[{channel_name!r}] must be a SignalRecord.")
        stft_result = compute_stft(
            record,
            window_length_samples=window_length_samples,
            overlap_samples=overlap_samples,
            nfft=nfft,
            window_name=window_name,
        )
        ridge_result = extract_peak_ridge(
            stft_result,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
            event_start_time_s=None,
            analysis_end_time_s=None,
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
            analysis_start_time_s=analysis_start,
            analysis_end_time_s=analysis_end,
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
        display_velocity_m_s, velocity_origins = _display_velocity(
            stft_result.time_s,
            signal_detection_result.signal_states,
            refined_velocity_m_s,
            manual_event_reference_time_s=manual_reference,
            assume_pre_event_zero_for_display=(
                assume_pre_event_zero_for_display
            ),
        )
        continuity_result = assess_ridge_continuity(refined_result)
        stream_event_candidates = build_stream_event_candidates(
            signal_detection_result,
            profile_name=profile_name,
            channel_name=channel_name,
            config=event_candidate_config,
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
            signal_detection_result=signal_detection_result,
            stream_event_candidates=stream_event_candidates,
        )
    return MappingProxyType(analyses)


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


def _display_velocity(
    time_s: FloatArray,
    signal_states: tuple[SignalState, ...],
    refined_velocity_m_s: FloatArray,
    *,
    manual_event_reference_time_s: float | None,
    assume_pre_event_zero_for_display: bool,
) -> tuple[FloatArray, tuple[str, ...]]:
    display = refined_velocity_m_s.copy()
    origins: list[str] = []
    for index, state in enumerate(signal_states):
        if (
            assume_pre_event_zero_for_display
            and manual_event_reference_time_s is not None
            and time_s[index] < manual_event_reference_time_s
        ):
            display[index] = 0.0
            origins.append("assumed_pre_event_zero_display_only")
        elif state is SignalState.MEASURED:
            origins.append("quality_gated_measurement")
        elif state is SignalState.OUTSIDE_ANALYSIS_WINDOW:
            origins.append("outside_analysis_window")
        else:
            origins.append(state.value)
    return display, tuple(origins)


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


__all__ = ["analyze_configuration", "analyze_profile"]
