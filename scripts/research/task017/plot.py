"""Per-channel candidate curves, status rows and raw spectral overlays (PNG/SVG)."""
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

from scripts.research.task017.compare import frozen_plans
from scripts.research.task017.prepare import OUT, load, records, spectrum

GROUPS = [
    ["M1_balanced", "formal_short512", "formal_long2048", "balanced_wide8", "short_wide8"],
    ["M1_balanced", "demean1024_control", "detrend1024_control", "demean512_control"],
    ["M1_balanced", "stft_short", "stft_long", "stage_stft1024", "unclipped_short"],
    ["M1_balanced", "dechirp", "varpro", "clutter_varpro", "signed_dechirp"],
    ["M1_balanced", "low_glrt", "stft_low", "tone_refine"],
    ["M1_balanced", "acmd", "matrix_pencil", "time_domain", "visual_onset_dechirp", "visual_onset_varpro"],
    ["M1_balanced", "M2_task014_gui", "M3_parameters", "M4_specialized", "TASK014_research_simple"],
]
FOCUS = ["M1_balanced", "formal_short512", "stft_short", "dechirp", "varpro",
         "low_glrt", "visual_onset_varpro", "M4_specialized"]
LABEL = {
    "M1_balanced": "Balanced 1024 (6 GHz)", "formal_short512": "Formal short 512",
    "formal_long2048": "Formal long 2048", "balanced_wide8": "Balanced 1024 (8 GHz)",
    "short_wide8": "Short 512 (8 GHz)", "stft_short": "Stage-clipped short 512",
    "stft_long": "Stage-clipped long 2048", "stage_stft1024": "Stage-clipped 1024",
    "unclipped_short": "Detrended full-support 512", "low_glrt": "Low-band GLRT",
    "stft_low": "Low-band STFT", "tone_refine": "Long-window tone refinement",
    "dechirp": "Native Dechirp", "varpro": "Native VarPro", "clutter_varpro": "Clutter VarPro",
    "signed_dechirp": "Stage-clipped signed Dechirp", "acmd": "ACMD-inspired variant",
    "matrix_pencil": "LS matrix-pencil family", "time_domain": "Regularized time-domain model",
    "visual_onset_dechirp": "Dechirp + visual onset", "visual_onset_varpro": "VarPro + visual onset",
    "M2_task014_gui": "TASK015 M2 (old GUI map)", "M3_parameters": "TASK015 M3 parameters",
    "M4_specialized": "TASK015 M4 specialized", "TASK014_research_simple": "TASK014 research replay",
    "demean1024_control": "Mean removed / Hann1024 control",
    "detrend1024_control": "Linear baseline removed / Hann1024",
    "demean512_control": "Mean removed / Hann512 control",
}
METHODS = list(dict.fromkeys(m for g in GROUPS for m in g))
PALETTE = [*[plt.colormaps["tab20"](i/19) for i in range(20)],
           *[plt.colormaps["Dark2"](i/7) for i in range(8)]]
COLORS: dict[str, Any] = {name: PALETTE[i] for i, name in enumerate(METHODS)}
COLORS["M1_balanced"] = "#191919"
STAGE_COLOR = {"stationary": "#dddddd", "unknown": "#ddd1e7", "onset": "#e9a77c",
               "plateau": "#cae6db", "decline": "#bed9ec", "rebound": "#e2db98",
               "acceleration": "#f0c6d1", "weak_signal": "#eed6b9", "noise": "#eeeeee"}


def finish(fig: Any, path: Path, title: str) -> None:
    if path.with_suffix(".png").exists():
        raise FileExistsError(path)
    fig.suptitle(title, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, .975))
    fig.savefig(path.with_suffix(".png"), dpi=130)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)


def stage_marks(ax: Any, segments: Any) -> None:
    for seg in segments:
        if seg["stage"] == "onset":
            ax.axvline(seg["start_s"]*1e6, color="#ac5327", linewidth=.8, alpha=.7)
            ax.axvspan(*(v*1e6 for v in seg["start_range_s"]), color="#ac5327", alpha=.13)
            ax.axvline(seg["end_s"]*1e6, color="#ac5327", linewidth=.6, alpha=.5)
    ax.ticklabel_format(axis="x", useOffset=False, style="plain")
    ax.grid(alpha=.12)


