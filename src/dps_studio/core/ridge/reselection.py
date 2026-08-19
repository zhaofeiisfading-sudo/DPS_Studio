"""Experimental high-confidence continuity-assisted candidate reselection."""

from __future__ import annotations

import math

import numpy as np

from dps_studio.core.ridge.candidate_models import (
    LocalPeakCandidate,
    LocalPeakCandidateResult,
)
from dps_studio.core.ridge.continuity_models import EventAwareContinuityResult
from dps_studio.core.ridge.diagnostic_models import RidgeContinuityStatus
from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import RefinedRidgeResult, RidgeRefinementStatus
from dps_studio.core.ridge.quality_models import RidgeSpectralQualityStatus
from dps_studio.core.ridge.reselection_models import (
    CandidateReselectionEvidence,
    CandidateReselectionReason,
    ContinuityReselectionConfig,
    ExperimentalReselectionResult,
    ReselectionFrameStatus,
)


def reselect_isolated_jump_candidates(
    refined_ridge_result: RefinedRidgeResult,
    candidates: LocalPeakCandidateResult,
    continuity: EventAwareContinuityResult,
    *,
    config: ContinuityReselectionConfig,
) -> ExperimentalReselectionResult:
    """Build an experimental copy using only explicit high-confidence gates."""
    _validate_inputs(refined_ridge_result, candidates, continuity, config)
    legacy = refined_ridge_result.refined_frequency_hz
    experimental = legacy.copy()
    maximum_neighbor_distance_hz = (
        config.maximum_neighbor_distance_hz
        if config.maximum_neighbor_distance_hz is not None
        else continuity.config.neighbor_recovery_tolerance_hz
    )
    evidence_by_frame: list[tuple[CandidateReselectionEvidence, ...]] = []
    frame_statuses: list[ReselectionFrameStatus] = []

    for frame_index, frame_candidates in enumerate(candidates.candidates_by_frame):
        status = continuity.statuses[frame_index]
        event_transition = _contains_event(continuity, frame_index)
        legacy_bin = int(
            refined_ridge_result.discrete_frequency_bin_index[frame_index]
        )
        previous_hz = legacy[frame_index - 1] if frame_index > 0 else math.nan
        next_hz = (
            legacy[frame_index + 1]
            if frame_index + 1 < legacy.size
            else math.nan
        )
        legacy_hz = float(legacy[frame_index])
        legacy_previous_distance = (
            abs(legacy_hz - float(previous_hz))
            if math.isfinite(legacy_hz) and math.isfinite(float(previous_hz))
            else math.nan
        )
        legacy_next_distance = (
            abs(legacy_hz - float(next_hz))
            if math.isfinite(legacy_hz) and math.isfinite(float(next_hz))
            else math.nan
        )
        recovery_hz = (
            abs(float(next_hz) - float(previous_hz))
            if math.isfinite(float(previous_hz)) and math.isfinite(float(next_hz))
            else math.nan
        )

        prelim: list[tuple[LocalPeakCandidate, CandidateReselectionReason, float, float]] = []
        eligible: list[tuple[LocalPeakCandidate, float, float]] = []
        for candidate in frame_candidates:
            reason, distance_previous, distance_next = _candidate_reason(
                candidate,
                legacy_bin=legacy_bin,
                continuity_status=status,
                event_transition=event_transition,
                previous_hz=float(previous_hz),
                next_hz=float(next_hz),
                legacy_previous_distance=legacy_previous_distance,
                legacy_next_distance=legacy_next_distance,
                config=config,
                maximum_neighbor_distance_hz=maximum_neighbor_distance_hz,
            )
            prelim.append((candidate, reason, distance_previous, distance_next))
            if reason is CandidateReselectionReason.ELIGIBLE_NOT_SELECTED:
                eligible.append((candidate, distance_previous, distance_next))

        selected_rank: int | None = None
        if eligible:
            selected, _, _ = min(
                eligible,
                key=lambda item: (
                    max(item[1], item[2]),
                    item[1] + item[2],
                    item[0].amplitude_rank,
                ),
            )
            selected_rank = selected.amplitude_rank
            experimental[frame_index] = selected.refined_frequency_hz
            frame_statuses.append(ReselectionFrameStatus.RESELECTED)
        else:
            frame_statuses.append(
                _frame_status(
                    status,
                    event_transition=event_transition,
                    has_alternative=any(
                        candidate.bin_index != legacy_bin
                        for candidate in frame_candidates
                    ),
                )
            )

        frame_evidence = tuple(
            CandidateReselectionEvidence(
                candidate_rank=candidate.amplitude_rank,
                candidate_frequency_hz=candidate.refined_frequency_hz,
                candidate_magnitude=candidate.magnitude,
                candidate_peak_to_background_db=candidate.peak_to_background_db,
                candidate_peak_to_competitor_db=candidate.peak_to_competitor_db,
                distance_to_previous_hz=distance_previous,
                distance_to_next_hz=distance_next,
                neighbor_recovery_hz=recovery_hz,
                event_transition=event_transition,
                legacy_selected=candidate.bin_index == legacy_bin,
                experimental_selected=candidate.amplitude_rank == selected_rank,
                reselection_reason=(
                    CandidateReselectionReason.RESELECTED
                    if candidate.amplitude_rank == selected_rank
                    else reason
                ),
            )
            for candidate, reason, distance_previous, distance_next in prelim
        )
        evidence_by_frame.append(frame_evidence)

    return ExperimentalReselectionResult(
        time_s=refined_ridge_result.time_s,
        legacy_frequency_hz=legacy,
        experimental_frequency_hz=experimental,
        evidence_by_frame=tuple(evidence_by_frame),
        frame_statuses=tuple(frame_statuses),
        config=config,
        method=ExperimentalReselectionResult.METHOD,
        source_path=refined_ridge_result.source_path,
    )


