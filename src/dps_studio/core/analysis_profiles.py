"""Explicit immutable analysis profiles and daily output modes.

``BALANCED_PROFILE`` is the default.  It prioritizes plateau stability,
frequency-estimate stability, and noise robustness.  The explicit
``HIGH_TIME_RESOLUTION_PROFILE`` shortens the window support (12.8 ns for the
current 40 GHz dataset) at the cost of frequency stability and plateau
jitter; it is not a higher-accuracy claim.  Profiles are never selected or
switched from signal contents.

Dataset-specific values such as wavelength, event start, and analysis end are
deliberately absent and must remain explicit run parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Integral
from typing import cast


RIDGE_REFINEMENT_METHOD = "log_magnitude_three_point_quadratic"


class AnalysisProfileId(str, Enum):
    """Stable identifiers for user-selected analysis profiles."""

    BALANCED = "balanced"
    HIGH_TIME_RESOLUTION = "high_time_resolution"


class OutputMode(str, Enum):
    """Explicit daily output modes; production is the default."""

    PRODUCTION = "production"
    DIAGNOSTIC = "diagnostic"


def _strict_integer(value: object, *, field_name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{field_name} must be an integer and cannot be bool.")
    converted = int(value)
    if converted < minimum:
        raise ValueError(f"{field_name} must be greater than or equal to {minimum}.")
    return converted


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a finite float and cannot be bool.")
    try:
        converted = float(cast("float | str", value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be convertible to float.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} must be finite.")
    return converted


@dataclass(frozen=True, slots=True, eq=False)
class AnalysisProfile:
    """Validated numerical configuration with no paths or presentation state."""

    profile_id: AnalysisProfileId
    display_name: str
    window_name: str
    window_length_samples: int
    overlap_samples: int
    hop_samples: int
    nfft: int
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    ridge_refinement: str
    tradeoff_note: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, AnalysisProfileId):
            raise TypeError("profile_id must be an AnalysisProfileId.")
        for field_name in ("display_name", "window_name", "tradeoff_note"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")
        if self.window_name != "hann":
            raise ValueError("window_name must be 'hann' for the formal profiles.")

        window_length = _strict_integer(
            self.window_length_samples,
            field_name="window_length_samples",
            minimum=2,
        )
        overlap = _strict_integer(
            self.overlap_samples,
            field_name="overlap_samples",
            minimum=0,
        )
        hop = _strict_integer(
            self.hop_samples,
            field_name="hop_samples",
            minimum=1,
        )
        nfft = _strict_integer(self.nfft, field_name="nfft", minimum=window_length)
        if overlap >= window_length:
            raise ValueError("overlap_samples must be smaller than window_length_samples.")
        if hop != window_length - overlap:
            raise ValueError(
                "hop_samples must equal window_length_samples - overlap_samples."
            )
        minimum_frequency = _finite_float(
            self.minimum_frequency_hz,
            field_name="minimum_frequency_hz",
        )
        maximum_frequency = _finite_float(
            self.maximum_frequency_hz,
            field_name="maximum_frequency_hz",
        )
        if minimum_frequency < 0.0:
            raise ValueError("minimum_frequency_hz must be non-negative.")
        if maximum_frequency <= minimum_frequency:
            raise ValueError(
                "maximum_frequency_hz must be greater than minimum_frequency_hz."
            )
        if self.ridge_refinement != RIDGE_REFINEMENT_METHOD:
            raise ValueError(
                f"ridge_refinement must be {RIDGE_REFINEMENT_METHOD!r}."
            )

        object.__setattr__(self, "window_length_samples", window_length)
        object.__setattr__(self, "overlap_samples", overlap)
        object.__setattr__(self, "hop_samples", hop)
        object.__setattr__(self, "nfft", nfft)
        object.__setattr__(self, "minimum_frequency_hz", minimum_frequency)
        object.__setattr__(self, "maximum_frequency_hz", maximum_frequency)


BALANCED_PROFILE = AnalysisProfile(
    profile_id=AnalysisProfileId.BALANCED,
    display_name="Balanced",
    window_name="hann",
    window_length_samples=768,
    overlap_samples=640,
    hop_samples=128,
    nfft=4096,
    minimum_frequency_hz=0.05e9,
    maximum_frequency_hz=2.0e9,
    ridge_refinement=RIDGE_REFINEMENT_METHOD,
    tradeoff_note=(
        "Default profile prioritizing plateau stability, frequency-estimate "
        "stability, and noise robustness."
    ),
)

HIGH_TIME_RESOLUTION_PROFILE = AnalysisProfile(
    profile_id=AnalysisProfileId.HIGH_TIME_RESOLUTION,
    display_name="High time resolution",
    window_name="hann",
    window_length_samples=512,
    overlap_samples=384,
    hop_samples=128,
    nfft=4096,
    minimum_frequency_hz=0.05e9,
    maximum_frequency_hz=2.0e9,
    ridge_refinement=RIDGE_REFINEMENT_METHOD,
    tradeoff_note=(
        "Shorter time support at the cost of frequency stability and plateau "
        "jitter; this is not a higher-accuracy claim."
    ),
)

DEFAULT_ANALYSIS_PROFILE = BALANCED_PROFILE
DEFAULT_OUTPUT_MODE = OutputMode.PRODUCTION

_PROFILES = {
    AnalysisProfileId.BALANCED: BALANCED_PROFILE,
    AnalysisProfileId.HIGH_TIME_RESOLUTION: HIGH_TIME_RESOLUTION_PROFILE,
}


def get_analysis_profile(
    profile_id: AnalysisProfileId | str,
) -> AnalysisProfile:
    """Return one explicit profile without inspecting any signal data."""
    if isinstance(profile_id, bool):
        raise TypeError("profile_id must be an AnalysisProfileId or string.")
    if isinstance(profile_id, AnalysisProfileId):
        identifier = profile_id
    elif isinstance(profile_id, str):
        try:
            identifier = AnalysisProfileId(profile_id)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in AnalysisProfileId)
            raise ValueError(
                f"Unknown analysis profile {profile_id!r}; expected one of: {allowed}."
            ) from exc
    else:
        raise TypeError("profile_id must be an AnalysisProfileId or string.")
    return _PROFILES[identifier]


__all__ = [
    "AnalysisProfile",
    "AnalysisProfileId",
    "BALANCED_PROFILE",
    "DEFAULT_ANALYSIS_PROFILE",
    "DEFAULT_OUTPUT_MODE",
    "HIGH_TIME_RESOLUTION_PROFILE",
    "OutputMode",
    "get_analysis_profile",
]
