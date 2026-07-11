"""Validated data model for raw PDV time-voltage signals."""

from __future__ import annotations

import math
from copy import deepcopy
from os import PathLike
from pathlib import Path
from typing import ClassVar
from collections.abc import Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray

from dps_studio.core.models.exceptions import (
    NonFiniteSignalError,
    NonMonotonicTimeError,
    SignalConversionError,
    SignalLengthError,
    SignalShapeError,
    SignalValidationError,
)


FloatArray = NDArray[np.float64]


class SignalRecord:
    """Validated raw PDV samples and representative sampling information.

    Non-uniform time axes are retained without resampling or warnings. Sampling
    interval, sample rate, and Nyquist frequency are representative values based
    on the median of all adjacent time intervals.
    """

    DEFAULT_UNIFORMITY_RELATIVE_TOLERANCE: ClassVar[float] = 1e-6

    __slots__ = (
        "_duration_s",
        "_end_time_s",
        "_is_uniformly_sampled",
        "_maximum_relative_interval_deviation",
        "_metadata",
        "_nyquist_frequency_hz",
        "_representative_sample_interval_s",
        "_sample_rate_hz",
        "_source_path",
        "_start_time_s",
        "_time_s",
        "_uniformity_relative_tolerance",
        "_voltage_v",
    )

    def __init__(
        self,
        time_s: ArrayLike,
        voltage_v: ArrayLike,
        source_path: str | PathLike[str] | None = None,
        metadata: Mapping[str, object] | None = None,
        *,
        uniformity_relative_tolerance: float = DEFAULT_UNIFORMITY_RELATIVE_TOLERANCE,
    ) -> None:
        """Create a signal record from time and voltage samples in SI units.

        Args:
            time_s: One-dimensional, strictly increasing time samples in seconds.
            voltage_v: One-dimensional voltage samples in volts.
            source_path: Optional source path retained without filesystem access.
            metadata: Optional small metadata mapping, stored as a deep copy.
            uniformity_relative_tolerance: Finite non-negative relative interval
                tolerance. Zero requests strict interval comparison.

        Raises:
            SignalValidationError: If the samples or derived sampling information
                are invalid.
        """
        tolerance = _validate_uniformity_relative_tolerance(
            uniformity_relative_tolerance
        )
        time_array = _convert_to_float_array(time_s, field_name="time_s")
        _validate_one_dimensional(time_array, field_name="time_s")
        voltage_array = _convert_to_float_array(voltage_v, field_name="voltage_v")
        _validate_one_dimensional(voltage_array, field_name="voltage_v")
        _validate_lengths(time_array, voltage_array)
        _validate_finite(time_array, field_name="time_s")
        _validate_finite(voltage_array, field_name="voltage_v")
        _validate_strictly_increasing(time_array)

        (
            representative_interval,
            sample_rate,
            nyquist_frequency,
            maximum_relative_deviation,
        ) = _derive_sampling_information(time_array)

        time_array.setflags(write=False)
        voltage_array.setflags(write=False)

        self._time_s = time_array
        self._voltage_v = voltage_array
        self._source_path = _normalize_source_path(source_path)
        self._metadata = deepcopy(dict(metadata)) if metadata is not None else {}
        self._uniformity_relative_tolerance = tolerance
        self._representative_sample_interval_s = representative_interval
        self._sample_rate_hz = sample_rate
        self._nyquist_frequency_hz = nyquist_frequency
        self._maximum_relative_interval_deviation = maximum_relative_deviation
        self._is_uniformly_sampled = maximum_relative_deviation <= tolerance
        self._start_time_s = float(time_array[0])
        self._end_time_s = float(time_array[-1])
        self._duration_s = self._end_time_s - self._start_time_s

    @property
    def time_s(self) -> FloatArray:
        """Return the read-only time samples in seconds."""
        read_only_view = self._time_s.view()
        read_only_view.setflags(write=False)
        return read_only_view

    @property
    def voltage_v(self) -> FloatArray:
        """Return the read-only voltage samples in volts."""
        read_only_view = self._voltage_v.view()
        read_only_view.setflags(write=False)
        return read_only_view

    @property
    def source_path(self) -> Path | None:
        """Return the optional source path without resolving it."""
        return self._source_path

    @property
    def metadata(self) -> Mapping[str, object]:
        """Return a deep copy of the signal metadata."""
        return deepcopy(self._metadata)

    @property
    def uniformity_relative_tolerance(self) -> float:
        """Return the relative interval tolerance used by this record."""
        return self._uniformity_relative_tolerance

    @property
    def sample_count(self) -> int:
        """Return the number of time-voltage sample pairs."""
        return int(self._time_s.size)

    @property
    def representative_sample_interval_s(self) -> float:
        """Return the median adjacent sample interval in seconds."""
        return self._representative_sample_interval_s

    @property
    def sample_rate_hz(self) -> float:
        """Return the representative sample rate derived from the median interval."""
        return self._sample_rate_hz

    @property
    def nyquist_frequency_hz(self) -> float:
        """Return half of the representative sample rate in hertz."""
        return self._nyquist_frequency_hz

    @property
    def duration_s(self) -> float:
        """Return the elapsed time between the first and last samples."""
        return self._duration_s

    @property
    def start_time_s(self) -> float:
        """Return the first sample time in seconds."""
        return self._start_time_s

    @property
    def end_time_s(self) -> float:
        """Return the last sample time in seconds."""
        return self._end_time_s

    @property
    def is_uniformly_sampled(self) -> bool:
        """Return whether all intervals satisfy the configured relative tolerance."""
        return self._is_uniformly_sampled

    @property
    def maximum_relative_interval_deviation(self) -> float:
        """Return the largest relative deviation from the median interval."""
        return self._maximum_relative_interval_deviation