def draw_curve(ax: Any, name: str, values: Any, bounds: tuple[float, float]) -> None:
    t = values["time_s"]*1e6
    selected = (t >= bounds[0]) & (t <= bounds[1])
    f, gated = values["frequency_hz"]/1e9, np.isfinite(values["gated_frequency_hz"])
    for segment in np.unique(values["segment_id"][selected]):
        mask = selected & (values["segment_id"] == segment)
        ax.plot(t[mask], f[mask], color=COLORS[name], alpha=.55, linewidth=.65)
    ax.scatter(t[selected & gated], f[selected & gated], s=7, color=COLORS[name],
               label=LABEL[name], zorder=3)
    rejected = selected & ~gated & np.isfinite(f)
    ax.scatter(t[rejected], f[rejected], s=15, color=COLORS[name], marker="x", linewidth=.65)


def background(ax: Any, spec: Any, bounds: tuple[float, float]) -> None:
    freq, t, power = spec
    fsel = freq <= 8e9
    tsel = (t*1e6 >= bounds[0]-.04) & (t*1e6 <= bounds[1]+.04)
    db = 10*np.log10(np.maximum(power[fsel][:, tsel], 1e-30)/max(float(power.max()), 1e-30))
    ax.pcolormesh(t[tsel]*1e6, freq[fsel]/1e9, db, vmin=-60, vmax=0,
                  shading="auto", cmap="Greys", rasterized=True, alpha=.8)


def curves(item: Any, traces: Any, segments: Any, dest: Path, tag: str,
           bounds: tuple[float, float], spec: Any | None = None) -> None:
    groups = GROUPS if spec is None else [GROUPS[0], GROUPS[1], GROUPS[3], GROUPS[5], GROUPS[6]]
    fig, axs = plt.subplots(len(groups)+1, 1, figsize=(15, 3*len(groups)+1.8), sharex=True,
                            gridspec_kw={"height_ratios": [3]*len(groups)+[1.5]})
    for ax, group in zip(axs, groups, strict=False):
        if spec is not None:
            background(ax, spec, bounds)
        for name in group:
            draw_curve(ax, name, traces[name], bounds)
        stage_marks(ax, segments)
        ax.set_ylim(0, 8.25)
        ax.set_ylabel("Beat frequency (GHz)")
        ax.legend(loc="upper left", fontsize=8, ncol=3, framealpha=.87)
    # Missing estimates are categorical symbols, never plotted as zero-frequency data.
    ax = axs[-1]
    for i, name in enumerate(FOCUS):
        v = traces[name]
        t = v["time_s"]*1e6
        selected = (t >= bounds[0]) & (t <= bounds[1])
        missing = selected & ~np.isfinite(v["frequency_hz"])
        rejected = selected & np.isfinite(v["frequency_hz"]) & ~np.isfinite(v["gated_frequency_hz"])
        passed = selected & np.isfinite(v["gated_frequency_hz"])
        for mask, marker, color in ((missing, "|", "#bbb"), (rejected, "x", "#b35625"),
                                    (passed, ".", "#167153")):
            ax.scatter(t[mask], np.full(int(mask.sum()), i), s=8, marker=marker, c=color)
    ax.set_yticks(range(len(FOCUS)), [LABEL[name] for name in FOCUS], fontsize=7)
    ax.set_ylabel("Status only", fontsize=8)
    ax.set_ylim(-.7, len(FOCUS)-.3)
    ax.set_xlim(*bounds)
    ax.ticklabel_format(axis="x", useOffset=False, style="plain")
    ax.set_xlabel("Original absolute time (microseconds)")
    title = (f"{item['id']} | {tag} | circles = original gate passed; x = rejected candidate; "
             "gray | = missing (status rows)\n"
             "Bands differ: formal 0.05-6 GHz, wide/native to 8 GHz, low methods 0.005-0.25 GHz; "
             "wavelength UNCONFIRMED; branch identity requires experimental confirmation")
    finish(fig, dest / tag, title)


