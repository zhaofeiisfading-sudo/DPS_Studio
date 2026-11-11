"""Paired jump comparison and decomposition against the strong STFT union."""
from __future__ import annotations

import argparse
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task018.audit import read
from scripts.research.task018.figures import PHASES, save
from scripts.research.task018.inputs import OUT, inventory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--stack', default='stack_v1')
    parser.add_argument('--output', default='paired_v1')
    parser.add_argument('--figures', default='v1')
    args = parser.parse_args()
    base, plots = OUT / 'data', OUT / 'figures'
    src, dest, figure_dir = ((root / key).resolve() for root, key in
                            ((base, args.stack), (base, args.output), (plots, args.figures)))
    assert src.parent == dest.parent == base and figure_dir.parent == plots
    dest.mkdir(exist_ok=False)
    items, _ = inventory()
    results: list[dict[str, Any]] = []
    for item in items:
        ch = item['id']
        file = item['file']
        p = read(src / f'{ch}__peaks.csv.gz')
        p = p[p.primary]
        f = read(src / f'{ch}__curves.csv.gz')
        f = f[f.primary & f.method.isin(('B0', 'B1', 'B2', 'S0', 'S1', 'S2'))]
        b = f[f.method == 'B1']
        for stage, group in [('ALL', b), *b.groupby('stage')]:
            ff = f[f.sample_index.isin(group.sample_index)]
            q = group.sample_index.to_numpy()
            x = ff.pivot(index='sample_index', columns='method', values='frequency_hz')
            ss = ff.pivot(index='sample_index', columns='method', values='S')
            assert np.array_equal(q, x.index)
            a = ss.B1.to_numpy() & ss.S2.to_numpy()
            pair = (np.diff(q) == 128) & a[1:] & a[:-1]
            h = p[p.sample_index.isin(q)]
            strong = ss.B1 | ss.B2
            any_stft = ss.B0 | strong
            results.append(dict(channel=ch, file=file, stage=stage, centers=len(q),
                joint_supported_pairs=int(pair.sum()),
                **{name+'_jumps_on_joint_pairs': int((abs(np.diff(x[name]))[pair] > 250e6).sum())
                   for name in ('B1', 'S2')},
                B1_or_B2_supported=int(strong.sum()), any_STFT_supported=int(any_stft.sum()),
                S2_supported=int(ss.S2.sum()),
                new_B2_support_over_B1=int((ss.B2 & ~ss.B1).sum()),
                S2_support_beyond_B1_B2=int((ss.S2 & ~strong).sum()),
                S2_support_beyond_all_STFT=int((ss.S2 & ~any_stft).sum()),
                high_without_S=int(h.high_without_S.sum()),
                high_in_noise_or_stationary=int(h.high_in_noise_or_stationary.sum()),
                high_and_harmonic_like=int((h.high_consensus & h.harmonic_like).sum())))
    df = pd.DataFrame(results)
    df.to_csv(dest / 'paired_jumps_and_stft_union.csv', index=False, mode='x')
    agg = df.groupby('stage').sum(numeric_only=True)
    agg.to_csv(dest / 'paired_by_stage.csv', mode='x')
    names = [r['id'] for r in items]
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 6), layout='constrained')
    for ax, series, title in zip(axes, ('B1_jumps_on_joint_pairs', 'S2_jumps_on_joint_pairs', 'high_without_S'),
        ('B1 · jumps >250 MHz', 'S2 · jumps >250 MHz', 'S1 · high consensus without S'), strict=True):
        z = df.pivot(index='channel', columns='stage', values=series).reindex(index=names, columns=PHASES)
        cmap = 'OrRd' if series == 'high_without_S' else 'Blues'
        vmax = float(z.max().max()) if series == 'high_without_S' else float(df[
            ['B1_jumps_on_joint_pairs', 'S2_jumps_on_joint_pairs']].max().max())
        image = ax.imshow(z, aspect='auto', cmap=cmap, vmin=0, vmax=max(vmax, 1.))
        ax.set_facecolor('#eeeeee')
        ax.set(title=title, xticks=range(len(PHASES)), xticklabels=[p.replace('_', ' ') for p in PHASES],
               yticks=range(len(names)), yticklabels=names)
        ax.tick_params(axis='x', labelrotation=48, labelsize=8)
        ax.tick_params(axis='y', labelsize=7)
        for i, j in np.argwhere(np.isfinite(z.to_numpy())):
            v = z.iloc[i, j]
            ax.text(j, i, f'{v:.0f}', ha='center', va='center', fontsize=8,
                    color='white' if v > vmax*.62 else '#263547')
        fig.colorbar(image, ax=ax, shrink=.78)
    fig.suptitle('F4 · Paired jumps use the same supported adjacent centers; gray = no evaluated stage')
    save(fig, figure_dir / 'F4_stage_jumps_and_warnings')
    print(agg.to_string())


if __name__ == '__main__':
    main()
