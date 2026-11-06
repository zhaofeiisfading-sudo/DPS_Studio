"""Manual gating and an extensible SI-unit estimator contract."""

from .models import BeatEstimate, EstimatorRequest, Segment, SegmentedResult, validate_plan
from .pool import AlgorithmPool, analyze_segments, default_pool

__all__ = ["AlgorithmPool", "BeatEstimate", "EstimatorRequest", "Segment",
           "SegmentedResult", "analyze_segments", "default_pool", "validate_plan"]
