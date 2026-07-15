"""Immutable result models for baseline and refined ridge extraction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class RidgeQualityFlag(str, Enum):
    """Per-frame status for an unsmoothed peak-bin ridge candidate."""

    PRE_EVENT = "pre_event"
    CANDIDATE = "candidate"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"


class RidgeRefinementStatus(str, Enum):
    """Per-frame outcome of local sub-bin peak refinement."""

    PRE_EVENT = "pre_event"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"
    REFINED = "refined"
    BOUNDARY_PEAK = "boundary_peak"
    INVALID_LOCAL_PEAK = "invalid_local_peak"
    OFFSET_OUT_OF_RANGE = "offset_out_of_range"


@dataclass(frozen=True, slots=True, eq=False)
class RidgeResult:
    """Immutable baseline ridge values on the complete STFT time axis."""

    time_s: FloatArray
    frequency_hz: FloatArray
    peak_magnitude: FloatArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    event_start_time_s: float | None
    analysis_end_time_s: float | None
    source_path: Path | None

    def __post_init__(self) -> None:
        """Validate ridge invariants and detach arrays into immutable buffers."""
        time_s = _as_float64_array(self.time_s, field_name="time_s")
        frequency_hz = _as_float64_array(
            self.frequency_hz,
            field_name="frequency_hz",
        )
        peak_magnitude = _as_float64_array(
            self.peak_magnitude,
            field_name="peak_magnitude",
        )
        quality_flags = tuple(self.quality_flags)
        minimum_frequency_hz = _finite_float(
            self.minimum_frequency_hz,
            field_name="minimum_frequency_hz",
        )
        maximum_frequency_hz = _finite_float(
            self.maximum_frequency_hz,
            field_name="maximum_frequency_hz",
        )
        event_start_time_s = _optional_finite_float(
            self.event_start_time_s,
            field_name="event_start_time_s",
        )
        analysis_end_time_s = _optional_finite_float(
            self.analysis_end_time_s,
            field_name="analysis_end_time_s",
        )

        for field_name, array in (
            ("time_s", time_s),
            ("frequency_hz", frequency_hz),
            ("peak_magnitude", peak_magnitude),
        ):
            if array.ndim != 1:
                raise RidgeConfigurationError(
                    f"{field_name} must be one-dimensional; got shape {array.shape}."
                )
        if time_s.size == 0:
            raise RidgeConfigurationError("time_s must contain at least one value.")
        if frequency_hz.size != time_s.size or peak_magnitude.size != time_s.size:
            raise RidgeConfigurationError(
                "frequency_hz and peak_magnitude must have the same length as time_s."
            )
        if len(quality_flags) != time_s.size:
            raise RidgeConfigurationError(
                "quality_flags must have the same length as time_s."
            )
        if not np.all(np.isfinite(time_s)):
            raise RidgeConfigurationError("time_s must contain only finite values.")
        if time_s.size > 1 and not np.all(np.diff(time_s) > 0.0):
            raise RidgeConfigurationError("time_s must be strictly increasing.")
        if not all(isinstance(flag, RidgeQualityFlag) for flag in quality_flags):
            raise RidgeConfigurationError(
                "quality_flags must contain only RidgeQualityFlag values."
            )
        if minimum_frequency_hz < 0.0:
            raise RidgeConfigurationError(
                "minimum_frequency_hz must be greater than or equal to zero."
            )
        if maximum_frequency_hz <= minimum_frequency_hz:
            raise RidgeConfigurationError(
                "maximum_frequency_hz must be greater than minimum_frequency_hz."
            )
        if (
            event_start_time_s is not None
            and analysis_end_time_s is not None
            and event_start_time_s > analysis_end_time_s
        ):
            raise RidgeConfigurationError(
                "event_start_time_s must be less than or equal to analysis_end_time_s."
            )
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be pathlib.Path or None.")

        _validate_frame_values(
            time_s=time_s,
            frequency_hz=frequency_hz,
            peak_magnitude=peak_magnitude,
            quality_flags=quality_flags,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
            event_start_time_s=event_start_time_s,
            analysis_end_time_s=analysis_end_time_s,
        )

        object.__setattr__(self, "time_s", _store_float64_immutable(time_s))
        object.__setattr__(
            self,
            "frequency_hz",
            _store_float64_immutable(frequency_hz),
        )
        object.__setattr__(
            self,
            "peak_magnitude",
            _store_float64_immutable(peak_magnitude),
        )
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "minimum_frequency_hz", minimum_frequency_hz)
        object.__setattr__(self, "maximum_frequency_hz", maximum_frequency_hz)
        object.__setattr__(self, "event_start_time_s", event_start_time_s)
        object.__setattr__(self, "analysis_end_time_s", analysis_end_time_s)


@dataclass(frozen=True, slots=True, eq=False)
class RefinedRidgeResult:
    """Immutable local sub-bin refinement of a baseline peak-bin ridge."""

    REFINEMENT_METHOD: ClassVar[str] = (
        "log-magnitude three-point quadratic peak interpolation"
    )

    time_s: FloatArray
    discrete_frequency_hz: FloatArray
    refined_frequency_hz: FloatArray
    discrete_frequency_bin_index: IntArray
    frequency_bin_offset: FloatArray
    peak_magnitude: FloatArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    refinement_statuses: tuple[RidgeRefinementStatus, ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    event_start_time_s: float | None
    analysis_end_time_s: float | None
    refinement_method: str
    source_path: Path | None

    def __post_init__(self) -> None:
        """Validate refinement invariants and detach arrays into immutable buffers."""
        time_s = _as_float64_array(self.time_s, field_name="time_s")
        discrete_frequency_hz = _as_float64_array(
            self.discrete_frequency_hz,
            field_name="discrete_frequency_hz",
        )
        refined_frequency_hz = _as_float64_array(
            self.refined_frequency_hz,
            field_name="refined_frequency_hz",
        )
        discrete_frequency_bin_index = _as_int64_array(
            self.discrete_frequency_bin_index,
            field_name="discrete_frequency_bin_index",
        )
        frequency_bin_offset = _as_float64_array(
            self.frequency_bin_offset,
            field_name="frequency_bin_offset",
        )
        peak_magnitude = _as_float64_array(
            self.peak_magnitude,
            field_name="peak_magnitude",
        )
        try:
            quality_flags = tuple(self.quality_flags)
            refinement_statuses = tuple(self.refinement_statuses)
        except TypeError as exc:
            raise RidgeConfigurationError(
                "quality_flags and refinement_statuses must be iterable."
            ) from exc
        minimum_frequency_hz = _finite_float(
            self.minimum_frequency_hz,
            field_name="minimum_frequency_hz",
        )
        maximum_frequency_hz = _finite_float(
            self.maximum_frequency_hz,
            field_name="maximum_frequency_hz",
        )
        event_start_time_s = _optional_finite_float(
            self.event_start_time_s,
            field_name="event_start_time_s",
        )
        analysis_end_time_s = _optional_finite_float(
            self.analysis_end_time_s,
            field_name="analysis_end_time_s",
        )

        arrays = (
            ("time_s", time_s),
            ("discrete_frequency_hz", discrete_frequency_hz),
            ("refined_frequency_hz", refined_frequency_hz),
            ("discrete_frequency_bin_index", discrete_frequency_bin_index),
            ("frequency_bin_offset", frequency_bin_offset),
            ("peak_magnitude", peak_magnitude),
        )
        for field_name, array in arrays:
            if array.ndim != 1:
                raise RidgeConfigurationError(
                    f"{field_name} must be one-dimensional; got shape {array.shape}."
                )
        if time_s.size == 0:
            raise RidgeConfigurationError("time_s must contain at least one value.")
        if any(array.size != time_s.size for _, array in arrays[1:]):
            raise RidgeConfigurationError(
                "All refinement arrays must have the same length as time_s."
            )
        if len(quality_flags) != time_s.size or len(refinement_statuses) != time_s.size:
            raise RidgeConfigurationError(
                "quality_flags and refinement_statuses must have the same length as time_s."
            )
        if not np.all(np.isfinite(time_s)):
            raise RidgeConfigurationError("time_s must contain only finite values.")
        if time_s.size > 1 and not np.all(np.diff(time_s) > 0.0):
            raise RidgeConfigurationError("time_s must be strictly increasing.")
        if not all(isinstance(flag, RidgeQualityFlag) for flag in quality_flags):
            raise RidgeConfigurationError(
                "quality_flags must contain only RidgeQualityFlag values."
            )
        if not all(
            isinstance(status, RidgeRefinementStatus)
            for status in refinement_statuses
        ):
            raise RidgeConfigurationError(
                "refinement_statuses must contain only RidgeRefinementStatus values."
            )
        if minimum_frequency_hz < 0.0:
            raise RidgeConfigurationError(
                "minimum_frequency_hz must be greater than or equal to zero."
            )
        if maximum_frequency_hz <= minimum_frequency_hz:
            raise RidgeConfigurationError(
                "maximum_frequency_hz must be greater than minimum_frequency_hz."
            )
        if (
            event_start_time_s is not None
            and analysis_end_time_s is not None
            and event_start_time_s > analysis_end_time_s
        ):
            raise RidgeConfigurationError(
                "event_start_time_s must be less than or equal to analysis_end_time_s."
            )
        if self.refinement_method != self.REFINEMENT_METHOD:
            raise RidgeConfigurationError(
                f"refinement_method must be {self.REFINEMENT_METHOD!r}."
            )
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be pathlib.Path or None.")

        _validate_refined_frame_values(
            discrete_frequency_hz=discrete_frequency_hz,
            refined_frequency_hz=refined_frequency_hz,
            discrete_frequency_bin_index=discrete_frequency_bin_index,
            frequency_bin_offset=frequency_bin_offset,
            peak_magnitude=peak_magnitude,
            quality_flags=quality_flags,
            refinement_statuses=refinement_statuses,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
        )

        object.__setattr__(self, "time_s", _store_float64_immutable(time_s))
        object.__setattr__(
            self,
            "discrete_frequency_hz",
            _store_float64_immutable(discrete_frequency_hz),
        )
        object.__setattr__(
            self,
            "refined_frequency_hz",
            _store_float64_immutable(refined_frequency_hz),
        )
        object.__setattr__(
            self,
            "discrete_frequency_bin_index",
            _store_int64_immutable(discrete_frequency_bin_index),
        )
        object.__setattr__(
            self,
            "frequency_bin_offset",
            _store_float64_immutable(frequency_bin_offset),
        )
        object.__setattr__(
            self,
            "peak_magnitude",
            _store_float64_immutable(peak_magnitude),
        )
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "refinement_statuses", refinement_statuses)
        object.__setattr__(self, "minimum_frequency_hz", minimum_frequency_hz)
        object.__setattr__(self, "maximum_frequency_hz", maximum_frequency_hz)
        object.__setattr__(self, "event_start_time_s", event_start_time_s)
        object.__setattr__(self, "analysis_end_time_s", analysis_end_time_s)


def _validate_refined_frame_values(
    *,
    discrete_frequency_hz: FloatArray,
    refined_frequency_hz: FloatArray,
    discrete_frequency_bin_index: IntArray,
    frequency_bin_offset: FloatArray,
    peak_magnitude: FloatArray,
    quality_flags: tuple[RidgeQualityFlag, ...],
    refinement_statuses: tuple[RidgeRefinementStatus, ...],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> None:
    failure_statuses = {
        RidgeRefinementStatus.BOUNDARY_PEAK,
        RidgeRefinementStatus.INVALID_LOCAL_PEAK,
        RidgeRefinementStatus.OFFSET_OUT_OF_RANGE,
    }
    for index, (flag, status) in enumerate(zip(quality_flags, refinement_statuses)):
        discrete = float(discrete_frequency_hz[index])
        refined = float(refined_frequency_hz[index])
        bin_index = int(discrete_frequency_bin_index[index])
        offset = float(frequency_bin_offset[index])
        magnitude = float(peak_magnitude[index])

        if flag is RidgeQualityFlag.PRE_EVENT:
            expected_status = RidgeRefinementStatus.PRE_EVENT
        elif flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            expected_status = RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
        else:
            expected_status = None

        if expected_status is not None:
            if status is not expected_status:
                raise RidgeConfigurationError(
                    "Masked ridge frames must retain their matching refinement status."
                )
            if (
                bin_index != -1
                or not math.isnan(discrete)
                or not math.isnan(refined)
                or not math.isnan(offset)
                or not math.isnan(magnitude)
            ):
                raise RidgeConfigurationError(
                    "Masked ridge frames must have bin index -1 and NaN values."
                )
            continue

        if status not in failure_statuses and status is not RidgeRefinementStatus.REFINED:
            raise RidgeConfigurationError(
                "CANDIDATE frames must have a candidate refinement status."
            )
        if not math.isfinite(discrete) or not math.isfinite(magnitude):
            raise RidgeConfigurationError(
                "CANDIDATE frames must retain finite discrete frequency and peak magnitude."
            )
        if not minimum_frequency_hz <= discrete <= maximum_frequency_hz:
            raise RidgeConfigurationError(
                "CANDIDATE discrete frequencies must lie within the search range."
            )
        if magnitude < 0.0 or bin_index < 0:
            raise RidgeConfigurationError(
                "CANDIDATE peak magnitudes and discrete bin indices must be non-negative."
            )
        if status is RidgeRefinementStatus.REFINED:
            if not math.isfinite(refined) or not math.isfinite(offset):
                raise RidgeConfigurationError(
                    "REFINED frames must have finite refined frequency and bin offset."
                )
            if not -0.5 <= offset <= 0.5:
                raise RidgeConfigurationError(
                    "REFINED frequency_bin_offset must lie within [-0.5, 0.5]."
                )
            if not minimum_frequency_hz <= refined <= maximum_frequency_hz:
                raise RidgeConfigurationError(
                    "REFINED frequencies must lie within the search range."
                )
        elif not math.isnan(refined) or not math.isnan(offset):
            raise RidgeConfigurationError(
                "Failed CANDIDATE refinements must have NaN refined frequency and offset."
            )


def _validate_frame_values(
    *,
    time_s: FloatArray,
    frequency_hz: FloatArray,
    peak_magnitude: FloatArray,
    quality_flags: tuple[RidgeQualityFlag, ...],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    event_start_time_s: float | None,
    analysis_end_time_s: float | None,
) -> None:
    for index, flag in enumerate(quality_flags):
        expected_flag = RidgeQualityFlag.CANDIDATE
        if event_start_time_s is not None and time_s[index] < event_start_time_s:
            expected_flag = RidgeQualityFlag.PRE_EVENT
        elif analysis_end_time_s is not None and time_s[index] > analysis_end_time_s:
            expected_flag = RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW
        if flag is not expected_flag:
            raise RidgeConfigurationError(
                "quality_flags are inconsistent with the configured time window."
            )

        frequency = frequency_hz[index]
        magnitude = peak_magnitude[index]
        if flag is RidgeQualityFlag.CANDIDATE:
            if not math.isfinite(frequency) or not math.isfinite(magnitude):
                raise RidgeConfigurationError(
                    "CANDIDATE frames must have finite frequency and peak magnitude."
                )
            if frequency < minimum_frequency_hz or frequency > maximum_frequency_hz:
                raise RidgeConfigurationError(
                    "CANDIDATE frequencies must lie within the configured search range."
                )
            if magnitude < 0.0:
                raise RidgeConfigurationError(
                    "CANDIDATE peak magnitudes must be non-negative."
                )
        elif not math.isnan(frequency) or not math.isnan(magnitude):
            raise RidgeConfigurationError(
                "Masked frames must have NaN frequency and peak magnitude."
            )


def _as_float64_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} could not be converted to a float64 array."
        ) from exc


def _as_int64_array(value: object, *, field_name: str) -> IntArray:
    try:
        array = np.asarray(value)
        if array.dtype.kind not in {"i", "u"}:
            raise TypeError
        return np.array(array, dtype=np.int64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} could not be converted to an int64 array."
        ) from exc


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise RidgeConfigurationError(f"{field_name} must be a finite float.")
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} must be a finite float."
        ) from exc
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be a finite float.")
    return converted


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name=field_name)


def _store_float64_immutable(array: FloatArray) -> FloatArray:
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _store_int64_immutable(array: IntArray) -> IntArray:
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.int64).reshape(array.shape)
    stored.setflags(write=False)
    return stored