def _convert_to_float_array(value: ArrayLike, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SignalConversionError(
            f"{field_name} could not be converted to a NumPy float64 array."
        ) from exc


def _validate_one_dimensional(array: FloatArray, *, field_name: str) -> None:
    if array.ndim != 1:
        raise SignalShapeError(
            f"{field_name} must be one-dimensional; got {array.ndim} dimensions "
            f"with shape {array.shape}."
        )


def _validate_lengths(time_s: FloatArray, voltage_v: FloatArray) -> None:
    if time_s.size != voltage_v.size:
        raise SignalLengthError(
            "time_s and voltage_v must have equal length; "
            f"got time_s length {time_s.size} and voltage_v length {voltage_v.size}."
        )
    if time_s.size < 2:
        raise SignalLengthError(
            f"time_s and voltage_v must contain at least two samples; got {time_s.size}."
        )


def _validate_finite(array: FloatArray, *, field_name: str) -> None:
    invalid_indices = np.flatnonzero(~np.isfinite(array))
    if invalid_indices.size:
        index = int(invalid_indices[0])
        raise NonFiniteSignalError(
            f"{field_name} must contain only finite values; "
            f"found {array[index]!r} at index {index}."
        )


def _validate_strictly_increasing(time_s: FloatArray) -> None:
    invalid_intervals = np.flatnonzero(time_s[1:] <= time_s[:-1])
    if not invalid_intervals.size:
        return

    left_index = int(invalid_intervals[0])
    right_index = left_index + 1
    left_value = time_s[left_index]
    right_value = time_s[right_index]
    if right_value == left_value:
        detail = (
            f"duplicate value {right_value!r} at indices {left_index} and {right_index}"
        )
    else:
        detail = (
            f"value decreases from {left_value!r} at index {left_index} "
            f"to {right_value!r} at index {right_index}"
        )
    raise NonMonotonicTimeError(f"time_s must be strictly increasing; {detail}.")


def _validate_uniformity_relative_tolerance(value: float) -> float:
    try:
        tolerance = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SignalValidationError(
            "uniformity_relative_tolerance must be a finite non-negative number."
        ) from exc
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise SignalValidationError(
            "uniformity_relative_tolerance must be finite and non-negative; "
            f"got {tolerance!r}."
        )
    return tolerance


def _normalize_source_path(source_path: str | PathLike[str] | None) -> Path | None:
    if source_path is None:
        return None
    try:
        return Path(source_path)
    except (TypeError, ValueError) as exc:
        raise SignalValidationError(
            "source_path must be a string, os.PathLike object, or None."
        ) from exc


def _derive_sampling_information(time_s: FloatArray) -> tuple[float, float, float, float]:
    with np.errstate(over="ignore", invalid="ignore"):
        intervals = np.diff(time_s)

    invalid_finite_intervals = np.flatnonzero(~np.isfinite(intervals))
    if invalid_finite_intervals.size:
        left_index = int(invalid_finite_intervals[0])
        raise SignalValidationError(
            "Cannot derive sampling information: interval between time_s indices "
            f"{left_index} and {left_index + 1} is non-finite."
        )

    invalid_positive_intervals = np.flatnonzero(intervals <= 0.0)
    if invalid_positive_intervals.size:
        left_index = int(invalid_positive_intervals[0])
        raise SignalValidationError(
            "Cannot derive sampling information: interval between time_s indices "
            f"{left_index} and {left_index + 1} must be strictly positive; "
            f"got {intervals[left_index]!r}."
        )

    with np.errstate(over="ignore", invalid="ignore"):
        representative_interval = float(np.median(intervals))
    if not math.isfinite(representative_interval) or representative_interval <= 0.0:
        raise SignalValidationError(
            "Cannot derive sampling information: representative sample interval "
            f"must be finite and strictly positive; got {representative_interval!r}."
        )

    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        sample_rate = float(np.float64(1.0) / np.float64(representative_interval))
        nyquist_frequency = float(np.float64(sample_rate) / np.float64(2.0))
        maximum_relative_deviation = float(
            np.max(np.abs(intervals - representative_interval)) / representative_interval
        )

    if not math.isfinite(sample_rate):
        raise SignalValidationError(
            "Cannot derive sampling information: representative sample_rate_hz "
            f"must be finite; got {sample_rate!r}."
        )
    if not math.isfinite(nyquist_frequency):
        raise SignalValidationError(
            "Cannot derive sampling information: representative nyquist_frequency_hz "
            f"must be finite; got {nyquist_frequency!r}."
        )
    if not math.isfinite(maximum_relative_deviation):
        raise SignalValidationError(
            "Cannot derive sampling information: maximum relative interval deviation "
            f"must be finite; got {maximum_relative_deviation!r}."
        )

    return (
        representative_interval,
        sample_rate,
        nyquist_frequency,
        maximum_relative_deviation,
    )
