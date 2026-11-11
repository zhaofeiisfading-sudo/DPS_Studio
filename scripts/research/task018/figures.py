"""Render the all-channel atlas and evidence summaries from retained real rows."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from scipy.signal import stft  # type: ignore[import-untyped]

from scripts.research.task017.prepare import load
from scripts.research.task018.audit import read
from scripts.research.task018.fuse import PRIMARY
from scripts.research.task018.inputs import OUT, inventory

COLORS = dict(B0='#4f5764', B1='#167db0', B2='#a25b15', S0='#9a6eaf', S1='#458256', S2='#c72c58')
BAND = (.05, 6.)
PHASES = ('stationary', 'unknown', 'onset', 'acceleration', 'plateau', 'decline',
          'rebound', 'weak_signal', 'noise')


def save(fig: Any, path: Path) -> None:
    for ext in ('png', 'svg'):
        with path.with_suffix('.'+ext).open('xb') as handle:
            fig.savefig(handle, format=ext, dpi=210, facecolor='white')
    plt.close(fig)


def raw_map(t: Any, y: Any, fs: float, width: int, detrend: str | bool,
            high: float) -> tuple[Any, Any, Any]:
    f, x, z = stft(y, fs, nperseg=width, noverlap=width-128, nfft=4096, window='hann',
                   detrend=detrend, boundary=None, padded=False)
    keep = f <= high
    power = np.square(np.abs(z[keep]))
    assert np.isfinite(power).all()
    return (t[0]+x, f[keep]/1e9,
            10*np.log10(np.maximum(power, 1e-30)/max(float(power.max()), 1e-30)))


def image(ax: Any, x: Any, y: Any, z: Any, **kwargs: Any) -> Any:
    dx, dy = (x[1]-x[0])/2, (y[1]-y[0])/2
    return ax.imshow(z, origin='lower', aspect='auto', interpolation='nearest',
                     extent=(x[0]-dx, x[-1]+dx, y[0]-dy, y[-1]+dy), **kwargs)


def marks(ax: Any, plan: list[dict[str, Any]], x: Any, labels: bool = False) -> None:
    left, right = ax.get_xlim()
    for seg in plan:
        a, b = x(seg['start_s']), x(seg['end_s'])
        if left < a < right:
            ax.axvline(a, color='#758396', lw=.55, ls='--', alpha=.8)
        if seg['stage'] == 'onset':
            ax.axvspan(a, b, color='#7e9bb3', alpha=.17, lw=0)
        if labels and (b-a) > (right-left)*.055:
            ax.text((a+b)/2, 1.012, seg['stage'].replace('_', ' '), ha='center',
                    transform=ax.get_xaxis_transform(), fontsize=7, clip_on=True)


def curve(ax: Any, f: pd.DataFrame, name: str, x: Any, markers: bool = False) -> None:
    fr = f[f.method == name]
    time, hz = x(fr.time_s), fr.frequency_hz/1e9
    lw = 1.12 if name == 'S2' else .75
    c = COLORS[name]
    ax.plot(time, hz, lw=lw, color=c, alpha=.85 if name == 'S2' else .66,
            label=name, zorder=3 if name == 'S2' else 2)
    if markers:
        ax.scatter(time[fr.C], (fr.proposal_hz/1e9)[fr.C], s=18, marker='o',
                   facecolors='none', edgecolors=c, lw=.8)
        ax.scatter(time[fr.G], hz[fr.G], s=18, marker='+', c=c, lw=.9)
        ax.scatter(time[fr.S], hz[fr.S], s=12, marker='o', c=c, zorder=4)


def legends(ax: Any) -> None:
    ax.legend(loc='upper right', ncol=3, fontsize=8, framealpha=.9)


def configure(ax: Any, xlim: tuple[float, float], ylim: tuple[float, float] = BAND) -> None:
    ax.set(xlim=xlim, ylim=ylim, ylabel='Beat frequency (GHz)')


def heat(ax: Any, f: pd.DataFrame, p: pd.DataFrame, name: str, x: Any) -> Any:
    query = f[f.method == 'B1']
    grid = np.linspace(.05, 6., 299)
    z = np.zeros((len(grid), len(query)))
    index = {q: j for j, q in enumerate(query.sample_index)}
    for row in p.itertuples():
        hz = getattr(row, name+'_frequency_hz')/1e9
        if not np.isfinite(hz):
            continue
        j = index[row.sample_index]
        i = np.searchsorted(grid, hz)
        window = slice(max(0, i-3), min(len(grid), i+3))
        score = getattr(row, name+'_score')*np.clip(1-abs(grid[window]-hz)/.05, 0, 1)
        z[window, j] = np.maximum(z[window, j], score)
    return image(ax, x(query.time_s.to_numpy()), grid, z, vmin=0, vmax=1, cmap='magma')


def onset_figure(channel: str, t: Any, y: Any, fs: float, plan: Any, curves: pd.DataFrame,
                 peaks: pd.DataFrame, path: Path, window: dict[str, Any] | None = None) -> None:
    seg = window or next(s for s in plan if s['stage'] == 'onset')
    ref = seg['start_s']
    def x(time: Any) -> Any:
        return (time-ref)*1e9
    end = x(seg['end_s'])
    span = (-max(10., min(end*.15, 28.)), end+max(10., min(end*.15, 28.)))
    fig, axes = plt.subplots(4, 1, figsize=(11, 9.5), sharex=True, layout='constrained',
                             gridspec_kw={'height_ratios': [1.25, 1, 1, .65]})
    xx, ff, zz = raw_map(t, y, fs, 256, 'linear', 6e9)
    local = (x(xx) > span[0]-8) & (x(xx) < span[1]+8)
    img = image(axes[0], x(xx[local]), ff, zz[:, local], vmin=-58, vmax=0, cmap='viridis')
    # Inset colorbar keeps the time scales physically aligned across panels.
    fig.colorbar(img, cax=axes[0].inset_axes([.88, .06, .105, .055]), orientation='horizontal',
                 ticks=[-58, 0]).ax.tick_params(labelsize=6, pad=0)
    axes[0].set_title('Original voltage | 256-sample detrended STFT, dB rel. record peak', loc='left')
    visible = curves[curves.primary & (x(curves.time_s) > span[0]-6) & (x(curves.time_s) < span[1]+6)]
    for ax, names in zip(axes[1:3], (PRIMARY[:3], PRIMARY[3:]), strict=True):
        for name in names:
            curve(ax, visible, name, x, markers=True)
        legends(ax)
        ax.grid(alpha=.14)
    alternate = peaks[(peaks.S2_score > 0) & ~peaks.S2_selected & peaks.primary &
                      (x(peaks.time_s) > span[0]) & (x(peaks.time_s) < span[1])]
    axes[2].scatter(x(alternate.time_s), alternate.S2_frequency_hz/1e9, marker='D',
                    facecolors='none', edgecolors=COLORS['S2'], s=19, lw=.8)
    suspicious = peaks[peaks.high_without_S & peaks.primary]
    axes[2].scatter(x(suspicious.time_s), suspicious.S1_frequency_hz/1e9, marker='x',
                    c='#242424', s=22, lw=.9)
    base, s2 = (visible[visible.method == m] for m in ('B1', 'S2'))
    time = x(s2.time_s.to_numpy())
    b, s = base.S.to_numpy(), s2.S.to_numpy()
    swap = b & s & (abs(base.frequency_hz.to_numpy()-s2.frequency_hz.to_numpy()) > 100e6)
    axes[3].scatter(time[s], s2.voters.to_numpy()[s], s=18, c=COLORS['S2'], label='S2 supporting families')
    axes[3].scatter(time[s & ~b], np.zeros((s & ~b).sum()), s=22, marker='^', c='#21803c', label='Gain vs B1')
    axes[3].scatter(time[b & ~s], np.zeros((b & ~s).sum()), s=22, marker='v', c='#b94229', label='Loss vs B1')
    axes[3].scatter(time[swap], np.zeros(swap.sum()), s=23, marker='D', c='#7b53a0', label='Branch swap')
    axes[3].set(ylim=(-.5, 5.5), yticks=[0, 1, 3, 5], ylabel='Families',
                xlabel=f'Time from frozen {seg["stage"].replace("_", " ")} start (ns)')
    axes[3].legend(fontsize=7, loc='upper right', ncol=2)
    for ax in axes[:3]:
        configure(ax, span)
    for ax in axes:
        marks(ax, plan, x)
        ax.axvline(0, color='#293f56', lw=.85, ls=':')
        ax.axvline(end, color='#293f56', lw=.85, ls=':')
    fig.suptitle(f'{channel} | {seg["stage"].replace("_", " ").title()} | start = {ref*1e6:.8f} µs\n'
                 'Open circle: C · plus: native G · filled: S · diamond: alternate S · black ×: high vote without S',
                 fontsize=11)
    save(fig, path)


def trajectory_figure(channel: str, t: Any, plan: Any, f: pd.DataFrame, p: pd.DataFrame,
                      out: Path) -> None:
    def x(time: Any) -> Any:
        return (time-t[0])*1e6
    bounds = (0., float(x(t[-1])))
    xlabel = f'Time from first raw sample (µs); t₀ = {t[0]*1e6:.8f} µs'
    fig, axs = plt.subplots(3, 1, figsize=(12, 8.8), sharex=True, layout='constrained',
                            gridspec_kw={'height_ratios': [1, 1, .6]})
    for ax, names in zip(axs[:2], (PRIMARY[:3], PRIMARY[3:]), strict=True):
        for name in names:
            curve(ax, f, name, x)
            # Keep isolated observations visible even when a NaN breaks the line.
            m = f[f.method == name]
            finite = m.selected.to_numpy()
            solo = finite & ~np.r_[False, finite[:-1]] & ~np.r_[finite[1:], False]
            ax.scatter(x(m.time_s[solo]), m.frequency_hz[solo]/1e9, s=8,
                       c=COLORS[name], lw=0, zorder=4)
        configure(ax, bounds)
        legends(ax)
        ax.grid(alpha=.15)
    q = p[(p.S2_score > 0) & ~p.S2_selected]
    axs[1].scatter(x(q.time_s), q.S2_frequency_hz/1e9, marker='D',
                   facecolors='none', edgecolors=COLORS['S2'], s=12, lw=.6)
    for i, name in enumerate(PRIMARY):
        row = f[f.method == name]
        for mask, c in ((row.C & ~row.S, '#d7c8c5'), (row.S, COLORS[name])):
            axs[2].scatter(x(row.time_s[mask]), np.full(mask.sum(), i), marker='|', c=c, s=10, lw=.6)
    axs[2].set(xlabel=xlabel, xlim=bounds, yticks=np.arange(6), yticklabels=PRIMARY,
               ylim=(-.6, 5.6), title='Colored: S evidence · pale: C without S · blank: no C')
    for ax in axs:
        marks(ax, plan, x)
    fig.suptitle(f'{channel} | D · Full record, observed candidates only · diamonds: alternate S2')
    save(fig, out / f'{channel}__D_trajectories')


def channel_figures(item: dict[str, Any], plan: Any, data: Path, out: Path) -> None:
    channel = item['id']
    t, y, fs = load(item)
    f, p = (read(data / f'{channel}__{kind}.csv.gz') for kind in ('curves', 'peaks'))
    f = f[f.method.isin(PRIMARY)]
    def x(time: Any) -> Any:
        return (time-t[0])*1e6
    bounds = (0., float(x(t[-1])))
    xlabel = f'Time from first raw sample (µs); t₀ = {t[0]*1e6:.8f} µs'
    xx, ff, z = raw_map(t, y, fs, 1024, False, fs/2)

    fig, axs = plt.subplots(2, 1, figsize=(12, 7.5), sharex=True, layout='constrained')
    for ax, lim, label in zip(axs, ((0., fs/2e9), BAND), ('Full Nyquist span', 'Common evaluation band'), strict=True):
        img = image(ax, x(xx), ff, z, vmin=-65, vmax=0, cmap='viridis')
        configure(ax, bounds, lim)
        marks(ax, plan, x, labels=ax is axs[0])
        ax.set_title(label, loc='left', fontsize=10, pad=15 if ax is axs[0] else 5)
    axs[-1].set_xlabel(xlabel)
    fig.colorbar(img, ax=axs, label='Relative spectral power (dB)')
    fig.suptitle(f'{channel} | A · Raw STFT, Hann 1024, no detrending, full record')
    save(fig, out / f'{channel}__A_spectrum')

    fig, axs = plt.subplots(3, 1, figsize=(12, 9.2), sharex=True, layout='constrained')
    for ax, name in zip(axs, ('S0', 'S1', 'S2'), strict=True):
        h = heat(ax, f, p, name, x)
        configure(ax, bounds)
        marks(ax, plan, x)
        ax.set_title(dict(S0='S0 · estimator vote', S1='S1 · family vote',
                          S2='S2 · raw evidence constrained family vote')[name], loc='left', fontsize=10)
    axs[-1].set_xlabel(xlabel)
    fig.colorbar(h, ax=axs, label='Consensus score (displayed ±50 MHz)')
    fig.suptitle(f'{channel} | B · Candidate consensus at observed centers')
    save(fig, out / f'{channel}__B_consensus')

    fig, ax = plt.subplots(figsize=(12, 4.7), layout='constrained')
    h = image(ax, x(xx), ff, z, vmin=-65, vmax=0, cmap='viridis')
    s = p[p.S2_score > 0]
    for label, sub, c, size in [('S2 alternate', s[~s.S2_selected], '#ffc16c', 6),
                                ('S2 selected', s[s.S2_selected], '#f04e82', 5)]:
        ax.scatter(x(sub.time_s), sub.S2_frequency_hz/1e9, c=c, s=size, lw=0,
                   alpha=.85, label=label)
    q = p[p.high_without_S]
    ax.scatter(x(q.time_s), q.S1_frequency_hz/1e9, c='#fff4ed', s=12, marker='x', lw=.7,
               label=f'High S1 without S ({len(q)})')
    configure(ax, bounds)
    marks(ax, plan, x)
    legends(ax)
    fig.colorbar(h, ax=ax, label='Relative spectral power (dB)')
    ax.set(xlabel=xlabel, title=f'{channel} | C · Raw STFT with S2 branches and unsupported high S1')
    save(fig, out / f'{channel}__C_overlay')

    trajectory_figure(channel, t, plan, f, p, out)
    onset_figure(channel, t, y, fs, plan, f, p, out / f'{channel}__E_onset')
    for seg in plan:
        if seg['stage'] != 'onset':
            onset_figure(channel, t, y, fs, plan, f, p, out / f'{channel}__stage_{seg["id"]}', seg)
    print('plotted', channel, flush=True)


def summaries(data: Path, audit: Path, inputs: Path, out: Path) -> tuple[str, tuple[str, str]]:
    meta = json.loads((inputs / 'complete.json').read_text())
    names = [r['channel'] for r in meta['channels']]
    m = read(data / 'metrics.csv')
    m = m[m.stage == m.segment_or_stage]
    allm = m[m.stage == 'ALL']
    p = read(data / 'consensus_warnings.csv').query('stage == "ALL"').set_index('channel').loc[names]
    a = read(audit / 'candidate_union.csv')
    fig, axs = plt.subplots(2, 2, figsize=(14, 10), layout='constrained')
    x = np.arange(len(names))
    for j, method in enumerate(PRIMARY):
        mm = allm[allm.method == method].set_index('channel').loc[names]
        axs[0, 0].plot(x, 100*mm.S_coverage, color=COLORS[method], marker='.', lw=1, label=method)
        axs[1, 0].plot(x, mm.jump_250MHz_n, color=COLORS[method], marker='.', lw=1, label=method)
    axs[0, 0].set(ylabel='Supported centers (%)', title='Coverage on common full-record centers')
    axs[0, 0].legend(ncol=3, fontsize=8)
    axs[1, 0].set(ylabel='Adjacent jumps >250 MHz', title='Selected trajectories, no crossing missing frames')
    b = allm[allm.method == 'S2'].set_index('channel').loc[names]
    axs[0, 1].bar(x-.17, b.vs_B1_gain_n, .34, color='#27864c', label='New S centers')
    axs[0, 1].bar(x+.17, -b.vs_B1_loss_n, .34, color='#bd4830', label='Lost S centers')
    axs[0, 1].legend(fontsize=8)
    axs[0, 1].set(title='S2 compared with B1', ylabel='Paired center count')
    for j, (label, color) in enumerate((('high_without_S', '#9a2748'),
                                         ('high_in_noise_or_stationary', '#495686'),
                                         ('high_and_harmonic_like', '#a66d23'))):
        axs[1, 1].bar(x+(j-1)*.25, p[label], .25, color=color, label=label.replace('_', ' '))
    axs[1, 1].set(title='S1 consensus warnings (flags can overlap)', ylabel='Clusters')
    axs[1, 1].legend(fontsize=7)
    for ax in axs.flat:
        ax.set(xticks=x, xticklabels=names)
        ax.tick_params(axis='x', labelrotation=53, labelsize=8)
        ax.grid(axis='y', alpha=.15)
    save(fig, out / 'F1_all_channels')

    fig, axs = plt.subplots(2, 3, figsize=(15, 9.6), layout='constrained')
    for ax, method in zip(axs.flat, PRIMARY, strict=True):
        scores = m[m.method == method].pivot(index='channel', columns='stage', values='S_coverage')
        z = scores.reindex(index=names, columns=PHASES).to_numpy()*100
        h = ax.imshow(z, aspect='auto', cmap='YlGnBu', vmin=0, vmax=100)
        ax.set_facecolor('#eeeeee')
        ax.set(xticks=range(len(PHASES)), xticklabels=[s.replace('_', ' ') for s in PHASES],
               yticks=range(len(names)), yticklabels=names, title=method)
        ax.tick_params(axis='x', labelrotation=45, labelsize=8)
        ax.tick_params(axis='y', labelsize=8)
        for i, j in np.argwhere(np.isfinite(z)):
            ax.text(j, i, f'{z[i,j]:.0f}', ha='center', va='center', fontsize=6,
                    color='white' if z[i,j] > 60 else '#162338')
    fig.colorbar(h, ax=axs, label='Supported centers (%)')
    fig.suptitle('F2 · Frozen stages | gray cells: not applicable')
    save(fig, out / 'F2_stage_coverage')

    fig, axs = plt.subplots(1, 2, figsize=(13, 6), layout='constrained')
    s2 = m[m.method == 'S2'].pivot(index='channel', columns='stage', values='vs_B1_net_n')
    z = s2.reindex(index=names, columns=PHASES).to_numpy()
    bound = max(float(np.nanmax(abs(z))), 1.)
    h = axs[0].imshow(z, aspect='auto', cmap='PiYG', norm=TwoSlopeNorm(0., -bound, bound))
    axs[0].set_facecolor('#eeeeee')
    axs[0].set(xticks=range(len(PHASES)), xticklabels=[s.replace('_', ' ') for s in PHASES],
               yticks=x, yticklabels=names, title='S2 − B1 by frozen stage')
    axs[0].tick_params(axis='x', labelrotation=45, labelsize=8)
    axs[0].tick_params(axis='y', labelsize=8)
    for i, j in np.argwhere(np.isfinite(z)):
        axs[0].text(j, i, f'{z[i,j]:+.0f}', ha='center', va='center', fontsize=8)
    fig.colorbar(h, ax=axs[0], label='Net supported centers')
    timings = json.loads((data / 'complete.json').read_text())['timings']
    runtime = [sum(r['timing_s'].values())+timings[i]['main_vote_s'] for i, r in enumerate(meta['channels'])]
    for name in ('B0', 'B1', 'B2'):
        axs[1].plot(x, [r['timing_s'][name] for r in meta['channels']], '.-', color=COLORS[name], label=name)
    axs[1].plot(x, runtime, '.-', color=COLORS['S2'], label='All estimators + votes (excl. S evidence)')
    axs[1].set(xticks=x, xticklabels=names, ylabel='Seconds per channel (log scale)',
               yscale='log', title='Measured computation, one thread per estimator')
    axs[1].tick_params(axis='x', labelrotation=53, labelsize=8)
    axs[1].legend(fontsize=8)
    save(fig, out / 'F3_net_and_cost')

    fig, axs = plt.subplots(1, 2, figsize=(13, 5.6), layout='constrained')
    for label, mask, c in [('Shared by ≥2 families', a.family_n >= 2, '#315d82'),
                           ('Single family', a.family_n == 1, '#b5c5d4')]:
        counts = a[mask].groupby('channel').size().reindex(names, fill_value=0)
        axs[0].bar(x+(-.19 if c == '#315d82' else .19), counts, .38, label=label, color=c)
    nov = a[a.unmatched_B1B2]
    for label, mask, c in [('Supported', nov.S, '#309552'), ('Unsupported', ~nov.S, '#c47b65')]:
        counts = nov[mask].groupby('channel').size().reindex(names, fill_value=0)
        axs[1].bar(x+(-.19 if c == '#309552' else .19), counts, .38, label=label, color=c)
    axs[1].set_yscale('symlog', linthresh=1)
    for ax, label in zip(axs, ('Intersection and exclusive clusters', 'No match to B1 or B2 within 100 MHz'), strict=True):
        ax.set(xticks=x, xticklabels=names, ylabel='Candidate clusters', title=label)
        ax.tick_params(axis='x', labelrotation=53, labelsize=8)
        ax.legend(fontsize=8)
    save(fig, out / 'candidate_complementarity')
    strong = allm[(allm.method == 'B1') & ~allm.channel.isin(('20201210m_ch1', '20201214m_ch1', 'ch3_ch1'))]
    strong_id = strong.sort_values('S_coverage', ascending=False).channel.iloc[0]
    failures = read(data / 'metrics.csv')
    failures = failures[(failures.method == 'S2') & failures.segment_or_stage.str.fullmatch(r's\d+')]
    failure = failures.sort_values('vs_B1_frequency_loss_n', ascending=False).iloc[0]
    return str(strong_id), (str(failure.channel), str(failure.segment_or_stage))


def gallery(items: Any, plans: Any, out: Path, extra: list[str], filename: str) -> None:
    rel = out.relative_to(OUT).as_posix()
    def card(stem: str, title: str, channel: str = '', stage: str = '') -> str:
        url = f'{rel}/{stem}'
        return (f'<article data-channel="{escape(channel)}" data-stage="{escape(stage)}">'
                f'<h3>{escape(title)}</h3><a href="{url}.png"><img loading="lazy" '
                f'src="{url}.png" alt="{escape(title)}"></a><a href="{url}.svg">SVG</a></article>')
    full = [card(name, name.replace('_', ' ')) for name in
            ('F1_all_channels', 'F2_stage_coverage', 'F3_net_and_cost', 'candidate_complementarity', *extra)]
    titles = ('A · 原始频谱', 'B · 三种共识', 'C · 谱与融合叠加', 'D · 全记录曲线', 'E · 起跳')
    for item in items:
        ch = item['id']
        for j, (stem, title) in enumerate(zip(('A_spectrum', 'B_consensus', 'C_overlay', 'D_trajectories',
                                              'E_onset'), titles, strict=True)):
            full.append(card(f'{ch}__{stem}', ch+' | '+title, ch, 'onset' if j == 4 else 'all'))
        for seg in plans[ch]:
            if seg['stage'] != 'onset':
                full.append(card(f'{ch}__stage_{seg["id"]}', f'{ch} | {seg["id"]} {seg["stage"]}',
                                 ch, seg['stage']))
    def opts(values: Any) -> str:
        return ''.join(f'<option>{escape(s)}</option>' for s in values)
    with (OUT / filename).open('x', encoding='utf-8') as handle:
        handle.write('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>TASK-018 PDV 图册</title>
<style>body{font:16px system-ui;margin:2rem;color:#182739;background:#f4f7fb}
header{position:sticky;top:0;background:#f4f7fb;padding:1rem 0;z-index:2}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(400px,100%),1fr));gap:1rem}
article{border:1px solid #d9e1ea;border-radius:8px;padding:1rem;background:white}
img{width:100%;display:block} h3{margin:.1rem 0 .7rem} select{font:inherit;margin-right:1rem}
</style><header><h1>TASK-018 | PDV 异构估计器共识</h1>
<p>10 个原始文件、14 路通道。S 表示原电压诊断通过；颜色表示票数评分。点图可看 PNG 原图。</p>
<label>文件 / 通道 <select id="ch"><option value="">全部</option>'''+opts(r['id'] for r in items)
        +'''</select></label><label>阶段 <select id="stage"><option value="">全部</option>'''
        +opts(('all', *PHASES))+'''</select></label></header><main>'''+''.join(full)+'''</main>
<script>const ch=document.querySelector('#ch'),st=document.querySelector('#stage');
function pick(){document.querySelectorAll('article').forEach(a=>{a.hidden=
(ch.value&&a.dataset.channel!==ch.value)||(st.value&&a.dataset.stage!==st.value)})}
ch.onchange=st.onchange=pick;</script></html>''')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', default='v1')
    parser.add_argument('--stack', default='stack_v1')
    parser.add_argument('--audit', default='audit_v1')
    parser.add_argument('--input', default='inputs_v1')
    parser.add_argument('--gallery', default='gallery.html')
    parser.add_argument('--trajectories-only', action='store_true')
    args = parser.parse_args()
    plt.rcParams.update({'font.size': 9, 'svg.fonttype': 'none', 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.titleweight': 'semibold'})
    items, plans = inventory()
    base = OUT / 'data'
    out = (OUT / 'figures' / args.tag).resolve()
    assert out.parent == (OUT / 'figures').resolve()
    data, audit, inputs = ((base / n).resolve() for n in (args.stack, args.audit, args.input))
    assert data.parent == audit.parent == inputs.parent == base
    assert Path(args.gallery).name == args.gallery and args.gallery.endswith('.html')
    if args.trajectories_only:
        for item in items:
            ch = item['id']
            t, _, _ = load(item)
            f, p = (read(data / f'{ch}__{kind}.csv.gz') for kind in ('curves', 'peaks'))
            trajectory_figure(ch, t, plans[ch], f, p, out)
        extra = [p.stem for p in sorted(out.glob('G*.png'))]
        extra.append('F4_stage_jumps_and_warnings')
        gallery(items, plans, out, extra, args.gallery)
        return
    out.mkdir(parents=True, exist_ok=False)
    strong, failure = summaries(data, audit, inputs, out)
    for item in items:
        channel_figures(item, plans[item['id']], data, out)
    extra = []
    for ch in dict.fromkeys(('20201210m_ch1', '20201214m_ch1', 'ch3_ch1', strong)):
        t, y, fs = load(next(r for r in items if r['id'] == ch))
        stem = f'G_{ch}'
        f, p = (read(data / f'{ch}__{kind}.csv.gz') for kind in ('curves', 'peaks'))
        onset_figure(ch, t, y, fs, plans[ch], f, p, out / stem)
        extra.append(stem)
    ch, seg_id = failure
    t, y, fs = load(next(r for r in items if r['id'] == ch))
    segment = next(seg for seg in plans[ch] if seg['id'] == seg_id)
    f, p = (read(data / f'{ch}__{kind}.csv.gz') for kind in ('curves', 'peaks'))
    stem = f'G_branch_replacement_{ch}_{seg_id}'
    onset_figure(ch, t, y, fs, plans[ch], f, p, out / stem, segment)
    extra.append(stem)
    gallery(items, plans, out, extra, args.gallery)


if __name__ == '__main__':
    main()