def _candidate_reason(
    candidate: LocalPeakCandidate,
    *,
    legacy_bin: int,
    continuity_status: RidgeContinuityStatus,
    event_transition: bool,
    previous_hz: float,
    next_hz: float,
    legacy_previous_distance: float,
    legacy_next_distance: float,
    config: ContinuityReselectionConfig,
    maximum_neighbor_distance_hz: float,
) -> tuple[CandidateReselectionReason, float, float]:
    frequency_hz = candidate.refined_frequency_hz
    distance_previous = (
        abs(frequency_hz - previous_hz)
        if math.isfinite(frequency_hz) and math.isfinite(previous_hz)
        else math.nan
    )
    distance_next = (
        abs(frequency_hz - next_hz)
        if math.isfinite(frequency_hz) and math.isfinite(next_hz)
        else math.nan
    )
    if candidate.bin_index == legacy_bin:
        return (
            CandidateReselectionReason.LEGACY_SELECTED,
            distance_previous,
            distance_next,
        )
    if event_transition:
        return (
            CandidateReselectionReason.EVENT_TRANSITION_PROTECTED,
            distance_previous,
            distance_next,
        )
    if continuity_status is not RidgeContinuityStatus.ISOLATED_JUMP:
        return (
            CandidateReselectionReason.LEGACY_NOT_ISOLATED,
            distance_previous,
            distance_next,
        )
    if candidate.refinement_status is not RidgeRefinementStatus.REFINED:
        return (
            CandidateReselectionReason.REFINEMENT_UNAVAILABLE,
            distance_previous,
            distance_next,
        )
    if candidate.spectral_quality_status is not RidgeSpectralQualityStatus.ASSESSED:
        return (
            CandidateReselectionReason.SPECTRAL_EVIDENCE_UNAVAILABLE,
            distance_previous,
            distance_next,
        )
    if candidate.peak_to_background_db < config.minimum_peak_to_background_db:
        return (
            CandidateReselectionReason.PEAK_TO_BACKGROUND_TOO_LOW,
            distance_previous,
            distance_next,
        )
    if candidate.peak_to_competitor_db < config.minimum_peak_to_competitor_db:
        return (
            CandidateReselectionReason.PEAK_TO_COMPETITOR_TOO_LOW,
            distance_previous,
            distance_next,
        )
    if not (
        math.isfinite(distance_previous)
        and math.isfinite(distance_next)
        and math.isfinite(legacy_previous_distance)
        and math.isfinite(legacy_next_distance)
        and distance_previous < legacy_previous_distance
        and distance_next < legacy_next_distance
    ):
        return (
            CandidateReselectionReason.NOT_CLOSER_TO_BOTH_NEIGHBORS,
            distance_previous,
            distance_next,
        )
    if max(distance_previous, distance_next) > maximum_neighbor_distance_hz:
        return (
            CandidateReselectionReason.NEIGHBOR_DISTANCE_TOO_LARGE,
            distance_previous,
            distance_next,
        )
    return (
        CandidateReselectionReason.ELIGIBLE_NOT_SELECTED,
        distance_previous,
        distance_next,
    )


