"""Per-frame spectral contrast assessment for an already-selected ridge peak."""

from __future__ import annotations

import math
from numbers import Integral
from typing import cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import (
    RidgeConfigurationError,
    RidgeExtractionError,
)
from dps_studio.core.ridge.models import (
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
)
from dps_studio.core.ridge.quality_models import (
    RidgeSpectralQualityResult,
    RidgeSpectralQualityStatus,
)
from dps_studio.core.time_frequency import STFTResult


IntArray = NDArray[np.int64]


def assess_ridge_spectral_quality(
    stft_result: STFTResult,
    refined_ridge_result: RefinedRidgeResult,
    *,
    background_exclusion_half_width_hz: float,
    minimum_background_bin_count: int,
) -> RidgeSpectralQualityResult:
    """Assess spectral contrast without changing, dropping, or smoothing ridge points.

    The inclusive guard removes all search-band bins satisfying
    ``abs(frequency_hz - discrete_frequency_hz) <= guard``. The remaining
    magnitudes define the background median and strongest competitor. The two
    reported contrasts are magnitude ratios in dB and are not a formal SNR.
    """
    exclusion_half_width_hz = _positive_finite_float(
        background_exclusion_half_width_hz,
        field_name="background_exclusion_half_width_hz",
    )
    minimum_bin_count = _positive_integer(
        minimum_background_bin_count,
        field_name="minimum_background_bin_count",
    )
    band_indices = _validate_inputs(
        stft_result,
        refined_ridge_result,
        exclusion_half_width_hz=exclusion_half_width_hz,
    )

    frame_count = stft_result.time_s.size
    peak_magnitude = np.full(frame_count, np.nan, dtype=np.float64)
    background_median_magnitude = np.full(frame_count, np.nan, dtype=np.float64)
    strongest_competitor_magnitude = np.full(
        frame_count,
        np.nan,
        dtype=np.float64,
    )
    peak_to_background_db = np.full(frame_count, np.nan, dtype=np.float64)
    peak_to_competitor_db = np.full(frame_count, np.nan, dtype=np.float64)
    background_bin_count = np.full(frame_count, -1, dtype=np.int64)
    assessment_statuses: list[RidgeSpectralQualityStatus] = []

    background_indices_by_frame: dict[int, IntArray] = {}
    for frame_index, flag in enumerate(refined_ridge_result.quality_flags):
        if flag is not RidgeQualityFlag.CANDIDATE:
            continue
        peak_bin_index = int(
            refined_ridge_result.discrete_frequency_bin_index[frame_index]
        )
        peak_frequency_hz = float(stft_result.frequency_hz[peak_bin_index])
        retained = band_indices[
            np.abs(stft_result.frequency_hz[band_indices] - peak_frequency_hz)
            > exclusion_half_width_hz
        ]
        if retained.size == 0:
            raise RidgeConfigurationError(
                "background_exclusion_half_width_hz removes every search-band "
                f"background bin for candidate frame {frame_index}."
            )
        background_indices_by_frame[frame_index] = retained
        background_bin_count[frame_index] = retained.size

    try:
        for frame_index, flag in enumerate(refined_ridge_result.quality_flags):
            if flag is RidgeQualityFlag.PRE_EVENT:
                assessment_statuses.append(RidgeSpectralQualityStatus.PRE_EVENT)
                continue
            if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
                assessment_statuses.append(
                    RidgeSpectralQualityStatus.OUTSIDE_ANALYSIS_WINDOW
                )
                continue
            if flag is RidgeQualityFlag.NO_ALLOWED_BINS:
                assessment_statuses.append(
                    RidgeSpectralQualityStatus.NO_CANDIDATE
                )
                continue

            peak_bin_index = int(
                refined_ridge_result.discrete_frequency_bin_index[frame_index]
            )
            raw_peak_magnitude = float(
                np.abs(stft_result.spectrum[peak_bin_index, frame_index])
            )
            if not math.isfinite(raw_peak_magnitude) or raw_peak_magnitude <= 0.0:
                assessment_statuses.append(
                    RidgeSpectralQualityStatus.INVALID_PEAK_MAGNITUDE
                )
                continue
            peak_magnitude[frame_index] = raw_peak_magnitude

            background_indices = background_indices_by_frame[frame_index]
            if background_indices.size < minimum_bin_count:
                assessment_statuses.append(
                    RidgeSpectralQualityStatus.INSUFFICIENT_BACKGROUND_BINS
                )
                continue

            background_magnitudes = np.abs(
                stft_result.spectrum[background_indices, frame_index]
            )
            raw_background_median = float(np.median(background_magnitudes))
            raw_competitor = float(np.max(background_magnitudes))
            background_valid = (
                math.isfinite(raw_background_median)
                and raw_background_median > 0.0
            )
            competitor_valid = math.isfinite(raw_competitor) and raw_competitor > 0.0

            if background_valid:
                background_median_magnitude[frame_index] = raw_background_median
                peak_to_background_db[frame_index] = _magnitude_contrast_db(
                    raw_peak_magnitude,
                    raw_background_median,
                )
            if competitor_valid:
                strongest_competitor_magnitude[frame_index] = raw_competitor
                peak_to_competitor_db[frame_index] = _magnitude_contrast_db(
                    raw_peak_magnitude,
                    raw_competitor,
                )

            if not background_valid:
                assessment_statuses.append(
                    RidgeSpectralQualityStatus.INVALID_BACKGROUND
                )
            elif not competitor_valid:
                assessment_statuses.append(
                    RidgeSpectralQualityStatus.INVALID_COMPETITOR
                )
            else:
                assessment_statuses.append(RidgeSpectralQualityStatus.ASSESSED)
    except Exception as exc:
        raise RidgeExtractionError(
            "Could not assess ridge spectral quality from the validated inputs."
        ) from exc

    return RidgeSpectralQualityResult(
        time_s=refined_ridge_result.time_s,
        discrete_frequency_hz=refined_ridge_result.discrete_frequency_hz,
        refined_frequency_hz=refined_ridge_result.refined_frequency_hz,
        discrete_frequency_bin_index=(
            refined_ridge_result.discrete_frequency_bin_index
        ),
        peak_magnitude=peak_magnitude,
        background_median_magnitude=background_median_magnitude,
        strongest_competitor_magnitude=strongest_competitor_magnitude,
        peak_to_background_db=peak_to_background_db,
        peak_to_competitor_db=peak_to_competitor_db,
        background_bin_count=background_bin_count,
        quality_flags=refined_ridge_result.quality_flags,
        refinement_statuses=refined_ridge_result.refinement_statuses,
        assessment_statuses=tuple(assessment_statuses),
        minimum_frequency_hz=refined_ridge_result.minimum_frequency_hz,
        maximum_frequency_hz=refined_ridge_result.maximum_frequency_hz,
        event_start_time_s=refined_ridge_result.event_start_time_s,
        analysis_end_time_s=refined_ridge_result.analysis_end_time_s,
        background_exclusion_half_width_hz=exclusion_half_width_hz,
        minimum_background_bin_count=minimum_bin_count,
        assessment_method=RidgeSpectralQualityResult.ASSESSMENT_METHOD,
        source_path=refined_ridge_result.source_path,
    )


