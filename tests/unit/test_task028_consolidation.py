"""Graduation invariants and truth-independent regression checks."""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio.research import task023f_proposals as f
from dps_studio.research import task028_benchmark as b
from dps_studio.research import task028_consolidation as m
from dps_studio.research.task023e_waveform_benchmark import PROFILES
from dps_studio.research.task027_denoising import frozen_p3


def activation() -> dict[str, object]:
    cfg = m.FinalMethodConfig()
    return dict(core=True, diversity=True, config={
        key+'_config': asdict(getattr(cfg, key))
        for key in ('core', 'edge', 'internal', 'ambiguity', 'trim', 'branch')},
        effective_e4=asdict(f.effective_e4(cfg.branch)), proposal_config=asdict(cfg.proposal))


def test_config_roundtrip_and_literal_constants() -> None:
    cfg = m.FinalMethodConfig()
    assert m.FinalMethodConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))) == cfg
    assert cfg.branch.deviation_weight == .006
    assert cfg.branch.identity_break_penalty == 8
    assert f.effective_e4(cfg.branch).branch_acceptance_margin == 2.5
    assert cfg.core.trust_threshold == .64
    assert cfg.internal.acceptance_margin == 2


@pytest.mark.parametrize('family', [b.FAMILIES[0], b.FAMILIES[2], b.FAMILIES[6]])
def test_exact_p3_reproduction_provenance_and_separation(family: str) -> None:
    case = b.generate(family, 0, seed_base=28990000)
    raw = case.record.voltage_v.copy()
    stft, peaks = m.frontend(case.record, PROFILES[0])
    spectrum = stft.spectrum.copy()
    result = m.consolidate(stft, peaks)
    reference = frozen_p3(stft, peaks, activation())
    assert np.array_equal(result.trajectories['M2'].frequency_hz, reference)
    assert np.array_equal(raw, case.record.voltage_v)
    assert np.array_equal(spectrum, stft.spectrum)
    assert np.array_equal(result.trajectories['M0'].frequency_hz,
                          [frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    for trajectory in result.trajectories.values():
        assert np.isfinite(trajectory.frequency_hz).all()
        assert np.isnan(trajectory.validated_frequency_hz).all()
        assert np.isnan(trajectory.validated_apparent_velocity_m_per_s).all()
        assert all('HYPOTHESIS_UNCALIBRATED' in q for q in trajectory.quality_flags)
        assert np.array_equal(trajectory.apparent_velocity_m_per_s,
                              trajectory.frequency_hz * 1550e-9 / 2)
        assert not trajectory.frequency_hz.flags.writeable
        for i, frame in enumerate(peaks.candidates_by_frame):
            candidate = next(c for c in frame if c.candidate_rank == trajectory.candidate_rank[i])
            assert candidate.transition_frequency_hz == trajectory.frequency_hz[i]
    if family == b.FAMILIES[0]:
        assert not result.trajectories['M2'].modified.any()
    again = m.consolidate(stft, peaks)
    assert np.array_equal(again.trajectories['M2'].frequency_hz, reference)


def test_seed_reproducibility_and_profile_grouping() -> None:
    ids, seeds = set(), set()
    for family in b.FAMILIES:
        for instance in range(8):
            case = b.generate(family, instance)
            ids.add(case.case_id)
            seeds.add(case.seed)
            assert case.seed < 28990000
    assert len(ids) == len(seeds) == 64
    a = b.generate(b.FAMILIES[0], 0, seed_base=28990000)
    c = b.generate(b.FAMILIES[0], 0, seed_base=28990000)
    assert np.array_equal(a.record.voltage_v, c.record.voltage_v)
    assert PROFILES[0].profile_id != PROFILES[1].profile_id


def test_metrics_do_not_hide_missing_or_fast_errors() -> None:
    truth = np.full(4, 1e9)
    baseline = np.array([2e9, 1e9, 1e9, 2e9])
    result = np.array([1e9, 2e9, np.nan, 2e9])
    mask = np.ones(4, dtype=bool)
    row = b.metrics(result, baseline, truth, mask, mask, mask)
    row['candidate_recalled'] = 4
    ratio = b.ratios(row)
    assert row['corrected_frames'] == 1
    assert row['harmed_frames'] == 2
    assert row['wrong_frames'] == 3
    assert ratio['coverage'] == .75
    assert ratio['fast_change_preservation'] == 0
    assert ratio['fast_all_correct_fraction'] == .25
    assert ratio['obvious_jump_correction_rate'] == .5


def test_invalid_final_config_rejected() -> None:
    with pytest.raises(ValueError):
        replace(m.FinalMethodConfig(), top_k=40)
    with pytest.raises(ValueError):
        replace(m.FinalMethodConfig(), wavelength_m=float('nan'))


def test_new_core_has_no_artifact_or_gui_dependency() -> None:
    source = Path(m.__file__).read_text(encoding='utf-8')
    assert 'from dps_studio.gui' not in source
    assert 'read_text(' not in source
    assert 'data/raw' not in source
