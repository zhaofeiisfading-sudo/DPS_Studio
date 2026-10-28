"""Reproducible TASK-001 experiment. Use bandwidth_env.ps1 before execution."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib
import numpy as np
from scipy import signal, stats  # type: ignore[import-untyped]

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.research.bandwidth_task001 import (  # noqa: E402
    AnalogCase, FloatArray, NoiseModel, ToneSearch, ar_transform, checked_input,
    empirical_threshold, local_model_residual, residual_diagnostics,
    spectral_baselines, stationary_noise, synthesize, train_noise,
)

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("stft_peak", "stft_gate", "iid_glrt", "ar1_glrt")
FS = 20e9
BANDWIDTH = 3e9
ALPHA = 0.01
NOISE_RMS = 0.035
SEEDS = {"training": 11001, "null_calibration": 22001, "interval_calibration": 33001,
         "test": 44001, "diagnostics": 55001, "bootstrap": 66001}


def write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        write_text(path, "")
        return
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_output(path: Path) -> Path:
    resolved = path.resolve()
    allowed = ROOT / "results" / "task001_bandwidth"
    if not resolved.is_relative_to(allowed) or not allowed.resolve().is_relative_to(ROOT):
        raise ValueError("Output must stay in results/task001_bandwidth; junctions checked")
    parent = resolved
    while not parent.exists():
        parent = parent.parent
    if not parent.resolve().is_relative_to(ROOT):
        raise ValueError("Output ancestor resolves outside worktree")
    if resolved.exists():
        raise FileExistsError("Use a new run_id; existing results are never overwritten")
    resolved.mkdir(parents=True)
    return resolved


def setup_models(
    out: Path, calibration_count: int, interval_count: int,
) -> tuple[dict[tuple[int, float, str], ToneSearch], dict[tuple[int, float, str], float],
           dict[tuple[int, float, str], float]]:
    searches: dict[tuple[int, float, str], ToneSearch] = {}
    thresholds: dict[tuple[int, float, str], float] = {}
    scales: dict[tuple[int, float, str], float] = {}
    rows: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    frozen: dict[str, Any] = {}
    train_arrays: dict[str, FloatArray] = {}
    for noise_index, rho in enumerate((0., 0.85)):
        rng = np.random.default_rng(SEEDS["training"] + noise_index)
        training = np.array([stationary_noise(rng, 2048, NOISE_RMS, rho) for _ in range(64)])
        fitted = train_noise(training)
        iid = NoiseModel(0., float(np.std(training)))
        train_arrays[str(rho)] = training
        frozen[str(rho)] = {"ar1": asdict(fitted), "iid": asdict(iid)}
        for n in (256, 512):
            print(f"Calibration rho={rho} N={n}", flush=True)
            for name, model in (("iid_glrt", iid), ("ar1_glrt", fitted)):
                searches[n, rho, name] = ToneSearch(n, FS, model)
            scores: dict[str, list[float]] = {m: [] for m in METHODS[1:]}
            for i in range(calibration_count):
                seed = SEEDS["null_calibration"] + noise_index * 100000 + n * 1000 + i
                y = synthesize(AnalogCase(n=n, amplitude_v=0, noise_rho=rho), seed).voltage_v
                scores["stft_gate"].append(spectral_baselines(y, FS).gate_statistic_db)
                for m in METHODS[2:]:
                    scores[m].append(searches[n, rho, m].fit(y).score)
                rows.append({"n": n, "rho": rho, "seed": seed,
                             **{m: scores[m][-1] for m in scores}})
            for m, values in scores.items():
                thresholds[n, rho, m] = empirical_threshold(np.array(values), ALPHA)
            # Independent signal calibration only; no test labels. Store all
            # failures. Interval factors are conditional on accepted single-tone
            # calibration mixtures, never validated for chirp/branches/real data.
            ratios: dict[str, list[float]] = {m: [] for m in METHODS[2:]}
            rng_ci = np.random.default_rng(SEEDS["interval_calibration"] + n + noise_index)
            for i in range(interval_count):
                f = float(rng_ci.uniform(0.35e9, 9e9))
                amplitude = float(rng_ci.uniform(0.04, 0.14))
                seed = SEEDS["interval_calibration"] + noise_index * 100000 + n * 1000 + i
                case = AnalogCase(n=n, frequency_hz=f, amplitude_v=amplitude, noise_rho=rho,
                                  order=1 if i % 2 else 4)
                y = synthesize(case, seed).voltage_v
                for m in METHODS[2:]:
                    fit = searches[n, rho, m].fit(y)
                    accepted = fit.score > thresholds[n, rho, m]
                    standardized = abs(fit.frequency_hz - f) / fit.nominal_sigma_hz
                    if accepted:
                        ratios[m].append(standardized)
                    interval_rows.append({"n": n, "rho": rho, "seed": seed, "method": m,
                                          "frequency_hz": f, "accepted": accepted,
                                          "standardized_error": standardized})
            for m in METHODS[2:]:
                # At least 20 independently accepted waveforms are required.
                interval_values = np.asarray(ratios[m])
                factor = (empirical_threshold(interval_values, 0.05)
                          if len(interval_values) >= 20 else math.inf)
                scales[n, rho, m] = max(1.96, factor)
    # Infinity is preserved explicitly as text in JSON, not silently replaced.
    config = {"noise_models": frozen,
              "thresholds": {str(k): v if math.isfinite(v) else "INF" for k, v in thresholds.items()},
              "interval_scale": {str(k): v if math.isfinite(v) else "INF" for k, v in scales.items()}}
    write_json(out / "frozen_calibration.json", config)
    write_csv(out / "null_calibration.csv", rows)
    write_csv(out / "interval_calibration.csv", interval_rows)
    np.savez_compressed(out / "noise_training.npz", **dict[str, Any](train_arrays))
    return searches, thresholds, scales


def make_cases(repetitions: int, null_count: int) -> list[tuple[str, AnalogCase, int, bool]]:
    cases: list[tuple[str, AnalogCase, int, bool]] = []
    counter = 0
    for n in (256, 512):
        for rho in (0., 0.85):
            for order in (1, 4):
                for amplitude in (0.04, 0.12):
                    for ratio in (0.25, 1., 1.6, 2.6):
                        for _ in range(repetitions):
                            case = AnalogCase(n=n, noise_rho=rho, order=order,
                                              amplitude_v=amplitude, frequency_hz=ratio * BANDWIDTH)
                            cases.append(("tone", case, SEEDS["test"] + counter, True))
                            counter += 1
            for _ in range(null_count):
                cases.append(("null", AnalogCase(n=n, noise_rho=rho, amplitude_v=0),
                              SEEDS["test"] + counter, False))
                counter += 1
            special = {
                "fast_chirp": AnalogCase(n=n, noise_rho=rho, chirp_hz_per_s=8e16),
                "am": AnalogCase(n=n, noise_rho=rho, am_depth=0.9),
                "phase_modulation": AnalogCase(n=n, noise_rho=rho, phase_mod_rad=1.5),
                "competitor": AnalogCase(n=n, noise_rho=rho, competitor_hz=1.5e9,
                                         competitor_amplitude_v=0.15),
                "H_zero": AnalogCase(n=n, noise_rho=rho, response_zero=True),
                "quantization_erasure": AnalogCase(n=n, noise_rho=rho, amplitude_v=0.0002,
                                                    noise_rms_v=0., adc_step_v=0.002),
                "alias": AnalogCase(n=n, noise_rho=rho, frequency_hz=13e9, amplitude_v=0.25),
                "noise_shift": AnalogCase(n=n, noise_rho=0.2 if rho else 0.97, amplitude_v=0.),
                "coherent_interference": AnalogCase(n=n, noise_rho=rho, amplitude_v=0.,
                                                    competitor_hz=1.5e9,
                                                    competitor_amplitude_v=0.12),
            }
            for name, case in special.items():
                observable = name in {"fast_chirp", "am", "phase_modulation", "competitor"}
                for _ in range(24):
                    cases.append((name, case, SEEDS["test"] + counter, observable))
                    counter += 1
    return cases


def evaluate(
    out: Path, cases: list[tuple[str, AnalogCase, int, bool]],
    searches: dict[tuple[int, float, str], ToneSearch],
    thresholds: dict[tuple[int, float, str], float],
    scales: dict[tuple[int, float, str], float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    arrays = np.full((len(cases), 512), np.nan)
    for index, (name, case, seed, observable) in enumerate(cases):
        if index % 500 == 0:
            print(f"Held-out waveforms {index}/{len(cases)}", flush=True)
        w = synthesize(case, seed)
        arrays[index, :case.n] = w.voltage_v
        # Noise-shift cases deliberately keep the original model assignment.
        group_rho = (0.85 if case.noise_rho == 0.2 else 0. if case.noise_rho == 0.97
                     else case.noise_rho)
        start = perf_counter()
        baseline = spectral_baselines(w.voltage_v, FS)
        baseline_time = perf_counter() - start
        for m in METHODS:
            sigma = interval = math.nan
            if m.startswith("stft"):
                candidate = baseline.peak_hz if m == "stft_peak" else baseline.refined_hz
                score = baseline.gate_statistic_db
                accepted = m == "stft_peak" or score > thresholds[case.n, group_rho, m]
                accepted = accepted and math.isfinite(candidate)
                elapsed = baseline_time
            else:
                start = perf_counter()
                fit = searches[case.n, group_rho, m].fit(w.voltage_v)
                elapsed = perf_counter() - start
                candidate, score, sigma = fit.frequency_hz, fit.score, fit.nominal_sigma_hz
                accepted = score > thresholds[case.n, group_rho, m]
                interval = scales[case.n, group_rho, m] * sigma
            # Frequency truth is analog carrier at midpoint, not inferred from
            # the winning component. Aliases cannot validate that physical truth.
            error = candidate - w.analog_frequency_hz
            tolerance = FS / case.n / 4
            correct = bool(accepted and observable and abs(error) <= tolerance)
            competitor_alias = abs((case.competitor_hz + FS / 2) % FS - FS / 2)
            wrong_branch = bool(accepted and name == "competitor"
                                and abs(candidate - competitor_alias) <= tolerance)
            rows.append({
                "waveform_id": index, "seed": seed, "case": name, "method": m,
                "n": case.n, "noise_group_rho": group_rho, "actual_noise_rho": case.noise_rho,
                "order": case.order, "amplitude_v": case.amplitude_v,
                "bandwidth_hz": BANDWIDTH, "sample_rate_hz": FS,
                "analog_truth_hz": w.analog_frequency_hz,
                "digital_alias_hz": w.digital_frequency_hz,
                "residual_snr_db": w.residual_snr_db,
                "candidate_frequency_hz": candidate,
                "accepted_frequency_hz": candidate if accepted else math.nan,
                "accepted": accepted, "quality_flag": "COMPONENT_DETECTED_BRANCH_UNREVIEWED"
                if accepted else "REJECTED", "uncertainty_hz": math.nan,
                "nominal_sigma_hz": sigma, "diagnostic_interval_half_width_hz": interval,
                "provenance": "digitized_waveform_only;no_velocity;no_truth_prior",
                "observable_target": observable, "tolerance_hz": tolerance,
                "frequency_error_hz": error, "correct": correct,
                "wrong_branch": wrong_branch, "false_recovery": bool(accepted and not observable),
                "nominal_95_covers": bool(accepted and abs(error) <= 1.96 * sigma),
                "calibrated_95_covers": bool(accepted and abs(error) <= interval),
                "digital_correct": bool(accepted and name == "alias"
                                        and abs(candidate - w.digital_frequency_hz) <= tolerance),
                "elapsed_s": elapsed, "score": score,
            })
    np.savez_compressed(out / "heldout_waveforms.npz", voltage_v=arrays)
    write_csv(out / "evaluation.csv", rows)
    return rows


def binomial_interval(k: int, n: int) -> tuple[float, float]:
    if not n:
        return math.nan, math.nan
    return (float(stats.beta.ppf(0.025, k, n - k + 1)) if k else 0.,
            float(stats.beta.ppf(0.975, k + 1, n - k)) if k < n else 1.)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    groups = [(case, m) for case in sorted({str(r["case"]) for r in rows}) for m in METHODS]
    groups += [("all_observable", m) for m in METHODS]
    for name, method in groups:
        part = [r for r in rows if r["method"] == method and
                (r["observable_target"] if name == "all_observable" else r["case"] == name)]
        accepted = [r for r in part if r["accepted"]]
        errors = [r["frequency_error_hz"] for r in accepted if r["observable_target"]]
        correct = sum(r["correct"] for r in part)
        lo, hi = binomial_interval(correct, len(part))
        fa_lo, fa_hi = binomial_interval(len(accepted), len(part))
        result.append({"case": name, "method": method, "frames": len(part),
                       "accepted": len(accepted), "coverage": len(accepted) / len(part),
                       "correct": correct, "total_correct_rate": correct / len(part),
                       "correct_ci_low": lo, "correct_ci_high": hi,
                       "accepted_rmse_hz": float(np.sqrt(np.mean(np.square(errors))))
                       if errors else math.nan,
                       "accepted_mae_hz": float(np.mean(np.abs(errors))) if errors else math.nan,
                       "wrong_branch_rate": sum(r["wrong_branch"] for r in part) / len(part),
                       "false_recovery_rate": sum(r["false_recovery"] for r in part) / len(part),
                       "acceptance_ci_low": fa_lo, "acceptance_ci_high": fa_hi,
                       "nominal_95_coverage": sum(r["nominal_95_covers"] for r in accepted)
                       / len(accepted) if accepted and method.endswith("glrt") else math.nan,
                       "calibrated_95_coverage": sum(r["calibrated_95_covers"] for r in accepted)
                       / len(accepted) if accepted and method.endswith("glrt") else math.nan,
                       "mean_elapsed_s": float(np.mean([r["elapsed_s"] for r in part]))})
    return result


def boundary_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for n in (256, 512):
        for rho in (0., 0.85):
            for order in (1, 4):
                for amp in (0.04, 0.12):
                    for method in METHODS:
                        nulls = [r for r in rows if r["case"] == "null" and r["n"] == n
                                 and r["noise_group_rho"] == rho and r["method"] == method]
                        fa = sum(r["accepted"] for r in nulls) / len(nulls)
                        contiguous = True
                        maximum = math.nan
                        for ratio in (0.25, 1., 1.6, 2.6):
                            part = [r for r in rows if r["case"] == "tone" and r["n"] == n
                                    and r["noise_group_rho"] == rho and r["order"] == order
                                    and r["amplitude_v"] == amp and r["method"] == method
                                    and r["analog_truth_hz"] == ratio * BANDWIDTH]
                            lo, hi = binomial_interval(sum(r["correct"] for r in part), len(part))
                            reliable = lo >= 0.9 and fa <= ALPHA
                            contiguous = contiguous and reliable
                            if contiguous:
                                maximum = ratio * BANDWIDTH
                            result.append({"n": n, "rho": rho, "order": order, "amplitude_v": amp,
                                           "method": method, "frequency_hz": ratio * BANDWIDTH,
                                           "mean_residual_snr_db": float(np.mean(
                                               [r["residual_snr_db"] for r in part])),
                                           "correct_rate": sum(r["correct"] for r in part) / len(part),
                                           "correct_ci_low": lo, "correct_ci_high": hi,
                                           "matched_null_fa": fa, "empirical_cell_pass": reliable,
                                           "contiguous_tested_max_hz": maximum})
    return result


def diagnostics(out: Path) -> None:
    mechanisms = {
        "white_tone": AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15, noise_rho=0.),
        "OU_tone": AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15),
        "chirp_white": AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15,
                                  noise_rho=0., chirp_hz_per_s=4e16),
        "two_tone_white": AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15,
                                     noise_rho=0., competitor_hz=1.45e9,
                                     competitor_amplitude_v=0.10),
        "am_white": AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15,
                               noise_rho=0., am_depth=0.9),
        "phase_white": AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15,
                                  noise_rho=0., phase_mod_rad=1.5),
    }
    rows: list[dict[str, Any]] = []
    saved: dict[str, FloatArray] = {}
    for j, (name, case) in enumerate(mechanisms.items()):
        for repeat in range(20):
            y = synthesize(case, SEEDS["diagnostics"] + j * 100 + repeat).voltage_v
            for model in ("tone", "chirp", "two_tone"):
                residual, parameters = local_model_residual(y, FS, model)
                rows.append({"mechanism": name, "repeat": repeat, "fit_model": model,
                             **parameters, **residual_diagnostics(residual, FS)})
                if repeat == 0:
                    saved[f"{name}_{model}"] = residual
                    saved[f"{name}_signal"] = y
    write_csv(out / "residual_diagnostics.csv", rows)
    np.savez_compressed(out / "residual_examples.npz", **dict[str, Any](saved))
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), constrained_layout=True)
    for ax, name in zip(axes.flat, mechanisms, strict=True):
        for model in ("tone", "chirp", "two_tone"):
            part = [r for r in rows if r["mechanism"] == name and r["fit_model"] == model]
            ax.scatter([model] * len(part), [r["lag1"] for r in part], s=12, alpha=0.6)
        ax.axhline(0.3, color="gray", ls=":")
        ax.set(title=name, ylabel="Residual lag-1 ACF", ylim=(-0.3, 1.))
    fig.savefig(out / "residual_attribution.png", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    for ax, name in zip(axes.flat, ("OU_tone", "chirp_white", "two_tone_white", "am_white"),
                        strict=True):
        for model in ("tone", "chirp", "two_tone"):
            f, p = signal.welch(saved[f"{name}_{model}"], FS, nperseg=128)
            ax.semilogy(f / 1e9, p, label=model)
        ax.set(title=name, xlabel="Frequency (GHz)", ylabel="Residual PSD (V²/Hz)")
        ax.legend(fontsize=8)
    fig.savefig(out / "residual_psd.png", dpi=180)
    plt.close(fig)
    # Verify that the precision factor changes signal and noise together.
    rng = np.random.default_rng(SEEDS["diagnostics"] + 999)
    noise = stationary_noise(rng, 100000, NOISE_RMS, 0.85)
    transformed = ar_transform(noise, 0.85)
    impact: dict[str, Any] = {"noise_lag1_before": residual_diagnostics(noise, FS)["lag1"],
              "noise_lag1_after": residual_diagnostics(transformed, FS)["lag1"],
              "noise_rms_before_v": float(np.std(noise)),
              "noise_rms_after_v": float(np.std(transformed)),
              "signal_gain_by_frequency": {str(f): abs(1 - 0.85 * np.exp(-2j * np.pi * f / FS))
                                            for f in (0.75e9, 3e9, 7.8e9)}}
    # Counterexample: coherent signal contamination changes a residual-fitted
    # noise model. This fit is never fed into the tested independent-noise method.
    train = np.array([stationary_noise(rng, 2048, NOISE_RMS, 0.85) for _ in range(32)])
    t = np.arange(2048) / FS
    contaminated = train + 0.15 * np.cos(2 * np.pi * 0.75e9 * t)
    clean_model, contaminated_model = train_noise(train), train_noise(contaminated)
    test = synthesize(AnalogCase(frequency_hz=0.75e9, amplitude_v=0.04), 998877).voltage_v
    impact["contamination_counterexample"] = {
        "independent_model": asdict(clean_model), "contaminated_model": asdict(contaminated_model),
        "score_independent": ToneSearch(256, FS, clean_model).fit(test).score,
        "score_contaminated": ToneSearch(256, FS, contaminated_model).fit(test).score,
    }
    write_json(out / "precision_transform_audit.json", impact)
    # Independent oversampling check of changing-signal analog discretization.
    convergence: list[dict[str, Any]] = []
    for name in ("chirp_white", "am_white", "phase_white"):
        case = replace(mechanisms[name], noise_rms_v=0.)
        signals = [synthesize(replace(case, oversample=s), 5678).clean_v for s in (8, 16, 32)]
        convergence.append({"case": name,
                            "relative_rms_8_vs_32": float(np.linalg.norm(signals[0] - signals[2])
                                                          / np.linalg.norm(signals[2])),
                            "relative_rms_16_vs_32": float(np.linalg.norm(signals[1] - signals[2])
                                                           / np.linalg.norm(signals[2]))})
    write_csv(out / "analog_convergence.csv", convergence)


def real_diagnostics(out: Path, manifest: Path | None) -> None:
    raw_files = [p for p in (ROOT / "data" / "raw").rglob("*") if p.is_file()
                 and p.name != ".gitkeep"]
    if manifest is None:
        write_json(out / "real_data_status.json", {
            "status": "REAL_DATA_UNAVAILABLE" if not raw_files else "EXPLICIT_MAPPING_REQUIRED",
            "raw_file_count": len(raw_files), "files_accessed": [], "raw_sha256": "N/A",
            "instrument_response": "UNKNOWN", "bandwidth_hz": "UNKNOWN",
            "wavelength_m": "UNKNOWN", "optical_offset_hz": "UNKNOWN", "independent_truth": "UNKNOWN",
        })
        return
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    hashes: list[dict[str, Any]] = []
    for item in spec["files"]:
        path = checked_input(ROOT / item["path"], ROOT)
        before = sha(path)
        try:
            loaded = read_delimited_signals(
                path, time_column=item["time_column"], voltage_columns={"pdv": item["voltage_column"]},
                delimiter=item["delimiter"], has_header=item["has_header"], encoding=item["encoding"],
                time_scale=item["time_scale"], voltage_scales={"pdv": item["voltage_scale"]},
                original_time_unit=item["original_time_unit"],
                original_voltage_units={"pdv": item["original_voltage_unit"]},
            )
            record = loaded.records["pdv"]
            mask = ((record.time_s >= item["start_time_s"])
                    & (record.time_s <= item["end_time_s"]))
            y = record.voltage_v[mask]
            for n in (256, 512):
                for start in range(0, len(y) - n + 1, n):
                    for model in ("tone", "chirp", "two_tone"):
                        # Fixed 20 GHz search is intentionally not used here.
                        # Attribution fitter still requires the supported sample rate.
                        if not np.isclose(record.sample_rate_hz, FS, rtol=1e-5):
                            raise ValueError("Real prototype currently requires fs=20 GHz")
                        residual, fitted = local_model_residual(y[start:start + n], FS, model)
                        rows.append({"file": str(path), "n": n, "start_sample": start,
                                     "model": model, "quality_flag": "OBSERVATIONAL_ONLY",
                                     "accepted_frequency_hz": math.nan, **fitted,
                                     **residual_diagnostics(residual, FS)})
        finally:
            after = sha(path)
            hashes.append({"path": str(path), "sha256_before": before, "sha256_after": after,
                           "unchanged": before == after})
            write_json(out / f"raw_sha256_{len(hashes)}.json", hashes[-1])
            if before != after:
                raise RuntimeError(f"Raw integrity changed during read: {path}")
    write_csv(out / "real_residual_diagnostics.csv", rows)
    write_json(out / "real_data_status.json", {"status": "OBSERVATIONAL_ONLY", "hashes": hashes,
                                               "metadata": spec.get("instrument", "UNKNOWN")})


def paired_effects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    rng = np.random.default_rng(SEEDS["bootstrap"])
    # One nonoverlapping frame per independent waveform, never count overlapping
    # STFT frames as independent samples. Paired bootstrap across waveform IDs.
    for rho in (0., 0.85):
        for name in ("tone", "all_observable"):
            ref = [r for r in rows if r["method"] == "stft_gate" and r["noise_group_rho"] == rho
                   and (r["observable_target"] if name == "all_observable" else r["case"] == name)]
            other = {r["waveform_id"]: r for r in rows if r["method"] == "ar1_glrt"}
            differences = np.array([float(other[r["waveform_id"]]["correct"]) - float(r["correct"])
                                    for r in ref])
            draws = differences[rng.integers(0, len(ref), (2000, len(ref)))].mean(axis=1)
            lo, hi = np.quantile(draws, (0.025, 0.975))
            result.append({"case": name, "rho": rho, "paired_waveforms": len(ref),
                           "correct_rate_difference_ar1_minus_gate": float(differences.mean()),
                           "paired_bootstrap_95_low": float(lo), "paired_bootstrap_95_high": float(hi)})
    return result


def reports(out: Path, summary: list[dict[str, Any]], boundary: list[dict[str, Any]]) -> None:
    def pct(x: float) -> str:
        return f"{100 * x:.2f}%" if math.isfinite(x) else "N/A"

    table = ["|Case|Method|N|Coverage|Total correct|Accepted RMSE (MHz)|False recovery|95% interval coverage|",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in summary:
        table.append(f"|{r['case']}|{r['method']}|{r['frames']}|{pct(r['coverage'])}|"
                     f"{pct(r['total_correct_rate'])}|{r['accepted_rmse_hz'] / 1e6:.3f}|"
                     f"{pct(r['false_recovery_rate'])}|{pct(r['calibrated_95_coverage'])}|")
    write_text(out / "BENCHMARK_RESULTS.md", "# TASK-001 held-out benchmark\n\n" + "\n".join(table)
               + "\n\nTotal correct includes rejected target frames in denominator. Accepted RMSE includes all accepted"
               " target frames, including wrong branches. Null coverage equals false acceptance. Alias false recovery"
               " means unjustified analog-carrier acceptance, even when digital alias is accurate.\n\n"
               "Nominal null FPR=1%, calibrated per independent noise regime/window with entire-search statistic."
               " No guarantee under shifted noise or coherent interference. See cell_boundary.csv for each SNR,"
               " window, analog response, accuracy tolerance fs/(4N), exact binomial CI and contiguous tested grid."
               " A grid pass requires correctness lower 95% bound >=90% and observed matched-null FPR <=1%;"
               " finite-sample null uncertainty remains. No interpolation to an instrument bandwidth limit.\n")
    write_text(out / "README_TASK001.md", "# Reproduction\n\n"
               "Run from the worktree using PowerShell 7 and scripts/bandwidth_env.ps1.\n\n"
               "```powershell\n. ./scripts/bandwidth_env.ps1\n"
               "& D:/miniconda3/envs/dps-studio/python.exe scripts/run_task001_bandwidth.py\n```\n\n"
               "Every run uses a new directory. config.json records independent seeds; frozen_calibration.json"
               " is written before held-out evaluation. No test-label tuning. evaluation.csv retains every"
               " candidate/rejection/failure and heldout_waveforms.npz retains corresponding digitized arrays."
               " All frequencies are Hz; voltages V; times s. Real instrument/optics metadata UNKNOWN; no velocity"
               " conversion. Uncertainty_hz intentionally NaN: interval columns are diagnostic synthetic-model"
               " intervals, whose held-out coverage is reported and may fail under misspecification.\n\n"
               "CPU times include production STFT/quality shared by both spectral baselines; GLRT times include"
               " entire search and local refinement, excluding one-time training/calibration/design-bank construction."
               " STFT frame interval=N/fs, window duration=N/fs; rectangular model observation duration=(N-1)/fs."
               " FFT grid fs/(4N) is zero-padded grid spacing; Hann null-to-null main lobe ~4fs/N.\n\n"
               "Optional --real-manifest requires explicit file/channel/unit/interval mappings, restricted to local"
               " data/raw; it writes only observations plus before/after SHA-256. Supported prototype fs=20 GHz."
               " No data migration or external worktree reading. See docs/TASK-001_BANDWIDTH_RESEARCH.md.\n")
    write_text(out / "RESIDUAL_DIAGNOSTICS.md", "# Residual attribution\n\n"
               "REAL_DATA_UNAVAILABLE unless an explicit manifest was supplied; see real_data_status.json."
               " residual_diagnostics.csv compares tone, chirp and two-tone fits under known white/OU noise,"
               " chirp, AM, phase modulation and competing tones. Columns include lag-1/max-20 ACF, Welch PSD peak,"
               " peak power fraction, quarter-window power ratio, fitted amplitude/frequency/chirp and convergence."
               " These are descriptive diagnostics, not independent p-values or source identification.\n\n"
               "Reduced residual correlation under a richer signal fit supports attribution only within that"
               " controlled synthetic mechanism. ACF/AR fit alone cannot identify electronics as the real source."
               " precision_transform_audit.json checks the same AR precision factor on signal and noise, and"
               " includes contaminated-training suppression as a counterexample. analog_convergence.csv reports"
               " oversampled analog solver error; steady tones use exact continuous H(jw).\n")
    maxima = [r["contiguous_tested_max_hz"] for r in boundary
              if r["method"] == "ar1_glrt" and math.isfinite(r["contiguous_tested_max_hz"])]
    write_text(out / "TASK001_VERDICT.md", "# TASK-001 verdict\n\nMIXED\n\n"
               "REQUIRES_EXPERIMENTAL_CONFIRMATION; REAL_DATA_UNAVAILABLE (default run).\n\n"
               "A frozen independent-noise covariance can improve digital component detection under matched"
               " synthetic assumptions. Detection cannot establish target identity or resolve an analog alias."
               " Noise shift, competing components and signal misspecification remain explicit counterexamples."
               " No actual oscilloscope response or independent over-bandwidth truth is available.\n\n"
               f"Largest passing contiguous tested frequency across model cells: {max(maxima) if maxima else 'NONE'} Hz."
               " This is conditional and grid-limited; per-cell failures and finite-sample FPR uncertainty must be"
               " read alongside it. Prioritize instrument/noise calibration and independent injected-tone truth"
               " before expanding algorithms. The tracked report provides the quantitative interpretation.\n")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    for ax, rho in zip(axes, (0., 0.85), strict=True):
        for m in METHODS:
            part = [r for r in boundary if r["method"] == m and r["rho"] == rho
                    and r["n"] == 512 and r["amplitude_v"] == 0.04 and r["order"] == 4]
            ax.plot([r["frequency_hz"] / BANDWIDTH for r in part],
                    [r["correct_rate"] for r in part], "o-", label=m)
        ax.set(title=f"rho={rho}, N=512, order=4, A=0.04 V",
               xlabel="Analog frequency / -3 dB bandwidth", ylabel="Total-frame correct rate", ylim=(-0.03, 1.03))
        ax.legend(fontsize=8)
    fig.savefig(out / "identifiability_boundary.png", dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("run_%Y%m%d_%H%M%S"))
    parser.add_argument("--repetitions", type=int, default=48)
    parser.add_argument("--null-count", type=int, default=500)
    parser.add_argument("--calibration-count", type=int, default=499)
    parser.add_argument("--interval-count", type=int, default=128)
    parser.add_argument("--real-manifest", type=Path)
    args = parser.parse_args()
    if min(args.repetitions, args.null_count, args.calibration_count, args.interval_count) < 1:
        parser.error("All counts must be positive")
    if git("branch", "--show-current") != "research/bandwidth":
        raise RuntimeError("Wrong branch; no automatic switching")
    out = validate_output(ROOT / "results" / "task001_bandwidth" / args.run_id)
    config = {"task": "TASK-001", "verdict": "PENDING", "parameters": vars(args) | {
        "real_manifest": str(args.real_manifest) if args.real_manifest else None},
        "seeds": SEEDS, "sample_rate_hz": FS, "analog_bandwidth_hz": BANDWIDTH,
        "nominal_fpr": ALPHA, "accuracy_tolerance_hz": "fs/(4*N)",
        "methods": METHODS, "search_band_hz": [0.2e9, 9.5e9],
        "wavelength_m": "UNKNOWN", "optical_offset_hz": "UNKNOWN", "velocity_conversion": False,
        "environment": {"python": sys.version, "executable": sys.executable,
                        "platform": platform.platform(),
                        "libraries": {k: importlib.metadata.version(k) for k in
                                      ("numpy", "scipy", "matplotlib", "pytest", "ruff", "mypy")},
                        "thread_env": {k: os.environ.get(k) for k in
                                       ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}},
        "git_head": git("rev-parse", "HEAD"), "git_status_start": git("status", "--short"),
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in
                          (Path(__file__), ROOT / "src/dps_studio/research/bandwidth_task001.py")}}
    write_json(out / "config.json", config)
    start = perf_counter()
    try:
        searches, thresholds, scales = setup_models(out, args.calibration_count, args.interval_count)
        rows = evaluate(out, make_cases(args.repetitions, args.null_count), searches, thresholds, scales)
        summary, boundary = summarize(rows), boundary_table(rows)
        write_csv(out / "summary.csv", summary)
        write_csv(out / "cell_boundary.csv", boundary)
        write_csv(out / "paired_bootstrap.csv", paired_effects(rows))
        diagnostics(out)
        real_diagnostics(out, args.real_manifest)
        reports(out, summary, boundary)
        write_json(out / "completion.json", {"status": "COMPLETE", "waveforms": len(rows) // len(METHODS),
                                              "evaluations": len(rows), "elapsed_s": perf_counter() - start})
    except Exception as exc:
        write_json(out / "failure.json", {"status": "FAILED", "type": type(exc).__name__,
                                           "reason": str(exc), "elapsed_s": perf_counter() - start})
        raise
    print(f"COMPLETE {out}", flush=True)


if __name__ == "__main__":
    main()
