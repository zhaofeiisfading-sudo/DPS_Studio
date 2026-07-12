"""Convert a non-negative baseline beat-frequency ridge to apparent velocity."""

from __future__ import annotations

import math
from typing import cast

import numpy as np

from dps_studio.core.physics.exceptions import (
    VelocityConfigurationError,
    VelocityConversionError,
)
from dps_studio.core.physics.models import ApparentVelocityResult, FloatArray
from dps_studio.core.ridge import RidgeResult


def convert_ridge_to_apparent_velocity(
    ridge_result: RidgeResult,
    *,
    vacuum_wavelength_m: float,
) -> ApparentVelocityResult:
    """Convert one ridge using normal-incidence reflection ``v = lambda*f/2``.

    This formula is limited to the explicitly configured normal-incidence,
    reflection-mode PDV geometry. The caller must provide the vacuum wavelength
    in SI metres; no wavelength or unit is guessed. The one-sided real-signal
    STFT supplies only non-negative beat frequencies, so the result is an unsigned
    magnitude and no sign or direction is inferred. No incidence-angle,
    refractive-index, LiF-window, or other correction is applied, and harmonic
    frequencies are not reinterpreted as independent physical velocities.
    """
    if not isinstance(ridge_result, RidgeResult):
        raise VelocityConfigurationError(
            "ridge_result must be a RidgeResult instance; "
            f"got {type(ridge_result).__name__}."
        )
    wavelength = _positive_finite_wavelength(vacuum_wavelength_m)

    finite_frequency = np.isfinite(ridge_result.frequency_hz)
    negative_frequency = np.flatnonzero(
        finite_frequency & (ridge_result.frequency_hz < 0.0)
    )
    if negative_frequency.size:
        index = int(negative_frequency[0])
        raise VelocityConfigurationError(
            "Finite RidgeResult candidate frequencies must be non-negative; "
            f"found a negative value at index {index}."
        )

    try:
        with np.errstate(over="raise", invalid="raise", under="ignore"):
            wavelength_array = np.float64(wavelength)
            larger_factor: FloatArray = np.maximum(
                ridge_result.frequency_hz,
                wavelength_array,
            )
            smaller_factor: FloatArray = np.minimum(
                ridge_result.frequency_hz,
                wavelength_array,
            )
            apparent_velocity_m_s: FloatArray = (
                larger_factor / np.float64(2.0)
            ) * smaller_factor
    except (FloatingPointError, OverflowError) as exc:
        raise VelocityConversionError(
            "Candidate apparent-velocity conversion overflowed for finite input data."
        ) from exc

    invalid_velocity = np.flatnonzero(
        finite_frequency & ~np.isfinite(apparent_velocity_m_s)
    )
    if invalid_velocity.size:
        index = int(invalid_velocity[0])
        raise VelocityConversionError(
            "A finite beat frequency produced a non-finite candidate apparent "
            f"velocity at index {index}."
        )
    negative_velocity = np.flatnonzero(
        np.isfinite(apparent_velocity_m_s) & (apparent_velocity_m_s < 0.0)
    )
    if negative_velocity.size:
        index = int(negative_velocity[0])
        raise VelocityConversionError(
            "Candidate apparent velocity must be non-negative; "
            f"found a negative result at index {index}."
        )
    if not np.array_equal(
        np.isnan(ridge_result.frequency_hz),
        np.isnan(apparent_velocity_m_s),
    ):
        raise VelocityConversionError(
            "Candidate apparent-velocity conversion did not preserve NaN positions."
        )

    return ApparentVelocityResult(
        time_s=ridge_result.time_s,
        beat_frequency_hz=ridge_result.frequency_hz,
        apparent_velocity_m_s=apparent_velocity_m_s,
        quality_flags=ridge_result.quality_flags,
        vacuum_wavelength_m=wavelength,
        conversion_model=ApparentVelocityResult.CONVERSION_MODEL,
        is_signed=False,
        source_path=ridge_result.source_path,
    )


def _positive_finite_wavelength(value: object) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise VelocityConfigurationError(
            "vacuum_wavelength_m must be a finite float greater than zero in SI metres."
        )
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise VelocityConfigurationError(
            "vacuum_wavelength_m must be a finite float greater than zero in SI metres."
        ) from exc
    if not math.isfinite(converted) or converted <= 0.0:
        raise VelocityConfigurationError(
            "vacuum_wavelength_m must be finite and strictly positive in SI metres."
        )
    return converted
