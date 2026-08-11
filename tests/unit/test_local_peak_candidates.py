from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.ridge import (
    LocalPeakCandidateConfig,
    RidgeRefinementStatus,
    RidgeSpectralQualityStatus,
    extract_local_peak_candidates,
)
from dps_studio.core.time_frequency import STFTResult


def _stft(magnitudes: np.ndarray) -> STFTResult:
    values = np.asarray(magnitudes, dtype=np.complex128)
    if values.ndim == 1:
        values = values[:, None]
    frequency_hz = np.arange(values.shape[0], dtype=np.float64) * 10.0
    return STFTResult(
        time_s=np.arange(values.shape[1], dtype=np.float64),
        frequency_hz=frequency_hz,
        spectrum=values,
        window_name="hann",
        window_length_samples=8,
        overlap_samples=4,
        hop_samples=4,
        nfft=2 * (values.shape[0] - 1),
        sample_rate_hz=20.0 * (values.shape[0] - 1),
        source_path=Path("synthetic.csv"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _extract(
    magnitudes: np.ndarray,
    *,
    maximum_candidates: int = 3,
    minimum_frequency_hz: float = 10.0,
    maximum_frequency_hz: float = 70.0,
) -> object:
    return extract_local_peak_candidates(
        _stft(magnitudes),
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        background_exclusion_half_width_hz=10.0,
        minimum_background_bin_count=2,
        config=LocalPeakCandidateConfig(maximum_candidates),
    )


def test_single_local_peak_is_retained_and_refined() -> None:
    result = _extract(np.array([0.1, 0.2, 1.0, 4.0, 1.0, 0.2, 0.1, 0.1, 0.1]))

    candidate = result.candidates_by_frame[0][0]
    assert candidate.bin_index == 3
    assert candidate.discrete_frequency_hz == 30.0
    assert candidate.amplitude_rank == 1
    assert candidate.refined_frequency_hz == pytest.approx(30.0)
    assert candidate.refinement_status is RidgeRefinementStatus.REFINED
    assert candidate.spectral_quality_status is RidgeSpectralQualityStatus.ASSESSED
    assert candidate.peak_to_background_db > 20.0


def test_distinct_peaks_are_ranked_and_k_truncated() -> None:
    magnitudes = np.array([0.1, 0.2, 5.0, 0.5, 9.0, 0.5, 7.0, 0.2, 0.1])

    result = _extract(magnitudes, maximum_candidates=2)

    assert [candidate.bin_index for candidate in result.candidates_by_frame[0]] == [4, 6]
    assert [candidate.amplitude_rank for candidate in result.candidates_by_frame[0]] == [1, 2]


def test_plateau_is_one_peak_not_multiple_adjacent_fft_bins() -> None:
    result = _extract(np.array([0.1, 0.2, 1.0, 5.0, 5.0, 5.0, 1.0, 0.2, 0.1]))

    assert len(result.candidates_by_frame[0]) == 1
    assert result.candidates_by_frame[0][0].bin_index == 4


def test_search_band_excludes_outside_peak_and_monotonic_band_has_no_candidate() -> None:
    outside = _extract(
        np.array([0.1, 20.0, 0.1, 1.0, 3.0, 2.0, 1.0, 0.2, 0.1]),
        minimum_frequency_hz=20.0,
        maximum_frequency_hz=70.0,
    )
    monotonic = _extract(np.arange(9, dtype=np.float64))

    assert [candidate.bin_index for candidate in outside.candidates_by_frame[0]] == [4]
    assert monotonic.candidates_by_frame[0] == ()


def test_refinement_failure_is_explicit_and_never_uses_discrete_fallback() -> None:
    result = _extract(np.array([0.1, 0.0, 5.0, 1.0, 0.2, 0.1, 0.1, 0.1, 0.1]))

    candidate = result.candidates_by_frame[0][0]
    assert candidate.refinement_status is RidgeRefinementStatus.INVALID_LOCAL_PEAK
    assert np.isnan(candidate.refined_frequency_hz)
    assert np.isnan(candidate.frequency_bin_offset)


def test_alternative_quality_is_independent_and_strongest_can_be_competitor() -> None:
    result = _extract(np.array([0.1, 0.2, 10.0, 1.0, 0.2, 8.0, 0.2, 0.1, 0.1]))

    strongest, alternative = result.candidates_by_frame[0]
    assert alternative.strongest_competitor_magnitude == pytest.approx(strongest.magnitude)
    assert alternative.peak_to_competitor_db == pytest.approx(
        20.0 * np.log10(alternative.magnitude / strongest.magnitude)
    )
    assert alternative.peak_to_competitor_db < 0.0
    assert alternative.peak_to_competitor_db != strongest.peak_to_competitor_db
