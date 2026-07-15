"""Tests for pure development-only window-length diagnostic helpers."""

import numpy as np
import pytest

from scripts.compare_real_ridge_refinement import (
    _paired_channel_statistics,
    _relative_stft_magnitude_db,
    _series_detail_statistics,
)


def test_series_detail_statistics_do_not_bridge_invalid_frames() -> None:
    time_relative_s = np.arange(7, dtype=np.float64)
    velocity_m_s = np.array(
        [1.0, 3.0, 6.0, np.nan, 10.0, 14.0, 19.0],
        dtype=np.float64,
    )
    valid = np.ones(7, dtype=np.bool_)

    statistics = _series_detail_statistics(
        time_relative_s,
        velocity_m_s,
        valid,
        start_relative_s=0.0,
        end_relative_s=6.0,
    )

    assert statistics.valid_frame_count == 6
    assert statistics.first_difference_absolute_median_m_s == pytest.approx(3.5)
    assert statistics.first_difference_absolute_p95_m_s == pytest.approx(4.85)
    assert statistics.first_difference_standard_deviation_m_s == pytest.approx(
        np.std([2.0, 3.0, 4.0, 5.0])
    )
    assert statistics.second_difference_rms_m_s == pytest.approx(1.0)
    assert statistics.velocity_min_m_s == pytest.approx(1.0)
    assert statistics.velocity_max_m_s == pytest.approx(19.0)
    assert statistics.velocity_span_m_s == pytest.approx(18.0)


def test_paired_channel_statistics_use_only_same_valid_frames() -> None:
    time_relative_s = np.arange(5, dtype=np.float64)
    first_velocity_m_s = np.array(
        [1.0, 2.0, np.nan, 4.0, 5.0],
        dtype=np.float64,
    )
    second_velocity_m_s = np.array(
        [1.5, 1.0, np.nan, 3.0, 7.0],
        dtype=np.float64,
    )
    refined = np.ones(5, dtype=np.bool_)

    statistics = _paired_channel_statistics(
        time_relative_s,
        first_velocity_m_s,
        refined,
        second_velocity_m_s,
        refined,
        start_relative_s=0.0,
        end_relative_s=4.0,
    )

    assert statistics.paired_frame_count == 4
    assert statistics.absolute_difference_median_m_s == pytest.approx(1.0)
    assert statistics.absolute_difference_p95_m_s == pytest.approx(1.85)
    assert statistics.absolute_difference_maximum_m_s == pytest.approx(2.0)
    assert statistics.pearson_correlation == pytest.approx(
        np.corrcoef([1.0, 2.0, 4.0, 5.0], [1.5, 1.0, 3.0, 7.0])[0, 1]
    )


def test_relative_stft_magnitude_db_is_plot_only_and_floored() -> None:
    magnitude = np.array([[1.0, 0.1, 0.0]], dtype=np.float64)
    original = magnitude.copy()

    relative_db = _relative_stft_magnitude_db(magnitude)

    np.testing.assert_array_equal(magnitude, original)
    np.testing.assert_allclose(relative_db, [[0.0, -20.0, -60.0]])
