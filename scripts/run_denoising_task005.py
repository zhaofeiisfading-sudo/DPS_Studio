"""Reproduce TASK005 from immutable voltage files into a NEW scratch directory.

The scratch directory holds spectra/trajectories; delivery files are selected
separately. Existing results are never overwritten. A second invocation may add
the other phase to an existing matching TASK005 scratch run.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.analysis_profiles import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.core.io import read_delimited_signals
from dps_studio.research import denoising_task001 as bilateral
from dps_studio.research import denoising_task003 as risk
from dps_studio.research import task028_consolidation as frozen
from dps_studio.research.denoising_task005 import (
    BandConfig, BandObservations, BandSeed, make_observations, track_band,
)

ROOT = Path(__file__).resolve().parents[1]
FloatArray = NDArray[np.float64]
Row = dict[str, Any]
PROFILES = (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_csv(path: Path, rows: list[Row]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_bounds(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    changes = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int))).reshape(-1, 2)
    return [(int(a), int(b)) for a, b in changes]


def _paths(stft: Any, peaks: Any) -> dict[str, FloatArray]:
    result = frozen.consolidate(stft, peaks)
    paths = {"M0": result.trajectories["M0"].frequency_hz,
             "M1": result.trajectories["M2"].frequency_hz}
    proposals = bilateral.propose_repairs(stft, peaks, paths["M1"])
    paths["M2"], _ = bilateral.apply_repairs(peaks, paths["M1"], proposals)
    paths["M3"], _, _ = risk.risk_repair(peaks, paths["M1"], proposals)
    return paths


def _real_scores(meta: Row, case: Row, obs: BandObservations,
                 paths: dict[str, FloatArray], indices: NDArray[np.int64]) -> tuple[list[Row], Row]:
    t_ns = (obs.time_s - meta["start_s"]) * 1e9
    first, last = case["analysis_relative_ns"]
    q = (t_ns >= first) & (t_ns <= last)
    low, high = np.array(case["query_frequency_ghz"]) * 1e9
    rows: list[Row] = []
    for method, f in paths.items():
        finite = q & np.isfinite(f)
        inside = finite & (f >= low) & (f <= high)
        changed = finite & (abs(f - paths["M0"]) > 1.)
        runs = run_bounds(changed)
        longest = max(runs, key=lambda pair: pair[1] - pair[0], default=(0, 0))
        a, b = longest
        row = dict(domain="real_observational", case_id=case["case_id"], role=case["role"],
            filename=meta["filename"], channel=meta["channel"], profile=meta["profile"],
            method=method, frames=int(q.sum()), finite_frames=int(finite.sum()),
            missing_frames=int((q & ~np.isfinite(f)).sum()),
            coverage=float(finite.sum() / q.sum()), query_selected_frames=int(inside.sum()),
            outside_query_frames=int((finite & ~inside).sum()),
            changed_vs_strongest=int(changed.sum()),
            changed_vs_p3=int((finite & (abs(f-paths["M1"]) > 1.)).sum()),
            identical_to_strongest=int((finite & (f == paths["M0"])).sum()),
            longest_changed_run_frames=b-a,
            longest_changed_first_ns=float(t_ns[a]) if b > a else None,
            longest_changed_last_ns=float(t_ns[b-1]) if b > a else None,
            analysis_first_ns=first, analysis_last_ns=last,
            minimum_frequency_hz=meta["minimum_hz"], maximum_frequency_hz=meta["maximum_hz"])
        rows.append(row)
    selected = q & (indices >= 0)
    frames = np.flatnonzero(selected)
    bg = obs.candidate_background_db[frames, indices[selected]]
    selected_f = paths["N5"]
    changed = selected & (abs(selected_f - paths["M0"]) > 1.)
    original_out = (paths["M0"] < low) | (paths["M0"] > high)
    branch_switch = changed & original_out & (selected_f >= low) & (selected_f <= high)
    info = dict(case_id=case["case_id"], profile=meta["profile"],
        selected_bg_min_db=float(bg.min()) if len(bg) else None,
        selected_bg_median_db=float(np.median(bg)) if len(bg) else None,
        selected_candidate_rank_median=float(np.median(indices[selected]+1)) if len(bg) else None,
        conditional_branch_switch_frames=int(branch_switch.sum()),
        finite_first_ns=float(t_ns[frames[0]]) if len(frames) else None,
        finite_last_ns=float(t_ns[frames[-1]]) if len(frames) else None)
    return rows, info


def run_real(config: Row, work: Path, raw_root: Path) -> None:
    folder = work / "real"
    folder.mkdir(exist_ok=False)
    cfg = BandConfig(**config["algorithm_config"])
    manifest: list[Row] = []
    metrics: list[Row] = []
    details: list[Row] = []
    primary_changes: list[Row] = []
    for item in config["raw_files"]:
        path = raw_root / item["filename"]
        if sha256(path) != item["sha256"]:
            raise ValueError(f"Raw SHA-256 mismatch: {path}")
        imported = read_delimited_signals(path, **item["reader"])
        for channel, record in imported.records.items():
            print(f"REAL {path.name} / {channel}", flush=True)
            pair: dict[str, Any] = {}
            for base_profile in PROFILES:
                p = replace(base_profile, minimum_frequency_hz=item["minimum_frequency_hz"],
                            maximum_frequency_hz=item["maximum_frequency_hz"])
                stft, peaks = frozen.frontend(record, p)
                pair[p.profile_id.value] = (stft, peaks, make_observations(stft, peaks),
                                             _paths(stft, peaks))
            case = next((c for c in config["real_cases"] if c["filename"] == path.name
                         and c["channel"] == channel), None)
            for profile_name, (stft, peaks, obs, paths) in pair.items():
                other = next(value[2] for key, value in pair.items() if key != profile_name)
                seed = (BandSeed(record.start_time_s + case["seed_relative_ns"] * 1e-9,
                        case["seed_frequency_ghz"] * 1e9, case["seed_frequency_tolerance_hz"])
                        if case else None)
                result = track_band(obs, seed=seed, config=cfg, companion=other)
                mono = track_band(obs, seed=seed, config=cfg)
                auto = track_band(obs, config=cfg, companion=other)
                auto_single = track_band(obs, config=cfg)
                paths.update(N5=result.frequency_hz, mono5=mono.frequency_hz,
                             auto5=auto.frequency_hz, auto_single=auto_single.frequency_hz)
                finite = result.candidate_indices >= 0
                selected = obs.candidate_frequency_hz[
                    np.flatnonzero(finite), result.candidate_indices[finite]]
                np.testing.assert_array_equal(result.frequency_hz[finite], selected)
                tag = path.stem + "__" + channel + "__" + profile_name
                meta = dict(tag=tag, filename=path.name, channel=channel, profile=profile_name,
                    start_s=record.start_time_s, frames=len(obs.time_s),
                    sample_rate_hz=record.sample_rate_hz, window_samples=stft.window_length_samples,
                    resolution_hz=obs.resolution_hz, minimum_hz=item["minimum_frequency_hz"],
                    maximum_hz=item["maximum_frequency_hz"], raw_sha256=item["sha256"],
                    case_id=case["case_id"] if case else None,
                    role=case["role"] if case else "screening_only", mode=result.mode,
                    diagnostics=result.diagnostics, auto_diagnostics=auto.diagnostics,
                    automatic_finite_frames=int(np.isfinite(auto.frequency_hz).sum()),
                    automatic_single_finite_frames=int(np.isfinite(auto_single.frequency_hz).sum()))
                manifest.append(meta)
                amplitude = np.full(obs.candidate_frequency_hz.shape, np.nan)
                for i, frame in enumerate(peaks.candidates_by_frame):
                    for j, candidate in enumerate(frame):
                        amplitude[i, j] = candidate.peak_amplitude
                with (folder / (tag + ".npz")).open("xb") as stream:
                    np.savez_compressed(stream, time_s=obs.time_s,
                        frequency_hz=obs.grid_frequency_hz, magnitude=obs.magnitude.astype(np.float32),
                        candidate_f=obs.candidate_frequency_hz, candidate_bg=obs.candidate_background_db,
                        candidate_bin=obs.candidate_bin_indices, candidate_amp=amplitude,
                        selected_indices=result.candidate_indices, tube_support=result.tube_support_fraction,
                        companion_support=result.candidate_companion_support,
                        flags=np.array(result.quality_flags), **paths)
                if case:
                    rows, info = _real_scores(meta, case, obs, paths, result.candidate_indices)
                    metrics.extend(rows)
                    details.append(info)
                    if case["case_id"] == "D1":
                        t_ns = (obs.time_s-record.start_time_s) * 1e9
                        first, last = case["analysis_relative_ns"]
                        mask = finite & (t_ns >= first) & (t_ns <= last)
                        mask &= abs(result.frequency_hz-paths["M0"]) > 1.
                        for selected_frame in np.flatnonzero(mask):
                            i = int(selected_frame)
                            j = int(result.candidate_indices[i])
                            primary_changes.append(dict(profile=profile_name, frame=i,
                                relative_time_ns=float(t_ns[i]), strongest_hz=float(paths["M0"][i]),
                                p3_hz=float(paths["M1"][i]), new_hz=float(result.frequency_hz[i]),
                                delta_hz=float(result.frequency_hz[i]-paths["M0"][i]),
                                original_candidate_rank=j+1, candidate_bg_db=float(obs.candidate_background_db[i,j]),
                                selected_amplitude_ratio=float(amplitude[i,j]/amplitude[i,0]),
                                tube_support=float(result.tube_support_fraction[i]),
                                flags=result.quality_flags[i]))
    write_json(work / "real_manifest.json", manifest)
    write_json(work / "real_case_details.json", details)
    write_csv(work / "real_metrics.csv", metrics)
    write_csv(work / "Figure01_changes.csv", primary_changes)


def run_synthetic(config: Row, work: Path) -> None:
    from dps_studio.research.denoising_task005_benchmark import (
        frame_truth, generate, registration, score_path,
    )

    folder = work / "synthetic"
    folder.mkdir(exist_ok=False)
    cfg = BandConfig(**config["algorithm_config"])
    rows: list[Row] = []
    registry = registration()
    write_json(work / "synthetic_registration.json", registry)
    write_json(work / "synthetic_generator.json", dict(
        generator_sha256=sha256(ROOT / "src/dps_studio/research/denoising_task005_benchmark.py"),
        registered_utc=datetime.now(timezone.utc).isoformat(),
        algorithm_source_sha256=config["algorithm_source_sha256"]))
    for registered in registry:
        case = generate(registered["family"], registered["seed"])
        print(f"AUX {case.case_id}", flush=True)
        pair: dict[str, Any] = {}
        for base in PROFILES:
            analysis_profile = replace(base, minimum_frequency_hz=.2e9, maximum_frequency_hz=6e9)
            stft, peaks = frozen.frontend(case.record, analysis_profile)
            pair[analysis_profile.profile_id.value] = (stft, peaks, make_observations(stft, peaks), _paths(stft, peaks))
        seed = BandSeed(case.seed_time_s, case.seed_frequency_hz)
        for profile_name, (stft, peaks, obs, paths) in pair.items():
            other = next(value[2] for key, value in pair.items() if key != profile_name)
            result = track_band(obs, seed=seed, config=cfg, companion=other)
            paths["N5"] = result.frequency_hz
            labels = frame_truth(case, obs.time_s, stft.window_length_samples)
            for method, f in paths.items():
                score = score_path(f, labels["truth_hz"], baseline=paths["M0"],
                    tolerance_hz=config["synthetic"]["tolerance_hz"], absent_mask=labels["target_absent"])
                relative_p3 = score_path(f, labels["truth_hz"], baseline=paths["M1"],
                    tolerance_hz=config["synthetic"]["tolerance_hz"], absent_mask=labels["target_absent"])
                rows.append(dict(domain="synthetic_known_truth", case_id=case.case_id,
                    family=case.family, seed=case.seed, profile=profile_name, method=method,
                    mixed_window_frames=int(labels["mixed_window"].sum()), **score,
                    corrected_vs_p3=relative_p3["corrected_frames"],
                    harmed_vs_p3=relative_p3["harmed_frames"],
                    abstained_previously_correct_p3=relative_p3["abstained_previously_correct"]))
            with (folder / (case.case_id + "__" + profile_name + ".npz")).open("xb") as stream:
                np.savez_compressed(stream, time_s=obs.time_s, frequency_hz=obs.grid_frequency_hz,
                    magnitude=obs.magnitude.astype(np.float32), truth=labels["truth_hz"],
                    target_absent=labels["target_absent"], mixed_window=labels["mixed_window"],
                    seed_time_s=case.seed_time_s, seed_frequency_hz=case.seed_frequency_hz,
                    indices=result.candidate_indices, flags=np.array(result.quality_flags), **paths)
    write_csv(work / "synthetic_metrics.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research/denoising_task005.json")
    parser.add_argument("--raw-root", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--phase", choices=("real", "synthetic", "all"), default="all")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if sha256(ROOT / "src/dps_studio/research/denoising_task005.py") != config["algorithm_source_sha256"]:
        raise ValueError("TASK005 inference source differs from the frozen configuration")
    marker = args.work_dir / "task005_run.json"
    config_sha = sha256(args.config)
    if args.work_dir.exists():
        if not marker.is_file() or json.loads(marker.read_text())["config_sha256"] != config_sha:
            raise FileExistsError("Work directory must be new or a matching TASK005 scratch run")
    else:
        args.work_dir.mkdir(parents=True)
        write_json(marker, dict(task="TASK-005", created_utc=datetime.now(timezone.utc).isoformat(),
            config_sha256=config_sha, algorithm_source_sha256=config["algorithm_source_sha256"]))
    if args.phase in ("real", "all"):
        run_real(config, args.work_dir, args.raw_root)
    if args.phase in ("synthetic", "all"):
        run_synthetic(config, args.work_dir)


if __name__ == "__main__":
    main()
