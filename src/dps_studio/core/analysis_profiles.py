"""Explicit immutable analysis profiles and daily output modes.

``BALANCED_PROFILE`` is the default.  It prioritizes plateau stability,
frequency-estimate stability, and noise robustness.  The explicit
``HIGH_TIME_RESOLUTION_PROFILE`` shortens the window support (12.8 ns for the
current 40 GHz dataset) at the cost of frequency stability and plateau
jitter. ``HIGH_FREQUENCY_RESOLUTION_PROFILE`` uses the repository's audited
1024-sample, fixed-hop configuration for longer time support and a narrower
window-limited frequency scale.  The two ``VERY_HIGH_*`` profiles extend that
same fixed-hop axis for experimental inspection only.  None is a
higher-accuracy claim.
Profiles are never selected or switched from signal contents.

Dataset-specific values such as wavelength, event start, and analysis end are
deliberately absent and must remain explicit run parameters.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Integral
from types import MappingProxyType
from typing import cast

import numpy as np

from dps_studio.core.models import SignalRecord


RIDGE_REFINEMENT_METHOD = "log_magnitude_three_point_quadratic"


class AnalysisProfileId(str, Enum):
    """Stable identifiers for user-selected analysis profiles."""

    BALANCED = "balanced"
    HIGH_TIME_RESOLUTION = "high_time_resolution"
    HIGH_FREQUENCY_RESOLUTION = "high_frequency_resolution"
    VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL = (
        "very_high_time_resolution_experimental"
    )
    VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL = (
        "very_high_frequency_resolution_experimental"
    )


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


@dataclass(frozen=True, slots=True)
class AnalysisParameterOverrides:
    """Explicit per-run scientific values layered over one formal profile.

    ``None`` means "use the immutable base value".  Dataset-specific vacuum
    wavelength is included in this per-run layer because it deliberately does
    not belong to a reusable :class:`AnalysisProfile`.
    """

    vacuum_wavelength_m: float | None = None
    window_length_samples: int | None = None
    overlap_samples: int | None = None
    nfft: int | None = None
    minimum_frequency_hz: float | None = None
    maximum_frequency_hz: float | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether every final value still comes from its base."""
        return all(
            value is None
            for value in (
                self.vacuum_wavelength_m,
                self.window_length_samples,
                self.overlap_samples,
                self.nfft,
                self.minimum_frequency_hz,
                self.maximum_frequency_hz,
            )
        )


@dataclass(frozen=True, slots=True)
class AnalysisRunParameters:
    """Immutable, validated final values and their preset provenance."""

    base_profile: AnalysisProfile
    base_vacuum_wavelength_m: float
    overrides: AnalysisParameterOverrides
    vacuum_wavelength_m: float
    window_name: str
    window_length_samples: int
    overlap_samples: int
    nfft: int
    minimum_frequency_hz: float
    maximum_frequency_hz: float

    @property
    def hop_samples(self) -> int:
        """Derive the only valid hop from window length and overlap."""
        return self.window_length_samples - self.overlap_samples

    @property
    def preset_name(self) -> str:
        """Return the immutable base preset name, even for a custom run."""
        return self.base_profile.display_name

    @property
    def preset_id(self) -> str:
        """Return the base identifier for an unchanged preset, else custom."""
        return "custom" if self.is_custom else self.base_profile.profile_id.value

    @property
    def is_custom(self) -> bool:
        """Return whether at least one final value explicitly overrides its base."""
        return not self.overrides.is_empty

    @property
    def custom_overrides(self) -> Mapping[str, int | float]:
        """Return immutable explicit override values for provenance/export."""
        values: dict[str, int | float] = {}
        for field_name in (
            "vacuum_wavelength_m",
            "window_length_samples",
            "overlap_samples",
            "nfft",
            "minimum_frequency_hz",
            "maximum_frequency_hz",
        ):
            value = getattr(self.overrides, field_name)
            if value is not None:
                values[field_name] = value
        return MappingProxyType(values)

    @property
    def provenance_name(self) -> str:
        """Return a stable descriptive name for downstream run metadata."""
        if self.is_custom:
            return f"custom_based_on_{self.base_profile.profile_id.value}"
        return self.base_profile.profile_id.value

    def validate_for_records(self, records: Mapping[str, SignalRecord]) -> None:
        """Validate data-dependent limits using the workflow's actual grids.

        Static profile rules are already enforced by
        :func:`build_analysis_run_parameters`.  This check adds only constraints
        that depend on loaded records: uniform sampling, sample count, the exact
        one-sided FFT grid (including odd ``nfft``), and the two-bin minimum used
        by the formal spectral-quality/detection stages.
        """
        if not isinstance(records, Mapping) or not records:
            raise TypeError("records must be a non-empty mapping of SignalRecord values.")
        for channel_name, record in records.items():
            if not isinstance(channel_name, str) or not channel_name:
                raise TypeError("Every records key must be a non-empty string.")
            if not isinstance(record, SignalRecord):
                raise TypeError(f"records[{channel_name!r}] must be a SignalRecord.")
            if not record.is_uniformly_sampled:
                raise ValueError(
                    f"records[{channel_name!r}] is not approximately uniformly sampled."
                )
            if self.window_length_samples > record.sample_count:
                raise ValueError(
                    "window_length_samples cannot exceed record.sample_count; "
                    f"got {self.window_length_samples} for channel "
                    f"{channel_name!r} with {record.sample_count} samples."
                )
            frequency_hz = np.fft.rfftfreq(
                self.nfft,
                d=1.0 / record.sample_rate_hz,
            )
            grid_maximum_hz = float(frequency_hz[-1])
            if self.maximum_frequency_hz > grid_maximum_hz:
                raise ValueError(
                    f"maximum_frequency_hz={self.maximum_frequency_hz!r} "
                    f"exceeds channel {channel_name!r} STFT/Nyquist-limited "
                    "maximum frequency "
                    f"{grid_maximum_hz!r} Hz."
                )
            band_bin_count = int(
                np.count_nonzero(
                    (frequency_hz >= self.minimum_frequency_hz)
                    & (frequency_hz <= self.maximum_frequency_hz)
                )
            )
            if band_bin_count < 2:
                raise ValueError(
                    "The closed search range must contain at least two STFT bins "
                    f"for channel {channel_name!r}; got {band_bin_count}."
                )


