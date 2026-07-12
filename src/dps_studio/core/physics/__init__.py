"""Public candidate apparent-velocity conversion APIs and errors."""

from dps_studio.core.physics.exceptions import (
    VelocityConfigurationError,
    VelocityConversionError,
    VelocityError,
)
from dps_studio.core.physics.models import ApparentVelocityResult
from dps_studio.core.physics.velocity import convert_ridge_to_apparent_velocity

__all__ = [
    "ApparentVelocityResult",
    "VelocityConfigurationError",
    "VelocityConversionError",
    "VelocityError",
    "convert_ridge_to_apparent_velocity",
]
