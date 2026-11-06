"""The 768/128 Hann baseline used for pre-TASK-014 waveform replays."""
from dataclasses import replace

from dps_studio.core.analysis_profiles import BALANCED_PROFILE

ARCHIVED_BALANCED = replace(
    BALANCED_PROFILE, window_length_samples=768, overlap_samples=640, hop_samples=128,
)