def build_analysis_run_parameters(
    *,
    base_profile: AnalysisProfile,
    base_vacuum_wavelength_m: float,
    overrides: AnalysisParameterOverrides | None = None,
) -> AnalysisRunParameters:
    """Resolve one immutable preset plus explicit overrides into final values.

    Validation is delegated to the existing :class:`AnalysisProfile`
    constructor, so custom runs obey the same formal window, hop, ``nfft``,
    window-function, and search-band constraints as built-in presets.
    """
    if not isinstance(base_profile, AnalysisProfile):
        raise TypeError("base_profile must be an AnalysisProfile.")
    if overrides is None:
        overrides = AnalysisParameterOverrides()
    elif not isinstance(overrides, AnalysisParameterOverrides):
        raise TypeError("overrides must be an AnalysisParameterOverrides or None.")

    base_wavelength = _finite_float(
        base_vacuum_wavelength_m,
        field_name="base_vacuum_wavelength_m",
    )
    if base_wavelength <= 0.0:
        raise ValueError("base_vacuum_wavelength_m must be strictly positive.")
    wavelength = (
        base_wavelength
        if overrides.vacuum_wavelength_m is None
        else _finite_float(
            overrides.vacuum_wavelength_m,
            field_name="vacuum_wavelength_m",
        )
    )
    if wavelength <= 0.0:
        raise ValueError("vacuum_wavelength_m must be strictly positive.")

    window_length = (
        base_profile.window_length_samples
        if overrides.window_length_samples is None
        else overrides.window_length_samples
    )
    overlap = (
        base_profile.overlap_samples
        if overrides.overlap_samples is None
        else overrides.overlap_samples
    )
    nfft = base_profile.nfft if overrides.nfft is None else overrides.nfft
    minimum_frequency = (
        base_profile.minimum_frequency_hz
        if overrides.minimum_frequency_hz is None
        else overrides.minimum_frequency_hz
    )
    maximum_frequency = (
        base_profile.maximum_frequency_hz
        if overrides.maximum_frequency_hz is None
        else overrides.maximum_frequency_hz
    )
    try:
        derived_hop = window_length - overlap
    except TypeError as exc:
        raise TypeError(
            "window_length_samples and overlap_samples must be integers."
        ) from exc
    validated = AnalysisProfile(
        profile_id=base_profile.profile_id,
        display_name=base_profile.display_name,
        window_name=base_profile.window_name,
        window_length_samples=window_length,
        overlap_samples=overlap,
        hop_samples=derived_hop,
        nfft=nfft,
        minimum_frequency_hz=minimum_frequency,
        maximum_frequency_hz=maximum_frequency,
        ridge_refinement=base_profile.ridge_refinement,
        tradeoff_note=base_profile.tradeoff_note,
    )
    normalized = AnalysisParameterOverrides(
        vacuum_wavelength_m=(
            None
            if _same_numeric_value(wavelength, base_wavelength)
            else wavelength
        ),
        window_length_samples=(
            None
            if validated.window_length_samples
            == base_profile.window_length_samples
            else validated.window_length_samples
        ),
        overlap_samples=(
            None
            if validated.overlap_samples == base_profile.overlap_samples
            else validated.overlap_samples
        ),
        nfft=(None if validated.nfft == base_profile.nfft else validated.nfft),
        minimum_frequency_hz=(
            None
            if _same_numeric_value(
                validated.minimum_frequency_hz,
                base_profile.minimum_frequency_hz,
            )
            else validated.minimum_frequency_hz
        ),
        maximum_frequency_hz=(
            None
            if _same_numeric_value(
                validated.maximum_frequency_hz,
                base_profile.maximum_frequency_hz,
            )
            else validated.maximum_frequency_hz
        ),
    )
    return AnalysisRunParameters(
        base_profile=base_profile,
        base_vacuum_wavelength_m=base_wavelength,
        overrides=normalized,
        vacuum_wavelength_m=(
            base_wavelength
            if normalized.vacuum_wavelength_m is None
            else normalized.vacuum_wavelength_m
        ),
        window_name=validated.window_name,
        window_length_samples=(
            base_profile.window_length_samples
            if normalized.window_length_samples is None
            else normalized.window_length_samples
        ),
        overlap_samples=(
            base_profile.overlap_samples
            if normalized.overlap_samples is None
            else normalized.overlap_samples
        ),
        nfft=(base_profile.nfft if normalized.nfft is None else normalized.nfft),
        minimum_frequency_hz=(
            base_profile.minimum_frequency_hz
            if normalized.minimum_frequency_hz is None
            else normalized.minimum_frequency_hz
        ),
        maximum_frequency_hz=(
            base_profile.maximum_frequency_hz
            if normalized.maximum_frequency_hz is None
            else normalized.maximum_frequency_hz
        ),
    )


