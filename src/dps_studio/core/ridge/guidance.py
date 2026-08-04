"""GUI-independent physical constraints for guided ridge candidate search."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.time_frequency import STFTResult


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True, eq=False)
class RidgeCorridorConstraint:
    """One immutable piecewise-linear ridge corridor in SI coordinates.

    The control points define only an allowed candidate-search region.  They
    are never interpreted as measured frequencies or converted to velocity.
    The corridor is active on the closed interval from its first to last
    control time. The staged guided workflow uses that interval as its formal
    analysis domain, so guided frequency and velocity remain NaN outside it.
    """

    control_times_s: FloatArray
    control_frequencies_hz: FloatArray
    half_width_hz: float

    def __post_init__(self) -> None:
        times = _float_array(self.control_times_s, field_name="control_times_s")
        frequencies = _float_array(
            self.control_frequencies_hz,
            field_name="control_frequencies_hz",
        )
        half_width = _finite_float(self.half_width_hz, field_name="half_width_hz")
        if times.ndim != 1 or frequencies.ndim != 1:
            raise RidgeConfigurationError(
                "Ridge corridor control arrays must be one-dimensional."
            )
        if times.size < 2:
            raise RidgeConfigurationError(
                "A ridge corridor requires at least two control points."
            )
        if frequencies.size != times.size:
            raise RidgeConfigurationError(
                "control_frequencies_hz must match control_times_s."
            )
        if not np.all(np.isfinite(times)) or not np.all(np.isfinite(frequencies)):
            raise RidgeConfigurationError(
                "Ridge corridor control coordinates must all be finite."
            )
        if not np.all(np.diff(times) > 0.0):
            raise RidgeConfigurationError(
                "Ridge corridor control times must be strictly increasing."
            )
        if np.any(frequencies < 0.0):
            raise RidgeConfigurationError(
                "Ridge corridor control frequencies must be non-negative."
            )
        if half_width <= 0.0:
            raise RidgeConfigurationError(
                "Ridge corridor half_width_hz must be strictly positive."
            )
        object.__setattr__(self, "control_times_s", _immutable_array(times))
        object.__setattr__(
            self,
            "control_frequencies_hz",
            _immutable_array(frequencies),
        )
        object.__setattr__(self, "half_width_hz", half_width)

    @property
    def start_time_s(self) -> float:
        """Return the first control time and inclusive activation boundary."""
        return float(self.control_times_s[0])

    @property
    def end_time_s(self) -> float:
        """Return the last control time and inclusive activation boundary."""
        return float(self.control_times_s[-1])

    @property
    def control_point_count(self) -> int:
        """Return the number of physical control points."""
        return int(self.control_times_s.size)

    def is_active_at(self, time_s: float) -> bool:
        """Return whether the closed corridor time domain contains ``time_s``."""
        value = _finite_float(time_s, field_name="time_s")
        return self.start_time_s <= value <= self.end_time_s

    def center_frequency_hz(self, time_s: float) -> float:
        """Linearly interpolate the center frequency inside the active domain."""
        value = _finite_float(time_s, field_name="time_s")
        if not self.is_active_at(value):
            raise RidgeConfigurationError(
                "time_s lies outside the ridge corridor's active time domain."
            )
        return float(
            np.interp(value, self.control_times_s, self.control_frequencies_hz)
        )

    def allowed_band_hz(self, time_s: float) -> tuple[float, float] | None:
        """Return the corridor band, or ``None`` outside its active domain."""
        value = _finite_float(time_s, field_name="time_s")
        if not self.is_active_at(value):
            return None
        center = self.center_frequency_hz(value)
        return center - self.half_width_hz, center + self.half_width_hz


def validate_ridge_corridor_for_stft(
    constraint: RidgeCorridorConstraint,
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
) -> None:
    """Validate one corridor against real STFT and analysis coordinates."""
    if not isinstance(constraint, RidgeCorridorConstraint):
        raise RidgeConfigurationError(
            "constraint must be a RidgeCorridorConstraint instance."
        )
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError("stft_result must be an STFTResult instance.")
    minimum = _finite_float(
        minimum_frequency_hz,
        field_name="minimum_frequency_hz",
    )
    maximum = _finite_float(
        maximum_frequency_hz,
        field_name="maximum_frequency_hz",
    )
    analysis_start = _optional_finite_float(
        analysis_start_time_s,
        field_name="analysis_start_time_s",
    )
    analysis_end = _optional_finite_float(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )
    if maximum <= minimum:
        raise RidgeConfigurationError(
            "maximum_frequency_hz must be greater than minimum_frequency_hz."
        )
    if (
        analysis_start is not None
        and analysis_end is not None
        and analysis_start > analysis_end
    ):
        raise RidgeConfigurationError(
            "analysis_start_time_s must not exceed analysis_end_time_s."
        )
    time_minimum = float(stft_result.time_s[0])
    time_maximum = float(stft_result.time_s[-1])
    tolerance_s = 64.0 * np.finfo(np.float64).eps * max(
        1.0,
        abs(time_minimum),
        abs(time_maximum),
    )
    if (
        constraint.start_time_s < time_minimum - tolerance_s
        or constraint.end_time_s > time_maximum + tolerance_s
    ):
        raise RidgeConfigurationError(
            "Ridge corridor control times must lie on the STFT time axis."
        )
    if analysis_start is not None and constraint.start_time_s < analysis_start - tolerance_s:
        raise RidgeConfigurationError(
            "Ridge corridor control times must lie inside the analysis range."
        )
    if analysis_end is not None and constraint.end_time_s > analysis_end + tolerance_s:
        raise RidgeConfigurationError(
            "Ridge corridor control times must lie inside the analysis range."
        )
    grid_maximum = float(stft_result.frequency_hz[-1])
    if np.any(constraint.control_frequencies_hz > grid_maximum):
        raise RidgeConfigurationError(
            "Ridge corridor control frequencies must not exceed the STFT maximum."
        )
    corridor_minimum = float(np.min(constraint.control_frequencies_hz)) - (
        constraint.half_width_hz
    )
    corridor_maximum = float(np.max(constraint.control_frequencies_hz)) + (
        constraint.half_width_hz
    )
    if corridor_maximum < minimum or corridor_minimum > maximum:
        raise RidgeConfigurationError(
            "The ridge corridor does not intersect the global search band."
        )


def _float_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} must be convertible to a float64 array."
        ) from exc


def _immutable_array(array: FloatArray) -> FloatArray:
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64).reshape(
        array.shape
    )
    stored.setflags(write=False)
    return stored


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise RidgeConfigurationError(f"{field_name} must be a finite float.")
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(f"{field_name} must be a finite float.") from exc
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be a finite float.")
    return converted


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name=field_name)


__all__ = ["RidgeCorridorConstraint", "validate_ridge_corridor_for_stft"]
