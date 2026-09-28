"""Physical, provenance and fail-closed checks, with no held-out observations."""
from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.research import task027_denoising as m
from dps_studio.research.task023e_waveform_benchmark import PROFILES, array_hash
from scripts.evaluate_task027 import counts, rates
from scripts.run_task027 import case_for, verify_freeze, write_json


def record() -> SignalRecord:
    t = np.arange(2048)/40e9
    return SignalRecord(t, np.cos(2*np.pi*3e9*t))


def test_read_only_source_and_identical_time(tmp_path: Path) -> None:
    source = tmp_path/'raw.dat'
    source.write_bytes(b'read only source sentinel')
    raw = record()
    raw = SignalRecord(raw.time_s, raw.voltage_v, source_path=source)
    hashes = (array_hash(raw.time_s), array_hash(raw.voltage_v))
    filtered = m.preprocess(raw)
    assert np.array_equal(raw.time_s, filtered.time_s)
    assert len(raw.voltage_v) == len(filtered.voltage_v)
    assert hashes == (array_hash(raw.time_s), array_hash(raw.voltage_v))
    assert source.read_bytes() == b'read only source sentinel'
    assert 'task027_processing' in filtered.metadata


def test_nonuniform_rejected_without_resampling() -> None:
    raw = record()
    t = raw.time_s.copy()
    t[100] += 1e-12
    with pytest.raises(ValueError, match='Nonuniform'):
        m.preprocess(SignalRecord(t, raw.voltage_v))


@pytest.mark.parametrize('config', [m.FilterConfig(taps=128), m.FilterConfig(cutoff_hz=21e9),
                                  m.FilterConfig(padding='wrap'), m.FilterConfig(taps=1)])
def test_invalid_filter_rejected(config: m.FilterConfig) -> None:
    with pytest.raises(ValueError):
        m.preprocess(record(), config)


def test_centered_impulse_has_no_time_shift_and_keeps_samples() -> None:
    raw = record()
    voltage = np.zeros(len(raw.time_s))
    voltage[1000] = 1
    filtered = m.preprocess(SignalRecord(raw.time_s, voltage))
    assert np.argmax(filtered.voltage_v) == 1000
    np.testing.assert_allclose(filtered.voltage_v[936:1065], filtered.voltage_v[936:1065][::-1])


def test_stopband_rejected_passband_preserved() -> None:
    raw = record()
    voltage = np.cos(2*np.pi*3e9*raw.time_s)+np.cos(2*np.pi*12e9*raw.time_s)
    filtered = m.preprocess(SignalRecord(raw.time_s, voltage))
    for frequency, bound in [(3e9, .99), (12e9, .01)]:
        amplitude = abs(2*np.mean(filtered.voltage_v[128:-128]
                                 *np.exp(-2j*np.pi*frequency*raw.time_s[128:-128])))
        assert amplitude > bound if frequency == 3e9 else amplitude < bound


@pytest.mark.parametrize('gate', [{}, {'safety': False}, {'safety': True, 'performance': False}])
def test_failed_or_missing_gate_blocks_next_stage(gate: dict[str, bool]) -> None:
    with pytest.raises(RuntimeError, match='prohibited'):
        m.require_gate(gate)


def test_passed_gate() -> None:
    m.require_gate({'safety': True, 'performance': True})


def test_gt_not_accepted_by_processing_or_backend() -> None:
    assert set(inspect.signature(m.preprocess).parameters) == {'record', 'config'}
    assert set(inspect.signature(m.frozen_p3).parameters) == {'stft', 'peaks', 'activation'}
    row = dict(dataset='OBVIOUS', family='O8', instance=0, seed=27990001)
    case = case_for(row)
    swapped = replace(case, truth_hz=case.nuisance_hz, nuisance_hz=case.truth_hz)
    assert np.array_equal(m.preprocess(case.record).voltage_v,
                          m.preprocess(swapped.record).voltage_v)


def test_stft_axes_and_si_units() -> None:
    raw = record()
    a, peaks = m.frontend(raw, PROFILES[0])
    b, _ = m.frontend(m.preprocess(raw), PROFILES[0])
    assert np.array_equal(a.time_s, b.time_s)
    assert np.array_equal(a.frequency_hz, b.frequency_hz)
    assert np.max(abs(m.strongest(peaks)-3e9)) < 1e6
    assert abs(1550e-9*float(m.strongest(peaks)[0])/2-2325) < 1


def test_nan_counts_missing_as_wrong_and_harm() -> None:
    _, peaks = m.frontend(record(), PROFILES[0])
    n = len(peaks.time_s)
    truth = np.full(n, 3e9)
    path = truth.copy()
    path[0] = np.nan
    empty = np.zeros(n, dtype=bool)
    result = counts(path, truth, truth, ~empty, empty, empty, empty, peaks)
    assert result['harmed_frames'] == 1 and result['wrong'] == 1
    assert result['truth_selected'] == n-1
    assert rates(result)['truth_coverage'] == (n-1)/n


def test_freeze_rejects_changed_hash_and_exclusive_output(tmp_path: Path) -> None:
    write_json(tmp_path/'frozen_manifest.json', {__file__: 'invalid'})
    with pytest.raises(RuntimeError, match='changed'):
        verify_freeze(tmp_path)
    with pytest.raises(FileExistsError):
        write_json(tmp_path/'frozen_manifest.json', {})


@pytest.mark.parametrize('family', [f'O{i}' for i in range(1, 9)])
def test_obvious_cases_are_time_domain_and_repeatable(family: str) -> None:
    row = dict(dataset='OBVIOUS', family=family, instance=0, seed=27990002)
    case = case_for(row)
    assert len(case.record.time_s) == 16000
    assert np.array_equal(case.record.voltage_v, case_for(row).record.voltage_v)
    if family == 'O1':
        assert np.isnan(case.truth_hz[:6400]).all()
    if family == 'O6':
        assert case.truth_hz[0] == 4.5e9 and case.truth_hz[-1] == 1.5e9
