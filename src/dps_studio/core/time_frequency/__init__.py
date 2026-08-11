"""Public time-frequency analysis APIs and errors."""

from dps_studio.core.time_frequency.exceptions import (
    NonUniformSamplingError,
    STFTComputationError,
    STFTConfigurationError,
    TimeFrequencyError,
)
from dps_studio.core.time_frequency.models import STFTResult
from dps_studio.core.time_frequency.stft import compute_stft
from dps_studio.core.time_frequency.windows import (
    STFTWindowName,
    SUPPORTED_STFT_WINDOW_NAMES,
    validate_stft_window_name,
)

__all__ = [
    "NonUniformSamplingError",
    "STFTComputationError",
    "STFTConfigurationError",
    "STFTResult",
    "TimeFrequencyError",
    "compute_stft",
    "STFTWindowName",
    "SUPPORTED_STFT_WINDOW_NAMES",
    "validate_stft_window_name",
]
