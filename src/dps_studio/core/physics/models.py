"""Immutable results for candidate apparent-velocity conversion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.physics.exceptions import VelocityConfigurationError
from dps_studio.core.ridge import RidgeQualityFlag


FloatArray = NDArray[np.float64]


class WindowMaterial(str, Enum):
    """Window choices with a formally implemented velocity correction."""

    NONE = "none"
    LIF = "LiF"


def _positive_model_parameter(value: object, *, field_name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise VelocityConfigurationError(
            f"{field_name} must be finite and strictly positive."
        )
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            f"{field_name} must be finite and strictly positive."
        ) from exc
    if not math.isfinite(converted) or converted <= 0.0:
        raise VelocityConfigurationError(
            f"{field_name} must be finite and strictly positive."
        )
    return converted


@dataclass(frozen=True, slots=True)
class LiFWindowCorrectionModel:
    """Validated Rigg et al. calibration for shocked [100] LiF at 1550 nm."""

    material: str = "LiF"
    model: str = "Rigg2014_Eq16"
    b1: float = 0.7895
    b2: float = 0.9918
    reference_wavelength_m: float = 1550.0e-9
    crystal_orientation: str = "[100]"
    paper_velocity_unit: str = "km/s"
    loading_context: str = "dynamic compression / calibrated window correction"
    source: str = "Rigg et al., Journal of Applied Physics 116, 033515 (2014)"
    source_doi: str = "10.1063/1.4890714"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "b1",
            _positive_model_parameter(self.b1, field_name="LiF b1"),
        )
        object.__setattr__(
            self,
            "b2",
            _positive_model_parameter(self.b2, field_name="LiF b2"),
        )
        object.__setattr__(
            self,
            "reference_wavelength_m",
            _positive_model_parameter(
                self.reference_wavelength_m,
                field_name="LiF reference_wavelength_m",
            ),
        )
        for field_name in (
            "material",
            "model",
            "crystal_orientation",
            "paper_velocity_unit",
            "loading_context",
            "source",
            "source_doi",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise VelocityConfigurationError(
                    f"LiF {field_name} must be non-empty text."
                )


LIF_RIGG_2014_1550NM = LiFWindowCorrectionModel()


@dataclass(frozen=True, slots=True)
class VelocityCorrectionConfig:
    """Formal SI configuration for separable angle and window corrections.

    ``measurement_angle_rad`` is the angle between the PDV measurement
    line-of-sight and the normal direction of interface motion.  It is the
    actual measurement geometry at the interface, not necessarily an external
    fibre mounting angle when a refracting transparent window is present.
    """

    window_material: WindowMaterial = WindowMaterial.LIF
    measurement_angle_rad: float = 0.0
    lif_model: LiFWindowCorrectionModel = LIF_RIGG_2014_1550NM

    def __post_init__(self) -> None:
        if not isinstance(self.window_material, WindowMaterial):
            raise VelocityConfigurationError(
                "window_material must be a supported WindowMaterial."
            )
        if not isinstance(self.lif_model, LiFWindowCorrectionModel):
            raise VelocityConfigurationError(
                "lif_model must be a LiFWindowCorrectionModel."
            )
        if isinstance(self.measurement_angle_rad, (bool, np.bool_)):
            raise VelocityConfigurationError(
                "measurement_angle_rad must be finite in [0, pi/2)."
            )
        try:
            angle = float(cast("float | str", self.measurement_angle_rad))
        except (TypeError, ValueError, OverflowError) as exc:
            raise VelocityConfigurationError(
                "measurement_angle_rad must be finite in [0, pi/2)."
            ) from exc
        if not math.isfinite(angle) or angle < 0.0 or angle >= math.pi / 2.0:
            raise VelocityConfigurationError(
                "measurement_angle_rad must be finite in [0, pi/2)."
            )
        object.__setattr__(self, "measurement_angle_rad", angle)

    @property
    def window_correction_enabled(self) -> bool:
        """Return whether a formal material correction is selected."""
        return self.window_material is not WindowMaterial.NONE


@dataclass(frozen=True, slots=True, eq=False)
class VelocityCorrectionResult:
    """Independent formal velocity layers on one shared time/frame axis."""

    apparent_velocity_m_s: FloatArray
    angle_corrected_apparent_velocity_m_s: FloatArray
    corrected_velocity_m_s: FloatArray
    config: VelocityCorrectionConfig
    vacuum_wavelength_m: float
    wavelength_matches_model_reference: bool
    wavelength_validation_message: str | None

    def __post_init__(self) -> None:
        apparent = _as_float64_array(
            self.apparent_velocity_m_s,
            field_name="apparent_velocity_m_s",
        )
        angle_corrected = _as_float64_array(
            self.angle_corrected_apparent_velocity_m_s,
            field_name="angle_corrected_apparent_velocity_m_s",
        )
        corrected = _as_float64_array(
            self.corrected_velocity_m_s,
            field_name="corrected_velocity_m_s",
        )
        if apparent.ndim != 1:
            raise VelocityConfigurationError(
                "Velocity correction arrays must be one-dimensional."
            )
        if angle_corrected.shape != apparent.shape or corrected.shape != apparent.shape:
            raise VelocityConfigurationError(
                "Velocity correction arrays must have identical shapes."
            )
        for field_name, values in (
            ("apparent_velocity_m_s", apparent),
            ("angle_corrected_apparent_velocity_m_s", angle_corrected),
            ("corrected_velocity_m_s", corrected),
        ):
            _validate_nonnegative_or_nan(values, field_name=field_name)
        apparent_nan = np.isnan(apparent)
        if not np.array_equal(apparent_nan, np.isnan(angle_corrected)) or not np.array_equal(
            apparent_nan,
            np.isnan(corrected),
        ):
            raise VelocityConfigurationError(
                "Every correction layer must preserve apparent-velocity NaN positions."
            )
        if not isinstance(self.config, VelocityCorrectionConfig):
            raise VelocityConfigurationError(
                "config must be a VelocityCorrectionConfig."
            )
        wavelength = _positive_finite_float(
            self.vacuum_wavelength_m,
            field_name="vacuum_wavelength_m",
        )
        if not isinstance(self.wavelength_matches_model_reference, bool):
            raise VelocityConfigurationError(
                "wavelength_matches_model_reference must be a boolean."
            )
        if self.wavelength_validation_message is not None and (
            not isinstance(self.wavelength_validation_message, str)
            or not self.wavelength_validation_message.strip()
        ):
            raise VelocityConfigurationError(
                "wavelength_validation_message must be non-empty text or None."
            )
        object.__setattr__(self, "apparent_velocity_m_s", _store_float64_immutable(apparent))
        object.__setattr__(
            self,
            "angle_corrected_apparent_velocity_m_s",
            _store_float64_immutable(angle_corrected),
        )
        object.__setattr__(
            self,
            "corrected_velocity_m_s",
            _store_float64_immutable(corrected),
        )
        object.__setattr__(self, "vacuum_wavelength_m", wavelength)


@dataclass(frozen=True, slots=True, eq=False)
class ApparentVelocityResult:
    """Unsigned candidate apparent velocity on the complete ridge time axis."""

    CONVERSION_MODEL: ClassVar[str] = "normal-incidence reflection PDV: v=lambda*f/2"

    time_s: FloatArray
    beat_frequency_hz: FloatArray
    apparent_velocity_m_s: FloatArray
    quality_flags: tuple[RidgeQualityFlag, ...]
    vacuum_wavelength_m: float
    conversion_model: str
    is_signed: bool
    source_path: Path | None

    def __post_init__(self) -> None:
        """Validate result invariants and detach arrays into immutable buffers."""
        time_s = _as_float64_array(self.time_s, field_name="time_s")
        beat_frequency_hz = _as_float64_array(
            self.beat_frequency_hz,
            field_name="beat_frequency_hz",
        )
        apparent_velocity_m_s = _as_float64_array(
            self.apparent_velocity_m_s,
            field_name="apparent_velocity_m_s",
        )
        try:
            quality_flags = tuple(self.quality_flags)
        except TypeError as exc:
            raise VelocityConfigurationError(
                "quality_flags must be an iterable of RidgeQualityFlag values."
            ) from exc
        vacuum_wavelength_m = _positive_finite_float(
            self.vacuum_wavelength_m,
            field_name="vacuum_wavelength_m",
        )

        for field_name, array in (
            ("time_s", time_s),
            ("beat_frequency_hz", beat_frequency_hz),
            ("apparent_velocity_m_s", apparent_velocity_m_s),
        ):
            if array.ndim != 1:
                raise VelocityConfigurationError(
                    f"{field_name} must be one-dimensional; got shape {array.shape}."
                )
        if time_s.size == 0:
            raise VelocityConfigurationError("time_s must contain at least one value.")
        if (
            beat_frequency_hz.size != time_s.size
            or apparent_velocity_m_s.size != time_s.size
        ):
            raise VelocityConfigurationError(
                "beat_frequency_hz and apparent_velocity_m_s must have the same "
                "length as time_s."
            )
        if len(quality_flags) != time_s.size:
            raise VelocityConfigurationError(
                "quality_flags must have the same length as time_s."
            )
        if not np.all(np.isfinite(time_s)):
            raise VelocityConfigurationError("time_s must contain only finite values.")
        if time_s.size > 1 and not np.all(np.diff(time_s) > 0.0):
            raise VelocityConfigurationError("time_s must be strictly increasing.")
        if not all(isinstance(flag, RidgeQualityFlag) for flag in quality_flags):
            raise VelocityConfigurationError(
                "quality_flags must contain only RidgeQualityFlag values."
            )

        _validate_nonnegative_or_nan(
            beat_frequency_hz,
            field_name="beat_frequency_hz",
        )
        _validate_nonnegative_or_nan(
            apparent_velocity_m_s,
            field_name="apparent_velocity_m_s",
        )
        if not np.array_equal(
            np.isnan(beat_frequency_hz),
            np.isnan(apparent_velocity_m_s),
        ):
            raise VelocityConfigurationError(
                "beat_frequency_hz and apparent_velocity_m_s must have NaN at "
                "the same positions."
            )
        _validate_quality_semantics(
            beat_frequency_hz=beat_frequency_hz,
            apparent_velocity_m_s=apparent_velocity_m_s,
            quality_flags=quality_flags,
        )

        if self.conversion_model != self.CONVERSION_MODEL:
            raise VelocityConfigurationError(
                f"conversion_model must be {self.CONVERSION_MODEL!r}."
            )
        if self.is_signed is not False:
            raise VelocityConfigurationError(
                "is_signed must be False because a one-sided ridge provides "
                "only unsigned magnitude."
            )
        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise VelocityConfigurationError("source_path must be pathlib.Path or None.")

        object.__setattr__(self, "time_s", _store_float64_immutable(time_s))
        object.__setattr__(
            self,
            "beat_frequency_hz",
            _store_float64_immutable(beat_frequency_hz),
        )
        object.__setattr__(
            self,
            "apparent_velocity_m_s",
            _store_float64_immutable(apparent_velocity_m_s),
        )
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "vacuum_wavelength_m", vacuum_wavelength_m)


def _as_float64_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            f"{field_name} could not be converted to a float64 array."
        ) from exc


def _positive_finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise VelocityConfigurationError(
            f"{field_name} must be a finite float greater than zero in SI metres."
        )
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            f"{field_name} must be a finite float greater than zero in SI metres."
        ) from exc
    if not math.isfinite(converted) or converted <= 0.0:
        raise VelocityConfigurationError(
            f"{field_name} must be finite and strictly positive in SI metres."
        )
    return converted


def _validate_nonnegative_or_nan(array: FloatArray, *, field_name: str) -> None:
    invalid_nonfinite = np.flatnonzero(~np.isfinite(array) & ~np.isnan(array))
    if invalid_nonfinite.size:
        index = int(invalid_nonfinite[0])
        raise VelocityConfigurationError(
            f"{field_name} may contain finite values or NaN, but not infinity; "
            f"found an invalid value at index {index}."
        )
    negative = np.flatnonzero(np.isfinite(array) & (array < 0.0))
    if negative.size:
        index = int(negative[0])
        raise VelocityConfigurationError(
            f"Finite {field_name} values must be non-negative; "
            f"found a negative value at index {index}."
        )


def _validate_quality_semantics(
    *,
    beat_frequency_hz: FloatArray,
    apparent_velocity_m_s: FloatArray,
    quality_flags: tuple[RidgeQualityFlag, ...],
) -> None:
    for index, flag in enumerate(quality_flags):
        frequency_is_finite = math.isfinite(float(beat_frequency_hz[index]))
        velocity_is_finite = math.isfinite(float(apparent_velocity_m_s[index]))
        if flag is RidgeQualityFlag.CANDIDATE:
            if not frequency_is_finite or not velocity_is_finite:
                raise VelocityConfigurationError(
                    "CANDIDATE frames must have finite beat frequency and "
                    "apparent velocity."
                )
        elif frequency_is_finite or velocity_is_finite:
            raise VelocityConfigurationError(
                "PRE_EVENT and OUTSIDE_ANALYSIS_WINDOW frames must retain NaN "
                "beat frequency and apparent velocity."
            )


def _store_float64_immutable(array: FloatArray) -> FloatArray:
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored
