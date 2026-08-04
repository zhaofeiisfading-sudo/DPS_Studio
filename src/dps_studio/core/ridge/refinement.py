"""Local three-point sub-bin refinement of a baseline peak ridge."""

from __future__ import annotations

import math

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
    RidgeResult,
)
from dps_studio.core.time_frequency import STFTResult


def refine_peak_ridge_subbin(
    stft_result: STFTResult,
    ridge_result: RidgeResult,
) -> RefinedRidgeResult:
    """Refine each TASK-005 candidate using its two adjacent frequency bins."""
    _validate_inputs(stft_result, ridge_result)

    frequency_axis = stft_result.frequency_hz
    spacing_hz = _uniform_frequency_spacing(frequency_axis)
    band_indices = np.flatnonzero(
        (frequency_axis >= ridge_result.minimum_frequency_hz)
        & (frequency_axis <= ridge_result.maximum_frequency_hz)
    )
    if band_indices.size == 0:
        raise RidgeConfigurationError(
            "RidgeResult search range must contain at least one STFT frequency bin."
        )
    first_band_index = int(band_indices[0])
    last_band_index = int(band_indices[-1])

    frame_count = ridge_result.time_s.size
    refined_frequency_hz = np.full(frame_count, np.nan, dtype=np.float64)
    discrete_frequency_bin_index = np.full(frame_count, -1, dtype=np.int64)
    frequency_bin_offset = np.full(frame_count, np.nan, dtype=np.float64)
    statuses: list[RidgeRefinementStatus] = []

    try:
        for frame_index, flag in enumerate(ridge_result.quality_flags):
            if flag is RidgeQualityFlag.PRE_EVENT:
                statuses.append(RidgeRefinementStatus.PRE_EVENT)
                continue
            if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
                statuses.append(RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW)
                continue
            if flag is RidgeQualityFlag.NO_ALLOWED_BINS:
                statuses.append(RidgeRefinementStatus.NO_CANDIDATE)
                continue

            discrete_frequency = float(ridge_result.frequency_hz[frame_index])
            frequency_index = int(np.searchsorted(frequency_axis, discrete_frequency))
            discrete_frequency_bin_index[frame_index] = frequency_index
            if (
                frequency_index == 0
                or frequency_index == frequency_axis.size - 1
                or frequency_index == first_band_index
                or frequency_index == last_band_index
            ):
                statuses.append(RidgeRefinementStatus.BOUNDARY_PEAK)
                continue

            local_magnitudes = np.abs(
                stft_result.spectrum[
                    frequency_index - 1 : frequency_index + 2,
                    frame_index,
                ]
            )
            if not np.all(np.isfinite(local_magnitudes)) or not np.all(
                local_magnitudes > 0.0
            ):
                statuses.append(RidgeRefinementStatus.INVALID_LOCAL_PEAK)
                continue

            y_left, y_center, y_right = (
                float(value) for value in np.log(local_magnitudes)
            )
            if not all(math.isfinite(value) for value in (y_left, y_center, y_right)):
                statuses.append(RidgeRefinementStatus.INVALID_LOCAL_PEAK)
                continue
            denominator = y_left - 2.0 * y_center + y_right
            denominator_tolerance = 16.0 * np.finfo(np.float64).eps * max(
                1.0,
                abs(y_left),
                2.0 * abs(y_center),
                abs(y_right),
            )
            if (
                not math.isfinite(denominator)
                or denominator >= 0.0
                or abs(denominator) <= denominator_tolerance
            ):
                statuses.append(RidgeRefinementStatus.INVALID_LOCAL_PEAK)
                continue

            delta = 0.5 * (y_left - y_right) / denominator
            if not math.isfinite(delta) or not -0.5 <= delta <= 0.5:
                statuses.append(RidgeRefinementStatus.OFFSET_OUT_OF_RANGE)
                continue
            refined_frequency = discrete_frequency + delta * spacing_hz
            if (
                not math.isfinite(refined_frequency)
                or refined_frequency < ridge_result.minimum_frequency_hz
                or refined_frequency > ridge_result.maximum_frequency_hz
                or refined_frequency < frequency_axis[0]
                or refined_frequency > frequency_axis[-1]
            ):
                statuses.append(RidgeRefinementStatus.OFFSET_OUT_OF_RANGE)
                continue

            refined_frequency_hz[frame_index] = refined_frequency
            frequency_bin_offset[frame_index] = delta
            statuses.append(RidgeRefinementStatus.REFINED)
    except Exception as exc:
        raise RidgeExtractionError(
            "Could not refine the baseline ridge with local three-point interpolation."
        ) from exc

    return RefinedRidgeResult(
        time_s=ridge_result.time_s,
        discrete_frequency_hz=ridge_result.frequency_hz,
        refined_frequency_hz=refined_frequency_hz,
        discrete_frequency_bin_index=discrete_frequency_bin_index,
        frequency_bin_offset=frequency_bin_offset,
        peak_magnitude=ridge_result.peak_magnitude,
        quality_flags=ridge_result.quality_flags,
        refinement_statuses=tuple(statuses),
        minimum_frequency_hz=ridge_result.minimum_frequency_hz,
        maximum_frequency_hz=ridge_result.maximum_frequency_hz,
        event_start_time_s=ridge_result.event_start_time_s,
        analysis_end_time_s=ridge_result.analysis_end_time_s,
        refinement_method=RefinedRidgeResult.REFINEMENT_METHOD,
        source_path=ridge_result.source_path,
    )


