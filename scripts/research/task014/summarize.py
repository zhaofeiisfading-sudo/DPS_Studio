"""Aggregate truth-bearing cases and full-record observations separately."""
import argparse
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[3] / "artifacts/TASK-014"
METHODS = ["stft768", "simple_map", "low_refined_map", "clip_stft2048", "profile2048", "one_peak"]
LABELS = ["Original STFT", "Simple map", "Refined map", "Matched FFT", "Two peaks", "One peak"]


def summarize() -> None:
    data = pd.read_csv(OUT / "synthetic.csv")
    all_cases = data.query("kind == 'supported' and region == 'all' and method in @METHODS")
    rows = []
    for population, frame in (("all", all_cases), ("low", all_cases.query("family == 'low_plateau'"))):
        for name, g in frame.groupby("method"):
            n = g.target_n.sum()
            rows.append(dict(population=population, method=name, cases=len(g),
                             rmse=np.sqrt(g.sse_m2_s2.sum()/g.finite_n.sum()),
                             coverage=100*g.finite_n.sum()/n, failure=100*g.failure_n.sum()/n,
                             wrong=g.wrong_branch_n.sum(), eligible=g.branch_eligible_n.sum(),
                             branch_missing=g.branch_missing_n.sum(), onset_mae=g.onset_abs_error_ns.mean(),
                             onset_missed=g.onset_missed.sum(), onset_eligible=g.onset_eligible.sum(),
                             cost_ms=g.runtime_s.mean()*1e3))
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT / "summary.csv", index=False)
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "font.size": 9, "axes.labelsize": 9, "font.family": "DejaVu Sans"})
    low = summary.query("population == 'low'").set_index("method").loc[METHODS[3:]]
    fig, axes = plt.subplots(1, 3, figsize=(8, 2.8), layout="constrained")
    for ax, field, label in zip(axes, ["rmse", "coverage", "cost_ms"],
                                ["Supported RMSE (m/s)", "Target coverage (%)", "Cost (ms / record)"],
                                strict=True):
        ax.bar(range(3), low[field], color=["#777777", "#0072B2", "#D55E00"])
        ax.set_xticks(range(3), LABELS[3:], rotation=25, ha="right")
        ax.set_ylabel(label)
        ax.set_ylim(0, low[field].max()*1.20)
        ax.bar_label(ax.containers[0], fmt="%.2f", fontsize=8)
    fig.savefig(OUT / "figures/low_plateau.png", dpi=400)
    plt.close(fig)
    real = pd.read_csv(OUT / "real.csv")
    fig, axes = plt.subplots(1, 2, figsize=(8, 4.8), layout="constrained", sharey=True)
    for method, color, marker in zip(["stft768", "clip_stft2048", "one_peak"],
                                     ["#777777", "#0072B2", "#D55E00"], ["o", "+", "x"], strict=True):
        g = real.query("method == @method")
        axes[0].scatter(100*g.finite/g.centers, g.channel, color=color, marker=marker, label=method)
        axes[1].scatter(g.disagreement_100MHz, g.channel, color=color, marker=marker)
    axes[0].set_xlabel("Finite estimates (% of centers)")
    axes[1].set_xlabel("Paired differences >100 MHz (count)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.savefig(OUT / "figures/real_frequency.png", dpi=400)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    requested = parser.parse_args().run.resolve()
    if not requested.is_dir() or not requested.is_relative_to(OUT.resolve()):
        parser.error("Choose an existing TASK-014 run")
    OUT = requested
    (OUT / "figures").mkdir(exist_ok=False)
    summarize()
