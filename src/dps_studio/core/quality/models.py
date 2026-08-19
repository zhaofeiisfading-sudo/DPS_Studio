"""Immutable configuration and results for spectral beat-signal detection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import RidgeRefinementStatus


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


class SignalState(str, Enum):
    """Formal per-frame signal-existence state.

    ``MEASURED`` means spectrally qualified under the configured detection
    rules. It does not confirm the physical identity of the selected branch.
    """

    MEASURED = "measured"
    NO_DETECTABLE_BEAT = "no_detectable_beat"
    AMBIGUOUS_PEAK = "ambiguous_peak"
    INSUFFICIENT_CYCLES = "insufficient_cycles"
    PEAK_AT_BAND_BOUNDARY = "peak_at_band_boundary"
    REFINEMENT_FAILED = "refinement_failed"
    UNSTABLE_DETECTION = "unstable_detection"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"


@dataclass(frozen=True, slots=True)
class SignalDetectionConfig:
    """Validated thresholds for formal beat-signal existence detection.

    The defaults are development defaults for this repository's synthetic
    validation. They are explicit analysis settings, not instrument limits or
    universal physical standards.
    """

    minimum_peak_to_background_db: float = 10.0
    minimum_peak_to_competitor_db: float = 3.0
    peak_exclusion_half_width_bins: int = 12
    minimum_consecutive_frames: int = 3
    minimum_cycles_in_window: float = 1.0
    enabled: bool = True

    DEFAULT_STATUS: ClassVar[str] = (
        "development defaults; synthetic behavior verified; experimental "
        "threshold validation remains required"
    )

    def __post_init__(self) -> None:
        for field_name in (
            "minimum_peak_to_background_db",
            "minimum_peak_to_competitor_db",
        ):
            value = _finite_nonnegative_float(
                getattr(self, field_name),
                field_name=field_name,
            )
            object.__setattr__(self, field_name, value)
        cycles = _finite_positive_float(
            self.minimum_cycles_in_window,
            field_name="minimum_cycles_in_window",
        )
        object.__setattr__(self, "minimum_cycles_in_window", cycles)
        guard_bins = _nonnegative_integer(
            self.peak_exclusion_half_width_bins,
            field_name="peak_exclusion_half_width_bins",
        )
        object.__setattr__(self, "peak_exclusion_half_width_bins", guard_bins)
        consecutive = _positive_integer(
            self.minimum_consecutive_frames,
            field_name="minimum_consecutive_frames",
        )
        object.__setattr__(self, "minimum_consecutive_frames", consecutive)
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean.")


@dataclass(frozen=True, slots=True, eq=False)
class SignalDetectionResult:
    """Complete per-frame evidence and quality-gated formal measurements.

    The retained ``detected_event_candidate_*`` fields are TASK-013
    compatibility metadata for the first final-MEASURED run. Event-level
    eligibility and multi-stream consensus are independent downstream results.
    """

    DETECTION_METHOD: ClassVar[str] = (
        "per-frame unmodified STFT selected ridge peak; median background and "
        "strongest competitor outside an inclusive bin guard; ordered quality "
        "gates with an explicit relative-to-strongest threshold for validated "
        "continuity alternatives, which retain their explicit single-frame "
        "production rescue status; exact legacy consecutive-frame runs without "
        "interpolation or smoothing"
    )

    time_s: FloatArray
    coarse_peak_frequency_hz: FloatArray
    refined_frequency_hz: FloatArray
    apparent_velocity_m_s: FloatArray
    signal_states: tuple[SignalState, ...]
    peak_amplitude: FloatArray
    background_level: FloatArray
    strongest_competitor_level: FloatArray
    peak_to_background_db: FloatArray
    peak_to_competitor_db: FloatArray
    peak_bin_index: IntArray
    peak_is_at_band_boundary: BoolArray
    cycles_in_window: FloatArray
    refinement_statuses: tuple[RidgeRefinementStatus, ...]
    detection_config: SignalDetectionConfig
    analysis_start_time_s: float | None
    analysis_end_time_s: float | None
    manual_event_reference_time_s: float | None
    detected_event_candidate_time_s: float | None
    detected_event_candidate_run_frame_count: int
    detected_event_candidate_source: str
    window_duration_s: float
    hop_duration_s: float
    minimum_resolvable_frequency_by_cycle_rule_hz: float
    corresponding_apparent_velocity_m_s: float
    detection_method: str

    def __post_init__(self) -> None:
        float_fields = (
            "time_s",
            "coarse_peak_frequency_hz",
            "refined_frequency_hz",
            "apparent_velocity_m_s",
            "peak_amplitude",
            "background_level",
            "strongest_competitor_level",
            "peak_to_background_db",
            "peak_to_competitor_db",
            "cycles_in_window",
        )
        float_arrays = {
            field_name: _float_array(getattr(self, field_name), field_name=field_name)
            for field_name in float_fields
        }
        peak_bin_index = _int_array(
            self.peak_bin_index,
            field_name="peak_bin_index",
        )
        boundary = _bool_array(
            self.peak_is_at_band_boundary,
            field_name="peak_is_at_band_boundary",
        )
        time_s = float_arrays["time_s"]
        if time_s.ndim != 1 or time_s.size == 0:
            raise ValueError("time_s must be a non-empty one-dimensional array.")
        if not np.all(np.isfinite(time_s)):
            raise ValueError("time_s must contain only finite values.")
        if time_s.size > 1 and not np.all(np.diff(time_s) > 0.0):
            raise ValueError("time_s must be strictly increasing.")
        arrays = (*float_arrays.values(), peak_bin_index, boundary)
        if any(array.ndim != 1 or array.size != time_s.size for array in arrays):
            raise ValueError("Every detection array must match the time_s axis.")

        states = tuple(self.signal_states)
        refinements = tuple(self.refinement_statuses)
        if len(states) != time_s.size or len(refinements) != time_s.size:
            raise ValueError("Detection status sequences must match the time_s axis.")
        if not all(isinstance(state, SignalState) for state in states):
            raise TypeError("signal_states must contain only SignalState values.")
        if not all(
            isinstance(status, RidgeRefinementStatus) for status in refinements
        ):
            raise TypeError(
                "refinement_statuses must contain only RidgeRefinementStatus values."
            )
        if not isinstance(self.detection_config, SignalDetectionConfig):
            raise TypeError("detection_config must be a SignalDetectionConfig.")

        measured = np.fromiter(
            (state is SignalState.MEASURED for state in states),
            dtype=np.bool_,
            count=len(states),
        )
        refined = float_arrays["refined_frequency_hz"]
        velocity = float_arrays["apparent_velocity_m_s"]
        if not np.all(np.isfinite(refined[measured])) or not np.all(
            np.isfinite(velocity[measured])
        ):
            raise ValueError("MEASURED frames must have finite frequency and velocity.")
        if not np.all(np.isnan(refined[~measured])) or not np.all(
            np.isnan(velocity[~measured])
        ):
            raise ValueError(
                "Non-MEASURED frames must retain NaN formal frequency and velocity."
            )
        if np.any(velocity[measured] < 0.0):
            raise ValueError("Formal apparent velocity must be non-negative.")

        analysis_start = _optional_finite_float(
            self.analysis_start_time_s,
            field_name="analysis_start_time_s",
        )
        analysis_end = _optional_finite_float(
            self.analysis_end_time_s,
            field_name="analysis_end_time_s",
        )
        manual_reference = _optional_finite_float(
            self.manual_event_reference_time_s,
            field_name="manual_event_reference_time_s",
        )
        if (
            analysis_start is not None
            and analysis_end is not None
            and analysis_start > analysis_end
        ):
            raise ValueError(
                "analysis_start_time_s must not exceed analysis_end_time_s."
            )
        candidate_time = _optional_finite_float(
            self.detected_event_candidate_time_s,
            field_name="detected_event_candidate_time_s",
        )
        candidate_frames = _nonnegative_integer(
            self.detected_event_candidate_run_frame_count,
            field_name="detected_event_candidate_run_frame_count",
        )
        if (candidate_time is None) != (candidate_frames == 0):
            raise ValueError(
                "Candidate time must be present exactly when candidate run length is "
                "positive."
            )
        if candidate_frames and candidate_frames < (
            self.detection_config.minimum_consecutive_frames
        ):
            raise ValueError(
                "Candidate run length must satisfy minimum_consecutive_frames."
            )
        if self.detected_event_candidate_source != "spectral_detection":
            raise ValueError(
                "detected_event_candidate_source must be 'spectral_detection'."
            )
        window_duration = _finite_positive_float(
            self.window_duration_s,
            field_name="window_duration_s",
        )
        hop_duration = _finite_positive_float(
            self.hop_duration_s,
            field_name="hop_duration_s",
        )
        minimum_frequency = _finite_positive_float(
            self.minimum_resolvable_frequency_by_cycle_rule_hz,
            field_name="minimum_resolvable_frequency_by_cycle_rule_hz",
        )
        corresponding_velocity = _finite_positive_float(
            self.corresponding_apparent_velocity_m_s,
            field_name="corresponding_apparent_velocity_m_s",
        )
        if self.detection_method != self.DETECTION_METHOD:
            raise ValueError(f"detection_method must be {self.DETECTION_METHOD!r}.")

        for field_name, array in float_arrays.items():
            object.__setattr__(self, field_name, _immutable_array(array))
        object.__setattr__(self, "peak_bin_index", _immutable_array(peak_bin_index))
        object.__setattr__(
            self,
            "peak_is_at_band_boundary",
            _immutable_array(boundary),
        )
        object.__setattr__(self, "signal_states", states)
        object.__setattr__(self, "refinement_statuses", refinements)
        object.__setattr__(self, "analysis_start_time_s", analysis_start)
        object.__setattr__(self, "analysis_end_time_s", analysis_end)
        object.__setattr__(
            self,
            "manual_event_reference_time_s",
            manual_reference,
        )
        object.__setattr__(self, "detected_event_candidate_time_s", candidate_time)
        object.__setattr__(
            self,
            "detected_event_candidate_run_frame_count",
            candidate_frames,
        )
        object.__setattr__(self, "window_duration_s", window_duration)
        object.__setattr__(self, "hop_duration_s", hop_duration)
        object.__setattr__(
            self,
            "minimum_resolvable_frequency_by_cycle_rule_hz",
            minimum_frequency,
        )
        object.__setattr__(
            self,
            "corresponding_apparent_velocity_m_s",
            corresponding_velocity,
        )


def _finite_nonnegative_float(value: object, *, field_name: str) -> float:
    converted = _finite_float(value, field_name=field_name)
    if converted < 0.0:
        raise ValueError(f"{field_name} must be non-negative.")
    return converted


def _finite_positive_float(value: object, *, field_name: str) -> float:
    converted = _finite_float(value, field_name=field_name)
    if converted <= 0.0:
        raise ValueError(f"{field_name} must be strictly positive.")
    return converted


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite numeric value.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} must be finite.")
    return converted


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name=field_name)


def _nonnegative_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{field_name} must be an integer.")
    converted = int(value)
    if converted < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return converted


def _positive_integer(value: object, *, field_name: str) -> int:
    converted = _nonnegative_integer(value, field_name=field_name)
    if converted < 1:
        raise ValueError(f"{field_name} must be at least 1.")
    return converted


def _float_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be convertible to float64.") from exc


def _int_array(value: object, *, field_name: str) -> IntArray:
    try:
        array = np.asarray(value)
        if array.dtype.kind not in {"i", "u"}:
            raise TypeError
        return np.array(array, dtype=np.int64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be an integer array.") from exc


def _bool_array(value: object, *, field_name: str) -> BoolArray:
    try:
        array = np.asarray(value)
        if array.dtype.kind != "b":
            raise TypeError
        return np.array(array, dtype=np.bool_, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a boolean array.") from exc


def _immutable_array(array: NDArray[np.generic]) -> NDArray[np.generic]:
    buffer = array.tobytes(order="C")
    stored = np.frombuffer(buffer, dtype=array.dtype).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = ["SignalDetectionConfig", "SignalDetectionResult", "SignalState"]
