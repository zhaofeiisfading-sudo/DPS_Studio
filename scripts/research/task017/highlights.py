"""Readable onset case cards and descriptive counts; no inferred physical speed."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task017.compare import frozen_plans
from scripts.research.task017.prepare import OUT, load, records, spectrum

FOCUS = {"M1_balanced": ("Balanced STFT", "#222222"),
         "demean512_control": ("Mean-removed STFT 512", "#d66a1c"),
         "stft_short": ("Stage-clipped STFT 512", "#9b4b91"),
         "visual_onset_varpro": ("VarPro + frozen visual onset", "#0076b6")}


def card(item: dict[str, Any], output: str, analysis: str) -> dict[str, str]:
    dest = Path(output)
    t, y, fs = load(item)
    onset = next(seg for seg in frozen_plans()[item["id"]] if seg["stage"] == "onset")
    a, b = onset["start_s"]-20e-9, onset["end_s"]+30e-9
    fig, axs = plt.subplots(4, 1, figsize=(13, 10), sharex=True,
                            gridspec_kw={"height_ratios": [1, 2.2, 2.2, .9]})
    mask = (t >= a) & (t <= b)
    axs[0].plot(t[mask]*1e6, y[mask], color="#3c637b", linewidth=.65)
    axs[0].set_ylabel("Voltage (V)*")
    f, times, p = spectrum(t, y, fs, 512, hop=64)
    fi, ti = f <= 8e9, (times >= a-20e-9) & (times <= b+20e-9)
    db = 10*np.log10(np.maximum(p[fi][:, ti], 1e-30)/max(float(p.max()), 1e-30))
    axs[1].pcolormesh(times[ti]*1e6, f[fi]/1e9, db, cmap="viridis", vmin=-60, vmax=0,
                      shading="auto", rasterized=True)
    axs[1].set_ylabel("Raw STFT / GHz")
    counts = []
    for i, (name, (label, color)) in enumerate(FOCUS.items()):
        v = dict(np.load(Path(analysis) / item["id"] / f"{name}.npz"))
        xx, yy = v["time_s"]*1e6, v["frequency_hz"]/1e9
        selected = (xx >= a*1e6) & (xx <= b*1e6)
        gate = np.isfinite(v["gated_frequency_hz"])
        for ax in axs[1:3]:
            ax.plot(xx[selected], yy[selected], color=color, linewidth=.6, alpha=.55)
            ax.scatter(xx[selected & gate], yy[selected & gate], c=color, s=22,
                       label=label if ax is axs[2] else None, zorder=5)
            rejected = selected & ~gate & np.isfinite(yy)
            ax.scatter(xx[rejected], yy[rejected], c=color, s=25, marker="x", linewidth=.9, zorder=4)
        supported = selected & v["spectrally_supported"]
        axs[2].scatter(xx[supported], yy[supported], facecolors="none", edgecolors=color,
                        marker="D", s=62, linewidth=.7)
        missing = selected & ~np.isfinite(yy)
        axs[3].scatter(xx[missing], np.full(int(missing.sum()), i), c="#b5b5b5", marker="|", s=24)
        axs[3].scatter(xx[selected & gate], np.full(int((selected & gate).sum()), i),
                        c=color, marker="o", s=10)
        rejected = selected & ~gate & np.isfinite(yy)
        axs[3].scatter(xx[rejected], np.full(int(rejected.sum()), i), c=color, marker="x", s=20)
        actual = v["stage"] == "onset"
        counts.append(f"{label}: C/G/S={int((actual & np.isfinite(yy)).sum())}/"
                      f"{int((actual & gate).sum())}/{int((actual & v['spectrally_supported']).sum())}")
    axs[2].set_ylabel("Candidate frequency / GHz")
    axs[2].legend(loc="upper left", ncol=2, fontsize=8)
    for ax in axs[1:3]:
        ax.set_ylim(0, 8)
    for ax in axs:
        ax.axvspan(onset["start_s"]*1e6, onset["end_s"]*1e6, color="#ac5327", alpha=.09)
        ax.axvline(onset["start_s"]*1e6, color="#ac5327", linewidth=.8)
        ax.axvline(onset["end_s"]*1e6, color="#ac5327", linewidth=.8)
        ax.set_xlim(a*1e6, b*1e6)
        ax.ticklabel_format(axis="x", style="plain", useOffset=False)
        ax.grid(alpha=.12)
    axs[3].set_yticks(range(len(FOCUS)), [v[0] for v in FOCUS.values()], fontsize=8)
    axs[3].set_ylabel("Status only")
    axs[3].set_xlabel("Original absolute time (microseconds)")
    fig.suptitle(f"{item['id']} | frozen onset interval shaded | no calibrated wavelength\n"
                 "o = original gate passed; x = rejected candidate; open diamond = short raw-evidence support; "
                 "gray | = missing\n"+"; ".join(counts[:2])+"\n"+"; ".join(counts[2:]), fontsize=10)
    fig.text(.01, .004, "*Inherited headerless volts/seconds mapping. STFT bands: 0.05-6 GHz; "
             "stage 0.005-6 GHz; VarPro native 0.005-8 GHz. Support does not establish target identity.", fontsize=8)
    fig.tight_layout(rect=(0, .025, 1, .91))
    base = dest / (item["id"]+"__onset_card")
    fig.savefig(base.with_suffix(".png"), dpi=150)
    fig.savefig(base.with_suffix(".svg"))
    plt.close(fig)
    return {"channel": item["id"], "png": base.with_suffix(".png").relative_to(OUT).as_posix(),
            "svg": base.with_suffix(".svg").relative_to(OUT).as_posix()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, default=OUT / "data/analysis_v03")
    args = parser.parse_args()
    dest = args.output.resolve()
    if not dest.is_relative_to(OUT / "figures"):
        parser.error("Choose a new TASK-017 figure directory")
    dest.mkdir(exist_ok=False)
    with ProcessPoolExecutor(max_workers=3) as executor:
        manifest = list(executor.map(card, records(), [str(dest)]*len(records()),
                                    [str(args.analysis)]*len(records())))
    frame = pd.read_csv(args.analysis / "segment_metrics.csv")
    onset = frame[frame.stage == "onset"]
    fig, axs = plt.subplots(4, 4, figsize=(17, 12), sharey=False)
    for ax, item in zip(axs.flat, records(), strict=False):
        sub = onset[onset.channel == item["id"]].set_index("method")
        names = list(FOCUS)
        for j, (key, label) in enumerate((("candidate_n", "candidate"), ("gated_n", "gated"),
                                           ("supported_n", "raw-supported"))):
            ax.bar(np.arange(4)+(j-1)*.23, sub.loc[names, key], .23, label=label)
        ax.set_title(item["id"], fontsize=9)
        ax.set_xticks(range(4), ["Balanced", "Mean512", "Clip512", "Visual VP"], fontsize=7)
        ax.set_ylim(0, float(sub.centers.iloc[0])+1)
        ax.grid(axis="y", alpha=.15)
    for ax in list(axs.flat)[14:]:
        ax.axis("off")
    axs[0, 0].legend(fontsize=7)
    fig.suptitle("Real onset counts at fixed original sample centers | 14 channels in 10 files\n"
                 "C/G/S are distinct observables; overlapping frames and paired channels are not independent repeats")
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(dest / "onset_counts.png", dpi=150)
    fig.savefig(dest / "onset_counts.svg")
    plt.close(fig)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("14 onset cards and count summary complete", flush=True)


if __name__ == "__main__":
    main()
