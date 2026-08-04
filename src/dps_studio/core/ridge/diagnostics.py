"""Ridge continuity and related-frequency spectral evidence diagnostics."""

from __future__ import annotations

import math
from typing import cast

import numpy as np

from dps_studio.core.ridge.diagnostic_models import (
    RelatedFrequencyEvidenceResult,
    RelatedFrequencyEvidenceStatus,
    RidgeContinuityResult,
    RidgeContinuityStatus,
)
from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import (
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
)
from dps_studio.core.ridge.quality_models import RidgeSpectralQualityResult
from dps_studio.core.time_frequency import STFTResult


def assess_ridge_continuity(
    refined_ridge_result: RefinedRidgeResult,
) -> RidgeContinuityResult:
    """Calculate differences only across adjacent successfully refined frames."""
    _validate_refined_result(refined_ridge_result)
    frame_count = refined_ridge_result.time_s.size
    previous_refined_frequency_hz = np.full(frame_count, np.nan, dtype=np.float64)
    frame_interval_s = np.full(frame_count, np.nan, dtype=np.float64)
    frequency_step_hz = np.full(frame_count, np.nan, dtype=np.float64)
    absolute_frequency_step_hz = np.full(frame_count, np.nan, dtype=np.float64)
    frequency_slope_hz_s = np.full(frame_count, np.nan, dtype=np.float64)
    frequency_second_difference_hz = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    continuity_statuses: list[RidgeContinuityStatus] = []

    for frame_index, (flag, refinement_status) in enumerate(
        zip(
            refined_ridge_result.quality_flags,
            refined_ridge_result.refinement_statuses,
        )
    ):
        if flag is RidgeQualityFlag.PRE_EVENT:
            continuity_statuses.append(RidgeContinuityStatus.PRE_EVENT)
            continue
        if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            continuity_statuses.append(
                RidgeContinuityStatus.OUTSIDE_ANALYSIS_WINDOW
            )
            continue
        if refinement_status is not RidgeRefinementStatus.REFINED:
            continuity_statuses.append(
                RidgeContinuityStatus.REFINEMENT_UNAVAILABLE
            )
            continue
        if frame_index == 0 or not _is_refined_candidate(
            refined_ridge_result,
            frame_index - 1,
        ):
            continuity_statuses.append(
                RidgeContinuityStatus.NO_PREVIOUS_CANDIDATE
            )
            continue

        previous_index = frame_index - 1
        interval_s = float(
            refined_ridge_result.time_s[frame_index]
            - refined_ridge_result.time_s[previous_index]
        )
        if not math.isfinite(interval_s) or interval_s <= 0.0:
            continuity_statuses.append(
                RidgeContinuityStatus.INVALID_TIME_INTERVAL
            )
            continue
        current_frequency_hz = float(
            refined_ridge_result.refined_frequency_hz[frame_index]
        )
        previous_frequency_hz = float(
            refined_ridge_result.refined_frequency_hz[previous_index]
        )
        step_hz = current_frequency_hz - previous_frequency_hz
        slope_hz_s = step_hz / interval_s
        if not all(math.isfinite(value) for value in (step_hz, slope_hz_s)):
            continuity_statuses.append(RidgeContinuityStatus.INPUT_MISMATCH)
            continue
        previous_refined_frequency_hz[frame_index] = previous_frequency_hz
        frame_interval_s[frame_index] = interval_s
        frequency_step_hz[frame_index] = step_hz
        absolute_frequency_step_hz[frame_index] = abs(step_hz)
        frequency_slope_hz_s[frame_index] = slope_hz_s

        if frame_index < 2 or not _is_refined_candidate(
            refined_ridge_result,
            frame_index - 2,
        ):
            continuity_statuses.append(
                RidgeContinuityStatus.NO_TWO_PREVIOUS_CANDIDATES
            )
            continue
        second_previous_frequency_hz = float(
            refined_ridge_result.refined_frequency_hz[frame_index - 2]
        )
        second_difference_hz = (
            current_frequency_hz
            - 2.0 * previous_frequency_hz
            + second_previous_frequency_hz
        )
        if not math.isfinite(second_difference_hz):
            continuity_statuses.append(RidgeContinuityStatus.INPUT_MISMATCH)
            previous_refined_frequency_hz[frame_index] = np.nan
            frame_interval_s[frame_index] = np.nan
            frequency_step_hz[frame_index] = np.nan
            absolute_frequency_step_hz[frame_index] = np.nan
            frequency_slope_hz_s[frame_index] = np.nan
            continue
        frequency_second_difference_hz[frame_index] = second_difference_hz
        continuity_statuses.append(RidgeContinuityStatus.ASSESSED)

    return RidgeContinuityResult(
        time_s=refined_ridge_result.time_s,
        refined_frequency_hz=refined_ridge_result.refined_frequency_hz,
        previous_refined_frequency_hz=previous_refined_frequency_hz,
        frame_interval_s=frame_interval_s,
        frequency_step_hz=frequency_step_hz,
        absolute_frequency_step_hz=absolute_frequency_step_hz,
        frequency_slope_hz_s=frequency_slope_hz_s,
        frequency_second_difference_hz=frequency_second_difference_hz,
        quality_flags=refined_ridge_result.quality_flags,
        refinement_statuses=refined_ridge_result.refinement_statuses,
        continuity_statuses=tuple(continuity_statuses),
        minimum_frequency_hz=refined_ridge_result.minimum_frequency_hz,
        maximum_frequency_hz=refined_ridge_result.maximum_frequency_hz,
        event_start_time_s=refined_ridge_result.event_start_time_s,
        analysis_end_time_s=refined_ridge_result.analysis_end_time_s,
        continuity_method=RidgeContinuityResult.CONTINUITY_METHOD,
        source_path=refined_ridge_result.source_path,
    )


