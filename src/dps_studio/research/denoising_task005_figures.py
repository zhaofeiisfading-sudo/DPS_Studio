"""Publication figures from TASK005's actual, frozen voltage-derived outputs."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Rectangle
import numpy as np

Row = dict[str, Any]
COLORS = {"M0": "#C45A26", "M1": "#8974A5", "M2": "#566C8E",
          "M3": "#919191", "N5": "#007A9C", "seed": "#008D64"}
LABELS = {"M0": "Strongest", "M1": "P3", "M2": "M2", "M3": "M3", "N5": "SG-DBand"}
STYLE: Any = {"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"],
    "font.size": 6.8, "axes.titlesize": 7.3, "axes.labelsize": 7., "legend.fontsize": 6.4,
    "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "axes.linewidth": .65,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "svg.fonttype": "none", "pdf.fonttype": 42, "savefig.facecolor": "white"}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _arrays(path: Path) -> Row:
    with np.load(path) as data:
        return {key: data[key] for key in data.files}


def _case(work: Path, config: Row, manifest: list[Row], cid: str, profile: str
          ) -> tuple[Row, Row, Row]:
    case = next(c for c in config["real_cases"] if c["case_id"] == cid)
    meta = next(m for m in manifest if m["case_id"] == cid and m["profile"] == profile)
    return case, meta, _arrays(work / "real" / (meta["tag"] + ".npz"))


def _reference(d: Row, t_ns: Any, xlim: Any, ylim: Any) -> float:
    time_mask = (t_ns >= xlim[0]) & (t_ns <= xlim[1])
    frequency_mask = ((d["frequency_hz"] >= ylim[0]*1e9)
                      & (d["frequency_hz"] <= ylim[1]*1e9))
    return float(np.max(d["magnitude"][frequency_mask][:, time_mask]))


def _spectrum(ax: Axes, d: Row, time_ns: Any, xlim: Any, ylim: Any,
              reference: float) -> Any:
    image_db = 20*np.log10(np.maximum(d["magnitude"], 1e-30)/reference)
    mesh = ax.pcolormesh(time_ns, d["frequency_hz"]/1e9, image_db, cmap="Greys",
                         vmin=-45, vmax=0, shading="nearest", rasterized=True)
    ax.set(xlim=xlim, ylim=ylim, xlabel="Time after first sample (ns)", ylabel="Frequency (GHz)")
    ax.tick_params(direction="out", length=2.5, width=.6)
    return mesh


def _line(ax: Axes, t: Any, f: Any, method: str, *, label: str | None = None) -> None:
    styles = {"M0": "-", "M1": "--", "M2": ":", "M3": "-.", "N5": "-"}
    ax.plot(t, f/1e9, color=COLORS[method], ls=styles[method],
            lw=.95 if method == "N5" else .78, label=label or LABELS[method])


def _seed(ax: Axes, case: Row) -> None:
    ax.plot(case["seed_relative_ns"], case["seed_frequency_ghz"], marker="*", ms=6.5,
            color=COLORS["seed"], markeredgecolor="white", markeredgewidth=.3, zorder=6)


def _save(fig: Figure, output: Path, name: str) -> None:
    targets = [output / (name+suffix) for suffix in (".svg", ".pdf", ".png")]
    if any(path.exists() for path in targets):
        raise FileExistsError(f"Refusing to overwrite figure {name}")
    for path in targets:
        fig.savefig(path, dpi=500)
    plt.close(fig)


def figure01(work: Path, output: Path, config: Row, manifest: list[Row]) -> None:
    case, meta, d = _case(work, config, manifest, "D1", "balanced")
    t = (d["time_s"]-meta["start_s"])*1e9
    xlim = case["analysis_relative_ns"]
    ylim = case["display_frequency_ghz"]
    reference = _reference(d, t, xlim, ylim)
    fig = plt.figure(figsize=(183/25.4, 139/25.4))
    grid = fig.add_gridspec(2, 2, left=.09, right=.91, bottom=.105, top=.88,
                           wspace=.31, hspace=.48)
    axes = [fig.add_subplot(grid[i, j]) for i in range(2) for j in range(2)]
    for ax, method, title in zip(axes[:2], ("M0", "N5"),
                                 ("a  Strongest", "b  SG-DBand: one specified seed"), strict=True):
        im = _spectrum(ax, d, t, xlim, ylim, reference)
        _line(ax, t, d[method], method)
        ax.set_title(title, loc="left", fontweight="bold", pad=7)
        ax.set_xticks([1650, 1750, 1850, 1950])
    _seed(axes[1], case)
    axes[1].annotate("specified weaker band", xy=(1680, .87), xytext=(1680, 1.06),
                     fontsize=6.5, ha="center", arrowprops={"arrowstyle": "-", "lw": .6})
    cbar = fig.colorbar(im, cax=fig.add_axes((.935, .59, .012, .29)))
    cbar.set_label("Relative magnitude (dB)", fontsize=6.5, labelpad=1)
    detail = (1620, 1755)
    _spectrum(axes[2], d, t, detail, (.18, 1.02), reference)
    q_detail = (t >= detail[0]) & (t <= detail[1])
    equal = all(np.array_equal(d["M0"][q_detail], d[m][q_detail]) for m in ("M1", "M2"))
    if equal:
        _line(axes[2], t, d["M0"], "M0", label="Strongest = P3 = M2")
    else:
        for method in ("M0", "M1", "M2"):
            _line(axes[2], t, d[method], method)
    _line(axes[2], t, d["N5"], "N5")
    axes[2].set_title("c  Detail: Strongest = P3 = M2" if equal else "c  Detail: method comparison",
                      loc="left", fontweight="bold", pad=7)
    if not equal:
        axes[2].legend(loc="center right", ncol=1, fontsize=6.)
    q = (t >= xlim[0]) & (t <= xlim[1])
    changed = q & np.isfinite(d["N5"]) & (abs(d["N5"]-d["M0"]) > 1.)
    delta = (d["N5"][changed]-d["M0"][changed])/1e9
    axes[3].axhline(0, color=".65", lw=.6)
    axes[3].vlines(t[changed], 0, delta, color=COLORS["N5"], lw=.6)
    axes[3].scatter(t[changed], delta, color=COLORS["N5"], s=5, zorder=3)
    axes[3].set(xlim=xlim, xlabel="Time after first sample (ns)", ylabel="Selected minus Strongest (GHz)")
    axes[3].set_xticks([1650, 1750, 1850, 1950])
    axes[3].set_title(f"d  Original-candidate replacements (n = {changed.sum()})",
                      loc="left", fontweight="bold", pad=7)
    fig.suptitle("20260607.csv | ch2 | Balanced | guided selection of an observed band",
                 y=.975, fontsize=8.5, fontweight="bold")
    finite_count = int((q & np.isfinite(d["N5"])).sum())
    fig.text(.5, .933, f"Shared 0.2–6 GHz search | {finite_count}/{q.sum()} frames retained | "
             "seed: 1800 ns, 0.86 GHz (±0.10 GHz)", ha="center", fontsize=7.)
    fig.text(.09, .025, "Identical original STFT in a–c. Gaps are NaN. Seed-defined identity is unvalidated.", fontsize=6.5)
    _save(fig, output, "Figure01_Real_Repair")


def figure02(work: Path, output: Path, config: Row, manifest: list[Row]) -> None:
    cids = ("D1", "T1", "N1", "N2")
    fig, axes = plt.subplots(4, 2, figsize=(183/25.4, 193/25.4))
    fig.subplots_adjust(left=.10, right=.91, bottom=.065, top=.915, wspace=.29, hspace=.65)
    last_image = None
    for i, cid in enumerate(cids):
        loaded = [_case(work, config, manifest, cid, p) for p in ("balanced", "high_time_resolution")]
        case = loaded[0][0]
        xlim, ylim = case["analysis_relative_ns"], case["display_frequency_ghz"]
        reference = max(_reference(d, (d["time_s"]-m["start_s"])*1e9, xlim, ylim)
                        for _, m, d in loaded)
        for j, (_, meta, d) in enumerate(loaded):
            ax = axes[i, j]
            t = (d["time_s"]-meta["start_s"])*1e9
            last_image = _spectrum(ax, d, t, xlim, ylim, reference)
            for method in ("M0", "M1", "M2", "N5"):
                _line(ax, t, d[method], method)
            _seed(ax, case)
            q = (t >= xlim[0]) & (t <= xlim[1])
            finite = q & np.isfinite(d["N5"])
            same = int((finite & (d["N5"] == d["M0"])).sum())
            profile = "Balanced" if j == 0 else "HTR"
            title = f"{chr(97+2*i+j)}  {case['filename']} | {case['channel'].replace('pdv_channel_', 'ch')} | {profile}"
            ax.set_title(title, loc="left", fontweight="bold", fontsize=6.8, pad=6)
            ax.text(.03, .95, f"N5: {finite.sum()}/{q.sum()} finite; {same} unchanged from Strongest",
                    transform=ax.transAxes, va="top", fontsize=6.,
                    bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 1.5})
            if cid == "N2" and finite.any():
                last = int(np.flatnonzero(finite)[-1])
                ax.annotate(f"N5 terminates at {t[last]:.1f} ns", xy=(t[last], d["N5"][last]/1e9),
                            xytext=(.50, .70), textcoords="axes fraction", fontsize=6.,
                            arrowprops={"arrowstyle": "-", "lw": .6, "color": COLORS["N5"]})
            if j:
                ax.set_ylabel("")
    handles = [Line2D([], [], color=COLORS[m], ls={"M1": "--", "M2": ":"}.get(m, "-"),
                      lw=.9, label=LABELS[m]) for m in ("M0", "M1", "M2", "N5")]
    handles.append(Line2D([], [], color=COLORS["seed"], marker="*", ls="", ms=5., label="Specified seed"))
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.51, .978), ncol=5)
    assert last_image is not None
    cbar = fig.colorbar(last_image, cax=fig.add_axes((.935, .38, .012, .24)))
    cbar.set_label("Relative magnitude (dB)", fontsize=6.5, labelpad=1)
    fig.text(.10, .017, "One common spectral reference per row. Windows are paired views of the same voltage. "
             "No real-data truth is assumed.", fontsize=6.1)
    _save(fig, output, "Figure02_Real_Multiple_Cases")


def _pooled(rows: list[Row], method: str) -> Row:
    selected = [r for r in rows if r["method"] == method]
    fields = ("present_frames", "finite_present_frames", "wrong_frames", "missing_frames",
              "corrected_frames", "harmed_frames", "abstained_previously_correct", "sum_squared_error_hz2")
    result = {key: sum(float(r[key]) for r in selected) for key in fields}
    result["rmse_hz"] = np.sqrt(result["sum_squared_error_hz2"]/result["finite_present_frames"])
    result["coverage"] = result["finite_present_frames"]/result["present_frames"]
    return result


def _seed_window_control(d: Row, case: Row) -> Any:
    """Actual original-peak selections given the same constant seed interval."""
    frequency = np.full(len(d["time_s"]), np.nan)
    center = case["seed_frequency_ghz"]*1e9
    tolerance = case["seed_frequency_tolerance_hz"]
    eligible = ((abs(d["candidate_f"]-center) <= tolerance) & (d["candidate_bg"] >= 6))
    for i in np.flatnonzero(np.any(eligible, axis=1)):
        j = int(np.flatnonzero(eligible[i])[0])
        frequency[i] = d["candidate_f"][i, j]
    return frequency


def figure02_context(work: Path, output: Path, config: Row, manifest: list[Row]) -> None:
    """Disclose full-record context and a post-freeze normal-curve extension."""
    fig, axes = plt.subplots(2, 2, figsize=(183/25.4, 150/25.4))
    fig.subplots_adjust(left=.10, right=.91, bottom=.13, top=.87, wspace=.34, hspace=.54)
    descriptions = ("D1", "N1", "N2", "A1")
    controls: list[Row] = []
    for ax, cid in zip(axes.flat, descriptions, strict=True):
        case, meta, d = _case(work, config, manifest, cid, "balanced")
        t = (d["time_s"]-meta["start_s"])*1e9
        if cid == "N1":
            xlim, ylim = (280., 835.3), (2.45, 5.)
        else:
            xlim = (float(t[0]), float(t[-1]))
            ylim = (.2, 2.5) if cid == "D1" else ((.5, 6.) if cid == "N2" else (.2, 6.))
        reference = _reference(d, t, xlim, ylim)
        im = _spectrum(ax, d, t, xlim, ylim, reference)
        _line(ax, t, d["M0"], "M0")
        _line(ax, t, d["N5"], "N5")
        _seed(ax, case)
        q = (t >= xlim[0]) & (t <= xlim[1])
        finite = q & np.isfinite(d["N5"])
        title = {"D1": "a  Full record: early identity is not inferred",
                 "N1": "b  Normal curve: frequency can leave seed interval",
                 "N2": "c  A real fast-transition limitation",
                 "A1": "d  Weak event: only a short fragment survives"}[cid]
        ax.set_title(title, loc="left", fontweight="bold", fontsize=6.8, pad=7)
        ax.text(.03, .95, case["filename"]+f" | N5: {finite.sum()}/{q.sum()} finite",
                transform=ax.transAxes, va="top", fontsize=6.,
                bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 1.5})
        if cid == "N1":
            fixed = _seed_window_control(d, case)
            ax.plot(t, fixed/1e9, color="#666666", ls="--", lw=.7, label="Seed-window Strongest")
            center = case["seed_frequency_ghz"]*1e9
            left_interval = finite & (abs(d["N5"]-center) > case["seed_frequency_tolerance_hz"])
            matches = finite & (d["N5"] == d["M0"])
            controls.append(dict(case_id="N1_extension_exploratory", profile="balanced",
                first_ns=xlim[0], last_ns=xlim[1], frames=int(q.sum()),
                new_finite=int(finite.sum()), new_matches_strongest=int(matches.sum()),
                new_outside_static_seed_interval=int(left_interval.sum()),
                fixed_window_finite=int((q & np.isfinite(fixed)).sum()),
                new_frequency_span_hz=float(np.ptp(d["N5"][finite]))))
            ax.legend(loc="lower left", fontsize=5.8)
    cbar = fig.colorbar(im, cax=fig.add_axes((.935, .58, .012, .29)))
    cbar.set_label("Relative magnitude (dB)", fontsize=6.3, labelpad=1)
    fig.suptitle("Full context, dynamic tracking and observed limits", y=.98,
                 fontsize=8.5, fontweight="bold")
    fig.text(.5, .928, "All curves are executed selections of original peaks; "
             "the grey control uses the same seed-frequency interval.", ha="center", fontsize=6.5)
    fig.text(.10, .035, "Panel b extends the frozen normal-case window for exploratory diagnosis; "
             "it does not replace the registered plateau result.", fontsize=6.1)
    with (output / "Figure02b_control_numbers.json").open("x", encoding="utf-8") as stream:
        json.dump(controls, stream, indent=2)
    _save(fig, output, "Figure02b_Real_Context")


def figure03(work: Path, output: Path, config: Row) -> None:
    cid = "task005_persistent_competitor_53051000"
    d = _arrays(work / "synthetic" / (cid+"__balanced.npz"))
    t = d["time_s"]*1e9
    xlim, ylim = (0, 800), (1.35, 3.65)
    reference = _reference(d, t, xlim, ylim)
    fig, axes = plt.subplots(2, 2, figsize=(183/25.4, 141/25.4))
    fig.subplots_adjust(left=.09, right=.91, bottom=.15, top=.88, wspace=.33, hspace=.55)
    for j, ax in enumerate(axes[0]):
        im = _spectrum(ax, d, t, xlim, ylim, reference)
        if j == 0:
            for method in ("M0", "M1", "M2"):
                _line(ax, t, d[method], method)
        else:
            ax.plot(t, d["truth"]/1e9, color="black", lw=.8, ls="--", label="Truth")
            _line(ax, t, d["N5"], "N5")
            ax.plot(float(d["seed_time_s"])*1e9, float(d["seed_frequency_hz"])/1e9,
                    marker="*", ms=6.5, color=COLORS["seed"], zorder=5)
            ax.legend(loc="upper left", ncol=2, fontsize=6.)
        ax.set_title(("a  Strongest / P3 / M2", "b  SG-DBand and known target")[j],
                     loc="left", fontweight="bold", pad=7)
    cbar = fig.colorbar(im, cax=fig.add_axes((.935, .59, .012, .29)))
    cbar.set_label("Relative magnitude (dB)", fontsize=6.5, labelpad=1)
    with (work / "synthetic_metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    methods = ("M0", "M1", "M2", "M3", "N5")
    pooled = [_pooled(rows, m) for m in methods]
    x = np.arange(len(methods))
    rmses = [p["rmse_hz"]/1e6 for p in pooled]
    bars = axes[1, 0].bar(x, rmses, color=[COLORS[m] for m in methods], width=.63)
    axes[1, 0].set(xticks=x, xticklabels=[LABELS[m] for m in methods], ylabel="Finite-output RMSE (MHz)")
    for bar, value in zip(bars, rmses, strict=True):
        axes[1, 0].annotate(f"{value:.1f}", (bar.get_x()+bar.get_width()/2, value),
                            xytext=(0, 3), textcoords="offset points", ha="center", fontsize=6.3)
    axes[1, 0].set_ylim(0, max(rmses)*1.25)
    axes[1, 0].set_title("c  All 12 waveforms × 2 paired windows", loc="left", fontweight="bold", pad=7)
    wrong = np.array([p["wrong_frames"]/p["present_frames"]*100 for p in pooled])
    missing = np.array([p["missing_frames"]/p["present_frames"]*100 for p in pooled])
    axes[1, 1].bar(x, wrong, color=[COLORS[m] for m in methods], width=.63)
    axes[1, 1].bar(x, missing, bottom=wrong, color="white", edgecolor=[COLORS[m] for m in methods],
                   hatch="////", width=.63, linewidth=.7)
    axes[1, 1].set(xticks=x, xticklabels=[LABELS[m] for m in methods],
                   ylabel="Wrong or missing / present frames (%)")
    axes[1, 1].set_ylim(0, max(float(np.max(wrong+missing))*1.25, 10))
    axes[1, 1].set_title("d  Failures include missing outputs", loc="left", fontweight="bold", pad=7)
    axes[1, 1].legend(handles=[Rectangle((0, 0), 1, 1, fc=".5", label="Wrong finite"),
        Rectangle((0, 0), 1, 1, fc="white", ec=".5", hatch="////", label="Missing")],
        loc="upper center", ncol=2, fontsize=6.)
    fig.suptitle("Independent voltage → STFT → candidate → algorithm validation",
                 y=.98, fontsize=8.5, fontweight="bold")
    fig.text(.5, .933, "Algorithm frozen before testing | 100 MHz error threshold | "
             "one coarse target cue per waveform", ha="center", fontsize=6.8)
    new = pooled[-1]
    fig.text(.09, .055, f"SG-DBand: {new['corrected_frames']:.0f} corrections; "
             f"{new['harmed_frames']:.0f} finite harms; "
             f"{new['abstained_previously_correct']:.0f} previously correct frames abstained.", fontsize=6.3)
    fig.text(.09, .025, "Includes absence, close-approach and fast-return limitations. "
             "RMSE uses finite outputs; d uses every eligible present frame.", fontsize=6.3)
    _save(fig, output, "Figure03_Synthetic_Validation")


def figure04(work: Path, output: Path, config: Row, manifest: list[Row]) -> None:
    case, meta, d = _case(work, config, manifest, "D1", "balanced")
    t = (d["time_s"]-meta["start_s"])*1e9
    fig = plt.figure(figsize=(183/25.4, 116/25.4))
    flow = fig.add_axes((.06, .65, .91, .27))
    flow.set(xlim=(0, 1), ylim=(0, 1))
    flow.axis("off")
    texts = ["Original voltage\nu(t)", "Two Hann STFTs\n768 / 512 samples",
             "Original Top-20\n+ oriented tubes", "Peak agreement\n+ persistent graph",
             "One seed\n+ bidirectional path"]
    centers = np.linspace(.075, .925, 5)
    for i, (x, text) in enumerate(zip(centers, texts, strict=True)):
        flow.add_patch(Rectangle((x-.072, .35), .144, .48,
                                 fc="#EAF1F4" if i < 4 else "#DCEEE8", ec="#607984", lw=.7))
        flow.text(x, .59, text, ha="center", va="center", fontsize=6.2)
        if i:
            flow.add_patch(FancyArrowPatch((centers[i-1]+.075, .59), (x-.077, .59),
                                           arrowstyle="-|>", mutation_scale=7, lw=.7, color="#607984"))
    flow.text(.5, .12, "Finite output = an original primary-window peak; unsupported frame = NaN",
               ha="center", fontsize=6.8)
    axes = [fig.add_axes((.10, .14, .35, .43)), fig.add_axes((.56, .14, .35, .43))]
    xlim, ylim = (1616, 1950), (.18, 1.15)
    reference = _reference(d, t, xlim, ylim)
    for ax in axes:
        im = _spectrum(ax, d, t, xlim, ylim, reference)
    valid = d["companion_support"] & (d["candidate_bg"] >= 6)
    q = (t >= xlim[0]) & (t <= xlim[1])
    i, j = np.nonzero(valid & q[:, None])
    axes[0].scatter(t[i], d["candidate_f"][i, j]/1e9, s=3.8, facecolors="none",
                     edgecolors="#7E6A9D", linewidths=.4, alpha=.8)
    axes[0].add_patch(Rectangle((1680-12.8, .86-meta["resolution_hz"]/2e9),
        25.6, meta["resolution_hz"]/1e9, fc="none", ec=COLORS["N5"], lw=.9))
    axes[0].set_title("a  Cross-window supported original peaks", loc="left", fontweight="bold", pad=7)
    axes[0].text(.03, .95, "Rectangle: local support footprint", transform=axes[0].transAxes,
                 va="top", fontsize=6., bbox={"facecolor": "white", "edgecolor": "none", "alpha": .8})
    _line(axes[1], t, d["N5"], "N5")
    _seed(axes[1], case)
    axes[1].set_title("b  Seed-constrained observed branch", loc="left", fontweight="bold", pad=7)
    cbar = fig.colorbar(im, cax=fig.add_axes((.935, .22, .012, .28)))
    cbar.set_label("Relative magnitude (dB)", fontsize=6.3, labelpad=1)
    fig.suptitle("SG-DBand: sparse identity cue + two-window spectral structure",
                 y=.98, fontsize=8.5, fontweight="bold")
    fig.text(.10, .025, "Actual 20260607.csv / ch2 data. Window agreement is structural evidence, "
             "not independent target validation.", fontsize=6.3)
    _save(fig, output, "Figure04_Method_Diagram")


def build_figures(work: Path, output: Path, config_path: Path) -> None:
    if output.exists():
        raise FileExistsError("Figure output directory must be new")
    config = _json(config_path)
    manifest = _json(work / "real_manifest.json")
    output.mkdir(parents=True)
    with plt.rc_context(STYLE):
        figure01(work, output, config, manifest)
        figure02(work, output, config, manifest)
        figure02_context(work, output, config, manifest)
        figure03(work, output, config)
        figure04(work, output, config, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    build_figures(args.work_dir, args.output_dir, args.config)


if __name__ == "__main__":
    main()
