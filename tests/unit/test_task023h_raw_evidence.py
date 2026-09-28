"""Physical/statistical and immutability contracts for the read-only H auditor."""
from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pytest

from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023g_retention_audit as g
from dps_studio.research import task023h_pair_audit as a
from dps_studio.research import task023h_raw_evidence as e
from dps_studio.research.task023e_waveform_benchmark import (
    PROFILES, ambiguous_pair, generate_case, profile_input,
)
from scripts import run_task023d_smooth_branch_rescue as legacy
from scripts import run_task023f_proposal_recovery as runner
from scripts.run_task023h_raw_audit import configs, fresh_case


def test_hilbert_reconstructs_known_complex_tone_and_preserves_input() -> None:
    t = np.arange(4096, dtype=float)/4096
    v = np.cos(2*np.pi*128*t+.3)
    saved = v.copy()
    z = e.analytic_signal(t, v)
    np.testing.assert_allclose(z, np.exp(1j*(2*np.pi*128*t+.3)), atol=3e-13)
    np.testing.assert_array_equal(v, saved)


def test_phase_integration_uses_actual_nonuniform_raw_dt() -> None:
    t = np.array([0., .01, .025, .027, .05])
    frequency = 3.+2*t
    np.testing.assert_allclose(e.integrate_phase(t, frequency), 2*np.pi*(3*t+t*t))


def test_phase_integral_chirp_matches_analytic_not_frame_spacing() -> None:
    t = np.arange(1024)/40e9
    f_hz = 2e9+1e15*t
    np.testing.assert_allclose(e.integrate_phase(t, f_hz), 2*np.pi*(2e9*t+.5e15*t*t))


@pytest.mark.parametrize('scale', [.01, .4, 3., 100.])
def test_all_four_statistics_are_global_amplitude_scale_invariant(scale: float) -> None:
    t = np.arange(2048)/40e9
    z = np.asarray(np.exp(2j*np.pi*2e9*t)+.7*np.exp(2j*np.pi*3e9*t), dtype=np.complex128)
    frequency = np.full(len(t), 2e9)
    before = e.demodulated_evidence(t, z, frequency, 768/40e9)
    after = e.demodulated_evidence(t, scale*z, frequency, 768/40e9)
    for feature in e.FEATURES:
        assert getattr(before, feature) == pytest.approx(getattr(after, feature), abs=1e-12)


def test_normalization_does_not_establish_identity_of_weaker_component() -> None:
    t = np.arange(4000)/40e9
    z = np.asarray(.3*np.exp(2j*np.pi*2e9*t)+np.exp(2j*np.pi*3e9*t), dtype=np.complex128)
    target = e.demodulated_evidence(t, z, np.full(len(t), 2e9), 768/40e9)
    nuisance = e.demodulated_evidence(t, z, np.full(len(t), 3e9), 768/40e9)
    assert target.E1 < nuisance.E1


def test_complex_amplitude_analytic_elimination_and_segment_gain() -> None:
    t = np.arange(4000)/40e9
    amplitudes = np.repeat(np.array([1+2j, -.5j, -2+1j, 1-1j]), 1000)
    z = amplitudes*np.exp(2j*np.pi*2e9*t)
    result = e.demodulated_evidence(t, z, np.full(len(t), 2e9), 768/40e9)
    assert result.E4raw == pytest.approx(1.)
    assert result.E4raw > result.E1
    expected = abs(np.mean(amplitudes))**2 / np.mean(abs(amplitudes)**2)
    assert result.E1 == pytest.approx(expected)


@pytest.mark.parametrize('feature', ['E1', 'E2', 'E3', 'E4raw'])
def test_matched_single_component_has_maximum_support(feature: str) -> None:
    t = np.arange(4096)/40e9
    z = np.exp(2j*np.pi*2e9*t)
    scores = e.demodulated_evidence(t, z, np.full(len(t), 2e9), 768/40e9)
    assert getattr(scores, feature) == pytest.approx(1.)


