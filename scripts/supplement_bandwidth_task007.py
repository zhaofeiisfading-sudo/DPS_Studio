"""Additional fair gated-STFT baseline and diagnostic analyses; no prototype retuning."""
from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.core.quality.detection import detect_beat_signal
from dps_studio.core.quality.models import SignalDetectionConfig, SignalState
from dps_studio.core.ridge.peak import extract_peak_ridge
from dps_studio.core.ridge.refinement import refine_peak_ridge_subbin
from dps_studio.core.ridge.spectral_quality import assess_ridge_spectral_quality
from dps_studio.core.time_frequency import compute_stft
from dps_studio.research.bandwidth_task007_simulation import simulate
from evaluate_bandwidth_task007 import scores, save
from run_bandwidth_task007 import synthetic_cases, ROOT


def gated_stft(record: SignalRecord) -> tuple[np.ndarray[Any, np.dtype[np.float64]], list[str]]:
    stft = compute_stft(record, window_length_samples=256, overlap_samples=128, nfft=512)
    fs = record.sample_rate_hz
    ridge = extract_peak_ridge(stft, minimum_frequency_hz=2 * fs / 256,
                              maximum_frequency_hz=fs / 2 - 2 * fs / 256)
    refined = refine_peak_ridge_subbin(stft, ridge)
    cfg = SignalDetectionConfig()
    quality = assess_ridge_spectral_quality(stft, refined,
        background_exclusion_half_width_hz=cfg.peak_exclusion_half_width_bins * fs / 512,
        minimum_background_bin_count=8)
    detected = detect_beat_signal(stft, refined, quality, detection_config=cfg,
                                  vacuum_wavelength_m=1550e-9)
    frequency = np.array(refined.refined_frequency_hz)
    good = np.array([state == SignalState.MEASURED for state in detected.signal_states])
    frequency[~good] = np.nan
    return frequency, [state.value for state in detected.signal_states]


