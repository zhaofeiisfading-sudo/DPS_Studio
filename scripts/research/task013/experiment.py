"""Execute paired waveforms without ever passing truth into estimators."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
from typing import Any

import numpy as np
import scipy  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import event_detector
from .cases import Case, VELOCITY, load, plan_dict, specifications
from .stage import (METHODS, Trace, annotation_at, empty, frozen_estimate, grid, local_estimate,
                    recommended, route, run_all)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/TASK-013"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def metric(values: np.ndarray[Any, Any], truth: np.ndarray[Any, Any],
           other: np.ndarray[Any, Any], region: np.ndarray[Any, Any]) -> dict[str, Any]:
    target = region & np.isfinite(truth)
    finite = target & np.isfinite(values)
    error = (values[finite] - truth[finite]) * VELOCITY
    n, m = int(target.sum()), int(finite.sum())
    branch = target & np.isfinite(other) & (abs(truth - other) > 20e6)
    wrong = branch & np.isfinite(values) & (abs(values - other) < abs(values - truth))
    absent = region & ~np.isfinite(truth)
    return {"target_n": n, "finite_n": m, "sse_m2_s2": float(error @ error),
            "rmse_m_s": float(np.sqrt(np.mean(error**2))) if m else None,
            "coverage": m / n if n else None,
            "failure_n": n - m + int((abs(error) > 77.5).sum()),
            "failure_fraction": (n - m + int((abs(error) > 77.5).sum())) / n if n else None,
            "strict_15_n": n - m + int((abs(error) > 15.).sum()),
            "strict_38p75_n": n - m + int((abs(error) > 38.75).sum()),
            "branch_eligible_n": int(branch.sum()), "wrong_branch_n": int(wrong.sum()),
            "branch_missing_n": int((branch & ~np.isfinite(values)).sum()),
            "absent_n": int(absent.sum()),
            "absent_output_n": int((absent & np.isfinite(values)).sum())}


def onset_metrics(case: Case, trace: Trace) -> dict[str, Any]:
    idx = grid(case.signal)
    t = case.signal.time_s[idx]
    crossed = np.isfinite(trace.accepted_hz) & (trace.accepted_hz * VELOCITY >= 100.)
    positions = np.flatnonzero(crossed[:-1] & crossed[1:])
    detected = float(t[positions[0]]) if len(positions) else None
    expected: float | None = None
    if case.onset_s is not None:
        truth_cross = np.flatnonzero(np.isfinite(case.truth_hz) & (case.truth_hz * VELOCITY >= 100.))
        expected = float(case.signal.time_s[truth_cross[0]]) if len(truth_cross) else None
    error = (detected - expected) * 1e9 if detected is not None and expected is not None else None
    return {"physical_onset_s": case.onset_s, "truth_100m_s_crossing_s": expected,
            "detected_100m_s_crossing_s": detected, "onset_error_ns": error,
            "onset_abs_error_ns": abs(error) if error is not None else None,
            "onset_missed": int(expected is not None and detected is None),
            "onset_early": int(error is not None and error < -2.),
            "onset_eligible": int(expected is not None)}


def score(case: Case, traces: dict[str, Trace]) -> list[dict[str, Any]]:
    idx = grid(case.signal)
    labels = case.stage_truth[idx]
    regions = {"all": np.ones(len(idx), dtype=bool)}
    regions.update({str(label): labels == label for label in np.unique(labels)})
    result = []
    for name, trace in traces.items():
        for region, mask in regions.items():
            base = {"case": case.signal.name, "split": case.split, "family": case.family,
                    "method": name, "region": region, "status": "OK", "runtime_s": trace.runtime_s}
            for kind, values in (("candidate", trace.candidate_hz), ("supported", trace.accepted_hz)):
                row = {**base, "kind": kind,
                       **metric(values, case.truth_hz[idx], case.other_hz[idx], mask)}
                if region == "all" and kind == "supported":
                    row.update(onset_metrics(case, trace))
                result.append(row)
    return result


def execute(spec: tuple[str, str, int], destination: str) -> list[dict[str, Any]]:
    case = load(spec)
    folder = Path(destination) / "cases"
    folder.mkdir(exist_ok=True)
    before = hashlib.sha256(case.signal.voltage_v.tobytes()).hexdigest()
    started = time.perf_counter()
    try:
        traces = run_all(case.signal, case.plan)
        if before != hashlib.sha256(case.signal.voltage_v.tobytes()).hexdigest():
            raise AssertionError("Estimator mutated input waveform")
        raw_onset, event = event_detector(case.signal)
        write_json(folder / f"{case.signal.name}.json", {
            "case": case.signal.name, "family": case.family, "split": case.split,
            "metadata": case.metadata, "manual_plan": plan_dict(case.plan),
            "input_sha256": before, "input_unchanged": True,
            "raw_energy_onset_s": float(case.signal.time_s[raw_onset]) if raw_onset is not None else None,
            "raw_energy_event": event, "elapsed_s": time.perf_counter() - started,
        })
        arrays: dict[str, Any] = {
            "time_s": case.signal.time_s, "voltage_v": case.signal.voltage_v,
            "truth_hz": case.truth_hz, "other_hz": case.other_hz,
            "amplitude_v": case.amplitude_v, "centers": grid(case.signal),
            "stage_truth": case.stage_truth,
            "corrected_velocity_m_s": np.full(len(grid(case.signal)), np.nan),
        }
        for name, trace in traces.items():
            for key in ("candidate_hz", "accepted_hz", "chirp_hz_s", "quality", "r2",
                        "condition", "support_samples"):
                arrays[f"{name}__{key}"] = getattr(trace, key)
        with (folder / f"{case.signal.name}.npz").open("xb") as stream:
            np.savez_compressed(stream, **arrays)
        rows = score(case, traces)
        write_csv(folder / f"{case.signal.name}.csv", rows)
        return rows
    except Exception:
        error = traceback.format_exc()
        write_json(folder / f"{case.signal.name}.error.json", {"error": error})
        raise


def freeze(destination: Path, specs: list[tuple[str, str, int]]) -> None:
    hashes = {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((OUT / "repro").glob("*.py"))}
    hashes["PROTOCOL.md"] = hashlib.sha256((OUT / "PROTOCOL.md").read_bytes()).hexdigest()
    write_json(destination / "freeze.json", {
        "source_sha256": hashes, "specifications": specs,
        "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
        "platform": platform.platform(), "methods": METHODS,
        "threads": {key: os.environ.get(key) for key in
                    ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
    })


def evaluate(destination: Path, *, development: bool = False, workers: int = 4,
             limit: int | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    specs = specifications(development=development)
    if limit is not None:
        specs = specs[:limit]
    freeze(destination, specs)
    rows: list[dict[str, Any]] = []
    failures = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(execute, spec, str(destination)): spec for spec in specs}
        for i, future in enumerate(as_completed(futures), 1):
            spec = futures[future]
            try:
                rows.extend(future.result())
            except Exception:
                failures.append({"spec": spec, "error": traceback.format_exc()})
            if i % 8 == 0 or i == len(specs):
                print(json.dumps({"completed": i, "total": len(specs), "failed_cases": len(failures),
                                  "elapsed_s": round(time.perf_counter() - started, 1)}), flush=True)
    write_csv(destination / "metrics.csv", sorted(rows, key=lambda r:
              (r["split"], r["case"], r["method"], r["region"], r["kind"])))
    write_json(destination / "completion.json", {"cases": len(specs), "failed_cases": failures,
               "rows": len(rows), "methods": len(METHODS), "elapsed_s": time.perf_counter() - started})
    if failures:
        raise RuntimeError("Cases failed; retained failures must be investigated")


def single(case: Case, name: str) -> Trace:
    if name == "unobservable":
        return empty(len(grid(case.signal)))
    if name in METHODS[:5]:
        return frozen_estimate(case.signal, name)
    if name in METHODS[5:10]:
        return local_estimate(case.signal, case.plan, name)
    current = name == "current_map"
    required = {recommended(annotation_at(case.plan, float(case.signal.time_s[i])), current=current)
                for i in grid(case.signal)}
    traces = {method: single(case, method) for method in sorted(required)}
    return route(case.signal, case.plan, traces, current=current)


def benchmark(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    families = ("onset_step", "fast_accel", "fast_decel", "stable_plateau", "low_plateau",
                "weak_spur", "drifting_spur", "noise_only")
    freeze(destination, [("independent", family, 0) for family in families])
    rows = []
    for family in families:
        case = load(("independent", family, 0))
        for name in METHODS:
            for repeat in range(3):
                start = time.perf_counter()
                result = single(case, name)
                elapsed = time.perf_counter() - start
                rows.append({"family": family, "method": name, "repeat": repeat,
                             "runtime_s": elapsed, "centers": len(result.accepted_hz),
                             "cost_includes_initialization": True})
        print(json.dumps({"benchmark_family": family}), flush=True)
    write_csv(destination / "measurements.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("evaluate", "development", "benchmark"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.mode == "benchmark":
        benchmark(args.output)
    else:
        evaluate(args.output, development=args.mode == "development", workers=args.workers,
                 limit=args.limit)


if __name__ == "__main__":
    main()
