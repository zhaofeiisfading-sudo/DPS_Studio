"""Promote validated continuity alternatives into the formal Automatic ridge."""

from __future__ import annotations

import numpy as np

from dps_studio.core.ridge.candidate_models import LocalPeakCandidateResult
from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import (
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeResult,
)
from dps_studio.core.ridge.reselection_models import ExperimentalReselectionResult
from dps_studio.core.ridge.selection_models import (
    AutomaticRidgeSelectionConfig,
    AutomaticRidgeSelectionResult,
    RidgeSelectionOrigin,
)


def select_automatic_ridge(
    strongest_ridge: RidgeResult,
    strongest_refined: RefinedRidgeResult,
    *,
    candidates: LocalPeakCandidateResult | None,
    reselection: ExperimentalReselectionResult | None,
    config: AutomaticRidgeSelectionConfig,
    effective_recovery_tolerance_hz: float,
) -> tuple[RidgeResult, RefinedRidgeResult, AutomaticRidgeSelectionResult]:
    """Return formal ridge objects plus explicit frame-level provenance."""
    _validate_inputs(
        strongest_ridge,
        strongest_refined,
        candidates,
        reselection,
        config,
    )
    frame_count = strongest_refined.time_s.size
    origins = [RidgeSelectionOrigin.STRONGEST_PEAK] * frame_count
    ranks = np.fromiter(
        (
            1 if flag is RidgeQualityFlag.CANDIDATE else 0
            for flag in strongest_refined.quality_flags
        ),
        dtype=np.int64,
        count=frame_count,
    )
    if not config.reselection_is_active or candidates is None or reselection is None:
        selection = AutomaticRidgeSelectionResult(
            time_s=strongest_refined.time_s,
            origins=tuple(origins),
            selected_candidate_rank=ranks,
            config=config,
            effective_recovery_tolerance_hz=effective_recovery_tolerance_hz,
            method=AutomaticRidgeSelectionResult.METHOD,
        )
        return strongest_ridge, strongest_refined, selection

    discrete_frequency_hz = strongest_refined.discrete_frequency_hz.copy()
    refined_frequency_hz = strongest_refined.refined_frequency_hz.copy()
    bin_index = strongest_refined.discrete_frequency_bin_index.copy()
    bin_offset = strongest_refined.frequency_bin_offset.copy()
    peak_magnitude = strongest_refined.peak_magnitude.copy()
    refinement_statuses = list(strongest_refined.refinement_statuses)

    for frame_index in reselection.reselected_frame_indices:
        evidence = next(
            (
                item
                for item in reselection.evidence_by_frame[frame_index]
                if item.experimental_selected
            ),
            None,
        )
        if evidence is None:
            raise RidgeConfigurationError(
                "A reselected frame must retain selected candidate evidence."
            )
        candidate = next(
            (
                item
                for item in candidates.candidates_by_frame[frame_index]
                if item.amplitude_rank == evidence.candidate_rank
            ),
            None,
        )
        if candidate is None:
            raise RidgeConfigurationError(
                "Selected reselection evidence has no matching local candidate."
            )
        discrete_frequency_hz[frame_index] = candidate.discrete_frequency_hz
        refined_frequency_hz[frame_index] = candidate.refined_frequency_hz
        bin_index[frame_index] = candidate.bin_index
        bin_offset[frame_index] = candidate.frequency_bin_offset
        peak_magnitude[frame_index] = candidate.magnitude
        refinement_statuses[frame_index] = candidate.refinement_status
        ranks[frame_index] = candidate.amplitude_rank
        origins[frame_index] = (
            RidgeSelectionOrigin.CONTINUITY_ASSISTED_ALTERNATIVE
        )

    formal_ridge = RidgeResult(
        time_s=strongest_ridge.time_s,
        frequency_hz=discrete_frequency_hz,
        peak_magnitude=peak_magnitude,
        quality_flags=strongest_ridge.quality_flags,
        minimum_frequency_hz=strongest_ridge.minimum_frequency_hz,
        maximum_frequency_hz=strongest_ridge.maximum_frequency_hz,
        event_start_time_s=strongest_ridge.event_start_time_s,
        analysis_end_time_s=strongest_ridge.analysis_end_time_s,
        source_path=strongest_ridge.source_path,
    )
    formal_refined = RefinedRidgeResult(
        time_s=strongest_refined.time_s,
        discrete_frequency_hz=discrete_frequency_hz,
        refined_frequency_hz=refined_frequency_hz,
        discrete_frequency_bin_index=bin_index,
        frequency_bin_offset=bin_offset,
        peak_magnitude=peak_magnitude,
        quality_flags=strongest_refined.quality_flags,
        refinement_statuses=tuple(refinement_statuses),
        minimum_frequency_hz=strongest_refined.minimum_frequency_hz,
        maximum_frequency_hz=strongest_refined.maximum_frequency_hz,
        event_start_time_s=strongest_refined.event_start_time_s,
        analysis_end_time_s=strongest_refined.analysis_end_time_s,
        refinement_method=strongest_refined.refinement_method,
        source_path=strongest_refined.source_path,
    )
    selection = AutomaticRidgeSelectionResult(
        time_s=strongest_refined.time_s,
        origins=tuple(origins),
        selected_candidate_rank=ranks,
        config=config,
        effective_recovery_tolerance_hz=effective_recovery_tolerance_hz,
        method=AutomaticRidgeSelectionResult.METHOD,
    )
    return formal_ridge, formal_refined, selection


def _validate_inputs(
    ridge: object,
    refined: object,
    candidates: object,
    reselection: object,
    config: object,
) -> None:
    if not isinstance(ridge, RidgeResult):
        raise RidgeConfigurationError("strongest_ridge must be a RidgeResult.")
    if not isinstance(refined, RefinedRidgeResult):
        raise RidgeConfigurationError(
            "strongest_refined must be a RefinedRidgeResult."
        )
    if candidates is not None and not isinstance(candidates, LocalPeakCandidateResult):
        raise RidgeConfigurationError(
            "candidates must be a LocalPeakCandidateResult or None."
        )
    if reselection is not None and not isinstance(
        reselection, ExperimentalReselectionResult
    ):
        raise RidgeConfigurationError(
            "reselection must be an ExperimentalReselectionResult or None."
        )
    if (candidates is None) != (reselection is None):
        raise RidgeConfigurationError(
            "candidates and reselection must be present together."
        )
    if not isinstance(config, AutomaticRidgeSelectionConfig):
        raise RidgeConfigurationError(
            "config must be an AutomaticRidgeSelectionConfig."
        )
    if not np.array_equal(ridge.time_s, refined.time_s):
        raise RidgeConfigurationError(
            "Strongest ridge and refined time axes must match exactly."
        )
    if candidates is not None:
        assert isinstance(reselection, ExperimentalReselectionResult)
        if not np.array_equal(
            refined.time_s,
            candidates.time_s,
        ) or not np.array_equal(refined.time_s, reselection.time_s):
            raise RidgeConfigurationError(
                "Candidate and reselection time axes must match the strongest ridge."
            )


__all__ = ["select_automatic_ridge"]
