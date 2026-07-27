"""Formal per-frame beat-signal detection from unmodified STFT magnitudes."""

from __future__ import annotations

import math

import numpy as np

from dps_studio.core.quality.models import (
    SignalDetectionConfig,
    SignalDetectionResult,
    SignalState,
)
from dps_studio.core.ridge import (
    RefinedRidgeResult,
    RidgeRefinementStatus,
    RidgeSpectralQualityResult,
    RidgeSpectralQualityStatus,
)
from dps_studio.core.time_frequency import STFTResult


def detect_beat_signal(
    stft_result: STFTResult,
    refined_ridge_result: RefinedRidgeResult,
    spectral_quality_result: RidgeSpectralQualityResult,
    *,
    detection_config: SignalDetectionConfig,
    vacuum_wavelength_m: float,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    manual_event_reference_time_s: float | None = None,
) -> SignalDetectionResult:
    """Apply ordered signal-existence and exact consecutive-frame gates."""
    _validate_inputs(
        stft_result,
        refined_ridge_result,
        spectral_quality_result,
    )
    if not isinstance(detection_config, SignalDetectionConfig):
        raise TypeError("detection_config must be a SignalDetectionConfig.")
    wavelength = _positive_finite(
        vacuum_wavelength_m,
        field_name="vacuum_wavelength_m",
    )
    analysis_start = _optional_finite(
        analysis_start_time_s,
        field_name="analysis_start_time_s",
    )
    analysis_end = _optional_finite(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )
    manual_reference = _optional_finite(
        manual_event_reference_time_s,
        field_name="manual_event_reference_time_s",
    )
    if (
        analysis_start is not None
        and analysis_end is not None
        and analysis_start > analysis_end
    ):
        raise ValueError("analysis_start_time_s must not exceed analysis_end_time_s.")

    frame_count = stft_result.time_s.size
    window_duration_s = (
        stft_result.window_length_samples / stft_result.sample_rate_hz
    )
    hop_duration_s = stft_result.hop_samples / stft_result.sample_rate_hz
    cycles = (
        refined_ridge_result.discrete_frequency_hz * window_duration_s
    ).astype(np.float64, copy=False)
    band_indices = np.flatnonzero(
        (stft_result.frequency_hz >= refined_ridge_result.minimum_frequency_hz)
        & (stft_result.frequency_hz <= refined_ridge_result.maximum_frequency_hz)
    )
    first_band_index = int(band_indices[0])
    last_band_index = int(band_indices[-1])
    peak_bin_index = refined_ridge_result.discrete_frequency_bin_index.copy()
    boundary = (peak_bin_index == first_band_index) | (
        peak_bin_index == last_band_index
    )

    outside = np.zeros(frame_count, dtype=np.bool_)
    if analysis_start is not None:
        outside |= stft_result.time_s < analysis_start
    if analysis_end is not None:
        outside |= stft_result.time_s > analysis_end

    provisional: list[SignalState] = []
    for index in range(frame_count):
        provisional.append(
            _provisional_state(
                index,
                outside=bool(outside[index]),
                boundary=bool(boundary[index]),
                refined_ridge_result=refined_ridge_result,
                spectral_quality_result=spectral_quality_result,
                cycles_in_window=float(cycles[index]),
                detection_config=detection_config,
            )
        )

    final_states = list(provisional)
    valid_runs = _measured_runs(provisional)
    qualifying_runs: list[tuple[int, int]] = []
    for start, stop in valid_runs:
        run_length = stop - start
        if run_length < detection_config.minimum_consecutive_frames:
            for index in range(start, stop):
                final_states[index] = SignalState.UNSTABLE_DETECTION
        else:
            qualifying_runs.append((start, stop))

    refined_frequency_hz = np.full(frame_count, np.nan, dtype=np.float64)
    apparent_velocity_m_s = np.full(frame_count, np.nan, dtype=np.float64)
    measured = np.fromiter(
        (state is SignalState.MEASURED for state in final_states),
        dtype=np.bool_,
        count=frame_count,
    )
    refined_frequency_hz[measured] = refined_ridge_result.refined_frequency_hz[
        measured
    ]
    apparent_velocity_m_s[measured] = (
        wavelength * refined_frequency_hz[measured] / 2.0
    )

    coarse = refined_ridge_result.discrete_frequency_hz.copy()
    peak = spectral_quality_result.peak_magnitude.copy()
    background = spectral_quality_result.background_median_magnitude.copy()
    competitor = spectral_quality_result.strongest_competitor_magnitude.copy()
    peak_to_background = spectral_quality_result.peak_to_background_db.copy()
    peak_to_competitor = spectral_quality_result.peak_to_competitor_db.copy()
    for array in (
        coarse,
        peak,
        background,
        competitor,
        peak_to_background,
        peak_to_competitor,
        cycles,
    ):
        array[outside] = np.nan
    peak_bin_index[outside] = -1
    boundary[outside] = False

    candidate_time: float | None = None
    candidate_run_length = 0
    if qualifying_runs:
        first_start, first_stop = qualifying_runs[0]
        candidate_time = float(stft_result.time_s[first_start])
        candidate_run_length = first_stop - first_start

    minimum_resolvable_frequency_hz = (
        detection_config.minimum_cycles_in_window / window_duration_s
    )
    return SignalDetectionResult(
        time_s=stft_result.time_s,
        coarse_peak_frequency_hz=coarse,
        refined_frequency_hz=refined_frequency_hz,
        apparent_velocity_m_s=apparent_velocity_m_s,
        signal_states=tuple(final_states),
        peak_amplitude=peak,
        background_level=background,
        strongest_competitor_level=competitor,
        peak_to_background_db=peak_to_background,
        peak_to_competitor_db=peak_to_competitor,
        peak_bin_index=peak_bin_index,
        peak_is_at_band_boundary=boundary,
        cycles_in_window=cycles,
        refinement_statuses=refined_ridge_result.refinement_statuses,
        detection_config=detection_config,
        analysis_start_time_s=analysis_start,
        analysis_end_time_s=analysis_end,
        manual_event_reference_time_s=manual_reference,
        detected_event_candidate_time_s=candidate_time,
        detected_event_candidate_run_frame_count=candidate_run_length,
        detected_event_candidate_source="spectral_detection",
        window_duration_s=window_duration_s,
        hop_duration_s=hop_duration_s,
        minimum_resolvable_frequency_by_cycle_rule_hz=(
            minimum_resolvable_frequency_hz
        ),
        corresponding_apparent_velocity_m_s=(
            wavelength * minimum_resolvable_frequency_hz / 2.0
        ),
        detection_method=SignalDetectionResult.DETECTION_METHOD,
    )


