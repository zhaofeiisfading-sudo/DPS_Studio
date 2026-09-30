"""Register and run the fixed Research graduation benchmark (exclusive writes)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.core.ridge import GlobalPathConfig
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research import task028_benchmark as b
from dps_studio.research import task028_consolidation as m
from dps_studio.research import task023f_proposals as f
from dps_studio.research.task023c_trusted_core_edge_rescue import EdgeRescueConfig
from dps_studio.research.task021b_real_experiment import DEFAULT_CONFIG_PATH, formal_read_input
from dps_studio.research.task023e_waveform_benchmark import PROFILES, array_hash

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


PROTOCOL = '''# TASK-028 frozen confirmatory protocol

64 independent waveforms = 8 families x 8 independent seeds; all FRESH_CONFIRMATORY.
No fitting, validation selection or threshold tuning; development is exclusively
LEGACY_DIAGNOSTIC TASK-023B/C/D/F/027. Unit-test seeds are disjoint (base 28990000).
Both profiles of a waveform remain in the same observation_group and split.
H identity label B reuses the same voltage and outputs and is diagnostic only.
Generation: 40 GHz sampling, 32000 samples (800 ns), family details in the saved
source hash and waveforms; parameter ranges fixed before first execution.
M0 strongest; M1 causal greedy node + pseudo-Huber step; M2 literal frozen F/P3.
Hann Balanced=768/640 overlap, High Time Resolution=512/384, nfft=4096; Top-20.
No waveform preprocessing, smoothing, resampling, truth/ROI/frequency input to M2.
All previous TASK datasets remain LEGACY_DIAGNOSTIC; fresh data is not retuned.

Frequency Hz, time s, voltage V, apparent velocity=1550e-9*f/2 m/s.
No window correction or corrected-velocity array. Candidate and validated
measurement channels are separate: all candidate outputs are uncalibrated;
validated frequency/velocity remain NaN. Coverage is candidate output coverage.
Branch correctness threshold=200 MHz (155 m/s). Corrected=wrong->correct;
harmed=correct->wrong. Intervention=exact candidate-frequency change vs M0.
Precision=corrected/interventions; harm=harmed/interventions. Also report absolute
error improvement/worsening >1 MHz separately (not a branch correction).
Wrong fraction includes missing outputs; finite-target RMSE reports its denominator.
Normal region: strongest correct, entire STFT support outside event; A all frames.
Fast preservation: G event centres on which M0 was correct, exact unchanged output;
also report correctness over ALL G event centres to expose baseline errors.
Obvious jump correction: B/C event-centre frames where M0 exceeds 200 MHz error.
This is a frame rate, not an event success rate. Undefined ratios are null/blank.
Candidate recall=any Top-20 within 200 MHz. No truth masking to raise coverage.

Primary descriptive summaries: frame-pooled and waveform-macro (merge both profiles
within waveform before RMSE/rates). Paired bootstrap resamples 64 waveform groups,
2000 replicates, fixed seed 280928; profile streams are never independent units.
Also report both profiles and all families, and ambiguity-excluded sensitivity.
No significance or universal accuracy claim is required. If benefit is uncertain,
report it and stop rather than search for a favorable sample or tune parameters.

Real behavior after synthetic: fixed 20260607.csv channel1 (relatively good),
PDV数据-质量中等/1/20201210m.dat channel1 (medium), ch3.csv channel1 (extreme bad),
both profiles, full record. No GT or real correctness claims; no case fishing.
Figures: first registered instance of A/C/D/E/H plus fixed real cases; if C first
has no repair, show it honestly and identify the best correction only in tables.
Figure contract: demonstrate preservation, local changes and failures through
spectrogram + frequency + apparent velocity + quality strips; quantitative grid;
Python matplotlib, 180 mm width, Arial, 400 dpi PNG and editable SVG, identical
method colors/units and no hidden points. Include source CSV/NPZ and captions.
Manual Focus Interval is design-only; absent from benchmark and final algorithm.
'''


def register(out: Path) -> None:
    if not (out / 'boundary_before.json').is_file():
        raise RuntimeError('Boundary snapshot required before registration')
    cfg = m.FinalMethodConfig()
    for folder in ('waveforms', 'streams', 'figures', 'real_streams', 'checks'):
        (out/folder).mkdir(exist_ok=False)
    write_json(out/'final_method_config.json', cfg.to_dict())
    write_json(out/'baseline_definition.json', dict(final='TASK023F_P3_LITERAL',
        M0='rank-one sub-bin candidate', M1='greedy node + pseudo-Huber step',
        M1_config=asdict(EdgeRescueConfig()), M2=cfg.to_dict(),
        effective_e4=asdict(f.effective_e4(cfg.branch)), frontend=asdict(GlobalPathConfig(top_k=20)),
        profiles=[asdict(p) for p in PROFILES], prior_data='LEGACY_DIAGNOSTIC'))
    with (out/'protocol.md').open('x', encoding='utf-8') as handle:
        handle.write(PROTOCOL)
    rows: list[dict[str, Any]] = []
    for family in b.FAMILIES:
        for i in range(8):
            case = b.generate(family, i)
            rows.append(dict(case_id=case.case_id, family=family, instance=i, seed=case.seed,
                split='FRESH_CONFIRMATORY', observation_group=case.case_id,
                profiles='balanced|high_time_resolution', voltage_sha256=array_hash(case.record.voltage_v),
                event_start_s=case.event_start_s, event_end_s=case.event_end_s))
            with (out/'waveforms'/f'{case.case_id}.npz').open('xb') as handle:
                np.savez_compressed(handle, time_s=case.record.time_s, voltage_v=case.record.voltage_v,
                    truth_hz=case.truth_hz, other_hz=case.other_hz)
    write_csv(out/'fresh_split.csv', rows)
    sources = list((ROOT/'src').rglob('*.py')) + [ROOT/'scripts/run_task028.py']
    write_json(out/'source_freeze.json', {str(p.relative_to(ROOT)): digest(p) for p in sources})
    legacy = []
    seeds: set[int] = set()
    hashes: set[str] = set()
    for pattern in ('fresh_split.csv', 'benchmark_manifest.csv', 'registration.csv'):
        for path in (ROOT/'artifacts').rglob(pattern):
            if out in path.parents:
                continue
            try:
                frame = pd.read_csv(path)
            except (ValueError, pd.errors.EmptyDataError):
                continue
            if 'seed' in frame:
                seeds.update(int(x) for x in frame.seed.dropna())
            for col in ('voltage_sha256', 'waveform_sha256'):
                if col in frame:
                    hashes.update(str(x) for x in frame[col].dropna())
            legacy.append(dict(path=str(path.relative_to(ROOT)), sha256=digest(path),
                               designation='LEGACY_DIAGNOSTIC', rows=len(frame)))
    overlaps = sorted({row['seed'] for row in rows} & seeds)
    hash_overlap = sorted({row['voltage_sha256'] for row in rows} & hashes)
    write_json(out/'split_audit.json', dict(independent_waveforms=64, profile_streams=128,
        fitting=False, unique_seeds=len({r['seed'] for r in rows}),
        unique_voltage_hashes=len({r['voltage_sha256'] for r in rows}),
        historical_seed_overlap=overlaps, historical_voltage_overlap=hash_overlap,
        historical_manifest_scope=legacy, historical_seed_count=len(seeds),
        caveat='Only available registered manifests can be checked; seeds alone are not proof of independence'))
    if overlaps or hash_overlap:
        raise AssertionError('Fresh registration overlaps historical manifest')
    print('Registered 64 waveforms before observations', flush=True)


def verify(out: Path) -> None:
    for rel, expected in json.loads((out/'source_freeze.json').read_text()).items():
        if digest(ROOT/rel) != expected:
            raise RuntimeError('Frozen source changed: '+rel)


def evaluate_stream(out: Path, stem: str, record: Any, profile: Any,
                    truth: Any = None, case: b.Case | None = None,
                    real: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start = time.perf_counter()
    stft, peaks = m.frontend(record, profile)
    frontend_seconds = time.perf_counter()-start
    start = time.perf_counter()
    result = m.consolidate(stft, peaks)
    total_seconds = time.perf_counter()-start
    baseline = result.trajectories['M0'].frequency_hz
    matrix = np.full((len(baseline), 20), np.nan)
    for i, frame in enumerate(peaks.candidates_by_frame):
        matrix[i, :len(frame)] = [c.transition_frequency_hz for c in frame]
    values: dict[str, Any] = dict(time_s=stft.time_s, candidates_hz=matrix,
        ambiguity=result.ambiguity, voltage_sha256=array_hash(record.voltage_v))
    rows, audits = [], []
    if case is not None:
        indices = np.rint(stft.time_s*b.FS_HZ).astype(int)
        truth = case.truth_hz[indices]
        values['truth_hz'] = truth
        values['other_hz'] = case.other_hz[indices]
    for method, trajectory in result.trajectories.items():
        path = trajectory.frequency_hz
        values[method] = path
        values[method+'_rank'] = trajectory.candidate_rank
        values[method+'_quality'] = np.asarray(trajectory.quality_flags)
        values[method+'_velocity_m_per_s'] = trajectory.apparent_velocity_m_per_s
        values[method+'_validated_frequency_hz'] = trajectory.validated_frequency_hz
        provenance = np.any(matrix == path[:, None], axis=1)
        if not np.all(provenance):
            raise AssertionError('Candidate provenance failed')
        row = dict(stream=stem, method=method, profile=profile.profile_id.value,
            frontend_seconds=frontend_seconds, all_methods_seconds=total_seconds,
            provenance_all=True, output_sha256=array_hash(path),
            quality_flagged_frames=sum(q != 'HYPOTHESIS_UNCALIBRATED' for q in trajectory.quality_flags))
        if case is not None:
            normal = ((stft.time_s + stft.window_length_samples / stft.sample_rate_hz / 2
                       < case.event_start_s) |
                      (stft.time_s - stft.window_length_samples / stft.sample_rate_hz / 2
                       >= case.event_end_s))
            if case.family == 'A_normal':
                normal[:] = True
            event = (stft.time_s >= case.event_start_s) & (stft.time_s < case.event_end_s)
            fast = event & (case.family == 'G_fast_change')
            obvious = event & (case.family in ('B_noise_peak', 'C_short_switch'))
            row.update(b.metrics(path, baseline, truth, normal, fast, obvious))
            row.update(case_id=case.case_id, family=case.family, seed=case.seed,
                candidate_recalled=int(np.any(abs(matrix-truth[:, None]) <= b.TOLERANCE_HZ, axis=1).sum()))
            row.update(b.ratios(row))
        else:
            row.update(frames=len(path), finite_frames=int(np.isfinite(path).sum()),
                coverage=float(np.isfinite(path).mean()), interventions=int(trajectory.modified.sum()),
                maximum_step_hz=float(np.max(abs(np.diff(path)))),
                jumps_over_450mhz=int(np.sum(abs(np.diff(path)) > 450e6)),
                physical_correctness='UNKNOWN_NO_GT')
        rows.append(row)
        for frame_index in np.flatnonzero(trajectory.modified):
            i = int(frame_index)
            audits.append(dict(stream=stem, method=method, frame=int(i),
                time_s=float(stft.time_s[i]), strongest_hz=float(baseline[i]),
                selected_hz=float(path[i]), candidate_rank=int(trajectory.candidate_rank[i]),
                quality=trajectory.quality_flags[i],
                truth_hz=float(truth[i]) if case is not None else None,
                decision='REPLACE_WITH_ALTERNATIVE',
                source='SIMPLE_CONTINUITY' if method == 'M1' else next((
                    w['window_id'] for w in result.window_audit if int(i) in w['frames']),
                    'INTERNAL_DUAL_ANCHOR_RESCUE')))
    folder = out / ('real_streams' if real else 'streams')
    with (folder/(stem+'.npz')).open('xb') as handle:
        np.savez_compressed(handle, **values)
    write_json(folder/(stem+'_windows.json'), result.window_audit)
    print(stem, 'seconds', round(total_seconds, 2), 'M2 interventions', rows[-1]['interventions'], flush=True)
    return rows, audits


def synthetic(out: Path) -> None:
    verify(out)
    rows, audits = [], []
    split = pd.read_csv(out/'fresh_split.csv')
    for item in split.to_dict('records'):
        case = b.generate(str(item['family']), int(item['instance']))
        if array_hash(case.record.voltage_v) != item['voltage_sha256']:
            raise AssertionError('Waveform regeneration mismatch')
        for profile in PROFILES:
            stem = case.case_id+'__'+profile.profile_id.value
            result, audit = evaluate_stream(out, stem, case.record, profile, case=case)
            rows.extend(result)
            audits.extend(audit)
    write_csv(out/'per_case_metrics.csv', rows)
    write_csv(out/'intervention_audit.csv', audits)


def real_data(out: Path) -> None:
    verify(out)
    if not (out/'per_case_metrics.csv').is_file():
        raise RuntimeError('Synthetic validation must complete first')
    config = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=ROOT)
    paths = ['20260607.csv', 'PDV数据-质量中等/1/20201210m.dat', 'ch3.csv']
    rows, audits = [], []
    for name in paths:
        path = ROOT/'data/raw'/name
        formal = formal_read_input(path, config)
        channel, record = next(iter(formal.loaded.records.items()))
        with (out/'real_streams'/(path.stem+'_input.npz')).open('xb') as handle:
            np.savez_compressed(handle, time_s=record.time_s, voltage_v=record.voltage_v)
        for profile in PROFILES:
            result, audit = evaluate_stream(out, path.stem+'__'+profile.profile_id.value,
                                            record, profile, real=True)
            for row in result:
                row.update(source=name, source_sha256=digest(path), channel=channel)
            rows.extend(result)
            audits.extend(audit)
    write_csv(out/'real_data_behavior.csv', rows)
    write_csv(out/'real_intervention_audit.csv', audits)


def summary(out: Path) -> None:
    frame = pd.read_csv(out/'per_case_metrics.csv')
    counts = ['frames', 'finite_frames', 'truth_frames', 'sse_hz2', 'squared_error_frames',
        'wrong_frames', 'interventions', 'corrected_frames', 'harmed_frames',
        'improved_error_frames', 'worsened_error_frames', 'normal_frames', 'normal_preserved',
        'fast_frames', 'fast_preserved', 'fast_all', 'fast_correct', 'obvious_frames',
        'obvious_corrected', 'candidate_recalled']
    rows = []
    for scope, sub in [('ALL', frame), ('IDENTIFIABLE_ONLY', frame[frame.family != b.FAMILIES[-1]])
                       ] + [(str(k), v) for k, v in frame.groupby('family')
                       ] + [(str(k), v) for k, v in frame.groupby('profile')]:
        for method, group in sub.groupby('method'):
            row = dict(scope=scope, aggregation='FRAME_POOLED', method=method,
                       waveforms=group.case_id.nunique(), **group[counts].sum().to_dict())
            row.update(b.ratios(row))
            rows.append(row)
            per_wave = [b.ratios(v[counts].sum().to_dict()) for _, v in group.groupby('case_id')]
            macro = pd.DataFrame(per_wave).mean().to_dict()
            rows.append(dict(scope=scope, aggregation='WAVEFORM_MACRO', method=method,
                             waveforms=len(per_wave), **macro))
    write_csv(out/'graduation_benchmark.csv', rows)
    # Pair each independent waveform once, merging its two profiles first.
    bootstrap = []
    rng = np.random.default_rng(280928)
    for scope, sub in [('ALL', frame), ('IDENTIFIABLE_ONLY', frame[frame.family != b.FAMILIES[-1]])]:
        wave = sub.groupby(['case_id', 'method'])[counts].sum().reset_index()
        wave['rmse_hz'] = np.sqrt(wave.sse_hz2 / wave.squared_error_frames)
        wave['wrong_branch_fraction'] = wave.wrong_frames / wave.truth_frames
        for metric in ('rmse_hz', 'wrong_branch_fraction'):
            pivot = wave.pivot(index='case_id', columns='method', values=metric)
            for ref in ('M0', 'M1'):
                delta = (pivot.M2-pivot[ref]).to_numpy()
                indices = rng.integers(0, len(delta), (2000, len(delta)))
                means = delta[indices].mean(axis=1)
                bootstrap.append(dict(scope=scope, comparison='M2-'+ref, metric=metric,
                    paired_waveforms=len(delta), mean_delta=float(delta.mean()),
                    ci95_low=float(np.quantile(means, .025)), ci95_high=float(np.quantile(means, .975)),
                    improved_waveforms=int((delta < 0).sum()), worsened_waveforms=int((delta > 0).sum())))
    write_csv(out/'paired_waveform_uncertainty.csv', bootstrap)
    ambiguity = []
    for path in sorted((out/'streams').glob('*H_identity*.npz')):
        with np.load(path) as v:
            for method in ('M0', 'M1', 'M2'):
                for label, key in [('A', 'truth_hz'), ('B', 'other_hz')]:
                    error = abs(v[method]-v[key])
                    ambiguity.append(dict(stream=path.stem, method=method, label=label,
                        rmse_hz=float(np.sqrt(np.mean(error**2))),
                        wrong_branch_fraction=float(np.mean(error > b.TOLERANCE_HZ)),
                        same_output=True, independent_unit=False))
    write_csv(out/'ambiguity_label_swap.csv', ambiguity)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['register', 'synthetic', 'real', 'summary'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.parent != ROOT/'artifacts/task028_candidate_method_consolidation':
        raise ValueError('Output must stay inside Research TASK-028 artifacts')
    {'register': register, 'synthetic': synthetic, 'real': real_data, 'summary': summary}[args.stage](out)
