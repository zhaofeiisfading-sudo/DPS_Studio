"""Reproduce TASK007 into a NEW directory. No data/raw or existing-file writes."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import json
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np

from dps_studio.core.analysis_profiles import BALANCED_PROFILE
from dps_studio.core.models import SignalRecord
from dps_studio.research.bandwidth_task007 import FitConfig, Model, fit_frame
from dps_studio.research.bandwidth_task007_simulation import Acquisition, simulate
from dps_studio.research import task028_consolidation as frozen

Row = dict[str, Any]
ROOT = Path(__file__).resolve().parents[1]
WINDOW = 256
HOP = 128
WAVELENGTH_M = 1550e-9  # simulation only, never experimental calibration


def json_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def csv_new(path: Path, rows: list[Row]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fit_config(fs: float, model: str, threshold: float, size: int = WINDOW) -> FitConfig:
    if model not in ("tone", "chirp"):
        raise ValueError(model)
    return FitConfig(fs, 2 * fs / size, fs / 2 - 2 * fs / size, cast(Model, model), threshold)


def calibrate() -> dict[str, Any]:
    rng = np.random.default_rng(700100)
    samples = rng.normal(size=(128, WINDOW))
    result: dict[str, Any] = {"seed": 700100, "frames": len(samples),
                              "rule": "max(14, empirical null q99 + 2); no test labels"}
    for model in ("tone", "chirp"):
        cfg = fit_config(16e9, model, 0.)
        scores = [fit_frame(y, cfg).detection_score for y in samples]
        result[model] = dict(threshold=max(14., float(np.quantile(scores, .99)) + 2),
                             scores=scores)
    return result


def analyze(record: SignalRecord, thresholds: dict[str, Any], *, size: int = WINDOW,
            hop: int = HOP) -> tuple[list[Row], Row]:
    fs = record.sample_rate_hz
    profile = replace(BALANCED_PROFILE, window_length_samples=size,
                      overlap_samples=size - hop, hop_samples=hop, nfft=2 * size,
                      minimum_frequency_hz=2 * fs / size,
                      maximum_frequency_hz=fs / 2 - 2 * fs / size)
    start = perf_counter()
    stft, peaks = frozen.frontend(record, profile)
    shared_s = perf_counter() - start
    start = perf_counter()
    mask = ((stft.frequency_hz >= profile.minimum_frequency_hz)
            & (stft.frequency_hz <= profile.maximum_frequency_hz))
    bins = stft.frequency_hz[mask]
    strongest = bins[np.argmax(abs(stft.spectrum[mask]), axis=0)]
    strongest_s = perf_counter() - start
    start = perf_counter()
    failure = ""
    try:
        p3 = frozen.consolidate(stft, peaks)
        inherited = p3.trajectories["M2"].frequency_hz
    except ValueError as exc:
        inherited = np.full(len(stft.time_s), np.nan)
        failure = str(exc)
    p3_s = perf_counter() - start
    rows: list[Row] = []
    for method, values in (("STFT_peak", strongest), ("Research_P3", inherited)):
        for i, (time, frequency) in enumerate(zip(stft.time_s, values, strict=True)):
            rows.append(dict(method=method, frame=i, time_s=float(time),
                             frequency_hz=float(frequency), candidate_frequency_hz=float(frequency),
                             sigma_hz=np.nan, chirp_hz_per_s=np.nan,
                             flag="HYPOTHESIS_UNCALIBRATED" if not failure else failure,
                             provenance="spectral_candidate", amplitude_v=np.nan,
                             detection_score=np.nan, residual_peak_score=np.nan,
                             residual_lag1=np.nan, residual_rms_v=np.nan))
    timings = {"shared_frontend_s": shared_s, "STFT_peak_s": strongest_s, "Research_P3_s": p3_s,
               "P3_failure": failure}
    for model in ("tone", "chirp"):
        start = perf_counter()
        cfg = fit_config(fs, model, thresholds[model]["threshold"], size)
        for i, time in enumerate(stft.time_s):
            y = record.voltage_v[i * hop:i * hop + size]
            result = fit_frame(y, cfg)
            rows.append(dict(method=f"VP_{model}", frame=i, time_s=float(time), **asdict(result)))
        timings[f"VP_{model}_s"] = perf_counter() - start
    return rows, timings


def synthetic_cases() -> list[Row]:
    cases: list[Row] = []
    index = 0
    for order in (1, 4):
        for fs in (16e9, 32e9):
            for snr in (-10., 0., 10., 20., 30.):
                for ratio in (.5, 1., 1.25, 1.5, 2., 3., 4., 6.):
                    for repeat in range(2):
                        index += 1
                        seed = 710000 + index
                        jitter = np.random.default_rng(seed + 900000).uniform(-.02, .02)
                        cases.append(dict(case_id=f"scan_{index:04d}", family="tone_scan",
                            seed=seed, frequency_hz=2e9 * (ratio + jitter), ratio_nominal=ratio,
                            acquisition=Acquisition(fs, 2e9, order, snr, 10, 4., 8),
                            chirp_hz_per_s=0., repeat=repeat))
    for family in ("fast_chirp", "competitor", "zero_response", "noise_only",
                   "strong_attenuation", "colored_noise", "coarse_adc", "clipping"):
        for repeat in range(8):
            index += 1
            config = Acquisition(16e9, 2e9, 4, 20., 10, 4., 8)
            row: Row = dict(case_id=f"stress_{index:04d}", family=family, seed=720000 + index,
                       frequency_hz=3.1e9, ratio_nominal=1.55, acquisition=config,
                       chirp_hz_per_s=0., repeat=repeat)
            if family == "fast_chirp":
                row["chirp_hz_per_s"] = 1.1e16
            if family == "competitor":
                row["competitor_ratio"] = .8
            if family == "zero_response":
                row["acquisition"] = replace(config, response="zero")
            if family == "noise_only":
                row["target_present"] = False
            if family == "strong_attenuation":
                row.update(frequency_hz=7.1e9, ratio_nominal=3.55,
                           acquisition=replace(config, snr_before_attenuation_db=-10.))
            if family == "colored_noise":
                row["colored_noise"] = True
                row["acquisition"] = replace(config, snr_before_attenuation_db=0.)
            if family == "coarse_adc":
                row["acquisition"] = replace(config, bits=4)
            if family == "clipping":
                row["acquisition"] = replace(config, full_scale_v=.01)
            cases.append(row)
    return cases


def run_synthetic(output: Path, calibration: dict[str, Any]) -> None:
    frames: list[Row] = []
    registrations = []
    for number, case in enumerate(synthetic_cases()):
        cfg = case["acquisition"]
        options = {k: v for k, v in case.items() if k in (
            "frequency_hz", "chirp_hz_per_s", "seed", "competitor_ratio",
            "target_present", "colored_noise")}
        generated = simulate(cfg, **options)
        record = SignalRecord(generated.time_s, generated.voltage_v)
        rows, timings = analyze(record, calibration)
        absent = cfg.response == "zero" or not generated.target_present
        for row in rows:
            center = row["frame"] * HOP + WINDOW // 2
            truth = float(generated.truth_hz[center])
            row.update(case_id=case["case_id"], family=case["family"], seed=case["seed"],
                       truth_hz=truth, frequency_ratio=truth / cfg.bandwidth_hz,
                       ratio_nominal=case["ratio_nominal"], bandwidth_hz=cfg.bandwidth_hz,
                       fs_hz=cfg.sample_rate_hz, order=cfg.order,
                       snr_pre_db=cfg.snr_before_attenuation_db,
                       no_signal=absent, alias_ambiguous=truth >= cfg.sample_rate_hz / 2,
                       tolerance_hz=max(50e6, .5 * cfg.sample_rate_hz / WINDOW),
                       clipped_fraction=generated.clipped_fraction,
                       apparent_velocity_m_s=row["frequency_hz"] * WAVELENGTH_M / 2,
                       corrected_velocity_m_s=np.nan,
                       truth_apparent_velocity_m_s=truth * WAVELENGTH_M / 2,
                       velocity_convention="SIMULATION:1550nm,offset0,+beat,no_window_correction")
        frames.extend(rows)
        registrations.append(dict(**{k: v for k, v in case.items() if k != "acquisition"},
                                  acquisition=asdict(cfg), phase_rad=generated.phase_rad,
                                  noise_sigma_v=generated.noise_sigma_v,
                                  clipped_fraction=generated.clipped_fraction, **timings))
        if number in (0, 80, 160, 240, 320, 328, 336, 344, 352):
            with (output / "data" / f"{case['case_id']}.npz").open("xb") as stream:
                np.savez_compressed(stream, time_s=generated.time_s, voltage_v=generated.voltage_v,
                                    noiseless_v=generated.noiseless_sampled_v,
                                    truth_hz=generated.truth_hz)
        if number % 40 == 0:
            print(f"synthetic {number}/{len(synthetic_cases())}", flush=True)
    csv_new(output / "output/frames.csv", frames)
    json_new(output / "output/registration.json", registrations)


def run_real(output: Path, calibration: dict[str, Any]) -> None:
    # Intervals are inherited context, never ground truth; full interior Nyquist search.
    cases = [("weak_late", "20260630-1.csv", 2, 3300e-9, 4980e-9),
             ("weak_competitor", "20260630-1.csv", 2, 1616e-9, 1950e-9),
             ("normal_high", "20221017a.dat", 1, 280e-9, 680e-9),
             ("complex", "ch3.csv", 1, 1000e-9, 1400e-9)]
    frames: list[Row] = []
    timings = []
    for name, filename, channel, low, high in cases:
        raw = np.loadtxt(ROOT / "data/raw" / filename, delimiter=",")
        relative = raw[:, 0] - raw[0, 0]
        mask = (relative >= low) & (relative <= high)
        # Explicitly crop contiguous samples; no resampling, interpolation, or unit change.
        record = SignalRecord(raw[mask, 0], raw[mask, channel])
        for size in (256, 512):
            rows, costs = analyze(record, calibration, size=size, hop=size)
            for row in rows:
                row.update(case_id=name, source=filename, channel_column=channel,
                           window_samples=size, time_relative_s=row["time_s"] - raw[0, 0],
                           apparent_velocity_m_s=np.nan, corrected_velocity_m_s=np.nan,
                           physical_status="REQUIRES_EXPERIMENTAL_CONFIRMATION",
                           bandwidth_hz="UNKNOWN", wavelength_m="UNKNOWN",
                           optical_offset_hz="UNKNOWN", anti_alias_confirmation="UNKNOWN",
                           threshold_status="256-sample null calibration; 512 is sensitivity only")
            frames.extend(rows)
            timings.append(dict(case_id=name, window_samples=size, **costs))
        print(f"real {name}", flush=True)
    csv_new(output / "output/real_frames.csv", frames)
    json_new(output / "output/real_costs.json", timings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("synthetic", "real", "all"), default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing existing output directory: {output}")
    for name in ("data", "output", "figures"):
        (output / name).mkdir(parents=True)
    calibration = calibrate()
    json_new(output / "output/calibration.json", calibration)
    print("null calibration complete", flush=True)
    if args.mode in ("synthetic", "all"):
        run_synthetic(output, calibration)
    if args.mode in ("real", "all"):
        run_real(output, calibration)


if __name__ == "__main__":
    main()
