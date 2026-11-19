"""Pure scientific engine for the STFT vs M4 comparison."""
from .comparison import (
    classify_differences,
    compute_comparison_bundle,
    convert_frequency_for_display,
    inspect_frame_waveform,
)
from .engine import compute_b1_stft, compute_m4_phase_coherent, compute_matched_stft_25p6ns
from .models import (
    ComparisonCancelledError,
    DiffCategory,
    Estimate,
    InterestingRegion,
    LocalComparisonWaveform,
    SpectrogramMap,
    StftM4ComparisonBundle,
)

__all__ = [
    "ComparisonCancelledError", "DiffCategory", "Estimate", "InterestingRegion",
    "LocalComparisonWaveform", "SpectrogramMap", "StftM4ComparisonBundle", "classify_differences",
    "compute_b1_stft", "compute_comparison_bundle", "compute_m4_phase_coherent",
    "compute_matched_stft_25p6ns", "convert_frequency_for_display", "inspect_frame_waveform",
]
