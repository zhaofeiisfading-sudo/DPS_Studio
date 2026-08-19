"""Public SI apparent-velocity conversion and correction APIs."""

from dps_studio.core.physics.corrections import (
    apply_velocity_corrections,
    correct_lif_window_velocity,
    correct_observation_angle,
    velocity_correction_metadata,
)

from dps_studio.core.physics.exceptions import (
    VelocityConfigurationError,
    VelocityConversionError,
    VelocityError,
)
from dps_studio.core.physics.models import (
    LIF_RIGG_2014_1550NM,
    ApparentVelocityResult,
    LiFWindowCorrectionModel,
    VelocityCorrectionConfig,
    VelocityCorrectionResult,
    WindowMaterial,
)
from dps_studio.core.physics.velocity import convert_ridge_to_apparent_velocity

__all__ = [
    "ApparentVelocityResult",
    "LIF_RIGG_2014_1550NM",
    "LiFWindowCorrectionModel",
    "VelocityCorrectionConfig",
    "VelocityConfigurationError",
    "VelocityCorrectionResult",
    "VelocityConversionError",
    "VelocityError",
    "WindowMaterial",
    "apply_velocity_corrections",
    "correct_lif_window_velocity",
    "correct_observation_angle",
    "convert_ridge_to_apparent_velocity",
    "velocity_correction_metadata",
]
