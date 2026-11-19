"""Matched raw-voltage STFT backgrounds, publication tracks and overview."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.collections import QuadMesh
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from dps_studio.core.segmentation.strategies import baseline, project_out
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.phase3_pairs import PAIR_SHOTS
from scripts.research.task023.waveform import Bool, detrend, offsets, samples_for_ns
from scripts.research.task024.ablations import FULL, NO_CFAR, NO_CHIRP, NO_CW, NO_PATH, VARIANTS
from scripts.research.task024.controls import B1, LONG_QUAD, QUAD
from scripts.research.task024.metrics import CHIRP_BINS, CHIRP_METHODS, PROFILE_STAGES
from scripts.research.task024.taxonomy import Row

STYLES = {
    B1: ("B1", "#4b5563"), QUAD: ("STFT 25.6 ns quad", "#125f9d"),
    LONG_QUAD: ("STFT 38.4 ns quad", "#7860ba"), FULL: ("M4 full", "#bc4633"),
    NO_CHIRP: ("M4 without chirp", "#40843a"), NO_CFAR: ("M4 without CFAR", "#977121"),
    NO_CW: ("M4 without CW/harmonic", "#197d76"), NO_PATH: ("M4 without path/gap", "#a04d8e"),
}
MARKERS = dict(zip(STYLES, ("o", "s", "^", "D", "v", "P", "X", "<"), strict=True))


@dataclass(frozen=True)
class Panel:
    left: Screening
    right: Screening
    bounds: tuple[float, float]
    title: str
    methods: tuple[str, ...]
    upper_ghz: float
    rails: bool = False


def _write(fig: Figure, path: Path) -> None:
    try:
        if not path.exists():
            with path.open("xb") as stream:
                fig.savefig(stream, format="png", dpi=200, facecolor="white")
    finally:
        plt.close(fig)


def _spectrum(ax: Axes, item: Screening, panel: Panel) -> QuadMesh:
    ch = item.channel
    width = samples_for_ns(12.8, ch.fs)
    q = np.arange(width//2, len(ch.y)-width//2+1, 32)
    time = ch.t[q]*1e6
    lo, hi = panel.bounds
    visible = (time >= lo-.004) & (time <= hi+.004)
    samples = ch.y[q[visible, None]+offsets(width)]
    taper = .5-.5*np.cos(2*np.pi*np.arange(width)/width)
    power = abs(np.fft.rfft(detrend(samples, degree=0)*taper, n=4096))**2
    f = np.fft.rfftfreq(4096, 1/ch.fs)/1e9
    band = (f >= .05) & (f <= panel.upper_ghz)
    energy = power[:, band]
    db = 10*np.log10(np.maximum(energy/max(float(energy.max()), 1e-30), 1e-8))
    return ax.pcolormesh(time[visible], f[band], db.T, shading="auto", cmap="cividis",
                         vmin=-55, vmax=0)


def _tracks(ax: Axes, item: Screening, panel: Panel, *, wide: bool = False) -> None:
    ch = item.channel
    time = ch.t[ch.q]*1e6
    lo, hi = panel.bounds
    visible = (time >= lo) & (time <= hi)
    if panel.rails:
        rail = np.asarray(item.results[FULL].diagnostics["rail_clipped"], dtype=np.bool_)
        clipped = time[visible & rail]
        ax.plot(clipped, np.full(len(clipped), .96), "|", ms=6, color="#919191",
                transform=ax.get_xaxis_transform(), label="Rail in 6.4 ns")
    for name in panel.methods:
        key = ("M4_8G" if name == FULL else f"{name}_8G") if wide else name
        accepted = item.results[key].accepted_hz[visible]/1e9
        label, color = STYLES[name]
        ax.plot(time[visible], accepted, color=color, marker=MARKERS[name], alpha=.9,
                ms=3.9, lw=.95, label=label, markerfacecolor="white", markeredgewidth=.7)
    ax.grid(axis="y", color="#dbe3eb", linewidth=.6)


def _axes(ax: Axes, panel: Panel) -> None:
    ax.set(xlim=panel.bounds, ylim=(0, panel.upper_ghz), ylabel="Frequency (GHz)",
           xlabel="Acquisition time (µs)")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.ticklabel_format(axis="x", style="plain", useOffset=False)


def _waveform(ax: Axes, item: Screening, row: Row) -> None:
    ch = item.channel
    q = int(str(row["sample_index"]))
    hz = float(str(row["B1_accepted_hz"]))
    ii = offsets(samples_for_ns(6.4, ch.fs))
    tau = ii/ch.fs
    voltage = ch.y[q+ii]
    null = baseline(tau, 1)
    phase = 2*np.pi*hz*tau
    design = np.column_stack((null, np.cos(phase), np.sin(phase)))
    model = design @ np.linalg.lstsq(design, voltage, rcond=1e-10)[0]
    ax.plot(tau*1e9, project_out(null, voltage)*1e3,
            color="#505362", lw=1.1, label="Detrended raw")
    ax.plot(tau*1e9, project_out(null, model)*1e3, color="#bc4633", lw=1.25,
            label=f"B1 tone {hz/1e9:.3f} GHz")
    r2 = float(str(row["B1_raw_chirp_r2_64ns"]))
    ax.set(title=f"6.4 ns local waveform   B1 raw $R^2$ = {r2:.3f}",
           xlabel="Time from center (ns)", ylabel="Detrended voltage (mV)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", color="#dbe3eb", linewidth=.6)


def _panel_figure(
    path: Path, title: str, panels: tuple[Panel, ...], *, pair: bool = False,
    wide: bool = False, detail: Row | None = None,
) -> None:
    fig, axes = plt.subplots(len(panels), 2, figsize=(13.1, 3.2*len(panels)+.7),
                             layout="constrained", squeeze=False)
    fig.set_layout_engine("constrained", rect=(.02, .013, .96, .955), h_pad=.075)
    fig.suptitle(title, x=.035, ha="left", fontsize=17, fontweight="bold")
    handles: dict[str, Artist] = {}
    for i, panel in enumerate(panels):
        left, right = axes[i]
        image = _spectrum(left, panel.left, panel)
        _axes(left, panel)
        left.set_title(panel.title, loc="left", fontsize=11, fontweight="bold")
        if pair:
            _tracks(left, panel.left, panel)
        if detail is not None and i == 2:
            t = float(str(detail["time_s"]))*1e6
            left.axvline(t, color="#fff3ce", lw=1., ls="--")
            _waveform(right, panel.left, detail)
            continue
        is_wide = wide and i == 1
        _tracks(right, panel.right, panel, wide=is_wide)
        if is_wide:
            _tracks(left, panel.left, panel)
            left.axhline(6., color="#fdf4c3", linestyle=":", lw=1.)
        right_title = ("8 GHz secondary band" if is_wide else panel.right.channel.id
                       if panel.left is not panel.right else "Published centers")
        _axes(right, panel)
        right.set_title(right_title, loc="left", fontsize=11, fontweight="bold")
        artists, labels = right.get_legend_handles_labels()
        handles.update((label, artist) for label, artist in zip(labels, artists, strict=True)
                       if isinstance(artist, Artist))
    fig.legend(list(handles.values()), list(handles), ncols=len(handles),
               loc="outside lower center", fontsize=8, frameon=False)
    fig.colorbar(image, ax=list(axes[:, 0]), shrink=.74, pad=.02,
                 label="12.8 ns Hann STFT (dB relative to panel peak)")
    _write(fig, path)


def _window(item: Screening, mask: Bool, pad_us: float) -> tuple[float, float]:
    ch = item.channel
    time = ch.t[ch.q][mask]*1e6
    return float(time.min()-pad_us), float(time.max()+pad_us)


def case_figures(
    path: Path, s: dict[str, Screening], wide: Screening, details: list[Row],
) -> None:
    def single(name: str, bounds: tuple[float, float], title: str,
               methods: tuple[str, ...], upper: float) -> Panel:
        return Panel(s[name], s[name], bounds, f"{name}   {title}", methods, upper)

    tail = (*CHIRP_METHODS[:-1], NO_CFAR, FULL)
    controls = (B1, QUAD, LONG_QUAD, FULL)
    high, low = s["20260630-1_ch1"], s["20260630-1_ch2"]
    late1, late2 = s["20260607_ch1"], s["20260607_ch2"]
    hz = high.results[FULL].accepted_hz
    quiet = high.channel.primary & (high.stages == "stationary")
    spur = quiet & (abs(hz-1.83e9) <= 50e6)
    low_spur = quiet & (abs(hz-100e6) <= 25e6)
    spur_bounds = _window(high, spur, .025)
    _panel_figure(path / "fig01_matched_stft_weak_tails.png", "Matched-duration STFT and weak tails", (
        single("20201211m_ch1", (108.320, 108.450), "Rapid decline and weak tail", tail, 1.8),
        single("20221017a_ch1", (88.195, 88.360), "Weak tail", tail, 4.5),
        single("ch3_ch1", (183.63, 183.90), "Weak tail and post-event noise", tail, 6.),
    ))
    _panel_figure(path / "fig02_onset_and_precursor_spurs.png", "Onset and precursor publications", (
        single("20201210m_ch1", (138.73, 138.80), "DC step and onset", controls, 6.),
        Panel(s["20201214m_ch1"], wide, (82.91, 83.015),
              "20201214m_ch1   6 GHz ceiling and early plateau", (B1, QUAD, FULL), 8.),
        single("20260630-1_ch1", _window(high, spur | low_spur, .035),
               "Stationary 1.83 GHz and 100 MHz lines", controls, 2.5),
    ), wide=True)
    competing, dual = (B1, QUAD, NO_CW, FULL), (B1, QUAD, NO_PATH, FULL)
    split = Panel(late1, late2, (555.66, 555.78), "20260607_ch1   Late dual-gain split", dual, 2.)
    _panel_figure(path / "fig03_competing_branches_and_clipping.png",
                  "Competing branches and dual-gain clipping", (
        Panel(low, low, (747.18, 747.26), "20260630-1_ch2   Competing branches", competing, 2.),
        Panel(high, low, (746.21, 746.84), "20260630-1_ch1   Clipped interval",
              competing, 2., rails=True),
        split,
    ), pair=True)
    strongest = max(details, key=lambda row: float(str(row["B1_raw_chirp_r2_64ns"])))
    t = float(str(strongest["time_s"]))*1e6
    noise = s["ch3_ch1"]
    mask = (noise.channel.primary & (noise.stages == "noise")
            & np.isfinite(noise.results[FULL].accepted_hz))
    _panel_figure(path / "fig04_m4_failures_and_overrejection.png",
                  "M4 failures and overrejection risks", (
        single("20260630-1_ch1", spur_bounds, "Stationary 1.83 GHz line", controls, 2.5),
        split,
        single(str(strongest["channel"]), (t-.035, t+.035),
               "Strongest rejected 6.4 ns raw fit", controls, 6.),
        single("ch3_ch1", _window(noise, mask, .030),
               "Residual noise-stage publications", controls, 3.5),
    ), pair=True, detail=strongest)


def overview_figure(
    path: Path, summary: list[Row], pairs: list[Row], chirp: list[Row], runtime: list[Row],
) -> None:
    fig = plt.figure(figsize=(16.4, 9.5), layout="constrained")
    layout = fig.add_gridspec(3, 2, height_ratios=(2.2, 1, 1), width_ratios=(1.18, 1))
    heat = fig.add_subplot(layout[0, 0])
    stages = ("decline", "weak_signal", "onset", "noise_excluding_M4_CW_overlap")
    pooled = {(str(r["visual_stage"]), str(r["method"])): r for r in summary}
    pair = {(str(r["shot"]), str(r["method"])): r for r in pairs
            if r["visual_stage"] == r["clipping"] == "all"}

    def change(data: dict[tuple[str, str], Row], group: str, name: str, col: str) -> float:
        return 100*(float(str(data[group, name][col]))-float(str(data[group, FULL][col])))

    delta = np.array([
        [change(pooled, stage, name, "accepted_fraction") for stage in stages]
        + [change(pair, shot, name, "agree_30mhz_frac") for shot in PAIR_SHOTS]
        for name in VARIANTS[1:]
    ])
    limit = max(float(np.nanmax(abs(delta))), 1.)
    heatmap = heat.imshow(delta, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    heat.set_xticks(range(delta.shape[1]), ("Decline", "Weak", "Onset", "Noise\nexcl. CW",
                                           *PAIR_SHOTS), rotation=24, ha="right")
    heat.set_yticks(range(delta.shape[0]), [name.removeprefix("M4_no_").replace("_", " ")
                                          for name in VARIANTS[1:]])
    for (i, j), value in np.ndenumerate(delta):
        heat.text(j, i, f"{value:+.1f}", ha="center", va="center", fontsize=8,
                  color="white" if abs(value) > .60*limit else "#273246")
    heat.set_title("Ablation minus M4 full   |   publication and ≤30 MHz pair agreement", loc="left")
    fig.colorbar(heatmap, ax=heat, shrink=.75, label="Percentage points")
    heat.axvline(3.5, color="#373b49", linewidth=1.)
    beta = {(r["observation_ns"], r["beta_bin_cycles"], r["method"]): r for r in chirp
            if r["visual_stage"] == "decline_and_weak_signal" and r["rate_cohort"] == "all"}
    for i, duration in enumerate((25.6, 38.4)):
        ax = fig.add_subplot(layout[i+1, 0])
        for name in CHIRP_METHODS:
            values = [float(str(beta[duration, label, name]["published_fraction"]))
                      for label in CHIRP_BINS[:-1]]
            label_text, color = STYLES[name]
            ax.plot(range(4), 100*np.asarray(values), "o-", color=color, lw=1.2, ms=4,
                    label=label_text)
        n = [beta[duration, label, FULL]["centers_n"] for label in CHIRP_BINS[:-1]]
        ax.set_xticks(range(4), [f"{label}\n(n={count})"
                                for label, count in zip(CHIRP_BINS[:-1], n, strict=True)])
        ax.set(ylim=(0, 103), ylabel="Published (%)",
               title=fr"$\beta_T = |df/dt|T^2$ (cycles), $T = {duration:g}$ ns")
        ax.grid(axis="y", color="#dbe3eb", linewidth=.6)
        if i == 1:
            ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(.5, -.23),
                      fontsize=7.5, frameon=False)
    time = fig.add_subplot(layout[:, 1])
    channel = [str(r["channel"]) for r in runtime]
    left = np.zeros(len(channel))
    palette = plt.get_cmap("tab20")(np.linspace(0., 1., len(PROFILE_STAGES)))
    for i, stage in enumerate(PROFILE_STAGES):
        duration_s = np.asarray([float(str(r[f"{stage}_s"])) for r in runtime])
        label = stage.lstrip("_").replace("_", " ")
        time.barh(channel, duration_s, left=left, color=palette[i], label=label, height=.68)
        left += duration_s
    time.invert_yaxis()
    time.set(xlabel="Standalone cold M4 time (s)", title="Cold runtime by stage")
    time.legend(ncols=3, fontsize=7.3, loc="upper left", bbox_to_anchor=(0, -.065))
    fig.suptitle("M4 ablations, chirp smearing and wall time", x=.03, ha="left",
                 fontsize=17, fontweight="bold")
    _write(fig, path)
