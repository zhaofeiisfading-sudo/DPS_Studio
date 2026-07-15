from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.ridge import (
    RefinedRidgeResult,
    RidgeConfigurationError,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeSpectralQualityResult,
    RidgeSpectralQualityStatus,
    assess_ridge_spectral_quality,
)
from dps_studio.core.time_frequency import STFTResult


FREQUENCY_AXIS_HZ = np.arange(0.0, 70.0, 10.0)
DEFAULT_SPECTRUM = np.array([0.5, 2.0, 4.0, 20.0, 4.0, 2.0, 0.5])


def _inputs(
    spectrum_by_frequency: np.ndarray = DEFAULT_SPECTRUM,
    *,
    time_s: np.ndarray | None = None,
    candidate_bin_index: int = 3,
    event_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    source_path: Path | None = Path("relative") / "signal.csv",
    candidate_refinement_status: RidgeRefinementStatus = (
        RidgeRefinementStatus.REFINED
    ),
) -> tuple[STFTResult, RefinedRidgeResult]:
    values = np.asarray(spectrum_by_frequency, dtype=np.complex128)
    if time_s is None:
        time_s = np.array([0.0])
    spectrum = np.repeat(values[:, None], time_s.size, axis=1)
    stft_result = STFTResult(
        time_s=time_s,
        frequency_hz=FREQUENCY_AXIS_HZ,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=12,
        overlap_samples=6,
        hop_samples=6,
        nfft=12,
        sample_rate_hz=120.0,
        source_path=source_path,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )

    discrete_frequency_hz = np.full(time_s.size, np.nan)
    refined_frequency_hz = np.full(time_s.size, np.nan)
    discrete_frequency_bin_index = np.full(time_s.size, -1, dtype=np.int64)
    frequency_bin_offset = np.full(time_s.size, np.nan)
    peak_magnitude = np.full(time_s.size, np.nan)
    quality_flags: list[RidgeQualityFlag] = []
    refinement_statuses: list[RidgeRefinementStatus] = []
    for index, time_value in enumerate(time_s):
        if event_start_time_s is not None and time_value < event_start_time_s:
            quality_flags.append(RidgeQualityFlag.PRE_EVENT)
            refinement_statuses.append(RidgeRefinementStatus.PRE_EVENT)
        elif analysis_end_time_s is not None and time_value > analysis_end_time_s:
            quality_flags.append(RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW)
            refinement_statuses.append(
                RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
            )
        else:
            quality_flags.append(RidgeQualityFlag.CANDIDATE)
            refinement_statuses.append(candidate_refinement_status)
            discrete_frequency_bin_index[index] = candidate_bin_index
            discrete_frequency_hz[index] = FREQUENCY_AXIS_HZ[candidate_bin_index]
            peak_magnitude[index] = abs(spectrum[candidate_bin_index, index])
            if candidate_refinement_status is RidgeRefinementStatus.REFINED:
                refined_frequency_hz[index] = discrete_frequency_hz[index]
                frequency_bin_offset[index] = 0.0

    refined_result = RefinedRidgeResult(
        time_s=time_s,
        discrete_frequency_hz=discrete_frequency_hz,
        refined_frequency_hz=refined_frequency_hz,
        discrete_frequency_bin_index=discrete_frequency_bin_index,
        frequency_bin_offset=frequency_bin_offset,
        peak_magnitude=peak_magnitude,
        quality_flags=tuple(quality_flags),
        refinement_statuses=tuple(refinement_statuses),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=50.0,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        refinement_method=RefinedRidgeResult.REFINEMENT_METHOD,
        source_path=source_path,
    )
    return stft_result, refined_result


def _assess(
    stft_result: STFTResult,
    refined_result: RefinedRidgeResult,
    *,
    guard_hz: float = 10.0,
    minimum_background_bin_count: int = 2,
) -> RidgeSpectralQualityResult:
    return assess_ridge_spectral_quality(
        stft_result,
        refined_result,
        background_exclusion_half_width_hz=guard_hz,
        minimum_background_bin_count=minimum_background_bin_count,
    )


def test_known_peak_and_fixed_background_recover_exact_contrast_db() -> None:
    stft_result, refined_result = _inputs()

    result = _assess(stft_result, refined_result)

    assert result.background_median_magnitude[0] == 2.0
    assert result.peak_to_background_db[0] == pytest.approx(20.0)
    assert result.assessment_statuses == (RidgeSpectralQualityStatus.ASSESSED,)


def test_known_strongest_competitor_recovers_exact_contrast_db() -> None:
    spectrum = np.array([0.5, 1.0, 4.0, 20.0, 4.0, 5.0, 0.5])
    stft_result, refined_result = _inputs(spectrum)

    result = _assess(stft_result, refined_result)

    assert result.strongest_competitor_magnitude[0] == 5.0
    assert result.peak_to_competitor_db[0] == pytest.approx(
        20.0 * np.log10(20.0 / 5.0)
    )


