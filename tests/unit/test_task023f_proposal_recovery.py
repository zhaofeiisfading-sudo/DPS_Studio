"""Mechanism, equivalence, lineage, label isolation, and oracle invariants."""
from __future__ import annotations

import csv
import inspect
import json
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_audit as audit
from dps_studio.research import task023f_proposals as f
from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, PROFILES, ambiguous_pair, array_hash, generate_case, oscillator_phase, profile_input,
)
from scripts import run_task023d_smooth_branch_rescue as legacy
from scripts import run_task023f_proposal_recovery as runner


@pytest.fixture(scope='module')
def fixture() -> tuple[Any, ...]:
    case = legacy._smooth_case('F_TEST', 'trailing_smooth')
    candidates = legacy._candidate_set(case)
    original = runner.original_e4(candidates, case.stft)
    ambiguity = d.BranchAmbiguityConfig(**runner.frozen_configs()['ambiguity_config'])
    config = f.effective_e4(d.BranchCompetitionConfig(**runner.frozen_configs()['branch_config']))
    broadband = f.broadband_evidence(case.stft)
    registry = f.windows(original, f.ProposalConfig(), ambiguity)
    searches = tuple(f.generate_proposals(w, original, candidates, ambiguity, config, broadband)
                     for w in registry if w.kind == 'EDGE' and w.indices)
    return case, candidates, original, ambiguity, config, broadband, registry, searches


def test_p0_exact_terminal_output_rank_and_acceptance(fixture: tuple[Any, ...]) -> None:
    _, candidates, original, ambiguity, config, broadband, _, searches = fixture
    result = f.apply_searches(searches, original, candidates, ambiguity, config, broadband)
    np.testing.assert_array_equal(result.final_frequency_hz, original.final_frequency_hz)
    np.testing.assert_array_equal(result.final_rank, original.final_rank)
    for search, selection in zip(searches, result.selections, strict=True):
        w = search.window
        best = d._search_branch(w.indices, w.anchor, w.slope, original.task023c, candidates,
                               original.ambiguity, ambiguity, config, broadband)
        assert search.proposals[0].state == best
        decision = original.leading_branch_decision if w.window_id == 'edge_left' else original.trailing_branch_decision
        assert selection.status == decision.status.value
        assert selection.accepted == tuple(step.modified for step in decision.steps)


def test_graph_strongest_stft_immutable_and_provenance(fixture: tuple[Any, ...]) -> None:
    case, candidates, original, ambiguity, config, broadband, _, searches = fixture
    snapshot = candidates.candidates_by_frame
    spectrum, strongest = case.stft.spectrum.copy(), original.task023c.strongest.frequency_hz.copy()
    result = f.apply_searches(searches, original, candidates, ambiguity, config, broadband)
    assert candidates.candidates_by_frame == snapshot
    np.testing.assert_array_equal(case.stft.spectrum, spectrum)
    np.testing.assert_array_equal(original.task023c.strongest.frequency_hz, strongest)
    for i, value in enumerate(result.final_frequency_hz):
        assert value in [c.transition_frequency_hz for c in snapshot[i]]
    assert np.all(np.isfinite(result.final_frequency_hz))


def test_permission_does_not_change_trust_or_score(fixture: tuple[Any, ...]) -> None:
    _, _, original, ambiguity, _, _, registry, _ = fixture
    before = original.task023c.trust.trust_score.copy()
    assert f.windows(original, f.ProposalConfig(challenge_core=True), ambiguity) == registry
    np.testing.assert_array_equal(original.task023c.trust.trust_score, before)


def test_retained_core_requires_explicit_acceptance(fixture: tuple[Any, ...]) -> None:
    _, candidates, original, ambiguity, config, broadband, _, searches = fixture
    result = f.apply_searches(searches, original, candidates, ambiguity, config, broadband)
    changed_core = original.trimmed_core_mask & (result.final_frequency_hz != result.strongest_frequency_hz)
    assert not np.any(changed_core & ~(result.permission_mask & result.accepted_mask))


