"""Consolidate immutable synthetic and observational TASK-001 evidence."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy import optimize  # type: ignore[import-untyped]

from dps_studio.research.bandwidth_task001 import AnalogCase, residual_diagnostics, synthesize
from run_task001_bandwidth import (
    METHODS, ROOT, SEEDS, binomial_interval, validate_output, write_csv, write_json, write_text,
)


def read_csv(path: Path) -> list[dict[str, str]]:
    # csv preserves literal case="null"; pandas' default NA parser would drop it.
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def flag(row: dict[str, str], key: str) -> bool:
    return row[key] == "True"


def rate(rows: list[dict[str, str]], key: str) -> float:
    return sum(flag(r, key) for r in rows) / len(rows) if rows else math.nan


def known_chirp_diagnostic(out: Path) -> None:
    """Oracle initialization diagnoses local optimizer failure, NOT a new estimator.

    Truth is used ONLY here, on synthetic attribution examples. No detection
    threshold, noise model, benchmark output or test method is modified.
    """
    case = AnalogCase(n=512, frequency_hz=1e9, amplitude_v=0.15,
                      noise_rho=0., chirp_hz_per_s=4e16)
    fs, n = case.sample_rate_hz, case.n
    t = (np.arange(n) - (n - 1) / 2) / n
    rows: list[dict[str, Any]] = []
    for repeat in range(20):
        y = synthesize(case, SEEDS["diagnostics"] + 200 + repeat).voltage_v

        def residual(q: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            phi = 2 * np.pi * n * (q[0] * t + 0.5 * q[1] * t**2)
            x = np.column_stack((np.ones(n), np.cos(phi), np.sin(phi)))
            return np.asarray(y - x @ np.linalg.lstsq(x, y, rcond=None)[0])

        fitted = optimize.least_squares(
            residual, [case.frequency_hz / fs, case.chirp_hz_per_s * n / fs**2],
            bounds=([0.01, -0.35], [0.475, 0.35]), max_nfev=100,
        )
        rows.append({"repeat": repeat, "oracle_truth_initialization": True,
                     "provenance": "SYNTHETIC_ORACLE_DIAGNOSTIC_ONLY;NOT_BENCHMARK_METHOD",
                     "frequency_hz": float(fitted.x[0] * fs),
                     "chirp_hz_per_s": float(fitted.x[1] * fs**2 / n),
                     **residual_diagnostics(residual(fitted.x), fs)})
    write_csv(out / "oracle_chirp_diagnostic.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-run", required=True)
    parser.add_argument("--reference-run", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    source = ROOT / "results" / "task001_bandwidth" / args.synthetic_run
    reference = ROOT / "results" / "task001_bandwidth" / args.reference_run
    for path in (source, reference):
        if not path.resolve(strict=True).is_relative_to(ROOT.resolve()):
            raise ValueError("Evidence directory resolves outside worktree")
    out = validate_output(ROOT / "results" / "task001_bandwidth" / args.run_id)
    rows = read_csv(source / "evaluation.csv")
    summaries = read_csv(source / "summary.csv")
    rsummary = read_csv(reference / "real_summary.csv")
    extended: list[dict[str, Any]] = []
    table = ["|Method|Tone correct/3072|Tone coverage|Tone accepted RMSE / MAE MHz|Matched null FA/2000|Beyond B correct/1536|",
             "|---|---:|---:|---:|---:|---:|"]
    for m in METHODS:
        tone = next(r for r in summaries if r["case"] == "tone" and r["method"] == m)
        null = [r for r in rows if r["case"] == "null" and r["method"] == m]
        oob = [r for r in rows if r["case"] == "tone" and r["method"] == m
               and float(r["analog_truth_hz"]) > float(r["bandwidth_hz"])]
        table.append(f"|{m}|{tone['correct']} ({100 * float(tone['total_correct_rate']):.2f}%)|"
                     f"{100 * float(tone['coverage']):.2f}%|{float(tone['accepted_rmse_hz']) / 1e6:.3f} / "
                     f"{float(tone['accepted_mae_hz']) / 1e6:.3f}|{sum(flag(r, 'accepted') for r in null)} "
                     f"({100 * rate(null, 'accepted'):.2f}%)|{sum(flag(r, 'correct') for r in oob)} "
                     f"({100 * rate(oob, 'correct'):.2f}%)|")
        for case in sorted({r["case"] for r in rows}):
            part = [r for r in rows if r["method"] == m and r["case"] == case]
            k = sum(flag(r, "accepted") for r in part)
            lo, hi = binomial_interval(k, len(part))
            extended.append({"method": m, "case": case, "frames": len(part),
                             "accepted": k, "correct": sum(flag(r, "correct") for r in part),
                             "coverage": k / len(part), "acceptance_ci_low": lo,
                             "acceptance_ci_high": hi, "total_correct_rate": rate(part, "correct"),
                             "wrong_frequency_acceptance_rate": sum(
                                 flag(r, "accepted") and flag(r, "observable_target")
                                 and not flag(r, "correct") for r in part) / len(part),
                             "wrong_branch_rate": rate(part, "wrong_branch"),
                             "false_physical_recovery_rate": rate(part, "false_recovery"),
                             "digital_alias_correct_rate": rate(part, "digital_correct")})
    write_csv(out / "extended_metrics.csv", extended)
    # Verdict follows observed results. Improving a matched tone test while
    # shifted-noise false acceptance or target ambiguity persists is MIXED.
    tone_rates = {m: next(float(r["total_correct_rate"]) for r in summaries
                         if r["case"] == "tone" and r["method"] == m) for m in METHODS}
    shift = next(r for r in extended if r["method"] == "ar1_glrt" and r["case"] == "noise_shift")
    improved = tone_rates["ar1_glrt"] > tone_rates["stft_gate"]
    verdict = ("MIXED" if improved and shift["coverage"] > 0.01 else
               "BETTER_THAN_BASELINE" if improved else "NOT_SUPPORTED")
    write_json(out / "assessment.json", {"verdict": verdict,
                                          "physical_verdict": "REQUIRES_EXPERIMENTAL_CONFIRMATION",
                                          "data_status": "OBSERVATIONAL_REFERENCE_ONLY",
                                          "synthetic_source": str(source), "reference_source": str(reference),
                                          "methods_unchanged_after_test": True,
                                          "false_recovery_claim": "No improvement guarantee under noise/model shift"})
    known_chirp_diagnostic(out)
    write_text(out / "README_TASK001.md", "# TASK-001 final evidence index\n\n"
               f"Verdict: {verdict}; REQUIRES_EXPERIMENTAL_CONFIRMATION.\n\n"
               f"Synthetic evidence: `{source}`. Real reference observations: `{reference}`.\n\n"
               "The synthetic run's REAL_DATA_UNAVAILABLE flag describes its data/raw-only inventory at execution."
               " Subsequent discovery of the documented docs/原始数据.csv reference is recorded separately;"
               " no prior artifact is overwritten. Final real status is OBSERVATIONAL_REFERENCE_ONLY.\n\n"
               "Reproduce with PowerShell 7, scripts/bandwidth_env.ps1, Python 3.12:\n\n"
               "```powershell\n. ./scripts/bandwidth_env.ps1\n"
               "& D:/miniconda3/envs/dps-studio/python.exe scripts/run_task001_bandwidth.py --run-id NEW_SYNTHETIC\n"
               "& D:/miniconda3/envs/dps-studio/python.exe scripts/diagnose_task001_reference.py --run-id NEW_REFERENCE\n"
               "& D:/miniconda3/envs/dps-studio/python.exe scripts/summarize_task001_bandwidth.py "
               "--synthetic-run NEW_SYNTHETIC --reference-run NEW_REFERENCE --run-id NEW_ASSESSMENT\n```\n\n"
               "Set OPENBLAS_NUM_THREADS, OMP_NUM_THREADS, MKL_NUM_THREADS to 1 for comparable timings."
               " Full scores, seeds, frozen calibration, failed cases and digitized waveforms remain in the"
               " source run. The tracked report is docs/TASK-001_BANDWIDTH_RESEARCH.md.\n")
    write_text(out / "BENCHMARK_RESULTS.md", "# Independent synthetic test\n\n" + "\n".join(table)
               + "\n\nNo target truth or frequency hint was passed to any benchmark estimator. Thresholds use"
               " 499 independent null calibration waveforms per noise/window group, nominal alpha=1%."
               " Matched held-out null acceptance is 24/2000 (1.20%, exact 95% CI 0.77–1.78%) for AR1,"
               " versus 17/2000 (0.85%, 0.50–1.36%) for gated STFT. This does not establish lower or equal"
               " false acceptance for AR1; per-group empirical rates are 0.8–1.8%.\n\n"
               "All accepted errors, including gross errors, enter RMSE/MAE. Rejected target frames enter"
               " total-frame correctness. Extended_metrics.csv includes wrong-frequency acceptance, wrong"
               " branch and false physical recovery; detection recall equals coverage for target-present"
               " cells and must be read together with correctness. No curve completion or temporal prior.\n\n"
               "Boundary criterion is lower exact 95% correctness bound >=90%, observed matched-null FA<=1%,"
               " and a contiguous prefix of the tested grid. Finite-sample FPR uncertainty remains: this is"
               " an empirical conditional boundary, not certification of alpha<=1% or of instrument bandwidth."
               " See source cell_boundary.csv for actual SNR, order, amplitude and window dependence.\n")
    lines = ["|Channel|N|Fit|Median lag-1|Median residual RMS V|", "|---|---:|---|---:|---:|"]
    for r in rsummary:
        lines.append(f"|{r['channel']}|{r['n']}|{r['fit_model']}|{float(r['median_lag1']):.4f}|"
                     f"{float(r['median_residual_rms_v']):.6g}|")
    write_text(out / "RESIDUAL_DIAGNOSTICS.md", "# Real reference and synthetic attribution\n\n"
               + "\n".join(lines) + "\n\n192 selected windows, 576 fits; two window sizes and channels from one file"
               " are not independent experiments. All 576 residuals exceed abs(lag1)=0.3. No observation is"
               " accepted as a validated target frequency. The reference SHA-256 is unchanged:\n\n"
               "`ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`.\n\n"
               "Synthetic white-tone residual lag1 median=-0.017; OU-tone=0.844; white-noise AM=0.734;"
               " white-noise chirp=0.838; two-tone=0.690. Correct two-tone fitting reduces the last to -0.001."
               " The initial local chirp optimizer fails for the faster chirp, despite reporting convergence."
               " oracle_chirp_diagnostic.csv uses known-truth initialization solely to diagnose that numerical"
               " failure; it is excluded from estimator scores and is not evidence of practical recovery.\n\n"
               "The AR precision factor is applied to data and signal design together. In a 100000-sample"
               " OU audit, lag1 changes 0.85045 -> -0.00262; signal gains at 0.75/3/7.8 GHz are"
               " 0.264/0.850/1.741, so it is not a neutral preprocessing operation. Contaminating noise"
               " training with a coherent tone changes rho 0.850 -> 0.960 and suppresses a weak-tone score"
               " 30.41 -> 8.35. Independent training avoids this specific feedback, but noise shift still fails.\n")
    write_text(out / "TASK001_VERDICT.md", f"# TASK-001 verdict\n\n{verdict}\n\n"
               "REQUIRES_EXPERIMENTAL_CONFIRMATION. Real status: OBSERVATIONAL_REFERENCE_ONLY.\n\n"
               "Matched-noise single-tone estimation improves on held-out waveforms. The original goal of"
               " improving reliability without extra false physical recovery is not established: shifted-noise"
               " false acceptance is 90/96 versus 12/96 for gated STFT, fast-chirp acceptance is 95/96 but"
               " correct estimation only 1/96, all 96 competition cases choose the wrong target branch,"
               " and all 96 aliases are accepted only as digital components. H=0 yields 2/96 random"
               " acceptances; quantization erasure yields 0/96. No erased information is recovered.\n\n"
               "Calibrated diagnostic interval coverage is 95.36% on accepted tones and 86.59% across accepted"
               " modeled/mismodeled target-present cases; chirp coverage is zero. Uncertainty_hz remains NaN."
               " No instrument transfer function, certified noise segment, optical offset/wavelength or"
               " independent over-bandwidth truth is supplied. Prioritize receiver/noise characterization and"
               " independently injected frequency sweeps; stop algorithm expansion pending that evidence.\n")
    print(f"ASSESSMENT {verdict}: {out}")


if __name__ == "__main__":
    main()
