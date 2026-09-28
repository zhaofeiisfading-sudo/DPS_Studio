"""Read-only GT auditor of frozen proposal graphs. Labels stop at this module."""
from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023g_retention_audit as g
from dps_studio.research.task023h_raw_evidence import (
    ComplexArray, FloatArray, evidence_for_proposal,
)


@dataclass(frozen=True)
class PathView:
    identifier: int
    frames: tuple[int, ...]
    frequencies: tuple[float, ...]
    ranks: tuple[int, ...]
    cost: float
    family: int


def fingerprint(value: Any) -> str:
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def prefix_view(search: f.SearchResult, identifier: int,
                nodes: dict[int, f.Expansion]) -> PathView:
    chain = []
    node = nodes[identifier]
    end = node
    while True:
        chain.append(node)
        if node.parent_id == 0:
            break
        node = nodes[node.parent_id]
    chain.reverse()
    return PathView(identifier, tuple(n.frame for n in chain),
        tuple(n.frequency_hz for n in chain), tuple(n.candidate_rank for n in chain),
        end.score, end.family)


def truth_error(path: PathView, truth: FloatArray, local: bool = False) -> tuple[float, float]:
    indices = path.frames[-4:] if local else path.frames
    freq = path.frequencies[-4:] if local else path.frequencies
    if len(indices) < 2 or not np.all(np.isfinite(truth[list(indices)])):
        return float('nan'), float('nan')
    delta = np.asarray(freq) - truth[list(indices)]
    return float(np.max(abs(delta))), float(np.mean(delta**2))


def pick_pair(paths: list[PathView], truth: FloatArray, *, selected: int | None = None,
              correct_ids: set[int] | None = None, wrong_ids: set[int] | None = None,
              local: bool = False) -> tuple[PathView, PathView] | None:
    errors = {p.identifier: truth_error(p, truth, local) for p in paths}
    near = [p for p in paths if errors[p.identifier][0] <= 200e6
            and (correct_ids is None or p.identifier in correct_ids)]
    wrong = [p for p in paths if errors[p.identifier][0] > 200e6
             and (wrong_ids is None or p.identifier in wrong_ids)]
    if not near or not wrong:
        return None
    correct = next((p for p in near if p.identifier == selected),
                   min(near, key=lambda p: (errors[p.identifier][1], p.identifier)))
    competitor = next((p for p in wrong if p.identifier == selected),
                      min(wrong, key=lambda p: (p.cost, p.identifier)))
    return correct, competitor


def score_pair(pair: tuple[PathView, PathView], context: dict[str, Any],
               candidates: RidgeCandidateSet, raw_time: FloatArray, analytic: ComplexArray,
               window_s: float, truth: FloatArray, taxonomy: str,
               scope: str, window_id: str, event_id: str = '') -> dict[str, Any]:
    correct, wrong = pair
    if correct.frames != wrong.frames:
        raise AssertionError('Pair must have exactly matched evidence windows')
    local = scope == 'LOCAL_SUBPATH'
    frames = correct.frames[-4:] if local else correct.frames
    frequencies = [p.frequencies[-4:] if local else p.frequencies for p in pair]
    # GT is used above/below for labels only, never passed to evidence function.
    scores = [evidence_for_proposal(raw_time, analytic, candidates.time_s[list(frames)],
        np.asarray(freq, dtype=float), window_s).row() for freq in frequencies]
    provenance = [[dict(frame=i, rank=rank, frequency_hz=freq,
        candidate_exact=any(c.candidate_rank == rank and c.transition_frequency_hz == freq
                            for c in candidates.candidates_by_frame[i]))
        for i, rank, freq in zip(p.frames, p.ranks, p.frequencies, strict=True)] for p in pair]
    assert all(step['candidate_exact'] for side in provenance for step in side)
    return dict(**context, pair_id=f'{context["waveform"]}:{context["profile"]}:{window_id}:'
        f'{scope}:{event_id}:{correct.identifier}:{wrong.identifier}',
        window=window_id, scope=scope, taxonomy=taxonomy, event_id=event_id,
        proposal_ids=[correct.identifier, wrong.identifier],
        frequency_history=[list(p.frequencies) for p in pair],
        full_frames=list(correct.frames), evidence_frames=list(frames),
        time_start_s=float(min(candidates.time_s[list(frames)])),
        time_end_s=float(max(candidates.time_s[list(frames)])),
        existing_e4_costs=[p.cost for p in pair], branch_family=[p.family for p in pair],
        candidate_provenance=provenance, truth_max_error_hz=[truth_error(p, truth, local)[0] for p in pair],
        truth_mse_hz2=[truth_error(p, truth, local)[1] for p in pair],
        scores=scores, baseline_difference=wrong.cost-correct.cost,
        baseline_scope='FULL_PREFIX_CUMULATIVE_COST' if local else 'MATCHED_FULL_HISTORY_COST',
        complete_terminal=scope == 'TERMINAL', candidate_available=True)