def test_b32_cannot_enter_final_selector(fixture: tuple[Any, ...]) -> None:
    _, candidates, original, ambiguity, config, broadband, _, searches = fixture
    diagnostic = replace(searches[0], diagnostic_only=True, beam_width=32)
    with pytest.raises(ValueError, match='diagnostic'):
        f.select_proposal(diagnostic, original, candidates, ambiguity, config, broadband)
    with pytest.raises(ValueError, match='diagnostic'):
        f.select_proposal(replace(diagnostic, diagnostic_only=False), original, candidates,
                          ambiguity, config, broadband)
    with pytest.raises(ValueError, match='B8'):
        f.generate_proposals(searches[0].window, original, candidates, ambiguity,
                             replace(config, beam_width=32), broadband)


def test_empty_edge_matches_frozen_no_edge_reason(fixture: tuple[Any, ...]) -> None:
    _, candidates, original, ambiguity, config, broadband, _, _ = fixture
    window = f.Window('edge_left', (), 0, 0., 'EDGE', 'NO_EDGE')
    search = f.generate_proposals(window, original, candidates, ambiguity, config, broadband)
    selection = f.select_proposal(search, original, candidates, ambiguity, config, broadband)
    assert selection.status == 'KEEP_NO_EDGE' and not selection.accepted


def test_family_grouping_and_diversity_retention(fixture: tuple[Any, ...]) -> None:
    state = fixture[-1][0].proposals[0].state
    states = tuple(replace(state, total_cost=float(i), frequencies_hz=(1e9,) * 4,
                           identity_support=1., local_supports=(1.,)) for i in range(9))
    other = replace(states[-1], frequencies_hz=(2e9,) * 4, total_cost=7.5)
    states = (*states[:8], other)
    families = f.family_ids(states)
    assert families == (0,) * 8 + (1,)
    keep = f.retained_indices(states, families, 8, True, fixture[4], 0.)
    assert len(keep) == 8 and 0 in keep and 8 in keep
    assert keep == f.retained_indices(states, f.family_ids(states), 8, True, fixture[4], 0.)
    assert 8 not in f.retained_indices((*states[:8], replace(other, identity_support=.1)),
                                     families, 8, True, fixture[4], 0.)


def test_cached_arithmetic_exact_for_every_candidate(fixture: tuple[Any, ...]) -> None:
    _, candidates, original, ambiguity, config, broadband, _, searches = fixture
    cache: dict[tuple[int, int], tuple[float, float]] = {}
    window = searches[0].window
    anchor = window.anchor
    for slope in (-8e15, 0., 7e15):
        state = d._initial_state(original.task023c, anchor, slope)
        for candidate in candidates.candidates_by_frame[window.indices[0]]:
            args = (state, candidate, anchor, window.indices[0], original.task023c,
                    candidates, original.ambiguity, ambiguity, config, broadband)
            assert f._extend_cached(*args, cache) == d._extend_branch(*args)


def test_trigger_window_anchor_tie_and_no_anchor(fixture: tuple[Any, ...]) -> None:
    _, _, original, ambiguity, _, _, _, _ = fixture
    core = original.trimmed_cores[0]
    n = len(original.task023c.time_s)
    rank = np.zeros(n, dtype=int)
    value = np.zeros(n)
    start = core.frame_start + 4
    rank[start:start + 4] = 2
    diagnostics = replace(original.ambiguity, best_alternative_rank=rank, branch_ambiguity=value)
    changed = replace(original, ambiguity=diagnostics)
    windows = [w for w in f.windows(changed, f.ProposalConfig(), ambiguity) if w.kind == 'CORE']
    assert len(windows) == 1 and len(windows[0].indices) == 4
    # Physical floating-point times can break nominal index ties; compare actual distances.
    expected = min((start - 1, start + 4), key=lambda i: (
        min(abs(original.task023c.time_s[i] - original.task023c.time_s[start]),
            abs(original.task023c.time_s[i] - original.task023c.time_s[start + 3])), i))
    assert windows[0].anchor == expected
    rank[:] = 2
    changed = replace(original, ambiguity=replace(diagnostics, best_alternative_rank=rank))
    windows = [w for w in f.windows(changed, f.ProposalConfig(), ambiguity) if w.kind == 'CORE']
    assert all(w.anchor is None and w.status == 'NO_ELIGIBLE_ANCHOR' for w in windows)


