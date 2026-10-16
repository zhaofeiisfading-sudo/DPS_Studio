"""Fresh split separation, no-truth inference, candidate conservation and veto safety."""
from __future__ import annotations

from dataclasses import replace
from inspect import signature

import numpy as np
import pytest

from dps_studio.core.analysis_profiles import BALANCED_PROFILE
from dps_studio.research import denoising_task001 as m2
from dps_studio.research import denoising_task001_benchmark as old
from dps_studio.research import denoising_task003 as risk
from dps_studio.research import denoising_task003_benchmark as bench
from dps_studio.research import denoising_task003_statistics as stats
from dps_studio.research.task028_consolidation import frontend


@pytest.mark.parametrize('family', bench.FAMILIES)
def test_fresh_voltage_and_group_registration(family: str) -> None:
    a = bench.generate(family, 'repair_opportunity', 0, 'TRAIN')
    b = bench.generate(family, 'repair_opportunity', 0, 'TRAIN')
    c = bench.generate(family, 'repair_opportunity', 0, 'HELD_OUT')
    np.testing.assert_array_equal(a.record.voltage_v, b.record.voltage_v)
    assert a.seed != c.seed
    assert not np.array_equal(a.record.voltage_v, c.record.voltage_v)
    assert a.record.sample_rate_hz == pytest.approx(40e9)
    assert np.array_equal(np.isfinite(a.truth_hz), a.target_present)
    assert a.record.time_s[-1] < 1e-6


def test_registration_has_no_seed_or_profile_leakage() -> None:
    rows = bench.registration()
    assert len(rows) == 192 == len({r['seed'] for r in rows})
    assert len({r['case_id'] for r in rows}) == len(rows)
    assert all('profile' not in r for r in rows)
    assert all(r['seed'] >= 43010000 for r in rows)


def test_whole_proposal_veto_retains_baseline_and_candidate_identity() -> None:
    case = old.generate('jump', 0, 'TRAIN')
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    original_spectrum = stft.spectrum.copy()
    baseline = np.array([f[0].transition_frequency_hz for f in peaks.candidates_by_frame])
    original_baseline = baseline.copy()
    proposals = m2.propose_repairs(stft, peaks, baseline)
    assert proposals
    path, flags, rows = risk.risk_repair(peaks, baseline, proposals, rule='R1')
    assert any(r['rejected'] for r in rows)
    for p, row in zip(proposals, rows, strict=True):
        if row['rejected']:
            np.testing.assert_array_equal(path[p.first:p.stop], baseline[p.first:p.stop])
            assert all(f == 'AMBIGUOUS_INTERVENTION' for f in flags[p.first:p.stop])
    loose, _, _ = risk.risk_repair(peaks, baseline, proposals,
                                  config=risk.RiskConfig(maximum_balance_db=0))
    expected, _ = m2.apply_repairs(peaks, baseline, proposals)
    np.testing.assert_array_equal(loose, expected)
    np.testing.assert_array_equal(stft.spectrum, original_spectrum)
    np.testing.assert_array_equal(baseline, original_baseline)
    assert all(any(c.transition_frequency_hz == path[i] for c in f)
               for i, f in enumerate(peaks.candidates_by_frame))


def test_identity_relabeling_cannot_change_observation_or_inference() -> None:
    case = bench.generate('anchor_exchange', 'harm_counterexample', 0, 'TRAIN')
    relabeled = replace(case, truth_hz=case.competitor_hz.copy())
    assert relabeled.record is case.record
    assert np.any(abs(case.truth_hz-relabeled.truth_hz) > 400e6)
    assert not any(x in str(signature(risk.diagnostics))
                   for x in ('truth', 'component_id', 'family', 'harmed'))
    stft, peaks = frontend(case.record, BALANCED_PROFILE)
    baseline = np.array([f[0].transition_frequency_hz for f in peaks.candidates_by_frame])
    proposals = m2.propose_repairs(stft, peaks, baseline)
    a, fa, ra = risk.risk_repair(peaks, baseline, proposals)
    b, fb, rb = risk.risk_repair(peaks, baseline, proposals)
    np.testing.assert_array_equal(a, b)
    assert fa == fb and ra == rb


@pytest.mark.parametrize('kwargs', [{'minimum_run_s': -1}, {'maximum_balance_db': -1},
                                  {'minimum_supported_fraction': 0},
                                  {'maximum_step_hz': np.nan}])
def test_invalid_config_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        risk.RiskConfig(**kwargs)


def test_bootstrap_combines_profiles_before_rmse_and_does_not_inflate_n() -> None:
    rows = []
    for method in ('M0', 'M2'):
        for profile, sse in (('a', 0.), ('b', 8.)):
            row = dict.fromkeys(stats.COUNT_KEYS, 0.)
            row.update(sse_hz2=sse if method == 'M2' else 0., squared_error_frames=1.)
            rows.append(dict(**row, case_id='one_waveform', method=method, profile=profile))
    result = stats.paired_uncertainty(rows, 'M2', 'M0')
    assert result['waveforms'] == 1
    assert result['mean_hz'] == 2.
    assert result['lower_hz'] == result['upper_hz'] == 2.