def audit_searches(searches: tuple[f.SearchResult, ...], candidates: RidgeCandidateSet,
                   truth: FloatArray, strongest: FloatArray, raw_time: FloatArray,
                   analytic: ComplexArray, window_s: float, context: dict[str, Any],
                   replays: dict[str, g.Replay],
                   existing_events: list[dict[str, Any]] | None = None,
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strict pairs and explicitly separate local diagnostics; no invented descendants."""
    before = fingerprint(searches)
    pairs: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for search in searches:
        if not search.lineage:
            continue
        nodes = {n.hypothesis_id: n for n in search.lineage}
        terminal_paths = [prefix_view(search, p.hypothesis_id, nodes) for p in search.proposals]
        selected = search.proposals[0].hypothesis_id if search.proposals else None
        for local in (False, True):
            pair = pick_pair(terminal_paths, truth, selected=selected, local=local)
            if pair is not None:
                taxonomy = 'CORRECT_SELECTION_CONTROL' if pair[0].identifier == selected else 'SELECTION_LOSS'
                pairs.append(score_pair(pair, context, candidates, raw_time, analytic, window_s,
                    truth, taxonomy, 'LOCAL_SUBPATH' if local else 'TERMINAL', search.window.window_id,
                    'terminal'))
            ledger.append(dict(**context, window=search.window.window_id, stage='terminal',
                local=local, pair_available=pair is not None, proposals=len(terminal_paths)))
        replay = replays[search.window.window_id]
        events = []
        if existing_events is not None:
            events = [e for e in existing_events if e['window'] == search.window.window_id]
        else:
            missing = [i for i in search.window.indices
                if np.isfinite(truth[i]) and abs(strongest[i]-truth[i]) > 200e6
                and any(abs(c.transition_frequency_hz-truth[i]) <= 200e6
                        for c in candidates.candidates_by_frame[i])
                and not any(abs(p.frequencies[p.frames.index(i)]-truth[i]) <= 200e6
                            for p in terminal_paths)]
            grouped: dict[tuple[int, tuple[int, ...]], list[int]] = {}
            for source in missing:
                key = replay.cohort_loss(source, truth)
                grouped.setdefault(key, []).append(source)
            for (frame, ids), sources in grouped.items():
                event = g.audit_event(replay, dict(window_id=search.window.window_id,
                    first_loss_frame=frame, cohort_ids=ids), truth)
                events.append(dict(event, source_frames=sources, affected_error_frames=len(sources),
                    cohort_ids=ids))
        for index, event in enumerate(events):
            frame = int(event['first_loss_frame'])
            live = {n.hypothesis_id for n in replay.frames[frame] if n.retained}
            if 'cohort_ids' in event:
                cut = set(event['cohort_ids'])
            else:
                # Legacy representative belongs to the saved source cohort. Reconstruct it
                # from its source frames instead of assuming every cut is the same lineage.
                sources = event.get('source_frames', [])
                cut = set()
                for source in sources:
                    loss_frame, ids = replay.cohort_loss(int(source), truth)
                    if loss_frame == frame:
                        cut.update(ids)
                if not cut:
                    cut = {int(event['lineage_id'])}
            views = [prefix_view(search, hid, nodes) for hid in sorted(live | cut)]
            for local in (False, True):
                pair = pick_pair(views, truth, correct_ids=cut, wrong_ids=live, local=local)
                scope = 'LOCAL_SUBPATH' if local else 'PRUNING_PREFIX'
                if pair is not None:
                    pairs.append(score_pair(pair, context, candidates, raw_time, analytic, window_s,
                        truth, event['taxonomy'], scope, search.window.window_id, str(index)))
                ledger.append(dict(**context, **event, scope=scope, stage='pruning',
                    pair_available=pair is not None,
                    exclusion_reason='' if pair else 'NO_MATCHED_ALL_GT_NEAR_PREFIX_VS_WRONG_LIVE'))
    assert fingerprint(searches) == before, 'Audit mutated frozen proposals'
    return pairs, ledger


def ranking_credit(difference: float, tolerance: float = 1e-12) -> float:
    if not np.isfinite(difference):
        return 0.
    return 1. if difference > tolerance else (0. if difference < -tolerance else .5)


def candidate_availability(candidates: RidgeCandidateSet,
                           truth: FloatArray) -> NDArray[np.bool_]:
    return np.asarray([any(abs(c.transition_frequency_hz-truth[i]) <= 200e6 for c in frame)
        for i, frame in enumerate(candidates.candidates_by_frame)], dtype=bool)
