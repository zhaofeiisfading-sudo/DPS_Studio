"""Inspect candidate unions, family exclusivity and paired overlap before fusion."""
from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task018.inputs import FAMILIES, METHODS, OUT, json_write
from scripts.research.task018.model import Candidate, clusters

PRIORITY = {m: i for i, m in enumerate(METHODS)}
WIDTH = 100e6


def points(frame: pd.DataFrame) -> list[Candidate]:
    return [Candidate(i.Index, i.estimator, i.family, i.frequency_hz, i.G, i.S,
                      (i.native_rank, PRIORITY[i.estimator]))
            for i in frame.itertuples() if i.C]


def read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, float_precision='round_trip', keep_default_na=True)


def identifies(row: Any) -> dict[str, Any]:
    return {key: getattr(row, key) for key in ('file', 'channel', 'time_s', 'sample_index',
                                             'primary', 'stage', 'segment_id', 'clipping_proxy')}


def direct_match(hz: float, targets: list[float], width: float = WIDTH) -> bool:
    return any(abs(hz-f) <= width for f in targets)


def summarize_channel(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    detail, pairs = [], []
    for _, slab in frame[frame.primary].groupby('sample_index', sort=False):
        loc = identifies(next(slab.itertuples()))
        candidates = points(slab)
        supports = [p for p in candidates if p.supported]
        b1 = [p.hz for p in candidates if p.estimator == 'B1']
        strong = [p.hz for p in candidates if p.estimator in ('B1', 'B2')]
        strong_s = [p.hz for p in supports if p.estimator in ('B1', 'B2')]
        for k, group in enumerate(clusters(candidates, WIDTH)):
            fam = {p.family for p in group}
            sfam = {p.family for p in group if p.supported}
            other = [p.hz for p in candidates if p not in group]
            unique = [p for p in group if not direct_match(p.hz, strong)]
            detail.append({**loc, 'cluster': k, 'lo_hz': group[0].hz, 'hi_hz': group[-1].hz,
                           'estimators': '|'.join(sorted({p.estimator for p in group})),
                           'families': '|'.join(sorted(fam)), 'family_n': len(fam),
                           'supported_families': '|'.join(sorted(sfam)), 'supported_family_n': len(sfam),
                           'member_n': len(group), 'S': bool(sfam),
                           'unmatched_B1': all(not direct_match(p.hz, b1) for p in group),
                           'unmatched_B1B2': len(unique) == len(group),
                           'unmatched_B1B2_S': bool(sfam) and all(
                               not direct_match(p.hz, strong_s) for p in group if p.supported),
                           'harmonic_like': any(abs(p.hz-r*x) <= WIDTH or abs(x-r*p.hz) <= WIDTH
                                                for p in group for x in other for r in (2, 3)),
                           'edge_like': any(p.hz <= 100e6 for p in group),
                           'low_background_gain': bool((slab.loc[[p.key for p in group],
                                                          'background_gain_db'] < 6).any())})
        for kind, units in (('family', FAMILIES), ('estimator', METHODS)):
            attr = 'family' if kind == 'family' else 'estimator'
            limit = slab[slab.applicable].groupby(attr).evaluation_max_hz.max().to_dict()
            for a, b in combinations(units, 2):
                if a not in limit or b not in limit:
                    continue
                high = min(limit[a], limit[b])
                v = [[p for p in candidates if getattr(p, attr) == key and p.hz <= high] for key in (a, b)]
                f, g = v
                sa, sb = (any(p.supported for p in series) for series in v)
                pairs.append(dict(channel=loc['channel'], stage=loc['stage'], kind=kind, a=a, b=b,
                    jointly_applicable=1, paired_C=int(bool(f and g)),
                    near_C=int(any(direct_match(p.hz, [x.hz for x in g]) for p in f)),
                    near_S=int(any(p.supported and direct_match(p.hz, [x.hz for x in g if x.supported])
                                   for p in f)),
                    joint_C_both_fail_S=int(bool(f and g) and not (sa or sb)),
                    joint_C_a_fails_S=int(bool(f and g) and not sa),
                    joint_C_b_fails_S=int(bool(f and g) and not sb)))
    return detail, pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='inputs_v1')
    parser.add_argument('--output', default='audit_v1')
    args = parser.parse_args()
    source, dest = ((OUT / 'data' / n).resolve() for n in (args.input, args.output))
    assert dest.parent == source.parent == (OUT / 'data').resolve()
    manifest = json.loads((source / 'complete.json').read_text(encoding='utf-8'))
    dest.mkdir(exist_ok=False)
    detail, paired = [], []
    for item in manifest['channels']:
        a, b = summarize_channel(read(source / f'{item["channel"]}.csv.gz'))
        detail.extend(a)
        paired.extend(b)
    table = pd.DataFrame(detail)
    table.to_csv(dest / 'candidate_union.csv', index=False, mode='x')
    table[table.family_n >= 2].to_csv(dest / 'cross_family_intersection.csv', index=False, mode='x')
    table[table.family_n == 1].to_csv(dest / 'family_exclusive.csv', index=False, mode='x')
    table[table.unmatched_B1B2].to_csv(dest / 'strong_stft_unmatched.csv', index=False, mode='x')
    aggregates = ['S', 'unmatched_B1', 'unmatched_B1B2', 'unmatched_B1B2_S', 'harmonic_like',
                  'edge_like', 'low_background_gain']
    for label, fields in (('stage', ['file', 'channel', 'stage']), ('family_sets', ['channel', 'families'])):
        by = table.groupby(fields)
        totals = by[aggregates].sum().assign(cluster_n=by.size())
        totals.to_csv(dest / f'{label}_counts.csv', mode='x')
    df = pd.DataFrame(paired)
    nums = [c for c in df if c not in ('channel', 'stage', 'kind', 'a', 'b')]
    for name, keys in (('channel_stage', ['channel', 'stage']), ('all', [])):
        totals = df.groupby([*keys, 'kind', 'a', 'b'])[nums].sum()
        n = totals.paired_C.replace(0, np.nan)
        pa, pb = totals.joint_C_a_fails_S/n, totals.joint_C_b_fails_S/n
        totals['co_failure_excess_over_product'] = totals.joint_C_both_fail_S/n - pa*pb
        totals['agreement_given_joint_C'] = totals.near_C/n
        totals.to_csv(dest / f'paired_{name}.csv', mode='x')
    json_write(dest / 'complete.json', dict(input=source.name, union=len(table),
        intersection=int((table.family_n >= 2).sum()), exclusive=int((table.family_n == 1).sum()),
        unmatched_strong=int(table.unmatched_B1B2.sum()),
        unmatched_strong_supported=int((table.unmatched_B1B2 & table.S).sum())))
    print((dest / 'complete.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()
