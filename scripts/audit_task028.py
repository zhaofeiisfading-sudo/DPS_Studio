"""Verify stored graduation outputs and read-only repository boundaries."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.research import task028_benchmark as b
from dps_studio.research import task028_consolidation as m
from scripts.run_task028 import ROOT, digest, verify, write_csv, write_json


def snapshot(out: Path) -> None:
    """Start a new auditable run; existing directories cannot be reused."""
    out.mkdir(parents=True, exist_ok=False)
    result = {}
    for name, base in [('Research', ROOT), ('Production', ROOT.parent/'DPS_Studio')]:
        git = {cmd: subprocess.check_output(['git', *cmd.split()], cwd=base).decode(
            'utf-8', errors='replace') for cmd in ('status --short', 'branch --show-current',
                'rev-parse HEAD', 'rev-parse main', 'diff --name-status', 'diff --cached')}
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=base).decode().split('\0')
        files = {base/n for n in names if n and (base/n).is_file()}
        for folder in ('src', 'scripts', 'tests', 'data/raw'):
            files.update(p for p in (base/folder).rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts)
        result[name] = dict(git=git, hashes={p.relative_to(base).as_posix(): digest(p)
                                            for p in sorted(files)})
    write_json(out/'boundary_before.json', result)


def boundary(out: Path) -> None:
    before = json.loads((out/'boundary_before.json').read_text(encoding='utf-8'))
    results: dict[str, Any] = {}
    raw = []
    for name, base in [('Research', ROOT), ('Production', ROOT.parent/'DPS_Studio')]:
        state = before[name]
        changed = []
        for rel, expected in state['hashes'].items():
            path = base/rel
            actual = digest(path) if path.is_file() else 'MISSING'
            if actual != expected:
                changed.append(rel)
            if rel.startswith('data/raw/'):
                raw.append(dict(repository=name, path=rel, before=expected, after=actual,
                                unchanged=expected == actual))
        git = {cmd: subprocess.check_output(['git', *cmd.split()], cwd=base).decode(
            'utf-8', errors='replace') for cmd in state['git']}
        with (out/(name+'_git_after.json')).open('x', encoding='utf-8') as handle:
            json.dump(git, handle, indent=2)
        initial_lines = set(state['git']['status --short'].splitlines())
        final_lines = set(git['status --short'].splitlines())
        prior_raw = {r for r in state['hashes'] if r.startswith('data/raw/')}
        current_raw = {p.relative_to(base).as_posix() for p in (base/'data/raw').rglob('*') if p.is_file()}
        results[name] = dict(files_checked=len(state['hashes']), changed_files=changed,
            raw_inventory_unchanged=prior_raw == current_raw,
            status_added=sorted(final_lines-initial_lines), status_removed=sorted(initial_lines-final_lines),
            git_unchanged={cmd: git[cmd] == state['git'][cmd] for cmd in git},
            head=git['rev-parse HEAD'].strip(), branch=git['branch --show-current'].strip())
    write_csv(out/'raw_hash_verification.csv', raw)
    write_json(out/'boundary_verification.json', results)
    if any(not r['unchanged'] for r in raw) or any(v['changed_files'] for v in results.values()):
        raise AssertionError('Preexisting file boundary failed')
    if not all(results['Production']['git_unchanged'].values()):
        raise AssertionError('Production git state changed')
    if not all(v['raw_inventory_unchanged'] for v in results.values()):
        raise AssertionError('Raw inventory changed')
    print('Boundary verified', {k: v['files_checked'] for k, v in results.items()}, flush=True)


def audit(out: Path) -> None:
    verify(out)
    split = pd.read_csv(out/'fresh_split.csv')
    metrics = pd.read_csv(out/'per_case_metrics.csv')
    assert len(split) == split.seed.nunique() == split.voltage_sha256.nunique() == 64
    assert len(metrics) == 384
    assert (metrics.groupby('case_id').profile.nunique() == 2).all()
    assert split.groupby('observation_group').split.nunique().max() == 1
    cfg = m.FinalMethodConfig.from_dict(json.loads((out/'final_method_config.json').read_text()))
    assert cfg == m.FinalMethodConfig()
    checks: list[dict[str, Any]] = []
    for folder in ('streams', 'real_streams'):
        for path in sorted((out/folder).glob('*.npz')):
            if path.stem.endswith('_input'):
                continue
            with np.load(path) as values:
                for method in ('M0', 'M1', 'M2'):
                    freq = values[method]
                    candidates = values['candidates_hz']
                    rank = values[method+'_rank']
                    provenance = candidates[np.arange(len(freq)), rank-1]
                    assert np.array_equal(freq, provenance)
                    assert np.all(np.isfinite(freq))
                    assert np.all(np.isnan(values[method+'_validated_frequency_hz']))
                    assert np.array_equal(values[method+'_velocity_m_per_s'], freq*cfg.wavelength_m/2)
                    assert all('HYPOTHESIS_UNCALIBRATED' in q for q in values[method+'_quality'])
                    if method == 'M0':
                        assert np.array_equal(freq, candidates[:, 0])
                    if folder == 'streams':
                        row = metrics[(metrics.stream == path.stem) & (metrics.method == method)].iloc[0]
                        error = abs(freq-values['truth_hz'])
                        assert int((error > b.TOLERANCE_HZ).sum()) == row.wrong_frames
                        assert int((freq != values['M0']).sum()) == row.interventions
                        assert np.isclose(float(np.sum(error**2)), row.sse_hz2)
                    checks.append(dict(stream=path.stem, method=method, candidate_provenance=True,
                        coverage=1., quality_separate=True, SI_velocity=True, frames=len(freq)))
    write_csv(out/'saved_output_audit.csv', checks)
    audit_frame = pd.read_csv(out/'intervention_audit.csv')
    intervention_rows = []
    for method, group in audit_frame.groupby('method'):
        for source, subset in group.groupby('source'):
            old = abs(subset.strongest_hz-subset.truth_hz)
            new = abs(subset.selected_hz-subset.truth_hz)
            intervention_rows.append(dict(method=method, source=source, interventions=len(subset),
                corrected=int(((old > b.TOLERANCE_HZ) & (new <= b.TOLERANCE_HZ)).sum()),
                harmed=int(((old <= b.TOLERANCE_HZ) & (new > b.TOLERANCE_HZ)).sum())))
    write_csv(out/'mechanism_attribution.csv', intervention_rows)
    write_json(out/'output_audit.json', dict(passed=True, trajectories_checked=len(checks),
        synthetic_waveforms=64, synthetic_streams=128, real_streams=6,
        config_roundtrip=True, profile_grouping=True, no_train_test_tuning=True,
        observed_candidate_coverage=1., validated_measurement_coverage=0.,
        source_freeze_verified=True))
    print('Saved output checks passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['snapshot', 'boundary', 'outputs'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.parent != ROOT/'artifacts/task028_candidate_method_consolidation':
        raise ValueError('Output must stay inside Research TASK-028 artifacts')
    {'snapshot': snapshot, 'boundary': boundary, 'outputs': audit}[args.stage](out)
