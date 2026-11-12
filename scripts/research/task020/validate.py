"""Verify the delivered real-data tables, atlas links and image containers."""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import numpy as np
from PIL import Image

from scripts.research.task017.compare import digest
from scripts.research.task017.prepare import load
from scripts.research.task018.audit import read
from scripts.research.task018.inputs import FMAX, FMIN, inventory, json_write
from scripts.research.task020.atlas import FOCUS
from scripts.research.task020.replay import OUT, STACK


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.targets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == 'id' and value:
                assert value not in self.ids
                self.ids.add(value)
            if name in ('href', 'src') and value:
                self.targets.add(value)


def verify_images(paths: set[Path]) -> None:
    namespace = '{http://www.w3.org/2000/svg}'
    for path in sorted(paths):
        if path.suffix == '.png':
            with Image.open(path) as img:
                assert img.width >= 1800 and img.height >= 600
                img.verify()
        else:
            svg = ElementTree.parse(path).getroot()
            assert svg.tag == namespace+'svg'
            assert 'Beat frequency (GHz)' in ''.join(svg.itertext())
            images = list(svg.iter(namespace+'image'))
            if path.stem.endswith(('_1', '_3')):
                n_panels = 3 if path.stem.endswith('_1') else 4
                # The background is the repeated, rasterized STFT. A narrow
                # colorbar may be embedded as one additional raster.
                assert len(images) in (n_panels, n_panels+1), path
                bands = sorted((float(img.get('width', '0')) for img in images), reverse=True)
                assert bands[0]-bands[n_panels-1] < 2., path
            elif path.stem.endswith('_2'):
                assert not images


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(OUT.resolve()):
        parser.error('Use TASK-020 or a fresh subdirectory inside it.')
    items, plans = inventory()
    atlas = Links()
    atlas.feed((out / 'gallery.html').read_text(encoding='utf-8'))
    paths = set()
    for target in atlas.targets:
        url = urlsplit(target)
        assert not url.scheme and not url.netloc
        if not url.path:
            assert url.fragment in atlas.ids
            continue
        path = (out / unquote(url.path)).resolve()
        assert path.is_relative_to(out) and path.is_file(), target
        paths.add(path)
    expected: set[Path] = set()
    counts = dict(total_centers=0, primary_centers=0, onset_centers=0)
    for item in items:
        channel = item['id']
        t, _, _ = load(item)
        centers = read(out / 'data/centers' / f'{channel}.csv')
        q = centers.sample_index.to_numpy()
        np.testing.assert_array_equal(q, np.arange(0, len(t), 128))
        np.testing.assert_array_equal(centers.time_s, t[q])
        for name in ('A', 'B', 'BS', 'C'):
            hz = centers[name+'_output_hz'].dropna()
            assert hz.between(FMIN, FMAX).all()
        assert centers.BS_output_hz.equals(centers.B_frequency_hz.where(centers.B_S))
        assert np.array_equal(centers.C_S, centers.C_output_hz.notna())
        assert not (centers.B_S & ~centers.C_S).any()
        assert centers.A_output_hz.equals(centers.A_native_gated_hz.where(centers.A_G))
        assert centers.B_output_hz.equals(centers.B_native_gated_hz.where(centers.B_G))
        for kind in ('candidates', 'peaks'):
            assert digest(out / 'data' / kind / f'{channel}.csv.gz') == digest(
                STACK / f'{channel}__{kind}.csv.gz')
        folder = out / 'figures' / channel
        stems = [f'{key}_{j}' for key in ('full', *(s['id'] for s in plans[channel]))
                 for j in range(1, 4)]
        if channel in FOCUS or channel == '20260630-1_ch1':
            stems.append('consensus')
        expected.update(folder / f'{stem}.{ext}' for stem in stems for ext in ('png', 'svg'))
        counts['total_centers'] += len(q)
        counts['primary_centers'] += int(centers.primary.sum())
        counts['onset_centers'] += int((centers.primary & (centers.stage == 'onset')).sum())
    assert counts == dict(total_centers=9690, primary_centers=9475, onset_centers=69)
    assert expected == {p for p in paths if p.suffix in ('.svg', '.png')}
    assert expected == set((out / 'figures').rglob('*.png')) | set(
        (out / 'figures').rglob('*.svg'))
    verify_images(expected)
    report = dict(channels=len(items), views=len(items)+sum(map(len, plans.values())),
                  image_pairs=len(expected)//2, local_file_links=len(paths), **counts)
    json_write(out / 'delivery_validation.json', report)
    print(report)


if __name__ == '__main__':
    main()
