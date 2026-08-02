"""Public formal workflow API with no GUI, plotting, or file-output dependency."""

from dps_studio.core.workflow.analysis import analyze_configuration, analyze_profile
from dps_studio.core.workflow.config import (
    AnalysisConfiguration,
    InputConfiguration,
    OutputConfiguration,
    PlotConfiguration,
    QualityConfiguration,
    WorkflowConfiguration,
    WorkflowConfigurationError,
    load_workflow_config,
)
from dps_studio.core.workflow.display import (
    PRE_EVENT_DISPLAY_ORIGIN,
    build_display_velocity,
    configure_channel_event_reference,
    configure_channel_display_velocity,
)
from dps_studio.core.workflow.models import ChannelAnalysis
from dps_studio.core.workflow.quality_parameters import (
    derive_background_exclusion_half_width_hz,
    derive_bin_guard_half_width_hz,
)

__all__ = [
    "AnalysisConfiguration",
    "ChannelAnalysis",
    "InputConfiguration",
    "OutputConfiguration",
    "PlotConfiguration",
    "QualityConfiguration",
    "WorkflowConfiguration",
    "WorkflowConfigurationError",
    "PRE_EVENT_DISPLAY_ORIGIN",
    "analyze_configuration",
    "analyze_profile",
    "build_display_velocity",
    "configure_channel_event_reference",
    "configure_channel_display_velocity",
    "derive_background_exclusion_half_width_hz",
    "derive_bin_guard_half_width_hz",
    "load_workflow_config",
]
