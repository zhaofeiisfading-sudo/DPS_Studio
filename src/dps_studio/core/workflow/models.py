"""Immutable aggregate results for one channel in the formal workflow."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.event_candidates import StreamEventCandidates
from dps_studio.core.physics import ApparentVelocityResult
from dps_studio.core.quality import SignalDetectionResult
from dps_studio.core.ridge import (
    EventAwareContinuityResult,
    ExperimentalReselectionResult,
    LocalPeakCandidateResult,
    RefinedRidgeResult,
    RidgeContinuityResult,
    RidgeResult,
    RidgeSpectralQualityResult,
)
from dps_studio.core.time_frequency import STFTResult


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True, eq=False)
class ChannelAnalysis:
    """Complete numerical results for one independently analyzed channel."""

    stft_result: STFTResult
    ridge_result: RidgeResult
    refined_result: RefinedRidgeResult
    discrete_velocity_result: ApparentVelocityResult
    formal_discrete_velocity_m_s: FloatArray
    refined_velocity_m_s: FloatArray
    display_velocity_m_s: FloatArray
    velocity_origins: tuple[str, ...]
    spectral_quality_result: RidgeSpectralQualityResult
    continuity_result: RidgeContinuityResult
    event_aware_continuity_result: EventAwareContinuityResult
    signal_detection_result: SignalDetectionResult
    stream_event_candidates: StreamEventCandidates
    local_peak_candidates: LocalPeakCandidateResult | None = None
    experimental_reselection_result: ExperimentalReselectionResult | None = None

    def __post_init__(self) -> None:
        formal_discrete_velocity = _immutable_float_array(
            self.formal_discrete_velocity_m_s,
            field_name="formal_discrete_velocity_m_s",
        )
        refined_velocity = _immutable_float_array(
            self.refined_velocity_m_s,
            field_name="refined_velocity_m_s",
        )
        display_velocity = _immutable_float_array(
            self.display_velocity_m_s,
            field_name="display_velocity_m_s",
        )
        frame_count = self.stft_result.time_s.size
        if formal_discrete_velocity.shape != (frame_count,):
            raise ValueError(
                "formal_discrete_velocity_m_s must match the STFT time axis."
            )
        if refined_velocity.shape != (frame_count,):
            raise ValueError("refined_velocity_m_s must match the STFT time axis.")
        if display_velocity.shape != (frame_count,):
            raise ValueError("display_velocity_m_s must match the STFT time axis.")
        origins = tuple(self.velocity_origins)
        if len(origins) != frame_count:
            raise ValueError("velocity_origins must match the STFT time axis.")
        if not np.array_equal(
            refined_velocity,
            self.signal_detection_result.apparent_velocity_m_s,
            equal_nan=True,
        ):
            raise ValueError(
                "refined_velocity_m_s must equal the formal detection velocity."
            )
        if not np.array_equal(
            self.stft_result.time_s,
            self.signal_detection_result.time_s,
        ):
            raise ValueError("Signal detection and STFT time axes must match.")
        if not isinstance(self.stream_event_candidates, StreamEventCandidates):
            raise TypeError(
                "stream_event_candidates must be a StreamEventCandidates."
            )
        if self.local_peak_candidates is not None and not isinstance(
            self.local_peak_candidates, LocalPeakCandidateResult
        ):
            raise TypeError(
                "local_peak_candidates must be a LocalPeakCandidateResult or None."
            )
        if self.experimental_reselection_result is not None and not isinstance(
            self.experimental_reselection_result,
            ExperimentalReselectionResult,
        ):
            raise TypeError(
                "experimental_reselection_result must be an "
                "ExperimentalReselectionResult or None."
            )
        if (self.local_peak_candidates is None) != (
            self.experimental_reselection_result is None
        ):
            raise ValueError(
                "Local candidates and experimental reselection must be present together."
            )
        object.__setattr__(
            self,
            "formal_discrete_velocity_m_s",
            formal_discrete_velocity,
        )
        object.__setattr__(self, "refined_velocity_m_s", refined_velocity)
        object.__setattr__(self, "display_velocity_m_s", display_velocity)
        object.__setattr__(self, "velocity_origins", origins)

    @property
    def discrete_velocity_m_s(self) -> FloatArray:
        """Formal quality-gated velocity from the coarse discrete frequency."""
        return self.formal_discrete_velocity_m_s

    @property
    def provisional_discrete_velocity_m_s(self) -> FloatArray:
        """Quality-unfiltered compatibility view; never a formal measurement."""
        return self.discrete_velocity_result.apparent_velocity_m_s


def _immutable_float_array(value: object, *, field_name: str) -> FloatArray:
    try:
        array = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be convertible to float64.") from exc
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = ["ChannelAnalysis"]
