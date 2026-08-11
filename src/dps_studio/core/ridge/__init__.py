"""Public baseline and local sub-bin ridge APIs and errors."""

from dps_studio.core.ridge.exceptions import (
    RidgeConfigurationError,
    RidgeError,
    RidgeExtractionError,
)
from dps_studio.core.ridge.diagnostic_models import (
    RelatedFrequencyEvidenceResult,
    RelatedFrequencyEvidenceStatus,
    RidgeContinuityResult,
    RidgeContinuityStatus,
)
from dps_studio.core.ridge.continuity import assess_event_aware_ridge_continuity
from dps_studio.core.ridge.continuity_models import (
    EventAwareContinuityConfig,
    EventAwareContinuityResult,
)
from dps_studio.core.ridge.candidate_models import (
    LocalPeakCandidate,
    LocalPeakCandidateConfig,
    LocalPeakCandidateResult,
)
from dps_studio.core.ridge.candidates import extract_local_peak_candidates
from dps_studio.core.ridge.diagnostics import (
    assess_related_frequency_evidence,
    assess_ridge_continuity,
)
from dps_studio.core.ridge.guidance import (
    RidgeCorridorConstraint,
    validate_ridge_corridor_for_stft,
)
from dps_studio.core.ridge.models import (
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeResult,
)
from dps_studio.core.ridge.peak import extract_peak_ridge
from dps_studio.core.ridge.quality_models import (
    RidgeSpectralQualityResult,
    RidgeSpectralQualityStatus,
)
from dps_studio.core.ridge.refinement import (
    refine_peak_ridge_subbin,
    refine_three_point_log_magnitude,
)
from dps_studio.core.ridge.reselection import reselect_isolated_jump_candidates
from dps_studio.core.ridge.reselection_models import (
    CandidateReselectionEvidence,
    CandidateReselectionReason,
    ContinuityReselectionConfig,
    ExperimentalReselectionResult,
    ReselectionFrameStatus,
)
from dps_studio.core.ridge.selection import select_automatic_ridge
from dps_studio.core.ridge.selection_models import (
    AutomaticRidgeExtractionMode,
    AutomaticRidgeSelectionConfig,
    AutomaticRidgeSelectionResult,
    RidgeSelectionOrigin,
)
from dps_studio.core.ridge.spectral_quality import assess_ridge_spectral_quality

__all__ = [
    "RidgeConfigurationError",
    "RidgeError",
    "RidgeExtractionError",
    "RefinedRidgeResult",
    "EventAwareContinuityConfig",
    "EventAwareContinuityResult",
    "LocalPeakCandidate",
    "LocalPeakCandidateConfig",
    "LocalPeakCandidateResult",
    "CandidateReselectionEvidence",
    "CandidateReselectionReason",
    "ContinuityReselectionConfig",
    "ExperimentalReselectionResult",
    "ReselectionFrameStatus",
    "AutomaticRidgeExtractionMode",
    "AutomaticRidgeSelectionConfig",
    "AutomaticRidgeSelectionResult",
    "RidgeSelectionOrigin",
    "RelatedFrequencyEvidenceResult",
    "RelatedFrequencyEvidenceStatus",
    "RidgeContinuityResult",
    "RidgeContinuityStatus",
    "RidgeCorridorConstraint",
    "RidgeQualityFlag",
    "RidgeRefinementStatus",
    "RidgeResult",
    "RidgeSpectralQualityResult",
    "RidgeSpectralQualityStatus",
    "assess_related_frequency_evidence",
    "assess_event_aware_ridge_continuity",
    "assess_ridge_continuity",
    "assess_ridge_spectral_quality",
    "extract_local_peak_candidates",
    "extract_peak_ridge",
    "refine_peak_ridge_subbin",
    "refine_three_point_log_magnitude",
    "reselect_isolated_jump_candidates",
    "select_automatic_ridge",
    "validate_ridge_corridor_for_stft",
]
