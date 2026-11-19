"""Overview and hard-region cards for the TASK-023 channel audits."""
from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator, ScalarFormatter
from scipy.ndimage import median_filter  # type: ignore[import-untyped]

from scripts.research.task023.common import Channel, Estimate
from scripts.research.task023.pursuit import rail_mask
from scripts.research.task023.regime import Regime, Segmentation
from scripts.research.task023.waveform import (
    FLOOR, Bool, Float, detrend, offsets, same_side_weights, samples_for_ns,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ZOOMS = {
    "20201210m_ch1": (("onset", 138.73, 138.80), ("decline", 139.20, 139.50)),
    "20201211m_ch1": (("onset", 107.72, 107.78), ("weak", 108.25, 108.47)),
    "20221017a_ch1": (("precursor_onset", 87.55, 87.76), ("weak", 88.14, 88.36)),
    "20260630-1_ch2": (("onset", 746.20, 746.30), ("competing", 746.85, 747.45)),
    "ch3_ch1": (("active", 183.63, 183.90),),
}
METHODS = ("B1", "M1", "M2", "M3")
PHASE2_METHODS = ("B1", "M1", "M3", "M4")
TRACK_COLORS = {"B1": "#f4f6f9", "M1": "#55d7ff", "M2": "#ffcc54", "M3": "#ff75be",
                "M4": "#ffcc54"}
EVIDENCE_COLORS = {"B1": "#323c4c", "M1": "#006d91", "M2": "#9e5800", "M3": "#a02c68",
                   "M4": "#8a5300"}
MARKERS = {"B1": "o", "M1": "s", "M2": "^", "M3": "D", "M4": "v"}
PHASE2_ZOOMS = {
    "20201210m_ch1": (("onset", 138.73, 138.80),),
    "20201211m_ch1": (("weak", 108.350, 108.417),),
    "20221017a_ch1": (("weak", 88.225, 88.334),),
    "20260630-1_ch2": (("onset", 746.205, 746.260), ("competing", 747.180, 747.265)),
    "ch3_ch1": ZOOMS["ch3_ch1"],
}
HELDOUT_ZOOMS = {
    "20201214m_ch1": (("onset", 82.935, 83.005), ("decline_weak", 83.420, 83.620)),
    "20231019-ch1_ch1": (("onset", 89.405, 89.455), ("weak", 89.960, 90.140)),
    "20260607_ch1": (("onset", 554.655, 554.715), ("weak_unknown", 555.310, 555.680)),
    "20260607_ch2": (("onset", 554.655, 554.715), ("weak_unknown", 555.310, 555.680)),
    "20260630-1_ch1": (("onset", 746.205, 746.260), ("competing", 747.180, 747.265)),
    "20260630-2_ch1": (("onset", 540.205, 540.265), ("weak_competing", 540.760, 541.320)),
    "20260630-2_ch2": (("onset", 540.205, 540.265), ("weak_competing", 540.760, 541.320)),
    "20260701_ch1": (("onset", 656.835, 656.890), ("weak", 657.710, 657.890)),
    "20260701_ch2": (("onset", 656.835, 656.890), ("weak", 657.710, 657.890)),
}
REGIME_COLORS = ("#dce3eb", "#9b83b0", "#d85740", "#347ba2",
                 "#2c927a", "#e8b756", "#725aba", "#c65889")
REGIME_SHORT = ("Quiet", "Clutter", "Step", "Steady", "Chirp", "Weak tail",
                "Persistent CW", "Multi-branch")


def _spectrogram(ch: Channel, duration: float) -> tuple[Float, Float, Float]:
    width = samples_for_ns(duration, ch.fs)
    nfft = max(2048, width)
    q = np.arange(0, len(ch.y), 128, dtype=np.int64)
    f = np.fft.rfftfreq(nfft, 1/ch.fs)
    bins = f <= ch.fmax
    bed = np.interp(f[bins], ch.quiet.frequency_hz, ch.quiet.floor_v2)
    taper = np.hanning(width)
    p_db = np.empty((int(bins.sum()), len(q)))
    for start in range(0, len(q), 128):
        idx = q[start:start+128]
        sample = idx[:, None]+offsets(width)
        keep = (sample >= 0) & (sample < len(ch.y))
        weight = keep*same_side_weights(idx, width, ch.quiet.steps, len(ch.y))
        y = ch.y[np.clip(sample, 0, len(ch.y)-1)]
        residual = detrend(y, weight, degree=2 if duration >= 25.6 else 1)
        window = weight*taper
        spectrum = np.fft.rfft(residual*window, n=nfft, axis=-1)[:, bins]
        power = abs(spectrum)**2 / np.maximum(np.sum(window**2, axis=-1, keepdims=True), FLOOR)
        p_db[:, start:start+len(idx)] = (10*np.log10(np.maximum(power/bed, FLOOR))).T
    return ch.t[q]*1e6, f[bins]/1e9, p_db


def _voltage(ax: Axes, ch: Channel, lo: float, hi: float, rail: Bool) -> None:
    start, stop = np.searchsorted(ch.t, (lo*1e-6, hi*1e-6))
    size = samples_for_ns(6.4, ch.fs) + 1
    left, right = max(0, start-size//2), min(len(ch.y), stop+size//2)
    v = ch.y[left:right]
    steps = ch.quiet.steps.index
    cuts = np.r_[left, steps[(steps > left) & (steps < right)], right]
    baseline = np.concatenate([median_filter(ch.y[a:b], size=size, mode="nearest")
                               for a, b in zip(cuts[:-1], cuts[1:], strict=True)])
    x = ch.t[left:right]*1e6
    ax.plot(x, v, lw=.65, color="#234869", alpha=.84, label="Raw voltage")
    ax.plot(x, baseline, lw=1.2, color="#ba581c", label="6.4 ns median baseline")
    in_view = (ch.t[steps]*1e6 >= lo) & (ch.t[steps]*1e6 <= hi)
    for i, step in enumerate(steps[in_view]):
        ax.axvline(ch.t[step]*1e6, color="#754886", linestyle="--", lw=1.1,
                   label="Detected step" if i == 0 else "")
    rail_in_view = rail[left:right] & (x >= lo) & (x <= hi)
    if rail_in_view.any():
        ax.scatter(x[rail_in_view], v[rail_in_view], s=5., color="#b22442", label="Rail samples",
                   zorder=4, linewidths=0.)
        for level in np.unique(v[rail_in_view]):
            ax.axhline(level, color="#b22442", linestyle=":", lw=.6, alpha=.7)
    ymin, ymax = float(ch.y[start:stop].min()), float(ch.y[start:stop].max())
    margin = max(.06*(ymax-ymin), 1e-5)
    ax.set(ylim=(ymin-margin, ymax+margin), ylabel="Voltage (V)")
    ax.legend(loc="upper right", ncols=2, fontsize=8, framealpha=.92)


def _tracks(
    ax: Axes, time: Float, results: dict[str, Estimate], zoom: bool, view: Bool,
    methods: tuple[str, ...], secondary_methods: tuple[str, ...],
) -> None:
    for method in methods:
        ax.plot(time, results[method].accepted_hz/1e9, color=TRACK_COLORS[method],
                marker=MARKERS[method], ms=3.0 if zoom else 1.8, lw=.8, alpha=.92, label=method)
    for method in secondary_methods:
        secondary = results[method].diagnostics["secondary_hz"]
        if np.isfinite(secondary[view]).any():
            ax.plot(time, secondary/1e9, linestyle="--",
                    color="#91ef7b" if method == "M2" else "#c5a8ff",
                    marker="x" if method == "M2" else "+", ms=4.3 if zoom else 2.5,
                    lw=.8, label=f"{method} secondary")


def _quality(
    r2: Axes, rho: Axes, time: Float, results: dict[str, Estimate], zoom: bool,
    methods: tuple[str, ...],
) -> None:
    for method in methods:
        result = results[method]
        accepted = np.isfinite(result.accepted_hz)
        color = EVIDENCE_COLORS[method]
        for ax, key, style in (
            (r2, "raw_chirp_r2_64ns", "-"), (r2, "raw_chirp_r2_256ns", "--"),
            (rho, "split_half_coherence_256ns", "-"),
        ):
            value: Float = getattr(result.raw, key)
            rejected = ~accepted & np.isfinite(value)
            ax.plot(time[rejected], value[rejected], linestyle="none", marker=".",
                    ms=2.3, color=color, alpha=.17)
            ax.plot(time, np.where(accepted, value, np.nan), color=color, linestyle=style,
                    lw=.79, marker=MARKERS[method] if zoom else ".", ms=2.6)
    r2.set(ylabel="Raw chirp fit\n$R^2$", ylim=(-.04, 1.04), yticks=[0., .25, .50, .75, 1.])
    rho.set(ylabel="Split-half\ncoherence", ylim=(-1.06, 1.06), yticks=[-1., -.5, 0., .5, 1.])
    rho.axhline(.55, color="#667282", linestyle=":", lw=.9)
    r2.legend(handles=(
        Line2D([0], [0], color="#323c4c", lw=1., label="6.4 ns"),
        Line2D([0], [0], color="#323c4c", linestyle="--", lw=1., label="25.6 ns"),
        Line2D([0], [0], color="#323c4c", alpha=.4, marker=".", linestyle="none",
               label="Rejected proposal"),
    ), loc="upper right", ncols=3, fontsize=8, framealpha=.92)


def _regime_strip(ax: Axes, time: Float, regimes: Segmentation, view: Bool) -> None:
    half = float(np.median(np.diff(time)))/2
    ax.imshow(regimes.index[None, :], aspect="auto", interpolation="nearest",
              extent=(time[0]-half, time[-1]+half, 0., 1.),
              cmap=ListedColormap(REGIME_COLORS), vmin=-.5, vmax=len(Regime)-.5)
    ax.set(yticks=[], ylabel="Regime")
    handles = [Patch(facecolor=REGIME_COLORS[i], label=REGIME_SHORT[i])
               for i in np.unique(regimes.index[view])]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0., 1.04),
              borderaxespad=0., ncols=8, fontsize=8, frameon=False,
              handlelength=1., columnspacing=.9)


