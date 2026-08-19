from __future__ import annotations

import numpy as np
import pytest

from tools.task020a_background_whitening import (
    BackgroundWhiteningError,
    assess_background_uniformity,
    compute_frequency_background_whitening,
)


def _run(quantity: np.ndarray, *, minimum_frames: int = 3):
    return compute_frequency_background_whitening(
        quantity,
        time_s=np.arange(quantity.shape[1], dtype=np.float64),
        frequency_hz=np.arange(quantity.shape[0], dtype=np.float64) * 1.0e6,
        background_start_s=0.0,
        background_end_s=2.0,
        minimum_background_frames=minimum_frames,
    )


def test_constant_background_is_recovered_and_shapes_are_preserved() -> None:
    quantity = np.full((4, 5), 7.5, dtype=np.float64)

    result = _run(quantity)

    np.testing.assert_array_equal(result.background_frequency_profile, 7.5)
    np.testing.assert_allclose(result.whitened_ratio[:, :3], 1.0, rtol=1.0e-15)
    assert result.raw_spectral_quantity.shape == quantity.shape
    assert result.whitened_ratio.shape == quantity.shape
    assert result.background_contrast_db.shape == quantity.shape


def test_frequency_dependent_background_is_flattened() -> None:
    profile = np.array([1.0, 5.0, 25.0, 125.0])
    quantity = np.repeat(profile[:, np.newaxis], 5, axis=1)

    result = _run(quantity)
    metrics = assess_background_uniformity(result)

    np.testing.assert_array_equal(result.background_frequency_profile, profile)
    assert metrics.raw_nonuniformity_db > 15.0
    assert metrics.whitened_nonuniformity_db < 1.0e-12


def test_median_resists_sparse_extreme_outlier() -> None:
    quantity = np.full((3, 5), 2.0)
    quantity[1, 1] = 1.0e9

    result = _run(quantity)

    np.testing.assert_array_equal(result.background_frequency_profile, 2.0)
    np.testing.assert_array_equal(result.background_mad_frequency_profile, 0.0)


def test_inputs_are_not_modified_and_outputs_are_detached_read_only() -> None:
    quantity = np.arange(1.0, 21.0).reshape(4, 5)
    original = quantity.copy()

    result = _run(quantity)

    np.testing.assert_array_equal(quantity, original)
    assert not np.shares_memory(quantity, result.raw_spectral_quantity)
    assert not result.raw_spectral_quantity.flags.writeable
    assert not result.whitened_ratio.flags.writeable


def test_empty_background_interval_fails_explicitly() -> None:
    with pytest.raises(BackgroundWhiteningError, match="contains no STFT frames"):
        compute_frequency_background_whitening(
            np.ones((2, 4)),
            time_s=np.arange(4.0),
            frequency_hz=np.arange(2.0),
            background_start_s=10.0,
            background_end_s=11.0,
        )


def test_insufficient_background_frames_fails_explicitly() -> None:
    with pytest.raises(BackgroundWhiteningError, match="at least 3 are required"):
        compute_frequency_background_whitening(
            np.ones((2, 4)),
            time_s=np.arange(4.0),
            frequency_hz=np.arange(2.0),
            background_start_s=0.0,
            background_end_s=1.0,
            minimum_background_frames=3,
        )


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_nonfinite_input_is_rejected(bad_value: float) -> None:
    quantity = np.ones((2, 4))
    quantity[0, 0] = bad_value

    with pytest.raises(BackgroundWhiteningError, match="only finite"):
        _run(quantity)


def test_nonpositive_background_profile_is_rejected() -> None:
    quantity = np.ones((2, 4))
    quantity[0] = 0.0

    with pytest.raises(BackgroundWhiteningError, match="strictly positive"):
        _run(quantity)


def test_db_formula_and_scale_aware_epsilon_are_numerically_exact() -> None:
    quantity = np.array([[2.0, 2.0, 2.0, 20.0]])

    result = _run(quantity)
    expected_epsilon = np.finfo(np.float64).eps * 2.0
    expected = 10.0 * np.log10((20.0 + expected_epsilon) / (2.0 + expected_epsilon))

    assert result.epsilon == expected_epsilon
    assert result.background_contrast_db[0, 3] == pytest.approx(expected)
    assert result.background_contrast_db[0, 3] == pytest.approx(10.0)


def test_negative_linear_quantity_is_rejected() -> None:
    quantity = np.ones((2, 4))
    quantity[1, 2] = -0.1

    with pytest.raises(BackgroundWhiteningError, match="non-negative"):
        _run(quantity)
