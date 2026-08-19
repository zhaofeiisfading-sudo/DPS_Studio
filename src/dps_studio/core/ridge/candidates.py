"""Distinct per-frame local spectral peaks for Automatic diagnostics."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import find_peaks  # type: ignore[import-untyped]

from dps_studio.core.ridge.candidate_models import (
    LocalPeakCandidate,
    LocalPeakCandidateConfig,
    LocalPeakCandidateResult,
)
from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.quality_models import RidgeSpectralQualityStatus
from dps_studio.core.ridge.refinement import refine_three_point_log_magnitude
from dps_studio.core.time_frequency import STFTResult


def extract_local_peak_candidates(
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    background_exclusion_half_width_hz: float,
    minimum_background_bin_count: int,
    config: LocalPeakCandidateConfig,
) -> LocalPeakCandidateResult:
    """Retain a bounded set of distinct unsmoothed local maxima per frame."""
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError("stft_result must be an STFTResult.")
    if not isinstance(config, LocalPeakCandidateConfig):
        raise RidgeConfigurationError("config must be a LocalPeakCandidateConfig.")
    minimum = _finite_float(minimum_frequency_hz, "minimum_frequency_hz")
    maximum = _finite_float(maximum_frequency_hz, "maximum_frequency_hz")
    guard_hz = _finite_float(
        background_exclusion_half_width_hz,
        "background_exclusion_half_width_hz",
    )
    if minimum < 0.0 or maximum <= minimum:
        raise RidgeConfigurationError("The closed candidate search band is invalid.")
    if guard_hz <= 0.0:
        raise RidgeConfigurationError(
            "background_exclusion_half_width_hz must be strictly positive."
        )
    if (
        isinstance(minimum_background_bin_count, bool)
        or not isinstance(minimum_background_bin_count, int)
        or minimum_background_bin_count < 1
    ):
        raise RidgeConfigurationError(
            "minimum_background_bin_count must be a positive integer."
        )

    frequency_axis = stft_result.frequency_hz
    band_indices = np.flatnonzero(
        (frequency_axis >= minimum) & (frequency_axis <= maximum)
    )
    if band_indices.size < 3:
        raise RidgeConfigurationError(
            "The candidate search band must contain at least three STFT bins."
        )
    if minimum < frequency_axis[0] or maximum > frequency_axis[-1]:
        raise RidgeConfigurationError(
            "The candidate search band must lie within the STFT frequency axis."
        )
    spacing_hz = _uniform_spacing_hz(frequency_axis)
    first_band_index = int(band_indices[0])
    last_band_index = int(band_indices[-1])

    candidates_by_frame: list[tuple[LocalPeakCandidate, ...]] = []
    for frame_index in range(stft_result.time_s.size):
        magnitudes = np.abs(stft_result.spectrum[band_indices, frame_index])
        local_offsets, _ = find_peaks(magnitudes, plateau_size=(1, None))
        ranked_offsets = sorted(
            (int(offset) for offset in local_offsets),
            key=lambda offset: (-float(magnitudes[offset]), int(band_indices[offset])),
        )[: config.maximum_candidates_per_frame]
        frame_candidates = tuple(
            _candidate(
                stft_result,
                frame_index=frame_index,
                bin_index=int(band_indices[offset]),
                amplitude_rank=rank,
                band_indices=band_indices,
                first_band_index=first_band_index,
                last_band_index=last_band_index,
                frequency_spacing_hz=spacing_hz,
                minimum_frequency_hz=minimum,
                maximum_frequency_hz=maximum,
                guard_hz=guard_hz,
                minimum_background_bin_count=minimum_background_bin_count,
            )
            for rank, offset in enumerate(ranked_offsets, start=1)
        )
        candidates_by_frame.append(frame_candidates)

    return LocalPeakCandidateResult(
        time_s=stft_result.time_s,
        candidates_by_frame=tuple(candidates_by_frame),
        minimum_frequency_hz=minimum,
        maximum_frequency_hz=maximum,
        background_exclusion_half_width_hz=guard_hz,
        minimum_background_bin_count=minimum_background_bin_count,
        config=config,
        extraction_method=LocalPeakCandidateResult.EXTRACTION_METHOD,
        source_path=stft_result.source_path,
    )


def _candidate(
    stft_result: STFTResult,
    *,
    frame_index: int,
    bin_index: int,
    amplitude_rank: int,
    band_indices: np.ndarray,
    first_band_index: int,
    last_band_index: int,
    frequency_spacing_hz: float,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    guard_hz: float,
    minimum_background_bin_count: int,
) -> LocalPeakCandidate:
    magnitude = float(abs(stft_result.spectrum[bin_index, frame_index]))
    discrete_frequency_hz = float(stft_result.frequency_hz[bin_index])
    local_magnitudes = np.abs(
        stft_result.spectrum[bin_index - 1 : bin_index + 2, frame_index]
    )
    refined_frequency_hz, frequency_bin_offset, refinement_status = (
        refine_three_point_log_magnitude(
            left_magnitude=float(local_magnitudes[0]),
            center_magnitude=float(local_magnitudes[1]),
            right_magnitude=float(local_magnitudes[2]),
            discrete_frequency_hz=discrete_frequency_hz,
            frequency_spacing_hz=frequency_spacing_hz,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
            boundary_peak=(
                bin_index == 0
                or bin_index == stft_result.frequency_hz.size - 1
                or bin_index == first_band_index
                or bin_index == last_band_index
            ),
        )
    )
    retained = band_indices[
        np.abs(stft_result.frequency_hz[band_indices] - discrete_frequency_hz)
        > guard_hz
    ]
    background_count = int(retained.size)
    background = math.nan
    competitor = math.nan
    peak_to_background_db = math.nan
    peak_to_competitor_db = math.nan
    if not math.isfinite(magnitude) or magnitude <= 0.0:
        quality_status = RidgeSpectralQualityStatus.INVALID_PEAK_MAGNITUDE
    elif background_count < minimum_background_bin_count:
        quality_status = RidgeSpectralQualityStatus.INSUFFICIENT_BACKGROUND_BINS
    else:
        background_magnitudes = np.abs(stft_result.spectrum[retained, frame_index])
        background = float(np.median(background_magnitudes))
        competitor = float(np.max(background_magnitudes))
        if not math.isfinite(background) or background <= 0.0:
            quality_status = RidgeSpectralQualityStatus.INVALID_BACKGROUND
        elif not math.isfinite(competitor) or competitor <= 0.0:
            quality_status = RidgeSpectralQualityStatus.INVALID_COMPETITOR
        else:
            peak_to_background_db = _contrast_db(magnitude, background)
            peak_to_competitor_db = _contrast_db(magnitude, competitor)
            quality_status = RidgeSpectralQualityStatus.ASSESSED
    return LocalPeakCandidate(
        bin_index=bin_index,
        discrete_frequency_hz=discrete_frequency_hz,
        magnitude=magnitude,
        amplitude_rank=amplitude_rank,
        refined_frequency_hz=refined_frequency_hz,
        frequency_bin_offset=frequency_bin_offset,
        refinement_status=refinement_status,
        background_median_magnitude=background,
        strongest_competitor_magnitude=competitor,
        peak_to_background_db=peak_to_background_db,
        peak_to_competitor_db=peak_to_competitor_db,
        background_bin_count=background_count,
        spectral_quality_status=quality_status,
    )


def _contrast_db(numerator: float, denominator: float) -> float:
    return 20.0 * (math.log10(numerator) - math.log10(denominator))


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise RidgeConfigurationError(f"{field_name} must be finite.")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(f"{field_name} must be finite.") from exc
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be finite.")
    return converted


def _uniform_spacing_hz(frequency_axis: np.ndarray) -> float:
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
            "STFT frequency_hz must be uniformly spaced for candidate refinement."
        )
    return spacing_hz


__all__ = ["extract_local_peak_candidates"]
