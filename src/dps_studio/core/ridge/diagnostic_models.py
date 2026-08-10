"""Immutable ridge continuity and related-frequency diagnostic results."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import RidgeQualityFlag, RidgeRefinementStatus
from dps_studio.core.ridge.quality_models import RidgeSpectralQualityStatus


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class RidgeContinuityStatus(str, Enum):
    """Per-frame outcome of adjacent-frame continuity assessment."""

    PRE_EVENT = "pre_event"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"
    ASSESSED = "assessed"
    NO_PREVIOUS_CANDIDATE = "no_previous_candidate"
    NO_TWO_PREVIOUS_CANDIDATES = "no_two_previous_candidates"
    REFINEMENT_UNAVAILABLE = "refinement_unavailable"
    INVALID_TIME_INTERVAL = "invalid_time_interval"
    INPUT_MISMATCH = "input_mismatch"
    NORMAL_CONTINUITY = "normal_continuity"
    EVENT_TRANSITION = "event_transition"
    ISOLATED_JUMP = "isolated_jump"
    GAP = "gap"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class RelatedFrequencyEvidenceStatus(str, Enum):
    """Outcome for one target related-frequency band in one frame."""

    PRE_EVENT = "pre_event"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"
    ASSESSED = "assessed"
    REFINEMENT_UNAVAILABLE = "refinement_unavailable"
    TARGET_OUT_OF_RANGE = "target_out_of_range"
    INSUFFICIENT_SEARCH_BINS = "insufficient_search_bins"
    INVALID_MAIN_PEAK_MAGNITUDE = "invalid_main_peak_magnitude"
    INVALID_RELATED_FREQUENCY_MAGNITUDE = (
        "invalid_related_frequency_magnitude"
    )
    INPUT_MISMATCH = "input_mismatch"


@dataclass(frozen=True, slots=True, eq=False)
class RidgeContinuityResult:
    """Immutable adjacent-array-frame continuity evidence."""

    CONTINUITY_METHOD: ClassVar[str] = (
        "first difference and time slope from adjacent refined candidate frames; "
        "second difference from three adjacent refined candidate frames; no "
        "thresholding, smoothing, interpolation, or ridge modification"
    )

    time_s: FloatArray
    refined_frequency_hz: FloatArray
    previous_refined_frequency_hz: FloatArray
    frame_interval_s: FloatArray
    frequency_step_hz: FloatArray
    absolute_frequency_step_hz: FloatArray
    frequency_slope_hz_s: FloatArray
    frequency_second_difference_hz: FloatArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    refinement_statuses: tuple[RidgeRefinementStatus, ...]
    continuity_statuses: tuple[RidgeContinuityStatus, ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    event_start_time_s: float | None
    analysis_end_time_s: float | None
    continuity_method: str
    source_path: Path | None

    def __post_init__(self) -> None:
        float_arrays = {
            "time_s": _as_float64_array(self.time_s, field_name="time_s"),
            "refined_frequency_hz": _as_float64_array(
                self.refined_frequency_hz,
                field_name="refined_frequency_hz",
            ),
            "previous_refined_frequency_hz": _as_float64_array(
                self.previous_refined_frequency_hz,
                field_name="previous_refined_frequency_hz",
            ),
            "frame_interval_s": _as_float64_array(
                self.frame_interval_s,
                field_name="frame_interval_s",
            ),
            "frequency_step_hz": _as_float64_array(
                self.frequency_step_hz,
                field_name="frequency_step_hz",
            ),
            "absolute_frequency_step_hz": _as_float64_array(
                self.absolute_frequency_step_hz,
                field_name="absolute_frequency_step_hz",
            ),
            "frequency_slope_hz_s": _as_float64_array(
                self.frequency_slope_hz_s,
                field_name="frequency_slope_hz_s",
            ),
            "frequency_second_difference_hz": _as_float64_array(
                self.frequency_second_difference_hz,
                field_name="frequency_second_difference_hz",
            ),
        }
        quality_flags = tuple(self.quality_flags)
        refinement_statuses = tuple(self.refinement_statuses)
        continuity_statuses = tuple(self.continuity_statuses)
        minimum, maximum, event_start, analysis_end = _validate_common_metadata(
            time_s=float_arrays["time_s"],
            arrays=tuple(float_arrays.values()),
            quality_flags=quality_flags,
            refinement_statuses=refinement_statuses,
            minimum_frequency_hz=self.minimum_frequency_hz,
            maximum_frequency_hz=self.maximum_frequency_hz,
            event_start_time_s=self.event_start_time_s,
            analysis_end_time_s=self.analysis_end_time_s,
            source_path=self.source_path,
        )
        if len(continuity_statuses) != float_arrays["time_s"].size or not all(
            isinstance(status, RidgeContinuityStatus)
            for status in continuity_statuses
        ):
            raise RidgeConfigurationError(
                "continuity_statuses must match time_s and contain only "
                "RidgeContinuityStatus values."
            )
        if self.continuity_method != self.CONTINUITY_METHOD:
            raise RidgeConfigurationError(
                f"continuity_method must be {self.CONTINUITY_METHOD!r}."
            )
        _validate_continuity_frames(
            float_arrays=float_arrays,
            quality_flags=quality_flags,
            refinement_statuses=refinement_statuses,
            continuity_statuses=continuity_statuses,
            minimum_frequency_hz=minimum,
            maximum_frequency_hz=maximum,
        )

        for field_name, array in float_arrays.items():
            object.__setattr__(self, field_name, _store_float64_immutable(array))
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "refinement_statuses", refinement_statuses)
        object.__setattr__(self, "continuity_statuses", continuity_statuses)
        object.__setattr__(self, "minimum_frequency_hz", minimum)
        object.__setattr__(self, "maximum_frequency_hz", maximum)
        object.__setattr__(self, "event_start_time_s", event_start)
        object.__setattr__(self, "analysis_end_time_s", analysis_end)


@dataclass(frozen=True, slots=True, eq=False)
class RelatedFrequencyEvidenceResult:
    """Immutable local spectral evidence near explicit 2f and f/2 targets."""

    EVIDENCE_METHOD: ClassVar[str] = (
        "local maximum magnitude within an explicit half-width around 2f and f/2 "
        "targets in the closed ridge analysis band; 20*log10 main-to-related "
        "magnitude ratios; diagnostic evidence only"
    )

    time_s: FloatArray
    refined_frequency_hz: FloatArray
    discrete_frequency_bin_index: IntArray
    main_peak_magnitude: FloatArray
    double_frequency_target_hz: FloatArray
    double_frequency_peak_hz: FloatArray
    double_frequency_peak_magnitude: FloatArray
    double_frequency_peak_offset_hz: FloatArray
    main_to_double_frequency_db: FloatArray
    half_frequency_target_hz: FloatArray
    half_frequency_peak_hz: FloatArray
    half_frequency_peak_magnitude: FloatArray
    half_frequency_peak_offset_hz: FloatArray
    main_to_half_frequency_db: FloatArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    refinement_statuses: tuple[RidgeRefinementStatus, ...]
    spectral_quality_statuses: tuple[RidgeSpectralQualityStatus, ...]
    double_frequency_statuses: tuple[RelatedFrequencyEvidenceStatus, ...]
    half_frequency_statuses: tuple[RelatedFrequencyEvidenceStatus, ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    event_start_time_s: float | None
    analysis_end_time_s: float | None
    search_half_width_hz: float
    evidence_method: str
    source_path: Path | None

    @property
    def related_frequency_statuses(
        self,
    ) -> tuple[
        tuple[RelatedFrequencyEvidenceStatus, RelatedFrequencyEvidenceStatus],
        ...,
    ]:
        """Return per-frame ``(double-frequency, half-frequency)`` statuses."""
        return tuple(zip(self.double_frequency_statuses, self.half_frequency_statuses))

    def __post_init__(self) -> None:
        float_arrays = {
            "time_s": _as_float64_array(self.time_s, field_name="time_s"),
            "refined_frequency_hz": _as_float64_array(
                self.refined_frequency_hz,
                field_name="refined_frequency_hz",
            ),
            "main_peak_magnitude": _as_float64_array(
                self.main_peak_magnitude,
                field_name="main_peak_magnitude",
            ),
            "double_frequency_target_hz": _as_float64_array(
                self.double_frequency_target_hz,
                field_name="double_frequency_target_hz",
            ),
            "double_frequency_peak_hz": _as_float64_array(
                self.double_frequency_peak_hz,
                field_name="double_frequency_peak_hz",
            ),
            "double_frequency_peak_magnitude": _as_float64_array(
                self.double_frequency_peak_magnitude,
                field_name="double_frequency_peak_magnitude",
            ),
            "double_frequency_peak_offset_hz": _as_float64_array(
                self.double_frequency_peak_offset_hz,
                field_name="double_frequency_peak_offset_hz",
            ),
            "main_to_double_frequency_db": _as_float64_array(
                self.main_to_double_frequency_db,
                field_name="main_to_double_frequency_db",
            ),
            "half_frequency_target_hz": _as_float64_array(
                self.half_frequency_target_hz,
                field_name="half_frequency_target_hz",
            ),
            "half_frequency_peak_hz": _as_float64_array(
                self.half_frequency_peak_hz,
                field_name="half_frequency_peak_hz",
            ),
            "half_frequency_peak_magnitude": _as_float64_array(
                self.half_frequency_peak_magnitude,
                field_name="half_frequency_peak_magnitude",
            ),
            "half_frequency_peak_offset_hz": _as_float64_array(
                self.half_frequency_peak_offset_hz,
                field_name="half_frequency_peak_offset_hz",
            ),
            "main_to_half_frequency_db": _as_float64_array(
                self.main_to_half_frequency_db,
                field_name="main_to_half_frequency_db",
            ),
        }
        bin_indices = _as_int64_array(
            self.discrete_frequency_bin_index,
            field_name="discrete_frequency_bin_index",
        )
        quality_flags = tuple(self.quality_flags)
        refinement_statuses = tuple(self.refinement_statuses)
        spectral_quality_statuses = tuple(self.spectral_quality_statuses)
        double_statuses = tuple(self.double_frequency_statuses)
        half_statuses = tuple(self.half_frequency_statuses)
        minimum, maximum, event_start, analysis_end = _validate_common_metadata(
            time_s=float_arrays["time_s"],
            arrays=(*tuple(float_arrays.values()), bin_indices),
            quality_flags=quality_flags,
            refinement_statuses=refinement_statuses,
            minimum_frequency_hz=self.minimum_frequency_hz,
            maximum_frequency_hz=self.maximum_frequency_hz,
            event_start_time_s=self.event_start_time_s,
            analysis_end_time_s=self.analysis_end_time_s,
            source_path=self.source_path,
        )
        frame_count = float_arrays["time_s"].size
        status_sequences = (
            ("spectral_quality_statuses", spectral_quality_statuses, RidgeSpectralQualityStatus),
            ("double_frequency_statuses", double_statuses, RelatedFrequencyEvidenceStatus),
            ("half_frequency_statuses", half_statuses, RelatedFrequencyEvidenceStatus),
        )
        for field_name, statuses, expected_type in status_sequences:
            if len(statuses) != frame_count or not all(
                isinstance(status, expected_type) for status in statuses
            ):
                raise RidgeConfigurationError(
                    f"{field_name} must match time_s and contain valid status values."
                )
        search_half_width_hz = _finite_float(
            self.search_half_width_hz,
            field_name="search_half_width_hz",
        )
        if search_half_width_hz <= 0.0:
            raise RidgeConfigurationError(
                "search_half_width_hz must be greater than zero."
            )
        if self.evidence_method != self.EVIDENCE_METHOD:
            raise RidgeConfigurationError(
                f"evidence_method must be {self.EVIDENCE_METHOD!r}."
            )
        _validate_related_frames(
            float_arrays=float_arrays,
            bin_indices=bin_indices,
            quality_flags=quality_flags,
            refinement_statuses=refinement_statuses,
            spectral_quality_statuses=spectral_quality_statuses,
            double_statuses=double_statuses,
            half_statuses=half_statuses,
            minimum_frequency_hz=minimum,
            maximum_frequency_hz=maximum,
        )

        for field_name, array in float_arrays.items():
            object.__setattr__(self, field_name, _store_float64_immutable(array))
        object.__setattr__(
            self,
            "discrete_frequency_bin_index",
            _store_int64_immutable(bin_indices),
        )
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "refinement_statuses", refinement_statuses)
        object.__setattr__(
            self,
            "spectral_quality_statuses",
            spectral_quality_statuses,
        )
        object.__setattr__(self, "double_frequency_statuses", double_statuses)
        object.__setattr__(self, "half_frequency_statuses", half_statuses)
        object.__setattr__(self, "minimum_frequency_hz", minimum)
        object.__setattr__(self, "maximum_frequency_hz", maximum)
        object.__setattr__(self, "event_start_time_s", event_start)
        object.__setattr__(self, "analysis_end_time_s", analysis_end)
        object.__setattr__(self, "search_half_width_hz", search_half_width_hz)


def _validate_common_metadata(
    *,
    time_s: FloatArray,
    arrays: tuple[NDArray[np.generic], ...],
    quality_flags: tuple[RidgeQualityFlag, ...],
    refinement_statuses: tuple[RidgeRefinementStatus, ...],
    minimum_frequency_hz: object,
    maximum_frequency_hz: object,
    event_start_time_s: object,
    analysis_end_time_s: object,
    source_path: object,
) -> tuple[float, float, float | None, float | None]:
    for array in arrays:
        if array.ndim != 1:
            raise RidgeConfigurationError(
                f"All diagnostic arrays must be one-dimensional; got {array.shape}."
            )
    if time_s.size == 0 or any(array.size != time_s.size for array in arrays):
        raise RidgeConfigurationError(
            "All diagnostic arrays must have the same non-zero length as time_s."
        )
    if not np.all(np.isfinite(time_s)) or (
        time_s.size > 1 and not np.all(np.diff(time_s) > 0.0)
    ):
        raise RidgeConfigurationError(
            "time_s must be finite and strictly increasing."
        )
    if len(quality_flags) != time_s.size or not all(
        isinstance(flag, RidgeQualityFlag) for flag in quality_flags
    ):
        raise RidgeConfigurationError(
            "quality_flags must match time_s and contain RidgeQualityFlag values."
        )
    if len(refinement_statuses) != time_s.size or not all(
        isinstance(status, RidgeRefinementStatus)
        for status in refinement_statuses
    ):
        raise RidgeConfigurationError(
            "refinement_statuses must match time_s and contain valid values."
        )
    minimum = _finite_float(
        minimum_frequency_hz,
        field_name="minimum_frequency_hz",
    )
    maximum = _finite_float(
        maximum_frequency_hz,
        field_name="maximum_frequency_hz",
    )
    event_start = _optional_finite_float(
        event_start_time_s,
        field_name="event_start_time_s",
    )
    analysis_end = _optional_finite_float(
        analysis_end_time_s,
        field_name="analysis_end_time_s",
    )
    if minimum < 0.0 or maximum <= minimum:
        raise RidgeConfigurationError("The diagnostic frequency range is invalid.")
    if event_start is not None and analysis_end is not None and event_start > analysis_end:
        raise RidgeConfigurationError("The diagnostic analysis time range is invalid.")
    if source_path is not None and not isinstance(source_path, Path):
        raise RidgeConfigurationError("source_path must be pathlib.Path or None.")
    return minimum, maximum, event_start, analysis_end


def _validate_continuity_frames(
    *,
    float_arrays: dict[str, FloatArray],
    quality_flags: tuple[RidgeQualityFlag, ...],
    refinement_statuses: tuple[RidgeRefinementStatus, ...],
    continuity_statuses: tuple[RidgeContinuityStatus, ...],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> None:
    refined = float_arrays["refined_frequency_hz"]
    derived_names = (
        "previous_refined_frequency_hz",
        "frame_interval_s",
        "frequency_step_hz",
        "absolute_frequency_step_hz",
        "frequency_slope_hz_s",
        "frequency_second_difference_hz",
    )
    for index, (flag, refinement_status, status) in enumerate(
        zip(quality_flags, refinement_statuses, continuity_statuses)
    ):
        derived = tuple(float(float_arrays[name][index]) for name in derived_names)
        refined_value = float(refined[index])
        if flag is RidgeQualityFlag.PRE_EVENT:
            if (
                refinement_status is not RidgeRefinementStatus.PRE_EVENT
                or status is not RidgeContinuityStatus.PRE_EVENT
                or not math.isnan(refined_value)
                or not _all_nan(*derived)
            ):
                raise RidgeConfigurationError("Invalid PRE_EVENT continuity frame.")
            continue
        if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            if (
                refinement_status is not RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
                or status is not RidgeContinuityStatus.OUTSIDE_ANALYSIS_WINDOW
                or not math.isnan(refined_value)
                or not _all_nan(*derived)
            ):
                raise RidgeConfigurationError("Invalid OUTSIDE continuity frame.")
            continue
        if flag is RidgeQualityFlag.NO_ALLOWED_BINS:
            if (
                refinement_status is not RidgeRefinementStatus.NO_CANDIDATE
                or status is not RidgeContinuityStatus.REFINEMENT_UNAVAILABLE
                or not math.isnan(refined_value)
                or not _all_nan(*derived)
            ):
                raise RidgeConfigurationError(
                    "Invalid no-candidate continuity frame."
                )
            continue
        if refinement_status is not RidgeRefinementStatus.REFINED:
            if (
                status is not RidgeContinuityStatus.REFINEMENT_UNAVAILABLE
                or not math.isnan(refined_value)
                or not _all_nan(*derived)
            ):
                raise RidgeConfigurationError(
                    "Unavailable candidate refinements must have NaN continuity values."
            )
            continue
        if not math.isfinite(refined_value) or not (
            minimum_frequency_hz <= refined_value <= maximum_frequency_hz
        ):
            raise RidgeConfigurationError(
                "REFINED continuity frames require a finite in-band frequency."
            )
        if status is RidgeContinuityStatus.NO_PREVIOUS_CANDIDATE:
            if not _all_nan(*derived):
                raise RidgeConfigurationError(
                    "NO_PREVIOUS_CANDIDATE frames must have NaN derived values."
                )
        elif status is RidgeContinuityStatus.NO_TWO_PREVIOUS_CANDIDATES:
            if not all(math.isfinite(value) for value in derived[:5]) or not math.isnan(
                derived[5]
            ):
                raise RidgeConfigurationError(
                    "NO_TWO_PREVIOUS_CANDIDATES requires first-difference evidence only."
                )
        elif status is RidgeContinuityStatus.ASSESSED:
            if not all(math.isfinite(value) for value in derived):
                raise RidgeConfigurationError(
                    "ASSESSED continuity frames require finite derived values."
                )
        elif status in {
            RidgeContinuityStatus.INVALID_TIME_INTERVAL,
            RidgeContinuityStatus.INPUT_MISMATCH,
        }:
            if not _all_nan(*derived):
                raise RidgeConfigurationError(
                    "Invalid continuity frames must have NaN derived values."
                )
        else:
            raise RidgeConfigurationError(
                "CANDIDATE continuity frame has an incompatible status."
            )


def _validate_related_frames(
    *,
    float_arrays: dict[str, FloatArray],
    bin_indices: IntArray,
    quality_flags: tuple[RidgeQualityFlag, ...],
    refinement_statuses: tuple[RidgeRefinementStatus, ...],
    spectral_quality_statuses: tuple[RidgeSpectralQualityStatus, ...],
    double_statuses: tuple[RelatedFrequencyEvidenceStatus, ...],
    half_statuses: tuple[RelatedFrequencyEvidenceStatus, ...],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> None:
    refined = float_arrays["refined_frequency_hz"]
    main = float_arrays["main_peak_magnitude"]
    for index, (flag, refinement_status, spectral_status, double_status, half_status) in enumerate(
        zip(
            quality_flags,
            refinement_statuses,
            spectral_quality_statuses,
            double_statuses,
            half_statuses,
        )
    ):
        refined_value = float(refined[index])
        main_value = float(main[index])
        double_values = _branch_values(float_arrays, index, prefix="double_frequency")
        half_values = _branch_values(float_arrays, index, prefix="half_frequency")
        if flag is RidgeQualityFlag.PRE_EVENT:
            if (
                refinement_status is not RidgeRefinementStatus.PRE_EVENT
                or spectral_status is not RidgeSpectralQualityStatus.PRE_EVENT
                or double_status is not RelatedFrequencyEvidenceStatus.PRE_EVENT
                or half_status is not RelatedFrequencyEvidenceStatus.PRE_EVENT
                or int(bin_indices[index]) != -1
                or not math.isnan(refined_value)
                or not math.isnan(main_value)
                or not _all_nan(*double_values, *half_values)
            ):
                raise RidgeConfigurationError("Invalid PRE_EVENT related-frequency frame.")
            continue
        if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            if (
                refinement_status is not RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
                or spectral_status
                is not RidgeSpectralQualityStatus.OUTSIDE_ANALYSIS_WINDOW
                or double_status
                is not RelatedFrequencyEvidenceStatus.OUTSIDE_ANALYSIS_WINDOW
                or half_status
                is not RelatedFrequencyEvidenceStatus.OUTSIDE_ANALYSIS_WINDOW
                or int(bin_indices[index]) != -1
                or not math.isnan(refined_value)
                or not math.isnan(main_value)
                or not _all_nan(*double_values, *half_values)
            ):
                raise RidgeConfigurationError("Invalid OUTSIDE related-frequency frame.")
            continue
        if flag is RidgeQualityFlag.NO_ALLOWED_BINS:
            if (
                refinement_status is not RidgeRefinementStatus.NO_CANDIDATE
                or spectral_status is not RidgeSpectralQualityStatus.NO_CANDIDATE
                or double_status
                is not RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE
                or half_status
                is not RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE
                or int(bin_indices[index]) != -1
                or not math.isnan(refined_value)
                or not math.isnan(main_value)
                or not _all_nan(*double_values, *half_values)
            ):
                raise RidgeConfigurationError(
                    "Invalid no-candidate related-frequency frame."
                )
            continue
        if int(bin_indices[index]) < 0:
            raise RidgeConfigurationError(
                "CANDIDATE related-frequency frames require a non-negative bin index."
            )
        if refinement_status is not RidgeRefinementStatus.REFINED:
            if (
                double_status
                is not RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE
                or half_status
                is not RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE
                or not math.isnan(refined_value)
                or not math.isnan(main_value)
                or not _all_nan(*double_values, *half_values)
            ):
                raise RidgeConfigurationError(
                    "Unavailable refinements must have NaN related-frequency values."
            )
            continue
        if not math.isfinite(refined_value) or not (
            minimum_frequency_hz <= refined_value <= maximum_frequency_hz
        ):
            raise RidgeConfigurationError(
                "REFINED related-frequency frames require a finite in-band frequency."
            )
        if double_status is RelatedFrequencyEvidenceStatus.INVALID_MAIN_PEAK_MAGNITUDE:
            if (
                half_status
                is not RelatedFrequencyEvidenceStatus.INVALID_MAIN_PEAK_MAGNITUDE
                or not math.isnan(main_value)
                or not _all_nan(*double_values, *half_values)
            ):
                raise RidgeConfigurationError("Invalid main-peak status is inconsistent.")
            continue
        if not math.isfinite(main_value) or main_value <= 0.0:
            raise RidgeConfigurationError(
                "Related-frequency evidence requires a positive finite main magnitude."
            )
        _validate_branch(double_status, double_values)
        _validate_branch(half_status, half_values)


def _branch_values(
    float_arrays: dict[str, FloatArray],
    index: int,
    *,
    prefix: str,
) -> tuple[float, float, float, float, float]:
    ratio_name = (
        "main_to_double_frequency_db"
        if prefix == "double_frequency"
        else "main_to_half_frequency_db"
    )
    return (
        float(float_arrays[f"{prefix}_target_hz"][index]),
        float(float_arrays[f"{prefix}_peak_hz"][index]),
        float(float_arrays[f"{prefix}_peak_magnitude"][index]),
        float(float_arrays[f"{prefix}_peak_offset_hz"][index]),
        float(float_arrays[ratio_name][index]),
    )


def _validate_branch(
    status: RelatedFrequencyEvidenceStatus,
    values: tuple[float, float, float, float, float],
) -> None:
    target, peak_hz, peak_magnitude, offset_hz, ratio_db = values
    if status is RelatedFrequencyEvidenceStatus.ASSESSED:
        if (
            not all(math.isfinite(value) for value in values)
            or peak_magnitude <= 0.0
        ):
            raise RidgeConfigurationError(
                "ASSESSED related-frequency evidence must be finite and positive."
            )
    elif status is RelatedFrequencyEvidenceStatus.TARGET_OUT_OF_RANGE:
        if not _all_nan(*values):
            raise RidgeConfigurationError(
                "TARGET_OUT_OF_RANGE evidence must have NaN branch values."
            )
    elif status in {
        RelatedFrequencyEvidenceStatus.INSUFFICIENT_SEARCH_BINS,
        RelatedFrequencyEvidenceStatus.INVALID_RELATED_FREQUENCY_MAGNITUDE,
    }:
        if not math.isfinite(target) or not _all_nan(
            peak_hz,
            peak_magnitude,
            offset_hz,
            ratio_db,
        ):
            raise RidgeConfigurationError(
                "Failed in-range related-frequency evidence must retain only its target."
            )
    elif status is RelatedFrequencyEvidenceStatus.INPUT_MISMATCH:
        if not _all_nan(*values):
            raise RidgeConfigurationError(
                "INPUT_MISMATCH evidence must have NaN branch values."
            )
    else:
        raise RidgeConfigurationError(
            "REFINED candidate frame has an incompatible related-frequency status."
        )


def _all_nan(*values: float) -> bool:
    return all(math.isnan(float(value)) for value in values)


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
