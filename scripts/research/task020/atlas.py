"""Plot identical raw-spectrum backgrounds and inspectable candidate overlays."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from html import escape
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FormatStrFormatter, MaxNLocator  # noqa: E402
import numpy as np  # noqa: E402
from scipy.signal import stft  # type: ignore[import-untyped] # noqa: E402

from scripts.research.task017.prepare import load  # noqa: E402
from scripts.research.task018.inputs import FMAX, FMIN, inventory  # noqa: E402
from scripts.research.task020.replay import OUT, channel_data, readout  # noqa: E402

BAND = (FMIN/1e9, FMAX/1e9)
HOP = 128
LABEL = {'A': 'A  Balanced STFT', 'B': 'B  Demeaned 512 STFT', 'C': 'C  S2 stack'}
DARK = {'A': '#126d94', 'B': '#a85c03', 'C': '#9a2d82'}
LIGHT = {'A': '#60dcff', 'B': '#ffd076', 'C': '#fdb5fa'}
STAGES = dict(onset='起跳', plateau='平台', decline='下降', rebound='回升',
              weak_signal='弱信号', acceleration='加速', noise='噪声',
              stationary='静止/背景', unknown='未定')
FOCUS = ('20201210m_ch1', '20260630-1_ch2', 'ch3_ch1')
RAW_COLORS = LinearSegmentedColormap.from_list(
    'voltage_spectrum', ['#0d141e', '#303b47', '#68727f', '#a9afb8'])
RAW_NORM = Normalize(-60, 0)
SIZE = 16


def save(fig: Any, dest: Path) -> None:
    for ext in ('png', 'svg'):
        with dest.with_suffix('.'+ext).open('xb') as stream:
            fig.savefig(stream, format=ext, dpi=170, facecolor='white')
    plt.close(fig)


def spectrum(t: Any, voltage: Any, fs: float) -> tuple[Any, Any, Any]:
    width = 512
    f, _, values = stft(voltage, fs, window='hann', nperseg=width, noverlap=width-HOP,
                        nfft=4096, detrend=False, boundary=None, padded=False)
    q = np.arange(width//2, len(t)-width//2+1, HOP)
    assert len(q) == values.shape[1] and np.all(q % HOP == 0)
    # Include the bracketing display bins. The reference peak uses the stated band only.
    select = (f >= FMIN-(f[1]-f[0])) & (f <= FMAX+(f[1]-f[0]))
    in_band = (f >= FMIN) & (f <= FMAX)
    power = abs(values[select])**2
    peak = float(np.max(abs(values[in_band])**2))
    return (t[q]-t[0])*1e9, f[select]/1e9, 10*np.log10(np.maximum(power/peak, 1e-30))


def background(ax: Any, raw: tuple[Any, Any, Any], xlim: tuple[float, float]) -> Any:
    x, y, z = raw
    lo = max(0, np.searchsorted(x, xlim[0])-1)
    hi = min(len(x), np.searchsorted(x, xlim[1], side='right')+1)
    ax.set_facecolor('#e0e4e9')
    return ax.pcolormesh(x[lo:hi], y, z[:, lo:hi], shading='nearest', cmap=RAW_COLORS,
                         norm=RAW_NORM, rasterized=True, zorder=0)


def configure(ax: Any, xlim: tuple[float, float], bounds: list[float], *, left: bool) -> None:
    ax.set(xlim=xlim, ylim=BAND, xlabel='Time from record start (ns)',
           ylabel='Beat frequency (GHz)' if left else '',
           yticks=[.05, 1, 2, 3, 4, 5, 6])
    ax.tick_params(axis='y', labelleft=left)
    ax.yaxis.set_major_formatter(FormatStrFormatter('%g'))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    for x in bounds:
        if xlim[0] < x < xlim[1]:
            ax.axvline(x, color='#8e9aa9', ls=(0, (3, 4)), lw=.8, zorder=1)


def dots(ax: Any, x: Any, hz: Any, color: str, *, mode: str = 'filled') -> None:
    if len(x) == 0:
        return
    if mode == 'ring':
        ax.scatter(x, hz/1e9, s=SIZE, facecolors='none', edgecolors=color, linewidths=.72,
                   alpha=.72, zorder=3, clip_on=False)
    elif mode == 'cross':
        ax.scatter(x, hz/1e9, s=SIZE, c=color, marker='x', linewidths=.9, zorder=4,
                   clip_on=False)
    else:
        ax.scatter(x, hz/1e9, s=SIZE, c=color, linewidths=.3, edgecolors='#14202e',
                   zorder=5, marker='D' if mode == 'diamond' else 'o', clip_on=False)


def trace(ax: Any, d: Any, name: str, color: str, *, overlay: bool = False) -> None:
    f = d[name+'_output_hz']
    style = (0, (4, 2.6)) if name == 'C' and overlay else '-'
    ax.plot(d.x, f/1e9, color=color, lw=1.2, ls=style, zorder=3, label=LABEL[name])
    kept = f.notna()
    if not overlay:
        supported = kept & d[name+'_S']
        dots(ax, d.x[supported], f[supported], color)
        dots(ax, d.x[kept & ~supported], f[kept & ~supported], color, mode='diamond')
        if name == 'C':
            rejected = d.S1_selected & (~kept | (d.S1_source_row != d.C_source_row))
            dots(ax, d.x[rejected], d.S1_frequency_hz[rejected], color, mode='ring')
        else:
            rejected = d[name+'_C'] & ~kept
            dots(ax, d.x[rejected], d.loc[rejected, name+'_frequency_hz'], color, mode='ring')
    else:
        # Reveal isolated accepted samples even when a line has no segment to draw.
        isolated = kept & ~kept.shift(fill_value=False) & ~kept.shift(-1, fill_value=False)
        dots(ax, d.x[isolated], f[isolated], color)
        warned = kept & ~d[name+'_S']
        dots(ax, d.x[warned], f[warned], color, mode='diamond')


def keys(entries: list[tuple[str, str, str]]) -> list[Any]:
    return [Line2D([], [], marker=marker, ls='none', ms=5.2, markeredgecolor=color,
                   markerfacecolor=color if 'hollow' not in label else 'none', label=label)
            for marker, color, label in entries]


def note(fig: Any, legend: list[Any]) -> None:
    fig.legend(handles=legend, loc='outside lower center', ncol=len(legend),
               frameon=False, columnspacing=1.5)


def overlays(title: str, d: Any, raw: Any, xlim: tuple[float, float], bounds: list[float],
             dest: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.9), layout='constrained')
    fig.suptitle(title+'  /  Tracks on the same voltage spectrum', x=.035, ha='left')
    for j, (ax, name) in enumerate(zip(axes, LABEL, strict=True)):
        img = background(ax, raw, xlim)
        trace(ax, d, name, LIGHT[name])
        configure(ax, xlim, bounds, left=j == 0)
        ax.set_title(LABEL[name]+('  /  S2 output' if name == 'C' else '  /  native G output'),
                     loc='left')
    fig.colorbar(img, ax=axes, label='Raw STFT power (dB re record peak)', pad=.018,
                 ticks=[-60, -40, -20, 0])
    note(fig, keys([('o', DARK['A'], 'Released, S passed'), ('D', DARK['B'], 'Released, S failed'),
                    ('o', DARK['C'], 'Unreleased prefilter choice (hollow)')]))
    save(fig, dest)


def trajectories(title: str, d: Any, xlim: tuple[float, float], bounds: list[float],
                 dest: Path) -> None:
    fig = plt.figure(figsize=(15, 6.1), layout='constrained')
    grid = fig.add_gridspec(2, 3, height_ratios=[1, 1])
    ax = fig.add_subplot(grid[0, :])
    fig.suptitle(title+'  /  Released frequency tracks', x=.035, ha='left')
    for name in LABEL:
        trace(ax, d, name, DARK[name], overlay=True)
    configure(ax, xlim, bounds, left=True)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=12))
    ax.set(xlabel='', title='Overlay  /  A and B native G · C uses S')
    ax.legend(loc='lower left', bbox_to_anchor=(0, 1.01), ncol=3, frameon=False, borderpad=0)
    ax.grid(axis='y', alpha=.25)
    for j, name in enumerate(LABEL):
        sub = fig.add_subplot(grid[1, j], sharey=ax)
        trace(sub, d, name, DARK[name])
        configure(sub, xlim, bounds, left=j == 0)
        sub.set_title(LABEL[name], loc='left')
        sub.grid(axis='y', alpha=.25)
    note(fig, keys([('o', DARK['A'], 'Released, S passed'),
                    ('D', DARK['B'], 'Released, S failed (suspect)'),
                    ('o', DARK['C'], 'Unreleased prefilter choice (hollow)')]))
    save(fig, dest)


def filtering(title: str, d: Any, p: Any, raw: Any, xlim: tuple[float, float],
              bounds: list[float], dest: Path) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(17, 4.0), layout='constrained')
    fig.suptitle(title+'  /  Same raw-waveform evidence (S)', x=.035, ha='left')
    for j, (ax, name) in enumerate(zip(axes, ('A', 'B', 'BS', 'C'), strict=True)):
        img = background(ax, raw, xlim)
        color, warn = '#91f2e1', '#ffc470'
        if name == 'C':
            fail = ~p.S1_S
            other = (p.S2_voters > 0) & ~p.S2_selected
            dots(ax, p.x[fail], p.S1_frequency_hz[fail], warn, mode='ring')
            dots(ax, p.x[other], p.S2_frequency_hz[other], '#fbc2fd', mode='cross')
            dots(ax, d.x[d.C_S], d.C_output_hz[d.C_S], color)
            ax.set_title('C  S2 final and cluster audit', loc='left')
        else:
            baseline = 'B' if name == 'BS' else name
            valid = d[baseline+'_C']
            good = valid & d[baseline+'_S']
            bad = valid & ~good
            dots(ax, d.x[bad], d.loc[bad, baseline+'_frequency_hz'], warn,
                 mode='ring' if name == 'BS' else 'diamond')
            dots(ax, d.x[good], d.loc[good, baseline+'_frequency_hz'], color)
            ax.set_title('B + S  Demeaned 512 + evidence' if name == 'BS'
                         else LABEL[name]+' raw', loc='left')
        configure(ax, xlim, bounds, left=j == 0)
    fig.colorbar(img, ax=axes, label='Raw STFT power (dB re record peak)', pad=.015,
                 ticks=[-60, -40, -20, 0])
    note(fig, keys([('o', '#087d6b', 'S passed / final in B + S and C'),
                    ('D', '#ae6107', 'Raw candidate, S failed'),
                    ('o', '#ae6107', 'Rejected by S (hollow)'),
                    ('x', '#9a2d82', 'S passed, competing C cluster')]))
    save(fig, dest)


def consensus(title: str, d: Any, p: Any, raw: Any, xlim: tuple[float, float],
              bounds: list[float], dest: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(13, 7.6), layout='constrained', sharex=True)
    fig.suptitle(title+'  /  Raw power and consensus scores', x=.035, ha='left')
    img = background(axes[0], raw, xlim)
    axes[0].set_title('Original-voltage STFT power', loc='left')
    fig.colorbar(img, ax=axes[0], label='dB re record peak', pad=.02, ticks=[-60, -40, -20, 0])
    f = np.linspace(*BAND, 299)
    loc = {q: i for i, q in enumerate(d.sample_index)}
    for ax, name in zip(axes[1:], ('S1', 'S2'), strict=True):
        z = np.zeros((len(f), len(loc)))
        for peak in p.itertuples():
            hz = getattr(peak, name+'_frequency_hz')/1e9
            if np.isfinite(hz):
                j = loc[peak.sample_index]
                patch = getattr(peak, name+'_score')*np.maximum(0, 1-abs(f-hz)/.05)
                z[:, j] = np.maximum(z[:, j], patch)
        heat = ax.pcolormesh(d.x, f, z, shading='nearest', cmap='magma', vmin=0, vmax=1,
                             rasterized=True)
        fig.colorbar(heat, ax=ax, label='Vote score (unitless)', pad=.02, ticks=[0, .5, 1])
        ax.set_title(('S1 family votes before S' if name == 'S1'
                      else 'S2 family votes after S')+'  /  zero where no scored cluster', loc='left')
    for ax in axes:
        configure(ax, xlim, bounds, left=True)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=11))
    for ax in axes[:-1]:
        ax.set_xlabel('')
    save(fig, dest)


def figures(item: dict[str, Any], plan: list[dict[str, Any]], out: Path) -> list[dict[str, str]]:
    channel = item['id']
    t, y, fs = load(item)
    raw = spectrum(t, y, fs)
    candidates, curves, p = channel_data(channel)
    d = readout(candidates, curves, p)
    for table in (d, p):
        np.testing.assert_array_equal(table.time_s, t[table.sample_index])
        table['x'] = (table.time_s-t[0])*1e9
    folder = out / 'figures' / channel
    folder.mkdir()
    length = (t[-1]-t[0])*1e9
    frozen = [(seg['start_s']-t[0])*1e9 for seg in plan]
    views = [('full', 'full record', '全记录', (0., length))]
    for seg in plan:
        left, right = ((seg[key]-t[0])*1e9 for key in ('start_s', 'end_s'))
        margin = max(8., min(40., .10*(right-left)))
        views.append((seg['id'], seg['stage'].replace('_', ' '), STAGES[seg['stage']],
                      (max(0., left-margin), min(length, right+margin))))
    index = []
    for key, stage, zh, limits in views:
        window = stage if key == 'full' else f'{key} {stage}'
        title = f'{channel}  /  {window}  /  t₀ = {t[0]*1e6:.8f} µs'
        local = d[d.x.between(*limits)]
        peaks = p[p.x.between(*limits)]
        overlays(title, local, raw, limits, frozen, folder / f'{key}_1')
        trajectories(title, local, limits, frozen, folder / f'{key}_2')
        filtering(title, local, peaks, raw, limits, frozen, folder / f'{key}_3')
        index.append(dict(channel=channel, key=key, title=zh, stage=stage))
    if channel in FOCUS or channel == '20260630-1_ch1':
        consensus(channel, d, p, raw, (0., length), frozen, folder / 'consensus')
    print('Rendered', channel, len(index), 'views', flush=True)
    return index


def gallery(out: Path, index: list[dict[str, str]]) -> None:
    def card(path: str, caption: str) -> str:
        return (f'<figure><figcaption>{caption} · <a href="{path}.svg">SVG</a></figcaption>'
                f'<a href="{path}.png"><img loading="lazy" src="{path}.png" '
                f'alt="{escape(caption)}"></a></figure>')

    channels = list(dict.fromkeys(view['channel'] for view in index))
    nav = ' '.join(f'<a href="#{ch}">{ch}</a>' for ch in (*FOCUS, *[c for c in channels
                                                                      if c not in FOCUS]))
    sections = []
    for ch in (*FOCUS, *[c for c in channels if c not in FOCUS]):
        folder = f'figures/{ch}'
        blocks = []
        for view in (v for v in index if v['channel'] == ch):
            key = view['key']
            content = ''.join(card(f'{folder}/{key}_{j}', title) for j, title in enumerate(
                ('图 1 · 同一原始谱上的三条轨迹', '图 2 · 三条发布曲线及各自候选',
                 '图 3 · 同一 S 筛选前后'), 1))
            if key == 'full' and (out / folder / 'consensus.svg').is_file():
                content += card(f'{folder}/consensus', '原始谱、筛选前 S1、筛选后 S2')
            opened = ' open' if key == 'full' and ch == FOCUS[0] else ''
            blocks.append(f'<details id="{ch}-{key}"{opened}><summary>{key} · {view["title"]}'
                          f'</summary>{content}</details>')
        links = ' · '.join(f'<a href="data/{dir_name}/{ch}.{ext}">{label}</a>'
                           for dir_name, ext, label in (
                               ('centers', 'csv', '逐中心 CSV'), ('candidates', 'csv.gz', '候选 CSV.GZ'),
                               ('peaks', 'csv.gz', '共识簇 CSV.GZ')))
        sections.append(f'<section id="{ch}"><h2>{ch}</h2><p>{links}</p>{"".join(blocks)}</section>')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TASK-020 | 真实 PDV 三方法对照</title>
<style>
:root{color-scheme:light} body{margin:0;background:#eef2f6;color:#172432;
font:16px/1.55 system-ui,sans-serif} main,header{max-width:1420px;margin:auto;padding:0 24px}
h1{line-height:1.2} nav{display:flex;flex-wrap:wrap;gap:8px 15px} a{color:#085780}
section{margin:22px 0;padding:8px 20px 18px;background:white;border:1px solid #d6dfe8}
summary{cursor:pointer;font-weight:600;padding:7px 2px;border-top:1px solid #e5ebf1}
figure{margin:10px 0 22px} img{width:100%;height:auto;display:block}
figcaption{color:#35475a;margin-bottom:6px}
</style><header><h1>真实 PDV 三方法对照</h1>
<p>10 文件、14 通道。所有对照面板共用原始电压的 STFT 功率谱、频带、时间中心与色标。
图 1–2 中，A/B 线为原生门控 G 的输出，C 线为 S2。菱形是证据不足的发布点。
图 3 中，A/B 的原始候选包含未过 S 的实心菱形，B + S 和 C 用空心标记留存被 S 拒绝的候选或簇。
S 通过只说明局部原电压支持，仍需核对物理支路。共识图颜色表示票分。</p>
<p>虚线沿用 TASK-017 冻结分段。横轴相对于各记录原始起点，标题给出起点绝对时间。
点击 PNG 可打开原尺寸。<a href="data/paired_changes.csv">S2 新增和换支明细</a> ·
<a href="data/stage_diagnostics.csv">分段诊断</a> · <a href="data/timing.csv">耗时</a></p>
<nav>'''+nav+'''</nav></header><main>'''+''.join(sections)+'''</main>
<script>function reveal(){const e=document.getElementById(location.hash.slice(1));
if(e?.tagName==='DETAILS')e.open=true;else if(e?.tagName==='SECTION')e.querySelector('details').open=true}
addEventListener('hashchange',reveal);reveal();</script></html>'''
    with (out / 'gallery.html').open('x', encoding='utf-8') as handle:
        handle.write(html)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(OUT.resolve()):
        parser.error('Use TASK-020 or a fresh subdirectory inside it.')
    items, plans = inventory()
    (out / 'figures').mkdir(parents=True, exist_ok=False)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=style) as pool:
        pages = pool.map(figures, items, [plans[item['id']] for item in items], [out]*len(items))
        index = [view for page in pages for view in page]
    gallery(out, index)


def style() -> None:
    plt.rcParams.update({'font.size': 9, 'svg.fonttype': 'none', 'axes.titleweight': 'bold',
                         'figure.titlesize': 13, 'figure.titleweight': 'bold'})


if __name__ == '__main__':
    main()
