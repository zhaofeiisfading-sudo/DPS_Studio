"""Verify real data lineage, artifact consistency and repository checks."""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from scripts.research.task017.compare import digest
from scripts.research.task017.prepare import ROOT, load
from scripts.research.task018.audit import read
from scripts.research.task018.fuse import PRIMARY
from scripts.research.task018.inputs import FMAX, FMIN, OUT, inventory, json_write


class Gallery(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if (tag, name) in {('img', 'src'), ('a', 'href')} and value:
                self.assets.add(value)


def delivery() -> dict[str, Any]:
    items, plans = inventory()
    stack = OUT / 'data/stack_v1'
    raw_n, onset_n, reviewed = 0, 0, 0
    figures = OUT / 'figures/v1'
    png, svg = [sorted(p for p in figures.glob('*.'+ext) if not p.stem.endswith('__D_curves'))
                for ext in ('png', 'svg')]
    assert {p.stem for p in png} == {p.stem for p in svg}
    for item in items:
        ch = item['id']
        t, _, _ = load(item)
        c = read(stack / f'{ch}__candidates.csv.gz')
        b = read(stack / f'{ch}__curves.csv.gz')
        p = read(stack / f'{ch}__peaks.csv.gz')
        for frame in (c, b, p):
            np.testing.assert_array_equal(frame.time_s.to_numpy(), t[frame.sample_index.to_numpy()])
            assert (frame.sample_index % 128 == 0).all()
        assert (c.G <= c.C).all() and (c.S <= c.C).all()
        assert c[c.C].frequency_hz.between(FMIN, FMAX).all()
        assert c[c.C].cluster.notna().all() and c[~c.C].cluster.isna().all()
        assert c.source_row.is_unique and np.isfinite(c[c.C].raw_frequency_hz).all()
        assert p[['S0_score', 'S1_score', 'S2_score']].apply(lambda a: a.between(0., 1.)).all().all()
        assert (p.S2_score <= p.S1_score).all()
        assert ((p.frequency_hi_hz - p.frequency_lo_hz) <= 100e6).all()
        for name in ('S0', 'S1', 'S2'):
            src = name+'_source_row'
            check = p[p[src] >= 0].merge(c, left_on=src, right_on='source_row', validate='many_to_one')
            np.testing.assert_array_equal(check[name+'_frequency_hz'], check.frequency_hz_y)
            np.testing.assert_array_equal(check.sample_index_x, check.sample_index_y)
            assert check.C.all()
            if name == 'S2':
                assert check.S.all()
            picked = p[p[name+'_selected']]
            chosen = b[(b.method == name) & b.selected]
            assert picked.sample_index.is_unique
            np.testing.assert_array_equal(picked[src], chosen.source_row)
        s = b[b.method == 'S2']
        assert np.array_equal(s.selected, s.S)
        valid = c[c.S].sample_index.unique()
        assert set(s[s.S].sample_index) == set(valid)
        pri = b[b.method.str.startswith('S3_')]
        assert (pri.stage == 'onset').all() and pri.primary.all()
        counts = b[b.primary].groupby('method').size()
        n = int(counts.B1)
        assert all(counts[k] == n for k in PRIMARY)
        raw_n += n
        onset = int(((s.stage == 'onset') & s.primary).sum())
        onset_n += onset
        assert all(counts[k] == onset for k in counts.index if k.startswith('S3_'))
        for suffix in ('A_spectrum', 'B_consensus', 'C_overlay', 'D_trajectories', 'E_onset',
                       *(f'stage_{p["id"]}' for p in plans[ch] if p['stage'] != 'onset')):
            assert (figures / f'{ch}__{suffix}.png').is_file()
        reviewed += 1
    assert onset_n == 69 and raw_n == 9475 and reviewed == 14
    for file in png:
        with Image.open(file) as im:
            assert im.width >= 2100 and im.height >= 900
            im.verify()
    for file in svg:
        assert ET.parse(file).getroot().tag.endswith('}svg')
    gallery = Gallery()
    gallery.feed((OUT / 'gallery_reviewed.html').read_text(encoding='utf-8'))
    assert len(gallery.assets) == 2*len(png) == 336
    for file_ref in gallery.assets:
        path = (OUT / file_ref).resolve()
        assert path.is_relative_to(figures) and path.is_file()
    return dict(files=10, channels=reviewed, common_centers=raw_n, onset_centers=onset_n,
                png=len(png), svg=len(svg), gallery_links=len(gallery.assets),
                figures_sha256={f.name: digest(f) for f in [*png, *svg]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='validation_v1')
    parser.add_argument('--run-tests', action='store_true')
    args = parser.parse_args()
    dest = (OUT / 'data' / args.output).resolve()
    assert dest.parent == (OUT / 'data').resolve()
    dest.mkdir(exist_ok=False)
    p, t = 'scripts/research/task018', 'tests/unit/test_task018_consensus.py'
    hygiene = 'scripts/maintenance/check_repo_hygiene.py'
    commands = dict(ruff=['-m', 'ruff', 'check', p, t],
                    mypy=['-m', 'mypy', '--explicit-package-bases', '--follow-imports=silent', p, t],
                    hygiene=[hygiene], hygiene_json=[hygiene, '--json'],
                    hygiene_staged=[hygiene, '--staged-only'])
    if args.run_tests:
        commands['pytest'] = ['-m', 'pytest', '-q', t, 'tests/unit/test_task017_real_research.py',
            'tests/unit/test_task013_git_hygiene.py', 'tests/unit/test_task009_migration.py',
            'tests/unit/test_task015_stage_strategies.py::'
            'test_motion_and_observation_quality_are_independent_and_legacy_noise_loads']
    results = {}
    for name, cmd in commands.items():
        process = subprocess.run([sys.executable, '-B', *cmd], cwd=ROOT, capture_output=True,
                                 encoding='utf-8', errors='replace')
        with (dest / f'{name}.txt').open('x', encoding='utf-8') as log:
            log.write(process.stdout+process.stderr)
        results[name] = dict(exit_code=process.returncode, args=cmd)
        print(name, process.returncode, flush=True)
    json_write(dest / 'checks.json', results)
    json_write(dest / 'delivery.json', delivery())
    print('Delivery verified', flush=True)
    if any(row['exit_code'] for row in results.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
