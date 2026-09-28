"""Label-only retention counterfactuals. This module is never a generator.

The saved live B8 is not changed. Forced descendants are diagnostic probes and
cannot be returned as terminal proposals or accepted output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f


@dataclass(frozen=True)
class Probe:
    available: bool
    plausible: bool
    score_rank: int | None
    cost: float | None
    hypothesis: d._BranchState | None


def plausible(state: d._BranchState, config: d.BranchCompetitionConfig,
              broadband: float) -> bool:
    """Literal frozen per-frame acceptance evidence; not a generation filter."""
    return bool(state.identity_support >= config.minimum_identity_support
        and state.local_supports[-1] >= config.minimum_local_support
        and (broadband < config.broadband_z_threshold
             or state.local_supports[-1] >= config.broadband_support_floor))


def score_rank(cost: float, competitors: tuple[float, ...]) -> int:
    # Ties count ahead, conservatively: no invented favourable tie-break.
    return 1 + sum(value <= cost for value in competitors)


def category(*, one_step: bool, family_collision: bool, duplicate: bool,
             valid_descendant: bool, persistent: bool, has_future: bool) -> str:
    if not has_future:
        return 'UNRESOLVED_WINDOW_END'
    if one_step:
        return 'TEMPORARY_SCORE_DIP'
    if family_collision:
        return 'FAMILY_COLLISION'
    if duplicate:
        return 'DUPLICATE_OCCUPANCY'
    if not valid_descendant:
        return 'NO_VALID_DESCENDANT'
    if persistent:
        return 'PERSISTENT_SCORE_INFERIOR'
    return 'UNRESOLVED_SHORT_OR_DELAYED_RECOVERY'


class Replay:
    """Reconstruct saved states from actual parent IDs and frozen arithmetic."""

    def __init__(self, search: f.SearchResult, original: d.SmoothBranchOptimizationResult,
                 candidates: RidgeCandidateSet, ambiguity: d.BranchAmbiguityConfig,
                 config: d.BranchCompetitionConfig, broadband: np.ndarray) -> None:
        if search.window.anchor is None:
            raise ValueError('Cannot replay without the saved anchor')
        self.search, self.original, self.candidates = search, original, candidates
        self.ambiguity, self.config, self.broadband = ambiguity, config, broadband
        self.nodes = {n.hypothesis_id: n for n in search.lineage}
        self.states = {0: d._initial_state(original.task023c, search.window.anchor, search.window.slope)}
        self.evidence: dict[tuple[int, int], tuple[float, float]] = {}
        self.frames: dict[int, list[f.Expansion]] = {}
        for node in search.lineage:
            self.frames.setdefault(node.frame, []).append(node)

    def extend(self, state: d._BranchState, previous: int, frame: int,
               rank: int) -> d._BranchState:
        candidate = next(c for c in self.candidates.candidates_by_frame[frame] if c.candidate_rank == rank)
        return f._extend_cached(state, candidate, previous, frame, self.original.task023c,
            self.candidates, self.original.ambiguity, self.ambiguity, self.config, self.broadband, self.evidence)

    def state(self, identifier: int) -> d._BranchState:
        chain = []
        cursor = identifier
        while cursor not in self.states:
            chain.append(self.nodes[cursor])
            cursor = self.nodes[cursor].parent_id
        for node in reversed(chain):
            previous = (self.search.window.anchor if node.offset == 0
                        else self.search.window.indices[node.offset - 1])
            assert previous is not None
            state = self.extend(self.states[node.parent_id], previous, node.frame, node.candidate_rank)
            if state.total_cost != node.score or state.identity_support != node.identity:
                raise AssertionError('Frozen replay differs from saved DAG')
            self.states[node.hypothesis_id] = state
        return self.states[identifier]

    def consistent(self, frame: int, start: int, end: int, truth: np.ndarray) -> list[f.Expansion]:
        def near(node: f.Expansion) -> bool:
            while start <= node.frame <= end:
                if abs(node.frequency_hz - truth[node.frame]) > 200e6:
                    return False
                if node.parent_id == 0:
                    break
                node = self.nodes[node.parent_id]
            return True
        return [n for n in self.frames.get(frame, []) if near(n)]

    def cohort_loss(self, source_frame: int, truth: np.ndarray) -> tuple[int, tuple[int, ...]]:
        """First extinction of all descendants carrying a correct source-frame choice.

        Later frames are unrestricted, matching frame-level terminal availability.
        This can reveal pruning AFTER the original strongest-error interval.
        """
        start = self.search.window.indices.index(source_frame)
        alive: set[int] | None = None
        for frame in self.search.window.indices[start:]:
            nodes = [node for node in self.frames.get(frame, [])
                     if (abs(node.frequency_hz - truth[source_frame]) <= 200e6
                         if alive is None else node.parent_id in alive)]
            retained = {node.hypothesis_id for node in nodes if node.retained}
            if not retained:
                if not nodes:
                    raise AssertionError('No structural expansion: cannot label as beam pruning')
                return frame, tuple(node.hypothesis_id for node in nodes)
            alive = retained
        raise AssertionError('Claimed terminal-missing frame has a surviving terminal descendant')

    def probe(self, state: d._BranchState, offset: int, truth: np.ndarray) -> Probe:
        """One forced truth-near step compared with saved next-frame B8 expansions."""
        if offset + 1 >= len(self.search.window.indices):
            return Probe(False, False, None, None, None)
        frame, future = self.search.window.indices[offset:offset + 2]
        descendants = [self.extend(state, frame, future, c.candidate_rank)
                       for c in self.candidates.candidates_by_frame[future]
                       if np.isfinite(truth[future]) and abs(c.transition_frequency_hz - truth[future]) <= 200e6]
        valid = [s for s in descendants if plausible(s, self.config, float(self.broadband[future]))]
        choices = valid or descendants
        if not choices:
            return Probe(False, False, None, None, None)
        best = min(choices, key=lambda s: (s.total_cost, s.ranks, s.frequencies_hz))
        rank = score_rank(best.total_cost, tuple(n.score for n in self.frames.get(future, [])))
        return Probe(True, bool(valid), rank, best.total_cost, best)


def audit_event(replay: Replay, event: dict[str, Any], truth: np.ndarray) -> dict[str, Any]:
    frame = int(event['first_loss_frame'])
    nodes = ([replay.nodes[i] for i in event['cohort_ids']] if 'cohort_ids' in event else
             replay.consistent(frame, int(event['error_start']), int(event['error_end']), truth))
    cut = [n for n in nodes if not n.retained]
    if not cut or any(n.retained for n in nodes):
        raise AssertionError('Claimed first loss is not reproduced by parent-ID audit')
    cut.sort(key=lambda n: (n.score, n.candidate_rank, n.hypothesis_id))
    best = cut[0]
    probes = [(n, replay.probe(replay.state(n.hypothesis_id), n.offset, truth)) for n in cut]
    recovery = [(n, p) for n, p in probes if abs(n.frequency_hz - truth[frame]) <= 200e6
                and p.plausible and p.score_rank is not None and p.score_rank <= 8]
    score_dips = [(n, p) for n, p in recovery if n.expansion_rank > 8]
    chosen, probe = min(score_dips or recovery or probes, key=lambda pair: (
        pair[1].score_rank if pair[1].score_rank is not None else float('inf'), pair[0].score))
    current = replay.frames[frame]
    live = [n for n in current if n.retained]
    # A2 is a measured grouping counterfactual, with original guard and best-state protection.
    states = tuple(replay.state(n.hypothesis_id) for n in current)
    families = tuple(n.family for n in current)
    collision = False
    for node in cut:
        if not any(n.family == node.family and abs(n.frequency_hz - truth[frame]) > 200e6 for n in live):
            continue
        index = current.index(node)
        split = tuple(max(families) + 1 if i == index else family for i, family in enumerate(families))
        if index in f.retained_indices(states, split, 8, True, replay.config, float(replay.broadband[frame])):
            collision = True
            break
    # A3 records a slot occupancy mechanism only for guard-eligible displaced paths.
    duplicates = any(n.family_occupancy > 1 for n in live)
    eligible = any(plausible(replay.state(n.hypothesis_id), replay.config, float(replay.broadband[frame]))
                   and n.score - current[0].score <= replay.config.identity_break_penalty for n in cut)
    duplicate = duplicates and eligible and not collision
    # Four-step forced-label continuation is only a bounded diagnostic, not an oracle bound.
    steps = []
    state = replay.state(chosen.hypothesis_id)
    for offset in range(chosen.offset, min(chosen.offset + 4, len(replay.search.window.indices) - 1)):
        step = replay.probe(state, offset, truth)
        steps.append(step)
        if step.hypothesis is None:
            break
        state = step.hypothesis
    persistent = len(steps) == 4 and all(p.available and p.score_rank is not None and p.score_rank > 8 for p in steps)
    has_future = chosen.offset + 1 < len(replay.search.window.indices)
    future_truth_valid = has_future and bool(np.isfinite(truth[replay.search.window.indices[chosen.offset + 1]]))
    valid = any(p.plausible for _, p in probes)
    return dict(window=event['window_id'], first_loss_frame=frame,
        lineage_id=chosen.hypothesis_id, parent_id=chosen.parent_id, candidate_rank=chosen.candidate_rank,
        score_rank=chosen.expansion_rank, b8_cutoff=chosen.cutoff_score,
        score_gap=chosen.score - chosen.cutoff_score, score_gap_to_best=chosen.score - current[0].score,
        family_id=chosen.family, previous_survival_length=chosen.offset,
        consistent_children_lost=len(cut), representative_best_cost_lineage=best.hypothesis_id,
        first_loss_current_truth_near=bool(abs(chosen.frequency_hz - truth[frame]) <= 200e6),
        future_recovery_existence=bool(recovery), future_score_rank=probe.score_rank,
        raw_cost_dip_recovery=bool(score_dips),
        future_cost=probe.cost, valid_descendant=valid, structural_descendant_exists=any(p.available for _, p in probes),
        family_collision_counterfactual=collision, duplicate_occupancy=duplicate,
        persistent_four_step_inferior=persistent, future_steps_probed=len(steps),
        first_loss_reason='EXPANDED_THEN_PRUNED',
        taxonomy=('UNRESOLVED_NO_FUTURE_TRUTH' if has_future and not future_truth_valid else category(
            one_step=bool(score_dips), family_collision=collision, duplicate=duplicate,
            valid_descendant=valid, persistent=persistent, has_future=has_future)),
        probe_scope='FORCED_LABEL_DESCENDANT_VS_SAVED_B8; not a generated output or strict bound')