def _save_card(
    ch: Channel, results: dict[str, Estimate], figures: Path, name: str, lo: float, hi: float,
    spectrum: tuple[Float, Float, Float], rail: Bool, regimes: Segmentation | None = None,
) -> None:
    zoom = name != "overview"
    title = ("Full record" if not zoom else name.removeprefix("zoom_").replace("_", " ").capitalize())
    scale = 12.8 if zoom else 25.6
    spectrogram_time, f, p = spectrum
    dt = float(spectrogram_time[1]-spectrogram_time[0])
    df = float(f[1]-f[0])
    time = ch.t[ch.q]*1e6
    in_view = (time >= lo) & (time <= hi)
    methods = METHODS if regimes is None else PHASE2_METHODS
    secondary = ("M2",) if regimes is None else ("M2", "M4")
    selected = np.concatenate([results[m].accepted_hz[in_view] for m in methods]
                              + [results[m].diagnostics["secondary_hz"][in_view] for m in secondary])
    selected = selected[np.isfinite(selected)]/1e9
    maximum_ghz = (min(6., max(1.5, np.ceil(2*(float(selected.max())+.20))/2))
                   if zoom and len(selected) else 6.)
    ratios = [1.05, 1.70, .93, .78] if zoom else [2.2, 1., .75]
    height = 8.6 if zoom else 7.1
    if regimes is not None:
        ratios.append(.18)
        height += .65
    fig, axes = plt.subplots(len(ratios), 1, sharex=True, figsize=(12.5, height),
                             height_ratios=ratios,
                             layout="constrained")
    if zoom:
        voltage, spec, r2, rho = axes[:4]
        _voltage(voltage, ch, lo, hi, rail)
    else:
        spec, r2, rho = axes[:3]
    spec_idx = np.flatnonzero((spectrogram_time >= lo-dt) & (spectrogram_time <= hi+dt))
    fc = np.flatnonzero(f <= maximum_ghz+df)
    scene = p[np.ix_(fc, spec_idx)]
    top = float(np.clip(np.percentile(scene, 98.5), 16., 42.))
    image = spec.imshow(
        scene, aspect="auto", origin="lower", interpolation="nearest", cmap="magma",
        extent=(spectrogram_time[spec_idx[0]]-dt/2, spectrogram_time[spec_idx[-1]]+dt/2,
                -df/2, f[fc[-1]]+df/2), vmin=-3., vmax=top,
    )
    _tracks(spec, time, results, zoom, in_view, methods, secondary)
    _quality(r2, rho, time, results, zoom, methods)
    if regimes is not None:
        _regime_strip(axes[-1], time, regimes, in_view)
        if zoom and ch.id == "20201211m_ch1" and name == "zoom_weak":
            r2.set(ylim=(-.01, .21), yticks=[0., .04, .10, .15, .20])
            r2.axhline(.04, color="#8a5300", linestyle=":", lw=.8)
    for axis in axes:
        axis.set_xlim(lo, hi)
        axis.spines[["top", "right"]].set_visible(False)
        if axis is not spec:
            axis.grid(axis="y", lw=.5, color="#dce2e8")
    spec.set(ylabel="Beat frequency (GHz)", ylim=(0., maximum_ghz))
    spec.legend(loc="upper right", ncols=5, fontsize=8, facecolor="#191826",
                framealpha=.90, edgecolor="none", labelcolor="white")
    bar = fig.colorbar(image, ax=list(axes), shrink=.65, pad=.018)
    bar.set_label("Spectral power / quiet floor (dB)")
    for segment in ch.segments:
        boundary = segment["start_s"]*1e6
        if lo < boundary < hi:
            spec.axvline(boundary, color="white", linestyle=":", lw=.6, alpha=.5)
            for ax in (r2, rho):
                ax.axvline(boundary, color="#8793a4", linestyle=":", lw=.6, alpha=.6)
    axes[-1].set_xlabel("Acquisition time (µs)")
    rho.xaxis.set_major_locator(MaxNLocator(nbins=8))
    rho.xaxis.set_major_formatter(ScalarFormatter(useOffset=False))
    fig.suptitle(f"{ch.id}  |  {title}  ·  {scale:g} ns spectrogram", fontsize=15, weight="bold")
    fig.savefig(figures / f"{ch.id}__{name}.png", dpi=160)
    fig.savefig(figures / f"{ch.id}__{name}.svg", dpi=160)
    plt.close(fig)


def save_channel_figures(
    ch: Channel, results: dict[str, Estimate], figures: Path, regimes: Segmentation | None = None,
) -> None:
    rail = rail_mask(ch.y)
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "svg.fonttype": "none",
                                "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9}):
        _save_card(ch, results, figures, "overview", float(ch.t[0]*1e6), float(ch.t[-1]*1e6),
                   _spectrogram(ch, 25.6), rail, regimes)
        spectrum = _spectrogram(ch, 12.8)
        windows = ZOOMS if regimes is None else PHASE2_ZOOMS | HELDOUT_ZOOMS
        for name, lo, hi in windows[ch.id]:
            _save_card(ch, results, figures, f"zoom_{name}", lo, hi, spectrum, rail, regimes)
