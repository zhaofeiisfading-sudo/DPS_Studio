"""Minimal per-frame peak-bin ridge extraction."""

from __future__ import annotations

import math
from typing import cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import (
    RidgeConfigurationError,
    RidgeExtractionError,
)
from dps_studio.core.ridge.guidance import (
    RidgeCorridorConstraint,
    validate_ridge_corridor_for_stft,
)
from dps_studio.core.ridge.models import RidgeQualityFlag, RidgeResult
from dps_studio.core.time_frequency import STFTResult


def extract_peak_ridge(
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    event_start_time_s: float | None = None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    ridge_constraint: RidgeCorridorConstraint | None = None,
    allowed_search_mask: NDArray[np.bool_] | None = None,
) -> RidgeResult:
    """Extract the largest discrete-bin magnitude in each candidate frame.

    The frequency and time ranges are closed. Equal maxima use NumPy's first
    ``argmax`` result, which is the lowest-frequency bin in the search band.
    ``event_start_time_s`` is retained as a validated compatibility-only manual
    reference and never gates peak extraction. Use ``analysis_start_time_s`` and
    ``analysis_end_time_s`` only when an explicit analysis range is required.
    An optional ridge corridor or independent allowed-search mask intersects
    the global search band. Frames with no allowed bin retain NaN and an
    explicit flag. The STFT is never modified. No smoothing, continuity
    constraint, sub-bin interpolation, or physical conversion is applied.
    """
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError(
            "stft_result must be an STFTResult instance; "
            f"got {type(stft_result).__name__}."
        )
    minimum = _finite_float(
        minimum_frequency_hz,
        field_name="minimum_frequency_hz",
    )
    maximum = _finite_float(
        maximum_frequency_hz,
        field_name="maximum_frequency_hz",
    )
    _optional_finite_float(
        event_start_time_s,
        field_name="event_start_time_s",
    )
    analysis_start = _optional_finite_float(
        analysis_start_time_s,
        field_name="analysis_start_time_s",
    )
    analysis_end = _optional_finite_float(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )

    if minimum < 0.0:
        raise RidgeConfigurationError(
            "minimum_frequency_hz must be greater than or equal to zero."
        )
    if maximum <= minimum:
        raise RidgeConfigurationError(
            "maximum_frequency_hz must be greater than minimum_frequency_hz."
        )
    grid_minimum = float(stft_result.frequency_hz[0])
    grid_maximum = float(stft_result.frequency_hz[-1])
    if maximum > grid_maximum:
        raise RidgeConfigurationError(
            f"maximum_frequency_hz={maximum!r} exceeds the STFT maximum "
            f"frequency {grid_maximum!r} Hz."
        )
    if (
        analysis_start is not None
        and analysis_end is not None
        and analysis_start > analysis_end
    ):
        raise RidgeConfigurationError(
            "analysis_start_time_s must be less than or equal to "
            "analysis_end_time_s."
        )
    if ridge_constraint is not None:
        validate_ridge_corridor_for_stft(
            ridge_constraint,
            stft_result,
            minimum_frequency_hz=minimum,
            maximum_frequency_hz=maximum,
            analysis_start_time_s=analysis_start,
            analysis_end_time_s=analysis_end,
        )
    if ridge_constraint is not None and allowed_search_mask is not None:
        raise RidgeConfigurationError(
            "ridge_constraint and allowed_search_mask are mutually exclusive."
        )
    validated_search_mask: NDArray[np.bool_] | None = None
    if allowed_search_mask is not None:
        validated_search_mask = np.asarray(allowed_search_mask, dtype=np.bool_)
        if validated_search_mask.shape != stft_result.spectrum.shape:
            raise RidgeConfigurationError(
                "allowed_search_mask must match the STFT spectrum shape."
            )

    band_mask = (stft_result.frequency_hz >= minimum) & (
        stft_result.frequency_hz <= maximum
    )
    band_indices = np.flatnonzero(band_mask)
    if band_indices.size == 0:
        spacing_context = (
            f", bin spacing starts at "
            f"{float(stft_result.frequency_hz[1] - stft_result.frequency_hz[0])!r} Hz"
            if stft_result.frequency_hz.size > 1
            else ""
        )
        raise RidgeConfigurationError(
            f"Requested closed frequency range [{minimum!r}, {maximum!r}] Hz "
            "contains no STFT frequency bin; actual grid spans "
            f"[{grid_minimum!r}, {grid_maximum!r}] Hz with "
            f"{stft_result.frequency_hz.size} bins{spacing_context}."
        )

    pre_event_mask = np.zeros(stft_result.time_s.size, dtype=np.bool_)
    outside_mask = np.zeros(stft_result.time_s.size, dtype=np.bool_)
    if analysis_start is not None:
        pre_event_mask = stft_result.time_s < analysis_start
    if analysis_end is not None:
        outside_mask = stft_result.time_s > analysis_end
    candidate_mask = ~(pre_event_mask | outside_mask)

    frequency_hz = np.full(stft_result.time_s.shape, np.nan, dtype=np.float64)
    peak_magnitude = np.full(stft_result.time_s.shape, np.nan, dtype=np.float64)
    quality_flags = [RidgeQualityFlag.CANDIDATE] * stft_result.time_s.size
    for index in np.flatnonzero(pre_event_mask):
        quality_flags[int(index)] = RidgeQualityFlag.PRE_EVENT
    for index in np.flatnonzero(outside_mask):
        quality_flags[int(index)] = RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW

    candidate_indices = np.flatnonzero(candidate_mask)
    if (
        candidate_indices.size
        and ridge_constraint is None
        and validated_search_mask is None
    ):
        try:
            magnitude = np.abs(stft_result.spectrum)
            search_band_magnitude = magnitude[np.ix_(band_indices, candidate_indices)]
            relative_peak_indices = np.argmax(search_band_magnitude, axis=0)
            frequency_indices = band_indices[relative_peak_indices]
            frequency_hz[candidate_indices] = stft_result.frequency_hz[frequency_indices]
            peak_magnitude[candidate_indices] = search_band_magnitude[
                relative_peak_indices,
                np.arange(candidate_indices.size),
            ]
        except Exception as exc:
            raise RidgeExtractionError(
                "Could not extract the baseline peak-bin ridge from the validated "
                "STFT result and search configuration."
            ) from exc
    elif candidate_indices.size:
        try:
            magnitude = np.abs(stft_result.spectrum)
            frequency_axis = stft_result.frequency_hz
            for raw_frame_index in candidate_indices:
                frame_index = int(raw_frame_index)
                allowed_indices = band_indices
                if validated_search_mask is not None:
                    allowed_indices = band_indices[
                        validated_search_mask[band_indices, frame_index]
                    ]
                else:
                    assert ridge_constraint is not None
                    corridor_band = ridge_constraint.allowed_band_hz(
                        float(stft_result.time_s[frame_index])
                    )
                    if corridor_band is None:
                        corridor_band = (minimum, maximum)
                    corridor_minimum, corridor_maximum = corridor_band
                    allowed_indices = band_indices[
                        (frequency_axis[band_indices] >= corridor_minimum)
                        & (frequency_axis[band_indices] <= corridor_maximum)
                    ]
                if allowed_indices.size == 0:
                    quality_flags[frame_index] = RidgeQualityFlag.NO_ALLOWED_BINS
                    continue
                allowed_magnitudes = magnitude[allowed_indices, frame_index]
                relative_peak_index = int(np.argmax(allowed_magnitudes))
                frequency_index = int(allowed_indices[relative_peak_index])
                frequency_hz[frame_index] = frequency_axis[frequency_index]
                peak_magnitude[frame_index] = allowed_magnitudes[
                    relative_peak_index
                ]
        except Exception as exc:
            raise RidgeExtractionError(
                "Could not extract the constrained peak-bin ridge from "
                "the validated STFT result and search configuration."
            ) from exc

    return RidgeResult(
        time_s=stft_result.time_s,
        frequency_hz=frequency_hz,
        peak_magnitude=peak_magnitude,
        quality_flags=tuple(quality_flags),
        minimum_frequency_hz=minimum,
        maximum_frequency_hz=maximum,
        event_start_time_s=analysis_start,
        analysis_end_time_s=analysis_end,
        source_path=stft_result.source_path,
    )


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise RidgeConfigurationError(f"{field_name} must be a finite float.")
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} must be a finite float."
        ) from exc
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be a finite float.")
    return converted


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name=field_name)