def assess_related_frequency_evidence(
    stft_result: STFTResult,
    refined_ridge_result: RefinedRidgeResult,
    spectral_quality_result: RidgeSpectralQualityResult,
    *,
    search_half_width_hz: float,
) -> RelatedFrequencyEvidenceResult:
    """Find local maxima near explicit 2f and f/2 diagnostic targets."""
    validated_half_width_hz = _positive_finite_float(
        search_half_width_hz,
        field_name="search_half_width_hz",
    )
    _validate_related_inputs(
        stft_result,
        refined_ridge_result,
        spectral_quality_result,
    )
    nyquist_hz = 0.5 * stft_result.sample_rate_hz
    if validated_half_width_hz > nyquist_hz:
        raise RidgeConfigurationError(
            "search_half_width_hz cannot exceed the Nyquist frequency."
        )
    frame_count = stft_result.time_s.size
    main_peak_magnitude = np.full(frame_count, np.nan, dtype=np.float64)
    double_frequency_target_hz = np.full(frame_count, np.nan, dtype=np.float64)
    double_frequency_peak_hz = np.full(frame_count, np.nan, dtype=np.float64)
    double_frequency_peak_magnitude = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    double_frequency_peak_offset_hz = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    main_to_double_frequency_db = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    half_frequency_target_hz = np.full(frame_count, np.nan, dtype=np.float64)
    half_frequency_peak_hz = np.full(frame_count, np.nan, dtype=np.float64)
    half_frequency_peak_magnitude = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    half_frequency_peak_offset_hz = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    main_to_half_frequency_db = np.full(frame_count, np.nan, dtype=np.float64)
    double_statuses: list[RelatedFrequencyEvidenceStatus] = []
    half_statuses: list[RelatedFrequencyEvidenceStatus] = []

    for frame_index, (flag, refinement_status) in enumerate(
        zip(
            refined_ridge_result.quality_flags,
            refined_ridge_result.refinement_statuses,
        )
    ):
        if flag is RidgeQualityFlag.PRE_EVENT:
            double_statuses.append(RelatedFrequencyEvidenceStatus.PRE_EVENT)
            half_statuses.append(RelatedFrequencyEvidenceStatus.PRE_EVENT)
            continue
        if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            double_statuses.append(
                RelatedFrequencyEvidenceStatus.OUTSIDE_ANALYSIS_WINDOW
            )
            half_statuses.append(
                RelatedFrequencyEvidenceStatus.OUTSIDE_ANALYSIS_WINDOW
            )
            continue
        if refinement_status is not RidgeRefinementStatus.REFINED:
            double_statuses.append(
                RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE
            )
            half_statuses.append(
                RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE
            )
            continue

        raw_main_peak_magnitude = float(
            spectral_quality_result.peak_magnitude[frame_index]
        )
        if (
            not math.isfinite(raw_main_peak_magnitude)
            or raw_main_peak_magnitude <= 0.0
        ):
            double_statuses.append(
                RelatedFrequencyEvidenceStatus.INVALID_MAIN_PEAK_MAGNITUDE
            )
            half_statuses.append(
                RelatedFrequencyEvidenceStatus.INVALID_MAIN_PEAK_MAGNITUDE
            )
            continue
        main_peak_magnitude[frame_index] = raw_main_peak_magnitude
        refined_frequency_hz = float(
            refined_ridge_result.refined_frequency_hz[frame_index]
        )

        double_values = _assess_target_band(
            stft_result=stft_result,
            frame_index=frame_index,
            target_hz=2.0 * refined_frequency_hz,
            main_peak_magnitude=raw_main_peak_magnitude,
            search_half_width_hz=validated_half_width_hz,
            minimum_frequency_hz=refined_ridge_result.minimum_frequency_hz,
            maximum_frequency_hz=refined_ridge_result.maximum_frequency_hz,
            nyquist_hz=nyquist_hz,
        )
        (
            double_frequency_target_hz[frame_index],
            double_frequency_peak_hz[frame_index],
            double_frequency_peak_magnitude[frame_index],
            double_frequency_peak_offset_hz[frame_index],
            main_to_double_frequency_db[frame_index],
            double_status,
        ) = double_values
        double_statuses.append(double_status)

        half_values = _assess_target_band(
            stft_result=stft_result,
            frame_index=frame_index,
            target_hz=0.5 * refined_frequency_hz,
            main_peak_magnitude=raw_main_peak_magnitude,
            search_half_width_hz=validated_half_width_hz,
            minimum_frequency_hz=refined_ridge_result.minimum_frequency_hz,
            maximum_frequency_hz=refined_ridge_result.maximum_frequency_hz,
            nyquist_hz=nyquist_hz,
        )
        (
            half_frequency_target_hz[frame_index],
            half_frequency_peak_hz[frame_index],
            half_frequency_peak_magnitude[frame_index],
            half_frequency_peak_offset_hz[frame_index],
            main_to_half_frequency_db[frame_index],
            half_status,
        ) = half_values
        half_statuses.append(half_status)

    return RelatedFrequencyEvidenceResult(
        time_s=refined_ridge_result.time_s,
        refined_frequency_hz=refined_ridge_result.refined_frequency_hz,
        discrete_frequency_bin_index=(
            refined_ridge_result.discrete_frequency_bin_index
        ),
        main_peak_magnitude=main_peak_magnitude,
        double_frequency_target_hz=double_frequency_target_hz,
        double_frequency_peak_hz=double_frequency_peak_hz,
        double_frequency_peak_magnitude=double_frequency_peak_magnitude,
        double_frequency_peak_offset_hz=double_frequency_peak_offset_hz,
        main_to_double_frequency_db=main_to_double_frequency_db,
        half_frequency_target_hz=half_frequency_target_hz,
        half_frequency_peak_hz=half_frequency_peak_hz,
        half_frequency_peak_magnitude=half_frequency_peak_magnitude,
        half_frequency_peak_offset_hz=half_frequency_peak_offset_hz,
        main_to_half_frequency_db=main_to_half_frequency_db,
        quality_flags=refined_ridge_result.quality_flags,
        refinement_statuses=refined_ridge_result.refinement_statuses,
        spectral_quality_statuses=(
            spectral_quality_result.assessment_statuses
        ),
        double_frequency_statuses=tuple(double_statuses),
        half_frequency_statuses=tuple(half_statuses),
        minimum_frequency_hz=refined_ridge_result.minimum_frequency_hz,
        maximum_frequency_hz=refined_ridge_result.maximum_frequency_hz,
        event_start_time_s=refined_ridge_result.event_start_time_s,
        analysis_end_time_s=refined_ridge_result.analysis_end_time_s,
        search_half_width_hz=validated_half_width_hz,
        evidence_method=RelatedFrequencyEvidenceResult.EVIDENCE_METHOD,
        source_path=refined_ridge_result.source_path,
    )


