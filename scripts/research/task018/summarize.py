"""Generate readout tables without changing the frozen denominators or selections."""
from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task018.audit import read
from scripts.research.task018.fuse import PRIMARY
from scripts.research.task018.inputs import OUT, inventory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='readout_v1')
    parser.add_argument('--stack', default='stack_v1')
    parser.add_argument('--input', default='inputs_v1')
    args = parser.parse_args()
    base = OUT / 'data'
    dest, stack, initial = ((base / n).resolve() for n in (args.output, args.stack, args.input))
    assert dest.parent == stack.parent == initial.parent == base
    dest.mkdir(exist_ok=False)
    inputs = json.loads((initial / 'complete.json').read_text(encoding='utf-8'))
    fusion = json.loads((stack / 'complete.json').read_text(encoding='utf-8'))
    times = {v['channel']: v for v in fusion['timings']}
    metrics = read(stack / 'metrics.csv')
    aggregates = metrics[metrics.stage == metrics.segment_or_stage]
    count = [c for c in metrics if c.endswith('_n') or c == 'centers']
    for label, keys in [('file_stage', ['file']), ('all_stage', [])]:
        table = aggregates.groupby([*keys, 'stage', 'method'])[count].sum()
        for kind in ('C', 'G', 'S'):
            table[kind+'_coverage'] = table[kind+'_n']/table.centers
        table.to_csv(dest / f'{label}.csv', mode='x')
    items, plans = inventory()
    phase_status = []
    swaps: list[pd.DataFrame] = []
    onset: list[pd.DataFrame] = []
    flagged: list[pd.DataFrame] = []
    extrema: list[dict[str, Any]] = []
    applicability: list[pd.DataFrame] = []
    for item in items:
        ch = item['id']
        for stage in sorted({p['stage'] for segs in plans.values() for p in segs}):
            n = sum(p['stage'] == stage for p in plans[ch])
            phase_status.append(dict(file=item['file'], channel=ch, stage=stage,
                                     frozen_segments=n, status='present' if n else 'not applicable'))
        selected = read(stack / f'{ch}__curves.csv.gz')
        f = selected[selected.primary & selected.method.isin(PRIMARY)]
        peaks = read(stack / f'{ch}__peaks.csv.gz')
        cand = read(stack / f'{ch}__candidates.csv.gz').query('primary')
        applicability.append(cand.groupby(['file', 'channel', 'stage', 'estimator', 'native_rank',
                                            'candidate_status']).size().rename('count').reset_index())
        flags = peaks[peaks.primary & peaks.high_consensus]
        flagged.append(flags[flags.high_without_S | flags.high_in_noise_or_stationary |
                             flags.high_in_weak_signal | flags.harmonic_like | flags.edge_like |
                             flags.low_background_gain | flags.clipping_proxy])
        start = next(p['start_s'] for p in plans[ch] if p['stage'] == 'onset')
        on = selected[selected.primary & (selected.stage == 'onset')].copy()
        on['from_frozen_start_ns'] = (on.time_s-start)*1e9
        onset.append(on)
        compare = f[f.method.isin(('B1', 'S2'))].pivot(index='sample_index', columns='method',
            values=['S', 'G', 'frequency_hz', 'selected_source', 'native_rank'])
        diff = compare['frequency_hz'].S2 - compare['frequency_hz'].B1
        both = compare['S'].S2 & compare['S'].B1
        swap = both & (abs(diff) > 100e6)
        gain = compare['S'].S2 & ~compare['S'].B1
        selection = compare[gain | swap].copy()
        selection.columns = ['_'.join(c) for c in selection.columns]
        coordinates = f[f.method == 'B1'].set_index('sample_index')[['file', 'channel', 'time_s',
                                                                     'stage', 'segment_id']]
        selection = coordinates.join(selection, how='inner')
        selection['status'] = np.where(swap[selection.index], 'supported_branch_replacement',
                                       'new_supported_center')
        selection['delta_hz'] = diff[selection.index]
        swaps.append(selection.reset_index())
        for (segment, method), group in f[f.S].groupby(['segment_id', 'method']):
            if group.stage.iloc[0] not in ('decline', 'rebound', 'acceleration', 'plateau'):
                continue
            d = dict(file=item['file'], channel=ch, stage=group.stage.iloc[0], segment_id=segment,
                     method=method, supported_n=len(group))
            for label, fn in (('min', 'idxmin'), ('max', 'idxmax')):
                pick = group.loc[getattr(group.frequency_hz, fn)()]
                d[label+'_hz'], d[label+'_time_s'] = pick.frequency_hz, pick.time_s
            extrema.append(d)
    pd.DataFrame(phase_status).to_csv(dest / 'stage_applicability.csv', index=False, mode='x')
    pd.concat(swaps).to_csv(dest / 's2_b1_changes.csv', index=False, mode='x')
    pd.concat(onset).to_csv(dest / 'all_onset_centers.csv', index=False, mode='x')
    pd.concat(flagged).to_csv(dest / 'suspicious_high_consensus.csv', index=False, mode='x')
    pd.concat(applicability).to_csv(dest / 'estimator_applicability.csv', index=False, mode='x')
    pd.DataFrame(extrema).to_csv(dest / 'supported_stage_extrema.csv', index=False, mode='x')
    rt = []
    for row in inputs['channels']:
        name = row['channel']
        tm = times[name]
        rt.append(dict(channel=name, file=row['file'], **row['timing_s'],
                       S2_compute_before_evidence_s=sum(row['timing_s'].values())+tm['main_vote_s'],
                       raw_support_both_backgrounds_s=row['support_two_backgrounds_s'],
                       extraction_wall_s=row['channel_wall_s'],
                       **{key: val for key, val in tm.items() if key != 'channel'},
                       extraction_worker_peak_MiB=row['worker_peak_working_set_bytes']/2**20))
    pd.DataFrame(rt).to_csv(dest / 'timing.csv', index=False, mode='x')
    print('Readout:', dest, flush=True)


if __name__ == '__main__':
    main()