@pytest.mark.parametrize('array_kind', ['voltage', 'frequency'])
def test_nan_is_never_filled(array_kind: str) -> None:
    t = np.arange(64)/40e9
    if array_kind == 'voltage':
        v = np.ones(64)
        v[13] = np.nan
        with pytest.raises(ValueError, match='NONFINITE_RAW_INPUT'):
            e.analytic_signal(t, v)
        assert np.isnan(v[13])
    else:
        frequency = np.ones(64)
        frequency[13] = np.nan
        score = e.demodulated_evidence(t, np.ones(64, dtype=complex), frequency, 768/40e9)
        assert np.isnan(score.E1) and 'NONFINITE' in score.quality


def test_low_amplitude_phase_is_masked_not_silently_interpolated() -> None:
    t = np.arange(200)/40e9
    z = np.exp(2j*np.pi*2e9*t)
    z[20:180] = 0
    score = e.demodulated_evidence(t, z, np.full(200, 2e9), 768/40e9)
    assert score.samples == 200
    assert np.isnan(score.E3) and score.quality == 'LOW_PHASE_COVERAGE'


def test_zero_signal_returns_nan_quality() -> None:
    t = np.arange(64)/40e9
    score = e.demodulated_evidence(t, np.zeros(64, dtype=complex), np.ones(64), 768/40e9)
    assert score.quality == 'ZERO_AMPLITUDE_PHASE_UNDEFINED'
    assert np.isnan(score.E1)


def test_raw_grid_is_not_resampled() -> None:
    t = np.array([0., 1., 2.2, 3.])
    with pytest.raises(ValueError, match='NONUNIFORM'):
        e.analytic_signal(t, np.ones(4))


def test_proposal_model_is_explicit_and_does_not_extrapolate_or_cross_nan() -> None:
    t = np.arange(10, dtype=float)
    mask, frequency = e.proposal_model(t, np.array([7., 2.]), np.array([17., 12.]))
    np.testing.assert_array_equal(t[mask], np.arange(2., 8.))
    np.testing.assert_array_equal(frequency, np.arange(12., 18.))
    with pytest.raises(ValueError, match='NONFINITE_PROPOSAL'):
        e.proposal_model(t, np.array([2., 7.]), np.array([12., np.nan]))


def test_identity_swap_observation_scores_exactly_identical() -> None:
    first, second = ambiguous_pair(0)
    np.testing.assert_array_equal(first.record.voltage_v, second.record.voltage_v)
    assert not np.array_equal(first.truth_hz, second.truth_hz)
    results = []
    for case in (first, second):
        z = e.analytic_signal(case.record.time_s, case.record.voltage_v)
        results.append([e.demodulated_evidence(case.record.time_s, z, template,
            768/40e9).row() for template in (first.truth_hz, second.truth_hz)])
    assert results[0] == results[1]


def test_truth_signature_boundary_and_no_tracker_dependency() -> None:
    for func in (e.analytic_signal, e.demodulated_evidence, e.evidence_for_proposal,
                 f.generate_proposals, f.select_proposal):
        assert not {'truth', 'gt', 'label', 'target_identity'} & inspect.signature(func).parameters.keys()
    assert 'truth' in inspect.signature(a.audit_searches).parameters
    source = inspect.getsource(e)
    assert 'task023f_proposals' not in source and 'truth_hz' not in source


def test_same_fresh_generator_only_seed_changed() -> None:
    case = fresh_case('amplitude_exchange', 8)
    expected = generate_case('amplitude_exchange', 8, seed=2408408)
    np.testing.assert_array_equal(case.record.voltage_v, expected.record.voltage_v)
    assert case.parameters == expected.parameters


