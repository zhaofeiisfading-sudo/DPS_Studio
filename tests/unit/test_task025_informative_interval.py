"""Independent invariants for the research-only interval experiment."""
from __future__ import annotations

import inspect
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from dps_studio.research import task023h_raw_evidence as old
from dps_studio.research import task025_informative_interval as gate
from dps_studio.research.task023e_waveform_benchmark import (
    PROFILES, generate_case, profile_input,
)
from dps_studio.research.task023h_pair_audit import fingerprint
from dps_studio.research.task025_stress_benchmark import evaluation_masks, registered_case


def test_exact_historical_e1_and_unchanged_stft_candidates_raw() -> None:
    case = generate_case('correct_and_fast', 8, 25990001)
    for profile in PROFILES:
        stft, candidates, _, _ = profile_input(case, profile)
        before = fingerprint((stft.spectrum, candidates, case.record.voltage_v))
        time = stft.time_s[:4]
        frequency = np.asarray([frame[0].transition_frequency_hz
                                for frame in candidates.candidates_by_frame[:4]])
        duration = profile.window_length_samples/40e9
        value = gate.strongest_support(case.record.time_s, case.record.voltage_v,
                                      time, frequency, duration)
        analytic = old.analytic_signal(case.record.time_s, case.record.voltage_v)
        for i, center in enumerate(time):
            mask = ((case.record.time_s >= center-duration/2) &
                    (case.record.time_s < center+duration/2))
            expected = old.demodulated_evidence(case.record.time_s[mask], analytic[mask],
                np.full(int(mask.sum()), frequency[i]), duration)
            assert value.e1[i] == expected.E1
            assert value.analytic_rms_v[i] == expected.amplitude_rms_v
        assert before == fingerprint((stft.spectrum, candidates, case.record.voltage_v))
        assert all(len(frame) <= 20 for frame in candidates.candidates_by_frame)


def test_calibration_order_statistic_is_highest_feasible_with_ties() -> None:
    values = np.arange(1000, dtype=float)
    target = np.ones(1000, dtype=bool)
    threshold = gate.calibration_threshold(values, target, split='CALIBRATION')
    assert threshold == 5
    assert np.mean(values >= threshold) == .995
    assert np.mean(values >= 6) < .995
    values[:6] = 5
    assert gate.calibration_threshold(values, target, split='CALIBRATION') == 5


@pytest.mark.parametrize('split', ['HELD_OUT', 'FRESH_HELD_OUT', 'REAL', 'LEGACY_DIAGNOSTIC'])
def test_noncalibration_threshold_rejected(split: str) -> None:
    with pytest.raises(ValueError, match='CALIBRATION only'):
        gate.calibration_threshold(np.ones(10), np.ones(10, dtype=bool), split=split)


def test_nonfinite_positive_counted_as_miss_not_deleted() -> None:
    values = np.ones(1000)
    values[:6] = np.nan
    with pytest.raises(ValueError, match='NOT SUPPORTED'):
        gate.calibration_threshold(values, np.ones(1000, dtype=bool), split='CALIBRATION')


def test_four_frames_and_physical_context_without_new_gap_rule() -> None:
    time = np.arange(30, dtype=float)*10e-9
    values = np.zeros(30)
    values[4:7] = 1
    values[12:16] = 1
    supported, active = gate.informative_mask(time, values, 1.)
    assert supported.sum() == 7
    expected = np.zeros(30, dtype=bool)
    expected[11:17] = True
    np.testing.assert_array_equal(active, expected)
    assert not active[4:7].any()


@pytest.mark.parametrize('pattern', [[], [True], [False], [True, True, False, True]])
def test_runs_preserve_boundary_and_empty_input(pattern: list[bool]) -> None:
    mask = np.asarray(pattern, dtype=bool)
    rebuilt = np.zeros(len(mask), dtype=bool)
    for first, stop in gate.runs(mask):
        rebuilt[first:stop] = True
    np.testing.assert_array_equal(mask, rebuilt)


def test_full_output_exact_outside_and_inputs_not_changed() -> None:
    strongest = np.arange(17, dtype=float)*1e8
    proposed = strongest+2e8
    active = np.arange(17) % 3 == 0
    before = fingerprint((strongest, proposed, active))
    result = gate.complete_output(strongest, proposed, active)
    assert result.shape == strongest.shape and np.isfinite(result).all()
    np.testing.assert_array_equal(result[~active], strongest[~active])
    np.testing.assert_array_equal(result[active], proposed[active])
    assert before == fingerprint((strongest, proposed, active))


def test_detector_signature_has_no_gt_manual_or_final_input() -> None:
    for function in (gate.strongest_support, gate.informative_mask):
        names = inspect.signature(function).parameters
        assert not any(any(banned in name for banned in ('truth', 'target', 'manual', 'final',
                                                         'ch3', 'proposal')) for name in names)
    source = inspect.getsource(gate)
    assert 'task023e_waveform_benchmark' not in source
    assert 'task025_stress_benchmark' not in source


