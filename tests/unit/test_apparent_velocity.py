from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.models import DPSStudioError
from dps_studio.core.physics import (
    ApparentVelocityResult,
    VelocityConfigurationError,
    VelocityConversionError,
    VelocityError,
    convert_ridge_to_apparent_velocity,
)
from dps_studio.core.ridge import RidgeQualityFlag, RidgeResult


def _candidate_ridge(
    frequency_hz: np.ndarray | None = None,
    *,
    source_path: Path | None = None,
) -> RidgeResult:
    if frequency_hz is None:
        frequency_hz = np.array([2.0e9], dtype=np.float64)
    frequency_hz = np.asarray(frequency_hz, dtype=np.float64)
    maximum_frequency_hz = max(1.0, float(np.max(frequency_hz)))
    return RidgeResult(
        time_s=np.arange(frequency_hz.size, dtype=np.float64),
        frequency_hz=frequency_hz,
        peak_magnitude=np.ones(frequency_hz.size, dtype=np.float64),
        quality_flags=(RidgeQualityFlag.CANDIDATE,) * frequency_hz.size,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=maximum_frequency_hz,
        event_start_time_s=None,
        analysis_end_time_s=None,
        source_path=source_path,
    )


def _windowed_ridge(*, source_path: Path | None = None) -> RidgeResult:
    return RidgeResult(
        time_s=np.array([0.0, 1.0, 2.0]),
        frequency_hz=np.array([np.nan, 2.0e9, np.nan]),
        peak_magnitude=np.array([np.nan, 4.0, np.nan]),
        quality_flags=(
            RidgeQualityFlag.PRE_EVENT,
            RidgeQualityFlag.CANDIDATE,
            RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW,
        ),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=2.0e9,
        event_start_time_s=1.0,
        analysis_end_time_s=1.0,
        source_path=source_path,
    )


def test_known_frequency_uses_normal_incidence_reflection_formula() -> None:
    result = convert_ridge_to_apparent_velocity(
        _candidate_ridge(),
        vacuum_wavelength_m=1.0e-6,
    )

    assert result.apparent_velocity_m_s[0] == pytest.approx(1000.0)
    assert result.vacuum_wavelength_m == pytest.approx(1.0e-6)
    assert result.conversion_model == "normal-incidence reflection PDV: v=lambda*f/2"
    assert result.is_signed is False


def test_multiple_frequencies_convert_elementwise_and_remain_nonnegative() -> None:
    result = convert_ridge_to_apparent_velocity(
        _candidate_ridge(np.array([0.0, 1.0e9, 2.0e9])),
        vacuum_wavelength_m=1.0e-6,
    )

    np.testing.assert_allclose(result.apparent_velocity_m_s, [0.0, 500.0, 1000.0])
    assert result.apparent_velocity_m_s.dtype == np.float64
    assert result.apparent_velocity_m_s.ndim == 1
    assert np.all(result.apparent_velocity_m_s >= 0.0)


def test_nan_frames_axes_flags_and_full_frame_count_are_preserved() -> None:
    ridge_result = _windowed_ridge()

    result = convert_ridge_to_apparent_velocity(
        ridge_result,
        vacuum_wavelength_m=1.0e-6,
    )

    np.testing.assert_array_equal(result.time_s, ridge_result.time_s)
    np.testing.assert_array_equal(
        result.beat_frequency_hz,
        ridge_result.frequency_hz,
    )
    np.testing.assert_array_equal(
        np.isnan(result.apparent_velocity_m_s),
        np.isnan(ridge_result.frequency_hz),
    )
    assert result.apparent_velocity_m_s[1] == pytest.approx(1000.0)
    assert len(result.time_s) == len(ridge_result.time_s) == 3
    assert result.quality_flags == ridge_result.quality_flags


@pytest.mark.parametrize(
    "vacuum_wavelength_m",
    [True, np.bool_(True), 0.0, -1.0, np.nan, np.inf, -np.inf, "1550 nm"],
)
def test_invalid_vacuum_wavelength_is_rejected(vacuum_wavelength_m: object) -> None:
    with pytest.raises(VelocityConfigurationError):
        convert_ridge_to_apparent_velocity(
            _candidate_ridge(),
            vacuum_wavelength_m=vacuum_wavelength_m,  # type: ignore[arg-type]
        )


def test_non_ridge_input_is_rejected() -> None:
    with pytest.raises(VelocityConfigurationError, match="must be a RidgeResult"):
        convert_ridge_to_apparent_velocity(  # type: ignore[arg-type]
            object(),
            vacuum_wavelength_m=1.0e-6,
        )


