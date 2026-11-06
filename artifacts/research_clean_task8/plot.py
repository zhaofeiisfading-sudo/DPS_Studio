"""File-backed full-coverage figures; fixed first-instance synthetic examples."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .audit import OUT, ROOT
from .common import WAVELENGTH_M, Context
from .catalog import METHODS, run_folder
from .data import FAMILIES, read_raw
from .runner import write_csv, write_json

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "savefig.dpi": 150, "figure.dpi": 110})
COLORS = dict(zip(METHODS, ("#666666", "#242424", "#a6a6a6", "#3998a3", "#118c78",
                          "#316fba", "#d27c18", "#c53030", "#8465aa", "#91634b",
                          "#449348", "#b34b8e", "#7c8e39", "#3f536f"), strict=True))


def save(fig: Any, path: Path, svg: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    if svg:
        fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def real_plots() -> list[dict[str, Any]]:
    table = pd.read_csv(OUT/"tables/all_real_metrics.csv")
    inventory = json.loads((OUT/"raw_inventory.json").read_text(encoding="utf-8"))
    manifest = []
    for item in inventory:
        if item["kind"] != "RAW":
            continue
        for channel, signal in enumerate(read_raw(item), 1):
            rows = table[(table.raw_path == item["path"]) & (table.voltage_column == channel)]
            context = Context(signal)
            start = signal.time_s[0]
            band = context.freq_grid <= 8e9
            spec = context.raw_spectrum[band]
            db = 20*np.log10(np.maximum(spec, 1e-300)/max(float(spec.max()), 1e-300))
            ts = (context.seed_time-start)*1e9
            extent = (ts[0], ts[-1], 0., context.freq_grid[band][-1]/1e9)
            for row in rows.itertuples():
                name, case_id = row.method, row.case_id
                p = run_folder(OUT, name, "real", case_id)
                path = OUT/name/"figures/real"/f"{case_id}.png"
                if path.exists():
                    manifest.append(dict(method=name, domain="REAL_NO_GT", case_id=case_id,
                        path=path.relative_to(OUT).as_posix(), selection="ALL_RAW_CHANNELS"))
                    continue
                result = np.load(p/"trajectory.npz")
                t = (result["time_s"]-start)*1e9
                f, accepted = result["frequency_hz"], result["accepted_hz"]
                fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True,
                                         gridspec_kw={"height_ratios": [2.3, 1.7, 1]})
                image = axes[0].imshow(db, origin="lower", aspect="auto", extent=extent,
                                       cmap="magma", vmin=-60, vmax=0, interpolation="nearest")
                axes[0].plot(t, context.raw_seed_hz[context.seed_indices]/1e9,
                              color="#d7d7d7", lw=.7, label="wide original STFT")
                axes[0].plot(t, f/1e9, color="#ffa656", lw=.8, alpha=.85, label="candidate")
                axes[0].plot(t, accepted/1e9, color="#54d4f1", lw=1.25, label="supported hypothesis")
                axes[0].set_ylabel("Beat frequency / GHz")
                axes[0].set_ylim(0, 8)
                axes[0].legend(loc="upper left", fontsize=8)
                fig.colorbar(image, ax=axes[0], pad=.01, fraction=.025,
                             label="STFT magnitude / dB re record max")
                axes[1].plot(t, f*WAVELENGTH_M/2, color="#d27c18", lw=.8, alpha=.7,
                              label="candidate")
                axes[1].plot(t, accepted*WAVELENGTH_M/2, color="#16739a", lw=1.2,
                              label="waveform-supported; identity unvalidated")
                axes[1].set_ylabel("Equivalent apparent velocity\n(m/s; assumed 1550 nm)")
                axes[1].legend(loc="upper left", fontsize=8)
                axes[2].plot(t, result["r2"], color="#65557d", lw=.8)
                axes[2].axhline(.2, color="#888888", lw=.8, ls=":")
                axes[2].set_ylim(-.04, 1.04)
                axes[2].set_ylabel("Fit R2 (heuristic)")
                axes[2].set_xlabel("Time from first original sample / ns")
                for ax in axes:
                    ax.grid(alpha=.15)
                    ax.set_xlim(0, (signal.time_s[-1]-start)*1e9)
                    if pd.notna(row.detected_onset_s):
                        ax.axvline((row.detected_onset_s-start)*1e9, color="#2a896a", lw=.9, ls="--")
                domain = "R2 is on nuisance-subtracted voltage" if name == "clutter_varpro" else "R2 is on original voltage"
                fig.suptitle(f"{name} | {signal.name} | REAL DATA: no Ground Truth\n"
                             f"Candidate {row.candidate_coverage:.1%}, supported {row.accepted_coverage:.1%}; "
                             f"{row.total_s:.3f} s; {domain}\n"
                             f"{item['path']} | raw SHA256 {item['sha256'][:16]}...", fontsize=10)
                fig.tight_layout(rect=(0, 0, 1, .91))
                path = OUT/name/"figures/real"/f"{case_id}.png"
                save(fig, path)
                with (p/"trajectory.csv").open("x", encoding="utf-8", newline="") as handle:
                    pd.DataFrame({key: result[key] for key in (
                        "time_s", "frequency_hz", "accepted_hz",
                        "equivalent_apparent_velocity_m_s",
                        "accepted_equivalent_apparent_velocity_m_s", "corrected_velocity_m_s", "flags")}
                                 ).to_csv(handle, index=False)
                manifest.append(dict(method=name, domain="REAL_NO_GT", case_id=case_id,
                                     path=path.relative_to(OUT).as_posix(), selection="ALL_RAW_CHANNELS"))
            print(f"Plotted every method: {signal.name}", flush=True)
    return manifest


def synthetic_plots() -> list[dict[str, Any]]:
    manifest = []
    metrics = pd.read_csv(OUT/"tables/all_fresh_metrics.csv")
    for family in FAMILIES:
        case_id = f"fresh_{family}_00"
        wave = np.load(OUT/"datasets/fresh"/f"{case_id}.npz")
        meta = json.loads((OUT/"datasets/fresh"/f"{case_id}.json").read_text(encoding="utf-8"))
        baseline = np.load(OUT/"gated_stft512/runs/fresh"/case_id/"trajectory.npz")
        for name in METHODS:
            path = OUT/name/"figures/synthetic"/f"{case_id}.png"
            if path.exists():
                manifest.append(dict(method=name, domain="SYNTHETIC_KNOWN_GT", case_id=case_id,
                    path=path.relative_to(OUT).as_posix(), selection="FIRST_REGISTERED_INSTANCE"))
                continue
            result = np.load(run_folder(OUT, name, "fresh", case_id)/"trajectory.npz")
            t = result["time_s"]*1e9
            truth = wave["truth_hz"][result["sample_indices"]]*WAVELENGTH_M/2
            candidate = result["frequency_hz"]*WAVELENGTH_M/2
            accepted = result["accepted_hz"]*WAVELENGTH_M/2
            reference = baseline["frequency_hz"]*WAVELENGTH_M/2
            row = metrics[(metrics.case_id == case_id) & (metrics.method == name)].iloc[0]
            fig, axes = plt.subplots(3, 1, figsize=(10, 8), gridspec_kw={"height_ratios": [2, 1.5, 1]})
            for ax in axes[:2]:
                ax.plot(t, reference, color="#b2b2b2", lw=.9, label="DC + gated STFT512 control")
                ax.plot(t, truth, color="black", lw=1.5, label="generator truth")
                ax.plot(t, candidate, color="#d27c18", lw=.7, alpha=.7, label="candidate")
                ax.plot(t, accepted, color="#16739a", lw=1.1, label="supported hypothesis")
                ax.set_ylabel("Apparent velocity / m/s")
                ax.grid(alpha=.2)
            axes[0].set_xlim(0, 320)
            axes[0].legend(loc="upper left", ncols=2, fontsize=7)
            onset = meta["onset_s"]
            axes[1].set_xlim((onset*1e9-12, onset*1e9+52) if onset is not None else (0, 80))
            axes[1].set_title("Fixed onset neighborhood; no prior-zero fill", fontsize=9)
            axes[2].plot(t, candidate-truth, color="#d27c18", lw=.7, label="candidate error")
            axes[2].plot(t, accepted-truth, color="#16739a", lw=1.1, label="supported error")
            axes[2].axhline(0, color="black", lw=.6)
            axes[2].set_xlim(0, 320)
            axes[2].set_ylabel("Velocity error / m/s")
            axes[2].set_xlabel("Time / ns")
            axes[2].grid(alpha=.2)
            for ax in axes:
                if onset is not None:
                    ax.axvline(onset*1e9, color="black", lw=.8, ls=":")
                if pd.notna(row.detected_onset_s):
                    ax.axvline(row.detected_onset_s*1e9, color="#2a896a", lw=.8, ls="--")
            fig.suptitle(f"{name} | {family} | fixed registered instance 00, seed {meta['seed']}\n"
                         f"Supported coverage {row.accepted_motion_coverage:.1%}; "
                         f"full-denominator failure {row.accepted_motion_failure_fraction:.1%}; "
                         f"onset error {row.onset_error_ns:.3f} ns\n"
                         f"Conditional finite RMSE {row.accepted_motion_rmse_m_s:.3f} m/s; "
                         f"AC cutoff {meta['highpass_cutoff_hz']/1e6:g} MHz", fontsize=10)
            fig.tight_layout(rect=(0, 0, 1, .91))
            path = OUT/name/"figures/synthetic"/f"{case_id}.png"
            save(fig, path)
            manifest.append(dict(method=name, domain="SYNTHETIC_KNOWN_GT", case_id=case_id,
                                 path=path.relative_to(OUT).as_posix(), selection="FIRST_REGISTERED_INSTANCE"))
    return manifest


def overview_plots() -> list[dict[str, Any]]:
    summary = pd.read_csv(OUT/"tables/fresh_summary.csv")
    d = summary[(summary.region == "motion") & (summary.channel == "accepted")
                & (summary.family != "ALL")]
    fig, axes = plt.subplots(1, 3, figsize=(23, 7), layout="constrained")
    for ax, column, title, cmap, scale in zip(axes,
            ("finite_rmse_m_s", "coverage", "failure_fraction"),
            ("Conditional finite RMSE / m/s", "Supported coverage / %", "Failure including missing / %"),
            ("YlOrRd", "viridis", "magma"), (1., 100., 100.), strict=True):
        matrix = d.pivot(index="method", columns="family", values=column).reindex(
            index=METHODS, columns=FAMILIES).to_numpy()*scale
        im = ax.imshow(np.ma.masked_invalid(matrix), cmap=cmap, aspect="auto")
        for i in range(len(METHODS)):
            for j in range(len(FAMILIES)):
                value = matrix[i, j]
                label = "NA" if not np.isfinite(value) else f"{value:.1f}"
                ax.text(j, i, label, ha="center", va="center", fontsize=6,
                        bbox={"facecolor": "white", "alpha": .75, "edgecolor": "none", "pad": .4})
        ax.set_xticks(range(len(FAMILIES)), FAMILIES, rotation=60, ha="right", fontsize=8)
        ax.set_yticks(range(len(METHODS)), METHODS, fontsize=8)
        ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=.03)
    fig.suptitle("96 frozen synthetic waveforms: every family, failures and abstentions retained")
    path = OUT/"figures/synthetic_comparison.png"
    save(fig, path, True)
    manifest = [dict(method="ALL", domain="SYNTHETIC_KNOWN_GT", case_id="ALL_96",
                     path=path.relative_to(OUT).as_posix(), selection="ALL_REGISTERED_WAVEFORMS")]
    phase = pd.read_csv(OUT/"tables/phase_stress_by_velocity.csv")
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
    for name in METHODS:
        s = phase[phase.method == name]
        for ax, column in zip(axes, ("coverage", "accepted_failure_fraction"), strict=True):
            ax.plot(s.specified_velocity_m_s, s[column]*100, "o-", label=name,
                    ms=3, lw=1, color=COLORS[name])
            ax.set_xlabel("Specified target velocity / m/s")
            ax.set_ylim(-3, 103)
            ax.grid(alpha=.2)
    axes[0].set_ylabel("Candidate coverage / %")
    axes[1].set_ylabel("Supported failure incl. missing / %")
    axes[1].legend(fontsize=7, ncols=2)
    fig.suptitle("50 random phases: joint low-speed / AC-cutoff / SNR stress; 10 waveforms per speed")
    path = OUT/"figures/low_speed_phase_stress.png"
    save(fig, path, True)
    manifest.append(dict(method="ALL", domain="SYNTHETIC_KNOWN_GT", case_id="PHASE_50",
                         path=path.relative_to(OUT).as_posix(), selection="ALL_REGISTERED_WAVEFORMS"))
    return manifest


def main() -> None:
    manifest = real_plots()+synthetic_plots()+overview_plots()
    write_csv(OUT/"figure_manifest.csv", manifest)
    write_json(OUT/"checks/figure_counts.json", dict(real=17*len(METHODS),
        synthetic_fixed=len(FAMILIES)*len(METHODS), overview=2, manifest_rows=len(manifest)))
    print(f"Saved {len(manifest)} PNG figures and two SVG overviews under {ROOT}", flush=True)


if __name__ == "__main__":
    main()