def test_original_generator_unchanged_except_seed_metadata() -> None:
    row = dict(dataset='CORE', family='amplitude_exchange', instance=8, seed=25990002,
               waveform='test', split='CALIBRATION')
    case = registered_case(row)
    expected = generate_case('amplitude_exchange', 8, 25990002)
    assert fingerprint((case.record, case.truth_hz, case.parameters)) == fingerprint(
        (expected.record, expected.truth_hz, expected.parameters))


@pytest.mark.parametrize('family', ['H0', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'H7'])
def test_hard_negatives_never_acquire_target_label(family: str) -> None:
    row = dict(dataset='HARD_NEGATIVE', family=family, instance=0, seed=25990003,
               waveform='test', split='CALIBRATION')
    case = registered_case(row)
    indices = np.arange(0, 80000, 128)
    masks = evaluation_masks(case, 'HARD_NEGATIVE', case.record.time_s[indices],
                             case.truth_hz[indices])
    assert not masks['target_present'].any()
    assert np.all(masks['structured'] != masks['low_information'])
    if family in ('H2', 'H3', 'H5', 'H6', 'H7'):
        assert masks['structured'].all()
    if family in ('H0', 'H1'):
        assert masks['low_information'].all()


def test_zero_amplitude_evidence_flag_does_not_create_nan_output() -> None:
    raw_time = np.arange(4000)/40e9
    frames = np.asarray([20e-9, 30e-9, 40e-9, 50e-9])
    strongest = np.full(4, 2e9)
    scores = gate.strongest_support(raw_time, np.zeros(4000), frames, strongest, 12.8e-9)
    assert np.isnan(scores.e1).all()
    assert all('ZERO_AMPLITUDE' in flag for flag in scores.quality)
    _, active = gate.informative_mask(frames, scores.e1, .1)
    assert not active.any()
    assert np.isfinite(gate.complete_output(strongest, strongest, active)).all()


def test_frozen_original_source_and_config_hashes() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = root / 'artifacts/task025_informative_interval/20260914T100937Z/frozen_manifest.json'
    hashes = json.loads(manifest.read_text(encoding='utf-8'))['Research']['hashes']
    selected = {name: digest for name, digest in hashes.items() if name.startswith((
        'src/dps_studio/core/', 'src/dps_studio/research/task023', 'configs/'))}
    assert any('ridge' in name for name in selected)
    assert any('time_frequency' in name for name in selected)
    assert any('task023f_proposals' in name for name in selected)
    for name, digest in selected.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name


def test_registered_split_waveforms_and_legacy_seeds_disjoint() -> None:
    root = Path(__file__).resolve().parents[2]
    folder = root / 'artifacts/task025_informative_interval/20260914T100937Z'
    registration = json.loads((folder / 'seed_registration.json').read_text())
    assert len(registration) == len({r['waveform'] for r in registration}) == 272
    assert len({r['seed'] for r in registration}) == 272
    cal = {r['waveform'] for r in registration if r['split'] == 'CALIBRATION'}
    held = {r['waveform'] for r in registration if r['split'] == 'HELD_OUT'}
    assert not cal & held and len(cal) == 94 and len(held) == 178
    legacy = json.loads((root / 'artifacts/task023h_raw_domain_evidence/20260913T132656Z/'
                         'seed_registration.json').read_text())
    assert not {r['seed'] for r in registration} & {r['seed'] for r in legacy}
    for r in registration:
        expected = r['instance'] < (13 if r['dataset'] == 'CORE' else 3)
        assert (r['split'] == 'CALIBRATION') == expected


def test_calibration_provenance_excludes_held_out_and_is_immutable() -> None:
    root = Path(__file__).resolve().parents[2]
    folder = root / 'artifacts/task025_informative_interval/20260914T100937Z'
    provenance = json.loads((folder / 'threshold_provenance.json').read_text())
    assert len(provenance) == 188
    registration = json.loads((folder / 'seed_registration.json').read_text())
    cal = {r['waveform'] for r in registration if r['split'] == 'CALIBRATION'}
    for row in provenance:
        assert row['split'] == 'CALIBRATION'
        assert any(row['stream'] == name+'_'+p.profile_id.value for name in cal for p in PROFILES)
        assert hashlib.sha256((folder / 'streams' / (row['stream']+'.npz')).read_bytes()).hexdigest(
            ) == row['sha256']


def test_partial_missing_frequency_is_rejected_without_filling() -> None:
    with pytest.raises(ValueError, match='complete'):
        gate.complete_output(np.array([1., np.nan]), np.ones(2), np.zeros(2, dtype=bool))


def test_nonuniform_raw_time_is_rejected_without_resampling() -> None:
    with pytest.raises(ValueError, match='NONUNIFORM'):
        gate.strongest_support(np.asarray([0., 1., 2.2, 3.]), np.ones(4),
                              np.array([1.]), np.array([.2]), 2.)
