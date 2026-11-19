"""Phase 3 pair overlays and the separate wide-band diagnostic."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from scripts.research.task023.common import Channel
from scripts.research.task023.phase1_plots import _spectrogram
from scripts.research.task023.phase3_pairs import PairComparison
from scripts.research.task023.waveform import FMAX, Float

PLATEAU_US = (82.974, 83.340)


def _save(fig: Figure, path: Path) -> None:
    try:
        for extension in (".png", ".svg"):
            fig.savefig(path.with_suffix(extension), dpi=160)
    finally:
        plt.close(fig)


def save_pair_figure(pair: PairComparison, figures: Path) -> None:
    time = pair.time_s * 1e6
    colors = {"B1": "#205e8a", "M4": "#ae411e"}
    fig, (tracks, residual) = plt.subplots(
        2, sharex=True, figsize=(12.5, 6.1), height_ratios=(1.65, 1), layout="constrained",
    )
    for method, color in colors.items():
        for channel, by_method, style in (
            ("ch1", pair.accepted_ch1, "-"), ("ch2", pair.accepted_ch2, "--"),
        ):
            hz = by_method[method]
            tracks.plot(time, hz/1e9, color=color, ls=style, lw=1.,
                        marker="." if channel == "ch2" else None, ms=2,
                        label=f"{method} {channel}")
        delta = np.abs(pair.accepted_ch1[method] - pair.accepted_ch2[method])/1e6
        residual.plot(time, delta, color=color, lw=.8, marker=".", ms=2, label=method)
    for own, color, name, y in (
        (pair.clipped_ch1, "#7a498b", "ch1 rail window", .970),
        (pair.clipped_ch2, "#287866", "ch2 rail window", .910),
    ):
        if own.any():
            tracks.plot(time[own], np.full(int(own.sum()), y), transform=tracks.get_xaxis_transform(),
                        color=color, marker="|", ms=4, ls="none", label=name)
    for threshold in (30., 100., 250.):
        residual.axhline(threshold, color="#8091a0", lw=.75, ls=":", alpha=.8)
    tracks.set(ylabel="Published frequency (GHz)", ylim=(0., 6.55))
    tracks.legend(loc="upper left", ncols=3, fontsize=9)
    residual.set(ylabel=r"$|f_{\mathrm{ch1}} - f_{\mathrm{ch2}}|$ (MHz)",
                 xlabel="Acquisition time (µs)", ylim=(0., None))
    residual.set_yscale("symlog", linthresh=100)
    residual.legend(loc="upper right")
    residual.xaxis.set_major_locator(MaxNLocator(nbins=10))
    residual.ticklabel_format(axis="x", useOffset=False)
    residual.set_xlim(time[0], time[-1])
    for axis in (tracks, residual):
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="x", color="#e3e8ed", lw=.6)
    fig.suptitle(f"{pair.shot}  |  Dual-gain agreement on identical physical centers",
                 fontsize=15, weight="bold")
    _save(fig, figures / f"pair_{pair.shot}")


def save_oob_figure(ch: Channel, accepted: dict[str, Float], figures: Path) -> None:
    time = ch.t[ch.q] * 1e6
    spectrogram_time, f, power = _spectrogram(ch, 12.8)
    dt = float(spectrogram_time[1] - spectrogram_time[0])
    df = float(f[1] - f[0])
    lo, hi = 82.935, 83.620
    view = (spectrogram_time >= lo-dt) & (spectrogram_time <= hi+dt)
    visible_times = spectrogram_time[view]
    scene = power[:, view]
    fig, (spec, tracks) = plt.subplots(
        2, sharex=True, figsize=(12.5, 7), height_ratios=(1.30, 1), layout="constrained",
    )
    image = spec.imshow(
        scene, origin="lower", aspect="auto", interpolation="nearest", cmap="magma",
        extent=(visible_times[0]-dt/2, visible_times[-1]+dt/2, -df/2, f[-1]+df/2),
        vmin=-3., vmax=float(np.clip(np.percentile(scene, 98.5), 16., 42.)),
    )
    for name, color, marker in (("B1_8G", "#65d6ff", "o"), ("M4_8G", "#fff184", "x")):
        spec.plot(time, accepted[name]/1e9, color=color, lw=.8, marker=marker, ms=2.5,
                  label=name)
    for name, color, style in (
        ("B1_6G", "#205e8a", "--"), ("M4_6G", "#ae411e", "--"),
        ("B1_8G", "#205e8a", "-"), ("M4_8G", "#ae411e", "-"),
    ):
        tracks.plot(time, accepted[name]/1e9, lw=1., color=color, ls=style, label=name)
    tracks.axvspan(*PLATEAU_US, color="#dfbb62", alpha=.19, label="Frozen visual plateau")
    for axis, color in ((spec, "#f3eef4"), (tracks, "#737d87")):
        axis.axhline(FMAX/1e9, color=color, lw=1., ls=":", label="Primary 6 GHz limit")
        axis.set(ylabel="Beat frequency (GHz)", ylim=(0., ch.fmax/1e9), xlim=(lo, hi))
        axis.spines[["top", "right"]].set_visible(False)
    spec.legend(loc="upper right", ncols=3, fontsize=9, facecolor="#272230", labelcolor="white")
    tracks.legend(loc="upper right", ncols=3, fontsize=9)
    tracks.set_xlabel("Acquisition time (µs)")
    tracks.ticklabel_format(axis="x", useOffset=False)
    fig.colorbar(image, ax=[spec, tracks], shrink=.65, pad=.02, label="Power / quiet floor (dB)")
    fig.suptitle(f"{ch.id}  |  Separate 8 GHz diagnostic", fontsize=15, weight="bold")
    _save(fig, figures / f"{ch.id}__oob_8ghz")