def _frame_status(
    continuity_status: RidgeContinuityStatus,
    *,
    event_transition: bool,
    has_alternative: bool,
) -> ReselectionFrameStatus:
    if event_transition:
        return ReselectionFrameStatus.EVENT_TRANSITION_PROTECTED
    if continuity_status is not RidgeContinuityStatus.ISOLATED_JUMP:
        if continuity_status in {
            RidgeContinuityStatus.GAP,
            RidgeContinuityStatus.INSUFFICIENT_CONTEXT,
        }:
            return ReselectionFrameStatus.GAP_OR_INSUFFICIENT_CONTEXT
        return ReselectionFrameStatus.LEGACY_NOT_ISOLATED
    if not has_alternative:
        return ReselectionFrameStatus.NO_ALTERNATIVE
    return ReselectionFrameStatus.NO_ELIGIBLE_ALTERNATIVE


def _contains_event(continuity: EventAwareContinuityResult, frame_index: int) -> bool:
    event_time_s = continuity.event_reference_time_s
    if event_time_s is None:
        return False
    distance_s = abs(float(continuity.time_s[frame_index]) - event_time_s)
    half_support_s = 0.5 * continuity.stft_window_duration_s
    return distance_s <= half_support_s or math.isclose(
        distance_s,
        half_support_s,
        rel_tol=8.0 * np.finfo(np.float64).eps,
        abs_tol=0.0,
    )


def _validate_inputs(
    refined: object,
    candidates: object,
    continuity: object,
    config: object,
) -> None:
    if not isinstance(refined, RefinedRidgeResult):
        raise RidgeConfigurationError("refined must be a RefinedRidgeResult.")
    if not isinstance(candidates, LocalPeakCandidateResult):
        raise RidgeConfigurationError("candidates must be a LocalPeakCandidateResult.")
    if not isinstance(continuity, EventAwareContinuityResult):
        raise RidgeConfigurationError(
            "continuity must be an EventAwareContinuityResult."
        )
    if not isinstance(config, ContinuityReselectionConfig):
        raise RidgeConfigurationError("config must be a ContinuityReselectionConfig.")
    if not np.array_equal(refined.time_s, candidates.time_s) or not np.array_equal(
        refined.time_s, continuity.time_s
    ):
        raise RidgeConfigurationError(
            "Refined ridge, candidates, and continuity time axes must match exactly."
        )
    if not np.array_equal(
        refined.refined_frequency_hz,
        continuity.frequency_hz,
        equal_nan=True,
    ):
        raise RidgeConfigurationError(
            "Continuity frequency_hz must be the supplied legacy refined ridge."
        )
    if not (refined.source_path == candidates.source_path == continuity.source_path):
        raise RidgeConfigurationError("All reselection inputs must share source_path.")


__all__ = ["reselect_isolated_jump_candidates"]
