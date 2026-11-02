from __future__ import annotations

import numpy as np
import pytest

from dps_studio.core.physics.acceleration import differentiate_velocity


@pytest.mark.parametrize("times", [[0., 1., 2., 3.], [0., .1, .4, 1., 2.]])
@pytest.mark.parametrize("slope", [0., 3., -7.])
def test_constant_and_linear_on_actual_time_coordinates(times: list[float], slope: float) -> None:
    time = np.asarray(times)
    result = differentiate_velocity(time, 12 + slope * time)
    np.testing.assert_allclose(result.acceleration_m_s2, slope, atol=1e-12)


def test_quadratic_nonuniform_interior_and_first_order_edges() -> None:
    time = np.array([0., .3, 1.4, 3.])
    result = differentiate_velocity(time, time**2)
    np.testing.assert_allclose(result.acceleration_m_s2, [.3, .6, 2.8, 4.4])
    assert result.numerical_flags == (
        "one_sided_secant", "central_nonuniform", "central_nonuniform", "one_sided_secant",
    )


def test_si_microsecond_axis_and_m_per_second_velocity() -> None:
    time_s = np.array([0., 1., 2.]) * 1e-6
    result = differentiate_velocity(time_s, [0., 1000., 2000.])
    np.testing.assert_allclose(result.acceleration_m_s2, 1e9)


@pytest.mark.parametrize("time,velocity,expected", [
    ([], [], []), ([1.], [5.], [np.nan]), ([1., 3.], [5., 9.], [2., 2.]),
    ([0., 1., 2.], [0., 1., 4.], [1., 2., 3.]),
])
def test_short_segments(time: list[float], velocity: list[float], expected: list[float]) -> None:
    np.testing.assert_allclose(differentiate_velocity(time, velocity).acceleration_m_s2, expected)


def test_nan_infinity_and_known_mask_do_not_bridge_or_modify_inputs() -> None:
    time = np.arange(10, dtype=float)
    velocity = np.array([0., 2., np.nan, 100., 104., np.inf, 1., 10., 20., 24.])
    before = velocity.copy()
    mask = np.ones(10, dtype=bool)
    mask[7] = False
    result = differentiate_velocity(time, velocity, valid_mask=mask)
    np.testing.assert_allclose(result.acceleration_m_s2, [2., 2., np.nan, 4., 4., np.nan,
                                                        np.nan, np.nan, 4., 4.])
    np.testing.assert_array_equal(velocity, before)
    np.testing.assert_array_equal(time, np.arange(10))
    assert not result.acceleration_m_s2.flags.writeable


def test_explicit_break_keeps_both_finite_endpoints_separate() -> None:
    result = differentiate_velocity([0., 1., 2., 3.], [0., 1., 100., 103.],
                                    break_before=[False, False, True, False])
    np.testing.assert_array_equal(result.acceleration_m_s2, [1., 1., 3., 3.])


@pytest.mark.parametrize("time,velocity", [
    ([0., 0.], [1., 2.]), ([2., 1.], [1., 2.]), ([0., np.nan], [1., 2.]),
    ([0., np.inf], [1., 2.]), ([0., 1.], [1.]), ([[0., 1.]], [[1., 2.]]),
    ([0., 1.], [[1., 2.]]),
])
def test_invalid_axes_are_rejected(time: object, velocity: object) -> None:
    with pytest.raises(ValueError):
        differentiate_velocity(time, velocity)


@pytest.mark.parametrize("mask", [[True], [1, 0], [[True, False]]])
def test_invalid_mask_rejected(mask: object) -> None:
    with pytest.raises(ValueError):
        differentiate_velocity([0., 1.], [1., 2.], valid_mask=mask)