def test_real_stft_and_candidate_set_unchanged_after_evidence() -> None:
    case = fresh_case('correct_and_fast', 8)
    stft, candidates, _, _ = profile_input(case, PROFILES[0])
    before = a.fingerprint((case.record.voltage_v, stft.spectrum, candidates))
    z = e.analytic_signal(case.record.time_s, case.record.voltage_v)
    frequency = np.array([frame[0].transition_frequency_hz for frame in candidates.candidates_by_frame])
    e.evidence_for_proposal(case.record.time_s, z, candidates.time_s[:4], frequency[:4], 768/40e9)
    assert a.fingerprint((case.record.voltage_v, stft.spectrum, candidates)) == before
    assert max(map(len, candidates.candidates_by_frame)) <= 20
    assert [(p.window_length_samples, p.overlap_samples, p.nfft) for p in PROFILES] == [
        (768, 640, 4096), (512, 384, 4096)]


def test_frozen_graph_costs_selector_and_candidates_unchanged() -> None:
    case = legacy._smooth_case('H_AUDIT_TEST', 'trailing_smooth')
    candidates = legacy._candidate_set(case)
    original = runner.original_e4(candidates, case.stft)
    ambiguity, config = configs()
    broadband = f.broadband_evidence(case.stft)
    window = next(w for w in f.windows(original, f.ProposalConfig(), ambiguity)
                  if len(w.indices) >= 2 and w.anchor is not None)
    search = f.generate_proposals(window, original, candidates, ambiguity, config, broadband, diversity=True)
    before = a.fingerprint((search, candidates, original, case.stft.spectrum))
    selection = f.select_proposal(search, original, candidates, ambiguity, config, broadband)
    replay = g.Replay(search, original, candidates, ambiguity, config, broadband)
    for proposal in search.proposals:
        assert replay.state(proposal.hypothesis_id) == proposal.state
    nodes = {n.hypothesis_id: n for n in search.lineage}
    for proposal in search.proposals:
        path = a.prefix_view(search, proposal.hypothesis_id, nodes)
        assert path.frequencies == proposal.state.frequencies_hz
        assert path.cost == proposal.state.total_cost
    assert a.fingerprint((search, candidates, original, case.stft.spectrum)) == before
    assert f.select_proposal(search, original, candidates, ambiguity, config, broadband) == selection


def test_single_component_reference_agrees_with_explicit_fisher() -> None:
    t = np.arange(4096)/40e9
    amplitude, sigma, freq = 1., .2, 2e9
    phase = 2*np.pi*freq*t+.3
    jacobian = np.column_stack((np.cos(phase), -amplitude*np.sin(phase),
                               -amplitude*np.sin(phase)*2*np.pi*(t-t.mean())))
    fisher = jacobian.T@jacobian/sigma**2
    exact = float(np.sqrt(np.linalg.inv(fisher)[2, 2]))
    assert e.single_component_reference(t, amplitude, sigma) == pytest.approx(exact, rel=.005)


@pytest.mark.parametrize(('difference', 'credit'), [(1., 1.), (-1., 0.), (0., .5), (np.nan, 0.)])
def test_ranking_missing_and_ties_are_not_success(difference: float, credit: float) -> None:
    assert a.ranking_credit(difference) == credit


def test_local_prefix_never_masquerades_as_complete_near_path() -> None:
    path = a.PathView(1, tuple(range(8)), (1e9,)*4+(2e9,)*4, (0,)*8, 1., 0)
    truth = np.full(8, 2e9)
    assert a.truth_error(path, truth)[0] > 200e6
    assert a.truth_error(path, truth, local=True)[0] == 0


def test_no_gt_proposal_mutation_from_audit() -> None:
    source = inspect.getsource(a)
    for forbidden in ('generate_proposals(', 'apply_searches(', 'select_proposal('):
        assert forbidden not in source
    params: Any = inspect.signature(e.evidence_for_proposal).parameters
    assert set(params) == {'raw_time_s', 'analytic', 'knot_time_s', 'knot_frequency_hz', 'stft_window_s'}
