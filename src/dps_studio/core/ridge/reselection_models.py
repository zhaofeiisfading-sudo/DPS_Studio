"""Immutable evidence for experimental continuity-assisted peak reselection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import Path
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError


FloatArray = NDArray[np.float64]


class CandidateReselectionReason(str, Enum):
    """Candidate-level reason retained without an opaque aggregate score."""

    LEGACY_SELECTED = "legacy_selected"
    LEGACY_NOT_ISOLATED = "legacy_not_isolated"
    EVENT_TRANSITION_PROTECTED = "event_transition_protected"
    REFINEMENT_UNAVAILABLE = "refinement_unavailable"
    SPECTRAL_EVIDENCE_UNAVAILABLE = "spectral_evidence_unavailable"
    PEAK_TO_BACKGROUND_TOO_LOW = "peak_to_background_too_low"
    PEAK_TO_COMPETITOR_TOO_LOW = "peak_to_competitor_too_low"
    NOT_CLOSER_TO_BOTH_NEIGHBORS = "not_closer_to_both_neighbors"
    NEIGHBOR_DISTANCE_TOO_LARGE = "neighbor_distance_too_large"
    RESELECTED = "reselected"
    ELIGIBLE_NOT_SELECTED = "eligible_not_selected"


class ReselectionFrameStatus(str, Enum):
    """Frame-level experimental outcome."""

    LEGACY_NOT_ISOLATED = "legacy_not_isolated"
    EVENT_TRANSITION_PROTECTED = "event_transition_protected"
    GAP_OR_INSUFFICIENT_CONTEXT = "gap_or_insufficient_context"
    NO_ALTERNATIVE = "no_alternative"
    NO_ELIGIBLE_ALTERNATIVE = "no_eligible_alternative"
    RESELECTED = "reselected"


@dataclass(frozen=True, slots=True)
class ContinuityReselectionConfig:
    """Independent hard gates for the experimental reselection path."""

    minimum_peak_to_background_db: float = 6.0
    minimum_peak_to_competitor_db: float = -6.0
    maximum_neighbor_distance_hz: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "minimum_peak_to_background_db",
            "minimum_peak_to_competitor_db",
        ):
            value = _finite_real(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, value)
        maximum_distance = self.maximum_neighbor_distance_hz
        if maximum_distance is not None:
            maximum_distance = _finite_real(
                maximum_distance,
                "maximum_neighbor_distance_hz",
            )
            if maximum_distance <= 0.0:
                raise RidgeConfigurationError(
                    "maximum_neighbor_distance_hz must be strictly positive."
                )
        object.__setattr__(self, "maximum_neighbor_distance_hz", maximum_distance)


@dataclass(frozen=True, slots=True)
class CandidateReselectionEvidence:
    """Separated spectral and continuity evidence for one local peak."""

    candidate_rank: int
    candidate_frequency_hz: float
    candidate_magnitude: float
    candidate_peak_to_background_db: float
    candidate_peak_to_competitor_db: float
    distance_to_previous_hz: float
    distance_to_next_hz: float
    neighbor_recovery_hz: float
    event_transition: bool
    legacy_selected: bool
    experimental_selected: bool
    reselection_reason: CandidateReselectionReason


@dataclass(frozen=True, slots=True, eq=False)
class ExperimentalReselectionResult:
    """Diagnostic frequency copy; production ridge and velocities remain untouched."""

    METHOD: ClassVar[str] = (
        "isolated-jump-only hard gates over independent refinement, spectral "
        "contrast, and two-neighbor continuity evidence; lexicographic minimum "
        "of maximum neighbor distance, summed distance, then amplitude rank; no "
        "interpolation, smoothing, gap filling, or production-path mutation"
    )

    time_s: FloatArray
    legacy_frequency_hz: FloatArray
    experimental_frequency_hz: FloatArray
    evidence_by_frame: tuple[tuple[CandidateReselectionEvidence, ...], ...]
    frame_statuses: tuple[ReselectionFrameStatus, ...]
    config: ContinuityReselectionConfig
    method: str
    source_path: Path | None

    def __post_init__(self) -> None:
        arrays = {}
        for field_name in (
            "time_s",
            "legacy_frequency_hz",
            "experimental_frequency_hz",
        ):
            arrays[field_name] = np.array(
                getattr(self, field_name), dtype=np.float64, copy=True, order="C"
            )
        time_s = arrays["time_s"]
        if time_s.ndim != 1 or time_s.size == 0 or any(
            array.shape != time_s.shape for array in arrays.values()
        ):
            raise RidgeConfigurationError(
                "Every experimental reselection array must match non-empty time_s."
            )
        if not np.all(np.isfinite(time_s)) or (
            time_s.size > 1 and not np.all(np.diff(time_s) > 0.0)
        ):
            raise RidgeConfigurationError(
                "Experimental reselection time_s must be finite and increasing."
            )
        if any(np.any(np.isinf(array)) for array in arrays.values()):
            raise RidgeConfigurationError(
                "Experimental reselection frequencies may be finite or NaN."
            )
        evidence = tuple(tuple(frame) for frame in self.evidence_by_frame)
        statuses = tuple(self.frame_statuses)
        if len(evidence) != time_s.size or len(statuses) != time_s.size:
            raise RidgeConfigurationError(
                "Experimental evidence and statuses must match the time axis."
            )
        if not all(isinstance(status, ReselectionFrameStatus) for status in statuses):
            raise RidgeConfigurationError(
                "frame_statuses must contain ReselectionFrameStatus values."
            )
        if not isinstance(self.config, ContinuityReselectionConfig):
            raise RidgeConfigurationError(
                "config must be a ContinuityReselectionConfig."
            )
        if self.method != self.METHOD:
            raise RidgeConfigurationError(f"method must be {self.METHOD!r}.")
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be pathlib.Path or None.")
        for field_name, array in arrays.items():
            stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64)
            stored.setflags(write=False)
            object.__setattr__(self, field_name, stored)
        object.__setattr__(self, "evidence_by_frame", evidence)
        object.__setattr__(self, "frame_statuses", statuses)

    @property
    def reselected_frame_indices(self) -> tuple[int, ...]:
        """Return frames changed only in the experimental diagnostic copy."""
        return tuple(
            index
            for index, status in enumerate(self.frame_statuses)
            if status is ReselectionFrameStatus.RESELECTED
        )


def _finite_real(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RidgeConfigurationError(f"{field_name} must be a finite numeric value.")
    converted = float(value)
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be finite.")
    return converted


__all__ = [
    "CandidateReselectionEvidence",
    "CandidateReselectionReason",
    "ContinuityReselectionConfig",
    "ExperimentalReselectionResult",
    "ReselectionFrameStatus",
]
