"""Exceptions raised while loading signal data from files."""

from dps_studio.core.models.exceptions import DPSStudioError


class SignalIOError(DPSStudioError):
    """Base exception for signal file input errors."""


class SignalFileNotFoundError(SignalIOError):
    """Raised when a requested signal file does not exist."""


class SignalFileTypeError(SignalIOError):
    """Raised when a requested signal path is not a regular file."""


class SignalEncodingError(SignalIOError):
    """Raised when signal text cannot be decoded with the requested encoding."""


class SignalParseError(SignalIOError):
    """Raised when a signal file contains invalid text or CSV structure."""


class SignalColumnError(SignalIOError):
    """Raised when signal columns are missing or structurally inconsistent."""


class SignalConfigurationError(SignalIOError):
    """Raised when signal reader configuration is invalid."""