def segmentation(item: Any, segments: Any, spec: Any, dest: Path) -> None:
    t, y, _ = load(item)
    fig, axs = plt.subplots(3, 1, figsize=(15, 8), sharex=True,
                            gridspec_kw={"height_ratios": [.6, 1, 3]})
    for seg in segments:
        axs[0].axvspan(seg["start_s"]*1e6, seg["end_s"]*1e6,
                       color=STAGE_COLOR[seg["stage"]], ec="white")
        if (seg["end_s"]-seg["start_s"])/(t[-1]-t[0]) > .045:
            axs[0].text((seg["start_s"]+seg["end_s"])*.5e6, .5,
                         seg["id"]+" "+seg["stage"], ha="center", va="center", fontsize=8)
    axs[0].set_yticks([])
    block = max(1, len(t)//4000)
    raw = y[:len(y)//block*block].reshape(-1, block)
    tt = t[:len(raw)*block:block]*1e6
    axs[1].fill_between(tt, raw.min(axis=1), raw.max(axis=1), color="#426a7b")
    axs[1].set_ylabel("Raw voltage (V)*")
    background(axs[2], spec, (t[0]*1e6, t[-1]*1e6))
    axs[2].set_ylim(0, 8)
    axs[2].set_ylabel("Beat frequency (GHz)")
    axs[2].set_xlabel("Original absolute time (microseconds)")
    for ax in axs:
        stage_marks(ax, segments)
    axs[2].set_xlim(t[0]*1e6, t[-1]*1e6)
    finish(fig, dest / "frozen_segmentation", f"{item['id']} | FROZEN visual segments | "
           "raw Hann 1024 evidence only\n*Inherited headerless seconds/volts mapping; "
           "no measured zero; wavelength UNCONFIRMED; boundaries are uncertain manual judgements")


def execute(item: Any, analysis: str, output: str) -> list[dict[str, str]]:
    channel = item["id"]
    traces = {name: dict(np.load(Path(analysis) / channel / f"{name}.npz")) for name in METHODS}
    t, y, fs = load(item)
    spec = spectrum(t, y, fs, 1024)
    dest = Path(output) / channel
    dest.mkdir()
    segments = frozen_plans()[channel]
    segmentation(item, segments, spec, dest)
    full = (t[0]*1e6, t[-1]*1e6)
    curves(item, traces, segments, dest, "full_curves", full)
    curves(item, traces, segments, dest, "full_spectral_overlay", full, spec)
    onset = next(s for s in segments if s["stage"] == "onset")
    bounds = ((onset["start_s"]-25e-9)*1e6, (onset["end_s"]+40e-9)*1e6)
    curves(item, traces, segments, dest, "onset_curves", bounds)
    curves(item, traces, segments, dest, "onset_spectral_overlay", bounds, spec)
    for seg in segments:
        if seg["stage"] in ("stationary", "unknown", "noise", "onset"):
            continue
        bounds = (max(t[0], seg["start_s"]-10e-9)*1e6,
                  min(t[-1], seg["end_s"]+10e-9)*1e6)
        curves(item, traces, segments, dest, seg["id"]+"_"+seg["stage"], bounds, spec)
    print("figures", channel, flush=True)
    return [{"channel": channel, "png": p.relative_to(OUT).as_posix(),
             "svg": p.with_suffix(".svg").relative_to(OUT).as_posix()}
            for p in sorted(dest.glob("*.png"))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--id")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(OUT / "figures"):
        parser.error("Choose a new TASK-017 figure directory")
    output.mkdir(exist_ok=False)
    items = [item for item in records() if not args.id or args.id == item["id"]]
    with ProcessPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(execute, items, [str(args.analysis)]*len(items),
                                    [str(output)]*len(items)))
    manifest = [row for result in results for row in result]
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
