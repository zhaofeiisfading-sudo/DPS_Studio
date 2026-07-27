from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.ridge import (
    RefinedRidgeResult,
    RidgeConfigurationError,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeResult,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import STFTResult


FREQUENCY_AXIS = np.array([0.0, 10.0, 20.0, 30.0, 40.0])


def _log_parabola_magnitude(delta: float, *, height: float = 2.0) -> np.ndarray:
    positions = np.array([-1.0, 0.0, 1.0])
    return np.exp(height - (positions - delta) ** 2)


def _stft(
    local_magnitudes_by_frame: np.ndarray,
    *,
    source_path: Path | None = None,
    time_s: np.ndarray | None = None,
) -> STFTResult:
    local = np.asarray(local_magnitudes_by_frame, dtype=np.complex128)
    if local.ndim == 1:
        local = local[:, None]
    if time_s is None:
        time_s = np.arange(local.shape[1], dtype=np.float64)
    spectrum = np.full((FREQUENCY_AXIS.size, local.shape[1]), 1.0e-6 + 0.0j)
    spectrum[1:4, :] = local
    return STFTResult(
        time_s=time_s,
        frequency_hz=FREQUENCY_AXIS,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=8,
        overlap_samples=4,
        hop_samples=4,
        nfft=8,
        sample_rate_hz=80.0,
        source_path=source_path,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _ridge(
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float = 10.0,
    maximum_frequency_hz: float = 30.0,
    event_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
) -> RidgeResult:
    return extract_peak_ridge(
        stft_result,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        analysis_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
    )


def _manual_center_ridge(stft_result: STFTResult) -> RidgeResult:
    return RidgeResult(
        time_s=stft_result.time_s,
        frequency_hz=np.full(stft_result.time_s.size, 20.0),
        peak_magnitude=np.abs(stft_result.spectrum[2]),
        quality_flags=(RidgeQualityFlag.CANDIDATE,) * stft_result.time_s.size,
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        event_start_time_s=None,
        analysis_end_time_s=None,
        source_path=stft_result.source_path,
    )


@pytest.mark.parametrize("delta", [0.0, 0.25, -0.30])
def test_known_log_parabola_offsets_follow_fixed_formula(delta: float) -> None:
    stft_result = _stft(_log_parabola_magnitude(delta))
    ridge_result = _ridge(stft_result)

    result = refine_peak_ridge_subbin(stft_result, ridge_result)

    assert result.frequency_bin_offset[0] == pytest.approx(delta)
    assert result.refined_frequency_hz[0] == pytest.approx(20.0 + 10.0 * delta)
    assert result.refinement_statuses == (RidgeRefinementStatus.REFINED,)


def test_multiple_frames_are_refined_independently_without_integer_clamping() -> None:
    deltas = np.array([-0.4, -0.1, 0.2, 0.45])
    local = np.column_stack([_log_parabola_magnitude(delta) for delta in deltas])
    stft_result = _stft(local)

    result = refine_peak_ridge_subbin(stft_result, _ridge(stft_result))

    np.testing.assert_allclose(result.frequency_bin_offset, deltas)
    np.testing.assert_allclose(result.refined_frequency_hz, 20.0 + 10.0 * deltas)
    assert np.all(np.mod(result.refined_frequency_hz, 10.0) != 0.0)


def test_baseline_values_axes_flags_and_metadata_are_preserved_exactly() -> None:
    source_path = Path("relative") / "signal.csv"
    stft_result = _stft(_log_parabola_magnitude(0.2), source_path=source_path)
    ridge_result = _ridge(stft_result)

    result = refine_peak_ridge_subbin(stft_result, ridge_result)

    np.testing.assert_array_equal(result.time_s, ridge_result.time_s)
    np.testing.assert_array_equal(
        result.discrete_frequency_hz,
        ridge_result.frequency_hz,
    )
    np.testing.assert_array_equal(result.peak_magnitude, ridge_result.peak_magnitude)
    assert result.quality_flags == ridge_result.quality_flags
    assert result.minimum_frequency_hz == ridge_result.minimum_frequency_hz
    assert result.maximum_frequency_hz == ridge_result.maximum_frequency_hz
    assert result.source_path == source_path
    assert result.source_path is not None and not result.source_path.is_absolute()
    assert result.refinement_method == RefinedRidgeResult.REFINEMENT_METHOD


def test_pre_event_and_outside_window_statuses_propagate_with_masked_values() -> None:
    local = np.column_stack([_log_parabola_magnitude(0.2)] * 3)
    stft_result = _stft(local)
    ridge_result = _ridge(
        stft_result,
        event_start_time_s=1.0,
        analysis_end_time_s=1.0,
    )

    result = refine_peak_ridge_subbin(stft_result, ridge_result)

    assert result.refinement_statuses == (
        RidgeRefinementStatus.PRE_EVENT,
        RidgeRefinementStatus.REFINED,
        RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW,
    )
    np.testing.assert_array_equal(result.discrete_frequency_bin_index, [-1, 2, -1])
    assert np.isnan(result.refined_frequency_hz[[0, 2]]).all()
    assert np.isnan(result.frequency_bin_offset[[0, 2]]).all()


def test_stft_or_search_band_boundary_peak_is_not_refined() -> None:
    cases: list[tuple[STFTResult, float, float]] = []
    for edge_index in (0, FREQUENCY_AXIS.size - 1):
        stft_result = _stft(_log_parabola_magnitude(0.0))
        spectrum = stft_result.spectrum.copy()
        spectrum[edge_index, 0] = 100.0
        object.__setattr__(stft_result, "spectrum", spectrum)
        cases.append((stft_result, 0.0, 40.0))
    cases.extend(
        [
            (_stft(_log_parabola_magnitude(-0.2)), 20.0, 30.0),
            (_stft(_log_parabola_magnitude(0.2)), 10.0, 20.0),
        ]
    )

    for stft_result, minimum, maximum in cases:
        ridge_result = _ridge(
            stft_result,
            minimum_frequency_hz=minimum,
            maximum_frequency_hz=maximum,
        )
        result = refine_peak_ridge_subbin(stft_result, ridge_result)

        assert result.refinement_statuses == (RidgeRefinementStatus.BOUNDARY_PEAK,)
        assert np.isnan(result.refined_frequency_hz[0])
        assert np.isnan(result.frequency_bin_offset[0])
        assert np.isfinite(result.discrete_frequency_hz[0])


def test_nonpositive_flat_or_upward_local_peak_is_invalid() -> None:
    cases = [
        np.array([0.0, 2.0, 1.0]),
        np.array([1.0, 2.0, 0.0]),
        np.array([1.0, 1.0, 1.0]),
        np.array([2.0, 1.0, 2.0]),
    ]
    for local_magnitudes in cases:
        stft_result = _stft(local_magnitudes)
        ridge_result = _manual_center_ridge(stft_result)

        result = refine_peak_ridge_subbin(stft_result, ridge_result)

        assert result.refinement_statuses == (
            RidgeRefinementStatus.INVALID_LOCAL_PEAK,
        )
        assert result.discrete_frequency_bin_index[0] == 2
        assert np.isnan(result.refined_frequency_hz[0])
        assert np.isnan(result.frequency_bin_offset[0])


def test_nonfinite_local_magnitude_is_invalid() -> None:
    for invalid_value in (np.nan, np.inf, -np.inf):
        stft_result = _stft(_log_parabola_magnitude(0.0))
        corrupted_spectrum = stft_result.spectrum.copy()
        corrupted_spectrum[1, 0] = invalid_value
        object.__setattr__(stft_result, "spectrum", corrupted_spectrum)

        result = refine_peak_ridge_subbin(
            stft_result,
            _manual_center_ridge(stft_result),
        )

        assert result.refinement_statuses == (
            RidgeRefinementStatus.INVALID_LOCAL_PEAK,
        )
        assert np.isnan(result.refined_frequency_hz[0])


def test_offset_outside_half_bin_is_rejected_without_clipping() -> None:
    local_magnitudes = np.exp(np.array([0.0, 1.0, 1.5]))
    stft_result = _stft(local_magnitudes)

    result = refine_peak_ridge_subbin(stft_result, _manual_center_ridge(stft_result))

    assert result.refinement_statuses == (RidgeRefinementStatus.OFFSET_OUT_OF_RANGE,)
    assert np.isnan(result.frequency_bin_offset[0])
    assert np.isnan(result.refined_frequency_hz[0])


def test_mismatched_time_axis_source_path_and_types_are_rejected() -> None:
    first = _stft(_log_parabola_magnitude(0.0), source_path=Path("first.csv"))
    different_time = _stft(
        _log_parabola_magnitude(0.0),
        source_path=Path("first.csv"),
        time_s=np.array([1.0]),
    )
    different_source = _stft(
        _log_parabola_magnitude(0.0),
        source_path=Path("second.csv"),
    )
    ridge_result = _ridge(first)

    with pytest.raises(RidgeConfigurationError, match="time_s axes"):
        refine_peak_ridge_subbin(different_time, ridge_result)
    with pytest.raises(RidgeConfigurationError, match="source_path"):
        refine_peak_ridge_subbin(different_source, ridge_result)
    with pytest.raises(RidgeConfigurationError, match="STFTResult instance"):
        refine_peak_ridge_subbin(object(), ridge_result)  # type: ignore[arg-type]
    with pytest.raises(RidgeConfigurationError, match="RidgeResult instance"):
        refine_peak_ridge_subbin(first, object())  # type: ignore[arg-type]


def test_discrete_frequency_not_on_stft_axis_is_rejected() -> None:
    stft_result = _stft(_log_parabola_magnitude(0.0))
    ridge_result = _manual_center_ridge(stft_result)
    object.__setattr__(ridge_result, "frequency_hz", np.array([20.1]))

    with pytest.raises(RidgeConfigurationError, match="exactly match an STFT bin"):
        refine_peak_ridge_subbin(stft_result, ridge_result)


def test_refinement_does_not_modify_either_input() -> None:
    stft_result = _stft(_log_parabola_magnitude(0.25))
    ridge_result = _ridge(stft_result)
    originals = (
        stft_result.time_s.copy(),
        stft_result.frequency_hz.copy(),
        stft_result.spectrum.copy(),
        ridge_result.time_s.copy(),
        ridge_result.frequency_hz.copy(),
        ridge_result.peak_magnitude.copy(),
    )

    refine_peak_ridge_subbin(stft_result, ridge_result)

    for actual, expected in zip(
        (
            stft_result.time_s,
            stft_result.frequency_hz,
            stft_result.spectrum,
            ridge_result.time_s,
            ridge_result.frequency_hz,
            ridge_result.peak_magnitude,
        ),
        originals,
    ):
        np.testing.assert_array_equal(actual, expected)


def test_all_result_array_base_chains_are_bytes_backed_and_immutable() -> None:
    stft_result = _stft(_log_parabola_magnitude(0.25))
    result = refine_peak_ridge_subbin(stft_result, _ridge(stft_result))

    for array in (
        result.time_s,
        result.discrete_frequency_hz,
        result.refined_frequency_hz,
        result.discrete_frequency_bin_index,
        result.frequency_bin_offset,
        result.peak_magnitude,
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


def test_constructor_detaches_external_float_and_integer_arrays() -> None:
    time_s = np.array([0.0])
    discrete = np.array([20.0])
    refined = np.array([22.5])
    bins = np.array([2], dtype=np.int64)
    offsets = np.array([0.25])
    magnitudes = np.array([2.0])
    result = RefinedRidgeResult(
        time_s=time_s,
        discrete_frequency_hz=discrete,
        refined_frequency_hz=refined,
        discrete_frequency_bin_index=bins,
        frequency_bin_offset=offsets,
        peak_magnitude=magnitudes,
        quality_flags=(RidgeQualityFlag.CANDIDATE,),
        refinement_statuses=(RidgeRefinementStatus.REFINED,),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        event_start_time_s=None,
        analysis_end_time_s=None,
        refinement_method=RefinedRidgeResult.REFINEMENT_METHOD,
        source_path=None,
    )

    for array in (time_s, discrete, refined, bins, offsets, magnitudes):
        array[:] = 0

    np.testing.assert_array_equal(result.time_s, [0.0])
    np.testing.assert_array_equal(result.discrete_frequency_hz, [20.0])
    np.testing.assert_array_equal(result.refined_frequency_hz, [22.5])
    np.testing.assert_array_equal(result.discrete_frequency_bin_index, [2])
    np.testing.assert_array_equal(result.frequency_bin_offset, [0.25])
    np.testing.assert_array_equal(result.peak_magnitude, [2.0])


def test_public_imports_and_identity_equality_are_preserved() -> None:
    stft_result = _stft(_log_parabola_magnitude(0.0))
    first = refine_peak_ridge_subbin(stft_result, _ridge(stft_result))
    second = refine_peak_ridge_subbin(stft_result, _ridge(stft_result))

    assert first == first
    assert first != second
    assert RefinedRidgeResult.__module__ == "dps_studio.core.ridge.models"
    assert RidgeRefinementStatus.__module__ == "dps_studio.core.ridge.models"
    assert refine_peak_ridge_subbin.__module__ == "dps_studio.core.ridge.refinement"