def test_inclusive_guard_excludes_peak_and_adjacent_boundary_bins() -> None:
    spectrum = np.array([0.5, 2.0, 100.0, 200.0, 100.0, 2.0, 0.5])
    stft_result, refined_result = _inputs(spectrum)

    result = _assess(stft_result, refined_result)

    assert result.background_bin_count[0] == 2
    assert result.background_median_magnitude[0] == 2.0
    assert result.strongest_competitor_magnitude[0] == 2.0


def test_pre_event_and_outside_frames_have_nan_quality_values() -> None:
    stft_result, refined_result = _inputs(
        time_s=np.array([0.0, 1.0, 2.0]),
        event_start_time_s=1.0,
        analysis_end_time_s=1.0,
    )

    result = _assess(stft_result, refined_result)

    assert result.assessment_statuses == (
        RidgeSpectralQualityStatus.PRE_EVENT,
        RidgeSpectralQualityStatus.ASSESSED,
        RidgeSpectralQualityStatus.OUTSIDE_ANALYSIS_WINDOW,
    )
    for array in (
        result.discrete_frequency_hz,
        result.refined_frequency_hz,
        result.peak_magnitude,
        result.background_median_magnitude,
        result.strongest_competitor_magnitude,
        result.peak_to_background_db,
        result.peak_to_competitor_db,
    ):
        assert np.isnan(array[[0, 2]]).all()
    np.testing.assert_array_equal(result.background_bin_count, [-1, 2, -1])


def test_too_few_retained_background_bins_has_explicit_status() -> None:
    stft_result, refined_result = _inputs(candidate_bin_index=2)

    result = _assess(
        stft_result,
        refined_result,
        minimum_background_bin_count=3,
    )

    assert result.assessment_statuses == (
        RidgeSpectralQualityStatus.INSUFFICIENT_BACKGROUND_BINS,
    )
    assert result.background_bin_count[0] == 2
    assert np.isnan(result.background_median_magnitude[0])
    assert np.isnan(result.peak_to_background_db[0])


@pytest.mark.parametrize("invalid_peak", [0.0, np.nan, np.inf])
def test_zero_or_nonfinite_peak_magnitude_is_invalid(invalid_peak: float) -> None:
    stft_result, refined_result = _inputs()
    corrupted = stft_result.spectrum.copy()
    corrupted[3, 0] = invalid_peak
    object.__setattr__(stft_result, "spectrum", corrupted)

    result = _assess(stft_result, refined_result)

    assert result.assessment_statuses == (
        RidgeSpectralQualityStatus.INVALID_PEAK_MAGNITUDE,
    )
    assert np.isnan(result.peak_magnitude[0])
    assert np.isnan(result.peak_to_background_db[0])
    assert np.isnan(result.peak_to_competitor_db[0])


@pytest.mark.parametrize("invalid_background", [0.0, np.nan])
def test_zero_or_nonfinite_background_median_is_invalid(
    invalid_background: float,
) -> None:
    stft_result, refined_result = _inputs()
    corrupted = stft_result.spectrum.copy()
    corrupted[1, 0] = invalid_background
    corrupted[5, 0] = invalid_background
    object.__setattr__(stft_result, "spectrum", corrupted)

    result = _assess(stft_result, refined_result)

    assert result.assessment_statuses == (
        RidgeSpectralQualityStatus.INVALID_BACKGROUND,
    )
    assert np.isnan(result.background_median_magnitude[0])
    assert np.isnan(result.peak_to_background_db[0])


def test_nonfinite_strongest_competitor_is_invalid_independently() -> None:
    spectrum = np.array([0.5, 1.0, 1.0, 20.0, 1.0, 1.0, 0.5])
    stft_result, refined_result = _inputs(spectrum)
    corrupted = stft_result.spectrum.copy()
    corrupted[5, 0] = np.inf
    object.__setattr__(stft_result, "spectrum", corrupted)

    result = _assess(stft_result, refined_result, guard_hz=0.1)

    assert result.assessment_statuses == (
        RidgeSpectralQualityStatus.INVALID_COMPETITOR,
    )
    assert result.background_median_magnitude[0] == 1.0
    assert np.isfinite(result.peak_to_background_db[0])
    assert np.isnan(result.strongest_competitor_magnitude[0])
    assert np.isnan(result.peak_to_competitor_db[0])


def test_time_axis_mismatch_is_rejected() -> None:
    _, refined_result = _inputs()
    different_stft, _ = _inputs(time_s=np.array([1.0]))

    with pytest.raises(RidgeConfigurationError, match="time_s axes"):
        _assess(different_stft, refined_result)


@pytest.mark.parametrize("invalid_bin", [-1, 7])
def test_candidate_bin_index_must_be_in_bounds(invalid_bin: int) -> None:
    stft_result, refined_result = _inputs()
    object.__setattr__(
        refined_result,
        "discrete_frequency_bin_index",
        np.array([invalid_bin], dtype=np.int64),
    )

    with pytest.raises(RidgeConfigurationError, match="out of bounds"):
        _assess(stft_result, refined_result)


