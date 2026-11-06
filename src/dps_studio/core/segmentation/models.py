"""Immutable manual-gating inputs and auditable SI-unit estimates."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import VelocityCorrectionConfig

Float = NDArray[np.float64]
Bool = NDArray[np.bool_]
STAGES = ("unknown", "stationary", "onset", "acceleration", "plateau", "decline",
          "rebound", "weak_signal", "noise")


def frozen_float(values: object) -> Float:
    result = np.frombuffer(np.asarray(values, dtype=np.float64).tobytes(), dtype=np.float64)
    return result


@dataclass(frozen=True, slots=True)
class Segment:
    id: str
    start_s: float
    end_s: float
    stage: str = "unknown"
    algorithm: str = "stft"

    def __post_init__(self) -> None:
        if not self.id or not all(map(math.isfinite, (self.start_s, self.end_s))):
            raise ValueError("Segment needs an identity and finite SI endpoints")
        if self.start_s >= self.end_s or self.stage not in STAGES or not self.algorithm:
            raise ValueError("Invalid segment interval, stage or algorithm")


def validate_plan(segments: tuple[Segment, ...], start_s: float, end_s: float) -> None:
    """Every point has one owner: [start,end), with the final end included."""
    if not segments or segments[0].start_s != start_s or segments[-1].end_s != end_s:
        raise ValueError("The plan must cover the complete ROI")
    if len({segment.id for segment in segments}) != len(segments):
        raise ValueError("Segment identities must be unique")
    if any(left.end_s != right.start_s for left, right in zip(segments, segments[1:])):
        raise ValueError("Segments must be ordered and contiguous, without overlaps")


@dataclass(frozen=True, slots=True)
class EstimatorRequest:
    """Voltage V and absolute time s; algorithms never apply window/angle corrections."""
    record: SignalRecord
    start_s: float
    end_s: float
    wavelength_m: float
    workflow_options: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not all(map(math.isfinite, (self.start_s, self.end_s, self.wavelength_m))):
            raise ValueError("Finite SI settings required")
        if self.start_s >= self.end_s or self.wavelength_m <= 0:
            raise ValueError("Invalid ROI or wavelength")
        if self.start_s < self.record.start_time_s or self.end_s > self.record.end_time_s:
            raise ValueError("ROI must lie inside the original record")
        object.__setattr__(self, "workflow_options", MappingProxyType(dict(self.workflow_options)))


@dataclass(frozen=True, slots=True)
class BeatEstimate:
    time_s: Float
    frequency_hz: Float
    candidate_frequency_hz: Float
    quality: tuple[str, ...]
    algorithm: str
    source: str
    support_samples: int
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        arrays = [np.asarray(value) for value in
                  (self.time_s, self.frequency_hz, self.candidate_frequency_hz)]
        if any(value.ndim != 1 for value in arrays) or any(
                value.shape != arrays[0].shape for value in arrays):
            raise ValueError("Estimator arrays must be matching vectors")
        if len(self.quality) != len(arrays[0]) or not np.isfinite(arrays[0]).all():
            raise ValueError("Invalid quality or time axis")
        if np.any(np.diff(arrays[0]) <= 0) or self.support_samples <= 0:
            raise ValueError("Time must increase strictly; window support must be positive")
        if any(np.isinf(value).any() for value in arrays[1:]):
            raise ValueError("Missing estimates use NaN, never infinity")
        if np.any(arrays[1][np.isfinite(arrays[1])] < 0):
            raise ValueError("Real PDV beat frequency is a nonnegative magnitude")
        if not self.algorithm or not self.source:
            raise ValueError("Estimator provenance is required")
        for name in ("time_s", "frequency_hz", "candidate_frequency_hz"):
            object.__setattr__(self, name, frozen_float(getattr(self, name)))
        object.__setattr__(self, "quality", tuple(self.quality))
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class SegmentedResult:
    time_s: Float
    frequency_hz: Float
    candidate_frequency_hz: Float
    apparent_velocity_m_s: Float
    angle_corrected_velocity_m_s: Float
    corrected_velocity_m_s: Float
    segment_ids: tuple[str, ...]
    algorithm_ids: tuple[str, ...]
    quality: tuple[str, ...]
    segments: tuple[Segment, ...]
    wavelength_m: float
    correction_config: VelocityCorrectionConfig
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        count = len(self.time_s)
        for name in ("time_s", "frequency_hz", "candidate_frequency_hz",
                     "apparent_velocity_m_s", "angle_corrected_velocity_m_s",
                     "corrected_velocity_m_s"):
            array = np.asarray(getattr(self, name))
            if array.shape != (count,) or np.isinf(array).any():
                raise ValueError(f"Invalid output vector: {name}")
            object.__setattr__(self, name, frozen_float(array))
        if not np.isfinite(self.time_s).all() or np.any(np.diff(self.time_s) <= 0):
            raise ValueError("Assembled absolute time must increase without duplicate frames")
        if any(len(items) != count for items in
               (self.segment_ids, self.algorithm_ids, self.quality)):
            raise ValueError("Per-frame provenance must match time")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def valid(self) -> Bool:
        return np.isfinite(self.frequency_hz)