def _validate_inputs(stft_result: object, ridge_result: object) -> None:
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError(
            "stft_result must be an STFTResult instance; "
            f"got {type(stft_result).__name__}."
        )
    if not isinstance(ridge_result, RidgeResult):
        raise RidgeConfigurationError(
            "ridge_result must be a RidgeResult instance; "
            f"got {type(ridge_result).__name__}."
        )
    if stft_result.time_s.size != ridge_result.time_s.size:
        raise RidgeConfigurationError(
            "STFTResult and RidgeResult must contain the same number of time frames."
        )
    if not np.array_equal(stft_result.time_s, ridge_result.time_s):
        raise RidgeConfigurationError(
            "STFTResult and RidgeResult time_s axes must match exactly."
        )
    if stft_result.source_path != ridge_result.source_path:
        raise RidgeConfigurationError(
            "STFTResult and RidgeResult source_path values must match exactly."
        )
    grid_minimum = float(stft_result.frequency_hz[0])
    grid_maximum = float(stft_result.frequency_hz[-1])
    if (
        ridge_result.minimum_frequency_hz < grid_minimum
        or ridge_result.maximum_frequency_hz > grid_maximum
    ):
        raise RidgeConfigurationError(
            "RidgeResult search range must lie within the STFT frequency axis."
        )
    if len(ridge_result.quality_flags) != ridge_result.time_s.size:
        raise RidgeConfigurationError(
            "RidgeResult quality_flags length must match its time axis."
        )

    for frame_index, flag in enumerate(ridge_result.quality_flags):
        if not isinstance(flag, RidgeQualityFlag):
            raise RidgeConfigurationError(
                "RidgeResult quality_flags must contain only RidgeQualityFlag values."
            )
        frequency = float(ridge_result.frequency_hz[frame_index])
        magnitude = float(ridge_result.peak_magnitude[frame_index])
        if flag is RidgeQualityFlag.CANDIDATE:
            if not math.isfinite(frequency) or not math.isfinite(magnitude):
                raise RidgeConfigurationError(
                    "CANDIDATE RidgeResult frames must retain finite frequency and magnitude."
                )
            frequency_index = int(np.searchsorted(stft_result.frequency_hz, frequency))
            if (
                frequency_index >= stft_result.frequency_hz.size
                or stft_result.frequency_hz[frequency_index] != frequency
            ):
                raise RidgeConfigurationError(
                    "Every finite RidgeResult frequency must exactly match an STFT bin."
                )
        elif not math.isnan(frequency) or not math.isnan(magnitude):
            raise RidgeConfigurationError(
                "Masked RidgeResult frames must retain NaN frequency and magnitude."
            )


def _uniform_frequency_spacing(frequency_axis: NDArray[np.float64]) -> float:
    if frequency_axis.size < 2:
        raise RidgeConfigurationError(
            "STFT frequency axis must contain at least two bins for refinement."
        )
    spacings = np.diff(frequency_axis)
    spacing_hz = float(spacings[0])
    tolerance = (
        64.0
        * np.finfo(np.float64).eps
        * max(1, frequency_axis.size)
        * max(1.0, abs(spacing_hz))
    )
    if not np.all(np.abs(spacings - spacing_hz) <= tolerance):
        raise RidgeConfigurationError(
            "STFT frequency axis must have uniform bin spacing for refinement."
        )
    return spacing_hz