def _validate_inputs(
    stft_result: object,
    refined_ridge_result: object,
    *,
    exclusion_half_width_hz: float,
) -> IntArray:
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
    frame_count = stft_result.time_s.size
    if refined_ridge_result.time_s.size != frame_count:
        raise RidgeConfigurationError(
            "STFTResult and RefinedRidgeResult must contain the same number of "
            "time frames."
        )
    if not np.array_equal(stft_result.time_s, refined_ridge_result.time_s):
        raise RidgeConfigurationError(
            "STFTResult and RefinedRidgeResult time_s axes must match exactly."
        )
    if stft_result.source_path != refined_ridge_result.source_path:
        raise RidgeConfigurationError(
            "STFTResult and RefinedRidgeResult source_path values must match exactly."
        )
    if stft_result.spectrum.shape != (
        stft_result.frequency_hz.size,
        frame_count,
    ):
        raise RidgeConfigurationError(
            "STFTResult spectrum shape is inconsistent with its frequency and time axes."
        )

    required_arrays = (
        refined_ridge_result.discrete_frequency_hz,
        refined_ridge_result.refined_frequency_hz,
        refined_ridge_result.discrete_frequency_bin_index,
        refined_ridge_result.frequency_bin_offset,
        refined_ridge_result.peak_magnitude,
    )
    if any(array.ndim != 1 or array.size != frame_count for array in required_arrays):
        raise RidgeConfigurationError(
            "Every RefinedRidgeResult array must be one-dimensional and match time_s."
        )
    if (
        len(refined_ridge_result.quality_flags) != frame_count
        or len(refined_ridge_result.refinement_statuses) != frame_count
    ):
        raise RidgeConfigurationError(
            "RefinedRidgeResult status lengths must match its time axis."
        )

    grid_minimum = float(stft_result.frequency_hz[0])
    grid_maximum = float(stft_result.frequency_hz[-1])
    if (
        refined_ridge_result.minimum_frequency_hz < grid_minimum
        or refined_ridge_result.maximum_frequency_hz > grid_maximum
    ):
        raise RidgeConfigurationError(
            "RefinedRidgeResult search range must lie within the STFT frequency axis."
        )
    band_indices = np.flatnonzero(
        (stft_result.frequency_hz >= refined_ridge_result.minimum_frequency_hz)
        & (stft_result.frequency_hz <= refined_ridge_result.maximum_frequency_hz)
    ).astype(np.int64, copy=False)
    if band_indices.size < 2:
        raise RidgeConfigurationError(
            "The closed ridge search range must contain at least two STFT bins for "
            "spectral-quality assessment."
        )
    band_span_hz = float(
        stft_result.frequency_hz[int(band_indices[-1])]
        - stft_result.frequency_hz[int(band_indices[0])]
    )
    if exclusion_half_width_hz >= band_span_hz:
        raise RidgeConfigurationError(
            "background_exclusion_half_width_hz removes the complete search band."
        )

    expected_flags = _expected_quality_flags(refined_ridge_result)
    for frame_index, (flag, refinement_status, expected_flag) in enumerate(
        zip(
            refined_ridge_result.quality_flags,
            refined_ridge_result.refinement_statuses,
            expected_flags,
        )
    ):
        if not isinstance(flag, RidgeQualityFlag) or not isinstance(
            refinement_status,
            RidgeRefinementStatus,
        ):
            raise RidgeConfigurationError(
                "RefinedRidgeResult statuses contain invalid values."
            )
        if expected_flag is not RidgeQualityFlag.CANDIDATE and flag is not expected_flag:
            raise RidgeConfigurationError(
                "RefinedRidgeResult analysis time range and quality_flags are "
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
        bin_index = int(
            refined_ridge_result.discrete_frequency_bin_index[frame_index]
        )
        discrete_frequency_hz = float(
            refined_ridge_result.discrete_frequency_hz[frame_index]
        )
        refined_frequency_hz = float(
            refined_ridge_result.refined_frequency_hz[frame_index]
        )
        original_peak_magnitude = float(
            refined_ridge_result.peak_magnitude[frame_index]
        )
        if flag is RidgeQualityFlag.CANDIDATE:
            if refinement_status in {
                RidgeRefinementStatus.PRE_EVENT,
                RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW,
            }:
                raise RidgeConfigurationError(
                    "CANDIDATE frames cannot use masked refinement statuses."
                )
            if bin_index < 0 or bin_index >= stft_result.frequency_hz.size:
                raise RidgeConfigurationError(
                    f"CANDIDATE discrete bin index is out of bounds at frame {frame_index}."
                )
            if (
                not math.isfinite(discrete_frequency_hz)
                or stft_result.frequency_hz[bin_index] != discrete_frequency_hz
            ):
                raise RidgeConfigurationError(
                    "CANDIDATE discrete frequency and STFT bin index must match exactly."
                )
            if not (
                refined_ridge_result.minimum_frequency_hz
                <= discrete_frequency_hz
                <= refined_ridge_result.maximum_frequency_hz
            ):
                raise RidgeConfigurationError(
                    "CANDIDATE discrete frequency must lie within the ridge search range."
                )
            if not math.isfinite(original_peak_magnitude) or original_peak_magnitude < 0.0:
                raise RidgeConfigurationError(
                    "CANDIDATE RefinedRidgeResult peak magnitude must be finite and "
                    "non-negative."
                )
            if refinement_status is RidgeRefinementStatus.REFINED:
                if not math.isfinite(refined_frequency_hz):
                    raise RidgeConfigurationError(
                        "REFINED frames must retain finite refined frequency."
                    )
            elif not math.isnan(refined_frequency_hz):
                raise RidgeConfigurationError(
                    "Failed candidate refinements must retain NaN refined frequency."
                )
        else:
            if flag is RidgeQualityFlag.PRE_EVENT:
                expected_refinement_status = RidgeRefinementStatus.PRE_EVENT
            elif flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
                expected_refinement_status = (
                    RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
                )
            else:
                expected_refinement_status = RidgeRefinementStatus.NO_CANDIDATE
            if refinement_status is not expected_refinement_status:
                raise RidgeConfigurationError(
                    "Masked quality flags and refinement statuses must match."
                )
            if (
                bin_index != -1
                or not math.isnan(discrete_frequency_hz)
                or not math.isnan(refined_frequency_hz)
                or not math.isnan(original_peak_magnitude)
            ):
                raise RidgeConfigurationError(
                    "Masked RefinedRidgeResult frames must retain bin index -1 and "
                    "NaN values."
                )
    return band_indices


def _expected_quality_flags(
    result: RefinedRidgeResult,
) -> tuple[RidgeQualityFlag, ...]:
    expected: list[RidgeQualityFlag] = []
    for time_s in result.time_s:
        if result.event_start_time_s is not None and time_s < result.event_start_time_s:
            expected.append(RidgeQualityFlag.PRE_EVENT)
        elif result.analysis_end_time_s is not None and time_s > result.analysis_end_time_s:
            expected.append(RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW)
        else:
            expected.append(RidgeQualityFlag.CANDIDATE)
    return tuple(expected)


def _magnitude_contrast_db(numerator: float, denominator: float) -> float:
    return 20.0 * (math.log10(numerator) - math.log10(denominator))


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


def _positive_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise RidgeConfigurationError(
            f"{field_name} must be a positive integer and cannot be bool."
        )
    converted = int(value)
    if converted <= 0:
        raise RidgeConfigurationError(f"{field_name} must be greater than zero.")
    return converted
