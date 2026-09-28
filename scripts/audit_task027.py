"""Read saved observations; verify TASK-027 artifacts without rerunning a tracker."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from matplotlib.figure import Figure

from dps_studio.core.models import SignalRecord
from dps_studio.research import task027_denoising as m
from dps_studio.research.task023e_waveform_benchmark import PROFILES
from scripts.run_task027 import ROOT, digest, read_json, verify_freeze, write_csv, write_json


def snapshot(output: Path) -> None:
    """Capture a new run before registration; never replace an existing artifact."""
    if output.parent != ROOT / 'artifacts/task027_non_ai_open_exploration':
        raise ValueError('Snapshot must stay in the Research TASK-027 artifact root')
    output.mkdir(parents=True, exist_ok=False)
    result = {}
    for name, base in [('Research', ROOT), ('Production', ROOT.parent / 'DPS_Studio')]:
        git = {command: subprocess.check_output(['git', *command.split()], cwd=base).decode(
            'utf-8', errors='replace') for command in ('status --short', 'rev-parse HEAD',
                'rev-parse main', 'branch --show-current', 'diff', 'diff --cached')}
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=base).decode('utf-8').split('\0')
        files = {base/n for n in names if n and (base/n).is_file()}
        for folder in ('src', 'scripts', 'tests', 'data/raw'):
            files.update(p for p in (base/folder).rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts)
        result[name] = dict(git=git, hashes={p.relative_to(base).as_posix(): digest(p)
                                            for p in sorted(files)})
    write_json(output / 'boundary_before.json', result)
    print('Boundary snapshot saved', flush=True)


def boundary(output: Path) -> None:
    before = read_json(output / 'boundary_before.json')
    results = {}
    raw_rows = []
    for name, base in [('Research', ROOT), ('Production', ROOT.parent / 'DPS_Studio')]:
        state = before[name]
        changed = []
        for rel, expected in state['hashes'].items():
            path = base / rel
            actual = digest(path) if path.is_file() else 'MISSING'
            if actual != expected:
                changed.append(rel)
            if rel.startswith('data/raw/'):
                raw_rows.append(dict(repository=name, path=rel, before=expected,
                                     after=actual, unchanged=actual == expected))
        git = {}
        for command, expected in state['git'].items():
            actual = subprocess.check_output(['git', *command.split()], cwd=base).decode(
                'utf-8', errors='replace')
            if command == 'status --short':
                prior_lines = set(expected.splitlines())
                lines = set(actual.splitlines())
                git[command] = dict(removed=sorted(prior_lines-lines), added=sorted(lines-prior_lines))
                with (output / (name+'_status_after.txt')).open('x', encoding='utf-8') as handle:
                    handle.write(actual)
            else:
                git[command] = actual == expected
        results[name] = dict(files_checked=len(state['hashes']), changed_files=changed, git=git)
    write_csv(output / 'raw_hash_verification.csv', raw_rows)
    write_json(output / 'boundary_verification.json', results)
    print({k: dict(files_checked=v['files_checked'], changed_files=v['changed_files'])
           for k, v in results.items()}, flush=True)


def audit(output: Path) -> None:
    verify_freeze(output)
    results: list[dict[str, Any]] = []
    ambiguity: list[dict[str, Any]] = []
    focus_recovery: list[dict[str, Any]] = []
    for path in sorted((output / 'streams').glob('*.npz')):
        with np.load(path) as a:
            provenance = {}
            for method in ('strongest', 'P3', 'FIR_P3'):
                selected = a[method]
                candidates = a[method+'_candidates_hz']
                supported = np.any(np.isclose(selected[:, None], candidates, rtol=0, atol=1e-6), axis=1)
                provenance[method] = bool(np.all(supported | ~np.isfinite(selected)))
            results.append(dict(stream=path.stem, **provenance,
                no_confidence_claim=bool(np.all(a['quality'] == 'HYPOTHESIS_UNCALIBRATED')),
                same_frame_count=all(len(a[k]) == len(a['time_s']) for k in ('strongest', 'P3', 'FIR_P3'))))
            for method in ('strongest', 'P3', 'FIR_P3'):
                if 'swapped_truth_hz' in a:
                    for label, truth_key in [('A', 'truth_hz'), ('B', 'swapped_truth_hz')]:
                        error = abs(a[method]-a[truth_key])
                        ambiguity.append(dict(stream=path.stem, method=method, label=label,
                            same_output_reused=True, target_identity_claim=False,
                            rmse_hz=float(np.sqrt(np.mean(error**2))),
                            wrong_branch_fraction=float(np.mean(error > 200e6))))
                if any('_'+family+'_' in path.stem for family in ('O2', 'O3', 'O4', 'O5')):
                    focus = (a['time_s'] >= 160e-9) & (a['time_s'] < 200e-9)
                    wrong = focus & (abs(a['strongest']-a['truth_hz']) > 200e6)
                    focus_recovery.append(dict(stream=path.stem, method=method,
                        strongest_focus_wrong_frames=int(wrong.sum()),
                        recovered=int((wrong & (abs(a[method]-a['truth_hz']) <= 200e6)).sum())))
    write_csv(output / 'candidate_provenance_audit.csv', results)
    write_csv(output / 'ambiguity_label_swap.csv', ambiguity)
    write_csv(output / 'focus_error_recovery.csv', focus_recovery)
    safety = pd.read_csv(output / 'safety_audit.csv')
    safety.groupby(['family', 'profile']).mean(numeric_only=True).to_csv(
        output / 'safety_summary.csv', mode='x')
    rows = pd.concat([pd.read_csv(output / name) for name in
                      ('synthetic_results.csv', 'obvious_error_benchmark.csv')])
    if 'method' in rows:
        rows['rmse_hz'] = np.sqrt(rows.sse_hz2 / rows.truth_selected.replace(0, np.nan))
        rows['wrong_fraction'] = rows.wrong / rows.truth_frames.replace(0, np.nan)
        rows[rows.reference == 'P3'].groupby(['dataset', 'family', 'method']).agg(
            waveform_profile_mean_rmse_hz=('rmse_hz', 'mean'),
            wrong=('wrong', 'sum'), truth_frames=('truth_frames', 'sum'),
            corrected_frames=('corrected_frames', 'sum'), harmed_frames=('harmed_frames', 'sum'),
            interventions=('interventions', 'sum'), normal_frames=('normal_frames', 'sum'),
            normal_preserved=('normal_preserved', 'sum'), fast_frames=('fast_frames', 'sum'),
            fast_preserved=('fast_preserved', 'sum'), jump_frames=('obvious_jump_frames', 'sum'),
            jump_corrected=('jump_corrected', 'sum'), no_info_frames=('no_info_frames', 'sum'),
            false_tracks=('false_tracks', 'sum')).to_csv(output / 'family_summary.csv', mode='x')
    print('Artifact audit complete', flush=True)


def plots(output: Path) -> None:
    summary = pd.read_csv(output / 'aggregate_metrics.csv')
    figure = Figure(figsize=(10, 7), layout='constrained')
    axes = figure.subplots(2, 2)
    colors = ['#707070', '#0072B2', '#D55E00']
    for i, dataset in enumerate(('CORE', 'OBVIOUS')):
        rows = summary[(summary.dataset == dataset) & (summary.aggregation == 'POOLED')]
        for j, (column, scale, label) in enumerate((('rmse_hz', 1e-6, 'RMSE / MHz'),
                                                   ('wrong_branch', 100, 'Wrong branch / %'))):
            axes[i, j].bar(rows.method, rows[column]*scale, color=colors)
            axes[i, j].set(title=dataset+' | paired fresh waveforms', ylabel=label)
    figure.suptitle('TASK-027 | finite-target RMSE; missing outputs count wrong')
    figure.savefig(output / 'figures/performance.png', dpi=180)
    figure.savefig(output / 'figures/performance.svg')
    # Fixed first registered stress realization, no selection for favorable results.
    for family in ('O1', 'O3', 'O5', 'O6'):
        stem = 'T27_OBVIOUS_'+family+'_0'
        with np.load(output / 'waveforms' / (stem+'.npz')) as wave:
            record = SignalRecord(wave['time_s'], wave['voltage_v'])
        with np.load(output / 'streams' / (stem+'_balanced.npz')) as values:
            stft, _ = m.frontend(record, PROFILES[0])  # plotting only; never rerun P3
            figure = Figure(figsize=(11, 4), layout='constrained')
            axis = figure.subplots()
            amplitude = abs(stft.spectrum)
            db = 20*np.log10(np.maximum(amplitude/amplitude.max(), 1e-8))
            axis.pcolormesh(stft.time_s*1e9, stft.frequency_hz/1e9, db,
                            cmap='magma', vmin=-55, vmax=0, shading='auto', rasterized=True)
            for name, color, width in [('truth_hz', '#56B4E9', 1.6), ('strongest', 'white', .9),
                                        ('P3', '#009E73', 1.), ('FIR_P3', '#E69F00', .8)]:
                axis.plot(values['time_s']*1e9, values[name]/1e9, color=color, lw=width, label=name)
            changed = abs(values['FIR_P3']-values['P3']) > 1e6
            axis.scatter(values['time_s'][changed]*1e9, values['FIR_P3'][changed]/1e9,
                          s=12, facecolors='none', edgecolors='cyan', label='change >1 MHz')
            axis.set(xlabel='Time / ns', ylabel='Frequency / GHz', ylim=(.05, 6), title=stem)
            axis.legend(loc='upper right', fontsize=8)
            figure.savefig(output / ('figures/'+family+'_first_registered.png'), dpi=180)
    print('Saved diagnostic plots', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['snapshot', 'boundary', 'audit', 'plots'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    {'snapshot': snapshot, 'boundary': boundary, 'audit': audit,
     'plots': plots}[args.stage](args.output.resolve())
