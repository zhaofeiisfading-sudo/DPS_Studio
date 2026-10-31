"""Reproduce frozen TASK-002 synthetic and observational experiments.

Use bandwidth_env.ps1, one BLAS thread, and a fresh run-id. No existing
artifact is overwritten. Main/null splits and thresholds precede test labels.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import re
from time import perf_counter
from typing import Any

import numpy as np

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.ridge import (
    assess_ridge_spectral_quality, extract_peak_ridge, refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import compute_stft
from dps_studio.research.bandwidth_task001 import (
    AnalogCase, FloatArray, analog_response, empirical_threshold,
    stationary_noise, train_noise,
)
from dps_studio.research.bandwidth_task002 import (
    Acceptance, FREQUENCIES_HZ, FS, GATED, METHODS, MINIMUM_HZ, WINDOWS,
    WIDE_MAXIMUM_HZ, WideToneSearch, Window, acquire, frame_stft, noise_psd_v2_per_hz,
    spectral_frame,
)
from run_task001_bandwidth import write_csv

ROOT = Path(__file__).resolve().parents[1]
REPETITIONS = 400
NULL_COUNT = 4096
CONDITIONS = (
    ("ideal_white", True, 1, 6e9, 0.),
    ("ideal_OU", True, 1, 6e9, .85),
    ("LP1_B6_OU", False, 1, 6e9, .85),
    ("LP4_B6_OU", False, 4, 6e9, .85),
    ("LP4_B3_OU", False, 4, 3e9, .85),
)


def sha(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=True)
        stream.write("\n")


def seed(stage: int, w: int, condition: int, f: int, trial: int) -> int:
    return int(np.random.SeedSequence([20261029, stage, w, condition, f, trial])
               .generate_state(1, dtype=np.uint64)[0])


def output_path(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("run-id must be one safe path component")
    out = ROOT / "results" / "task002_bandwidth" / run_id
    if not out.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Output resolves outside worktree")
    out.mkdir(parents=True, exist_ok=True)
    if (out / "config.json").exists() or any(out.glob("*.csv")):
        raise FileExistsError("Run already used; select a new run-id")
    return out


def evaluate(y: FloatArray, window: Window, search: WideToneSearch) -> dict[str, Any]:
    start = perf_counter()
    stft = frame_stft(y, FS, window)
    stft_s = perf_counter() - start
    start = perf_counter()
    spectral = spectral_frame(stft)
    spectral_s = perf_counter() - start
    start = perf_counter()
    fit = search.fit(y)
    likelihood_s = perf_counter() - start
    return {
        "frequencies": {
            "A_default_peak": spectral.default_peak_hz,
            "B_wide_peak": spectral.wide_peak_hz,
            "C_wide_gate": spectral.wide_refined_hz,
            "D_ar1_glrt": fit.frequency_hz,
            "A_default_gate": spectral.default_refined_hz,
        },
        "scores": {"A_default_peak": math.inf, "B_wide_peak": math.inf,
                   "C_wide_gate": spectral.wide_score_db, "D_ar1_glrt": fit.score,
                   "A_default_gate": spectral.default_score_db},
        "stft_seconds": stft_s, "spectral_seconds": spectral_s,
        "ar1_seconds": likelihood_s,
        "background_db": spectral.wide_background_db,
        "competitor_db": spectral.wide_competitor_db,
        "ar1_nominal_sigma_hz": fit.nominal_sigma_hz,
    }


def trial_rows(
    result: dict[str, Any], thresholds: dict[str, float], metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    truth = float(metadata.get("truth_hz", math.nan))
    alias = float(metadata.get("alias_hz", math.nan))
    competitor = float(metadata.get("competitor_hz", 0.))
    for method in METHODS:
        f = float(result["frequencies"][method])
        score = float(result["scores"][method])
        accepted = math.isfinite(f) and score > thresholds.get(method, -math.inf)
        error = abs(f - truth)
        correct = accepted and error <= Acceptance().tolerance_hz
        rows.append({**metadata, "method": method, "candidate_hz": f,
                     "accepted": int(accepted), "correct": int(correct),
                     "absolute_error_hz": error, "score": score,
                     "threshold": thresholds.get(method, -math.inf),
                     "accepted_wrong": int(accepted and not correct),
                     "alias_hit": int(accepted and abs(f - alias) <= 50e6),
                     "competitor_hit": int(accepted and competitor > 0
                                           and abs(f - competitor) <= 50e6),
                     "digital_only": True, "validated_physical_velocity": False,
                     "background_db": result["background_db"],
                     "competitor_db": result["competitor_db"],
                     "ar1_nominal_sigma_hz": (result["ar1_nominal_sigma_hz"]
                                              if method == "D_ar1_glrt" else math.nan),
                     "stft_seconds": result["stft_seconds"],
                     # spectral timing covers both search bands jointly.
                     "both_spectral_bands_seconds": result["spectral_seconds"],
                     "ar1_seconds": result["ar1_seconds"]})
    return rows


def calibration(
    out: Path, wi: int, window: Window, ni: int, rho: float,
) -> tuple[WideToneSearch, dict[str, float]]:
    records = np.array([stationary_noise(np.random.default_rng(seed(1, wi, ni, 0, i)),
                                         2048, .035, rho) for i in range(128)])
    model = train_noise(records)
    search = WideToneSearch(window.n, FS, model)
    scores: dict[str, list[float]] = {method: [] for method in GATED}
    calibration_rows: list[dict[str, Any]] = []
    for i in range(NULL_COUNT):
        trial_seed = seed(2, wi, ni, 0, i)
        y = stationary_noise(np.random.default_rng(trial_seed), window.n, .035, rho)
        result = evaluate(y, window, search)
        for method in GATED:
            score = result["scores"][method]
            scores[method].append(score)
            calibration_rows.append({"window": window.name, "noise_rho": rho,
                                     "trial": i, "seed": trial_seed, "method": method,
                                     "score": score})
    thresholds = {m: empirical_threshold(np.array(s), .001) for m, s in scores.items()}
    write_csv(out / f"calibration_{window.name}_{ni}.csv", calibration_rows)
    write_json(out / f"thresholds_{window.name}_{ni}.json",
               {"model": asdict(model), "thresholds": thresholds, "count": NULL_COUNT,
                "alpha_calibration": .001, "strict_greater": True})
    rows: list[dict[str, Any]] = []
    for i in range(NULL_COUNT):
        trial_seed = seed(3, wi, ni, 0, i)
        y = stationary_noise(np.random.default_rng(trial_seed), window.n, .035, rho)
        result = evaluate(y, window, search)
        rows.extend(trial_rows(result, thresholds,
                               {"window": window.name, "condition": "null",
                                "noise_rho": rho, "trial": i, "seed": trial_seed,
                                "truth_hz": math.nan, "alias_hz": math.nan}))
    write_csv(out / f"null_{window.name}_{ni}.csv", rows)
    print(json.dumps({"stage": "calibrated_and_null_tested", "window": window.name,
                      "rho": rho, "thresholds": thresholds}), flush=True)
    return search, thresholds


def benchmark(out: Path) -> None:
    contexts: dict[tuple[int, int], tuple[WideToneSearch, dict[str, float]]] = {}
    for wi, window in enumerate(WINDOWS):
        for ni, rho in enumerate((0., .85)):
            contexts[(wi, ni)] = calibration(out, wi, window, ni, rho)
        for ci, (name, ideal, order, bandwidth, rho) in enumerate(CONDITIONS):
            search, thresholds = contexts[(wi, int(rho > 0))]
            rows: list[dict[str, Any]] = []
            for fi, frequency in enumerate(FREQUENCIES_HZ):
                case = AnalogCase(sample_rate_hz=FS, bandwidth_hz=bandwidth, order=order,
                                  n=window.n, frequency_hz=frequency, amplitude_v=.04,
                                  noise_rms_v=.035, noise_rho=rho, adc_step_v=0.)
                for trial in range(REPETITIONS):
                    trial_seed = seed(4, wi, ci, fi, trial)
                    waveform = acquire(case, trial_seed, ideal=ideal)
                    rows.extend(trial_rows(evaluate(waveform.voltage_v, window, search),
                                           thresholds, {
                                               "window": window.name, "condition": name,
                                               "truth_hz": frequency,
                                               "alias_hz": waveform.digital_frequency_hz,
                                               "noise_rho": rho, "trial": trial,
                                               "seed": trial_seed,
                                               "input_amplitude_v": .04,
                                               "noise_rms_v": .035,
                                               "bandwidth_hz": bandwidth if not ideal else math.nan,
                                               "chain_order": order if not ideal else 0,
                                               "response_magnitude": (1. if ideal else abs(
                                                   analog_response(frequency, bandwidth, order))),
                                               "adc_step_v": 0.,
                                               "observed_snr_db": waveform.residual_snr_db,
                                           }))
            write_csv(out / f"evaluation_{window.name}_{name}.csv", rows)
            print(json.dumps({"stage": "main", "window": window.name,
                              "condition": name, "rows": len(rows)}), flush=True)
        search, thresholds = contexts[(wi, 1)]
        pressure(out, wi, window, search, thresholds)


def pressure(out: Path, wi: int, window: Window, search: WideToneSearch,
             thresholds: dict[str, float]) -> None:
    base = AnalogCase(sample_rate_hz=FS, bandwidth_hz=6e9, n=window.n,
                      frequency_hz=12e9, amplitude_v=.04, noise_rms_v=.035, noise_rho=.85)
    cases = (
        ("fast_chirp", replace(base, chirp_hz_per_s=8e9 * FS / window.n), False),
        ("strong_competitor", replace(base, competitor_hz=8e9,
                                     competitor_amplitude_v=.08), True),
        ("alias_23_to_17", replace(base, frequency_hz=23e9), True),
        ("zero_response", replace(base, response_zero=True), False),
        ("noise_mismatch_white", replace(base, amplitude_v=0., noise_rho=0.), True),
        ("quantization_erasure", replace(base, amplitude_v=.0005, noise_rms_v=0.,
                                        adc_step_v=.002), True),
    )
    rows: list[dict[str, Any]] = []
    convergence = []
    for ci, (name, case, ideal) in enumerate(cases):
        for trial in range(REPETITIONS):
            trial_seed = seed(5, wi, ci, 0, trial)
            wave = acquire(case, trial_seed, ideal=ideal)
            rows.extend(trial_rows(evaluate(wave.voltage_v, window, search), thresholds, {
                "window": window.name, "condition": name, "trial": trial, "seed": trial_seed,
                "truth_hz": case.frequency_hz, "alias_hz": wave.digital_frequency_hz,
                "competitor_hz": case.competitor_hz, "noise_rho": case.noise_rho,
                "observed_snr_db": wave.residual_snr_db,
                "physical_status": ("NOT_IDENTIFIABLE" if name in (
                    "alias_23_to_17", "zero_response", "quantization_erasure",
                    "noise_mismatch_white") else "SYNTHETIC_MODEL_ONLY"),
            }))
            if name == "fast_chirp" and trial < 4:
                reference = acquire(replace(case, oversample=32), trial_seed).clean_v
                refined = acquire(replace(case, oversample=16), trial_seed).clean_v
                norm = max(float(np.linalg.norm(reference)), 1e-30)
                convergence.append({"window": window.name, "seed": trial_seed,
                                    "error8_vs32": float(np.linalg.norm(wave.clean_v-reference))/norm,
                                    "error16_vs32": float(np.linalg.norm(refined-reference))/norm})
    write_csv(out / f"pressure_{window.name}.csv", rows)
    write_csv(out / f"analog_convergence_{window.name}.csv", convergence)
    controls = []
    for fi, f in enumerate((8e9, 18e9)):
        clean = acquire(replace(base, frequency_hz=f, noise_rms_v=0.),
                        seed(6, wi, 0, fi, 0), ideal=True)
        controls.extend(trial_rows(evaluate(clean.voltage_v, window, search), thresholds,
                                   {"window": window.name, "condition": "clean_control",
                                    "truth_hz": f, "alias_hz": f, "trial": 0}))
    write_csv(out / f"controls_{window.name}.csv", controls)


def reference(out: Path) -> None:
    source = ROOT / "docs" / "原始数据.csv"
    resolved = source.resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("Reference waveform resolves outside this worktree")
    before = sha(resolved)
    metadata: dict[str, Any] = {
        "source": str(resolved), "sha256_before": before,
        "status": "OBSERVATIONAL_CANDIDATE", "hardware_fmax_hz": "UNKNOWN",
        "time_column": 0, "voltage_columns": {"ch1": 1, "ch2": 2},
        "time_unit": "s", "voltage_unit": "V", "time_scale": 1., "voltage_scale": 1.,
        "delimiter": ",", "header": False, "encoding": "utf-8",
        "native_adc_fs": "UNKNOWN", "instrument_H": "UNKNOWN", "bandwidth": "UNKNOWN",
        "wavelength": "UNKNOWN", "optical_offset": "UNKNOWN", "interface_truth": "UNKNOWN",
        "synthetic_gates_transferred": False,
    }
    write_json(out / "reference_before.json", metadata)
    try:
        loaded = read_delimited_signals(
            resolved, time_column=0, voltage_columns={"ch1": 1, "ch2": 2},
            delimiter=",", has_header=False, encoding="utf-8", time_scale=1.,
            voltage_scales={"ch1": 1., "ch2": 1.}, original_time_unit="s",
            original_voltage_units={"ch1": "V", "ch2": "V"},
        )
        rows: list[dict[str, Any]] = []
        for channel, record in loaded.records.items():
            for window in WINDOWS[1:]:
                stft = compute_stft(record, window_length_samples=window.n,
                                    overlap_samples=window.overlap, nfft=window.nfft)
                arrays: dict[str, Any] = {"frequency_hz": stft.frequency_hz,
                                          "time_s": stft.time_s,
                                          "magnitude": np.abs(stft.spectrum)}
                for band, minimum, maximum in (("default", MINIMUM_HZ, 6e9),
                                                ("wide", MINIMUM_HZ, WIDE_MAXIMUM_HZ),
                                                ("high", 6.05e9, WIDE_MAXIMUM_HZ)):
                    peak = extract_peak_ridge(stft, minimum_frequency_hz=minimum,
                                              maximum_frequency_hz=maximum)
                    refined = refine_peak_ridge_subbin(stft, peak)
                    quality = assess_ridge_spectral_quality(
                        stft, refined, background_exclusion_half_width_hz=2*record.sample_rate_hz
                        / window.n, minimum_background_bin_count=8)
                    arrays[band + "_peak_hz"] = peak.frequency_hz
                    for j in range(len(stft.time_s)):
                        rows.append({"channel": channel, "window": window.name, "band": band,
                                     "frame": j, "time_s": float(stft.time_s[j]),
                                     "peak_hz": float(peak.frequency_hz[j]),
                                     "refined_hz": float(refined.refined_frequency_hz[j]),
                                     "background_db": float(quality.peak_to_background_db[j]),
                                     "competitor_db": float(quality.peak_to_competitor_db[j]),
                                     "peak_magnitude_v": float(peak.peak_magnitude[j]),
                                     "status": "OBSERVATIONAL_CANDIDATE"})
                with (out / f"reference_{channel}_{window.name}.npz").open("xb") as stream:
                    np.savez_compressed(stream, **arrays)
            metadata[channel] = {"export_grid_fs_hz": record.sample_rate_hz,
                                  "sample_count": record.sample_count,
                                  "uniform": record.is_uniformly_sampled}
        write_csv(out / "reference_candidates.csv", rows)
    finally:
        metadata["sha256_after"] = sha(resolved)
        metadata["unchanged"] = metadata["sha256_after"] == before
        write_json(out / "reference_status.json", metadata)
        if not metadata["unchanged"]:
            raise RuntimeError("Reference bytes changed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    out = output_path(args.run_id)
    started = perf_counter()
    config = {"fs_hz": FS, "nyquist_hz": FS/2, "windows": [asdict(w) for w in WINDOWS],
              "frequencies_hz": FREQUENCIES_HZ, "conditions": CONDITIONS,
              "acceptance": asdict(Acceptance()), "repetitions": REPETITIONS,
              "null_calibration": NULL_COUNT, "null_test": NULL_COUNT,
              "seed_root": 20261029, "lambda_m_synthetic_only": 1550e-9,
              "optical_offset_hz_synthetic_only": 0., "beat_branch_synthetic_only": "positive",
              "noise_model_training": [128, 2048], "noise_rms_v": .035,
              "input_peak_amplitude_v": .04, "adc_step_main_v": 0.,
              "search_narrow_hz": [MINIMUM_HZ, 6e9],
              "search_wide_hz": [MINIMUM_HZ, WIDE_MAXIMUM_HZ],
              "prototype_selection": "none; inherited TASK001 fit; no label tuning",
              "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (
                  Path(__file__), ROOT / "src/dps_studio/research/bandwidth_task002.py",
                  ROOT / "src/dps_studio/research/bandwidth_task001.py",
                  ROOT / "docs/TASK-002_PREREGISTRATION.md")}}
    write_json(out / "config.json", config)
    f = np.linspace(0, FS/2, 2049)
    psd = [{"frequency_hz": float(q), "rho": rho, "psd_v2_per_hz": float(p)}
           for rho in (0., .85)
           for q, p in zip(f, noise_psd_v2_per_hz(f, FS, .035, rho), strict=True)]
    write_csv(out / "configured_noise_psd.csv", psd)
    benchmark(out)
    reference(out)
    write_json(out / "completion.json", {"completed": True, "seconds": perf_counter()-started})
    print(json.dumps({"out": str(out), "completed": True}), flush=True)


if __name__ == "__main__":
    main()
