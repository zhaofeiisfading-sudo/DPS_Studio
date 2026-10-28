"""Score TASK007 without hiding rejected frames, and save standalone figures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.research.bandwidth_task007_simulation import (
    Acquisition, regularized_inverse_gain, transfer,
)

METHODS = ("STFT_peak", "Research_P3", "VP_tone", "VP_chirp")
COLORS = ("#777777", "#D55E00", "#0072B2", "#009E73")


def scores(frame: Any) -> dict[str, Any]:
    finite = np.isfinite(frame.frequency_hz.to_numpy())
    signal = ~frame.no_signal.to_numpy(dtype=bool)
    comparable = finite & signal
    error = abs(frame.frequency_hz.to_numpy() - frame.truth_hz.to_numpy())
    good = comparable & (error <= frame.tolerance_hz.to_numpy())
    wrong = comparable & ~good
    absent = ~signal
    above = signal & (frame.truth_hz.to_numpy() > frame.bandwidth_hz.to_numpy())
    sigma = frame.sigma_hz.to_numpy()
    ci = comparable & np.isfinite(sigma) & (sigma > 0)
    penalty = np.where(finite, error, frame.fs_hz.to_numpy() / 2)

    def fraction(numerator: Any, denominator: Any) -> float:
        return float(np.sum(numerator) / np.sum(denominator)) if np.sum(denominator) else np.nan

    def rmse(values: Any) -> float:
        return float(np.sqrt(np.mean(values**2))) if len(values) else np.nan

    frequency_rmse = rmse(error[comparable])
    frequency_mae = float(np.mean(error[comparable])) if np.any(comparable) else np.nan
    return dict(frames=len(frame), independent_records=int(frame.case_id.nunique()),
                signal_frames=int(signal.sum()), no_signal_frames=int(absent.sum()),
                returned_frames=int(finite.sum()), wrong_frames=int(wrong.sum()),
                false_recovery_frames=int((finite & absent).sum()),
                coverage=float(np.mean(finite)),
                signal_coverage=fraction(comparable, signal),
                correct_all_signal=fraction(good, signal),
                wrong_branch_all_signal=fraction(wrong, signal),
                wrong_branch_returned=fraction(wrong, comparable),
                failure_including_rejection=fraction(signal & ~good, signal),
                false_recovery_rate=fraction(finite & absent, absent),
                beyond_bandwidth_identification=fraction(good & above, above),
                frequency_rmse_hz=frequency_rmse, frequency_mae_hz=frequency_mae,
                velocity_rmse_m_s=frequency_rmse * 1550e-9 / 2,
                velocity_mae_m_s=frequency_mae * 1550e-9 / 2,
                penalized_rmse_hz=rmse(penalty[signal]),
                ci95_coverage=fraction(ci & (error <= 1.96 * sigma), ci),
                ci_frames=int(ci.sum()),
                standardized_error_rms=rmse(error[ci] / sigma[ci]))


def save(fig: Any, root: Path, name: str) -> None:
    fig.savefig(root / f"{name}.png", dpi=180, bbox_inches="tight")
    fig.savefig(root / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def evaluate(root: Path) -> None:
    output = root / "evaluation"
    output.mkdir(exist_ok=False)
    figures = output / "figures"
    figures.mkdir()
    frame = pd.read_csv(root / "output/frames.csv")
    summary = []
    groups = dict(all=frame, tone_scan=frame[frame.family == "tone_scan"],
                  subnyquist_tone=frame[(frame.family == "tone_scan") & ~frame.alias_ambiguous],
                  alias_ambiguous=frame[frame.alias_ambiguous],
                  strict_null=frame[frame.no_signal],
                  strong_attenuation=frame[frame.family == "strong_attenuation"])
    for family in frame.family.unique():
        groups.setdefault(family, frame[frame.family == family])
    for name, group in groups.items():
        for method, subset in group.groupby("method"):
            summary.append(dict(group=name, method=method, **scores(subset)))
    pd.DataFrame(summary).to_csv(output / "summary.csv", index=False)
    cells = []
    scan = frame[frame.family == "tone_scan"]
    for keys, subset in scan.groupby(["order", "fs_hz", "snr_pre_db", "ratio_nominal", "method"]):
        order, fs, snr, ratio, method = keys
        cells.append(dict(order=order, fs_hz=fs, snr_pre_db=snr, ratio_nominal=ratio,
                          method=method, **scores(subset)))
    table = pd.DataFrame(cells)
    table.to_csv(output / "scan_cells.csv", index=False)
    per_case = []
    for (case, method), subset in frame.groupby(["case_id", "method"]):
        per_case.append(dict(case_id=case, family=subset.family.iloc[0], method=method,
                             **scores(subset)))
    case_table = pd.DataFrame(per_case)
    case_table.to_csv(output / "per_case.csv", index=False)
    rng = np.random.default_rng(77001)
    intervals = []
    for group in ("subnyquist_tone", "strict_null", "fast_chirp", "competitor"):
        ids = groups[group].case_id.unique()
        for method in METHODS:
            subset = case_table[(case_table.case_id.isin(ids)) & (case_table.method == method)]
            for metric in ("correct_all_signal", "coverage", "false_recovery_rate"):
                values = subset[metric].dropna().to_numpy()
                if len(values) < 2:
                    continue
                means = np.mean(rng.choice(values, size=(2000, len(values))), axis=1)
                low, high = np.quantile(means, [.025, .975])
                intervals.append(dict(group=group, method=method, metric=metric,
                    records=len(values), mean=float(values.mean()), low=float(low), high=float(high),
                    caveat="record bootstrap; grid mixture, two replicates/cell; zero events degenerate"))
    pd.DataFrame(intervals).to_csv(output / "record_bootstrap.csv", index=False)
    flags = frame.groupby(["method", "flag"]).size().reset_index(name="frames")
    flags.to_csv(output / "flags.csv", index=False)
    registration = json.loads((root / "output/registration.json").read_text(encoding="utf-8"))
    times = []
    for method in ("shared_frontend", *METHODS):
        values = [r[f"{method}_s"] for r in registration]
        times.append(dict(component=method, total_s=sum(values), median_s=float(np.median(values)),
                          records=len(values), note="wall clock; candidate frontend shared; no plotting"))
    pd.DataFrame(times).to_csv(output / "runtime.csv", index=False)

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True, sharey=True)
    for ax, method in zip(axes.flat, METHODS, strict=True):
        sel = table[(table.order == 4) & (table.fs_hz == 32e9) & (table.method == method)]
        grid = sel.pivot(index="snr_pre_db", columns="ratio_nominal", values="correct_all_signal")
        image = ax.imshow(grid.to_numpy(), origin="lower", aspect="auto", vmin=0, vmax=1,
                          cmap="viridis")
        ax.set_xticks(range(len(grid.columns)), [str(v) for v in grid.columns])
        ax.set_yticks(range(len(grid.index)), [str(int(v)) for v in grid.index])
        ax.set_title(method)
        ax.set_xlabel("Nominal f / B (dimensionless)")
        ax.set_ylabel("Unattenuated tone / output noise (dB)")
    fig.colorbar(image, ax=list(axes.flat), label="Correct / all signal frames (NaN is failure)",
                 fraction=.03, pad=.03)
    fig.suptitle("Synthetic detection boundary | B=2 GHz, 4-pole analog H, Fs=32 GS/s\n"
                 "N=256, 10-bit ADC, 2 independent records/cell; no measured hardware calibration")
    fig.subplots_adjust(top=.85, hspace=.35, wspace=.25, right=.86)
    save(fig, figures, "01_detection_boundary")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    for method, color in zip(METHODS, COLORS, strict=True):
        sel = table[(table.order == 4) & (table.fs_hz == 32e9)
                    & (table.snr_pre_db == 20) & (table.method == method)]
        axes[0].plot(sel.ratio_nominal, sel.frequency_rmse_hz / 1e6, "o-", color=color, label=method)
        axes[1].plot(sel.ratio_nominal, sel.signal_coverage, "o-", color=color)
        axes[2].plot(sel.ratio_nominal, sel.penalized_rmse_hz / 1e9, "o-", color=color)
    axes[0].set_yscale("log")
    for ax, ylabel in zip(axes, ("Returned-frame RMSE (MHz)", "Coverage (fraction)",
                               "Missing-penalized RMSE (GHz)"), strict=True):
        ax.set_xlabel("Nominal f / B")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    fig.suptitle("Synthetic | B=2 GHz, order=4, Fs=32 GS/s, pre-attenuation SNR=20 dB\n"
                 "Missing estimate penalty=Fs/2; finite-only RMSE must be read with coverage")
    fig.tight_layout()
    save(fig, figures, "02_error_and_coverage")

    selected = ("scan_0001", "stress_0321", "stress_0329", "stress_0337")
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    for ax, case in zip(axes.flat, selected, strict=True):
        sel = frame[frame.case_id == case]
        truth = sel[sel.method == "STFT_peak"]
        ax.plot(truth.time_s * 1e9, truth.truth_hz / 1e9, "k--", linewidth=2,
                label="Generator truth (not estimator input)")
        for method, color in zip(METHODS, COLORS, strict=True):
            rows = sel[sel.method == method]
            ax.plot(rows.time_s * 1e9, rows.frequency_hz / 1e9, ".-", color=color,
                    label=f"{method} ({int(np.isfinite(rows.frequency_hz).sum())}/{len(rows)})")
        ax.set_title(f"{case}: {sel.family.iloc[0]}")
        ax.set_xlabel("Time (ns)")
        ax.set_ylabel("Beat frequency (GHz)")
        ax.legend(fontsize=6)
    fig.suptitle("Synthetic waveform-based estimates | B=2 GHz, Fs=16 GS/s, N=256\n"
                 "Dashed=truth, solid/points=returned estimates; rejected intervals remain gaps")
    fig.tight_layout()
    save(fig, figures, "03_trajectories_and_failure")

    axis = np.linspace(0, 16e9, 2049)
    cfg = Acquisition(32e9, 2e9, 4, 20., 10, 4., 8)
    response = transfer(axis, cfg)
    rows = []
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(axis / 1e9, 20 * np.log10(abs(response)), label="Synthetic order-4 H")
    for assumed_ratio in (.8, 1., 1.2):
        assumed = transfer(axis, Acquisition(32e9, 2e9 * assumed_ratio, 4, 20., 10, 4., 8))
        gain = regularized_inverse_gain(assumed, .001)
        axes[1].plot(axis / 1e9, abs(gain), label=f"Assumed B / true B={assumed_ratio}")
        for f, h, g in zip(axis, response, gain, strict=True):
            rows.append(dict(frequency_hz=f, assumed_bandwidth_ratio=assumed_ratio,
                actual_h_abs=abs(h), inverse_gain_abs=abs(g), reconstructed_signal_gain=abs(g * h),
                output_noise_psd_multiplier=abs(g)**2,
                frequency_bin_snr_multiplier=1. if abs(g) > 0 else np.nan))
    pd.DataFrame(rows).to_csv(output / "inverse_diagnostic.csv", index=False)
    axes[0].set_ylabel("Amplitude response (dB)")
    axes[1].set_ylabel("Regularized inverse amplitude gain")
    for ax in axes:
        ax.set_xlabel("Frequency (GHz)")
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    fig.suptitle("Synthetic response diagnostic | B=2 GHz; H* / (|H|² + 0.001)\n"
                 "Signal and output noise are amplified together; zero response stays zero")
    fig.tight_layout()
    save(fig, figures, "04_transfer_and_inverse_noise")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, case in zip(axes, ("scan_0161", "stress_0337"), strict=True):
        data = np.load(root / "data" / f"{case}.npz")
        voltage = data["voltage_v"][:256]
        t = data["time_s"]
        freq = np.fft.rfftfreq(256, t[1] - t[0])
        power = abs(np.fft.rfft(voltage * np.hanning(256)))**2
        ax.plot(freq / 1e9, 10 * np.log10(np.maximum(power / power.max(), 1e-15)))
        ax.axvline(2., color="gray", linestyle=":", label="Synthetic B=2 GHz")
        ax.axvline(data["truth_hz"][128] / 1e9, color="black", linestyle="--", label="Truth")
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel("Relative windowed power (dB)")
        ax.set_title(case + (" | exact zero H" if "stress" in case else " | order 4, SNR=-10 dB"))
        ax.legend(fontsize=8)
    fig.suptitle("Synthetic raw digital spectra | Fs=16 GS/s, N=256; no compensation")
    fig.tight_layout()
    save(fig, figures, "05_raw_spectra")

    real = pd.read_csv(root / "output/real_frames.csv")
    real_summary = []
    for keys, group in real.groupby(["case_id", "window_samples"]):
        name, size = keys
        pivot = group.pivot(index="time_s", columns="method", values="frequency_hz")
        for method in METHODS:
            finite = np.isfinite(pivot[method])
            pair = finite & np.isfinite(pivot.STFT_peak)
            delta = pivot[method].diff().abs()
            real_summary.append(dict(case_id=name, window_samples=size, method=method,
                frames=len(pivot), coverage=float(finite.mean()),
                median_frequency_hz=float(pivot[method].median()),
                median_absolute_difference_vs_STFT_hz=float(
                    (pivot.loc[pair, method] - pivot.loc[pair, "STFT_peak"]).abs().median()),
                adjacent_jumps_over_200MHz=int((delta > 200e6).sum()),
                comparable_adjacent_pairs=int(delta.notna().sum()),
                status="OBSERVATIONAL_ONLY; bandwidth/identity/velocity truth UNKNOWN"))
    pd.DataFrame(real_summary).to_csv(output / "real_summary.csv", index=False)
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    for ax, name in zip(axes.flat, real.case_id.unique(), strict=True):
        group = real[(real.case_id == name) & (real.window_samples == 256)]
        for method, color in zip(METHODS, COLORS, strict=True):
            subset = group[group.method == method]
            ax.plot(subset.time_relative_s * 1e9, subset.frequency_hz / 1e9, ".", markersize=3,
                    color=color, label=method)
        ax.set_title(f"{name}: {group.source.iloc[0]}, column {group.channel_column.iloc[0]}")
        ax.set_xlabel("Time from file start (ns)")
        ax.set_ylabel("Candidate beat frequency (GHz)")
        ax.legend(fontsize=7)
    fig.suptitle("REAL RAW | N=256, full interior Nyquist search; no independent truth\n"
                 "Analog bandwidth UNKNOWN: these plots cannot demonstrate beyond-bandwidth recovery")
    fig.tight_layout()
    save(fig, figures, "06_real_observations")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.run)


if __name__ == "__main__":
    main()
