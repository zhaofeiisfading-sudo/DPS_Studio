"""GT-blind permission and retention experiment using the frozen E4 arithmetic.

The diagnostic beam width has a separate entry point. Neither generation nor
selection accepts labels. Lineage IDs identify *all* expansions, including cuts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from dps_studio.core.ridge import RidgeCandidate, RidgeCandidateSet
from dps_studio.core.time_frequency import STFTResult
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research.task021b_real_experiment import node_cost_components
from dps_studio.research.task023c_trusted_core_edge_rescue import (
    TrustedCoreOptimizationResult, _broadband_robust_z, _rank_limited_support,
)


@dataclass(frozen=True)
class ProposalConfig:
    challenge_core: bool = False
    diversity: bool = False
    trigger_frames: int = 4
    ambiguity_threshold: float = 0.36
    history_frames: int = 4


@dataclass(frozen=True)
class Window:
    window_id: str
    indices: tuple[int, ...]
    anchor: int | None
    slope: float
    kind: str
    status: str


@dataclass(frozen=True)
class Expansion:
    hypothesis_id: int
    parent_id: int
    frame: int
    offset: int
    score_before: float
    score: float
    expansion_rank: int
    cutoff_score: float
    candidate_rank: int
    frequency_hz: float
    history_hz: tuple[float, ...]
    identity: float
    local_support: float
    family: int
    family_occupancy: int
    retained: bool


@dataclass(frozen=True)
class Proposal:
    hypothesis_id: int
    state: d._BranchState


@dataclass(frozen=True)
class SearchResult:
    window: Window
    proposals: tuple[Proposal, ...]
    lineage: tuple[Expansion, ...]
    beam_width: int
    diagnostic_only: bool


@dataclass(frozen=True)
class Selection:
    selected_proposal: int | None
    status: str
    accepted: tuple[bool, ...]
    margin: float | None


@dataclass(frozen=True)
class ProposalResult:
    strongest_frequency_hz: np.ndarray
    final_frequency_hz: np.ndarray
    final_rank: np.ndarray
    permission_mask: np.ndarray
    accepted_mask: np.ndarray
    searches: tuple[SearchResult, ...]
    selections: tuple[Selection, ...]


def effective_e4(config: d.BranchCompetitionConfig) -> d.BranchCompetitionConfig:
    return replace(config, minimum_identity_support=max(config.minimum_identity_support, 0.62),
                   minimum_local_support=max(config.minimum_local_support, 0.65),
                   branch_acceptance_margin=config.branch_acceptance_margin + 1.5,
                   deviation_weight=config.deviation_weight * 1.5)


def runs(mask: np.ndarray) -> tuple[tuple[int, ...], ...]:
    padded = np.r_[False, mask, False].astype(int)
    return tuple(tuple(range(int(a), int(b))) for a, b in zip(
        np.flatnonzero(np.diff(padded) == 1), np.flatnonzero(np.diff(padded) == -1), strict=True,
    ))


def windows(
    result: d.SmoothBranchOptimizationResult, config: ProposalConfig,
    ambiguity_config: d.BranchAmbiguityConfig,
) -> tuple[Window, ...]:
    """Common registry includes denied core windows so cost denominators agree."""
    n = result.task023c.time_s.size
    time = result.task023c.time_s
    baseline = result.task023c.strongest.frequency_hz

    def slope(anchor: int, backward: bool) -> float:
        ix = np.arange(anchor, min(n, anchor + 4)) if backward else np.arange(
            max(0, anchor - 3), anchor + 1,
        )
        return float(np.median(np.diff(baseline[ix]) / np.diff(time[ix]))) if len(ix) > 1 else 0.

    out: list[Window] = []
    if not result.trimmed_cores:
        return ()
    for backward, edge_anchor in ((True, result.trimmed_cores[0].frame_start),
                             (False, result.trimmed_cores[-1].frame_end)):
        ix = tuple(range(edge_anchor - 1, -1, -1) if backward else range(edge_anchor + 1, n))
        out.append(Window('edge_left' if backward else 'edge_right', ix, edge_anchor,
                          slope(edge_anchor, backward), 'EDGE', 'ELIGIBLE' if ix else 'NO_EDGE'))
    a = result.ambiguity
    # Existing alternative diagnostic already restricts rank, separation and
    # connectivity. Require each trigger independently to persist for four frames.
    persistent = a.best_alternative_rank > 0
    ambiguous = a.branch_ambiguity >= config.ambiguity_threshold
    for core in result.trimmed_cores:
        trigger = np.zeros(n, dtype=bool)
        for raw in (persistent, ambiguous):
            local = np.zeros(n, dtype=bool)
            local[core.frame_start:core.frame_end + 1] = raw[core.frame_start:core.frame_end + 1]
            for run in runs(local):
                if len(run) >= config.trigger_frames:
                    trigger[list(run)] = True
        for run in runs(trigger):
            possible = [i for i in range(core.frame_start, core.frame_end + 1)
                        if not trigger[i] and min(abs(time[i] - time[run[0]]),
                                                 abs(time[i] - time[run[-1]]))
                        <= ambiguity_config.context_time_s]
            anchor = min(possible, key=lambda i: (
                min(abs(time[i] - time[run[0]]), abs(time[i] - time[run[-1]])), i,
            )) if possible else None
            backward = anchor is not None and anchor > run[-1]
            ix = tuple(reversed(run)) if backward else run
            out.append(Window(f'core_{core.core_id}_{run[0]}', ix, anchor,
                              slope(anchor, backward) if anchor is not None else 0., 'CORE',
                              'ELIGIBLE' if anchor is not None else 'NO_ELIGIBLE_ANCHOR'))
    return tuple(out)


def family_ids(states: tuple[d._BranchState, ...], separation_hz: float = 260e6,
               history_frames: int = 4) -> tuple[int, ...]:
    representatives: list[tuple[float, ...]] = []
    labels: list[int] = []
    for state in states:
        history = state.frequencies_hz[-history_frames:]
        family = next((i for i, rep in enumerate(representatives)
                       if len(history) == len(rep) and all(abs(a - b) <= separation_hz
                           for a, b in zip(history, rep, strict=True))), len(representatives))
        if family == len(representatives):
            representatives.append(history)
        labels.append(family)
    return tuple(labels)


def retained_indices(
    states: tuple[d._BranchState, ...], families: tuple[int, ...], width: int,
    diversity: bool, config: d.BranchCompetitionConfig, broadband: float,
) -> tuple[int, ...]:
    if not diversity:
        return tuple(range(min(width, len(states))))
    if not states:
        return ()
    selected = [0]
    seen = {families[0]}
    for i, state in enumerate(states[1:], 1):
        support = state.local_supports[-1]
        if (families[i] not in seen
            and state.identity_support >= config.minimum_identity_support
            and support >= config.minimum_local_support
            and (broadband < config.broadband_z_threshold or support >= config.broadband_support_floor)
            and state.total_cost - states[0].total_cost <= config.identity_break_penalty):
            selected.append(i)
            seen.add(families[i])
        if len(selected) == width:
            break
    selected.extend(i for i in range(len(states)) if i not in selected)
    # Original score order governs subsequent expansion and terminal selection.
    return tuple(sorted(selected[:width]))


def _search(
    window: Window, result: d.SmoothBranchOptimizationResult, candidates: RidgeCandidateSet,
    ambiguity_config: d.BranchAmbiguityConfig, config: d.BranchCompetitionConfig,
    broadband: np.ndarray, diversity: bool, width: int, diagnostic: bool,
) -> SearchResult:
    if window.anchor is None or not window.indices or any(
        not candidates.candidates_by_frame[i] for i in window.indices
    ):
        return SearchResult(window, (), (), width, diagnostic)
    states: tuple[Proposal, ...] = (Proposal(0, d._initial_state(result.task023c, window.anchor, window.slope)),)
    evidence_cache: dict[tuple[int, int], tuple[float, float]] = {}
    previous = window.anchor
    next_id = 1
    trace: list[Expansion] = []
    for offset, frame in enumerate(window.indices):
        expanded: list[tuple[int, int, float, d._BranchState]] = []
        for parent in states:
            for candidate in candidates.candidates_by_frame[frame]:
                child = _extend_cached(parent.state, candidate, previous, frame, result.task023c,
                                         candidates, result.ambiguity, ambiguity_config,
                                         config, broadband, evidence_cache)
                expanded.append((next_id, parent.hypothesis_id, parent.state.total_cost, child))
                next_id += 1
        expanded.sort(key=lambda x: (x[3].total_cost, x[3].ranks, x[3].frequencies_hz))
        values = tuple(x[3] for x in expanded)
        families = family_ids(values, ambiguity_config.minimum_branch_separation_hz)
        keep = retained_indices(values, families, width, diversity, config, float(broadband[frame]))
        cutoff = values[min(width, len(values)) - 1].total_cost
        occupancy = {fam: sum(families[i] == fam for i in keep) for fam in set(families)}
        for rank, (hid, parent_id, before, state) in enumerate(expanded):
            trace.append(Expansion(hid, parent_id, frame, offset, before, state.total_cost,
                                   rank + 1, cutoff, state.ranks[-1], state.frequencies_hz[-1],
                                   state.frequencies_hz[-4:], state.identity_support,
                                   state.local_supports[-1], families[rank],
                                   occupancy[families[rank]], rank in keep))
        states = tuple(Proposal(expanded[i][0], values[i]) for i in keep)
        previous = frame
    return SearchResult(window, states, tuple(trace), width, diagnostic)


def generate_proposals(
    window: Window, result: d.SmoothBranchOptimizationResult, candidates: RidgeCandidateSet,
    ambiguity_config: d.BranchAmbiguityConfig, config: d.BranchCompetitionConfig,
    broadband: np.ndarray, *, diversity: bool = False,
) -> SearchResult:
    if config.beam_width != 8:
        raise ValueError('Formal proposal generation is fixed at B8')
    return _search(window, result, candidates, ambiguity_config, config, broadband, diversity, 8, False)


def diagnostic_b32(
    window: Window, result: d.SmoothBranchOptimizationResult, candidates: RidgeCandidateSet,
    ambiguity_config: d.BranchAmbiguityConfig, config: d.BranchCompetitionConfig,
    broadband: np.ndarray,
) -> SearchResult:
    return _search(window, result, candidates, ambiguity_config, config, broadband, False, 32, True)


def select_proposal(
    search: SearchResult, result: d.SmoothBranchOptimizationResult, candidates: RidgeCandidateSet,
    ambiguity_config: d.BranchAmbiguityConfig, config: d.BranchCompetitionConfig,
    broadband: np.ndarray,
) -> Selection:
    """Best-first, then the literal E4 acceptance order; never try a runner-up."""
    if search.diagnostic_only or search.beam_width != 8:
        raise ValueError('B32 is diagnostic, never a final method')
    if not search.window.indices:
        return Selection(None, 'KEEP_NO_EDGE', (), None)
    if not search.proposals or search.window.anchor is None:
        return Selection(None, 'KEEP_EVIDENCE', tuple(False for _ in search.window.indices), None)
    best = search.proposals[0].state
    ix = search.window.indices
    baseline = d._score_strongest_branch(ix, search.window.anchor, search.window.slope,
        result.task023c, candidates, result.ambiguity, ambiguity_config, config, broadband)
    score = d._score_gain(baseline, best)
    strongest = result.task023c.strongest.frequency_hz
    changed = [f != strongest[i] for i, f in zip(ix, best.frequencies_hz, strict=True)]
    acceptable = [False] * len(ix)
    stopped = False
    for offset, frame in enumerate(ix):
        if stopped or not changed[offset]:
            continue
        identity, support = best.identities[offset], best.local_supports[offset]
        elevated = broadband[frame] >= config.broadband_z_threshold
        if (identity >= config.minimum_identity_support and support >= config.minimum_local_support
            and (not elevated or support >= config.broadband_support_floor)):
            acceptable[offset] = True
        else:
            stopped = True
    modified = sum(acceptable)
    deviation = sum(abs(best.frequencies_hz[j] - strongest[i]) for j, i in enumerate(ix)
                    if acceptable[j])
    status = 'ACCEPTED'
    if not any(changed):
        status = 'KEEP_NO_ALTERNATIVE'
    elif modified == 0:
        status = 'KEEP_EVIDENCE'
    elif score.branch_margin < config.branch_acceptance_margin:
        status = 'KEEP_MARGIN'
    elif (modified > config.maximum_modified_frames
          or modified / len(ix) > config.maximum_modified_fraction
          or deviation > config.maximum_total_deviation_hz):
        status = 'KEEP_DEVIATION_BUDGET'
    if status != 'ACCEPTED':
        acceptable = [False] * len(ix)
    return Selection(search.proposals[0].hypothesis_id, status, tuple(acceptable), score.branch_margin)


def apply_searches(
    searches: tuple[SearchResult, ...], result: d.SmoothBranchOptimizationResult,
    candidates: RidgeCandidateSet, ambiguity_config: d.BranchAmbiguityConfig,
    config: d.BranchCompetitionConfig, broadband: np.ndarray,
) -> ProposalResult:
    strongest = result.task023c.strongest.frequency_hz
    final, ranks = strongest.copy(), result.task023c.strongest.selected_rank.copy()
    permission, accepted = np.zeros(len(final), dtype=bool), np.zeros(len(final), dtype=bool)
    if result.trimmed_cores:
        d._apply_internal(result.task023c, result.trimmed_cores, result.trimmed_core_mask,
                          final, ranks, ['KEEP_STRONGEST'] * len(final))
    selections = []
    for search in searches:
        if any(permission[list(search.window.indices)]):
            raise ValueError('Overlapping windows are forbidden')
        permission[list(search.window.indices)] = True
        selection = select_proposal(search, result, candidates, ambiguity_config, config, broadband)
        selections.append(selection)
        if not search.proposals:
            continue
        state = search.proposals[0].state
        for j, i in enumerate(search.window.indices):
            if selection.accepted[j]:
                final[i], ranks[i], accepted[i] = state.frequencies_hz[j], state.ranks[j], True
    core_changed = result.trimmed_core_mask & (final != strongest)
    if np.any(core_changed & ~(permission & accepted)):
        raise AssertionError('Core deviation without permission and acceptance')
    d._verify_provenance(final, strongest, candidates)
    if not np.all(np.isfinite(final[np.isfinite(strongest)])):
        raise AssertionError('Coverage was lost')
    for array in (final, ranks, permission, accepted):
        array.flags.writeable = False
    return ProposalResult(strongest, final, ranks, permission, accepted, searches, tuple(selections))


def broadband_evidence(stft: STFTResult) -> np.ndarray:
    return _broadband_robust_z(stft)


TraceSink = Callable[[SearchResult], None]


def _extend_cached(
    state: d._BranchState,
    candidate: RidgeCandidate,
    previous_frame: int,
    frame_index: int,
    task023c: TrustedCoreOptimizationResult,
    candidate_set: RidgeCandidateSet,
    ambiguity: d.BranchAmbiguityDiagnostics,
    ambiguity_config: d.BranchAmbiguityConfig,
    config: d.BranchCompetitionConfig,
    broadband: np.ndarray,
    evidence_cache: dict[tuple[int, int], tuple[float, float]],
) -> d._BranchState:
    dt = float(task023c.time_s[frame_index] - task023c.time_s[previous_frame])
    predicted = state.current_frequency_hz + state.recent_slope_hz_per_s * dt
    residual = abs(candidate.transition_frequency_hz - predicted)
    tolerance = config.link_base_hz + config.maximum_rate_hz_per_s * abs(dt)
    link_quality = math.exp(-0.5 * (residual / tolerance) ** 2)
    broken = residual > tolerance
    identity = state.identity_support * (0.10 if broken else 0.90 + 0.10 * link_quality)
    key = (frame_index, candidate.candidate_rank)
    if key not in evidence_cache:
        support = _rank_limited_support(
            candidate_set,
            frame_index,
            candidate.transition_frequency_hz,
            tolerance_hz=ambiguity_config.link_base_hz,
            context_frames=max(1, ambiguity_config.minimum_persistent_frames // 2),
            rank_limit=ambiguity_config.maximum_candidate_rank,
        )
        node = float(node_cost_components(candidate, candidate_set.config)["total_candidate_node_cost"])
        evidence_cache[key] = (support, node)
    support, node = evidence_cache[key]
    changed = candidate.transition_frequency_hz != task023c.strongest.frequency_hz[frame_index]
    spectral_cost = config.spectral_weight * node
    persistence_cost = config.persistence_weight * (1.0 - support)
    anchor_cost = config.identity_weight * (1.0 - identity)
    if broken:
        anchor_cost += config.identity_break_penalty
    ambiguity_cost = config.ambiguity_weight * (1.0 - ambiguity.branch_ambiguity[frame_index]) * float(changed)
    elevated = max(float(broadband[frame_index] - config.broadband_z_threshold), 0.0)
    broadband_cost = config.broadband_weight * min(elevated, 10.0) * float(changed)
    deviation = abs(candidate.transition_frequency_hz - task023c.strongest.frequency_hz[frame_index])
    deviation_cost = config.deviation_weight * deviation / 100.0e6
    incremental = spectral_cost + persistence_cost + anchor_cost + ambiguity_cost + broadband_cost + deviation_cost
    observed_slope = (candidate.transition_frequency_hz - state.current_frequency_hz) / dt
    slope = config.slope_memory * state.recent_slope_hz_per_s + (1.0 - config.slope_memory) * observed_slope
    return d._BranchState(
        candidate.transition_frequency_hz,
        slope,
        identity,
        state.total_cost + incremental,
        state.spectral_cost + spectral_cost,
        state.persistence_cost + persistence_cost,
        state.anchor_cost + anchor_cost,
        state.ambiguity_cost + ambiguity_cost,
        state.broadband_cost + broadband_cost,
        state.deviation_cost + deviation_cost,
        (*state.frequencies_hz, float(candidate.transition_frequency_hz)),
        (*state.ranks, candidate.candidate_rank),
        (*state.identities, float(identity)),
        (*state.local_supports, float(support)),
        (*state.increments, (spectral_cost, persistence_cost, anchor_cost, ambiguity_cost, broadband_cost, deviation_cost)),
    )