def test_search_range_outside_stft_axis_is_rejected() -> None:
    stft_result, refined_result = _inputs()
    object.__setattr__(refined_result, "maximum_frequency_hz", 70.0)

    with pytest.raises(RidgeConfigurationError, match="search range"):
        _assess(stft_result, refined_result)


def test_relative_source_path_is_preserved_and_mismatch_is_rejected() -> None:
    relative_path = Path("relative") / "signal.csv"
    stft_result, refined_result = _inputs(source_path=relative_path)

    result = _assess(stft_result, refined_result)

    assert result.source_path == relative_path
    assert result.source_path is not None and not result.source_path.is_absolute()
    object.__setattr__(stft_result, "source_path", Path("other.csv"))
    with pytest.raises(RidgeConfigurationError, match="source_path"):
        _assess(stft_result, refined_result)


def test_public_imports_identity_equality_and_metadata() -> None:
    stft_result, refined_result = _inputs()
    first = _assess(stft_result, refined_result)
    second = _assess(stft_result, refined_result)

    assert first == first
    assert first != second
    assert RidgeSpectralQualityResult.__module__.endswith("quality_models")
    assert RidgeSpectralQualityStatus.__module__.endswith("quality_models")
    assert assess_ridge_spectral_quality.__module__.endswith("spectral_quality")
    assert first.background_exclusion_half_width_hz == 10.0
    assert first.minimum_background_bin_count == 2
    assert first.assessment_method == RidgeSpectralQualityResult.ASSESSMENT_METHOD


def test_mutating_inputs_after_assessment_does_not_change_result() -> None:
    stft_result, refined_result = _inputs()
    result = _assess(stft_result, refined_result)
    snapshots = {
        "time_s": result.time_s.copy(),
        "discrete_frequency_hz": result.discrete_frequency_hz.copy(),
        "peak_magnitude": result.peak_magnitude.copy(),
        "peak_to_background_db": result.peak_to_background_db.copy(),
    }

    object.__setattr__(stft_result, "spectrum", np.zeros_like(stft_result.spectrum))
    object.__setattr__(refined_result, "time_s", np.array([999.0]))
    object.__setattr__(refined_result, "discrete_frequency_hz", np.array([999.0]))

    for field_name, expected in snapshots.items():
        np.testing.assert_array_equal(getattr(result, field_name), expected)


def test_all_result_array_base_chains_are_bytes_backed_and_immutable() -> None:
    stft_result, refined_result = _inputs()
    result = _assess(stft_result, refined_result)

    for array in (
        result.time_s,
        result.discrete_frequency_hz,
        result.refined_frequency_hz,
        result.discrete_frequency_bin_index,
        result.peak_magnitude,
        result.background_median_magnitude,
        result.strongest_competitor_magnitude,
        result.peak_to_background_db,
        result.peak_to_competitor_db,
        result.background_bin_count,
    ):
        current: object = array
        visited_ids: set[int] = set()
        while isinstance(current, np.ndarray):
            assert id(current) not in visited_ids
            visited_ids.add(id(current))
            assert current.flags.writeable is False
            with pytest.raises(ValueError, match="WRITEABLE"):
                current.setflags(write=True)
            with pytest.raises(ValueError, match="read-only"):
                current.flat[0] = -999
            current = current.base
        assert isinstance(current, bytes)
        assert memoryview(current).readonly is True


@pytest.mark.parametrize("invalid_guard", [True, 0.0, -1.0, np.nan, np.inf])
def test_guard_must_be_explicit_finite_and_positive(invalid_guard: float) -> None:
    stft_result, refined_result = _inputs()

    with pytest.raises(RidgeConfigurationError, match="greater than zero"):
        _assess(stft_result, refined_result, guard_hz=invalid_guard)


def test_guard_that_removes_complete_background_is_rejected() -> None:
    stft_result, refined_result = _inputs()

    with pytest.raises(RidgeConfigurationError, match="complete search band"):
        _assess(stft_result, refined_result, guard_hz=40.0)


def test_analysis_window_metadata_and_flags_must_be_consistent() -> None:
    stft_result, refined_result = _inputs()
    object.__setattr__(refined_result, "event_start_time_s", 1.0)

    with pytest.raises(RidgeConfigurationError, match="analysis time range"):
        _assess(stft_result, refined_result)


def test_refinement_failure_does_not_change_or_block_discrete_peak_assessment() -> None:
    stft_result, refined_result = _inputs(
        candidate_refinement_status=RidgeRefinementStatus.BOUNDARY_PEAK
    )

    result = _assess(stft_result, refined_result)

    assert result.assessment_statuses == (RidgeSpectralQualityStatus.ASSESSED,)
    assert result.discrete_frequency_hz[0] == 30.0
    assert np.isnan(result.refined_frequency_hz[0])