def test_unsupported_single_frame_cannot_trigger_core(fixture: tuple[Any, ...]) -> None:
    _, _, original, ambiguity, _, _, _, _ = fixture
    n = len(original.task023c.time_s)
    rank = np.zeros(n, dtype=int)
    rank[original.trimmed_cores[0].frame_start + 2] = 2
    diagnostics = replace(original.ambiguity, best_alternative_rank=rank,
                          branch_ambiguity=np.zeros(n))
    windows = f.windows(replace(original, ambiguity=diagnostics), f.ProposalConfig(), ambiguity)
    assert not any(w.kind == 'CORE' for w in windows)


def test_lineage_parent_ids_and_width(fixture: tuple[Any, ...]) -> None:
    for search in fixture[-1]:
        seen = {0}
        for node in search.lineage:
            assert node.parent_id in seen
            assert node.hypothesis_id not in seen
            seen.add(node.hypothesis_id)
        for offset in set(node.offset for node in search.lineage):
            assert sum(node.retained for node in search.lineage if node.offset == offset) <= 8


def test_first_pruning_is_causal_not_terminal_inference() -> None:
    def node(hid: int, parent: int, frame: int, frequency: float, retained: bool) -> f.Expansion:
        return f.Expansion(hid, parent, frame, frame, 0., 1., 9, .5, 2, frequency,
                           (frequency,), 1., 1., 1, 0, retained)
    trace = (node(1, 0, 0, 1e9, True), node(2, 1, 1, 1e9, False),
             node(3, 1, 1, 2e9, True), node(4, 3, 2, 1e9, True))
    search = f.SearchResult(f.Window('tiny', (0, 1, 2), 3, 0., 'EDGE', 'ELIGIBLE'), (), trace, 8, False)
    rows = audit.lineage_audit(search, np.full(3, 1e9), np.ones(3, dtype=bool))
    assert rows[1]['first_loss_frame'] == 1
    assert rows[1]['first_loss_reason'] == 'EXPANDED_THEN_PRUNED'
    assert rows[2]['retained_consistent'] == 0  # re-entry is not the lost lineage


def test_oracle_never_stitches_complete_proposals(fixture: tuple[Any, ...]) -> None:
    state = fixture[-1][0].proposals[0].state
    proposals = tuple(f.Proposal(i + 1, replace(state, frequencies_hz=path)) for i, path in enumerate(
        ((1e9, 2e9), (2e9, 1e9))))
    search = f.SearchResult(f.Window('tiny', (0, 1), 2, 0., 'CORE', 'ELIGIBLE'), proposals, (), 8, False)
    values = audit.oracle(np.full(2, 3e9), np.full(2, 1e9), (search,))
    assert values['FEASIBLE_MIN_SSE']['rmse_mhz'] == pytest.approx(np.sqrt(.5) * 1000)
    assert values['FEASIBLE_MIN_WRONG']['wrong_branch'] == .5
    assert values['RELAXED_FRAMEWISE']['rmse_mhz'] == 0.


def test_exhaustive_two_candidate_three_step_graph(fixture: tuple[Any, ...]) -> None:
    _, full, original, ambiguity, config, broadband, _, _ = fixture
    candidates = replace(full, time_s=full.time_s[:4],
                         candidates_by_frame=tuple(frame[:2] for frame in full.candidates_by_frame[:4]))
    window = f.Window('exhaustive', (1, 2, 3), 0, 0., 'CORE', 'ELIGIBLE')
    search = f.generate_proposals(window, original, candidates, ambiguity, config, broadband)
    states = []
    for choices in product((0, 1), repeat=3):
        state = d._initial_state(original.task023c, 0, 0.)
        previous = 0
        for frame, choice in zip(window.indices, choices, strict=True):
            state = d._extend_branch(state, candidates.candidates_by_frame[frame][choice], previous,
                frame, original.task023c, candidates, original.ambiguity, ambiguity, config, broadband)
            previous = frame
        states.append(state)
    states.sort(key=lambda s: (s.total_cost, s.ranks, s.frequencies_hz))
    assert tuple(p.state for p in search.proposals) == tuple(states)
    assert len(search.lineage) == 2 + 4 + 8 and all(node.retained for node in search.lineage)
    truth = np.full(len(original.task023c.time_s), np.nan)
    truth[[1, 2, 3]] = states[-1].frequencies_hz
    values = audit.oracle(original.task023c.strongest.frequency_hz, truth, (search,))
    assert values['FEASIBLE_MIN_SSE']['rmse_mhz'] == 0.


