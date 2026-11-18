"""Immutable aggregate results for one channel in the formal workflow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.event_candidates import StreamEventCandidates
from dps_studio.core.physics import ApparentVelocityResult, VelocityCorrectionResult
from dps_studio.core.quality import SignalDetectionResult
from dps_studio.core.ridge import (
    AutomaticRidgeSelectionResult,
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


class WorkingRidgeSource(str, Enum):
    """Auditable source of one non-formal continuous Production point."""

    REFINED = "refined"
    CONTINUITY_SELECTED = "continuity_selected"
    STRONGEST_REFINED_FALLBACK = "strongest_refined_fallback"
    COARSE_BIN_FALLBACK = "coarse_bin_fallback"
    # Source-compatible aliases retained for existing integrations.
    LOW_CONFIDENCE_FALLBACK = "strongest_refined_fallback"
    DISCRETE_FALLBACK = "coarse_bin_fallback"
    INTERPOLATED = "interpolated"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"
    NO_ALLOWED_FINITE_BIN = "no_allowed_finite_bin"


@dataclass(frozen=True, slots=True, eq=False)
class ChannelAnalysis:
    """Complete numerical results for one independently analyzed channel."""

    stft_result: STFTResult
    ridge_result: RidgeResult
    refined_result: RefinedRidgeResult
    discrete_velocity_result: ApparentVelocityResult
    formal_discrete_velocity_m_s: FloatArray
    refined_velocity_m_s: FloatArray
    velocity_correction_result: VelocityCorrectionResult
    working_frequency_hz: FloatArray
    working_source: tuple[WorkingRidgeSource, ...]
    working_velocity_m_s: FloatArray
    working_velocity_correction_result: VelocityCorrectionResult
    display_velocity_m_s: FloatArray
    velocity_origins: tuple[str, ...]
    spectral_quality_result: RidgeSpectralQualityResult
    continuity_result: RidgeContinuityResult
    event_aware_continuity_result: EventAwareContinuityResult
    signal_detection_result: SignalDetectionResult
    stream_event_candidates: StreamEventCandidates
    automatic_ridge_selection_result: AutomaticRidgeSelectionResult
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
        working_frequency = _immutable_float_array(
            self.working_frequency_hz,
            field_name="working_frequency_hz",
        )
        working_velocity = _immutable_float_array(
            self.working_velocity_m_s,
            field_name="working_velocity_m_s",
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
        if working_frequency.shape != (frame_count,):
            raise ValueError("working_frequency_hz must match the STFT time axis.")
        if working_velocity.shape != (frame_count,):
            raise ValueError("working_velocity_m_s must match the STFT time axis.")
        if display_velocity.shape != (frame_count,):
            raise ValueError("display_velocity_m_s must match the STFT time axis.")
        working_source = tuple(self.working_source)
        if len(working_source) != frame_count or not all(
            isinstance(source, WorkingRidgeSource) for source in working_source
        ):
            raise ValueError(
                "working_source must contain one WorkingRidgeSource per STFT frame."
            )
        unavailable = np.fromiter(
            (
                source
                in {
                    WorkingRidgeSource.OUTSIDE_ANALYSIS_WINDOW,
                    WorkingRidgeSource.NO_ALLOWED_FINITE_BIN,
                }
                for source in working_source
            ),
            dtype=np.bool_,
            count=frame_count,
        )
        if np.any(np.isfinite(working_frequency) == unavailable):
            raise ValueError(
                "working_frequency_hz must be finite exactly for available sources."
            )
        if not np.array_equal(
            np.isfinite(working_frequency),
            np.isfinite(working_velocity),
        ):
            raise ValueError(
                "working_velocity_m_s must be finite exactly where working frequency is."
            )
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
        if not isinstance(self.velocity_correction_result, VelocityCorrectionResult):
            raise TypeError(
                "velocity_correction_result must be a VelocityCorrectionResult."
            )
        if not np.array_equal(
            refined_velocity,
            self.velocity_correction_result.apparent_velocity_m_s,
            equal_nan=True,
        ):
            raise ValueError(
                "Velocity correction input must equal the formal apparent velocity."
            )
        if not isinstance(
            self.working_velocity_correction_result,
            VelocityCorrectionResult,
        ):
            raise TypeError(
                "working_velocity_correction_result must be a "
                "VelocityCorrectionResult."
            )
        if not np.array_equal(
            working_velocity,
            self.working_velocity_correction_result.apparent_velocity_m_s,
            equal_nan=True,
        ):
            raise ValueError(
                "Working velocity correction input must equal working velocity."
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
        if not isinstance(
            self.automatic_ridge_selection_result,
            AutomaticRidgeSelectionResult,
        ):
            raise TypeError(
                "automatic_ridge_selection_result must be an "
                "AutomaticRidgeSelectionResult."
            )
        if not np.array_equal(
            self.stft_result.time_s,
            self.automatic_ridge_selection_result.time_s,
        ):
            raise ValueError(
                "Automatic ridge selection and STFT time axes must match."
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
        object.__setattr__(self, "working_frequency_hz", working_frequency)
        object.__setattr__(self, "working_source", working_source)
        object.__setattr__(self, "working_velocity_m_s", working_velocity)
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

    @property
    def apparent_velocity_m_s(self) -> FloatArray:
        """Formal quality-gated apparent PDV velocity, retained independently."""
        return self.velocity_correction_result.apparent_velocity_m_s

    @property
    def angle_corrected_apparent_velocity_m_s(self) -> FloatArray:
        """Formal apparent velocity after line-of-sight projection correction."""
        return self.velocity_correction_result.angle_corrected_apparent_velocity_m_s

    @property
    def corrected_velocity_m_s(self) -> FloatArray:
        """Formal final velocity after angle then selected window correction."""
        return self.velocity_correction_result.corrected_velocity_m_s

    @property
    def working_apparent_velocity_m_s(self) -> FloatArray:
        """Continuous apparent velocity converted from the working ridge."""
        return self.working_velocity_m_s

    @property
    def working_corrected_velocity_m_s(self) -> FloatArray:
        """Continuous corrected velocity converted from the working ridge."""
        return self.working_velocity_correction_result.corrected_velocity_m_s

    @property
    def continuous_frequency_hz(self) -> FloatArray:
        """Production plotting frequency; quality describes but does not erase it."""
        return self.working_frequency_hz

    @property
    def continuous_apparent_velocity_m_s(self) -> FloatArray:
        """Continuous apparent velocity before angle/window corrections."""
        return self.working_velocity_m_s

    @property
    def continuous_angle_corrected_apparent_velocity_m_s(self) -> FloatArray:
        """Continuous apparent velocity after observation-angle correction."""
        return (
            self.working_velocity_correction_result
            .angle_corrected_apparent_velocity_m_s
        )

    @property
    def continuous_corrected_velocity_m_s(self) -> FloatArray:
        """Continuous final physical velocity after configured corrections."""
        return self.working_velocity_correction_result.corrected_velocity_m_s

    @property
    def plot_velocity_m_s(self) -> FloatArray:
        """Final plotting/export velocity after optional event display convention."""
        return self.display_velocity_m_s


def _immutable_float_array(value: object, *, field_name: str) -> FloatArray:
    try:
        array = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be convertible to float64.") from exc
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = ["ChannelAnalysis", "WorkingRidgeSource"]
