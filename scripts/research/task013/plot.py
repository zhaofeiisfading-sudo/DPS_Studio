"""Consistent Times New Roman, closed axes, inward ticks, 600-dpi research figures."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .cases import VELOCITY
from .experiment import write_json

COLORS = {"stft512": "#777777", "stft768": "#0072B2", "dechirp": "#E69F00",
          "varpro": "#CC79A7", "clutter_varpro": "#A64B2A", "clip_stft512": "#D55E00",
          "clip_stft2048": "#D55E00", "profile512": "#8B6B3F", "profile2048": "#009E73",
          "bounded_chirp512": "#009E73", "current_map": "#0072B2", "stage_map": "#009E73"}
LABELS = {"stft512": "STFT 512", "stft768": "STFT 768", "dechirp": "Dechirp",
          "varpro": "VarPro", "clutter_varpro": "Clutter VP", "clip_stft512": "Clipped STFT 512",
          "clip_stft2048": "Clipped STFT 2048", "profile512": "Profile 512",
          "profile2048": "Profile 2048", "bounded_chirp512": "Bounded chirp 512",
          "current_map": "Current stage map", "stage_map": "Proposed stage map"}


def configure() -> str:
    font = font_manager.findfont("Times New Roman", fallback_to_default=False)
    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 11,
        "axes.labelsize": 11, "axes.titlesize": 12, "axes.linewidth": .9,
        "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
        "xtick.major.size": 4, "ytick.major.size": 4, "legend.fontsize": 9,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "svg.fonttype": "none", "mathtext.fontset": "stix", "axes.unicode_minus": True})
    return font


def save(fig: Any, folder: Path, name: str) -> None:
    fig.savefig(folder / f"{name}.png", dpi=600, bbox_inches="tight", pad_inches=.12)
    fig.savefig(folder / f"{name}.svg", bbox_inches="tight", pad_inches=.12)
    plt.close(fig)


def matrix(summary: Path, folder: Path) -> None:
    frame = pd.read_csv(summary / "stage.csv")
    frame = frame[(frame.split == "independent") & (frame.kind == "supported")]
    regions = ["onset", "acceleration", "plateau", "decline", "rebound", "low_frequency",
               "weak_signal", "stationary"]
    names = ["stft768", "dechirp", "varpro", "clutter_varpro", "clip_stft512", "clip_stft2048",
             "profile2048", "bounded_chirp512", "stage_map"]
    display = ["Onset", "Acceleration", "Plateau", "Decline", "Rebound", "Low-frequency tone",
               "Weak / dropout", "Static, unobservable"]
    fig, axes = plt.subplots(1, 2, figsize=(14.2, 6.4), layout="constrained")
    for ax, key, title, cmap in zip(axes, ["failure_percent", "coverage_percent"],
            ["a  Failure including missing estimates (%)", "b  Finite estimate coverage (%)"],
            ["magma_r", "viridis"], strict=True):
        table = frame.pivot(index="region", columns="method", values=key).reindex(index=regions, columns=names)
        values = table.to_numpy(dtype=float)
        im = ax.imshow(values, cmap=cmap, vmin=0, vmax=100, aspect="auto")
        for i in range(len(regions)):
            for j in range(len(names)):
                value = values[i, j]
                text = f"{value:.1f}" if np.isfinite(value) else "NA"
                light = value > 55 if key == "failure_percent" else value < 50
                ax.text(j, i, text, ha="center", va="center", fontsize=9,
                        color="white" if light else "#151515")
        ax.set(xticks=np.arange(len(names)), xticklabels=[LABELS[n] for n in names],
               yticks=np.arange(len(regions)), yticklabels=display, title=title)
        plt.setp(ax.get_xticklabels(), rotation=52, ha="right", rotation_mode="anchor")
        fig.colorbar(im, ax=ax, shrink=.7, pad=.025)
    fig.supxlabel("Independent synthetic waveforms; manual annotations with ±2 ns boundary jitter", fontsize=11)
    save(fig, folder, "01_stage_algorithm_matrix")


def trace_panel(ax: Any, error_ax: Any, z: Any, names: list[str], title: str,
                limits: tuple[float, float]) -> None:
    centers = z["centers"]
    time = z["time_s"][centers] * 1e9
    truth = z["truth_hz"][centers] * VELOCITY
    ax.plot(time, truth, color="#202020", linewidth=1.8, label="Synthetic truth", zorder=5)
    for i, name in enumerate(names):
        value = z[name + "__accepted_hz"] * VELOCITY
        style = ("--", ":", "-")[i % 3]
        ax.plot(time, value, style, color=COLORS[name], linewidth=1.3, label=LABELS[name],
                marker="o" if i == 2 else None, markersize=2.2, markevery=3)
        error_ax.plot(time, value - truth, style, color=COLORS[name], linewidth=1.1)
    ax.set(title=title, xlim=limits, ylabel="Apparent velocity (m s$^{-1}$)")
    error_ax.axhline(0, color="#666666", linewidth=.7)
    error_ax.set(xlim=limits, xlabel="Time (ns)", ylabel="Error (m s$^{-1}$)")
    ax.tick_params(labelbottom=False)
    ax.legend(loc="best", frameon=False, handlelength=2.5)


def curves(run: Path, folder: Path) -> None:
    fig = plt.figure(figsize=(12.8, 8.5), layout="constrained")
    outer = fig.add_gridspec(2, 2, hspace=.10, wspace=.08)
    configs = [
        ("low_plateau_00", ["stft768", "clip_stft2048", "profile2048"],
         "a  Low-frequency tone: 15 m s$^{-1}$", (45., 275.)),
        ("fast_accel_00", ["stft768", "clip_stft512", "bounded_chirp512"],
         "b  Fast acceleration", (50., 115.)),
        ("fast_decel_00", ["stft768", "clip_stft512", "bounded_chirp512"],
         "c  Fast deceleration", (115., 180.)),
        ("stable_plateau_00", ["stft768", "clip_stft2048", "profile2048"],
         "d  Stable plateau, 0 dB nominal SNR", (70., 250.)),
    ]
    for panel, (case, names, title, limits) in enumerate(configs):
        sub = outer[panel // 2, panel % 2].subgridspec(2, 1, height_ratios=[3, 1], hspace=.04)
        ax, error_ax = fig.add_subplot(sub[0]), fig.add_subplot(sub[1])
        with np.load(run / "cases" / f"independent_{case}.npz") as z:
            trace_panel(ax, error_ax, z, names, title, limits)
    save(fig, folder, "02_representative_velocity_curves")


def failures(run: Path, folder: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 7.4), layout="constrained")
    cases = [("drifting_spur_00", "a  Drifting clutter defeats prefix prediction"),
             ("crossing_00", "b  Two components: target identity is unresolved"),
             ("dropout_00", "c  Extinction remains in the failure denominator"),
             ("static_unobservable_00", "d  Static prior cannot create a beat measurement")]
    for ax, (case, title) in zip(axes.flat, cases, strict=True):
        with np.load(run / "cases" / f"independent_{case}.npz") as z:
            idx = z["centers"]
            t = z["time_s"][idx] * 1e9
            truth = z["truth_hz"][idx] * VELOCITY
            ax.plot(t, truth, color="#252525", linewidth=1.8, label="Latent synthetic truth")
            other = z["other_hz"][idx] * VELOCITY
            if np.isfinite(other).any():
                ax.plot(t, other, "--", color="#888888", linewidth=1.2, label="Interfering component")
            for name, style in (("stft768", ":"), ("stage_map", "-")):
                ax.plot(t, z[name + "__accepted_hz"] * VELOCITY, style,
                        color=COLORS[name], linewidth=1.4, label=LABELS[name],
                        marker="o" if name == "stage_map" else None, markersize=2.)
            if case.startswith("dropout"):
                ax.axvspan(135, 175, color="#D55E00", alpha=.10, label="Zero target amplitude")
            if case.startswith("static"):
                ax.set_ylim(-30, 30)
                ax.text(.5, .67, "All accepted estimates are NaN\nZero is a generator value / experimental prior",
                        transform=ax.transAxes, ha="center", va="center", fontsize=11)
            ax.set(title=title, xlim=(25, 295), xlabel="Time (ns)", ylabel="Apparent velocity (m s$^{-1}$)")
            ax.legend(loc="best", frameon=False, fontsize=9)
    save(fig, folder, "03_failure_cases")


def recommendation(folder: Path) -> None:
    fig, ax = plt.subplots(figsize=(13.2, 8.1))
    ax.set(xlim=(0, 13.2), ylim=(0, 8.1))
    ax.axis("off")
    ax.text(.25, 7.85, "Conditional stage-to-algorithm recommendations", fontsize=18, weight="bold")
    ax.text(.25, 7.45, "Manual stage + observation quality + boundary uncertainty; research recommendations only",
            fontsize=12, color="#555555")
    columns = [(.25, 3.0, "Manual annotation"), (3.65, 4.0, "Estimator / simple control"),
               (8.05, 4.8, "Condition that limits the recommendation")]
    for x, _, title in columns:
        ax.text(x, 6.95, title, fontsize=12, weight="bold")
    rows = [
        ("Static prior / no observable beat", "NaN + explicit reason", "Never convert the lowest frequency into measured zero", "#6D6D6D"),
        ("Visible low-frequency / plateau", "Long STFT; profile fit for refinement", "Enough cycles; account for baseline and front-end transfer", "#009E73"),
        ("Onset / abrupt change / turnaround", "Short, one-sided or clipped STFT", "Report the boundary uncertainty and lost support", "#D55E00"),
        ("Smooth acceleration / decline\n/ rebound", "Dechirp; bounded chirp as refinement", "Compare zero-slope control; wrong stage can constrain the fit", "#0072B2"),
        ("Weak signal with persistent clutter", "Clutter VarPro, conditionally", "Quiet prefix must exclude the target; test clutter persistence", "#A64B2A"),
        ("Weak signal without stable clutter", "Long STFT if locally stationary", "Extinction is missing data; never fill the gap as a measurement", "#CC79A7"),
        ("Noise / unresolved target identity", "NaN or retain multiple candidates", "A small waveform residual does not establish target identity", "#6D6D6D"),
        ("Unknown dynamics", "STFT baseline + diagnostics", "Keep manual choice and candidate provenance", "#0072B2"),
    ]
    for i, (stage, algorithm, condition, color) in enumerate(rows):
        y = 6.25 - i * .68
        for x, width, text in ((.25, 3., stage), (3.65, 4., algorithm), (8.05, 4.8, condition)):
            box = FancyBboxPatch((x, y - .26), width, .52, boxstyle="round,pad=0.05,rounding_size=0.06",
                                 linewidth=.85, edgecolor=color, facecolor=color + "0E")
            ax.add_patch(box)
            if x == 8.05:
                # Hand-wrap long scientific conditions, preserving clear reading order.
                words, lines, line = text.split(), [], ""
                for word in words:
                    if len(line) + len(word) > 59:
                        lines.append(line)
                        line = word
                    else:
                        line += (" " if line else "") + word
                lines.append(line)
                text = "\n".join(lines)
            ax.text(x + .10, y, text, va="center", ha="left", fontsize=10.3, linespacing=1.2)
        ax.add_patch(FancyArrowPatch((3.30, y), (3.58, y), arrowstyle="-|>",
                                    mutation_scale=11, linewidth=1.0, color=color))
        ax.add_patch(FancyArrowPatch((7.72, y), (7.98, y), arrowstyle="-|>",
                                    mutation_scale=11, linewidth=1.0, color=color))
    ax.text(.25, .25, "Quality flags, rejected points, support duration and candidate identity remain visible for every method.",
            fontsize=11, color="#444444")
    save(fig, folder, "04_stage_algorithm_recommendations")


def comparison(summary: Path, folder: Path) -> None:
    pairs = pd.read_csv(summary / "paired.csv")
    pairs = pairs[pairs.split == "independent"]
    choices = [("current_map", "stage_map", "all", "Stage map vs current map"),
               ("clip_stft512", "bounded_chirp512", "acceleration", "Bounded chirp vs short STFT: acceleration"),
               ("dechirp", "bounded_chirp512", "acceleration", "Bounded chirp vs Dechirp: acceleration"),
               ("clip_stft512", "bounded_chirp512", "decline", "Bounded chirp vs short STFT: decline"),
               ("clip_stft2048", "profile2048", "low_frequency", "Long profile vs long STFT: low frequency"),
               ("stft768", "profile2048", "low_frequency", "Long profile vs STFT 768: low frequency")]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.3), gridspec_kw={"width_ratios": [1.65, 1.]},
                             layout="constrained")
    ax = axes[0]
    for i, (base, method, region, label) in enumerate(choices):
        row = pairs[(pairs.baseline == base) & (pairs.method == method) & (pairs.region == region)].iloc[0]
        delta, lo, hi = row.failure_difference_pp, row.ci_low_pp, row.ci_high_pp
        ax.errorbar(delta, i, xerr=[[delta - lo], [hi - delta]], fmt="o", capsize=3,
                    color="#009E73" if hi < 0 else "#777777", markersize=5)
        ax.text(2.0, i, f"n={int(row.n_waveforms)}", va="center", fontsize=9)
    ax.axvline(0, color="#555555", linewidth=.9)
    ax.set(yticks=np.arange(len(choices)), yticklabels=[item[3] for item in choices],
           title="a  Paired failure-rate differences", xlabel="Candidate minus control (percentage points)")
    ax.invert_yaxis()
    cost = pd.read_csv(summary / "cost.csv")
    names = ["stft768", "clip_stft512", "clip_stft2048", "dechirp", "varpro", "clutter_varpro",
             "profile2048", "bounded_chirp512", "current_map", "stage_map"]
    ax = axes[1]
    for i, name in enumerate(names):
        row = cost[cost.method == name].iloc[0]
        ax.errorbar(row.median_ms, i, xerr=[[row.median_ms - row.p10_ms],
                    [row.p90_ms - row.median_ms]], fmt="o", color=COLORS[name], capsize=2, markersize=4)
    ax.set(yticks=np.arange(len(names)), yticklabels=[LABELS[n] for n in names], xscale="log",
           xlabel="Runtime per 12,800-sample record (ms)", title="b  Serial cost, initialization included")
    ax.invert_yaxis()
    fig.supxlabel("a: waveform bootstrap 95% intervals (exploratory).  b: median and 10–90% range, 8 records × 3 runs.",
                  fontsize=10)
    save(fig, folder, "05_paired_performance_and_cost")


def observability(run: Path, folder: Path) -> None:
    metrics = pd.read_csv(run / "metrics.csv")
    part = metrics[(metrics.split == "independent") & (metrics.kind == "supported")
                   & (metrics.region == "all")]
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.8), layout="constrained")
    low = part[part.family == "low_plateau"].copy()
    low["velocity"] = low.case.str.extract(r"_(\d+)$")[0].astype(int).map(
        lambda i: (15., 30., 60., 120.)[i % 4])
    ax = axes[0]
    for name, style in (("stft768", "o--"), ("clip_stft2048", "s:"), ("profile2048", "D-")):
        values = low[low.method == name].groupby("velocity").coverage.agg(["mean", "std"])
        ax.errorbar(values.index, values["mean"] * 100, yerr=values["std"] * 100,
                    fmt=style, color=COLORS[name], capsize=3, label=LABELS[name], markersize=4)
    ax.set(xlabel="True synthetic plateau velocity (m s$^{-1}$)", ylabel="Finite estimate coverage (%)",
           ylim=(-5, 105), xticks=[15, 30, 60, 120], title="a  Low frequency: window support matters")
    ax.legend(frameon=False, loc="lower right")
    names = ["stft512", "stft768", "dechirp", "clip_stft512", "current_map", "stage_map"]
    ax = axes[1]
    for i, name in enumerate(names):
        values = part[(part.method == name) & (part.onset_eligible == 1)]
        finite = values.onset_error_ns.dropna().to_numpy(dtype=float)
        jitter = np.random.default_rng(13).uniform(-.18, .18, len(finite))
        ax.scatter(np.full(len(finite), i) + jitter, finite, s=8, alpha=.4, color=COLORS[name], linewidths=0)
        if len(finite):
            ax.plot([i - .24, i + .24], [np.median(finite)] * 2, color="#222222", linewidth=1.6)
        ax.text(i, .98, f"miss {int(values.onset_missed.sum())}/{len(values)}", rotation=90,
                ha="center", va="top", transform=ax.get_xaxis_transform(), fontsize=8.5)
    ax.axhline(0, color="#555555", linewidth=.8)
    ax.set(xticks=np.arange(len(names)), xticklabels=[LABELS[n] for n in names],
           ylabel="First sustained 100 m s$^{-1}$ crossing error (ns)",
           title="b  Onset error and missed crossings")
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
    fig.supxlabel("a: mean ± SD across 6 waveforms per velocity.  b: each point is one waveform; missing crossings are counted.",
                  fontsize=10)
    save(fig, folder, "06_low_frequency_and_onset")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    font = configure()
    matrix(args.summary, args.output)
    curves(args.run, args.output)
    failures(args.run, args.output)
    recommendation(args.output)
    comparison(args.summary, args.output)
    observability(args.run, args.output)
    write_json(args.output / "style.json", {"font": font, "png_dpi": 600,
        "closed_axes": True, "ticks_inward": True, "svg_text_editable": True,
        "figures": 6, "formats": ["png", "svg"]})


if __name__ == "__main__":
    main()
