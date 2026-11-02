from __future__ import annotations

import numpy as np
import pytest

from dps_studio.core.physics.acceleration import local_linear_acceleration


@pytest.mark.parametrize("slope", [0., 3e9, -7e8])
def test_irregular_si_coordinates_and_truncated_edges(slope: float) -> None:
    time = 500e-6 + np.array([0., 1., 2.2, 3., 5., 6., 7.]) * 1e-9
    velocity = 42 + slope * (time - time[0])
    original = velocity.copy()
    result = local_linear_acceleration(time, velocity, window_s=8e-9)
    np.testing.assert_allclose(result.acceleration_m_s2, slope, rtol=1e-10, atol=1e-5)
    assert result.numerical_flags[0] == "local_linear_truncated"
    np.testing.assert_array_equal(velocity, original)
    assert not result.acceleration_m_s2.flags.writeable


def test_gaps_and_explicit_breaks_never_mix_slopes() -> None:
    time = np.arange(15, dtype=float)
    velocity = np.r_[np.arange(5.), np.nan, 100 + 2*np.arange(4.), 500 - np.arange(5.)]
    breaks = np.zeros(15, dtype=bool)
    breaks[10] = True
    result = local_linear_acceleration(time, velocity, window_s=100, break_before=breaks)
    np.testing.assert_allclose(result.acceleration_m_s2, np.r_[np.ones(5), np.nan,
                                                            np.full(4, 2.), -np.ones(5)])
    assert result.numerical_flags[5] == "invalid_or_masked"


@pytest.mark.parametrize("window", [0, -1, np.nan, np.inf])
def test_invalid_window(window: float) -> None:
    with pytest.raises(ValueError):
        local_linear_acceleration([0, 1, 2], [1, 2, 3], window_s=window)


def test_short_runs_and_tiny_windows_remain_nan() -> None:
    for time in ([], [0.], [0., 1.], [0., 1., 2.]):
        result = local_linear_acceleration(time, time, window_s=.1)
        assert np.all(np.isnan(result.acceleration_m_s2))


def test_quadratic_symmetric_window_and_noise_reduction() -> None:
    time = np.linspace(0, 1, 501)
    result = local_linear_acceleration(time, time**2, window_s=.081)
    np.testing.assert_allclose(result.acceleration_m_s2[30:-30], 2*time[30:-30], atol=1e-12)
    rng = np.random.default_rng(34)
    noisy = 3*time + rng.normal(0, .01, time.size)
    fitted = local_linear_acceleration(time, noisy, window_s=.081).acceleration_m_s2
    assert np.std(fitted[30:-30]-3) < np.std(np.gradient(noisy, time)[30:-30]-3) / 5


def test_grid_aligned_window_is_symmetric_under_absolute_time_shift() -> None:
    time = np.linspace(0, 2e-6, 1001)
    velocity = 100 + 50*np.tanh((time-1e-6)/20e-9)
    for shift in (0, 550e-6):
        result = local_linear_acceleration(time+shift, velocity, window_s=100e-9)
        peak = int(np.argmax(result.acceleration_m_s2))
        assert peak == 500
        np.testing.assert_allclose(result.acceleration_m_s2[400:601],
                                   result.acceleration_m_s2[600:399:-1], atol=.1, rtol=1e-8)
