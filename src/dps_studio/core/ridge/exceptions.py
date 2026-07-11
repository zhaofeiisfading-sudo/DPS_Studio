"""Exceptions raised by baseline ridge extraction operations."""

from dps_studio.core.models.exceptions import DPSStudioError


class RidgeError(DPSStudioError):
    """Base exception for ridge extraction errors."""


class RidgeConfigurationError(RidgeError):
    """Raised when ridge configuration or result data is invalid."""


class RidgeExtractionError(RidgeError):
    """Raised when ridge extraction fails for otherwise valid inputs."""
