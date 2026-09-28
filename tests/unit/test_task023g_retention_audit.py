"""Tests of implemented Phase A; unexecuted algorithms are never claimed tested."""
from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023g_retention_audit as g
from scripts import run_task023d_smooth_branch_rescue as legacy
from scripts import run_task023f_proposal_recovery as runner


@pytest.fixture(scope='module')
def replay_fixture() -> tuple[Any, ...]:
    case = legacy._smooth_case('G_AUDIT_TEST', 'trailing_smooth')
    candidates = legacy._candidate_set(case)
    original = runner.original_e4(candidates, case.stft)
    configs = runner.frozen_configs()
    ambiguity = d.BranchAmbiguityConfig(**configs['ambiguity_config'])
    config = f.effective_e4(d.BranchCompetitionConfig(**configs['branch_config']))
    broadband = f.broadband_evidence(case.stft)
    window = next(w for w in f.windows(original, f.ProposalConfig(), ambiguity)
                  if w.kind == 'EDGE' and len(w.indices) >= 2)
    search = f.generate_proposals(window, original, candidates, ambiguity, config, broadband, diversity=True)
    replay = g.Replay(search, original, candidates, ambiguity, config, broadband)
    return case, candidates, original, config, search, replay


def test_parent_replay_exact_frozen_cost_identity_terminal(replay_fixture: tuple[Any, ...]) -> None:
    _, _, _, _, search, replay = replay_fixture
    for node in search.lineage[:320]:
        state = replay.state(node.hypothesis_id)
        assert state.total_cost == node.score
        assert state.identity_support == node.identity
    for proposal in search.proposals:
        assert replay.state(proposal.hypothesis_id) == proposal.state


def test_probe_candidate_stft_strongest_and_score_immutable(replay_fixture: tuple[Any, ...]) -> None:
    case, candidates, original, config, search, replay = replay_fixture
    before = (candidates.candidates_by_frame, case.stft.spectrum.copy(),
              original.task023c.strongest.frequency_hz.copy(), config)
    truth = original.task023c.strongest.frequency_hz.copy()
    node = search.lineage[0]
    replay.probe(replay.state(node.hypothesis_id), node.offset, truth)
    assert candidates.candidates_by_frame == before[0]
    np.testing.assert_array_equal(case.stft.spectrum, before[1])
    np.testing.assert_array_equal(original.task023c.strongest.frequency_hz, before[2])
    assert config == before[3] and config.beam_width == 8


