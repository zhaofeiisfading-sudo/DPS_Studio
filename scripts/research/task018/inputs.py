"""Re-execute existing estimators on exact raw sample centers and retain C/G/S."""
from __future__ import annotations

import copy
from dataclasses import replace
import importlib
import json
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Context, Signal
from dps_studio.core.segmentation.strategies import Strategy, estimate_strategy
from scripts.research.task017.compare import (
    Trace, align, common_centers, diagnose, digest, evidence, formal, frozen_plans, normalize, request,
)
from scripts.research.task017.prepare import OUT as OLD
from scripts.research.task017.prepare import ROOT
from scripts.research.task017.prepare import load, records
from scripts.research.task018.boundary import OUT as OUT

FMIN, FMAX = 50e6, 6e9
METHODS = ('B1', 'B2', 'B0', 'dechirp', 'varpro', 'clutter_varpro', 'low_glrt', 'matrix_pencil')
FAMILY = dict(zip(METHODS, ('STFT', 'STFT', 'STFT', 'Dechirp', 'VarPro', 'VarPro',
                           'LowGLRT', 'Subspace'), strict=True))
FAMILIES = tuple(dict.fromkeys(FAMILY.values()))
NATIVE = ('dechirp', 'varpro', 'clutter_varpro', 'matrix_pencil')
PROTOCOL = ROOT / 'docs/tasks/TASK-018/PROTOCOL.md'


def inventory() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plans = frozen_plans()
    items = records()
    paths = {p.relative_to(ROOT).as_posix(): p for p in (ROOT / 'data/raw').rglob('*')
             if p.is_file() and p.suffix.lower() in {'.csv', '.dat'}}
    assert set(paths) == {r['file'] for r in items} and len(paths) == 10
    assert len(items) == len(plans) == 14 and set(plans) == {r['id'] for r in items}
    for name, path in paths.items():
        data = np.loadtxt(path, delimiter=',', ndmin=2)
        groups = [r for r in items if r['file'] == name]
        sha = digest(path)
        assert {r['column'] for r in groups} == set(range(1, data.shape[1]))
        assert np.isfinite(data).all() and (np.diff(data[:, 0]) > 0).all()
        for item in groups:
            assert item['sha256'] == sha and item['samples'] == len(data)
            assert item['start_s'] == data[0, 0] and item['end_s'] == data[-1, 0]
            assert item['sample_rate_hz'] == 1/np.median(np.diff(data[:, 0]))
    return items, plans


def coordinates(item: dict[str, Any], t: Any, plan: list[dict[str, Any]]) -> pd.DataFrame:
    q = common_centers(len(t))
    stage, segment = np.full(len(q), '', dtype='U32'), np.full(len(q), '', dtype='U16')
    assert plan[0]['start_s'] == t[0] and plan[-1]['end_s'] == t[-1]
    for j, seg in enumerate(plan):
        if j:
            assert abs(seg['start_s']-plan[j-1]['end_s']) < 5e-15
        own = (t[q] >= seg['start_s']) & ((t[q] <= seg['end_s']) if j == len(plan)-1
                                          else (t[q] < seg['end_s']))
        assert not np.any(segment[own] != '')
        stage[own], segment[own] = seg['stage'], seg['id']
    primary = (q >= 1024) & (q <= len(t)-1024)
    with np.load(OLD / 'data/full_v01' / item['id'] / 'M1_balanced.npz') as old:
        for key, arr in dict(sample_index=q, time_s=t[q], primary_common_support=primary,
                             stage=stage, segment_id=segment).items():
            np.testing.assert_array_equal(arr, old[key], err_msg=f'{item["id"]} {key}')
    assert np.all(segment != '')
    return pd.DataFrame(dict(file=item['file'], channel=item['id'], sample_index=q,
                             time_s=t[q], primary=primary, stage=stage, segment_id=segment))


def strategy_trace(t: Any, y: Any, name: str, fmax: float) -> Trace:
    spec = {'B1': Strategy(width=512, hop=128, nfft=4096, boundary='full', degree=0),
            'B2': Strategy(width=2048, hop=128, nfft=4096, boundary='full', degree=0),
            'low_glrt': Strategy(width=4096, hop=128, boundary='full', degree=2, mode='glrt')}[name]
    started = perf_counter()
    result = estimate_strategy(replace(request(t, y, spec.width, fmax), segment=None), name, spec)
    return Trace(result.time_s, result.candidate_frequency_hz, result.frequency_hz,
                 np.asarray(result.quality), np.zeros(len(result.time_s)), spec.width, FMIN,
                 250e6 if name == 'low_glrt' else fmax, perf_counter()-started, {},
                 f'core.segmentation.strategies.estimate_strategy / {spec}')


