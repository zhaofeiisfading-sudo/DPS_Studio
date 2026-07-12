"""Exceptions raised by apparent-velocity conversion operations."""

from dps_studio.core.models.exceptions import DPSStudioError


class VelocityError(DPSStudioError):
    """Base exception for apparent-velocity conversion errors."""


class VelocityConfigurationError(VelocityError):
    """Raised when velocity configuration or result data is invalid."""


class VelocityConversionError(VelocityError):
    """Raised when validated inputs cannot produce finite candidate velocities."""
