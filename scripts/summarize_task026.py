"""Predefined TASK-026 aggregation/gates; consumes saved observations only."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.freeze_task026 import load_json, write_json

MEASURES = ('rmse_hz', 'bias_hz', 'p95_absolute_error_hz', 'candidate_recall',
    'truth_near_rank', 'nearest_candidate_rmse_hz', 'discrete_rmse_hz', 'discrete_bias_hz',
    'sub_bin_shift_rmse_hz', 'valid_estimate_fraction', 'failure_rate', 'resolution_rate',
    'candidate_multiplicity', 'false_candidate_rate', 'residual_fraction')


def save(frame: Any, path: Path) -> None:
    with path.open('x', encoding='utf-8', newline='') as handle:
        frame.to_csv(handle, index=False)


def macro(frame: Any, metric: str) -> float:
    if not len(frame):
        return float('nan')
    return float(frame.groupby('waveform')[metric].mean().mean())


def aggregates(frame: Any) -> Any:
    result = []
    for (dataset, split, method, region), base in frame.groupby(
            ['dataset', 'split', 'method', 'region']):
        for profile in ('ALL', *sorted(base.profile.unique())):
            selected = base if profile == 'ALL' else base[base.profile == profile]
            for family in ('ALL', *sorted(selected.family.unique())):
                group = selected if family == 'ALL' else selected[selected.family == family]
                row = dict(dataset=dataset, split=split, method=method, region=region,
                           profile=profile, family=family, waveforms=group.waveform.nunique(),
                           streams=len(group))
                for metric in MEASURES:
                    per_waveform = group.groupby('waveform')[metric].mean()
                    row[metric] = float(per_waveform.mean())
                    row[metric+'_sd'] = float(per_waveform.std())
                for field in ('truth_frames', 'valid_frames', 'candidate_hits',
                              'two_component_frames', 'resolved_frames', 'false_candidates',
                              'candidate_count', 'frames'):
                    row[field] = int(group[field].sum())
                for name, numerator, denominator in (
                    ('pooled_candidate_recall', 'candidate_hits', 'truth_frames'),
                    ('pooled_resolution_rate', 'resolved_frames', 'two_component_frames'),
                    ('pooled_false_candidate_rate', 'false_candidates', 'candidate_count')):
                    row[name] = (row[numerator]/row[denominator] if row[denominator] else np.nan)
                result.append(row)
    return pd.DataFrame(result)


def gate_verdict(accuracy: bool, recall: bool, resolution: bool, false_candidates: bool,
                 runtime: bool, hard_gain: bool) -> str:
    if all((accuracy, recall, resolution, false_candidates, runtime, hard_gain)):
        return 'SUPPORTED'
    if accuracy or resolution:
        return 'MIXED'
    return 'NOT SUPPORTED'


def decide(frame: Any, runtime: Any, sanity: dict[str, Any]) -> dict[str, Any]:
    held = frame[(frame.split == 'HELD_OUT') & (frame.region == 'ALL')]
    base = held[held.method == 'R0']
    single = base[base.dataset == 'SINGLE']
    decisions: dict[str, Any] = {}
    for method in ('R1', 'R2', 'R3'):
        alternative = held[held.method == method]
        a = alternative[alternative.dataset == 'SINGLE']
        overall = 1-macro(a, 'rmse_hz')/macro(single, 'rmse_hz')
        fast = 1-macro(a[a.family == 'fast_chirp'], 'rmse_hz')/macro(
            single[single.family == 'fast_chirp'], 'rmse_hz')
        low = 1-macro(a[a.snr_db <= 0], 'rmse_hz')/macro(single[single.snr_db <= 0], 'rmse_hz')
        low_fast = 1-macro(a[(a.snr_db <= 0) & (a.family == 'fast_chirp')], 'rmse_hz')/macro(
            single[(single.snr_db <= 0) & (single.family == 'fast_chirp')], 'rmse_hz')
        recall_details = []
        for dataset in ('CORE', 'SINGLE', 'TWO'):
            for profile in ('ALL', 'balanced', 'high_time_resolution'):
                b = base[base.dataset == dataset]
                x = alternative[alternative.dataset == dataset]
                if profile != 'ALL':
                    b, x = b[b.profile == profile], x[x.profile == profile]
                bv, xv = macro(b, 'candidate_recall'), macro(x, 'candidate_recall')
                recall_details.append(dict(dataset=dataset, profile=profile, baseline=bv,
                                           alternative=xv, passed=bool(xv >= bv-1e-12)))
        gains = {}
        for region in ('CLOSE', 'LOW_SNR', 'FADE', 'CROSSING'):
            selected = frame[(frame.split == 'HELD_OUT') & (frame.dataset == 'TWO') &
                             (frame.region == region)]
            gains[region] = macro(selected[selected.method == method], 'resolution_rate')-macro(
                selected[selected.method == 'R0'], 'resolution_rate')
        false_increase = macro(alternative[(alternative.dataset != 'CORE') &
            (alternative.snr_db <= 0)], 'false_candidate_rate')-macro(base[
            (base.dataset != 'CORE') & (base.snr_db <= 0)], 'false_candidate_rate')
        noise = frame[(frame.split == 'HELD_OUT') & (frame.region == 'NOISE')]
        count_increase = macro(noise[noise.method == method], 'candidate_multiplicity')-macro(
            noise[noise.method == 'R0'], 'candidate_multiplicity')
        ratio = float(runtime[runtime.method == method].elapsed_s.mean()/
                      runtime[runtime.method == 'R0'].elapsed_s.mean())
        checks = dict(accuracy=bool(overall >= .10 or fast >= .20),
                      recall=all(r['passed'] for r in recall_details),
                      resolution=bool(any(g >= .10 for g in gains.values())),
                      false_candidates=bool(false_increase <= .02 and count_increase <= 1),
                      runtime=bool(ratio <= 5), hard_gain=bool(low >= .10 or low_fast >= .20 or
                          gains['LOW_SNR'] >= .10 or gains['FADE'] >= .10))
        verdict = gate_verdict(**checks) if sanity[method]['passed'] else 'NOT SUPPORTED'
        decisions[method] = dict(verdict=verdict, sanity_passed=sanity[method]['passed'],
            checks=checks, overall_rmse_improvement=overall, fast_rmse_improvement=fast,
            low_snr_improvement=low, low_snr_fast_improvement=low_fast,
            resolution_gains=gains, false_candidate_fraction_increase=false_increase,
            noise_candidates_per_frame_increase=count_increase,
            isolated_runtime_ratio=ratio, recall=recall_details)
    return decisions


def failure_maps(frame: Any) -> Any:
    held = frame[(frame.split == 'HELD_OUT') & (frame.region == 'ALL')]
    rows = []
    linear = ('stationary', 'slow_chirp', 'medium_chirp', 'fast_chirp')
    two = held[(held.dataset == 'TWO') & ~held.family.isin(('crossing', 'merging', 'diverging'))]
    single = held[(held.dataset == 'SINGLE') & held.family.isin(linear)]
    for name, selected, x, y, metric in (
        ('snr_separation', two, 'separation_hz', 'snr_db', 'resolution_rate'),
        ('snr_chirp', single, 'chirp_hz_per_s', 'snr_db', 'rmse_hz'),
        ('separation_amplitude_ratio', two, 'separation_hz', 'amplitude_ratio', 'resolution_rate'),
        ('separation_chirp_difference', two, 'separation_hz', 'slope_difference_hz_per_s',
         'resolution_rate')):
        for (method, profile, xv, yv), group in selected.groupby(['method', 'profile', x, y]):
            rows.append(dict(map=name, method=method, profile=profile, x_name=x, y_name=y,
                x_value=xv, y_value=yv, metric=metric, value=macro(group, metric),
                waveforms=group.waveform.nunique(), candidate_recall=macro(group, 'candidate_recall'),
                failure_rate=macro(group, 'failure_rate')))
    return pd.DataFrame(rows)


def denoising_evidence(frame: Any) -> Any:
    """Matched single-component low/high SNR cells; held-out, no cherry picking."""
    selected = frame[(frame.split == 'HELD_OUT') & (frame.region == 'ALL') &
                     (frame.dataset == 'SINGLE') & (frame.family.isin(
                         ('stationary', 'slow_chirp', 'medium_chirp', 'fast_chirp')))]
    keys = ['family', 'profile', 'carrier_hz', 'chirp_hz_per_s', 'amplitude_v', 'method']
    grouped = selected.groupby(keys+['snr_db']).failure_rate.mean().unstack('snr_db')
    joined = grouped.reset_index()
    joined['matched_low_fail_high_success'] = (joined[-20.] >= .2) & (joined[30.] <= .05)
    return joined


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output
    stages = ('single_calibration', 'single_held_out', 'two_core_calibration', 'two_core_held_out')
    frame = pd.concat([pd.read_csv(output/(s+'.csv')) for s in stages], ignore_index=True)
    agg = aggregates(frame)
    save(frame[frame.dataset == 'SINGLE'], output/'single_component_benchmark.csv')
    save(frame[(frame.dataset == 'SINGLE') & frame.family.str.contains('chirp')],
         output/'chirp_bias.csv')
    save(frame[frame.dataset == 'TWO'], output/'two_component_benchmark.csv')
    save(agg[agg.dataset == 'TWO'], output/'resolution_rate.csv')
    save(frame, output/'candidate_recall.csv')
    save(agg, output/'waveform_macro_summary.csv')
    save(failure_maps(frame), output/'failure_maps.csv')
    runtime = pd.read_csv(output/'runtime_isolated.csv')
    save(runtime, output/'runtime.csv')
    evidence = denoising_evidence(frame)
    save(evidence, output/'denoising_matched_conditions.csv')
    decisions = decide(frame, runtime, load_json(output/'phase_a_sanity.json'))
    write_json(output/'representation_gate.json', decisions)
    passed = [k for k, v in decisions.items() if v['verdict'] == 'SUPPORTED']
    if not passed:
        save(pd.DataFrame([dict(status='SKIPPED', reason='No method passed REPRESENTATION_GATE',
                                phase_d_executed=False)]), output/'optional_backend_comparison.csv')
        write_json(output/'skipped_stages.json', dict(phase_d='SKIPPED: no supported method',
            real='SKIPPED: no supported method', ch3='SKIPPED: evaluation-only, no new evaluation'))
    print(decisions, flush=True)


if __name__ == '__main__':
    main()