def test_negative_finite_frequency_is_rejected_even_if_ridge_is_corrupted() -> None:
    ridge_result = _candidate_ridge(np.array([1.0]))
    object.__setattr__(ridge_result, "frequency_hz", np.array([-1.0]))

    with pytest.raises(VelocityConfigurationError, match="non-negative"):
        convert_ridge_to_apparent_velocity(
            ridge_result,
            vacuum_wavelength_m=1.0e-6,
        )


def test_true_float64_overflow_raises_velocity_conversion_error() -> None:
    maximum_float = np.finfo(np.float64).max
    ridge_result = _candidate_ridge(np.array([maximum_float]))

    with pytest.raises(VelocityConversionError) as error_info:
        convert_ridge_to_apparent_velocity(
            ridge_result,
            vacuum_wavelength_m=maximum_float,
        )

    assert isinstance(error_info.value.__cause__, FloatingPointError)
    assert "[" not in str(error_info.value)


def test_large_but_finite_velocity_is_not_misclassified_as_overflow() -> None:
    maximum_float = np.finfo(np.float64).max

    result = convert_ridge_to_apparent_velocity(
        _candidate_ridge(np.array([maximum_float])),
        vacuum_wavelength_m=2.0,
    )

    assert result.apparent_velocity_m_s[0] == maximum_float
    assert np.isfinite(result.apparent_velocity_m_s[0])


def test_subnormal_wavelength_does_not_cause_spurious_zero() -> None:
    smallest_positive_float = np.nextafter(np.float64(0.0), np.float64(1.0))
    frequency_hz = np.float64(1.0e308)

    result = convert_ridge_to_apparent_velocity(
        _candidate_ridge(np.array([frequency_hz])),
        vacuum_wavelength_m=smallest_positive_float,
    )

    expected = (frequency_hz / np.float64(2.0)) * smallest_positive_float
    assert result.apparent_velocity_m_s[0] == expected
    assert result.apparent_velocity_m_s[0] > 0.0


def test_conversion_does_not_modify_ridge_result() -> None:
    ridge_result = _windowed_ridge(source_path=Path("relative") / "signal.csv")
    original_time = ridge_result.time_s.copy()
    original_frequency = ridge_result.frequency_hz.copy()
    original_magnitude = ridge_result.peak_magnitude.copy()
    original_flags = ridge_result.quality_flags

    convert_ridge_to_apparent_velocity(
        ridge_result,
        vacuum_wavelength_m=1.0e-6,
    )

    np.testing.assert_array_equal(ridge_result.time_s, original_time)
    np.testing.assert_array_equal(ridge_result.frequency_hz, original_frequency)
    np.testing.assert_array_equal(ridge_result.peak_magnitude, original_magnitude)
    assert ridge_result.quality_flags == original_flags
    assert ridge_result.event_start_time_s == 1.0
    assert ridge_result.analysis_end_time_s == 1.0
    assert ridge_result.source_path == Path("relative") / "signal.csv"


def test_result_arrays_have_fully_immutable_bytes_backing() -> None:
    result = convert_ridge_to_apparent_velocity(
        _windowed_ridge(),
        vacuum_wavelength_m=1.0e-6,
    )

    for array in [
        result.time_s,
        result.beat_frequency_hz,
        result.apparent_velocity_m_s,
    ]:
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


def test_result_constructor_detaches_external_arrays() -> None:
    time_s = np.array([0.0, 1.0])
    beat_frequency_hz = np.array([0.0, 2.0e6])
    apparent_velocity_m_s = np.array([0.0, 1.0])
    result = ApparentVelocityResult(
        time_s=time_s,
        beat_frequency_hz=beat_frequency_hz,
        apparent_velocity_m_s=apparent_velocity_m_s,
        quality_flags=(RidgeQualityFlag.CANDIDATE,) * 2,
        vacuum_wavelength_m=1.0e-6,
        conversion_model=ApparentVelocityResult.CONVERSION_MODEL,
        is_signed=False,
        source_path=None,
    )

    time_s[:] = 10.0
    beat_frequency_hz[:] = 10.0
    apparent_velocity_m_s[:] = 10.0

    np.testing.assert_array_equal(result.time_s, [0.0, 1.0])
    np.testing.assert_array_equal(result.beat_frequency_hz, [0.0, 2.0e6])
    np.testing.assert_array_equal(result.apparent_velocity_m_s, [0.0, 1.0])