def _assess_target_band(
    *,
    stft_result: STFTResult,
    frame_index: int,
    target_hz: float,
    main_peak_magnitude: float,
    search_half_width_hz: float,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    nyquist_hz: float,
) -> tuple[
    float,
    float,
    float,
    float,
    float,
    RelatedFrequencyEvidenceStatus,
]:
    nan = float("nan")
    if (
        not math.isfinite(target_hz)
        or target_hz < minimum_frequency_hz
        or target_hz > maximum_frequency_hz
        or target_hz < float(stft_result.frequency_hz[0])
        or target_hz > float(stft_result.frequency_hz[-1])
        or target_hz > nyquist_hz
    ):
        return (
            nan,
            nan,
            nan,
            nan,
            nan,
            RelatedFrequencyEvidenceStatus.TARGET_OUT_OF_RANGE,
        )
    search_indices = np.flatnonzero(
        (stft_result.frequency_hz >= minimum_frequency_hz)
        & (stft_result.frequency_hz <= maximum_frequency_hz)
        & (np.abs(stft_result.frequency_hz - target_hz) <= search_half_width_hz)
    )
    if search_indices.size == 0:
        return (
            target_hz,
            nan,
            nan,
            nan,
            nan,
            RelatedFrequencyEvidenceStatus.INSUFFICIENT_SEARCH_BINS,
        )
    magnitudes = np.abs(stft_result.spectrum[search_indices, frame_index])
    if not np.all(np.isfinite(magnitudes)):
        return (
            target_hz,
            nan,
            nan,
            nan,
            nan,
            RelatedFrequencyEvidenceStatus.INVALID_RELATED_FREQUENCY_MAGNITUDE,
        )
    relative_peak_index = int(np.argmax(magnitudes))
    peak_magnitude = float(magnitudes[relative_peak_index])
    if peak_magnitude <= 0.0:
        return (
            target_hz,
            nan,
            nan,
            nan,
            nan,
            RelatedFrequencyEvidenceStatus.INVALID_RELATED_FREQUENCY_MAGNITUDE,
        )
    peak_index = int(search_indices[relative_peak_index])
    peak_hz = float(stft_result.frequency_hz[peak_index])
    offset_hz = peak_hz - target_hz
    ratio_db = 20.0 * (
        math.log10(main_peak_magnitude) - math.log10(peak_magnitude)
    )
    return (
        target_hz,
        peak_hz,
        peak_magnitude,
        offset_hz,
        ratio_db,
        RelatedFrequencyEvidenceStatus.ASSESSED,
    )


