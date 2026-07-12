"""Immutable results for candidate apparent-velocity conversion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.physics.exceptions import VelocityConfigurationError
from dps_studio.core.ridge import RidgeQualityFlag


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True, eq=False)
class ApparentVelocityResult:
    """Unsigned candidate apparent velocity on the complete ridge time axis."""

    CONVERSION_MODEL: ClassVar[str] = "normal-incidence reflection PDV: v=lambda*f/2"

    time_s: FloatArray
    beat_frequency_hz: FloatArray
    apparent_velocity_m_s: FloatArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    vacuum_wavelength_m: float
    conversion_model: str
    is_signed: bool
    source_path: Path | None

    def __post_init__(self) -> None:
        """Validate result invariants and detach arrays into immutable buffers."""
        time_s = _as_float64_array(self.time_s, field_name="time_s")
        beat_frequency_hz = _as_float64_array(
            self.beat_frequency_hz,
            field_name="beat_frequency_hz",
        )
        apparent_velocity_m_s = _as_float64_array(
            self.apparent_velocity_m_s,
            field_name="apparent_velocity_m_s",
        )
        try:
            quality_flags = tuple(self.quality_flags)
        except TypeError as exc:
            raise VelocityConfigurationError(
                "quality_flags must be an iterable of RidgeQualityFlag values."
            ) from exc
        vacuum_wavelength_m = _positive_finite_float(
            self.vacuum_wavelength_m,
            field_name="vacuum_wavelength_m",
        )

        for field_name, array in (
            ("time_s", time_s),
            ("beat_frequency_hz", beat_frequency_hz),
            ("apparent_velocity_m_s", apparent_velocity_m_s),
        ):
            if array.ndim != 1:
                raise VelocityConfigurationError(
                    f"{field_name} must be one-dimensional; got shape {array.shape}."
                )
        if time_s.size == 0:
            raise VelocityConfigurationError("time_s must contain at least one value.")
        if (
            beat_frequency_hz.size != time_s.size
            or apparent_velocity_m_s.size != time_s.size
        ):
            raise VelocityConfigurationError(
                "beat_frequency_hz and apparent_velocity_m_s must have the same "
                "length as time_s."
            )
        if len(quality_flags) != time_s.size:
            raise VelocityConfigurationError(
                "quality_flags must have the same length as time_s."
            )
        if not np.all(np.isfinite(time_s)):
            raise VelocityConfigurationError("time_s must contain only finite values.")
        if time_s.size > 1 and not np.all(np.diff(time_s) > 0.0):
            raise VelocityConfigurationError("time_s must be strictly increasing.")
        if not all(isinstance(flag, RidgeQualityFlag) for flag in quality_flags):
            raise VelocityConfigurationError(
                "quality_flags must contain only RidgeQualityFlag values."
            )

        _validate_nonnegative_or_nan(
            beat_frequency_hz,
            field_name="beat_frequency_hz",
        )
        _validate_nonnegative_or_nan(
            apparent_velocity_m_s,
            field_name="apparent_velocity_m_s",
        )
        if not np.array_equal(
            np.isnan(beat_frequency_hz),
            np.isnan(apparent_velocity_m_s),
        ):
            raise VelocityConfigurationError(
                "beat_frequency_hz and apparent_velocity_m_s must have NaN at "
                "the same positions."
            )
        _validate_quality_semantics(
            beat_frequency_hz=beat_frequency_hz,
            apparent_velocity_m_s=apparent_velocity_m_s,
            quality_flags=quality_flags,
        )

        if self.conversion_model != self.CONVERSION_MODEL:
            raise VelocityConfigurationError(
                f"conversion_model must be {self.CONVERSION_MODEL!r}."
            )
        if self.is_signed is not False:
            raise VelocityConfigurationError(
                "is_signed must be False because a one-sided ridge provides "
                "only unsigned magnitude."
            )
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise VelocityConfigurationError("source_path must be pathlib.Path or None.")

        object.__setattr__(self, "time_s", _store_float64_immutable(time_s))
        object.__setattr__(
            self,
            "beat_frequency_hz",
            _store_float64_immutable(beat_frequency_hz),
        )
        object.__setattr__(
            self,
            "apparent_velocity_m_s",
            _store_float64_immutable(apparent_velocity_m_s),
        )
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "vacuum_wavelength_m", vacuum_wavelength_m)


def _as_float64_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            f"{field_name} could not be converted to a float64 array."
        ) from exc


def _positive_finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise VelocityConfigurationError(
            f"{field_name} must be a finite float greater than zero in SI metres."
        )
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            f"{field_name} must be a finite float greater than zero in SI metres."
        ) from exc
    if not math.isfinite(converted) or converted <= 0.0:
        raise VelocityConfigurationError(
            f"{field_name} must be finite and strictly positive in SI metres."
        )
    return converted


def _validate_nonnegative_or_nan(array: FloatArray, *, field_name: str) -> None:
    invalid_nonfinite = np.flatnonzero(~np.isfinite(array) & ~np.isnan(array))
    if invalid_nonfinite.size:
        index = int(invalid_nonfinite[0])
        raise VelocityConfigurationError(
            f"{field_name} may contain finite values or NaN, but not infinity; "
            f"found an invalid value at index {index}."
        )
    negative = np.flatnonzero(np.isfinite(array) & (array < 0.0))
    if negative.size:
        index = int(negative[0])
        raise VelocityConfigurationError(
            f"Finite {field_name} values must be non-negative; "
            f"found a negative value at index {index}."
        )


def _validate_quality_semantics(
    *,
    beat_frequency_hz: FloatArray,
    apparent_velocity_m_s: FloatArray,
    quality_flags: tuple[RidgeQualityFlag, ...],
) -> None:
    for index, flag in enumerate(quality_flags):
        frequency_is_finite = math.isfinite(float(beat_frequency_hz[index]))
        velocity_is_finite = math.isfinite(float(apparent_velocity_m_s[index]))
        if flag is RidgeQualityFlag.CANDIDATE:
            if not frequency_is_finite or not velocity_is_finite:
                raise VelocityConfigurationError(
                    "CANDIDATE frames must have finite beat frequency and "
                    "apparent velocity."
                )
        elif frequency_is_finite or velocity_is_finite:
            raise VelocityConfigurationError(
                "PRE_EVENT and OUTSIDE_ANALYSIS_WINDOW frames must retain NaN "
                "beat frequency and apparent velocity."
            )


def _store_float64_immutable(array: FloatArray) -> FloatArray:
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored
