"""Replay the frozen estimators, evidence and votes against retained TASK-018 data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from shutil import copyfile
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Context, Signal
from dps_studio.core.analysis_profiles import BALANCED_PROFILE
from scripts.research.task017.boundary import PRODUCTION, ROOT, git, manifest
from scripts.research.task017.compare import digest, evidence, formal
from scripts.research.task017.prepare import load
from scripts.research.task018.audit import WIDTH, points, read
from scripts.research.task018.fuse import choose, voter_caps
from scripts.research.task018.inputs import (
    FMAX, FMIN, METHODS, NATIVE, coordinates, inventory, json_write, make_rows,
    native_trace, strategy_trace,
)
from scripts.research.task018.inputs import OUT as FROZEN

OUT = ROOT / 'artifacts/TASK-020'
STACK = FROZEN / 'data/stack_v1'
INPUT = FROZEN / 'data/inputs_v1'
JUMP_HZ = 250e6


def boundary() -> dict[str, Any]:
    research, production = git(ROOT), git(PRODUCTION)
    return dict(research=research, production_git=production,
                index=digest(Path(research['common']) / 'index'),
                raw=manifest(ROOT / 'data/raw'), source=manifest(ROOT / 'src'),
                production=manifest(PRODUCTION),
                production_git_files=manifest(Path(production['common'])))


def compare_boundaries(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    checks = {key: before[key] == after[key] for key in after if key != 'research'}
    checks.update({f'research_{key}': before['research'][key] == after['research'][key]
                   for key in ('head', 'branch', 'common', 'staged')})
    return checks


def channel_data(channel: str) -> tuple[Any, Any, Any]:
    return tuple(read(STACK / f'{channel}__{kind}.csv.gz')
                 for kind in ('candidates', 'curves', 'peaks'))


def verify_rows(current: pd.DataFrame, archived: pd.DataFrame) -> None:
    for key in ('sample_index', 'time_s', 'primary', 'stage', 'segment_id', 'estimator',
                'native_rank', 'applicable', 'run_status', 'C', 'G', 'S',
                'native_quality', 'candidate_status', 'gate_status'):
        np.testing.assert_array_equal(current[key], archived[key], err_msg=key)
    for key in ('raw_frequency_hz', 'frequency_hz', 'native_gated_hz', 'chirp_hz_s',
                'spectral_contrast_db', 'background_gain_db', 'cycles_256', 'raw_tone_r2',
                'raw_chirp_r2', 'relative_strongest_db', 'competitor_advantage_db'):
        np.testing.assert_allclose(current[key], archived[key], rtol=1e-10,
                                   atol=.01 if 'hz' in key else 1e-8, err_msg=key)


def verify_fusion(candidates: pd.DataFrame, curves: pd.DataFrame, peaks: pd.DataFrame) -> float:
    started = perf_counter()
    replayed = []
    for q, slab in candidates.groupby('sample_index', sort=False):
        _, caps = voter_caps(slab)
        groups, s1, s2 = choose(points(slab), caps)
        replayed.append((q, groups, s1, s2))
    runtime = perf_counter()-started
    old_curves = curves.set_index(['sample_index', 'method'])
    old_peaks = peaks.set_index(['sample_index', 'cluster'])
    assert len(peaks) == sum(len(groups) for _, groups, _, _ in replayed)
    for q, _, s1, s2 in replayed:
        for name, pool in (('S1', s1), ('S2', s2)):
            old = old_curves.loc[(q, name)]
            assert bool(old.selected) == bool(pool)
            if pool:
                assert pool[0].representative.key == old.source_row
                np.testing.assert_allclose(pool[0].representative.hz, old.frequency_hz, atol=.01)
            for peak in pool:
                reference = old_peaks.loc[(q, peak.cluster)]
                assert peak.representative.key == reference[f'{name}_source_row']
                assert peak.voters == reference[f'{name}_voters']
                np.testing.assert_allclose(peak.score, reference[f'{name}_score'], atol=1e-14)
        if s1:
            assert len(s2) == int((old_peaks.loc[q].S2_voters > 0).sum())
    return runtime


def replay_channel(item: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
    archived, curves, peaks = channel_data(item['id'])
    t, y, fs = load(item)
    coords = coordinates(item, t, plan)
    coords['clipping_proxy'] = archived.iloc[:len(coords)].clipping_proxy.to_numpy()
    q = coords.sample_index.to_numpy()
    onset = next(seg for seg in plan if seg['stage'] == 'onset')
    started = perf_counter()
    ev = evidence(t, y, fs, q, onset['start_range_s'][0]-2e-9)
    evidence_s = perf_counter()-started
    started = perf_counter()
    context = Context(Signal(t, y, item['id']))
    context_s = perf_counter()-started
    timing = dict(channel=item['id'], context_s=context_s, evidence_shared_s=evidence_s)
    blocks = []
    for name in METHODS:
        secondary = None
        if name == 'B0':
            trace = formal(t, y)
        elif name in NATIVE:
            trace, secondary = native_trace(context, name)
        else:
            trace = strategy_trace(t, y, name, FMAX)
        timing[name+'_estimate_s'] = trace.runtime
        started = perf_counter()
        blocks.append(make_rows(name, trace, t, fs, coords, ev, None, FMAX))
        if secondary is not None:
            blocks.append(make_rows(name, secondary, t, fs, coords, ev, None, FMAX, 2))
        timing[name+'_audit_s'] = perf_counter()-started
    current = pd.concat(blocks, ignore_index=True)
    np.testing.assert_array_equal(current.index, archived.source_row)
    verify_rows(current, archived)
    vote_s = verify_fusion(current, curves, peaks)
    timing.update(vote_s=vote_s, A_s=timing['B0_estimate_s'], B_s=timing['B1_estimate_s'],
                  BS_s=timing['B1_estimate_s']+evidence_s+timing['B1_audit_s'],
                  S2_s=context_s+evidence_s+vote_s+sum(
                      timing[name+'_estimate_s']+timing[name+'_audit_s'] for name in METHODS))
    print(item['id'], len(coords), 'centers verified; S2', round(timing['S2_s'], 2), 's',
          flush=True)
    return timing


def readout(candidates: pd.DataFrame, curves: pd.DataFrame, peaks: pd.DataFrame) -> pd.DataFrame:
    a, b = (candidates[candidates.estimator == name].set_index('sample_index')
            for name in ('B0', 'B1'))
    s1, c = (curves[curves.method == name].set_index('sample_index') for name in ('S1', 'S2'))
    frame = b[['file', 'channel', 'time_s', 'primary', 'stage', 'segment_id',
               'clipping_proxy']].copy()
    for label, baseline in (('A', a), ('B', b)):
        for key in ('raw_frequency_hz', 'frequency_hz', 'native_gated_hz', 'native_quality',
                    'candidate_status', 'gate_status', 'C', 'G', 'S', 'relative_strongest_db',
                    'competitor_advantage_db'):
            frame[label+'_'+key] = baseline[key]
        frame[label+'_output_hz'] = baseline.native_gated_hz.where(baseline.G)
    for label, pool in (('S1', s1), ('C', c)):
        for key in ('S', 'selected', 'frequency_hz', 'quality', 'selected_source', 'source_row',
                    'voters', 'conflict', 'score'):
            frame[label+'_'+key] = pool[key]
    frame['BS_output_hz'] = b.frequency_hz.where(b.S)
    frame['C_output_hz'] = c.frequency_hz
    source = candidates.set_index('source_row').reindex(c.source_row)
    for key in ('native_rank', 'native_quality', 'relative_strongest_db',
                'competitor_advantage_db', 'raw_tone_r2', 'raw_chirp_r2'):
        frame['C_'+key] = source[key].to_numpy()
    for key, weights in (('prefilter_clusters', peaks.S1_voters > 0),
                         ('S_clusters', peaks.S2_voters > 0),
                         ('high_without_S', peaks.high_without_S)):
        frame[key] = weights.groupby(peaks.sample_index).sum().reindex(frame.index, fill_value=0)
    frame['S_STFT_union'] = candidates[candidates.family == 'STFT'].groupby('sample_index').S.any()
    assert not (b.S & ~c.S).any()
    assert np.array_equal(c.S, frame.S_clusters > 0)
    assert np.array_equal(b.S, frame.BS_output_hz.notna())
    assert not (c.S & ~source.S.fillna(False).to_numpy(dtype=bool)).any()
    frame['delta_C_minus_B_hz'] = c.frequency_hz-b.frequency_hz
    frame['C_new_S'] = c.S & ~b.S
    frame['C_replaces_supported_B'] = c.S & b.S & (frame.delta_C_minus_B_hz.abs() > WIDTH)
    frame['C_new_outside_STFT_union'] = c.S & ~frame.S_STFT_union
    frame['C_requires_native_chirp'] = c.S & (frame.C_raw_tone_r2 < .20)
    return frame.reset_index()


def metrics(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    shared = frame.primary
    d = frame[shared]
    row = dict(channel=frame.channel.iloc[0], stage=frame.stage.iloc[0] if label != 'all' else 'all',
               segment_or_stage=label, centers=len(d))
    consecutive = d.sample_index.diff() == 128
    b_pair = consecutive & d.BS_output_hz.notna() & d.BS_output_hz.shift().notna()
    c_pair = consecutive & d.C_output_hz.notna() & d.C_output_hz.shift().notna()
    paired = b_pair & c_pair
    for name in ('A', 'B', 'BS', 'C'):
        output = d[name+'_output_hz']
        s = d[('B' if name == 'BS' else name)+'_S']
        row.update({name+'_S': int(s.sum()), name+'_published': int(output.notna().sum()),
                    name+'_published_without_S': int((output.notna() & ~s).sum()),
                    name+'_jumps': int((consecutive & (output.diff().abs() > JUMP_HZ)).sum()),
                    name+'_first_S_time_s': d.loc[s, 'time_s'].min()})
    for key in ('prefilter_clusters', 'S_clusters', 'high_without_S', 'C_new_S',
                'C_replaces_supported_B', 'C_new_outside_STFT_union', 'C_requires_native_chirp'):
        row[key] = int(d[key].sum())
    row.update(B_raw_candidates=int(d.B_C.sum()), B_removed_by_S=int((d.B_C & ~d.B_S).sum()),
               S1_winners_without_S=int((d.S1_selected & ~d.S1_S).sum()),
               C_competing_centers=int((d.S_clusters > 1).sum()),
               C_single_family=int((d.C_S & (d.C_voters == 1)).sum()),
               shared_pairs=int(paired.sum()),
               shared_BS_jumps=int((paired & (d.BS_output_hz.diff().abs() > JUMP_HZ)).sum()),
               shared_C_jumps=int((paired & (d.C_output_hz.diff().abs() > JUMP_HZ)).sum()))
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('before', 'compare', 'after'))
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(OUT.resolve()):
        parser.error('Use TASK-020 or a fresh subdirectory inside it.')
    out.mkdir(parents=True, exist_ok=True)
    if args.phase in ('before', 'after'):
        snapshot = boundary()
        json_write(out / f'{args.phase}.json', snapshot)
        if args.phase == 'after':
            checks = compare_boundaries(json.loads((out / 'before.json').read_text(encoding='utf-8')),
                                        snapshot)
            json_write(out / 'boundaries.json', checks)
            print(checks, flush=True)
            if not all(checks.values()):
                raise RuntimeError(checks)
        return
    profile = BALANCED_PROFILE
    assert (profile.window_name, profile.window_length_samples, profile.hop_samples, profile.nfft,
            profile.minimum_frequency_hz, profile.maximum_frequency_hz) == (
                'hann', 1024, 64, 4096, FMIN, FMAX)
    items, plans = inventory()
    data = out / 'data'
    data.mkdir(exist_ok=False)
    for kind in ('centers', 'candidates', 'peaks'):
        (data / kind).mkdir()
    timing, changes, onsets = [], [], []
    summaries: list[dict[str, Any]] = []
    for item in items:
        channel = item['id']
        timing.append(replay_channel(item, plans[channel]))
        candidates, curves, peaks = channel_data(channel)
        frame = readout(candidates, curves, peaks)
        frame.to_csv(data / 'centers' / f'{channel}.csv', index=False, mode='x')
        for kind in ('candidates', 'peaks'):
            copyfile(STACK / f'{channel}__{kind}.csv.gz', data / kind / f'{channel}.csv.gz')
        groups = [('all', frame), *frame.groupby('stage', sort=False),
                  *frame.groupby('segment_id', sort=False)]
        summaries.extend(metrics(group, name) for name, group in groups)
        changes.append(frame[frame.primary & (frame.C_new_S | frame.C_replaces_supported_B)])
        onsets.append(frame[frame.primary & (frame.stage == 'onset')])
    for name, table in (('timing', pd.DataFrame(timing)), ('stage_diagnostics', pd.DataFrame(summaries)),
                        ('paired_changes', pd.concat(changes)), ('onset_centers', pd.concat(onsets))):
        table.to_csv(data / f'{name}.csv', index=False, mode='x')
    json_write(data / 'replay.json', dict(channels=[r['id'] for r in items], candidates='C/G/S matched',
                                         fusion='S1/S2 winners and peak scores matched',
                                         frozen_inputs_sha256=digest(INPUT / 'preflight.json')))


if __name__ == '__main__':
    main()
