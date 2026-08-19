"""Immutable configuration and output for event-aware ridge continuity."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.diagnostic_models import RidgeContinuityStatus
from dps_studio.core.ridge.exceptions import RidgeConfigurationError


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class EventAwareContinuityConfig:
    """Explicit SI thresholds for isolated one-frame jump classification."""

    isolated_jump_threshold_hz: float
    neighbor_recovery_tolerance_hz: float

    def __post_init__(self) -> None:
        jump = _finite_float(
            self.isolated_jump_threshold_hz,
            field_name="isolated_jump_threshold_hz",
        )
        recovery = _finite_float(
            self.neighbor_recovery_tolerance_hz,
            field_name="neighbor_recovery_tolerance_hz",
        )
        if jump <= 0.0:
            raise RidgeConfigurationError(
                "isolated_jump_threshold_hz must be strictly positive."
            )
        if recovery < 0.0:
            raise RidgeConfigurationError(
                "neighbor_recovery_tolerance_hz must be non-negative."
            )
        object.__setattr__(self, "isolated_jump_threshold_hz", jump)
        object.__setattr__(self, "neighbor_recovery_tolerance_hz", recovery)


@dataclass(frozen=True, slots=True, eq=False)
class EventAwareContinuityResult:
    """Per-frame evidence that never modifies, fills, or smooths the ridge."""

    METHOD: ClassVar[str] = (
        "adjacent SI frequency differences and centered local slope; isolated "
        "one-frame excursion requires large deviations from both finite neighbors "
        "and neighbor recovery; event transition is the set of STFT window "
        "supports containing the explicit reference time; no interpolation, "
        "smoothing, deletion, or ridge reselection"
    )

    time_s: FloatArray
    frequency_hz: FloatArray
    delta_frequency_from_previous_hz: FloatArray
    delta_frequency_to_next_hz: FloatArray
    local_frequency_slope_hz_per_s: FloatArray
    neighbor_recovery_difference_hz: FloatArray
    statuses: tuple[RidgeContinuityStatus, ...]
    event_reference_time_s: float | None
    event_reference_source: str | None
    stft_window_duration_s: float
    config: EventAwareContinuityConfig
    method: str
    source_path: Path | None

    def __post_init__(self) -> None:
        arrays = {
            "time_s": _float_array(self.time_s, field_name="time_s"),
            "frequency_hz": _float_array(
                self.frequency_hz,
                field_name="frequency_hz",
            ),
            "delta_frequency_from_previous_hz": _float_array(
                self.delta_frequency_from_previous_hz,
                field_name="delta_frequency_from_previous_hz",
            ),
            "delta_frequency_to_next_hz": _float_array(
                self.delta_frequency_to_next_hz,
                field_name="delta_frequency_to_next_hz",
            ),
            "local_frequency_slope_hz_per_s": _float_array(
                self.local_frequency_slope_hz_per_s,
                field_name="local_frequency_slope_hz_per_s",
            ),
            "neighbor_recovery_difference_hz": _float_array(
                self.neighbor_recovery_difference_hz,
                field_name="neighbor_recovery_difference_hz",
            ),
        }
        time_s = arrays["time_s"]
        if time_s.ndim != 1 or time_s.size == 0:
            raise RidgeConfigurationError(
                "time_s must be a non-empty one-dimensional array."
            )
        if not np.all(np.isfinite(time_s)) or (
            time_s.size > 1 and not np.all(np.diff(time_s) > 0.0)
        ):
            raise RidgeConfigurationError(
                "time_s must contain finite, strictly increasing SI seconds."
            )
        if any(array.shape != time_s.shape for array in arrays.values()):
            raise RidgeConfigurationError(
                "Every continuity array must match the one-dimensional time_s axis."
            )
        if any(np.any(np.isinf(array)) for array in arrays.values()):
            raise RidgeConfigurationError(
                "Continuity arrays may contain finite values or NaN, never infinity."
            )

        statuses = tuple(self.statuses)
        if len(statuses) != time_s.size or not all(
            isinstance(status, RidgeContinuityStatus) for status in statuses
        ):
            raise RidgeConfigurationError(
                "statuses must match time_s and contain RidgeContinuityStatus values."
            )
        if not isinstance(self.config, EventAwareContinuityConfig):
            raise RidgeConfigurationError(
                "config must be an EventAwareContinuityConfig."
            )
        window_duration = _finite_float(
            self.stft_window_duration_s,
            field_name="stft_window_duration_s",
        )
        if window_duration <= 0.0:
            raise RidgeConfigurationError(
                "stft_window_duration_s must be strictly positive."
            )
        event_time = _optional_finite_float(
            self.event_reference_time_s,
            field_name="event_reference_time_s",
        )
        event_source = self.event_reference_source
        if (event_time is None) != (event_source is None):
            raise RidgeConfigurationError(
                "event_reference_source must be present exactly when event time is present."
            )
        if event_source is not None and (
            not isinstance(event_source, str) or not event_source.strip()
        ):
            raise RidgeConfigurationError(
                "event_reference_source must be a non-empty string or None."
            )
        if self.method != self.METHOD:
            raise RidgeConfigurationError(f"method must be {self.METHOD!r}.")
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be a pathlib.Path or None.")

        for field_name, array in arrays.items():
            object.__setattr__(self, field_name, _immutable_array(array))
        object.__setattr__(self, "statuses", statuses)
        object.__setattr__(self, "event_reference_time_s", event_time)
        object.__setattr__(self, "event_reference_source", event_source)
        object.__setattr__(self, "stft_window_duration_s", window_duration)


def _float_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            f"{field_name} must be convertible to float64."
        ) from exc


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RidgeConfigurationError(f"{field_name} must be a finite numeric value.")
    converted = float(value)
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be finite.")
    return converted


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name=field_name)


def _immutable_array(array: FloatArray) -> FloatArray:
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64).reshape(
        array.shape
    )
    stored.setflags(write=False)
    return stored


__all__ = ["EventAwareContinuityConfig", "EventAwareContinuityResult"]
