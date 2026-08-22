"""Immutable research models for first-order global candidate-path tracking."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import RidgeRefinementStatus

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class GlobalPathConfig:
    """Serializable, development-only parameters for TASK-021A.

    Candidate separation and background exclusion default to physical scales
    derived from the STFT window resolution ``sample_rate / window_length``.
    All costs are dimensionless; every frequency parameter is in Hz.
    """

    top_k: int = 5
    minimum_candidate_separation_hz: float | None = None
    candidate_separation_resolution_factor: float = 2.0
    background_exclusion_half_width_hz: float | None = None
    background_exclusion_resolution_factor: float = 2.0
    minimum_background_bin_count: int = 2
    background_contrast_weight: float = 1.5
    competitor_contrast_weight: float = 0.75
    cycles_weight: float = 0.5
    boundary_weight: float = 1.0
    refinement_failure_weight: float = 0.5
    background_reference_db: float = 10.0
    background_deficit_scale_db: float = 10.0
    competitor_reference_db: float = 0.0
    competitor_deficit_scale_db: float = 12.0
    target_cycles_in_window: float = 2.0
    frequency_step_scale_hz: float = 1.0e8
    continuity_weight: float = 1.0
    null_node_cost: float = 0.25
    null_stay_cost: float = 0.0
    ridge_entry_cost: float = 3.0
    ridge_exit_cost: float = 3.0

    DEVELOPMENT_STATUS: ClassVar[str] = "development / uncalibrated"

    def __post_init__(self) -> None:
        object.__setattr__(self, "top_k", _integer(self.top_k, "top_k", 1, 32))
        object.__setattr__(
            self,
            "minimum_background_bin_count",
            _integer(
                self.minimum_background_bin_count,
                "minimum_background_bin_count",
                1,
                None,
            ),
        )
        for field_name in (
            "candidate_separation_resolution_factor",
            "background_exclusion_resolution_factor",
            "background_deficit_scale_db",
            "competitor_deficit_scale_db",
            "target_cycles_in_window",
            "frequency_step_scale_hz",
        ):
            value = _finite_real(getattr(self, field_name), field_name)
            if value <= 0.0:
                raise RidgeConfigurationError(f"{field_name} must be strictly positive.")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "background_contrast_weight",
            "competitor_contrast_weight",
            "cycles_weight",
            "boundary_weight",
            "refinement_failure_weight",
            "continuity_weight",
            "null_node_cost",
            "null_stay_cost",
            "ridge_entry_cost",
            "ridge_exit_cost",
        ):
            value = _finite_real(getattr(self, field_name), field_name)
            if value < 0.0:
                raise RidgeConfigurationError(f"{field_name} must be non-negative.")
            object.__setattr__(self, field_name, value)
        for field_name in ("background_reference_db", "competitor_reference_db"):
            object.__setattr__(
                self,
                field_name,
                _finite_real(getattr(self, field_name), field_name),
            )
        for field_name in (
            "minimum_candidate_separation_hz",
            "background_exclusion_half_width_hz",
        ):
            raw_value = getattr(self, field_name)
            if raw_value is None:
                continue
            value = _finite_real(raw_value, field_name)
            if value <= 0.0:
                raise RidgeConfigurationError(
                    f"{field_name} must be strictly positive when supplied."
                )
            object.__setattr__(self, field_name, value)

    def to_metadata(self) -> dict[str, int | float | str | None]:
        """Return JSON-serializable parameter metadata."""
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
            if field_name != "DEVELOPMENT_STATUS"
        } | {"development_status": self.DEVELOPMENT_STATUS}


@dataclass(frozen=True, slots=True)
class RidgeCandidate:
    """One distinct in-band local spectral maximum in one STFT frame."""

    frame_index: int
    time_s: float
    candidate_rank: int
    discrete_bin_index: int
    discrete_frequency_hz: float
    refined_frequency_hz: float
    peak_amplitude: float
    peak_to_background_db: float
    peak_to_competitor_db: float
    cycles_in_window: float
    is_band_boundary: bool
    refinement_status: RidgeRefinementStatus

    def __post_init__(self) -> None:
        _integer(self.frame_index, "frame_index", 0, None)
        _integer(self.candidate_rank, "candidate_rank", 1, None)
        _integer(self.discrete_bin_index, "discrete_bin_index", 0, None)
        for field_name in (
            "time_s",
            "discrete_frequency_hz",
            "peak_amplitude",
            "cycles_in_window",
        ):
            value = _finite_real(getattr(self, field_name), field_name)
            if field_name != "time_s" and value < 0.0:
                raise RidgeConfigurationError(f"{field_name} must be non-negative.")
        for field_name in ("peak_to_background_db", "peak_to_competitor_db"):
            if math.isinf(float(getattr(self, field_name))):
                raise RidgeConfigurationError(f"{field_name} may be finite or NaN.")
        if not isinstance(self.is_band_boundary, bool):
            raise RidgeConfigurationError("is_band_boundary must be boolean.")
        if not isinstance(self.refinement_status, RidgeRefinementStatus):
            raise RidgeConfigurationError(
                "refinement_status must be a RidgeRefinementStatus."
            )
        if self.refinement_status is RidgeRefinementStatus.REFINED:
            _finite_real(self.refined_frequency_hz, "refined_frequency_hz")
        elif not math.isnan(self.refined_frequency_hz):
            raise RidgeConfigurationError(
                "Failed refinement must retain NaN refined_frequency_hz."
            )

    @property
    def transition_frequency_hz(self) -> float:
        """Use refined frequency when available, otherwise the discrete bin."""
        if math.isfinite(self.refined_frequency_hz):
            return self.refined_frequency_hz
        return self.discrete_frequency_hz


@dataclass(frozen=True, slots=True, eq=False)
class RidgeCandidateSet:
    """All auditable Top-K candidates for one single-channel STFT."""

    EXTRACTION_METHOD: ClassVar[str] = (
        "unsmoothed in-band local maxima including band endpoints; scipy plateau "
        "collapsing; descending-amplitude non-maximum suppression in Hz"
    )

    time_s: FloatArray
    candidates_by_frame: tuple[tuple[RidgeCandidate, ...], ...]
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    effective_candidate_separation_hz: float
    effective_background_exclusion_half_width_hz: float
    config: GlobalPathConfig
    source_path: Path | None
    extraction_method: str = EXTRACTION_METHOD

    def __post_init__(self) -> None:
        time_s = _float_array(self.time_s, "time_s")
        if time_s.ndim != 1 or time_s.size == 0:
            raise RidgeConfigurationError("time_s must be a non-empty 1-D array.")
        if not np.all(np.isfinite(time_s)) or (
            time_s.size > 1 and not np.all(np.diff(time_s) > 0.0)
        ):
            raise RidgeConfigurationError("time_s must be finite and increasing.")
        frames = tuple(tuple(frame) for frame in self.candidates_by_frame)
        if len(frames) != time_s.size:
            raise RidgeConfigurationError("candidates_by_frame must match time_s.")
        if not isinstance(self.config, GlobalPathConfig):
            raise RidgeConfigurationError("config must be a GlobalPathConfig.")
        for frame_index, frame in enumerate(frames):
            if len(frame) > self.config.top_k:
                raise RidgeConfigurationError("A frame exceeds configured top_k.")
            if tuple(item.candidate_rank for item in frame) != tuple(
                range(1, len(frame) + 1)
            ):
                raise RidgeConfigurationError("Candidate ranks must be consecutive.")
            if any(
                item.frame_index != frame_index
                or item.time_s != float(time_s[frame_index])
                for item in frame
            ):
                raise RidgeConfigurationError("Candidate frame provenance is inconsistent.")
        minimum = _finite_real(self.minimum_frequency_hz, "minimum_frequency_hz")
        maximum = _finite_real(self.maximum_frequency_hz, "maximum_frequency_hz")
        if minimum < 0.0 or maximum <= minimum:
            raise RidgeConfigurationError("Candidate search band is invalid.")
        separation = _finite_real(
            self.effective_candidate_separation_hz,
            "effective_candidate_separation_hz",
        )
        guard = _finite_real(
            self.effective_background_exclusion_half_width_hz,
            "effective_background_exclusion_half_width_hz",
        )
        if separation <= 0.0 or guard <= 0.0:
            raise RidgeConfigurationError("Effective Hz scales must be positive.")
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise RidgeConfigurationError("source_path must be pathlib.Path or None.")
        if self.extraction_method != self.EXTRACTION_METHOD:
            raise RidgeConfigurationError("Unexpected candidate extraction method.")
        object.__setattr__(self, "time_s", _immutable(time_s))
        object.__setattr__(self, "candidates_by_frame", frames)
        object.__setattr__(self, "minimum_frequency_hz", minimum)
        object.__setattr__(self, "maximum_frequency_hz", maximum)
        object.__setattr__(self, "effective_candidate_separation_hz", separation)
        object.__setattr__(self, "effective_background_exclusion_half_width_hz", guard)


@dataclass(frozen=True, slots=True, eq=False)
class GlobalRidgePathResult:
    """Unique globally minimum first-order path, retaining all candidates."""

    METHOD: ClassVar[str] = (
        "first-order dynamic programming over each frame's Top-K candidates plus "
        "NULL; quadratic Hz transition and exact predecessor backtracking"
    )
    NULL_RANK: ClassVar[int] = 0

    time_s: FloatArray
    selected_candidate_rank: IntArray
    selected_discrete_frequency_hz: FloatArray
    selected_refined_frequency_hz: FloatArray
    is_null: BoolArray
    node_cost: FloatArray
    transition_cost: FloatArray
    cumulative_cost: FloatArray
    total_path_cost: float
    candidate_set: RidgeCandidateSet
    config: GlobalPathConfig
    provenance: Mapping[str, str]
    method: str = METHOD

    def __post_init__(self) -> None:
        time_s = _float_array(self.time_s, "time_s")
        ranks = _int_array(self.selected_candidate_rank, "selected_candidate_rank")
        discrete = _float_array(
            self.selected_discrete_frequency_hz,
            "selected_discrete_frequency_hz",
        )
        refined = _float_array(
            self.selected_refined_frequency_hz,
            "selected_refined_frequency_hz",
        )
        null = _bool_array(self.is_null, "is_null")
        node = _float_array(self.node_cost, "node_cost")
        transition = _float_array(self.transition_cost, "transition_cost")
        cumulative = _float_array(self.cumulative_cost, "cumulative_cost")
        all_arrays: tuple[NDArray[np.generic], ...] = (
            time_s,
            ranks,
            discrete,
            refined,
            null,
            node,
            transition,
            cumulative,
        )
        if time_s.ndim != 1 or time_s.size == 0 or any(
            value.shape != time_s.shape for value in all_arrays
        ):
            raise RidgeConfigurationError("All path arrays must match non-empty time_s.")
        if not np.array_equal(time_s, self.candidate_set.time_s):
            raise RidgeConfigurationError("Path and candidate-set time axes must match.")
        if np.any(ranks < 0) or not np.array_equal(ranks == self.NULL_RANK, null):
            raise RidgeConfigurationError("NULL frames must use rank sentinel zero.")
        if np.any(~np.isnan(discrete[null])) or np.any(~np.isnan(refined[null])):
            raise RidgeConfigurationError("NULL frequencies must be NaN.")
        if np.any(~np.isfinite(discrete[~null])):
            raise RidgeConfigurationError("Selected candidates need finite discrete Hz.")
        cost_arrays = {
            "node_cost": node,
            "transition_cost": transition,
            "cumulative_cost": cumulative,
        }
        for name, value in cost_arrays.items():
            if np.any(~np.isfinite(value)) or np.any(value < 0.0):
                raise RidgeConfigurationError(f"{name} must be finite and non-negative.")
        total = _finite_real(self.total_path_cost, "total_path_cost")
        if total < 0.0 or not math.isclose(
            total,
            float(cumulative[-1]),
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise RidgeConfigurationError("total_path_cost must equal final cumulative cost.")
        if not isinstance(self.config, GlobalPathConfig) or self.config != self.candidate_set.config:
            raise RidgeConfigurationError("Path config must match candidate-set config.")
        if self.method != self.METHOD:
            raise RidgeConfigurationError("Unexpected global-path method.")
        provenance = dict(self.provenance)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in provenance.items()):
            raise RidgeConfigurationError("provenance must map strings to strings.")
        stored_arrays: dict[str, NDArray[np.generic]] = {
            "time_s": time_s,
            "selected_candidate_rank": ranks,
            "selected_discrete_frequency_hz": discrete,
            "selected_refined_frequency_hz": refined,
            "is_null": null,
            "node_cost": node,
            "transition_cost": transition,
            "cumulative_cost": cumulative,
        }
        for name, stored_value in stored_arrays.items():
            object.__setattr__(self, name, _immutable(stored_value))
        object.__setattr__(self, "total_path_cost", total)
        object.__setattr__(self, "provenance", MappingProxyType(provenance))


def _integer(value: object, name: str, minimum: int, maximum: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise RidgeConfigurationError(f"{name} must be an integer and cannot be bool.")
    converted = int(value)
    if converted < minimum or (maximum is not None and converted > maximum):
        raise RidgeConfigurationError(f"{name} lies outside its allowed range.")
    return converted


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RidgeConfigurationError(f"{name} must be a finite number.")
    converted = float(value)
    if not math.isfinite(converted):
        raise RidgeConfigurationError(f"{name} must be finite.")
    return converted


def _float_array(value: object, name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(f"{name} must be convertible to float64.") from exc


def _int_array(value: object, name: str) -> IntArray:
    try:
        array = np.asarray(value)
        if array.dtype.kind not in {"i", "u"}:
            raise TypeError
        return np.array(array, dtype=np.int64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(f"{name} must be an integer array.") from exc


def _bool_array(value: object, name: str) -> BoolArray:
    try:
        array = np.asarray(value)
        if array.dtype.kind != "b":
            raise TypeError
        return np.array(array, dtype=np.bool_, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(f"{name} must be a boolean array.") from exc


def _immutable(array: NDArray[np.generic]) -> NDArray[np.generic]:
    stored = np.frombuffer(array.tobytes(order="C"), dtype=array.dtype).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = [
    "GlobalPathConfig",
    "GlobalRidgePathResult",
    "RidgeCandidate",
    "RidgeCandidateSet",
]
