"""GUI-independent physical constraints for guided ridge candidate search."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias, cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.time_frequency import STFTResult


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True, eq=False)
class ManualFrequencyBoundary:
    """One immutable piecewise-linear manual boundary in SI coordinates."""

    control_times_s: FloatArray
    control_frequencies_hz: FloatArray

    def __post_init__(self) -> None:
        times = _float_array(self.control_times_s, field_name="control_times_s")
        frequencies = _float_array(
            self.control_frequencies_hz,
            field_name="control_frequencies_hz",
        )
        if times.ndim != 1 or frequencies.ndim != 1:
            raise RidgeConfigurationError(
                "Manual boundary control arrays must be one-dimensional."
            )
        if times.size < 2:
            raise RidgeConfigurationError(
                "A formal manual boundary requires at least two control points."
            )
        if frequencies.size != times.size:
            raise RidgeConfigurationError(
                "control_frequencies_hz must match control_times_s."
            )
        if not np.all(np.isfinite(times)) or not np.all(np.isfinite(frequencies)):
            raise RidgeConfigurationError(
                "Manual boundary control coordinates must all be finite."
            )
        if not np.all(np.diff(times) > 0.0):
            raise RidgeConfigurationError(
                "Manual boundary control times must be strictly increasing."
            )
        if np.any(frequencies < 0.0):
            raise RidgeConfigurationError(
                "Manual boundary control frequencies must be non-negative."
            )
        object.__setattr__(self, "control_times_s", _immutable_array(times))
        object.__setattr__(
            self,
            "control_frequencies_hz",
            _immutable_array(frequencies),
        )

    @property
    def start_time_s(self) -> float:
        return float(self.control_times_s[0])

    @property
    def end_time_s(self) -> float:
        return float(self.control_times_s[-1])

    @property
    def control_point_count(self) -> int:
        return int(self.control_times_s.size)

    def is_active_at(self, time_s: float) -> bool:
        value = _finite_float(time_s, field_name="time_s")
        return self.start_time_s <= value <= self.end_time_s

    def frequency_hz(self, time_s: float) -> float:
        """Evaluate with linear interpolation and constant endpoint extension."""
        value = _finite_float(time_s, field_name="time_s")
        return float(
            np.interp(value, self.control_times_s, self.control_frequencies_hz)
        )

    def frequencies_hz(self, time_s: object) -> FloatArray:
        """Evaluate an ordered time grid without slope extrapolation."""
        time = _float_array(time_s, field_name="time_s")
        if time.ndim != 1 or not np.all(np.isfinite(time)):
            raise RidgeConfigurationError(
                "Manual boundary evaluation times must be a finite 1-D array."
            )
        values = np.interp(
            time,
            self.control_times_s,
            self.control_frequencies_hz,
        )
        return _immutable_array(np.asarray(values, dtype=np.float64))


@dataclass(frozen=True, slots=True, eq=False)
class ManualFrequencyRegion:
    """Optional full-analysis upper/lower limits intersected with the global band."""

    upper_boundary: ManualFrequencyBoundary | None = None
    lower_boundary: ManualFrequencyBoundary | None = None

    def __post_init__(self) -> None:
        for field_name, boundary in (
            ("upper_boundary", self.upper_boundary),
            ("lower_boundary", self.lower_boundary),
        ):
            if boundary is not None and not isinstance(
                boundary, ManualFrequencyBoundary
            ):
                raise RidgeConfigurationError(
                    f"{field_name} must be a ManualFrequencyBoundary or None."
                )
        crossing_time = self.first_crossing_time_s()
        if crossing_time is not None:
            raise RidgeConfigurationError(
                "Manual lower boundary exceeds the upper boundary at "
                f"time_s={crossing_time!r}."
            )

    @property
    def is_empty(self) -> bool:
        return self.upper_boundary is None and self.lower_boundary is None

    @property
    def control_point_count(self) -> int:
        return sum(
            boundary.control_point_count
            for boundary in (self.upper_boundary, self.lower_boundary)
            if boundary is not None
        )

    @property
    def constrained_time_range_s(self) -> tuple[float, float] | None:
        boundaries = tuple(
            boundary
            for boundary in (self.upper_boundary, self.lower_boundary)
            if boundary is not None
        )
        if not boundaries:
            return None
        return (
            min(boundary.start_time_s for boundary in boundaries),
            max(boundary.end_time_s for boundary in boundaries),
        )

    def effective_bounds_hz(
        self,
        time_s: float,
        *,
        minimum_frequency_hz: float,
        maximum_frequency_hz: float,
    ) -> tuple[float, float]:
        """Return global bounds contracted by endpoint-extended manual lines."""
        value = _finite_float(time_s, field_name="time_s")
        minimum = _finite_float(
            minimum_frequency_hz,
            field_name="minimum_frequency_hz",
        )
        maximum = _finite_float(
            maximum_frequency_hz,
            field_name="maximum_frequency_hz",
        )
        if maximum <= minimum:
            raise RidgeConfigurationError(
                "maximum_frequency_hz must be greater than minimum_frequency_hz."
            )
        lower = minimum
        upper = maximum
        if self.lower_boundary is not None:
            manual_lower = self.lower_boundary.frequency_hz(value)
            lower = max(lower, manual_lower)
        if self.upper_boundary is not None:
            manual_upper = self.upper_boundary.frequency_hz(value)
            upper = min(upper, manual_upper)
        if lower > upper:
            raise RidgeConfigurationError(
                "Manual lower boundary exceeds the upper boundary at "
                f"time_s={value!r}."
            )
        return lower, upper

    def first_crossing_time_s(self) -> float | None:
        """Return the first full-domain polyline knot with lower above upper."""
        upper = self.upper_boundary
        lower = self.lower_boundary
        if upper is None or lower is None:
            return None
        knots = np.unique(
            np.concatenate(
                (
                    upper.control_times_s,
                    lower.control_times_s,
                )
            )
        )
        upper_values = np.interp(
            knots,
            upper.control_times_s,
            upper.control_frequencies_hz,
        )
        lower_values = np.interp(
            knots,
            lower.control_times_s,
            lower.control_frequencies_hz,
        )
        invalid = np.flatnonzero(lower_values > upper_values)
        return float(knots[int(invalid[0])]) if invalid.size else None


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


RidgeSearchConstraint: TypeAlias = RidgeCorridorConstraint | ManualFrequencyRegion


def evaluate_manual_frequency_region_bounds(
    region: ManualFrequencyRegion,
    time_s: object,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> tuple[FloatArray, FloatArray]:
    """Evaluate the one authoritative allowed-region boundary pair on a time grid."""
    if not isinstance(region, ManualFrequencyRegion):
        raise RidgeConfigurationError(
            "region must be a ManualFrequencyRegion instance."
        )
    time = _float_array(time_s, field_name="time_s")
    if time.ndim != 1 or not np.all(np.isfinite(time)):
        raise RidgeConfigurationError(
            "Manual region evaluation times must be a finite 1-D array."
        )
    minimum = _finite_float(
        minimum_frequency_hz,
        field_name="minimum_frequency_hz",
    )
    maximum = _finite_float(
        maximum_frequency_hz,
        field_name="maximum_frequency_hz",
    )
    if maximum <= minimum:
        raise RidgeConfigurationError(
            "maximum_frequency_hz must be greater than minimum_frequency_hz."
        )
    lower = np.full(time.shape, minimum, dtype=np.float64)
    upper = np.full(time.shape, maximum, dtype=np.float64)
    if region.lower_boundary is not None:
        lower = np.maximum(lower, region.lower_boundary.frequencies_hz(time))
    if region.upper_boundary is not None:
        upper = np.minimum(upper, region.upper_boundary.frequencies_hz(time))
    invalid = np.flatnonzero(lower > upper)
    if invalid.size:
        first = int(invalid[0])
        raise RidgeConfigurationError(
            "Manual lower boundary exceeds the upper boundary at "
            f"time_s={float(time[first])!r}."
        )
    return _immutable_array(lower), _immutable_array(upper)


def manual_frequency_region_mask(
    region: ManualFrequencyRegion,
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> NDArray[np.bool_]:
    """Rasterize one region without mutating or slicing the supplied STFT."""
    if not isinstance(region, ManualFrequencyRegion):
        raise RidgeConfigurationError(
            "region must be a ManualFrequencyRegion instance."
        )
    minimum = _finite_float(
        minimum_frequency_hz,
        field_name="minimum_frequency_hz",
    )
    maximum = _finite_float(
        maximum_frequency_hz,
        field_name="maximum_frequency_hz",
    )
    if maximum <= minimum:
        raise RidgeConfigurationError(
            "maximum_frequency_hz must be greater than minimum_frequency_hz."
        )
    frequency_axis = stft_result.frequency_hz
    lower, upper = evaluate_manual_frequency_region_bounds(
        region,
        stft_result.time_s,
        minimum_frequency_hz=minimum,
        maximum_frequency_hz=maximum,
    )
    mask = (
        (frequency_axis[:, np.newaxis] >= lower[np.newaxis, :])
        & (frequency_axis[:, np.newaxis] <= upper[np.newaxis, :])
        & (frequency_axis[:, np.newaxis] >= minimum)
        & (frequency_axis[:, np.newaxis] <= maximum)
    )
    mask.setflags(write=False)
    return mask


def validate_manual_frequency_region_for_stft(
    region: ManualFrequencyRegion,
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
) -> None:
    """Validate the effective grid intersection while retaining physical points."""
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError("stft_result must be an STFTResult instance.")
    analysis_start = _optional_finite_float(
        analysis_start_time_s,
        field_name="analysis_start_time_s",
    )
    analysis_end = _optional_finite_float(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )
    if (
        analysis_start is not None
        and analysis_end is not None
        and analysis_start > analysis_end
    ):
        raise RidgeConfigurationError(
            "analysis_start_time_s must not exceed analysis_end_time_s."
        )
    grid_maximum = float(stft_result.frequency_hz[-1])
    for boundary in (region.upper_boundary, region.lower_boundary):
        if boundary is not None and np.any(
            boundary.control_frequencies_hz > grid_maximum
        ):
            raise RidgeConfigurationError(
                "Manual boundary frequencies must not exceed the STFT maximum."
            )
    mask = manual_frequency_region_mask(
        region,
        stft_result,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
    )
    active_frames = np.ones(stft_result.time_s.shape, dtype=np.bool_)
    if analysis_start is not None:
        active_frames &= stft_result.time_s >= analysis_start
    if analysis_end is not None:
        active_frames &= stft_result.time_s <= analysis_end
    active_times = stft_result.time_s[active_frames]
    evaluate_manual_frequency_region_bounds(
        region,
        active_times,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
    )
    empty_frames = active_frames & ~np.any(mask, axis=0)
    if np.any(empty_frames):
        first = int(np.flatnonzero(empty_frames)[0])
        raise RidgeConfigurationError(
            "The manual frequency region has no STFT frequency bin at "
            f"time_s={float(stft_result.time_s[first])!r}."
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


__all__ = [
    "ManualFrequencyBoundary",
    "ManualFrequencyRegion",
    "RidgeCorridorConstraint",
    "RidgeSearchConstraint",
    "evaluate_manual_frequency_region_bounds",
    "manual_frequency_region_mask",
    "validate_manual_frequency_region_for_stft",
    "validate_ridge_corridor_for_stft",
]
