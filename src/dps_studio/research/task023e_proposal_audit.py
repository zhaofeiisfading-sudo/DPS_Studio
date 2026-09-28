"""Read-only fixed-beam feasibility audit; ground truth never enters the tracker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from dps_studio.core.time_frequency import STFTResult
from dps_studio.research.task023c_trusted_core_edge_rescue import _broadband_robust_z

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.research import task023d_smooth_branch_rescue as previous


@dataclass(frozen=True)
class BeamSnapshot:
    """All terminal states of the unchanged width-eight search."""

    indices: tuple[int, ...]
    states: tuple[Any, ...]
    anchor: int


def terminal_beam(
    indices: tuple[int, ...],
    anchor: int,
    slope: float,
    result: previous.SmoothBranchOptimizationResult,
    candidates: RidgeCandidateSet,
    ambiguity_config: previous.BranchAmbiguityConfig,
    config: previous.BranchCompetitionConfig,
    broadband: np.ndarray,
) -> BeamSnapshot:
    """Expose, without widening or rescoring, the original terminal beam.

    The loop and ordering mirror TASK-023D._search_branch. The runner verifies
    its first state against the existing search. No truth is accepted here.
    """
    if config.beam_width != 8:
        raise ValueError("TASK-023E fixes beam width at eight")
    states: tuple[previous._BranchState, ...] = (previous._initial_state(result.task023c, anchor, slope),)
    last = anchor
    for frame_index in indices:
        expanded = [
            previous._extend_branch(
                state, candidate, last, frame_index, result.task023c, candidates,
                result.ambiguity, ambiguity_config, config, broadband,
            )
            for state in states
            for candidate in candidates.candidates_by_frame[frame_index]
        ]
        if not expanded:
            return BeamSnapshot(indices[:len(states[0].frequencies_hz)], states, anchor)
        states = tuple(sorted(
            expanded, key=lambda state: (state.total_cost, state.ranks, state.frequencies_hz),
        )[:config.beam_width])
        last = frame_index
    return BeamSnapshot(indices, states, anchor)


def collect_beams(
    result: previous.SmoothBranchOptimizationResult, candidates: RidgeCandidateSet,
    ambiguity_config: previous.BranchAmbiguityConfig, config: previous.BranchCompetitionConfig,
    stft: STFTResult,
) -> tuple[BeamSnapshot, ...]:
    """Use exactly the first/last retained anchors and original slope initialization."""
    if not result.trimmed_cores:
        return ()
    count = len(candidates.candidates_by_frame)
    broadband = _broadband_robust_z(stft)
    beams = []
    for leading, anchor in (
        (True, result.trimmed_cores[0].frame_start),
        (False, result.trimmed_cores[-1].frame_end),
    ):
        indices = tuple(range(anchor - 1, -1, -1) if leading else range(anchor + 1, count))
        if not indices or any(not candidates.candidates_by_frame[i] for i in indices):
            continue
        slope_frames = np.arange(anchor, min(anchor + 4, count)) if leading else np.arange(
            max(0, anchor - 3), anchor + 1,
        )
        slope = float(np.median(
            np.diff(result.strongest.frequency_hz[slope_frames])
            / np.diff(candidates.time_s[slope_frames])
        )) if slope_frames.size >= 2 else 0.0
        beam = terminal_beam(
            indices, anchor, slope, result, candidates, ambiguity_config, config, broadband,
        )
        # Exact verification against the existing solver, including tie ordering.
        expected = previous._search_branch(
            indices, anchor, slope, result.task023c, candidates, result.ambiguity,
            ambiguity_config, config, broadband,
        )
        if beam.states[0] != expected:
            raise AssertionError("Exposed beam differs from the frozen TASK-023D solver")
        beams.append(beam)
    return tuple(beams)


def truth_connected(
    candidates: RidgeCandidateSet, truth: np.ndarray, tolerance_hz: float,
    config: previous.BranchCompetitionConfig,
) -> np.ndarray:
    """Adjacent truth-near candidate connectivity, independently of tracker costs.

    Return per-frame reachability within each contiguous truth-valid run. This
    is a geometric diagnostic, not a claim of physical target identity.
    """
    reachable = np.zeros(len(truth), dtype=bool)
    prior: list[float] = []
    for i, value in enumerate(truth):
        near = [c.transition_frequency_hz for c in candidates.candidates_by_frame[i]
                if np.isfinite(value) and abs(c.transition_frequency_hz - value) <= tolerance_hz]
        if i == 0 or not np.isfinite(truth[i - 1]):
            current = near
        else:
            limit = config.link_base_hz + config.maximum_rate_hz_per_s * abs(
                candidates.time_s[i] - candidates.time_s[i - 1],
            )
            current = [f for f in near if any(abs(f - p) <= limit for p in prior)]
        reachable[i] = bool(current)
        prior = current
    return reachable


def audit_frames(
    case_id: str, candidates: RidgeCandidateSet, truth: np.ndarray,
    result: previous.SmoothBranchOptimizationResult, beams: tuple[BeamSnapshot, ...],
    tolerance_hz: float = 200e6,
) -> list[dict[str, Any]]:
    """Separate availability, legal-region restrictions and terminal proposal loss.

    The pointwise oracle is intentionally optimistic: it may switch between
    terminal states every frame. Failure of this upper bound rules out every
    selector constrained to those proposals. It is never emitted as a result.
    """
    baseline = result.strongest.frequency_hz
    fallback = result.task023c.final_frequency_hz
    available = np.zeros(len(truth), dtype=bool)
    offered = np.zeros(len(truth), dtype=bool)
    oracle_error = np.abs(fallback - truth)
    for i, value in enumerate(truth):
        available[i] = any(abs(c.transition_frequency_hz - value) <= tolerance_hz
                           for c in candidates.candidates_by_frame[i])
    for beam in beams:
        for state in beam.states:
            for i, frequency in zip(beam.indices, state.frequencies_hz, strict=True):
                offered[i] |= abs(frequency - truth[i]) <= tolerance_hz
                oracle_error[i] = min(oracle_error[i], abs(frequency - truth[i]))
    # Frozen internal proposal already present in 023C also counts as offered.
    offered |= (fallback != baseline) & (np.abs(fallback - truth) <= tolerance_hz)
    connected = truth_connected(candidates, truth, tolerance_hz, previous.BranchCompetitionConfig())
    rows = []
    for i, value in enumerate(truth):
        valid = bool(np.isfinite(value))
        wrong = valid and abs(baseline[i] - value) > tolerance_hz
        correctable = wrong and bool(available[i])
        reason = "NO_BASELINE_BRANCH_ERROR"
        if wrong:
            reason = "CANDIDATE_MISSING" if not available[i] else (
                "CORE_LOCKED" if result.trimmed_core_mask[i] else (
                    "TERMINAL_PROPOSAL_MISSING" if not offered[i] else (
                        "ACCEPTED_CORRECTION" if abs(result.final_frequency_hz[i] - value)
                        <= tolerance_hz else "SCORE_OR_ACCEPTANCE_REJECTED"
                    )
                )
            )
        rows.append({
            "case_id": case_id, "frame": i, "time_s": candidates.time_s[i],
            "truth_hz": value, "truth_valid": valid,
            "strongest_hz": baseline[i], "task023c_hz": fallback[i],
            "task023d_hz": result.final_frequency_hz[i],
            "candidate_available": bool(available[i]), "truth_connected": bool(connected[i]),
            "terminal_proposal_available": bool(offered[i]),
            "core_locked": bool(result.trimmed_core_mask[i]),
            "strongest_wrong": bool(wrong), "candidate_correctable": bool(correctable),
            "proposal_blocked": bool(correctable and not offered[i]),
            "oracle_error_hz": float(oracle_error[i]), "reason": reason,
        })
    return rows


def feasibility_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Predeclared majority criterion; never calibrate from real data."""
    correctable = sum(r["candidate_correctable"] for r in rows)
    blocked = sum(r["proposal_blocked"] for r in rows)
    fraction = blocked / correctable if correctable else 0.0
    return {
        "candidate_correctable_wrong_frames": correctable,
        "proposal_blocked_frames": blocked,
        "proposal_blocked_fraction": fraction,
        "majority_threshold": 0.5,
        "stop_scorer": fraction > 0.5,
        "reason": "PROPOSAL_BOTTLENECK" if fraction > 0.5 else "MAJORITY_GATE_PASSED",
    }
