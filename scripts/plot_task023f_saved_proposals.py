"""Plot saved ch3 proposals without reading raw or rerunning any search/selector."""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
from pathlib import Path
from typing import cast

import numpy as np
from matplotlib.figure import Figure

from dps_studio.research.task023f_proposals import SearchResult
from scripts.evaluate_task023f_frozen import searches_for_variant
from scripts.finalize_task023f_recovery import read_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    activation = json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
    for profile in ('balanced', 'high_time_resolution'):
        stem = f'ch3__{profile}__pdv_channel_1'
        rows = read_csv(output / 'real_streams' / (stem + '_provenance.csv'))
        with gzip.open(output / 'real_streams' / (stem + '_lineages.pickle.gz'), 'rb') as handle:
            cache = cast(dict[tuple[str, str], SearchResult], pickle.load(handle)['searches'])
        figure = Figure(figsize=(15, 11), layout='constrained')
        axes = figure.subplots(4, 2)
        for i, variant in enumerate(('P0', 'P1', 'P2', 'P3')):
            selected = [r for r in rows if r['variant'] == variant]
            times = np.asarray([float(r['time_s']) for r in selected]) * 1e9
            strongest = np.asarray([float(r['strongest_frequency_hz']) for r in selected]) / 1e9
            final = np.asarray([float(r['final_frequency_hz']) for r in selected]) / 1e9
            core = np.asarray([r['core'] == 'True' for r in selected])
            accepted = np.asarray([r['accepted'] == 'True' for r in selected])
            searches = searches_for_variant(cache, variant, activation)
            for j, axis in enumerate(axes[i]):
                axis.plot(times, strongest, color='black', lw=.8, label='strongest')
                for search in searches:
                    ix = np.asarray(search.window.indices, dtype=int)
                    if search.window.kind == 'CORE' and len(ix):
                        axis.axvspan(float(times[ix].min()), float(times[ix].max()), color='#ee7733', alpha=.13)
                    for proposal in search.proposals:
                        axis.plot(times[ix], np.asarray(proposal.state.frequencies_hz) / 1e9,
                                  color='#0077bb', alpha=.25, lw=.6)
                axis.plot([], [], color='#0077bb', alpha=.6, label='terminal proposals')
                axis.plot(times, final, color='#cc3311', lw=.9, linestyle='--', label='frozen final')
                axis.scatter(times[accepted], final[accepted], s=12, color='#eeaa33', label='accepted')
                axis.set(ylabel=f'{variant} frequency / GHz', ylim=(.05, 6))
                if j and core.any():
                    axis.set_xlim(float(times[core].min()) - 16, float(times[core].max()) + 16)
                if not i:
                    axis.set_title('Full record' if not j else 'Retained core + 16 ns display context')
            axes[i, 0].legend(loc='upper left', ncol=2, fontsize=7)
        for axis in axes[-1]:
            axis.set_xlabel('Time / ns')
        figure.suptitle(f'ch3 {profile}: saved proposals; orange = challenge window; no physical truth')
        path = output / 'figures' / (stem + '_proposal_overlay.png')
        if path.exists():
            raise FileExistsError(path)
        figure.savefig(path, dpi=150)


if __name__ == '__main__':
    main()