def supplement(root: Path) -> None:
    out = root / "supplement"
    out.mkdir(exist_ok=False)
    frame = pd.read_csv(root / "output/frames.csv")
    rows = []
    start = perf_counter()
    for case in synthetic_cases():
        cfg = case["acquisition"]
        options = {k: v for k, v in case.items() if k in (
            "frequency_hz", "chirp_hz_per_s", "seed", "competitor_ratio",
            "target_present", "colored_noise")}
        generated = simulate(cfg, **options)
        frequency, flags = gated_stft(SignalRecord(generated.time_s, generated.voltage_v))
        baseline = frame[(frame.case_id == case["case_id"]) & (frame.method == "STFT_peak")].copy()
        baseline["method"] = "Existing_STFT_quality"
        baseline["frequency_hz"] = frequency
        baseline["flag"] = flags
        baseline["apparent_velocity_m_s"] = frequency * 1550e-9 / 2
        rows.append(baseline)
    gated = pd.concat(rows, ignore_index=True)
    gated.to_csv(out / "gated_baseline_frames.csv", index=False)
    with (out / "gated_runtime.txt").open("x", encoding="utf-8") as stream:
        stream.write(f"Regeneration + gated baseline all 384 cases: {perf_counter() - start:.6f} s\n")
    merged = pd.concat([frame, gated], ignore_index=True)
    summary = []
    for name, subset in {
        "all": merged,
        "subnyquist_tone": merged[(merged.family == "tone_scan") & ~merged.alias_ambiguous],
        "strict_null": merged[merged.no_signal],
        "fast_chirp": merged[merged.family == "fast_chirp"],
        "competitor": merged[merged.family == "competitor"],
        "alias_ambiguous": merged[merged.alias_ambiguous],
    }.items():
        for method, group in subset.groupby("method"):
            summary.append(dict(group=name, method=method, **scores(group)))
    pd.DataFrame(summary).to_csv(out / "five_method_summary.csv", index=False)
    # Same accepted frames for precision comparison; explicit selection, not detection evidence.
    matched = []
    tone = frame[(frame.family == "tone_scan") & ~frame.alias_ambiguous]
    pivot = tone.pivot(index=["case_id", "frame"], columns="method", values="frequency_hz")
    truth = tone[tone.method == "VP_tone"].set_index(["case_id", "frame"])
    accepted = np.isfinite(pivot.VP_tone)
    for method in pivot.columns:
        delta = (pivot.loc[accepted, method] - truth.loc[accepted, "truth_hz"]).to_numpy()
        matched.append(dict(method=method, frames=int(accepted.sum()), total=len(pivot),
                            frequency_rmse_hz=float(np.sqrt(np.nanmean(delta**2))),
                            frequency_mae_hz=float(np.nanmean(abs(delta))),
                            selection="VP_tone accepted subnyquist tones; conditional precision only"))
    pd.DataFrame(matched).to_csv(out / "matched_frame_precision.csv", index=False)

    real = pd.read_csv(root / "output/real_frames.csv")
    candidate = []
    sensitivity = []
    for (name, size, method), subset in real[real.method.str.startswith("VP")].groupby(
            ["case_id", "window_samples", "method"]):
        candidate.append(dict(case_id=name, size=size, method=method,
            frames=len(subset), median_candidate_hz=float(subset.candidate_frequency_hz.median()),
            median_lag1=float(subset.residual_lag1.median()),
            median_detection_score=float(subset.detection_score.median()),
            median_residual_peak_score=float(subset.residual_peak_score.median()),
            coverage=float(subset.frequency_hz.notna().mean()),
            caveat="Rejected candidates are not recovered measurements"))
        for correlation_limit in (.2, .3, .5, .8):
            retained = ((subset.detection_score >= 14) & (subset.residual_peak_score <= 14)
                        & (abs(subset.residual_lag1) <= correlation_limit)
                        & ~subset.flag.str.contains("OPTIMIZER_FAILED|SEARCH_BOUNDARY|ILL_CONDITIONED"))
            sensitivity.append(dict(case_id=name, size=size, method=method,
                                    residual_correlation_limit=correlation_limit,
                                    accepted_fraction=float(retained.mean()),
                                    status="post-run sensitivity only; no new accepted output"))
    pd.DataFrame(candidate).to_csv(out / "real_candidate_diagnostics.csv", index=False)
    pd.DataFrame(sensitivity).to_csv(out / "real_gate_sensitivity.csv", index=False)

    # A deliberately exposed low-SNR catastrophic chirp basin, not removed as an outlier.
    failed = frame[(frame.family == "tone_scan") & ~frame.alias_ambiguous
                   & (frame.method == "VP_chirp")
                   & (abs(frame.frequency_hz - frame.truth_hz) > frame.tolerance_hz)]
    failed.to_csv(out / "catastrophic_accepted_chirp.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, name in zip(axes, ("normal_high", "weak_late"), strict=True):
        group = real[(real.case_id == name) & (real.window_samples == 256)]
        for method, color in (("Research_P3", "#D55E00"), ("VP_tone", "#0072B2"),
                              ("VP_chirp", "#009E73")):
            sub = group[group.method == method]
            ax.scatter(sub.time_relative_s * 1e9, sub.candidate_frequency_hz / 1e9,
                       s=10, facecolors="none", edgecolors=color, label=method + " candidate")
        ax.set_title(name + " | all VP estimates rejected")
        ax.set_xlabel("Time from file start (ns)")
        ax.set_ylabel("Candidate frequency (GHz)")
        ax.legend(fontsize=7)
    fig.suptitle("REAL | N=256 | Hollow markers are unvalidated candidates, not measurements\n"
                 "Noise correlation/model mismatch prevents calibrated frequency/velocity claims")
    fig.tight_layout()
    save(fig, out, "07_rejected_real_candidates")
    # Representative waveform and residual at a fixed central frame, no best-frame selection.
    data = np.loadtxt(ROOT / "data/raw/20221017a.dat", delimiter=",")
    t = data[:, 0] - data[0, 0]
    raw = data[(t >= 280e-9) & (t <= 680e-9), 1]
    selected = real[(real.case_id == "normal_high") & (real.window_samples == 256)
                    & (real.method == "VP_tone")].iloc[62]
    y = raw[62 * 256:63 * 256]
    fs = 1 / np.median(np.diff(data[:, 0]))
    local = (np.arange(256) - 128) / fs
    phase = 2 * np.pi * selected.candidate_frequency_hz * local
    design = np.column_stack([np.cos(phase), np.sin(phase), np.ones(256)])
    fitted = design @ np.linalg.lstsq(design, y, rcond=None)[0]
    fig, axes = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    axes[0].plot(local * 1e9, y, label="Observed voltage", linewidth=1)
    axes[0].plot(local * 1e9, fitted, label="Rejected local tone fit", linewidth=1)
    axes[0].set_ylabel("Voltage (V)")
    axes[0].legend()
    axes[1].plot(local * 1e9, y - fitted, color="#777777")
    axes[1].set_ylabel("Residual (V)")
    axes[1].set_xlabel("Local time from window center (ns)")
    fig.suptitle("REAL 20221017a.dat, voltage column 1, fixed frame 62; N=256\n"
                 "A visible carrier does not validate the iid-noise residual model")
    fig.tight_layout()
    save(fig, out, "08_real_waveform_residual")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    supplement(parser.parse_args().run)