def _same_numeric_value(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1.0e-12, abs_tol=0.0)


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

HIGH_FREQUENCY_RESOLUTION_PROFILE = AnalysisProfile(
    profile_id=AnalysisProfileId.HIGH_FREQUENCY_RESOLUTION,
    display_name="High frequency resolution",
    window_name="hann",
    window_length_samples=1024,
    overlap_samples=896,
    hop_samples=128,
    nfft=4096,
    minimum_frequency_hz=0.05e9,
    maximum_frequency_hz=2.0e9,
    ridge_refinement=RIDGE_REFINEMENT_METHOD,
    tradeoff_note=(
        "Longer time support and a narrower window-limited frequency scale at "
        "the cost of time localization; this is not a higher-accuracy claim."
    ),
)

VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE = AnalysisProfile(
    profile_id=AnalysisProfileId.VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL,
    display_name="Very High Time Resolution (Experimental)",
    window_name="hann",
    window_length_samples=256,
    overlap_samples=128,
    hop_samples=128,
    nfft=4096,
    minimum_frequency_hz=0.05e9,
    maximum_frequency_hz=2.0e9,
    ridge_refinement=RIDGE_REFINEMENT_METHOD,
    tradeoff_note=(
        "Experimental: shorter time support improves local time response but "
        "weakens finite-window frequency resolution."
    ),
)

VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE = AnalysisProfile(
    profile_id=AnalysisProfileId.VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL,
    display_name="Very High Frequency Resolution (Experimental)",
    window_name="hann",
    window_length_samples=2048,
    overlap_samples=1920,
    hop_samples=128,
    nfft=4096,
    minimum_frequency_hz=0.05e9,
    maximum_frequency_hz=2.0e9,
    ridge_refinement=RIDGE_REFINEMENT_METHOD,
    tradeoff_note=(
        "Experimental: longer time support improves finite-window frequency "
        "resolution but weakens fast-transient time localization."
    ),
)

DEFAULT_ANALYSIS_PROFILE = BALANCED_PROFILE
DEFAULT_OUTPUT_MODE = OutputMode.PRODUCTION

_PROFILES = {
    AnalysisProfileId.BALANCED: BALANCED_PROFILE,
    AnalysisProfileId.HIGH_TIME_RESOLUTION: HIGH_TIME_RESOLUTION_PROFILE,
    AnalysisProfileId.HIGH_FREQUENCY_RESOLUTION: (
        HIGH_FREQUENCY_RESOLUTION_PROFILE
    ),
    AnalysisProfileId.VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL: (
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE
    ),
    AnalysisProfileId.VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL: (
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE
    ),
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
    "AnalysisParameterOverrides",
    "AnalysisProfile",
    "AnalysisProfileId",
    "AnalysisRunParameters",
    "BALANCED_PROFILE",
    "DEFAULT_ANALYSIS_PROFILE",
    "DEFAULT_OUTPUT_MODE",
    "HIGH_TIME_RESOLUTION_PROFILE",
    "HIGH_FREQUENCY_RESOLUTION_PROFILE",
    "VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE",
    "VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE",
    "OutputMode",
    "build_analysis_run_parameters",
    "get_analysis_profile",
]
