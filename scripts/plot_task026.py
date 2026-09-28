"""Deterministic publication-style plots of saved TASK-026 measurements only."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.freeze_task026 import load_json

COLORS = ('#0072B2', '#D55E00', '#009E73', '#CC79A7')
STYLES = ('-', '--', '-.', ':')
PROFILES = ('balanced', 'high_time_resolution')


def export(fig: Any, output: Path, name: str) -> None:
    for suffix in ('png', 'svg'):
        path = output/'figures'/f'{name}.{suffix}'
        if path.exists():
            raise FileExistsError(path)
        fig.savefig(path, dpi=300, bbox_inches='tight')
    plt.close(fig)


def lines(frame: Any, output: Path, name: str, x: str, metric: str,
          xlabel: str, ylabel: str, *, xscale: float = 1., yscale: float = 1.) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout='constrained', sharey=True)
    for ax, profile in zip(axes, PROFILES):
        selected = frame[frame.profile == profile]
        for i, method in enumerate(('R0', 'R1', 'R2', 'R3')):
            group = selected[selected.method == method].groupby(x)[metric]
            value, sd = group.mean(), group.std()
            ax.errorbar(value.index.to_numpy()*xscale, value.to_numpy()*yscale,
                yerr=sd.to_numpy()*yscale, label=method, color=COLORS[i], linestyle=STYLES[i],
                marker=('o', 's', '^', 'd')[i], markersize=3, capsize=2, linewidth=1)
        ax.set(xlabel=xlabel, title=profile.replace('_', ' '))
        ax.legend(frameon=False, ncol=2)
    axes[0].set_ylabel(ylabel)
    fig.supxlabel('Held-out waveform means; bars = descriptive waveform SD, not CI', fontsize=8)
    export(fig, output, name)


def maps(output: Path) -> None:
    frame = pd.read_csv(output/'failure_maps.csv')
    labels = {'separation_hz': ('Nominal center separation (MHz)', 1e-6),
              'snr_db': ('Pre-fade target SNR (dB)', 1.),
              'chirp_hz_per_s': ('Chirp rate (10$^{16}$ Hz/s)', 1e-16),
              'slope_difference_hz_per_s': ('Slope difference (10$^{16}$ Hz/s)', 1e-16),
              'amplitude_ratio': ('Nuisance / target amplitude', 1.)}
    for name, group in frame.groupby('map'):
        fig, axes = plt.subplots(2, 4, figsize=(12, 6), layout='constrained')
        rmse = name == 'snr_chirp'
        vmax = float(group.value.max()/1e6) if rmse else 100.
        mesh = None
        for p, profile in enumerate(PROFILES):
            for m, method in enumerate(('R0', 'R1', 'R2', 'R3')):
                ax = axes[p, m]
                cell = group[(group.profile == profile) & (group.method == method)]
                if not len(cell):
                    ax.text(.5, .5, 'NOT TESTED', ha='center', transform=ax.transAxes)
                    continue
                table = cell.pivot(index='y_value', columns='x_value', values='value')
                xlabel, xs = labels[cell.x_name.iloc[0]]
                ylabel, ys = labels[cell.y_name.iloc[0]]
                mesh = ax.imshow(table.to_numpy()*(1e-6 if rmse else 100), origin='lower',
                                 aspect='auto', cmap='viridis', vmin=0, vmax=vmax)
                ax.set_xticks(range(len(table.columns)), [f'{v*xs:g}' for v in table.columns],
                              rotation=45)
                ax.set_yticks(range(len(table.index)), [f'{v*ys:g}' for v in table.index])
                ax.set_title(f'{method} | {profile.replace("_", " ")}')
                ax.set_xlabel(xlabel)
                if m == 0:
                    ax.set_ylabel(ylabel)
        if mesh is not None:
            fig.colorbar(mesh, ax=axes.ravel().tolist(), shrink=.75,
                         label='Frequency RMSE (MHz)' if rmse else 'Two-component resolution (%)')
        fig.suptitle('Held-out physical grid; equal waveform weighting over remaining registered axes',
                     fontsize=10)
        export(fig, output, name+'_map')


def representative_plots(output: Path) -> None:
    rows = load_json(output/'seed_registration.json')
    selected = [r for r in rows if r['instance'] == 1 and r['dataset'] != 'CORE' and
                r['carrier_hz'] == 3e9 and r['amplitude_v'] == 1 and r['snr_db'] in (-20., 10.)
                and (r['family'] == 'stationary' or
                     (r['family'] == 'fast_chirp' and r['chirp_hz_per_s'] == 4e16) or
                     (r['family'] == 'crossing' and r['separation_hz'] == 150e6))]
    for row in selected:
        fig, axes = plt.subplots(2, 4, figsize=(12, 6), sharex=True, sharey=True,
                                 layout='constrained')
        mesh = None
        for p, profile in enumerate(PROFILES):
            with np.load(output/'streams'/f'{row["waveform"]}__{profile}.npz') as arrays:
                freq, time = arrays['frequency_axis_hz'], arrays['time_s']
                band = (freq >= 1.5e9) & (freq <= 4.5e9)
                for m, method in enumerate(('R0', 'R1', 'R2', 'R3')):
                    ax = axes[p, m]
                    amplitude = arrays[method+'_representation']
                    # Same normalization rule/dB color scale, separately normalized operators.
                    db = 20*np.log10(np.maximum(amplitude/np.max(amplitude), 1e-4))
                    mesh = ax.pcolormesh(time*1e9, freq[band]*1e-9, db[band], shading='nearest',
                                         cmap='cividis', vmin=-50, vmax=0, rasterized=True)
                    ax.plot(time*1e9, arrays['truth_hz']*1e-9, color='white', lw=1.2)
                    ax.plot(time*1e9, arrays['nuisance_hz']*1e-9, color='white', lw=1.2, ls='--')
                    hypotheses = arrays[method+'_frequency_hz']
                    ax.scatter(np.broadcast_to(time[:, None], hypotheses.shape)*1e9,
                               hypotheses*1e-9, s=2, color='#E69F00', alpha=.7)
                    ax.plot(time*1e9, hypotheses[:, 0]*1e-9, color='#56B4E9', lw=.8)
                    ax.set_title(f'{method} | {profile.replace("_", " ")}')
                    ax.set_ylim(1.5, 4.5)
                    if p == 1:
                        ax.set_xlabel('Time (ns)')
                    if m == 0:
                        ax.set_ylabel('Frequency (GHz)')
        if mesh is not None:
            fig.colorbar(mesh, ax=axes.ravel().tolist(), shrink=.75,
                         label='dB / representation maximum (not common physical energy)')
        fig.suptitle(f'{row["family"]}, {row["snr_db"]:g} dB, {row["waveform"]}: '
                     'white = truth; orange = <=20 hypotheses; blue = strongest', fontsize=10)
        export(fig, output, f'representation_{row["family"]}_{int(row["snr_db"])}dB')
        with np.load(output/'waveforms'/f'{row["waveform"]}.npz') as raw:
            fig, ax = plt.subplots(figsize=(9, 2.5), layout='constrained')
            ax.plot(raw['time_s']*1e9, raw['voltage_v'], color='#0072B2', linewidth=.4)
            ax.set(xlabel='Time (ns)', ylabel='Unmodified voltage (V)',
                   title=f'{row["waveform"]} | {row["family"]} | {row["snr_db"]:g} dB')
            export(fig, output, f'waveform_{row["family"]}_{int(row["snr_db"])}dB')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.fonttype': 'none'})
    frame = pd.read_csv(output/'candidate_recall.csv')
    held = frame[(frame.split == 'HELD_OUT') & (frame.region == 'ALL')]
    single = held[held.dataset == 'SINGLE']
    lines(single, output, 'frequency_error_vs_snr', 'snr_db', 'rmse_hz',
          'Pre-fade target SNR (dB)', 'Frequency RMSE (MHz)', yscale=1e-6)
    linear = single[single.family.isin(('stationary', 'slow_chirp', 'medium_chirp', 'fast_chirp'))]
    lines(linear[linear.snr_db == 30], output, 'bias_vs_chirp_rate', 'chirp_hz_per_s', 'bias_hz',
          'Chirp rate (10$^{16}$ Hz/s)', 'Signed frequency bias (MHz)', xscale=1e-16, yscale=1e-6)
    lines(held[(held.dataset == 'TWO') & ~held.family.isin(('crossing', 'merging', 'diverging'))],
          output, 'resolution_vs_separation', 'separation_hz', 'resolution_rate',
          'Nominal center separation (MHz)', 'Two-component resolution (%)',
          xscale=1e-6, yscale=100)
    maps(output)
    representative_plots(output)


if __name__ == '__main__':
    main()
