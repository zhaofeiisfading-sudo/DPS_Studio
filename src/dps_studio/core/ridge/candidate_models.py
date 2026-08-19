"""Immutable local spectral-peak candidates for experimental diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.ridge.quality_models import RidgeSpectralQualityStatus


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class LocalPeakCandidateConfig:
    """Explicit bound for distinct local maxima retained per STFT frame."""

    maximum_candidates_per_frame: int = 3

    def __post_init__(self) -> None:
        value = self.maximum_candidates_per_frame
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise RidgeConfigurationError(
                "maximum_candidates_per_frame must be an integer and cannot be bool."
            )
        if not 1 <= int(value) <= 32:
            raise RidgeConfigurationError(
                "maximum_candidates_per_frame must lie in the closed interval [1, 32]."
            )
        object.__setattr__(self, "maximum_candidates_per_frame", int(value))


@dataclass(frozen=True, slots=True)
class LocalPeakCandidate:
    """One independently refined and assessed local maximum."""

    bin_index: int
    discrete_frequency_hz: float
    magnitude: float
    amplitude_rank: int
    refined_frequency_hz: float
    frequency_bin_offset: float
    refinement_status: RidgeRefinementStatus
    background_median_magnitude: float
    strongest_competitor_magnitude: float
    peak_to_background_db: float
    peak_to_competitor_db: float
    background_bin_count: int
    spectral_quality_status: RidgeSpectralQualityStatus

    def __post_init__(self) -> None:
        if self.bin_index < 0 or self.amplitude_rank < 1:
            raise RidgeConfigurationError(
                "Candidate bin_index and amplitude_rank must be non-negative/positive."
            )
        if not math.isfinite(self.discrete_frequency_hz) or (
            self.discrete_frequency_hz < 0.0
        ):
            raise RidgeConfigurationError(
                "Candidate discrete_frequency_hz must be finite and non-negative."
            )
        if not math.isfinite(self.magnitude) or self.magnitude < 0.0:
            raise RidgeConfigurationError(
                "Candidate magnitude must be finite and non-negative."
            )
        if not isinstance(self.refinement_status, RidgeRefinementStatus):
            raise RidgeConfigurationError(
                "Candidate refinement_status must be a RidgeRefinementStatus."
            )
        if self.refinement_status is RidgeRefinementStatus.REFINED:
            if not math.isfinite(self.refined_frequency_hz) or not math.isfinite(
                self.frequency_bin_offset
            ):
                raise RidgeConfigurationError(
                    "A refined candidate must retain finite refined values."
                )
        elif not math.isnan(self.refined_frequency_hz) or not math.isnan(
            self.frequency_bin_offset
        ):
            raise RidgeConfigurationError(
                "A failed candidate refinement must retain NaN refined values."
            )
        if not isinstance(self.spectral_quality_status, RidgeSpectralQualityStatus):
            raise RidgeConfigurationError(
                "Candidate spectral_quality_status must be a valid status."
            )
        quality_values = (
            self.background_median_magnitude,
            self.strongest_competitor_magnitude,
            self.peak_to_background_db,
            self.peak_to_competitor_db,
        )
        if self.spectral_quality_status is RidgeSpectralQualityStatus.ASSESSED:
            if self.background_bin_count < 1 or not all(
                math.isfinite(value) for value in quality_values
            ):
                raise RidgeConfigurationError(
                    "An assessed candidate must retain finite independent spectral evidence."
                )
        elif any(math.isinf(value) for value in quality_values):
            raise RidgeConfigurationError(
                "Unavailable candidate evidence may be finite or NaN, never infinity."
            )


@dataclass(frozen=True, slots=True, eq=False)
class LocalPeakCandidateResult:
    """Bounded distinct local maxima for every frame of one Automatic STFT."""

    EXTRACTION_METHOD: ClassVar[str] = (
        "scipy.signal.find_peaks on unsmoothed search-band magnitudes; plateau "
        "represented once; descending magnitude rank with frequency-bin tie break"
    )

    time_s: FloatArray
    candidates_by_frame: tuple[tuple[LocalPeakCandidate, ...], ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    background_exclusion_half_width_hz: float
    minimum_background_bin_count: int
    config: LocalPeakCandidateConfig
    extraction_method: str
    source_path: Path | None

    def __post_init__(self) -> None:
        time_s = np.array(self.time_s, dtype=np.float64, copy=True, order="C")
        if time_s.ndim != 1 or time_s.size == 0:
            raise RidgeConfigurationError(
                "Local candidate time_s must be a non-empty one-dimensional array."
            )
        if not np.all(np.isfinite(time_s)) or (
            time_s.size > 1 and not np.all(np.diff(time_s) > 0.0)
        ):
            raise RidgeConfigurationError(
                "Local candidate time_s must be finite and strictly increasing."
            )
        frames = tuple(tuple(frame) for frame in self.candidates_by_frame)
        if len(frames) != time_s.size:
            raise RidgeConfigurationError(
                "candidates_by_frame must match the complete STFT time axis."
            )
        if not isinstance(self.config, LocalPeakCandidateConfig):
            raise RidgeConfigurationError("config must be a LocalPeakCandidateConfig.")
        for frame in frames:
            if len(frame) > self.config.maximum_candidates_per_frame:
                raise RidgeConfigurationError(
                    "A frame contains more candidates than the configured bound."
                )
            if not all(isinstance(candidate, LocalPeakCandidate) for candidate in frame):
                raise RidgeConfigurationError(
                    "Every retained candidate must be a LocalPeakCandidate."
                )
            if tuple(candidate.amplitude_rank for candidate in frame) != tuple(
                range(1, len(frame) + 1)
            ):
                raise RidgeConfigurationError(
                    "Candidate amplitude ranks must be consecutive and start at one."
                )
            if len({candidate.bin_index for candidate in frame}) != len(frame):
                raise RidgeConfigurationError(
                    "Candidates in one frame must refer to distinct local maxima."
                )
        minimum = _finite_real(self.minimum_frequency_hz, "minimum_frequency_hz")
        maximum = _finite_real(self.maximum_frequency_hz, "maximum_frequency_hz")
        guard = _finite_real(
            self.background_exclusion_half_width_hz,
            "background_exclusion_half_width_hz",
        )
        if minimum < 0.0 or maximum <= minimum or guard <= 0.0:
            raise RidgeConfigurationError(
                "Candidate frequency bounds and background guard are invalid."
            )
        if self.minimum_background_bin_count < 1:
            raise RidgeConfigurationError(
                "minimum_background_bin_count must be a positive integer."
            )
        if self.extraction_method != self.EXTRACTION_METHOD:
            raise RidgeConfigurationError(
                f"extraction_method must be {self.EXTRACTION_METHOD!r}."
            )
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be pathlib.Path or None.")
        stored = np.frombuffer(time_s.tobytes(order="C"), dtype=np.float64)
        stored.setflags(write=False)
        object.__setattr__(self, "time_s", stored)
        object.__setattr__(self, "candidates_by_frame", frames)
        object.__setattr__(self, "minimum_frequency_hz", minimum)
        object.__setattr__(self, "maximum_frequency_hz", maximum)
        object.__setattr__(self, "background_exclusion_half_width_hz", guard)


def _finite_real(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RidgeConfigurationError(f"{field_name} must be a finite numeric value.")
    converted = float(value)
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{field_name} must be finite.")
    return converted


__all__ = [
    "LocalPeakCandidate",
    "LocalPeakCandidateConfig",
    "LocalPeakCandidateResult",
]
