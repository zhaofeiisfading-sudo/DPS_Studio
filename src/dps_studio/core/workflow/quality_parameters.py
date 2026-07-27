"""Shared spectral-quality parameter derivations."""

from __future__ import annotations

import math
from numbers import Integral, Real


def derive_background_exclusion_half_width_hz(
    *,
    sample_rate_hz: float,
    window_length_samples: int,
    window_scale: float,
) -> float:
    """Return ``window_scale * sample_rate / window_length`` in hertz.

    This is a configured diagnostic guard, not a universal or experimentally
    validated physical standard.
    """
    sample_rate = _positive_finite_float(
        sample_rate_hz,
        field_name="sample_rate_hz",
    )
    if (
        isinstance(window_length_samples, bool)
        or not isinstance(window_length_samples, Integral)
        or window_length_samples < 1
    ):
        raise ValueError("window_length_samples must be a positive integer.")
    scale = _positive_finite_float(window_scale, field_name="window_scale")
    return scale * sample_rate / int(window_length_samples)


def derive_bin_guard_half_width_hz(
    *,
    frequency_bin_spacing_hz: float,
    peak_exclusion_half_width_bins: int,
) -> float:
    """Convert an exact neighbor-bin guard to an inclusive hertz threshold.

    A half-bin offset ensures that a configured value of ``N`` excludes the
    peak bin and exactly ``N`` adjacent bins on either side of a uniform grid.
    """
    spacing = _positive_finite_float(
        frequency_bin_spacing_hz,
        field_name="frequency_bin_spacing_hz",
    )
    if (
        isinstance(peak_exclusion_half_width_bins, bool)
        or not isinstance(peak_exclusion_half_width_bins, Integral)
        or peak_exclusion_half_width_bins < 0
    ):
        raise ValueError(
            "peak_exclusion_half_width_bins must be a non-negative integer."
        )
    return (int(peak_exclusion_half_width_bins) + 0.5) * spacing


def _positive_finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite positive number.")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0.0:
        raise ValueError(f"{field_name} must be finite and strictly positive.")
    return converted


__all__ = [
    "derive_background_exclusion_half_width_hz",
    "derive_bin_guard_half_width_hz",
]
