"""Fuse audited candidates and export every peak, representative and ablation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task018.audit import WIDTH, identifies, points, read
from scripts.research.task018.extract import peak_working_set
from scripts.research.task018.inputs import FAMILIES, OUT, json_write
from scripts.research.task018.model import Candidate, Peak, clusters, vote

BASELINES = ('B0', 'B1', 'B2')
PRIMARY = (*BASELINES, 'S0', 'S1', 'S2')
SHIFTS = (-5, -2, 0, 2, 5)


def voter_caps(slab: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    a: dict[str, float] = {}
    b: dict[str, float] = {}
    for row in slab.itertuples():
        if row.applicable:
            a[row.estimator] = row.evaluation_max_hz
            b[row.family] = max(b.get(row.family, 0.), row.evaluation_max_hz)
    return a, b


def represent(loc: dict[str, Any], method: str, p: Peak | None, proposal: Peak | None,
              conflict: bool, groups: int) -> dict[str, Any]:
    r = p.representative if p else None
    return {**loc, 'method': method, 'C': proposal is not None, 'G': bool(r and r.gated),
            'S': bool(r and r.supported), 'selected': p is not None,
            'frequency_hz': r.hz if r else np.nan,
            'proposal_hz': (r or proposal.representative).hz if proposal else np.nan,
            'selected_source': r.estimator if r else '', 'native_rank': r.priority[0] if r else 0,
            'source_row': r.key if r else -1, 'cluster': p.cluster if p else -1,
            'score': p.score if p else np.nan, 'voters': p.voters if p else 0,
            'eligible': p.eligible if p else 0, 'cluster_n': groups,
            'conflict': conflict, 'quality': ('NO_S' if proposal and not r else
                    'NO_C' if not r else 'SUPPORTED_COMPETING' if r.supported and conflict else
                    'SUPPORTED_CROSS_FAMILY' if r.supported and p and p.voters >= 2 and method.startswith('S2')
                    else 'SUPPORTED' if r.supported else 'UNSUPPORTED')}


def baseline(loc: dict[str, Any], name: str, candidates: list[Candidate]) -> dict[str, Any]:
    r = next((p for p in candidates if p.estimator == name), None)
    p = Peak(-1, np.nan, np.nan, 1, 1, r, (name,)) if r else None
    return represent(loc, name, p, p, False, int(r is not None))


def choose(candidates: list[Candidate], caps: dict[str, float], width: float = WIDTH,
           ) -> tuple[list[list[Candidate]], list[Peak], list[Peak]]:
    groups = clusters(candidates, width)
    return groups, vote(groups, caps, family=True), vote(groups, caps, family=True, require_support=True)


def first(values: list[Peak]) -> Peak | None:
    return values[0] if values else None


def compare_frame(slab: pd.DataFrame, prior_slabs: dict[int, pd.DataFrame], *,
                  ablate: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                        list[dict[str, Any]]]:
    loc = identifies(next(slab.itertuples()))
    candidates = points(slab)
    estimator_caps, fam_caps = voter_caps(slab)
    groups, s1, s2 = choose(candidates, fam_caps)
    s0 = vote(groups, estimator_caps, family=False)
    chosen = [baseline(loc, b, candidates) for b in BASELINES]
    for name, peaks, pre in (('S0', s0, s0), ('S1', s1, s1), ('S2', s2, s1)):
        conflict = len(s2 if name == 'S2' else pre) > 1
        chosen.append(represent(loc, name, first(peaks), first(pre), conflict, len(pre)))
    s0dict, s1dict, s2dict = ({p.cluster: p for p in pe} for pe in (s0, s1, s2))
    peaks_out: list[dict[str, Any]] = []
    member: list[dict[str, Any]] = []
    for k, group in enumerate(groups):
        a, b, c = s0dict[k], s1dict[k], s2dict.get(k)
        f = b.representative.hz
        other = [p.hz for idx, g in enumerate(groups) if idx != k for p in g]
        harmonic = any(abs(f-r*x) <= WIDTH or abs(x-r*f) <= WIDTH for x in other for r in (2, 3))
        hi = b.score >= .6 and b.voters >= 3
        row = {**loc, 'cluster': k, 'frequency_lo_hz': group[0].hz, 'frequency_hi_hz': group[-1].hz,
               'frequency_hz': f, 'members': len(group), 'branches_at_center': len(groups),
               'S_clusters_at_center': len(s2), 'conflict': len(groups) > 1,
               'high_consensus': hi, 'high_without_S': hi and c is None,
               'high_in_noise_or_stationary': hi and loc['stage'] in ('noise', 'stationary'),
               'high_in_weak_signal': hi and loc['stage'] == 'weak_signal',
               'harmonic_like': harmonic, 'edge_like': f <= 100e6,
               'low_background_gain': bool(slab.loc[b.representative.key, 'background_gain_db'] < 6)}
        for name, x, selected in (('S0', a, s0[0]), ('S1', b, s1[0]), ('S2', c, first(s2))):
            prefix = name+'_'
            row.update({prefix+key: val for key, val in dict(
                score=x.score if x else 0., mass=x.mass if x else 0., voters=x.voters if x else 0,
                eligible=x.eligible if x else b.eligible, frequency_hz=x.representative.hz if x else np.nan,
                source_row=x.representative.key if x else -1, G=bool(x and x.representative.gated),
                S=bool(x and x.representative.supported), source=x.representative.estimator if x else '',
                contributors='|'.join(x.supporters) if x else '', selected=x is not None and x == selected,
            ).items()})
        peaks_out.append(row)
        member.extend(dict(source_row=p.key, cluster=k, S0_score=a.score, S1_score=b.score,
                           S2_score=c.score if c else 0., family_votes=b.voters,
                           supported_family_votes=c.voters if c else 0,
                           competing_clusters=len(groups)-1,
                           S0_selected=p.key == s0[0].representative.key,
                           S1_selected=p.key == s1[0].representative.key,
                           S2_selected=bool(s2 and p.key == s2[0].representative.key)) for p in group)
    if ablate and loc['primary']:
        def add(name: str, points_: list[Candidate], caps_: dict[str, float], width: float = WIDTH) -> None:
            _, u, v = choose(points_, caps_, width)
            chosen.append(represent(loc, name, first(v), first(u), len(v) > 1, len(u)))

        for family in FAMILIES:
            add('LOO_'+family, [p for p in candidates if p.family != family],
                {k: v for k, v in fam_caps.items() if k != family})
        merged = {('ChirpFit' if k in ('Dechirp', 'VarPro') else k): cap for k, cap in fam_caps.items()}
        add('S2_shared_seed', [Candidate(p.key, p.estimator,
                                        'ChirpFit' if p.family in ('Dechirp', 'VarPro') else p.family,
                                        p.hz, p.gated, p.supported, p.priority) for p in candidates], merged)
        for w in (50, 200):
            add(f'S2_width_{w}', candidates, fam_caps, w*1e6)
        add('S2_fixed_prefix', [Candidate(p.key, p.estimator, p.family, p.hz, p.gated,
                                         bool(slab.loc[p.key, 'prefix_S']), p.priority)
                                for p in candidates], fam_caps)
        if prior_slabs:
            for delta in SHIFTS:
                manual = prior_slabs[delta]
                # Only these two variants use human stage knowledge. The
                # Clutter VarPro branch keeps its native automatic trigger.
                combined = pd.concat([slab[~slab.estimator.isin(('dechirp', 'varpro'))], manual])
                _, fc = voter_caps(combined)
                add(f'S3_{delta:+d}ns', points(combined), fc)
    return chosen, peaks_out, member


def comparison(curves: pd.DataFrame) -> list[dict[str, Any]]:
    metrics = []
    denominator = curves[(curves.method == 'B1') & curves.primary]
    all_methods = list(curves.method.unique())
    onset_only = {m for m in all_methods if m.startswith('S3_')}
    channel = curves.channel.iloc[0]
    file = curves.file.iloc[0]
    labels = ['ALL', *denominator.stage.unique(), *denominator.segment_id.unique()]
    for label in labels:
        key = 'segment_id' if label.startswith('s') and label[1:].isdigit() else 'stage'
        indices = denominator.sample_index if label == 'ALL' else denominator.loc[denominator[key] == label,
                                                                                 'sample_index']
        data = curves[curves.sample_index.isin(indices)]
        def ordered(name: str) -> pd.DataFrame:
            return data[data.method == name].sort_values('sample_index')

        def get_pair(f: pd.DataFrame, b: pd.DataFrame) -> dict[str, int]:
            sa, sb = f.S.to_numpy(), b.S.to_numpy()
            fa, fb = f.frequency_hz.to_numpy(), b.frequency_hz.to_numpy()
            close = abs(fa-fb) <= WIDTH
            return dict(gain_n=int((sa & ~sb).sum()), loss_n=int((sb & ~sa).sum()),
                        net_n=int(sa.sum()-sb.sum()), frequency_gain_n=int((sa & ~(sb & close)).sum()),
                        frequency_loss_n=int((sb & ~(sa & close)).sum()),
                        branch_replacement_n=int((sa & sb & ~close).sum()),
                        gate_rejected_same_rescue_n=int((sa & close & ~b.G.to_numpy()).sum()))

        stage = 'ALL' if label == 'ALL' else data.stage.iloc[0]
        bases = {b: ordered(b) for b in (*BASELINES, 'S0', 'S1', 'S2')}
        for method in all_methods:
            if method in onset_only and stage != 'onset':
                continue
            f = ordered(method)
            assert np.array_equal(f.sample_index, indices)
            n = len(f)
            if not n:
                continue
            f0 = f.frequency_hz.to_numpy()
            adjacent = np.diff(f.sample_index) == 128
            jumps = np.abs(np.diff(f0))[adjacent]
            supported_jumps = np.abs(np.diff(np.where(f.S, f0, np.nan)))[adjacent]
            row = dict(file=file, channel=channel, stage=stage, segment_or_stage=label,
                method=method, centers=n, C_n=int(f.C.sum()), G_n=int(f.G.sum()), S_n=int(f.S.sum()),
                G_and_S_n=int((f.G & f.S).sum()), G_not_S_n=int((f.G & ~f.S).sum()),
                selected_n=int(f.selected.sum()), unsupported_n=int((f.selected & ~f.S).sum()),
                conflict_n=int(f.conflict.sum()), multi_C_n=int((f.cluster_n > 1).sum()),
                mean_selected_score=float(f.score.mean()),
                cross_family_selected_n=int((f.voters >= 2).sum()) if method.startswith(('S1', 'S2', 'S3', 'LOO')) else 0,
                adjacent_pairs_n=int(np.isfinite(jumps).sum()), jump_250MHz_n=int((jumps > 250e6).sum()),
                supported_adjacent_pairs_n=int(np.isfinite(supported_jumps).sum()),
                supported_jump_250MHz_n=int((supported_jumps > 250e6).sum()),
                max_jump_hz=float(np.nanmax(jumps)) if np.isfinite(jumps).any() else np.nan,
                first_S_time_s=float(f.loc[f.S, 'time_s'].min()),
                first_S_sample=float(f.loc[f.S, 'sample_index'].min()))
            for base, old in bases.items():
                for column, val in get_pair(f, old).items():
                    row[f'vs_{base}_{column}'] = val
            for key in ('C', 'G', 'S'):
                row[key+'_coverage'] = row[key+'_n']/n
            metrics.append(row)
    return metrics


def execute(frame: pd.DataFrame, prior: pd.DataFrame | None, dest: Path,
            channel: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    t0 = perf_counter()
    if prior is None:
        priors: dict[int, dict[int, pd.DataFrame]] = {}
    else:
        prior.index += len(frame)
        priors = {q: {d: df for d, df in group.groupby('prior_shift_ns')}
                  for q, group in prior.groupby('sample_index')}
    curves, peaks, members = [], [], []
    core_elapsed = 0.
    for q, slab in frame.groupby('sample_index', sort=False):
        t = perf_counter()
        a, b, c = compare_frame(slab, priors.get(q, {}), ablate=False)
        core_elapsed += perf_counter()-t
        if prior is not None and slab.primary.iloc[0]:
            ablations, _, _ = compare_frame(slab, priors.get(q, {}), ablate=True)
            a.extend(ablations[len(PRIMARY):])
        curves.extend(a)
        peaks.extend(b)
        members.extend(c)
    f = pd.DataFrame(curves)
    k = pd.DataFrame(peaks)
    full = frame.join(pd.DataFrame(members).set_index('source_row'))
    full.index.name = 'source_row'
    full.to_csv(dest / f'{channel}__candidates.csv.gz', mode='x')
    f.to_csv(dest / f'{channel}__curves.csv.gz', index=False, mode='x')
    k.to_csv(dest / f'{channel}__peaks.csv.gz', index=False, mode='x')
    if prior is not None:
        prior.index.name = 'source_row'
        prior.to_csv(dest / f'{channel}__prior_candidates.csv.gz', mode='x')
    comparisons = comparison(f)
    warnings = []
    count_fields = ['high_consensus', 'high_without_S', 'high_in_noise_or_stationary',
                    'high_in_weak_signal', 'harmonic_like', 'edge_like', 'low_background_gain',
                    'clipping_proxy']
    k = k[k.primary].copy()
    for label, group in [('ALL', k), *k.groupby('stage')]:
        counts = group[count_fields].sum().to_dict()
        for flag in ('harmonic_like', 'edge_like', 'low_background_gain', 'clipping_proxy'):
            counts['high_and_'+flag] = int((group.high_consensus & group[flag]).sum())
        warnings.append(dict(channel=frame.channel.iloc[0], file=frame.file.iloc[0], stage=label,
            clusters=len(group), centers_with_clusters=group.sample_index.nunique(),
            multi_cluster_centers=group.loc[group.conflict, 'sample_index'].nunique(),
            competing_S_centers=group.loc[group.S_clusters_at_center > 1, 'sample_index'].nunique(),
            **counts))
    return comparisons, warnings, dict(channel=channel, main_vote_s=core_elapsed,
                                       wall_with_ablation_export_s=perf_counter()-t0,
                                       fusion_peak_working_set_bytes=peak_working_set())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='inputs_v1')
    parser.add_argument('--audit', default='audit_v1')
    parser.add_argument('--output', default='stack_v1')
    args = parser.parse_args()
    t0 = perf_counter()
    parent = (OUT / 'data').resolve()
    source, audit, dest = ((parent / n).resolve() for n in (args.input, args.audit, args.output))
    assert source.parent == audit.parent == dest.parent == parent
    assert json.loads((audit / 'complete.json').read_text())['input'] == source.name
    manifest = json.loads((source / 'complete.json').read_text(encoding='utf-8'))
    dest.mkdir(exist_ok=False)
    all_metrics, warnings, timings = [], [], []
    for row in manifest['channels']:
        name = row['channel']
        m, w, tm = execute(read(source / f'{name}.csv.gz'), read(source / f'{name}__priors.csv.gz'), dest, name)
        all_metrics.extend(m)
        warnings.extend(w)
        timings.append(tm)
        print('fused', name, round(tm['wall_with_ablation_export_s'], 1), 's', flush=True)
    m, _, _ = execute(read(source / 'wide8.csv.gz'), None, dest, 'wide8')
    pd.DataFrame(m).to_csv(dest / 'wide8_metrics.csv', index=False, mode='x')
    results = pd.DataFrame(all_metrics)
    results.to_csv(dest / 'metrics.csv', index=False, mode='x')
    results[results.stage == 'onset'].to_csv(dest / 'onset_metrics.csv', index=False, mode='x')
    pd.DataFrame(warnings).to_csv(dest / 'consensus_warnings.csv', index=False, mode='x')
    json_write(dest / 'complete.json', dict(input=source.name, audit=audit.name, timings=timings,
                                           wall_s=perf_counter()-t0, stage_prior_domain='onset only'))


if __name__ == '__main__':
    main()
