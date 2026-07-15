"""Immutable per-frame spectral-quality results for a selected ridge peak."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Integral
from pathlib import Path
from typing import ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import (
    RidgeQualityFlag,
    RidgeRefinementStatus,
)


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


class RidgeSpectralQualityStatus(str, Enum):
    """Per-frame outcome of spectral-quality assessment."""

    PRE_EVENT = "pre_event"
    OUTSIDE_ANALYSIS_WINDOW = "outside_analysis_window"
    ASSESSED = "assessed"
    INSUFFICIENT_BACKGROUND_BINS = "insufficient_background_bins"
    INVALID_PEAK_MAGNITUDE = "invalid_peak_magnitude"
    INVALID_BACKGROUND = "invalid_background"
    INVALID_COMPETITOR = "invalid_competitor"
    INPUT_MISMATCH = "input_mismatch"


@dataclass(frozen=True, slots=True, eq=False)
class RidgeSpectralQualityResult:
    """Immutable spectral contrast evidence on the complete STFT time axis."""

    ASSESSMENT_METHOD: ClassVar[str] = (
        "discrete peak magnitude compared with the median and maximum magnitudes "
        "outside an inclusive frequency guard in the closed ridge search band; "
        "20*log10 magnitude ratios; no thresholds or physical-accuracy claim"
    )

    time_s: FloatArray
    discrete_frequency_hz: FloatArray
    refined_frequency_hz: FloatArray
    discrete_frequency_bin_index: IntArray
    peak_magnitude: FloatArray
    background_median_magnitude: FloatArray
    strongest_competitor_magnitude: FloatArray
    peak_to_background_db: FloatArray
    peak_to_competitor_db: FloatArray
    background_bin_count: IntArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    refinement_statuses: tuple[RidgeRefinementStatus, ...]
    assessment_statuses: tuple[RidgeSpectralQualityStatus, ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    event_start_time_s: float | None
    analysis_end_time_s: float | None
    background_exclusion_half_width_hz: float
    minimum_background_bin_count: int
    assessment_method: str
    source_path: Path | None

    def __post_init__(self) -> None:
        """Validate invariants and detach every array into immutable bytes."""
        float_arrays = {
            "time_s": _as_float64_array(self.time_s, field_name="time_s"),
            "discrete_frequency_hz": _as_float64_array(
                self.discrete_frequency_hz,
                field_name="discrete_frequency_hz",
            ),
            "refined_frequency_hz": _as_float64_array(
                self.refined_frequency_hz,
                field_name="refined_frequency_hz",
            ),
            "peak_magnitude": _as_float64_array(
                self.peak_magnitude,
                field_name="peak_magnitude",
            ),
            "background_median_magnitude": _as_float64_array(
                self.background_median_magnitude,
                field_name="background_median_magnitude",
            ),
            "strongest_competitor_magnitude": _as_float64_array(
                self.strongest_competitor_magnitude,
                field_name="strongest_competitor_magnitude",
            ),
            "peak_to_background_db": _as_float64_array(
                self.peak_to_background_db,
                field_name="peak_to_background_db",
            ),
            "peak_to_competitor_db": _as_float64_array(
                self.peak_to_competitor_db,
                field_name="peak_to_competitor_db",
            ),
        }
        int_arrays = {
            "discrete_frequency_bin_index": _as_int64_array(
                self.discrete_frequency_bin_index,
                field_name="discrete_frequency_bin_index",
            ),
            "background_bin_count": _as_int64_array(
                self.background_bin_count,
                field_name="background_bin_count",
            ),
        }
        try:
            quality_flags = tuple(self.quality_flags)
            refinement_statuses = tuple(self.refinement_statuses)
            assessment_statuses = tuple(self.assessment_statuses)
        except TypeError as exc:
            raise RidgeConfigurationError(
                "quality_flags, refinement_statuses, and assessment_statuses "
                "must be iterable."
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
        exclusion_half_width_hz = _finite_float(
            self.background_exclusion_half_width_hz,
            field_name="background_exclusion_half_width_hz",
        )
        minimum_background_bin_count = _positive_integer(
            self.minimum_background_bin_count,
            field_name="minimum_background_bin_count",
        )

        for field_name, array in (*float_arrays.items(), *int_arrays.items()):
            if array.ndim != 1:
                raise RidgeConfigurationError(
                    f"{field_name} must be one-dimensional; got shape {array.shape}."
                )
        time_s = float_arrays["time_s"]
        if time_s.size == 0:
            raise RidgeConfigurationError("time_s must contain at least one value.")
        if any(array.size != time_s.size for array in float_arrays.values()) or any(
            array.size != time_s.size for array in int_arrays.values()
        ):
            raise RidgeConfigurationError(
                "All spectral-quality arrays must have the same length as time_s."
            )
        if not (
            len(quality_flags)
            == len(refinement_statuses)
            == len(assessment_statuses)
            == time_s.size
        ):
            raise RidgeConfigurationError(
                "All status sequences must have the same length as time_s."
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
        if not all(
            isinstance(status, RidgeSpectralQualityStatus)
            for status in assessment_statuses
        ):
            raise RidgeConfigurationError(
                "assessment_statuses must contain only RidgeSpectralQualityStatus values."
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
        if exclusion_half_width_hz <= 0.0:
            raise RidgeConfigurationError(
                "background_exclusion_half_width_hz must be greater than zero."
            )
        if self.assessment_method != self.ASSESSMENT_METHOD:
            raise RidgeConfigurationError(
                f"assessment_method must be {self.ASSESSMENT_METHOD!r}."
            )
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be pathlib.Path or None.")

        _validate_frame_values(
            float_arrays=float_arrays,
            int_arrays=int_arrays,
            quality_flags=quality_flags,
            refinement_statuses=refinement_statuses,
            assessment_statuses=assessment_statuses,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
            minimum_background_bin_count=minimum_background_bin_count,
        )

        for field_name, array in float_arrays.items():
            object.__setattr__(self, field_name, _store_float64_immutable(array))
        for field_name, array in int_arrays.items():
            object.__setattr__(self, field_name, _store_int64_immutable(array))
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "refinement_statuses", refinement_statuses)
        object.__setattr__(self, "assessment_statuses", assessment_statuses)
        object.__setattr__(self, "minimum_frequency_hz", minimum_frequency_hz)
        object.__setattr__(self, "maximum_frequency_hz", maximum_frequency_hz)
        object.__setattr__(self, "event_start_time_s", event_start_time_s)
        object.__setattr__(self, "analysis_end_time_s", analysis_end_time_s)
        object.__setattr__(
            self,
            "background_exclusion_half_width_hz",
            exclusion_half_width_hz,
        )
        object.__setattr__(
            self,
            "minimum_background_bin_count",
            minimum_background_bin_count,
        )


def _validate_frame_values(
    *,
    float_arrays: dict[str, FloatArray],
    int_arrays: dict[str, IntArray],
    quality_flags: tuple[RidgeQualityFlag, ...],
    refinement_statuses: tuple[RidgeRefinementStatus, ...],
    assessment_statuses: tuple[RidgeSpectralQualityStatus, ...],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    minimum_background_bin_count: int,
) -> None:
    discrete = float_arrays["discrete_frequency_hz"]
    refined = float_arrays["refined_frequency_hz"]
    peak = float_arrays["peak_magnitude"]
    background = float_arrays["background_median_magnitude"]
    competitor = float_arrays["strongest_competitor_magnitude"]
    peak_to_background = float_arrays["peak_to_background_db"]
    peak_to_competitor = float_arrays["peak_to_competitor_db"]
    bin_indices = int_arrays["discrete_frequency_bin_index"]
    background_counts = int_arrays["background_bin_count"]

    for index, (flag, refinement_status, assessment_status) in enumerate(
        zip(quality_flags, refinement_statuses, assessment_statuses)
    ):
        quality_values = (
            peak[index],
            background[index],
            competitor[index],
            peak_to_background[index],
            peak_to_competitor[index],
        )
        if flag is RidgeQualityFlag.PRE_EVENT:
            if (
                refinement_status is not RidgeRefinementStatus.PRE_EVENT
                or assessment_status is not RidgeSpectralQualityStatus.PRE_EVENT
            ):
                raise RidgeConfigurationError(
                    "PRE_EVENT frames must retain matching refinement and assessment statuses."
                )
            _require_masked_frame(
                discrete=float(discrete[index]),
                refined=float(refined[index]),
                bin_index=int(bin_indices[index]),
                background_count=int(background_counts[index]),
                quality_values=quality_values,
            )
            continue
        if flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            if (
                refinement_status
                is not RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
                or assessment_status
                is not RidgeSpectralQualityStatus.OUTSIDE_ANALYSIS_WINDOW
            ):
                raise RidgeConfigurationError(
                    "OUTSIDE frames must retain matching refinement and assessment statuses."
                )
            _require_masked_frame(
                discrete=float(discrete[index]),
                refined=float(refined[index]),
                bin_index=int(bin_indices[index]),
                background_count=int(background_counts[index]),
                quality_values=quality_values,
            )
            continue

        discrete_value = float(discrete[index])
        refined_value = float(refined[index])
        bin_index = int(bin_indices[index])
        background_count = int(background_counts[index])
        if (
            not math.isfinite(discrete_value)
            or not minimum_frequency_hz <= discrete_value <= maximum_frequency_hz
            or bin_index < 0
            or background_count < 0
        ):
            raise RidgeConfigurationError(
                "CANDIDATE frames must retain a finite in-band discrete frequency, "
                "a non-negative bin index, and a non-negative background count."
            )
        if refinement_status is RidgeRefinementStatus.REFINED:
            if (
                not math.isfinite(refined_value)
                or not minimum_frequency_hz <= refined_value <= maximum_frequency_hz
            ):
                raise RidgeConfigurationError(
                    "REFINED candidate frames must retain a finite in-band frequency."
                )
        elif not math.isnan(refined_value):
            raise RidgeConfigurationError(
                "Unavailable candidate refinements must retain NaN refined frequency."
            )
        if refinement_status in {
            RidgeRefinementStatus.PRE_EVENT,
            RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW,
        }:
            raise RidgeConfigurationError(
                "CANDIDATE frames cannot use masked refinement statuses."
            )

        peak_value = float(peak[index])
        background_value = float(background[index])
        competitor_value = float(competitor[index])
        peak_to_background_value = float(peak_to_background[index])
        peak_to_competitor_value = float(peak_to_competitor[index])
        if assessment_status is RidgeSpectralQualityStatus.ASSESSED:
            if background_count < minimum_background_bin_count or not all(
                math.isfinite(value) and value > 0.0
                for value in (peak_value, background_value, competitor_value)
            ):
                raise RidgeConfigurationError(
                    "ASSESSED frames require enough background bins and positive finite "
                    "peak, background, and competitor magnitudes."
                )
            if not math.isfinite(peak_to_background_value) or not math.isfinite(
                peak_to_competitor_value
            ):
                raise RidgeConfigurationError(
                    "ASSESSED contrast values must be finite."
                )
        elif (
            assessment_status
            is RidgeSpectralQualityStatus.INSUFFICIENT_BACKGROUND_BINS
        ):
            if (
                background_count >= minimum_background_bin_count
                or not math.isfinite(peak_value)
                or peak_value <= 0.0
                or not _all_nan(
                    background_value,
                    competitor_value,
                    peak_to_background_value,
                    peak_to_competitor_value,
                )
            ):
                raise RidgeConfigurationError(
                    "INSUFFICIENT_BACKGROUND_BINS frames must retain only a valid peak "
                    "and a below-minimum background count."
                )
        elif assessment_status is RidgeSpectralQualityStatus.INVALID_PEAK_MAGNITUDE:
            if not _all_nan(*quality_values):
                raise RidgeConfigurationError(
                    "INVALID_PEAK_MAGNITUDE frames must have NaN quality values."
                )
        elif assessment_status is RidgeSpectralQualityStatus.INVALID_BACKGROUND:
            if (
                background_count < minimum_background_bin_count
                or not math.isfinite(peak_value)
                or peak_value <= 0.0
                or not math.isnan(background_value)
                or not math.isnan(peak_to_background_value)
            ):
                raise RidgeConfigurationError(
                    "INVALID_BACKGROUND frames must retain a valid peak and NaN "
                    "background contrast."
                )
            _validate_optional_competitor_pair(
                competitor_value,
                peak_to_competitor_value,
            )
        elif assessment_status is RidgeSpectralQualityStatus.INVALID_COMPETITOR:
            if (
                background_count < minimum_background_bin_count
                or not all(
                    math.isfinite(value) and value > 0.0
                    for value in (peak_value, background_value)
                )
                or not math.isfinite(peak_to_background_value)
                or not math.isnan(competitor_value)
                or not math.isnan(peak_to_competitor_value)
            ):
                raise RidgeConfigurationError(
                    "INVALID_COMPETITOR frames must retain valid peak/background evidence "
                    "and NaN competitor evidence."
                )
        elif assessment_status is RidgeSpectralQualityStatus.INPUT_MISMATCH:
            if not _all_nan(*quality_values):
                raise RidgeConfigurationError(
                    "INPUT_MISMATCH frames must have NaN quality values."
                )
        else:
            raise RidgeConfigurationError(
                "CANDIDATE frames cannot use masked assessment statuses."
            )


def _require_masked_frame(
    *,
    discrete: float,
    refined: float,
    bin_index: int,
    background_count: int,
    quality_values: tuple[np.float64, ...],
) -> None:
    if (
        bin_index != -1
        or background_count != -1
        or not math.isnan(discrete)
        or not math.isnan(refined)
        or not _all_nan(*(float(value) for value in quality_values))
    ):
        raise RidgeConfigurationError(
            "Masked frames must have bin/count -1 and NaN spectral-quality values."
        )


def _validate_optional_competitor_pair(
    competitor_magnitude: float,
    peak_to_competitor_db: float,
) -> None:
    both_nan = math.isnan(competitor_magnitude) and math.isnan(peak_to_competitor_db)
    both_valid = (
        math.isfinite(competitor_magnitude)
        and competitor_magnitude > 0.0
        and math.isfinite(peak_to_competitor_db)
    )
    if not both_nan and not both_valid:
        raise RidgeConfigurationError(
            "Competitor magnitude and contrast must be either both valid or both NaN."
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


def _positive_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise RidgeConfigurationError(
            f"{field_name} must be a positive integer and cannot be bool."
        )
    converted = int(value)
    if converted <= 0:
        raise RidgeConfigurationError(f"{field_name} must be greater than zero.")
    return converted


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
