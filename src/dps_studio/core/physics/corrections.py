"""Formal SI observation-angle and LiF window velocity corrections."""

from __future__ import annotations

import math
from typing import cast

import numpy as np

from dps_studio.core.physics.exceptions import (
    VelocityConfigurationError,
    VelocityConversionError,
)
from dps_studio.core.physics.models import (
    LIF_RIGG_2014_1550NM,
    FloatArray,
    VelocityCorrectionConfig,
    VelocityCorrectionResult,
    WindowMaterial,
)


_ANGLE_MODEL = "line_of_sight_projection"
_SEPARABLE_MODEL_NOTE = (
    "Rigg 2014 LiF calibration is fundamentally a normal-incidence/window "
    "calibration; a non-zero observation angle is treated as a separable "
    "geometrical correction, not a fully coupled refractive model."
)


def correct_observation_angle(
    apparent_velocity_m_s: object,
    *,
    measurement_angle_rad: float,
) -> FloatArray:
    """Recover normal velocity from its PDV line-of-sight projection.

    The SI relation is ``v_normal = v_measured / cos(theta)``.  ``theta`` is
    the angle between the measurement line-of-sight and the interface-motion
    normal.  NaN values are preserved without interpolation or filling.
    """
    values = _velocity_array(apparent_velocity_m_s)
    angle = _measurement_angle(measurement_angle_rad)
    if angle == 0.0:
        return values
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            corrected = np.asarray(values / math.cos(angle), dtype=np.float64)
    except (FloatingPointError, OverflowError) as exc:
        raise VelocityConversionError(
            "Observation-angle correction produced a non-finite value."
        ) from exc
    _validate_correction_output(values, corrected)
    return corrected


def correct_lif_window_velocity(apparent_velocity_m_s: object) -> FloatArray:
    """Apply Rigg et al. (2014) Eq. 16 for [100] LiF at 1550 nm.

    The paper coefficients are defined for velocities in mm/us, numerically
    equivalent to km/s.  This function accepts and returns SI m/s and performs
    the paper-unit conversion explicitly.  No static refractive-index factor is
    multiplied or divided in addition to Eq. 16.
    """
    values = _velocity_array(apparent_velocity_m_s)
    apparent_km_s = values / np.float64(1000.0)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            corrected_km_s = LIF_RIGG_2014_1550NM.b1 * np.power(
                apparent_km_s,
                LIF_RIGG_2014_1550NM.b2,
            )
            corrected = np.asarray(corrected_km_s * 1000.0, dtype=np.float64)
    except (FloatingPointError, OverflowError) as exc:
        raise VelocityConversionError(
            "LiF Rigg-2014 correction produced a non-finite value."
        ) from exc
    _validate_correction_output(values, corrected)
    return corrected


def apply_velocity_corrections(
    apparent_velocity_m_s: object,
    *,
    config: VelocityCorrectionConfig | None = None,
    vacuum_wavelength_m: float,
) -> VelocityCorrectionResult:
    """Apply angle first and the selected window model second.

    The combination is an explicit engineering approximation: angle projection
    and normal-incidence LiF calibration are treated as separable.  It is not a
    Snell-law or dynamically coupled oblique-window optical model.
    """
    resolved_config = VelocityCorrectionConfig() if config is None else config
    if not isinstance(resolved_config, VelocityCorrectionConfig):
        raise VelocityConfigurationError(
            "config must be a VelocityCorrectionConfig or None."
        )
    wavelength = _positive_wavelength(vacuum_wavelength_m)
    apparent = _velocity_array(apparent_velocity_m_s)
    angle_corrected = correct_observation_angle(
        apparent,
        measurement_angle_rad=resolved_config.measurement_angle_rad,
    )
    if resolved_config.window_material is WindowMaterial.LIF:
        corrected = correct_lif_window_velocity(angle_corrected)
        wavelength_matches = wavelength == LIF_RIGG_2014_1550NM.reference_wavelength_m
        warning = (
            None
            if wavelength_matches
            else (
                "Selected LiF model is calibrated at exactly 1550 nm; the current "
                f"vacuum wavelength is {wavelength * 1e9:.12g} nm and has not been "
                "validated by this model."
            )
        )
    elif resolved_config.window_material is WindowMaterial.NONE:
        corrected = angle_corrected.copy()
        wavelength_matches = True
        warning = None
    else:  # pragma: no cover - enum plus config validation make this defensive.
        raise VelocityConfigurationError(
            f"Unsupported window material: {resolved_config.window_material!r}."
        )
    return VelocityCorrectionResult(
        apparent_velocity_m_s=apparent,
        angle_corrected_apparent_velocity_m_s=angle_corrected,
        corrected_velocity_m_s=corrected,
        config=resolved_config,
        vacuum_wavelength_m=wavelength,
        wavelength_matches_model_reference=wavelength_matches,
        wavelength_validation_message=warning,
    )


