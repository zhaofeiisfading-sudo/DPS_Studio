"""Stable SciPy-compatible STFT window presets used by formal analysis."""

from __future__ import annotations

from enum import Enum

from dps_studio.core.time_frequency.exceptions import STFTConfigurationError


class STFTWindowName(str, Enum):
    """First formal non-parameterized STFT window preset set."""

    HANN = "hann"
    HAMMING = "hamming"
    BLACKMAN = "blackman"
    BLACKMAN_HARRIS = "blackmanharris"
    BOXCAR = "boxcar"


SUPPORTED_STFT_WINDOW_NAMES = tuple(item.value for item in STFTWindowName)


def validate_stft_window_name(value: object) -> str:
    """Return a stable preset name or reject it without a silent fallback."""
    if not isinstance(value, str) or not value.strip():
        raise STFTConfigurationError("window_name must be a non-empty string.")
    normalized = value.strip()
    if normalized not in SUPPORTED_STFT_WINDOW_NAMES:
        supported = ", ".join(SUPPORTED_STFT_WINDOW_NAMES)
        raise STFTConfigurationError(
            f"Unsupported formal STFT window_name {normalized!r}; "
            f"expected one of: {supported}."
        )
    return normalized


__all__ = [
    "STFTWindowName",
    "SUPPORTED_STFT_WINDOW_NAMES",
    "validate_stft_window_name",
]