def native_trace(context: Context, name: str) -> tuple[Trace, Trace | None]:
    module = importlib.import_module(f'dps_studio.algorithms.waveform.{name}.implementation')
    started = perf_counter()
    result = module.run(context)
    runtime = perf_counter()-started
    width = module.PARAMETERS.get('window', 384)
    source = f'{module.__name__}.run'
    trace = Trace(context.time_s, result.frequency_hz, result.accepted_hz, result.flags,
                  result.extra.get('chirp_hz_per_s', np.zeros(len(context.time_s))),
                  width, 5e6, 8e9, runtime, result.details, source)
    secondary = None
    if name == 'matrix_pencil':
        f = result.extra['secondary_frequency_hz']
        secondary = replace(trace, candidate=f, gated=np.full_like(f, np.nan),
                            flags=np.where(np.isfinite(f), 'SECONDARY_NO_NATIVE_GATE', result.flags),
                            runtime=0., source=source+' / secondary_frequency_hz')
    return trace, secondary


def make_rows(name: str, tr: Trace, t: Any, fs: float, coords: pd.DataFrame,
              ev: dict[str, Any], prefix_ev: dict[str, Any] | None, fmax: float,
              rank: int = 1, manual: Context | None = None) -> pd.DataFrame:
    if manual is None:
        values = normalize(tr, t, fs)
    else:
        # Manual diagnostic evaluates only frozen onset centers, never other frames.
        p, ok = align(tr.time, t, fs, coords.sample_index.to_numpy())
        values = {}
        for key, data in (('raw_frequency_hz', tr.candidate), ('gated_frequency_hz', tr.gated),
                          ('chirp_hz_s', tr.rate), ('quality', tr.flags)):
            a = np.full(len(coords), 'NOT_RUN_MANUAL_SCOPE', dtype='U128') if key == 'quality' \
                else np.full(len(coords), np.nan)
            a[ok] = data[p[ok]]
            values[key] = a
    q, raw, gate, flags = (coords.sample_index.to_numpy(), values['raw_frequency_hz'],
                           values['gated_frequency_hz'], values['quality'])
    width = tr.width
    status = np.full(len(q), 'RAN', dtype='U40')
    for substring, label in (('NO_NATIVE_CENTER', 'NO_NATIVE_CENTER'), ('NO_EVENT', 'NO_EVENT'),
                             ('PRE_EVENT', 'PRE_EVENT'), ('INSUFFICIENT', 'INSUFFICIENT_WINDOW'),
                             ('NOT_RUN_MANUAL_SCOPE', 'NOT_RUN_MANUAL_SCOPE')):
        status[np.char.find(flags, substring) >= 0] = label
    if name == 'low_glrt':
        status[(q < width//2) | (q > len(t)-width//2)] = 'NO_COMPLETE_GLRT_WINDOW'
    if rank > 1:
        # Applicability belongs to the estimator; NO_EVENT and PRE_EVENT also
        # apply when no second pole exists.
        gate[:] = np.nan
    applicable = status == 'RAN'
    valid = np.isfinite(raw) & (raw >= FMIN) & (raw <= min(fmax, tr.fmax)) & applicable
    hz = np.where(valid, raw, np.nan)
    gated = valid & np.isfinite(gate) & (gate >= FMIN) & (gate <= min(fmax, tr.fmax))
    result = coords.copy()
    result['estimator'], result['family'], result['native_rank'] = name, FAMILY[name], rank
    result['source'] = tr.source
    result['raw_frequency_hz'], result['frequency_hz'], result['native_gated_hz'] = raw, hz, gate
    result['chirp_hz_s'], result['native_quality'] = values['chirp_hz_s'], flags
    result['applicable'], result['run_status'] = applicable, status
    result['evaluation_max_hz'] = min(fmax, tr.fmax)
    result['C'], result['G'] = valid, gated
    result['candidate_status'] = np.where(valid, 'CANDIDATE', np.where(~applicable, status,
                                             np.where(np.isfinite(raw), 'OUTSIDE_BAND', 'NO_CANDIDATE')))
    result['gate_status'] = np.where(gated, 'PASSED', np.where(valid,
                                    'NOT_DEFINED' if rank > 1 else 'REJECTED', 'NO_LEGAL_CANDIDATE'))
    dinput = dict(time_s=coords.time_s.to_numpy(), frequency_hz=hz,
                  chirp_hz_s=values['chirp_hz_s'])
    for key, value in diagnose(dinput, ev, fs).items():
        result['S' if key == 'spectrally_supported' else key] = value
    if prefix_ev is not None:
        d = diagnose(dinput, prefix_ev, fs)
        result['prefix_S'] = d['spectrally_supported']
        result['prefix_background_gain_db'] = d['background_gain_db']
    return result


def prior_context(context: Context, t: Any, q: Any, start: float) -> Context:
    prior = copy.copy(context)
    keep = np.isin(context.centers, q)
    for key in ('centers', 'time_s', 'seed_indices', 'seed', 'contrast'):
        setattr(prior, key, getattr(context, key)[keep])
    prior.onset = int(np.searchsorted(t, start))
    prior.event = {**context.event, 'manual_onset_sample': prior.onset}
    return prior


def check_replay(frame: pd.DataFrame, path: Path) -> None:
    with np.load(path) as previous:
        for current, old in (('raw_frequency_hz', 'raw_frequency_hz'), ('chirp_hz_s', 'chirp_hz_s'),
                             ('native_gated_hz', 'gated_frequency_hz')):
            np.testing.assert_allclose(frame[current], previous[old], atol=.01, rtol=1e-10,
                                       equal_nan=True, err_msg=str(path))


def extract(item: dict[str, Any], plan: list[dict[str, Any]], dest: Path) -> dict[str, Any]:
    started = perf_counter()
    channel = item['id']
    t, y, fs = load(item)
    coords = coordinates(item, t, plan)
    q = coords.sample_index.to_numpy()
    onset = next(seg for seg in plan if seg['stage'] == 'onset')
    start = onset['start_s']
    ev = evidence(t, y, fs, q, onset['start_range_s'][0]-2e-9)
    # evidence spectra and tone fits are identical; only the background changes.
    prefix_end = min(len(t)//20, 2048)
    ev_prefix = evidence(t, y, fs, q[:0], float(t[prefix_end]))
    ev_prefix = {**ev, 'background': ev_prefix['background']}
    clipped = np.zeros(len(q), dtype=bool)
    for bound in (y.min(), y.max()):
        rail = (y == bound).astype(np.int8)
        triplets = np.flatnonzero(rail[2:] + rail[1:-1] + rail[:-2] == 3) + 1
        p = np.searchsorted(triplets, q-127)
        ok = p < len(triplets)
        clipped[ok] |= triplets[p[ok]] <= q[ok]+126
    coords['clipping_proxy'] = clipped
    ctx_start = perf_counter()
    context = Context(Signal(t, y, channel))
    timings = {'context': perf_counter()-ctx_start}
    rows, trace_by_name = [], {}
    fit_seconds = 0.
    for name in METHODS:
        second = None
        if name == 'B0':
            tr = formal(t, y)
        elif name in NATIVE:
            tr, second = native_trace(context, name)
        else:
            tr = strategy_trace(t, y, name, FMAX)
        trace_by_name[name] = tr
        timings[name] = tr.runtime
        fit_started = perf_counter()
        frame = make_rows(name, tr, t, fs, coords, ev, ev_prefix, FMAX)
        rows.append(frame)
        if second is not None:
            trace_by_name['secondary'] = second
            rows.append(make_rows(name, second, t, fs, coords, ev, ev_prefix, FMAX, 2))
        fit_seconds += perf_counter()-fit_started
        if name in ('B0', 'B1', *NATIVE):
            root, base = (('dc_controls_v01', 'demean512_control') if name == 'B1'
                          else ('full_v01', 'M1_balanced' if name == 'B0' else name))
            check_replay(frame, OLD / 'data' / root / channel / f'{base}.npz')
    result = pd.concat(rows, ignore_index=True)
    result.to_csv(dest / f'{channel}.csv.gz', index=False, mode='x')
    # Save real, unpadded coordinates only. Spectral plots recompute directly from raw.
    prior_rows = []
    onset_q = q[(coords.stage == 'onset') & coords.primary]
    for delta in (-5, -2, 0, 2, 5):
        prior = prior_context(context, t, onset_q, start+delta*1e-9)
        for name in ('dechirp', 'varpro'):
            tr, _ = native_trace(prior, name)
            frame = make_rows(name, tr, t, fs, coords, ev, None, FMAX, manual=prior)
            frame = frame[frame.sample_index.isin(onset_q)].copy()
            frame['prior_shift_ns'] = delta
            frame['prior_sample'] = prior.onset
            prior_rows.append(frame)
    pd.concat(prior_rows).to_csv(dest / f'{channel}__priors.csv.gz', index=False, mode='x')
    if channel == '20201214m_ch1':
        wide = []
        for name in METHODS:
            tr = (formal(t, y, fmax=8e9) if name == 'B0' else
                  strategy_trace(t, y, name, 8e9) if name in ('B1', 'B2') else trace_by_name[name])
            wide.append(make_rows(name, tr, t, fs, coords, ev, None, 8e9))
        wide.append(make_rows('matrix_pencil', trace_by_name['secondary'], t, fs, coords, ev,
                              None, 8e9, 2))
        pd.concat(wide).to_csv(dest / 'wide8.csv.gz', index=False, mode='x')
    return dict(channel=channel, file=item['file'], sha256=item['sha256'], fs_hz=fs,
                evaluated=int(coords.primary.sum()), onset=len(onset_q), timing_s=timings,
                support_two_backgrounds_s=fit_seconds, channel_wall_s=perf_counter()-started,
                waveform_context_event=context.event,
                clutter_residual_event=trace_by_name['clutter_varpro'].details.get('residual_event'),
                clutter_nuisance=trace_by_name['clutter_varpro'].details.get('nuisance'),
                diagnostic_prefix_end_sample=prefix_end, wavelength='unknown')


def json_write(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def head() -> str:
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
