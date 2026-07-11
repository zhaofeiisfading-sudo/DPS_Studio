"""Exceptions raised by time-frequency analysis operations."""

from dps_studio.core.models.exceptions import DPSStudioError


class TimeFrequencyError(DPSStudioError):
    """Base exception for time-frequency analysis errors."""


class STFTConfigurationError(TimeFrequencyError):
    """Raised when STFT configuration or result metadata is invalid."""


class NonUniformSamplingError(TimeFrequencyError):
    """Raised when an STFT is requested for a non-uniformly sampled record."""


class STFTComputationError(TimeFrequencyError):
    """Raised when SciPy cannot compute an STFT for a valid configuration."""