def _validate_related_inputs(
    stft_result: object,
    refined_ridge_result: object,
    spectral_quality_result: object,
) -> None:
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError(
            "stft_result must be an STFTResult instance; "
            f"got {type(stft_result).__name__}."
        )
    if not isinstance(refined_ridge_result, RefinedRidgeResult):
        raise RidgeConfigurationError(
            "refined_ridge_result must be a RefinedRidgeResult instance; "
            f"got {type(refined_ridge_result).__name__}."
        )
    if not isinstance(spectral_quality_result, RidgeSpectralQualityResult):
        raise RidgeConfigurationError(
            "spectral_quality_result must be a RidgeSpectralQualityResult "
            f"instance; got {type(spectral_quality_result).__name__}."
        )
    _validate_refined_result(refined_ridge_result)
    frame_count = refined_ridge_result.time_s.size
    if stft_result.time_s.size != frame_count or spectral_quality_result.time_s.size != frame_count:
        raise RidgeConfigurationError(
            "STFT, refined ridge, and spectral quality frame counts must match."
        )
    if not np.array_equal(stft_result.time_s, refined_ridge_result.time_s) or not np.array_equal(
        spectral_quality_result.time_s,
        refined_ridge_result.time_s,
    ):
        raise RidgeConfigurationError(
            "STFT, refined ridge, and spectral quality time_s axes must match exactly."
        )
    if not (
        stft_result.source_path
        == refined_ridge_result.source_path
        == spectral_quality_result.source_path
    ):
        raise RidgeConfigurationError(
            "STFT, refined ridge, and spectral quality source_path values must match."
        )
    metadata_pairs = (
        (
            refined_ridge_result.minimum_frequency_hz,
            spectral_quality_result.minimum_frequency_hz,
        ),
        (
            refined_ridge_result.maximum_frequency_hz,
            spectral_quality_result.maximum_frequency_hz,
        ),
        (
            refined_ridge_result.event_start_time_s,
            spectral_quality_result.event_start_time_s,
        ),
        (
            refined_ridge_result.analysis_end_time_s,
            spectral_quality_result.analysis_end_time_s,
        ),
    )
    if any(left != right for left, right in metadata_pairs):
        raise RidgeConfigurationError(
            "Refined ridge and spectral quality frequency/time ranges must match."
        )
    if (
        refined_ridge_result.quality_flags
        != spectral_quality_result.quality_flags
        or refined_ridge_result.refinement_statuses
        != spectral_quality_result.refinement_statuses
    ):
        raise RidgeConfigurationError(
            "Refined ridge and spectral quality status sequences must match."
        )
    if not np.array_equal(
        refined_ridge_result.discrete_frequency_bin_index,
        spectral_quality_result.discrete_frequency_bin_index,
    ) or not np.array_equal(
        refined_ridge_result.refined_frequency_hz,
        spectral_quality_result.refined_frequency_hz,
        equal_nan=True,
    ):
        raise RidgeConfigurationError(
            "Refined ridge and spectral quality bin/frequency arrays must match."
        )
    if stft_result.spectrum.shape != (
        stft_result.frequency_hz.size,
        frame_count,
    ):
        raise RidgeConfigurationError(
            "STFT spectrum shape is inconsistent with its physical axes."
        )
    nyquist_hz = 0.5 * stft_result.sample_rate_hz
    tolerance_hz = 64.0 * np.finfo(np.float64).eps * max(1.0, nyquist_hz)
    if float(stft_result.frequency_hz[-1]) > nyquist_hz + tolerance_hz:
        raise RidgeConfigurationError(
            "STFT frequency axis cannot exceed the Nyquist frequency."
        )
    if (
        refined_ridge_result.minimum_frequency_hz
        < float(stft_result.frequency_hz[0])
        or refined_ridge_result.maximum_frequency_hz
        > min(float(stft_result.frequency_hz[-1]), nyquist_hz)
    ):
        raise RidgeConfigurationError(
            "The explicit ridge analysis band must lie within the STFT/Nyquist range."
        )
    if len(spectral_quality_result.assessment_statuses) != frame_count:
        raise RidgeConfigurationError(
            "spectral_quality_result assessment_statuses length must match time_s."
        )
    for frame_index, flag in enumerate(refined_ridge_result.quality_flags):
        if flag is not RidgeQualityFlag.CANDIDATE:
            continue
        bin_index = int(
            refined_ridge_result.discrete_frequency_bin_index[frame_index]
        )
        if bin_index < 0 or bin_index >= stft_result.frequency_hz.size:
            raise RidgeConfigurationError(
                f"CANDIDATE bin index is out of bounds at frame {frame_index}."
            )
        if (
            stft_result.frequency_hz[bin_index]
            != refined_ridge_result.discrete_frequency_hz[frame_index]
        ):
            raise RidgeConfigurationError(
                "CANDIDATE discrete frequency and STFT bin index must match exactly."
            )