def _provisional_state(
    index: int,
    *,
    outside: bool,
    boundary: bool,
    refined_ridge_result: RefinedRidgeResult,
    spectral_quality_result: RidgeSpectralQualityResult,
    cycles_in_window: float,
    detection_config: SignalDetectionConfig,
) -> SignalState:
    if outside:
        return SignalState.OUTSIDE_ANALYSIS_WINDOW
    if not detection_config.enabled:
        return SignalState.NO_DETECTABLE_BEAT
    assessment = spectral_quality_result.assessment_statuses[index]
    peak_to_background = float(
        spectral_quality_result.peak_to_background_db[index]
    )
    peak_to_competitor = float(
        spectral_quality_result.peak_to_competitor_db[index]
    )
    if (
        assessment is not RidgeSpectralQualityStatus.ASSESSED
        or not math.isfinite(peak_to_background)
        or not math.isfinite(peak_to_competitor)
    ):
        return SignalState.NO_DETECTABLE_BEAT
    if peak_to_background < detection_config.minimum_peak_to_background_db:
        return SignalState.NO_DETECTABLE_BEAT
    if peak_to_competitor < detection_config.minimum_peak_to_competitor_db:
        return SignalState.AMBIGUOUS_PEAK
    if boundary:
        return SignalState.PEAK_AT_BAND_BOUNDARY
    if (
        not math.isfinite(cycles_in_window)
        or cycles_in_window < detection_config.minimum_cycles_in_window
    ):
        return SignalState.INSUFFICIENT_CYCLES
    if (
        refined_ridge_result.refinement_statuses[index]
        is not RidgeRefinementStatus.REFINED
    ):
        return SignalState.REFINEMENT_FAILED
    return SignalState.MEASURED


def _measured_runs(states: list[SignalState]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(states):
        if states[index] is not SignalState.MEASURED:
            index += 1
            continue
        start = index
        while index < len(states) and states[index] is SignalState.MEASURED:
            index += 1
        runs.append((start, index))
    return runs


def _validate_inputs(
    stft_result: object,
    refined_ridge_result: object,
    spectral_quality_result: object,
) -> None:
    if not isinstance(stft_result, STFTResult):
        raise TypeError("stft_result must be an STFTResult.")
    if not isinstance(refined_ridge_result, RefinedRidgeResult):
        raise TypeError("refined_ridge_result must be a RefinedRidgeResult.")
    if not isinstance(spectral_quality_result, RidgeSpectralQualityResult):
        raise TypeError(
            "spectral_quality_result must be a RidgeSpectralQualityResult."
        )
    if not (
        np.array_equal(stft_result.time_s, refined_ridge_result.time_s)
        and np.array_equal(stft_result.time_s, spectral_quality_result.time_s)
    ):
        raise ValueError("STFT, ridge, and spectral-quality time axes must match.")
    if not (
        stft_result.source_path
        == refined_ridge_result.source_path
        == spectral_quality_result.source_path
    ):
        raise ValueError("STFT, ridge, and spectral-quality sources must match.")
    band_indices = np.flatnonzero(
        (stft_result.frequency_hz >= refined_ridge_result.minimum_frequency_hz)
        & (stft_result.frequency_hz <= refined_ridge_result.maximum_frequency_hz)
    )
    if band_indices.size < 2:
        raise ValueError("The detection search band must contain at least two bins.")


def _positive_finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a positive finite number.")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be a positive finite number.") from exc
    if not math.isfinite(converted) or converted <= 0.0:
        raise ValueError(f"{field_name} must be finite and strictly positive.")
    return converted


def _optional_finite(value: object, *, field_name: str) -> float | None:
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


__all__ = ["detect_beat_signal"]