def velocity_correction_metadata(
    result: VelocityCorrectionResult,
) -> dict[str, object]:
    """Return stable JSON-ready correction provenance for formal writers."""
    if not isinstance(result, VelocityCorrectionResult):
        raise TypeError("result must be a VelocityCorrectionResult.")
    config = result.config
    window: dict[str, object] = {
        "enabled": config.window_correction_enabled,
        "material": config.window_material.value,
        "model": None,
    }
    if config.window_material is WindowMaterial.LIF:
        model = LIF_RIGG_2014_1550NM
        window.update(
            {
                "model": model.model,
                "reference_wavelength_m": model.reference_wavelength_m,
                "crystal_orientation": model.crystal_orientation,
                "b1": model.b1,
                "b2": model.b2,
                "paper_velocity_unit": model.paper_velocity_unit,
                "loading_context": model.loading_context,
                "source": model.source,
                "source_doi": model.source_doi,
                "wavelength_matches_model_reference": (
                    result.wavelength_matches_model_reference
                ),
                "wavelength_validation_message": (
                    result.wavelength_validation_message
                ),
            }
        )
    return {
        "execution_order": [
            "apparent_velocity",
            "geometrical_angle_correction",
            "window_correction",
        ],
        "separable_model_note": _SEPARABLE_MODEL_NOTE,
        "angle": {
            "enabled": True,
            "angle_rad": config.measurement_angle_rad,
            "angle_deg_display": math.degrees(config.measurement_angle_rad),
            "model": _ANGLE_MODEL,
            "definition": (
                "angle between the PDV measurement line-of-sight and the normal "
                "direction of interface motion"
            ),
            "external_mounting_angle_may_differ_through_window": True,
            "snell_law_inference_applied": False,
            "source": (
                "Lea and Jardine, Review of Scientific Instruments 87, "
                "023101 (2016), Eq. 4"
            ),
            "source_doi": "10.1063/1.4940935",
        },
        "window": window,
    }


def _velocity_array(value: object) -> FloatArray:
    try:
        values = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            "apparent_velocity_m_s must be convertible to a float64 array."
        ) from exc
    if values.ndim != 1:
        raise VelocityConfigurationError(
            "apparent_velocity_m_s must be one-dimensional."
        )
    invalid = np.flatnonzero(~np.isfinite(values) & ~np.isnan(values))
    if invalid.size:
        raise VelocityConfigurationError(
            "apparent_velocity_m_s may contain finite values or NaN, but not infinity."
        )
    negative = np.flatnonzero(np.isfinite(values) & (values < 0.0))
    if negative.size:
        raise VelocityConfigurationError(
            "Finite apparent_velocity_m_s values must be non-negative."
        )
    return values


def _measurement_angle(value: object) -> float:
    try:
        return VelocityCorrectionConfig(
            window_material=WindowMaterial.NONE,
            measurement_angle_rad=cast("float", value),
        ).measurement_angle_rad
    except VelocityConfigurationError:
        raise


def _positive_wavelength(value: object) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise VelocityConfigurationError(
            "vacuum_wavelength_m must be finite and strictly positive."
        )
    try:
        wavelength = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            "vacuum_wavelength_m must be finite and strictly positive."
        ) from exc
    if not math.isfinite(wavelength) or wavelength <= 0.0:
        raise VelocityConfigurationError(
            "vacuum_wavelength_m must be finite and strictly positive."
        )
    return wavelength


def _validate_correction_output(source: FloatArray, corrected: FloatArray) -> None:
    if not np.array_equal(np.isnan(source), np.isnan(corrected)):
        raise VelocityConversionError("Velocity correction did not preserve NaN positions.")
    if np.any(np.isfinite(source) & ~np.isfinite(corrected)):
        raise VelocityConversionError(
            "A finite velocity produced a non-finite corrected velocity."
        )
    if np.any(np.isfinite(corrected) & (corrected < 0.0)):
        raise VelocityConversionError("Corrected velocity must be non-negative.")


__all__ = [
    "apply_velocity_corrections",
    "correct_lif_window_velocity",
    "correct_observation_angle",
    "velocity_correction_metadata",
]
