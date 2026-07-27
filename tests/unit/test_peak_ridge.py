from pathlib import Path

import numpy as np
import pytest

import dps_studio.core.ridge.peak as peak_module
from dps_studio.core.models import DPSStudioError
from dps_studio.core.ridge import (
    RidgeConfigurationError,
    RidgeError,
    RidgeExtractionError,
    RidgeQualityFlag,
    RidgeResult,
    extract_peak_ridge,
)
from dps_studio.core.time_frequency import STFTResult


def _stft_result(
    spectrum: np.ndarray | None = None,
    *,
    source_path: Path | None = None,
) -> STFTResult:
    if spectrum is None:
        spectrum = np.array(
            [
                [100.0, 100.0, 100.0, 100.0],
                [1.0, 2.0, 9.0, 4.0],
                [5.0, 8.0, 3.0, 1.0],
                [2.0, 4.0, 7.0, 6.0],
                [200.0, 200.0, 200.0, 200.0],
            ],
            dtype=np.complex128,
        )
    return STFTResult(
        time_s=np.array([0.0, 1.0, 2.0, 3.0]),
        frequency_hz=np.array([0.0, 10.0, 20.0, 30.0, 40.0]),
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


def _extract_default(stft_result: STFTResult | None = None) -> RidgeResult:
    return extract_peak_ridge(
        _stft_result() if stft_result is None else stft_result,
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
    )


def test_known_per_frame_peaks_and_magnitudes_are_extracted() -> None:
    result = _extract_default()

    np.testing.assert_array_equal(result.time_s, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_array_equal(result.frequency_hz, [20.0, 20.0, 10.0, 30.0])
    np.testing.assert_array_equal(result.peak_magnitude, [5.0, 8.0, 9.0, 6.0])
    assert result.quality_flags == (RidgeQualityFlag.CANDIDATE,) * 4


def test_search_is_limited_to_closed_frequency_band() -> None:
    result = extract_peak_ridge(
        _stft_result(),
        minimum_frequency_hz=20.0,
        maximum_frequency_hz=30.0,
    )

    np.testing.assert_array_equal(result.frequency_hz, [20.0, 20.0, 30.0, 30.0])
    assert np.all(result.frequency_hz >= 20.0)
    assert np.all(result.frequency_hz <= 30.0)


def test_stronger_peaks_outside_search_band_are_not_selected() -> None:
    result = _extract_default()

    assert np.all(result.frequency_hz != 0.0)
    assert np.all(result.frequency_hz != 40.0)
    assert np.max(result.peak_magnitude) < 100.0


def test_equal_maxima_choose_first_lowest_frequency_bin() -> None:
    spectrum = np.zeros((5, 4), dtype=np.complex128)
    spectrum[1, :] = 7.0
    spectrum[2, :] = 7.0

    result = _extract_default(_stft_result(spectrum))

    np.testing.assert_array_equal(result.frequency_hz, [10.0, 10.0, 10.0, 10.0])


def test_frames_before_explicit_analysis_start_are_nan_and_pre_event() -> None:
    result = extract_peak_ridge(
        _stft_result(),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        analysis_start_time_s=2.0,
    )

    assert np.all(np.isnan(result.frequency_hz[:2]))
    assert np.all(np.isnan(result.peak_magnitude[:2]))
    assert result.quality_flags[:2] == (RidgeQualityFlag.PRE_EVENT,) * 2
    assert result.quality_flags[2:] == (RidgeQualityFlag.CANDIDATE,) * 2


def test_frames_after_analysis_end_are_nan_and_outside_window() -> None:
    result = extract_peak_ridge(
        _stft_result(),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        analysis_end_time_s=1.0,
    )

    assert np.all(np.isnan(result.frequency_hz[2:]))
    assert np.all(np.isnan(result.peak_magnitude[2:]))
    assert result.quality_flags[:2] == (RidgeQualityFlag.CANDIDATE,) * 2
    assert result.quality_flags[2:] == (
        RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW,
    ) * 2


def test_frames_equal_to_both_time_boundaries_are_candidates() -> None:
    result = extract_peak_ridge(
        _stft_result(),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        analysis_start_time_s=1.0,
        analysis_end_time_s=2.0,
    )

    assert result.quality_flags == (
        RidgeQualityFlag.PRE_EVENT,
        RidgeQualityFlag.CANDIDATE,
        RidgeQualityFlag.CANDIDATE,
        RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW,
    )
    np.testing.assert_array_equal(result.frequency_hz[1:3], [20.0, 10.0])


def test_omitted_time_boundaries_keep_full_frame_count_as_candidates() -> None:
    stft_result = _stft_result()

    result = _extract_default(stft_result)

    assert len(result.time_s) == stft_result.time_s.size
    assert len(result.frequency_hz) == stft_result.time_s.size
    assert len(result.peak_magnitude) == stft_result.time_s.size
    assert len(result.quality_flags) == stft_result.time_s.size
    assert result.quality_flags == (RidgeQualityFlag.CANDIDATE,) * 4


def test_manual_event_reference_does_not_gate_or_change_ridge_arrays() -> None:
    first = extract_peak_ridge(
        _stft_result(),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        event_start_time_s=0.5,
    )
    second = extract_peak_ridge(
        _stft_result(),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        event_start_time_s=2.5,
    )
    np.testing.assert_array_equal(first.frequency_hz, second.frequency_hz)
    np.testing.assert_array_equal(first.peak_magnitude, second.peak_magnitude)
    assert first.quality_flags == second.quality_flags
    assert first.quality_flags == (RidgeQualityFlag.CANDIDATE,) * 4


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        (True, 30.0),
        (10.0, False),
        (np.nan, 30.0),
        (10.0, np.inf),
        (-1.0, 30.0),
        (20.0, 20.0),
        (30.0, 20.0),
    ],
)
def test_invalid_frequency_configuration_is_rejected(
    minimum: float,
    maximum: float,
) -> None:
    with pytest.raises(RidgeConfigurationError):
        extract_peak_ridge(
            _stft_result(),
            minimum_frequency_hz=minimum,
            maximum_frequency_hz=maximum,
        )


def test_maximum_frequency_above_stft_axis_is_rejected() -> None:
    with pytest.raises(RidgeConfigurationError, match="exceeds the STFT maximum"):
        extract_peak_ridge(
            _stft_result(),
            minimum_frequency_hz=10.0,
            maximum_frequency_hz=40.1,
        )


def test_frequency_range_without_discrete_bin_reports_request_and_grid() -> None:
    with pytest.raises(RidgeConfigurationError) as error_info:
        extract_peak_ridge(
            _stft_result(),
            minimum_frequency_hz=11.0,
            maximum_frequency_hz=19.0,
        )

    message = str(error_info.value)
    assert "[11.0, 19.0]" in message
    assert "[0.0, 40.0]" in message
    assert "5 bins" in message


@pytest.mark.parametrize(
    ("event_start", "analysis_end"),
    [
        (np.nan, None),
        (np.inf, None),
        (True, None),
        (None, np.nan),
        (None, -np.inf),
        (None, False),
    ],
)
def test_nonfinite_or_bool_time_boundaries_are_rejected(
    event_start: float | None,
    analysis_end: float | None,
) -> None:
    with pytest.raises(RidgeConfigurationError):
        extract_peak_ridge(
            _stft_result(),
            minimum_frequency_hz=10.0,
            maximum_frequency_hz=30.0,
            event_start_time_s=event_start,
            analysis_end_time_s=analysis_end,
        )


def test_analysis_start_after_analysis_end_is_rejected() -> None:
    with pytest.raises(RidgeConfigurationError, match="less than or equal"):
        extract_peak_ridge(
            _stft_result(),
            minimum_frequency_hz=10.0,
            maximum_frequency_hz=30.0,
            analysis_start_time_s=2.0,
            analysis_end_time_s=1.0,
        )


def test_extraction_does_not_modify_stft_result() -> None:
    stft_result = _stft_result()
    original_time = stft_result.time_s.copy()
    original_frequency = stft_result.frequency_hz.copy()
    original_spectrum = stft_result.spectrum.copy()

    _extract_default(stft_result)

    np.testing.assert_array_equal(stft_result.time_s, original_time)
    np.testing.assert_array_equal(stft_result.frequency_hz, original_frequency)
    np.testing.assert_array_equal(stft_result.spectrum, original_spectrum)


def test_result_arrays_are_detached_and_entire_base_chains_are_immutable() -> None:
    first = _extract_default()
    second = _extract_default()

    for array in [first.time_s, first.frequency_hz, first.peak_magnitude]:
        current: object = array
        visited_ids: set[int] = set()
        while isinstance(current, np.ndarray):
            assert id(current) not in visited_ids
            visited_ids.add(id(current))
            assert current.flags.writeable is False
            with pytest.raises(ValueError, match="WRITEABLE"):
                current.setflags(write=True)
            with pytest.raises(ValueError, match="read-only"):
                current.flat[0] = -999.0
            current = current.base
        assert isinstance(current, bytes)
        assert memoryview(current).readonly is True

    assert not np.shares_memory(first.time_s, second.time_s)
    assert not np.shares_memory(first.frequency_hz, second.frequency_hz)
    assert not np.shares_memory(first.peak_magnitude, second.peak_magnitude)


def test_relative_source_path_public_imports_and_identity_equality_are_preserved() -> None:
    relative_path = Path("relative") / "signal.csv"

    first = _extract_default(_stft_result(source_path=relative_path))
    second = _extract_default(_stft_result(source_path=relative_path))

    assert first.source_path == relative_path
    assert first.source_path is not None
    assert first.source_path.is_absolute() is False
    assert first == first
    assert first != second
    assert RidgeResult.__module__ == "dps_studio.core.ridge.models"
    assert extract_peak_ridge.__module__ == "dps_studio.core.ridge.peak"
    assert issubclass(RidgeError, DPSStudioError)
    assert issubclass(RidgeConfigurationError, RidgeError)
    assert issubclass(RidgeExtractionError, RidgeError)


def test_unexpected_calculation_error_is_wrapped_without_exposing_spectrum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_abs(value: object) -> None:
        raise RuntimeError("synthetic magnitude failure")

    monkeypatch.setattr(peak_module.np, "abs", fail_abs)

    with pytest.raises(RidgeExtractionError) as error_info:
        _extract_default()

    assert isinstance(error_info.value.__cause__, RuntimeError)
    assert "[" not in str(error_info.value)
