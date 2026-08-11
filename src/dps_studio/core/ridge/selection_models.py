"""Formal Automatic ridge-selection configuration and provenance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError


IntArray = NDArray[np.int64]


class AutomaticRidgeExtractionMode(str, Enum):
    """Explicit production mode for Automatic ridge extraction."""

    CONTINUITY_ASSISTED = "continuity_assisted"
    LEGACY_STRONGEST_PEAK = "legacy_strongest_peak"


class RidgeSelectionOrigin(str, Enum):
    """Provenance of one formally selected Automatic ridge point."""

    STRONGEST_PEAK = "strongest_peak"
    CONTINUITY_ASSISTED_ALTERNATIVE = "continuity_assisted_alternative"


@dataclass(frozen=True, slots=True)
class AutomaticRidgeSelectionConfig:
    """Serializable production gates for Automatic local-peak selection."""

    mode: AutomaticRidgeExtractionMode = (
        AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED
    )
    top_k_candidates: int = 3
    continuity_reselection_enabled: bool = True
    minimum_candidate_peak_to_background_db: float = 10.0
    minimum_candidate_relative_to_strongest_db: float = -6.0
    recovery_tolerance_hz: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, AutomaticRidgeExtractionMode):
            raise RidgeConfigurationError(
                "mode must be an AutomaticRidgeExtractionMode."
            )
        top_k = self.top_k_candidates
        if isinstance(top_k, bool) or not isinstance(top_k, Integral):
            raise RidgeConfigurationError(
                "top_k_candidates must be an integer and cannot be bool."
            )
        if not 1 <= int(top_k) <= 32:
            raise RidgeConfigurationError(
                "top_k_candidates must lie in the closed interval [1, 32]."
            )
        if not isinstance(self.continuity_reselection_enabled, bool):
            raise RidgeConfigurationError(
                "continuity_reselection_enabled must be a boolean."
            )
        background = _finite_real(
            self.minimum_candidate_peak_to_background_db,
            "minimum_candidate_peak_to_background_db",
        )
        relative = _finite_real(
            self.minimum_candidate_relative_to_strongest_db,
            "minimum_candidate_relative_to_strongest_db",
        )
        recovery = self.recovery_tolerance_hz
        if recovery is not None:
            recovery = _finite_real(recovery, "recovery_tolerance_hz")
            if recovery <= 0.0:
                raise RidgeConfigurationError(
                    "recovery_tolerance_hz must be strictly positive when set."
                )
        object.__setattr__(self, "top_k_candidates", int(top_k))
        object.__setattr__(
            self,
            "minimum_candidate_peak_to_background_db",
            background,
        )
        object.__setattr__(
            self,
            "minimum_candidate_relative_to_strongest_db",
            relative,
        )
        object.__setattr__(self, "recovery_tolerance_hz", recovery)

    @property
    def reselection_is_active(self) -> bool:
        """Return whether the configured production mode may rescue a frame."""
        return (
            self.mode is AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED
            and self.continuity_reselection_enabled
        )


@dataclass(frozen=True, slots=True, eq=False)
class AutomaticRidgeSelectionResult:
    """Immutable frame-level provenance for the formal Automatic ridge."""

    METHOD: ClassVar[str] = (
        "strongest local peak by default; optional isolated-jump-only "
        "event-aware continuity rescue under explicit spectral and two-neighbor "
        "hard gates; no interpolation, smoothing, filtering, or gap filling"
    )

    time_s: NDArray[np.float64]
    origins: tuple[RidgeSelectionOrigin, ...]
    selected_candidate_rank: IntArray
    config: AutomaticRidgeSelectionConfig
    effective_recovery_tolerance_hz: float
    method: str

    def __post_init__(self) -> None:
        time_s = np.array(self.time_s, dtype=np.float64, copy=True, order="C")
        ranks = np.array(
            self.selected_candidate_rank,
            dtype=np.int64,
            copy=True,
            order="C",
        )
        origins = tuple(self.origins)
        if time_s.ndim != 1 or time_s.size == 0:
            raise RidgeConfigurationError(
                "Automatic selection time_s must be a non-empty 1-D array."
            )
        if not np.all(np.isfinite(time_s)) or (
            time_s.size > 1 and not np.all(np.diff(time_s) > 0.0)
        ):
            raise RidgeConfigurationError(
                "Automatic selection time_s must be finite and increasing."
            )
        if ranks.shape != time_s.shape or len(origins) != time_s.size:
            raise RidgeConfigurationError(
                "Automatic selection provenance must match the time axis."
            )
        if np.any(ranks < 0):
            raise RidgeConfigurationError(
                "selected_candidate_rank must be zero or positive."
            )
        if not all(isinstance(origin, RidgeSelectionOrigin) for origin in origins):
            raise RidgeConfigurationError(
                "origins must contain RidgeSelectionOrigin values."
            )
        if not isinstance(self.config, AutomaticRidgeSelectionConfig):
            raise RidgeConfigurationError(
                "config must be an AutomaticRidgeSelectionConfig."
            )
        recovery = _finite_real(
            self.effective_recovery_tolerance_hz,
            "effective_recovery_tolerance_hz",
        )
        if recovery <= 0.0:
            raise RidgeConfigurationError(
                "effective_recovery_tolerance_hz must be strictly positive."
            )
        if self.method != self.METHOD:
            raise RidgeConfigurationError(f"method must be {self.METHOD!r}.")
        rescued = np.fromiter(
            (
                origin
                is RidgeSelectionOrigin.CONTINUITY_ASSISTED_ALTERNATIVE
                for origin in origins
            ),
            dtype=np.bool_,
            count=len(origins),
        )
        if np.any(ranks[rescued] <= 1):
            raise RidgeConfigurationError(
                "Continuity alternatives must retain a candidate rank above one."
            )
        object.__setattr__(self, "time_s", _immutable_array(time_s))
        object.__setattr__(self, "selected_candidate_rank", _immutable_array(ranks))
        object.__setattr__(self, "origins", origins)
        object.__setattr__(self, "effective_recovery_tolerance_hz", recovery)

    @property
    def reselected_frame_indices(self) -> tuple[int, ...]:
        """Return frames whose formal point came from a continuity alternative."""
        return tuple(
            index
            for index, origin in enumerate(self.origins)
            if origin is RidgeSelectionOrigin.CONTINUITY_ASSISTED_ALTERNATIVE
        )


def _finite_real(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RidgeConfigurationError(f"{field_name} must be a finite number.")
    converted = float(value)
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be finite.")
    return converted


def _immutable_array(value: NDArray[np.generic]) -> NDArray[np.generic]:
    stored = np.frombuffer(value.tobytes(order="C"), dtype=value.dtype).reshape(
        value.shape
    )
    stored.setflags(write=False)
    return stored


__all__ = [
    "AutomaticRidgeExtractionMode",
    "AutomaticRidgeSelectionConfig",
    "AutomaticRidgeSelectionResult",
    "RidgeSelectionOrigin",
]