def test_zero_truth_and_zero_intervention_denominators() -> None:
    x = np.array([1e9, 2e9])
    values = audit.metrics(x, x, np.array([1e9, np.nan]))
    assert values['valid_frames'] == 1 and values['precision'] is None and values['harm_rate'] is None
    assert values['no_truth_output_frames'] == 1
    assert audit.metrics(x, x, np.full(2, np.nan))['rmse_mhz'] is None
    assert audit.ratio(0, 0) is None


def test_default_192_hash_compatibility() -> None:
    rows = list(csv.DictReader((runner.E_ROOT / 'fresh_waveform_manifest.csv').open(encoding='utf-8')))
    assert len(rows) == 192
    for row in rows:
        case = generate_case(row['family'], int(row['instance']))
        assert array_hash(case.record.voltage_v) == row['voltage_sha256']
        assert array_hash(case.truth_hz) == row['truth_sha256']


def test_fresh_split_groups_seed_and_physical_instance() -> None:
    groups: set[str] = set()
    for family_index, family in enumerate(FAMILIES):
        for instance in range(8, 24):
            case = runner.fresh_case(family, instance)
            assert case.seed == 2306000 + family_index * 100 + instance
            assert case.observation_group not in groups
            groups.add(case.observation_group)
            assert case.parameters['variant'] == generate_case(family, instance).parameters['variant']
    assert len(groups) == 128


def test_label_swap_never_reaches_generator_or_selector(fixture: tuple[Any, ...]) -> None:
    assert 'truth' not in inspect.signature(f.generate_proposals).parameters
    assert 'truth' not in inspect.signature(f.select_proposal).parameters
    a, b = ambiguous_pair(0)
    assert a.observation_group == b.observation_group
    np.testing.assert_array_equal(a.record.voltage_v, b.record.voltage_v)
    assert not np.array_equal(a.truth_hz, b.truth_hz)
    sa, ca, _, _ = profile_input(a, PROFILES[0])
    sb, cb, _, _ = profile_input(b, PROFILES[0])
    assert ca.candidates_by_frame == cb.candidates_by_frame
    np.testing.assert_array_equal(sa.spectrum, sb.spectrum)


def test_phase_integral_and_stft_axes() -> None:
    case = generate_case('correct_and_fast', 1)
    phase = oscillator_phase(case.truth_hz)
    np.testing.assert_allclose(np.diff(phase) * 40e9 / (2 * np.pi), case.truth_hz[:-1], atol=.1)
    stft, _, truth, _ = profile_input(case, PROFILES[0])
    np.testing.assert_array_equal(truth, case.truth_hz[np.rint(stft.time_s * 40e9).astype(int)])
    assert stft.frequency_hz[1] == pytest.approx(40e9 / PROFILES[0].nfft, rel=1e-10)


def test_raw_result_filter_before_reader_and_read_only_hash(tmp_path: Path) -> None:
    raw = tmp_path / 'raw'
    raw.mkdir()
    path = raw / 'input.dat'
    path.write_bytes(b'raw input')
    before = runner.sha256(path)
    assert runner.eligible_raw(path, raw)
    assert not runner.eligible_raw(raw / 'x_RESULT.dat', raw)
    assert not runner.eligible_raw(tmp_path / 'outside.dat', raw)
    assert not runner.eligible_raw(raw / 'image.png', raw)
    assert runner.sha256(path) == before


def test_frozen_e4_constants_and_no_production_writes() -> None:
    config = f.effective_e4(d.BranchCompetitionConfig(**runner.frozen_configs()['branch_config']))
    assert config.beam_width == 8 and config.minimum_identity_support == .62
    assert config.minimum_local_support == .65 and config.branch_acceptance_margin == 2.5
    assert config.deviation_weight == pytest.approx(.009)
    root = runner.ROOT / 'artifacts/task023f_proposal_recall_recovery'
    snapshots = sorted(root.glob('*/freeze_before.json'))
    if snapshots:
        snapshot = json.loads(snapshots[-1].read_text(encoding='utf-8'))
        prod = runner.ROOT.parent / 'DPS_Studio'
        for relative, digest in snapshot['production_hashes'].items():
            assert runner.sha256(prod / relative) == digest