def test_one_step_probe_cannot_be_terminal(replay_fixture: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, original, _, search, replay = replay_fixture
    called = []
    extend = replay.extend
    def recorded(state: d._BranchState, previous: int, frame: int, rank: int) -> d._BranchState:
        called.append(frame)
        return cast(d._BranchState, extend(state, previous, frame, rank))
    monkeypatch.setattr(replay, 'extend', recorded)
    node = search.lineage[0]
    state = replay.state(node.hypothesis_id)
    called.clear()
    before = search.proposals
    probe = replay.probe(state, node.offset, original.task023c.strongest.frequency_hz)
    assert called and set(called) == {search.window.indices[node.offset + 1]}
    assert isinstance(probe, g.Probe) and not isinstance(probe, f.SearchResult)
    assert search.proposals == before


def test_window_end_is_unresolved_not_no_valid_descendant(replay_fixture: tuple[Any, ...]) -> None:
    _, _, original, _, search, replay = replay_fixture
    probe = replay.probe(search.proposals[0].state, len(search.window.indices) - 1,
                         original.task023c.strongest.frequency_hz)
    assert not probe.available and probe.score_rank is None
    assert g.category(one_step=False, family_collision=False, duplicate=False,
                      valid_descendant=False, persistent=False, has_future=False) == 'UNRESOLVED_WINDOW_END'


@pytest.mark.parametrize('cost,competitors,expected', [(1., (), 1), (2., (1., 2., 3.), 3),
                                                     (0., (1., 2.), 1)])
def test_lower_cost_and_conservative_ties(cost: float, competitors: tuple[float, ...], expected: int) -> None:
    assert g.score_rank(cost, competitors) == expected


@pytest.mark.parametrize('flags,expected', [
    ((True, True, True, True, False, True), 'TEMPORARY_SCORE_DIP'),
    ((False, True, True, True, False, True), 'FAMILY_COLLISION'),
    ((False, False, True, True, False, True), 'DUPLICATE_OCCUPANCY'),
    ((False, False, False, False, False, True), 'NO_VALID_DESCENDANT'),
    ((False, False, False, True, True, True), 'PERSISTENT_SCORE_INFERIOR'),
    ((False, False, False, True, False, True), 'UNRESOLVED_SHORT_OR_DELAYED_RECOVERY'),
])
def test_taxonomy_keeps_unresolved_distinct(flags: tuple[bool, ...], expected: str) -> None:
    keys = ('one_step', 'family_collision', 'duplicate', 'valid_descendant', 'persistent', 'has_future')
    assert g.category(**dict(zip(keys, flags, strict=True))) == expected


def test_no_truth_labels_enter_frozen_generator_or_selector() -> None:
    for function in (f.generate_proposals, f.select_proposal, f.windows):
        names = inspect.signature(function).parameters
        assert not {'truth', 'gt', 'manual_reference_interval'} & names.keys()
    assert 'truth' in inspect.signature(g.audit_event).parameters


def test_frozen_acceptance_evidence_exact(replay_fixture: tuple[Any, ...]) -> None:
    _, _, _, config, search, replay = replay_fixture
    for node in search.lineage[:30]:
        state = replay.state(node.hypothesis_id)
        expected = (node.identity >= config.minimum_identity_support
                    and node.local_support >= config.minimum_local_support
                    and (replay.broadband[node.frame] < config.broadband_z_threshold
                         or node.local_support >= config.broadband_support_floor))
        assert g.plausible(state, config, float(replay.broadband[node.frame])) == expected


def test_no_algorithm_gate_or_manual_interval_in_audit() -> None:
    assert not hasattr(g, 'generate_proposals')
    assert not hasattr(g, 'informative_gate')
    assert 'manual_reference_interval' not in inspect.signature(g.Replay).parameters


def test_raw_result_exclusion() -> None:
    raw = runner.ROOT / 'data/raw'
    assert not runner.eligible_raw(raw / 'analysis_RESULT.dat', raw)
    assert runner.eligible_raw(raw / 'numerical.dat', raw)
    assert not runner.eligible_raw(runner.ROOT.parent / 'DPS_Studio/data/raw/x.csv', raw)


def test_frozen_f_source_production_and_raw_hashes() -> None:
    manifest = runner.ROOT / 'artifacts/task023g_beam_retention_interval_gate/20260913T082646Z/frozen_manifest.json'
    snapshot = json.loads(manifest.read_text(encoding='utf-8'))
    for name, root in [('Research', runner.ROOT), ('Production', runner.ROOT.parent / 'DPS_Studio')]:
        for relative, digest in snapshot['hashes'][name].items():
            path = root / relative
            if 'raw' in path.parts or name == 'Production' or 'task023f' in path.name:
                assert runner.sha256(path) == digest, Path(relative)


def test_saved_live_width_remains_eight(replay_fixture: tuple[Any, ...]) -> None:
    _, _, _, _, search, _ = replay_fixture
    for frame in search.window.indices:
        assert sum(n.retained for n in search.lineage if n.frame == frame) <= 8
    assert len(search.proposals) <= 8 and not search.diagnostic_only


def test_cohort_follows_late_suffix_prune(replay_fixture: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, _, search, replay = replay_fixture
    template = search.lineage[0]
    nodes = [replace(template, hypothesis_id=1, parent_id=0, frame=0, frequency_hz=1e9, retained=True),
             replace(template, hypothesis_id=2, parent_id=0, frame=0, frequency_hz=3e9, retained=True),
             replace(template, hypothesis_id=3, parent_id=1, frame=1, frequency_hz=3e9, retained=True),
             replace(template, hypothesis_id=4, parent_id=2, frame=1, frequency_hz=3e9, retained=True),
             replace(template, hypothesis_id=5, parent_id=3, frame=2, frequency_hz=3e9, retained=False),
             replace(template, hypothesis_id=6, parent_id=4, frame=2, frequency_hz=3e9, retained=True)]
    synthetic = replace(search, window=replace(search.window, indices=(0, 1, 2)), lineage=tuple(nodes))
    monkeypatch.setattr(replay, 'search', synthetic)
    monkeypatch.setattr(replay, 'frames', {i: [n for n in nodes if n.frame == i] for i in range(3)})
    # Correct at frame 0, only dies at frame 2; no target label at later frames.
    assert replay.cohort_loss(0, np.asarray([1e9, np.nan, np.nan])) == (2, (5,))


def test_cohort_rejects_false_terminal_missing(replay_fixture: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, _, search, replay = replay_fixture
    node = replace(search.lineage[0], hypothesis_id=1, parent_id=0, frame=0, frequency_hz=1e9, retained=True)
    monkeypatch.setattr(replay, 'search', replace(search, window=replace(search.window, indices=(0,)), lineage=(node,)))
    monkeypatch.setattr(replay, 'frames', {0: [node]})
    with pytest.raises(AssertionError, match='surviving terminal'):
        replay.cohort_loss(0, np.asarray([1e9]))


def test_planned_fresh_split_has_no_waveform_profile_leakage() -> None:
    import csv
    output = runner.ROOT / 'artifacts/task023g_beam_retention_interval_gate/20260913T082646Z'
    with (output / 'fresh_split.csv').open(encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len({r['seed'] for r in rows}) == len({r['observation_group'] for r in rows}) == 128
    assert all(r['profiles'] == 'balanced;high_time_resolution' for r in rows)
    assert all(r['used_for_development'] == 'False' for r in rows)
    assert all(int(r['seed']) >= 2307000 and 8 <= int(r['instance']) < 24 for r in rows)


def test_shared_cohort_keeps_each_source_frames_original_interval() -> None:
    from scripts.run_task023g_retention_audit import restore_source_context
    rows = [dict(waveform='x', profile='balanced', window='core', frame=i,
                 first_loss_frame=9, taxonomy='FAMILY_COLLISION') for i in (2, 7)]
    original = [dict(case_id='x', profile='balanced', window_id='core', frame='2',
                     first_loss_frame='', error_start='2', error_end='3'),
                dict(case_id='x', profile='balanced', window_id='core', frame='7',
                     first_loss_frame='8', error_start='7', error_end='8')]
    restore_source_context(rows, original)
    assert [row['original_first_loss_frame'] for row in rows] == ['', '8']
    assert [row['error_start'] for row in rows] == [2, 7]
    assert all(row['first_loss_frame'] == 9 and row['taxonomy'] == 'FAMILY_COLLISION' for row in rows)