def _validate_refined_result(result: object) -> None:
    if not isinstance(result, RefinedRidgeResult):
        raise RidgeConfigurationError(
            "refined_ridge_result must be a RefinedRidgeResult instance; "
            f"got {type(result).__name__}."
        )
    frame_count = result.time_s.size
    arrays = (
        result.time_s,
        result.discrete_frequency_hz,
        result.refined_frequency_hz,
        result.discrete_frequency_bin_index,
        result.frequency_bin_offset,
        result.peak_magnitude,
    )
    if frame_count == 0 or any(
        array.ndim != 1 or array.size != frame_count for array in arrays
    ):
        raise RidgeConfigurationError(
            "Every RefinedRidgeResult array must be one-dimensional and match time_s."
        )
    if not np.all(np.isfinite(result.time_s)) or (
        frame_count > 1 and not np.all(np.diff(result.time_s) > 0.0)
    ):
        raise RidgeConfigurationError(
            "RefinedRidgeResult time_s must be finite and strictly increasing."
        )
    if (
        len(result.quality_flags) != frame_count
        or len(result.refinement_statuses) != frame_count
    ):
        raise RidgeConfigurationError(
            "RefinedRidgeResult status sequences must match time_s."
        )
    for frame_index, (time_s, flag, refinement_status) in enumerate(
        zip(result.time_s, result.quality_flags, result.refinement_statuses)
    ):
        if not isinstance(flag, RidgeQualityFlag) or not isinstance(
            refinement_status,
            RidgeRefinementStatus,
        ):
            raise RidgeConfigurationError(
                "RefinedRidgeResult contains invalid status values."
            )
        expected_flag = _expected_quality_flag(result, float(time_s))
        if expected_flag is not RidgeQualityFlag.CANDIDATE and flag is not expected_flag:
            raise RidgeConfigurationError(
                "RefinedRidgeResult analysis range and quality_flags are "
                f"inconsistent at frame {frame_index}."
            )
        if expected_flag is RidgeQualityFlag.CANDIDATE and flag not in {
            RidgeQualityFlag.CANDIDATE,
            RidgeQualityFlag.NO_ALLOWED_BINS,
        }:
            raise RidgeConfigurationError(
                "Unmasked refined ridge frames must be candidates or explicitly "
                "have no allowed bins."
            )
        bin_index = int(result.discrete_frequency_bin_index[frame_index])
        discrete_hz = float(result.discrete_frequency_hz[frame_index])
        refined_hz = float(result.refined_frequency_hz[frame_index])
        offset = float(result.frequency_bin_offset[frame_index])
        magnitude = float(result.peak_magnitude[frame_index])
        if flag is RidgeQualityFlag.CANDIDATE:
            if bin_index < 0 or not math.isfinite(discrete_hz) or not math.isfinite(
                magnitude
            ):
                raise RidgeConfigurationError(
                    "CANDIDATE frames require a valid bin, discrete frequency, and magnitude."
                )
            if refinement_status is RidgeRefinementStatus.REFINED:
                if not math.isfinite(refined_hz) or not math.isfinite(offset):
                    raise RidgeConfigurationError(
                        "REFINED frames require finite refined frequency and offset."
                    )
            elif (
                refinement_status
                in {
                    RidgeRefinementStatus.PRE_EVENT,
                    RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW,
                }
                or not math.isnan(refined_hz)
                or not math.isnan(offset)
            ):
                raise RidgeConfigurationError(
                    "Failed candidate refinements must retain NaN refined values."
                )
        else:
            if flag is RidgeQualityFlag.PRE_EVENT:
                expected_refinement = RidgeRefinementStatus.PRE_EVENT
            elif flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
                expected_refinement = RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
            else:
                expected_refinement = RidgeRefinementStatus.NO_CANDIDATE
            if (
                refinement_status is not expected_refinement
                or bin_index != -1
                or not all(
                    math.isnan(value)
                    for value in (discrete_hz, refined_hz, offset, magnitude)
                )
            ):
                raise RidgeConfigurationError(
                    "Masked RefinedRidgeResult frame is structurally inconsistent."
                )


def _expected_quality_flag(
    result: RefinedRidgeResult,
    time_s: float,
) -> RidgeQualityFlag:
    if result.event_start_time_s is not None and time_s < result.event_start_time_s:
        return RidgeQualityFlag.PRE_EVENT
    if result.analysis_end_time_s is not None and time_s > result.analysis_end_time_s:
        return RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW
    return RidgeQualityFlag.CANDIDATE


def _is_refined_candidate(result: RefinedRidgeResult, index: int) -> bool:
    return (
        result.quality_flags[index] is RidgeQualityFlag.CANDIDATE
        and result.refinement_statuses[index] is RidgeRefinementStatus.REFINED
    )


def _positive_finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise RidgeConfigurationError(
            f"{field_name} must be finite and greater than zero."
        )
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} must be finite and greater than zero."
        ) from exc
    if not math.isfinite(converted) or converted <= 0.0:
        raise RidgeConfigurationError(
            f"{field_name} must be finite and greater than zero."
        )
    return converted
