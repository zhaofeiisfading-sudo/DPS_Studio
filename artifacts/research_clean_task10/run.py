"""Reproduce TASK-010 into a new directory; never overwrite prior results."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import scipy  # type: ignore[import-untyped]

from artifacts.research_clean_task8.catalog import METHODS, run_folder
from artifacts.research_clean_task8.common import Signal, event_detector
from artifacts.research_clean_task8.data import FAMILIES, Case, generate
from artifacts.research_clean_task10.audit import OUT, ROOT, sha, write_json
from artifacts.research_clean_task10.experiment import (
    HOPS,
    VELOCITY,
    WINDOWS,
    Spec,
    Trace,
    adaptive,
    common_centers,
    error_correlation,
    estimate,
    evaluate,
    metric,
    onset_threshold,
)

T8 = ROOT / "artifacts/research_clean_task8"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def select(trace: Trace, hop: int) -> Trace:
    if hop % trace.spec.hop:
        raise ValueError("Trace view must select exact, nested raw indices")
    take = np.arange(0, len(trace.indices), hop // trace.spec.hop)
    return Trace(replace(trace.spec, hop=hop), trace.indices[take], trace.frequency_hz[take],
                 trace.discrete_hz[take], trace.accepted_hz[take], trace.contrast_db[take],
                 trace.peak_power_v2[take], trace.r2[take], trace.condition[take],
                 trace.flags[take], trace.runtime_s if hop == trace.spec.hop else 0.)


def save_trace(path: Path, trace: Trace, signal: Signal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.savez_compressed(stream, sample_indices=trace.indices,
            time_s=signal.time_s[trace.indices], frequency_hz=trace.frequency_hz,
            discrete_hz=trace.discrete_hz, accepted_hz=trace.accepted_hz,
            apparent_velocity_m_s=trace.frequency_hz * VELOCITY,
            supported_apparent_velocity_m_s=trace.accepted_hz * VELOCITY,
            corrected_velocity_m_s=np.full(len(trace.indices), np.nan),
            contrast_db=trace.contrast_db, peak_power_v2=trace.peak_power_v2,
            r2=trace.r2, condition=trace.condition, flags=trace.flags)


def frozen_case(stage: str, family: str, instance: int) -> Case:
    name = f"{'stress' if stage == 'phase_stress' else 'fresh'}_{family}_{instance:02d}"
    folder = T8 / "datasets" / stage
    info = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    with np.load(folder / f"{name}.npz") as z:
        return Case(Signal(z["time_s"], z["voltage_v"], name), z["truth_hz"],
                    z["other_hz"], z["amplitude_v"], info["onset_s"], family,
                    info["seed"], info)


def response(trace: Trace, signal: Signal, event: float = 105e-9) -> dict[str, Any]:
    time_s = signal.time_s[trace.indices]
    region = (time_s >= event - 40e-9) & (time_s <= event + 40e-9)
    out: dict[str, Any] = {}
    for label, frequency in (("candidate", trace.frequency_hz), ("supported", trace.accepted_hz)):
        velocity = frequency * VELOCITY
        positions: list[float | None] = []
        for fraction in (.1, .5, .9):
            take = np.flatnonzero(region & (velocity >= 240 + fraction * (1150 - 240)))
            crossing = float(time_s[take[0]]) if len(take) else None
            positions.append(crossing)
            out[f"{label}_t{int(fraction * 100)}_error_ns"] = (crossing - event) * 1e9 \
                if crossing is not None else None
        out[label + "_10_90_width_ns"] = (positions[2] - positions[0]) * 1e9 \
            if positions[2] is not None and positions[0] is not None else None
        vals = velocity[region & np.isfinite(velocity)]
        out[label + "_nonmonotone_drops_over_50_m_s"] = int((np.diff(vals) < -50).sum())
        out[label + "_transition_coverage"] = float(np.isfinite(velocity[region]).mean())
    return out


def evaluate_case(case: Case, stage: str, destination: Path, config: dict[str, Any],
                  rows: list[dict[str, Any]], shock_rows: list[dict[str, Any]]) -> None:
    signal = case.signal
    case_id = signal.name
    print(json.dumps(dict(event="case_start", stage=stage, case_id=case_id)), flush=True)
    dataset = destination / "datasets" / stage / f"{case_id}.npz"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    with dataset.open("xb") as stream:
        np.savez_compressed(stream, time_s=signal.time_s, voltage_v=signal.voltage_v,
                            truth_hz=case.truth_hz, amplitude_v=case.amplitude_v)
    write_json(dataset.with_suffix(".json"), dict(onset_s=case.onset_s, seed=case.seed,
               family=case.family, **{k: v for k, v in case.metadata.items()
                                      if k not in ("onset_s", "seed", "family")}))
    onset, event = event_detector(signal)
    write_json(destination / "events" / stage / f"{case_id}.json", event)
    initial = hashlib.sha256(signal.voltage_v.tobytes()).hexdigest()
    local_rows: list[dict[str, Any]] = []
    traces: dict[str, Trace] = {}
    windows = config["confirmation"]["windows"] if stage == "confirmation" else WINDOWS
    hops = config["confirmation"]["hops"] if stage == "confirmation" else HOPS

    def record(trace: Trace, threshold: float, stored: Path, reused: bool = False,
               dense_s: float | None = None) -> None:
        row = evaluate(signal, trace, case.truth_hz, case.family, case.onset_s,
                       case.metadata["events_s"], threshold, onset)
        row.update(stage=stage, case_id=case_id, family=case.family, seed=case.seed,
                   snr_db=case.metadata["snr_db"],
                   highpass_cutoff_hz=case.metadata["highpass_cutoff_hz"],
                   truth_onset_s=case.onset_s, status="OK", compute_reused=reused,
                   trajectory=stored.relative_to(destination).as_posix(),
                   shared_dense_compute_s=dense_s)
        if reused:
            row["runtime_s"] = None
        row.update(error_correlation(trace, case.truth_hz, case.family, signal.fs, case.onset_s))
        local_rows.append(row)
        if case.family == "two_shock":
            shock_rows.append(dict(stage=stage, case_id=case_id, **trace.spec.parameters(signal.fs),
                                   **response(trace, signal)))

    for width in windows:
        dense_hop = 32 if stage == "confirmation" else 1
        dense = estimate(signal, Spec(width, dense_hop),
                         batch_frames=config["batch_frames"], onset=onset)
        path = destination / "trajectories" / stage / case_id / (dense.spec.name + ".npz")
        save_trace(path, dense, signal)
        threshold = onset_threshold(select(dense, 128))
        for hop in hops:
            view = select(dense, hop)
            record(view, threshold, path, hop != dense_hop, dense.runtime_s)
        traces[Spec(width, 32).name] = select(dense, 32)
    if stage != "confirmation":
        for label, demean in (("wide_raw", False), ("wide_demean", True)):
            for width in WINDOWS:
                trace = estimate(signal, Spec(width, 32, minimum_hz=5e6, maximum_hz=8e9,
                                              demean=demean, label=label),
                                 batch_frames=config["batch_frames"], onset=onset)
                path = destination / "trajectories" / stage / case_id / (trace.spec.name + ".npz")
                save_trace(path, trace, signal)
                record(trace, onset_threshold(select(trace, 128)), path)
                traces[trace.spec.name] = trace
        for width, hop, nfft in config["fft_controls"]:
            trace = estimate(signal, Spec(width, hop, nfft, label="fft_control"),
                             batch_frames=config["batch_frames"], onset=onset)
            path = destination / "trajectories" / stage / case_id / (trace.spec.name + ".npz")
            save_trace(path, trace, signal)
            record(trace, onset_threshold(select(trace, 128)), path)
        short = traces[Spec(512, 32, minimum_hz=5e6, maximum_hz=8e9,
                            demean=True, label="wide_demean").name]
        long = traces[Spec(2048, 32, minimum_hz=5e6, maximum_hz=8e9,
                           demean=True, label="wide_demean").name]
        combined = adaptive(short, long, signal, onset)
        path = destination / "trajectories" / stage / case_id / (combined.spec.name + ".npz")
        save_trace(path, combined, signal)
        record(combined, onset_threshold(select(long, 128)), path, reused=True)
    if initial != hashlib.sha256(signal.voltage_v.tobytes()).hexdigest():
        raise AssertionError("Input voltage mutated")
    write_csv(destination / "cases" / stage / f"{case_id}.csv", local_rows)
    rows.extend(local_rows)
    print(json.dumps(dict(event="case_done", stage=stage, case_id=case_id,
                          configurations=len(local_rows))), flush=True)


def frozen_rescore(destination: Path) -> None:
    rows = []
    checks = []
    for stage in ("fresh", "phase_stress"):
        cases = [(f, i) for f in FAMILIES for i in range(8)] if stage == "fresh" else [
            ("low_ramp", i) for i in range(50)]
        for family, instance in cases:
            case = frozen_case(stage, family, instance)
            grid = common_centers(len(case.signal.time_s))
            for method in METHODS:
                path = run_folder(T8, method, stage, case.signal.name) / "trajectory.npz"
                with np.load(path) as saved:
                    positions = np.searchsorted(saved["sample_indices"], grid)
                    np.testing.assert_array_equal(saved["sample_indices"][positions], grid)
                    row: dict[str, Any] = dict(stage=stage, case_id=case.signal.name,
                        family=family, name="frozen::" + method, method=method,
                        provenance="UNCHANGED_TASK008_TRAJECTORY", source_sha256=sha(path))
                    for state, key in (("candidate", "frequency_hz"), ("supported", "accepted_hz")):
                        for region, mask in (("motion", np.ones(len(grid), dtype=bool)),
                                             ("low", case.truth_hz[grid] * VELOCITY < 200)):
                            row.update(metric(saved[key][positions], case.truth_hz[grid], mask,
                                              f"common_{state}_{region}_"))
                    rows.append(row)
                    if method in ("stft512", "stft768"):
                        width = 512 if method == "stft512" else 768
                        folder = destination / "trajectories" / stage / case.signal.name
                        with np.load(folder / (Spec(width, 1).name + ".npz")) as new:
                            p = np.searchsorted(new["sample_indices"], grid)
                            old_f, new_f = saved["frequency_hz"][positions], new["frequency_hz"][p]
                            np.testing.assert_allclose(old_f, new_f, rtol=1e-12, atol=1e-3,
                                                       equal_nan=True)
                            valid = np.isfinite(old_f) & np.isfinite(new_f)
                            checks.append(dict(stage=stage, case_id=case.signal.name, method=method,
                                nan_pattern_equal=bool(np.array_equal(np.isnan(old_f), np.isnan(new_f))),
                                max_abs_difference_hz=float(np.max(abs(old_f[valid] - new_f[valid])))
                                if valid.any() else 0.))
    write_csv(destination / "tables/frozen_common_rescored.csv", rows)
    write_json(destination / "checks/frozen_strict_equivalence.json", checks)
    for filename in ("all_fresh_metrics.csv", "all_phase_stress_metrics.csv", "all_real_metrics.csv",
                     "fresh_summary.csv", "phase_stress_summary.csv", "fresh_paired_bootstrap.csv"):
        target = destination / "frozen_tables" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((T8 / "tables" / filename).read_bytes())


def run_raw(destination: Path, config: dict[str, Any]) -> None:
    from dps_studio.research.task009_data import inventory
    records = [r for r in inventory() if r["kind"] == "RAW"]
    actual = sorted(p.resolve() for p in (ROOT / "data/raw").rglob("*")
                    if p.is_file() and p.suffix.lower() in (".csv", ".dat")
                    and "result" not in p.name.lower())
    indexed = {str((ROOT / r["local_path"]).resolve()) for r in records}
    if not all(str(p) in indexed for p in actual):
        raise AssertionError("A genuine data/raw file is missing from the input index")
    rows: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for ri, record in enumerate(records):
        path = ROOT / record["local_path"]
        matrix = np.loadtxt(path, delimiter=",", ndmin=2)
        if sha(path) != record["sha256"]:
            raise AssertionError("Raw input SHA mismatch")
        for column in range(1, matrix.shape[1]):
            case_id = f"raw{ri:02d}_{path.stem}_ch{column}"
            signal = Signal(np.array(matrix[:, 0]), np.array(matrix[:, column]), case_id)
            onset, event = event_detector(signal)
            write_json(destination / "events/real" / f"{case_id}.json", event)
            inputs.append(dict(case_id=case_id, path=record["local_path"], sha256=record["sha256"],
                               column=column, samples=len(matrix), sample_rate_hz=signal.fs))
            print(json.dumps(dict(event="real_start", case_id=case_id)), flush=True)
            specs = [Spec(w, h) for w, h in config["raw_specs"]]
            specs += [Spec(w, 32, minimum_hz=5e6, maximum_hz=8e9, demean=True,
                           label="wide_demean") for w in (512, 2048)]
            cache: dict[str, Trace] = {}
            thresholds: dict[tuple[str, int], float] = {}
            for spec in specs:
                trace = estimate(signal, spec, batch_frames=config["batch_frames"], onset=onset)
                key = (spec.label, spec.window)
                if key not in thresholds:
                    ref = trace if spec.hop == 128 else select(trace, 128)
                    thresholds[key] = onset_threshold(ref)
                folder = destination / "trajectories/real" / case_id
                save_trace(folder / (spec.name + ".npz"), trace, signal)
                row = evaluate(signal, trace, None, "REAL_NO_GT", None, [], thresholds[key], onset)
                row.update(case_id=case_id, stage="real", status="OK", source_sha256=record["sha256"],
                           raw_path=record["local_path"], voltage_column=column,
                           trajectory=(folder / (spec.name + ".npz")).relative_to(destination).as_posix(),
                           physical_calibration="UNCONFIRMED", compute_reused=False)
                rows.append(row)
                cache[spec.name] = trace
            combined = adaptive(cache[specs[-2].name], cache[specs[-1].name], signal, onset)
            save_trace(folder / (combined.spec.name + ".npz"), combined, signal)
            row = evaluate(signal, combined, None, "REAL_NO_GT", None, [],
                           thresholds[("wide_demean", 2048)], onset)
            row.update(case_id=case_id, stage="real", status="OK", raw_path=record["local_path"],
                       voltage_column=column, source_sha256=record["sha256"], compute_reused=True,
                       physical_calibration="UNCONFIRMED",
                       trajectory=(folder / (combined.spec.name + ".npz")).relative_to(destination).as_posix())
            rows.append(row)
            write_csv(destination / "cases/real" / f"{case_id}.csv", [r for r in rows if r["case_id"] == case_id])
    write_csv(destination / "tables/real_metrics.csv", rows)
    write_csv(destination / "tables/raw_streams.csv", inputs)
    write_json(destination / "checks/raw_input_completeness.json", dict(
        physical_raw_files=len(actual), indexed_raw_files=len(records), streams=len(inputs),
        all_physical_raw_included=True, additional_archived_raw=len(records) - len(actual)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists() or not destination.is_relative_to(OUT):
        parser.error("Output must be a new TASK-010 subdirectory")
    from dps_studio.research.task009_runtime import assert_local, source_guard
    assert_local()
    sys.addaudithook(source_guard)
    config = json.loads((OUT / "config.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "config.json", config)
    write_json(destination / "environment.json", dict(python=sys.version, executable=sys.executable,
        numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform(),
        threads={k: os.environ.get(k) for k in
                 ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
        branch=__import__("subprocess").check_output(["git", "branch", "--show-current"], text=True).strip(),
        started_local=time.strftime("%Y-%m-%d %H:%M:%S"), clock_timezone="execution_host"))
    for source in (OUT / "experiment.py", OUT / "run.py", OUT / "config.json", OUT / "PROTOCOL.md"):
        target = destination / "source_snapshot" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
    rows: list[dict[str, Any]] = []
    shock_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    jobs = [("fresh", f, i) for f in FAMILIES for i in range(1 if args.smoke else 8)]
    if not args.smoke:
        jobs += [("phase_stress", "low_ramp", i) for i in range(50)]
        jobs += [("confirmation", f, i) for f in config["confirmation"]["families"]
                 for i in config["confirmation"]["instances"]]
    for stage, family, instance in jobs:
        try:
            case = generate(family, instance) if stage == "confirmation" else frozen_case(stage, family, instance)
            evaluate_case(case, stage, destination, config, rows, shock_rows)
        except Exception as exc:
            failure = dict(stage=stage, family=family, instance=instance,
                           reason=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
            failures.append(failure)
            write_json(destination / "failures" / f"{stage}_{family}_{instance}.json", failure)
            print(json.dumps(failure), flush=True)
    write_csv(destination / "tables/synthetic_metrics.csv", rows)
    write_csv(destination / "tables/shock_response.csv", shock_rows)
    write_json(destination / "checks/exceptions.json", failures)
    if not args.smoke and not failures:
        frozen_rescore(destination)
        run_raw(destination, config)
    write_json(destination / "completion.json", dict(completed=True, smoke=args.smoke,
        synthetic_cases=len(jobs), synthetic_records=len(rows), exceptions=len(failures)))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
