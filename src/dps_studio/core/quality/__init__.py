"""Formal signal-existence quality gates with no GUI dependency."""

from dps_studio.core.quality.detection import detect_beat_signal
from dps_studio.core.quality.models import (
    SignalDetectionConfig,
    SignalDetectionResult,
    SignalState,
)

__all__ = [
    "SignalDetectionConfig",
    "SignalDetectionResult",
    "SignalState",
    "detect_beat_signal",
]