def test_relative_source_path_and_identity_equality_are_preserved() -> None:
    relative_path = Path("relative") / "signal.csv"

    first = convert_ridge_to_apparent_velocity(
        _candidate_ridge(source_path=relative_path),
        vacuum_wavelength_m=1.0e-6,
    )
    second = convert_ridge_to_apparent_velocity(
        _candidate_ridge(source_path=relative_path),
        vacuum_wavelength_m=1.0e-6,
    )

    assert first.source_path == relative_path
    assert first.source_path is not None
    assert first.source_path.is_absolute() is False
    assert first == first
    assert first != second


def test_public_imports_and_exception_hierarchy() -> None:
    assert ApparentVelocityResult.__module__ == "dps_studio.core.physics.models"
    assert (
        convert_ridge_to_apparent_velocity.__module__
        == "dps_studio.core.physics.velocity"
    )
    assert issubclass(VelocityError, DPSStudioError)
    assert issubclass(VelocityConfigurationError, VelocityError)
    assert issubclass(VelocityConversionError, VelocityError)


def test_result_has_only_candidate_apparent_velocity_contract() -> None:
    result = convert_ridge_to_apparent_velocity(
        _candidate_ridge(),
        vacuum_wavelength_m=1.0e-6,
    )

    assert {field.name for field in fields(result)} == {
        "time_s",
        "beat_frequency_hz",
        "apparent_velocity_m_s",
        "quality_flags",
        "vacuum_wavelength_m",
        "conversion_model",
        "is_signed",
        "source_path",
    }
    assert not hasattr(result, "corrected_velocity_m_s")


def test_result_model_rejects_broken_array_invariants() -> None:
    common = {
        "quality_flags": (RidgeQualityFlag.CANDIDATE,),
        "vacuum_wavelength_m": 1.0e-6,
        "conversion_model": ApparentVelocityResult.CONVERSION_MODEL,
        "is_signed": False,
        "source_path": None,
    }

    with pytest.raises(VelocityConfigurationError, match="one-dimensional"):
        ApparentVelocityResult(
            time_s=np.array([[0.0]]),
            beat_frequency_hz=np.array([1.0]),
            apparent_velocity_m_s=np.array([0.5e-6]),
            **common,  # type: ignore[arg-type]
        )
    with pytest.raises(VelocityConfigurationError, match="same length as time_s"):
        ApparentVelocityResult(
            time_s=np.array([0.0, 1.0]),
            beat_frequency_hz=np.array([1.0]),
            apparent_velocity_m_s=np.array([0.5e-6]),
            **common,  # type: ignore[arg-type]
        )
    with pytest.raises(VelocityConfigurationError, match="same length as time_s"):
        ApparentVelocityResult(
            time_s=np.array([0.0, 1.0]),
            beat_frequency_hz=np.array([1.0, 2.0]),
            apparent_velocity_m_s=np.array([0.5e-6, 1.0e-6]),
            quality_flags=(RidgeQualityFlag.CANDIDATE,),
            vacuum_wavelength_m=1.0e-6,
            conversion_model=ApparentVelocityResult.CONVERSION_MODEL,
            is_signed=False,
            source_path=None,
        )
    with pytest.raises(VelocityConfigurationError) as error_info:
        ApparentVelocityResult(
            time_s=np.array([0.0]),
            beat_frequency_hz=np.array([1.0]),
            apparent_velocity_m_s=np.array([0.5e-6]),
            quality_flags=None,  # type: ignore[arg-type]
            vacuum_wavelength_m=1.0e-6,
            conversion_model=ApparentVelocityResult.CONVERSION_MODEL,
            is_signed=False,
            source_path=None,
        )
    assert isinstance(error_info.value.__cause__, TypeError)
    with pytest.raises(VelocityConfigurationError, match="NaN at the same positions"):
        ApparentVelocityResult(
            time_s=np.array([0.0]),
            beat_frequency_hz=np.array([np.nan]),
            apparent_velocity_m_s=np.array([0.0]),
            **common,  # type: ignore[arg-type]
        )
    with pytest.raises(VelocityConfigurationError, match="non-negative"):
        ApparentVelocityResult(
            time_s=np.array([0.0]),
            beat_frequency_hz=np.array([1.0]),
            apparent_velocity_m_s=np.array([-1.0]),
            **common,  # type: ignore[arg-type]
        )
