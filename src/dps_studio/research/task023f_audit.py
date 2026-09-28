"""Read-only label-based funnel and whole-proposal oracles for TASK-023F."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research.task023e_proposal_audit import truth_connected
from dps_studio.research.task023f_proposals import ProposalResult, SearchResult, Window, runs

TOLERANCE_HZ = 200e6


@dataclass(frozen=True)
class AuditResult:
    frames: tuple[dict[str, Any], ...]
    pruning: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def metrics(strongest: np.ndarray, final: np.ndarray, truth: np.ndarray) -> dict[str, Any]:
    valid = np.isfinite(truth) & np.isfinite(strongest)
    output = np.isfinite(final)
    changed = np.isfinite(strongest) & output & (final != strongest)
    error = np.abs(final - truth)
    old = np.abs(strongest - truth)
    corrected = changed & valid & (error < old)
    harmed = changed & valid & (error > old)
    interventions = int(np.sum(changed & valid))
    n = int(np.sum(valid))
    sse = float(np.sum(error[valid & output] ** 2))
    wrong = int(np.sum(valid & (error > TOLERANCE_HZ)))
    return dict(valid_frames=n, sse_hz2=sse, rmse_mhz=np.sqrt(sse / n) / 1e6 if n else None,
                wrong_frames=wrong, wrong_branch=ratio(wrong, n),
                baseline_frames=int(np.sum(np.isfinite(strongest))),
                output_frames=int(np.sum(output & np.isfinite(strongest))),
                coverage=ratio(float(np.sum(output & np.isfinite(strongest))),
                               float(np.sum(np.isfinite(strongest)))),
                modifications=int(np.sum(changed)), truth_modifications=interventions,
                modification_fraction=ratio(float(np.sum(changed)),
                                            float(np.sum(np.isfinite(strongest)))),
                corrected_frames=int(np.sum(corrected)), harmed_frames=int(np.sum(harmed)),
                precision=ratio(float(np.sum(corrected)), interventions),
                harm_rate=ratio(float(np.sum(harmed)), interventions),
                no_truth_frames=int(np.sum(~np.isfinite(truth))),
                no_truth_output_frames=int(np.sum(~np.isfinite(truth) & output)),
                no_truth_modifications=int(np.sum(~np.isfinite(truth) & changed)))


def lineage_audit(search: SearchResult, truth: np.ndarray,
                  error_mask: np.ndarray) -> list[dict[str, Any]]:
    """Track truth-consistent prefixes within each continuous error interval.

    Parent IDs reconstruct every frequency history; a dropped prefix never
    silently reappears. Entry before an error interval is deliberately unrestricted.
    """
    by_frame: dict[int, list[Any]] = {}
    for node in search.lineage:
        by_frame.setdefault(node.frame, []).append(node)
    rows: list[dict[str, Any]] = []
    for interval in runs(error_mask):
        ix = [i for i in search.window.indices if i in interval]
        if not ix:
            continue
        alive: set[int] | None = None
        first_loss: int | None = None
        loss_reason = ''
        for frame in ix:
            nodes = by_frame.get(frame, [])
            expanded = [node for node in nodes if (alive is None or node.parent_id in alive)
                        and abs(node.frequency_hz - truth[frame]) <= TOLERANCE_HZ]
            kept = [node for node in expanded if node.retained]
            if first_loss is None and not kept:
                first_loss = frame
                loss_reason = 'EXPANDED_THEN_PRUNED' if expanded else 'HYPOTHESIS_NOT_GENERATED'
            alive = {node.hypothesis_id for node in kept}
            # Counterfactual crowding: truth expansion cut, duplicate retained family,
            # AND a truth-near family representative would be eligible under the guard.
            duplicates = any(node.family_occupancy > 1 for node in nodes if node.retained)
            rows.append(dict(window_id=search.window.window_id, error_start=interval[0],
                error_end=interval[-1], frame=frame, expanded_consistent=len(expanded),
                search_offset=nodes[0].offset if nodes else None,
                retained_consistent=len(kept), best_expansion_rank=min(
                    (node.expansion_rank for node in expanded), default=None),
                cutoff_score=nodes[0].cutoff_score if nodes else None,
                first_loss_frame=first_loss, first_loss_reason=loss_reason,
                first_loss_here=first_loss == frame, duplicate_family_occupancy=duplicates,
                truth_prefix_displaced_by_duplicates=bool(expanded and not kept and duplicates)))
    return rows


def internal_fallback(result: d.SmoothBranchOptimizationResult) -> np.ndarray:
    final = result.task023c.strongest.frequency_hz.copy()
    if result.trimmed_cores:
        d._apply_internal(result.task023c, result.trimmed_cores, result.trimmed_core_mask,
                          final, result.task023c.strongest.selected_rank.copy(),
                          ['KEEP_STRONGEST'] * len(final))
    return final


def audit(
    candidates: RidgeCandidateSet, truth: np.ndarray, nuisance: np.ndarray,
    original: d.SmoothBranchOptimizationResult, searches: tuple[SearchResult, ...],
    registry: tuple[Window, ...], mainlobe_hz: float, final: ProposalResult | None = None,
) -> AuditResult:
    strongest = original.task023c.strongest.frequency_hz
    valid = np.isfinite(truth) & np.isfinite(strongest)
    wrong = valid & (np.abs(strongest - truth) > TOLERANCE_HZ)
    available = np.array([any(abs(c.transition_frequency_hz - truth[i]) <= TOLERANCE_HZ
                             for c in frame) for i, frame in enumerate(candidates.candidates_by_frame)])
    terminal = np.zeros(len(truth), dtype=bool)
    generated = terminal.copy()
    selected = terminal.copy()
    prefix_retained = terminal.copy()
    expanded = terminal.copy()
    fallback = internal_fallback(original)
    terminal |= (fallback != strongest) & (np.abs(fallback - truth) <= TOLERANCE_HZ)
    generated |= terminal
    pruning: list[dict[str, Any]] = []
    search_frames: dict[int, SearchResult] = {}
    for search in searches:
        ix = list(search.window.indices)
        search_frames.update({i: search for i in ix})
        if search.proposals:
            generated[ix] = available[ix]
        for proposal in search.proposals:
            terminal[ix] |= np.abs(np.asarray(proposal.state.frequencies_hz) - truth[ix]) <= TOLERANCE_HZ
        if search.proposals:
            selected[ix] = np.abs(np.asarray(search.proposals[0].state.frequencies_hz)
                                  - truth[ix]) <= TOLERANCE_HZ
        parts = lineage_audit(search, truth, wrong)
        pruning.extend(parts)
        for row in parts:
            prefix_retained[row['frame']] |= row['retained_consistent'] > 0
            expanded[row['frame']] |= row['expanded_consistent'] > 0
    connected = truth_connected(candidates, truth, TOLERANCE_HZ, d.BranchCompetitionConfig())
    window_map = {i: window for window in registry for i in window.indices}
    resolved = np.abs(truth - nuisance) >= mainlobe_hz
    rows: list[dict[str, Any]] = []
    for i in np.flatnonzero(wrong):
        window = window_map.get(int(i))
        frame_search = search_frames.get(int(i))
        reason = 'TERMINAL_AVAILABLE'
        if not available[i]:
            reason = 'CANDIDATE_MISSING'
        elif window is None:
            reason = 'UNTRIGGERED_CORE' if original.trimmed_core_mask[i] else 'NO_LOCAL_WINDOW'
        elif window.anchor is None:
            reason = 'NO_ELIGIBLE_ANCHOR'
        elif frame_search is None:
            reason = 'CORE_PERMISSION_DENIED'
        elif not terminal[i]:
            reason = 'EXPANDED_THEN_PRUNED' if expanded[i] else 'HYPOTHESIS_NOT_GENERATED'
        elif final is not None and abs(final.final_frequency_hz[i] - truth[i]) > TOLERANCE_HZ:
            reason = 'ACCEPTANCE_REJECTED' if selected[i] else 'SELECTOR_NOT_SELECTED'
        near_rank = min((c.candidate_rank for c in candidates.candidates_by_frame[i]
                         if abs(c.transition_frequency_hz - truth[i]) <= TOLERANCE_HZ), default=None)
        trust = original.task023c.trust
        row = dict(frame=int(i), time_s=float(candidates.time_s[i]),
            truth_hz=float(truth[i]), strongest_hz=float(strongest[i]),
            strongest_error_hz=float(abs(strongest[i] - truth[i])),
            candidate_available=bool(available[i]), truth_near_rank=near_rank,
            geometric_connected=bool(connected[i]), branch_constructable=bool(generated[i]),
            core=bool(original.trimmed_core_mask[i]),
            ambiguity=float(original.ambiguity.branch_ambiguity[i]),
            alternative_rank=int(original.ambiguity.best_alternative_rank[i]),
            alternative_persistence=float(original.ambiguity.best_alternative_persistence[i]),
            window_id=window.window_id if window else '', anchor=window.anchor if window else None,
            permission=frame_search is not None, expanded_consistent=bool(expanded[i]),
            retained_consistent=bool(prefix_retained[i]), terminal=bool(terminal[i]),
            selected=bool(selected[i]), accepted=bool(final.accepted_mask[i]) if final else None,
            resolved=bool(resolved[i]), mainlobe_hz=mainlobe_hz, reason=reason)
        for name in ('trust_score', 'spectral_score', 'competitor_score', 'refinement_score',
                     'candidate_support', 'consistency_score', 'broadband_penalty'):
            row[name] = float(getattr(trust, name)[i])
        rows.append(row)
    error_runs = runs(wrong)
    branch_hits = 0
    for interval in error_runs:
        hit = False
        for search in searches:
            positions = {i: j for j, i in enumerate(search.window.indices)}
            if all(i in positions for i in interval):
                hit |= any(all(abs(p.state.frequencies_hz[positions[i]] - truth[i])
                               <= TOLERANCE_HZ for i in interval) for p in search.proposals)
        # The unchanged internal proposal is also one complete hypothesis.
        hit |= bool(np.all((fallback[list(interval)] != strongest[list(interval)])
                          & (np.abs(fallback[list(interval)] - truth[list(interval)]) <= TOLERANCE_HZ)))
        branch_hits += int(hit)
    denominator = int(np.sum(wrong))
    candidate_count = int(np.sum(wrong & available))
    terminal_count = int(np.sum(wrong & terminal))
    summary: dict[str, Any] = dict(error_frames=denominator, candidate_frames=candidate_count,
        graph_frames=int(np.sum(wrong & generated)), terminal_frames=terminal_count,
        missing_frames=int(np.sum(wrong & available & ~terminal)),
        candidate_recall=ratio(candidate_count, denominator),
        graph_recall=ratio(float(np.sum(wrong & generated)), denominator),
        terminal_recall=ratio(terminal_count, denominator),
        missing_proposal_fraction=ratio(float(np.sum(wrong & available & ~terminal)), candidate_count),
        graph_given_candidate=ratio(float(np.sum(wrong & generated)), candidate_count),
        terminal_given_graph=ratio(terminal_count, float(np.sum(wrong & generated))),
        error_intervals=len(error_runs), recovered_intervals=branch_hits,
        branch_recall=ratio(branch_hits, len(error_runs)),
        final_correction_recall=ratio(float(np.sum(wrong & (
            np.abs(final.final_frequency_hz - truth) <= TOLERANCE_HZ))), denominator) if final else None,
        no_truth_frames=int(np.sum(~np.isfinite(truth))),
        no_strongest_frames=int(np.sum(~np.isfinite(strongest))))
    for label, mask in (('resolved', resolved), ('unresolved', ~resolved)):
        summary[label + '_error_frames'] = int(np.sum(wrong & mask))
        summary[label + '_terminal_frames'] = int(np.sum(wrong & mask & terminal))
    return AuditResult(tuple(rows), tuple(pruning), summary)


def oracle(
    strongest: np.ndarray, truth: np.ndarray, searches: tuple[SearchResult, ...],
    fallback: np.ndarray | None = None,
) -> dict[str, dict[str, Any]]:
    """Whole-window choices are separable; ties keep strongest to avoid fake gains."""
    minimum_sse, minimum_wrong, relaxed = strongest.copy(), strongest.copy(), strongest.copy()
    occupied = np.zeros(len(strongest), dtype=bool)
    options: list[tuple[np.ndarray, list[np.ndarray]]] = []
    for search in searches:
        ix = np.asarray(search.window.indices, dtype=int)
        if np.any(occupied[ix]):
            raise ValueError('Oracle requires disjoint windows')
        occupied[ix] = True
        options.append((ix, [np.asarray(p.state.frequencies_hz) for p in search.proposals]))
    if fallback is not None:
        for run in runs((fallback != strongest) & ~occupied):
            ix = np.asarray(run)
            options.append((ix, [fallback[ix]]))
    for ix, proposals in options:
        choices = [strongest[ix], *proposals]
        valid = np.isfinite(truth[ix]) & np.isfinite(strongest[ix])
        errors = [np.abs(path - truth[ix]) for path in choices]
        sse = [float(np.sum(err[valid] ** 2)) for err in errors]
        wrong = [int(np.sum(err[valid] > TOLERANCE_HZ)) for err in errors]
        minimum_sse[ix] = choices[min(range(len(choices)), key=lambda j: (sse[j], j))]
        minimum_wrong[ix] = choices[min(range(len(choices)), key=lambda j: (wrong[j], j))]
        best = np.argmin(np.where(valid[None, :], np.asarray(errors), 0.), axis=0)
        relaxed[ix] = np.asarray(choices)[best, np.arange(len(ix))]
    return {name: metrics(strongest, path, truth) for name, path in (
        ('FEASIBLE_MIN_SSE', minimum_sse), ('FEASIBLE_MIN_WRONG', minimum_wrong),
        ('RELAXED_FRAMEWISE', relaxed))}
