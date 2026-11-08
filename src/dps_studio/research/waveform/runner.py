"""Exclusive-write experiments. Truth is provided only to the external scorer."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .audit import OUT, ROOT, sha
from dps_studio.algorithms.waveform.common import METHODS, WAVELENGTH_M, Context, Estimate, Float, Signal
from .data import FAMILIES, Case, generate, inventory, read_raw
from dps_studio.algorithms import waveform


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False,
                  default=lambda obj: obj.item() if isinstance(obj, np.generic) else str(obj))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        pd.DataFrame(rows).to_csv(handle, index=False)


def array_hash(x: Float) -> str:
    return hashlib.sha256(x.tobytes()).hexdigest()


def metric(values: Float, truth: Float, region: np.ndarray[Any, Any],
           prefix: str) -> dict[str, Any]:
    target = region & np.isfinite(truth)
    valid = target & np.isfinite(values)
    n, finite = int(sum(target)), int(sum(valid))
    error = values[valid]-truth[valid]
    wrong = int(sum(abs(error) > 100e6))
    result: dict[str, Any] = {prefix+"target_n": n, prefix+"finite_n": finite,
        prefix+"sse_hz2": float(error@error), prefix+"rmse_m_s": (
            float(np.sqrt(np.mean(error**2))*WAVELENGTH_M/2) if finite else None),
        prefix+"coverage": finite/n if n else None,
        prefix+"wrong_finite_n": wrong, prefix+"failure_n": wrong+n-finite,
        prefix+"failure_fraction": (wrong+n-finite)/n if n else None}
    for threshold in (50e6, 200e6):
        result[prefix+f"failure_{int(threshold/1e6)}mhz_n"] = int(sum(abs(error)>threshold))+n-finite
    return result


def score(context: Context, estimate: Estimate, case: Case | None) -> dict[str, Any]:
    f, accepted = estimate.frequency_hz, estimate.accepted_hz
    row: dict[str, Any] = dict(frames=len(f), candidate_finite_n=int(np.isfinite(f).sum()),
                               accepted_finite_n=int(np.isfinite(accepted).sum()),
                               candidate_coverage=float(np.mean(np.isfinite(f))),
                               accepted_coverage=float(np.mean(np.isfinite(accepted))),
                               detected_onset_s=estimate.onset_s,
                               frequency_median_hz=float(np.nanmedian(f)) if np.isfinite(f).any() else None,
                               raw_fit_r2_median=float(np.nanmedian(estimate.extra["r2"]))
                               if np.isfinite(estimate.extra["r2"]).any() else None,
                               jumps_over_500mhz=int(sum(abs(np.diff(f))>500e6)),
                               source_time_sha256=array_hash(context.signal.time_s),
                               source_voltage_sha256=array_hash(context.signal.voltage_v))
    if case is None:
        row.update(domain="REAL_NO_GT", accuracy_claim="UNAVAILABLE",
                   equivalent_velocity_wavelength_m=WAVELENGTH_M)
        return row
    truth = case.truth_hz[context.centers]
    amp = case.amplitude_v[context.centers]
    all_region = np.ones(len(f), dtype=bool)
    onset = (context.time_s >= case.onset_s) & (context.time_s < case.onset_s+40e-9) \
        if case.onset_s is not None else np.zeros(len(f), dtype=bool)
    fast = np.zeros(len(f), dtype=bool)
    for event in case.metadata["events_s"]:
        fast |= abs(context.time_s-event) < 10e-9
    if case.family == "fast_accel" and case.onset_s is not None:
        fast |= (context.time_s > case.onset_s) & (context.time_s < case.onset_s+45e-9)
    low = np.isfinite(truth) & (truth*WAVELENGTH_M/2 < 200)
    for label, region in (("motion", all_region), ("onset40", onset),
                           ("fast", fast), ("low", low)):
        row.update(metric(f, truth, region, "candidate_"+label+"_"))
        row.update(metric(accepted, truth, region, "accepted_"+label+"_"))
    static = ~np.isfinite(truth)
    dropout = np.isfinite(truth) & (amp == 0)
    row.update(domain="SYNTHETIC_KNOWN_GT", family=case.family, seed=case.seed,
               truth_onset_s=case.onset_s,
               onset_error_ns=(estimate.onset_s-case.onset_s)*1e9
               if estimate.onset_s is not None and case.onset_s is not None else None,
               missed_onset=case.onset_s is not None and estimate.onset_s is None,
               false_event=case.onset_s is None and estimate.onset_s is not None,
               static_n=int(sum(static)), static_accepted_n=int(sum(static & np.isfinite(accepted))),
               dropout_n=int(sum(dropout)), dropout_accepted_n=int(sum(dropout & np.isfinite(accepted))))
    return row


def save_result(folder: Path, context: Context, estimate: Estimate) -> None:
    folder.mkdir(parents=True, exist_ok=False)
    arrays: dict[str, Any] = dict(time_s=context.time_s, sample_indices=context.centers,
        frequency_hz=estimate.frequency_hz, accepted_hz=estimate.accepted_hz,
        equivalent_apparent_velocity_m_s=estimate.frequency_hz*WAVELENGTH_M/2,
        accepted_equivalent_apparent_velocity_m_s=estimate.accepted_hz*WAVELENGTH_M/2,
        corrected_velocity_m_s=np.full(len(context.centers), np.nan),
        flags=estimate.flags, **estimate.extra)
    with (folder/"trajectory.npz").open("xb") as handle:
        np.savez_compressed(handle, **arrays)
    write_json(folder/"diagnostics.json", {"method": estimate.details, "event": context.event})


def evaluate_signal(signal: Signal, stage: str, case_id: str,
                    case: Case | None, source: dict[str, Any]) -> list[dict[str, Any]]:
    initial = array_hash(signal.time_s), array_hash(signal.voltage_v)
    start = time.perf_counter()
    context = Context(signal)
    setup_s = time.perf_counter()-start
    rows = []
    for name in METHODS:
        module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
        start = time.perf_counter()
        row: dict[str, Any] = dict(stage=stage, case_id=case_id, method=name, setup_s=setup_s,
                                   **source)
        folder = OUT/name/"runs"/stage/case_id
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = module.run(context)
            elapsed = time.perf_counter()-start
            row.update(score(context, result, case), status="OK", estimator_s=elapsed,
                       total_s=setup_s+elapsed)
            result.details["runtime_warnings"] = [str(w.message) for w in caught]
            save_result(folder, context, result)
            write_json(folder/"metrics.json", row)
        except Exception as exc:
            elapsed = time.perf_counter()-start
            row.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}",
                       estimator_s=elapsed, total_s=setup_s+elapsed,
                       domain="REAL_NO_GT" if case is None else "SYNTHETIC_KNOWN_GT")
            write_json(folder/"failure.json", {**row, "traceback": traceback.format_exc()})
        rows.append(row)
    if initial != (array_hash(signal.time_s), array_hash(signal.voltage_v)):
        raise AssertionError("Raw in-memory input changed")
    write_json(OUT/"checks"/stage/f"{case_id}_input_invariance.json",
               dict(time_sha256=initial[0], voltage_sha256=initial[1], unchanged=True))
    return rows


def run_synthetic(stage: str, instances: int) -> None:
    rows = []
    cases = [(f, i) for f in FAMILIES for i in range(instances)]
    if stage == "phase_stress":
        cases = [("low_ramp", i) for i in range(50)]
    for index, (family, instance) in enumerate(cases):
        case = generate(family, instance, development=stage.startswith("development"),
                        phase_stress=stage == "phase_stress")
        case_id = case.signal.name
        folder = OUT/"datasets"/stage
        folder.mkdir(parents=True, exist_ok=True)
        with (folder/f"{case_id}.npz").open("xb") as handle:
            np.savez_compressed(handle, time_s=case.signal.time_s, voltage_v=case.signal.voltage_v,
                                truth_hz=case.truth_hz, other_hz=case.other_hz,
                                amplitude_v=case.amplitude_v)
        write_json(folder/f"{case_id}.json", dict(family=family, seed=case.seed,
                   onset_s=case.onset_s, **case.metadata))
        new = evaluate_signal(case.signal, stage, case_id, case, {})
        rows.extend(new)
        print(json.dumps(dict(stage=stage, completed=index+1, total=len(cases), case_id=case_id,
                              failures=sum(r["status"] != "OK" for r in new))), flush=True)
    save_tables(rows, stage)


def save_tables(rows: list[dict[str, Any]], stage: str) -> None:
    write_csv(OUT/"tables"/f"{stage}_metrics.csv", rows)
    for name in METHODS:
        selected = [r for r in rows if r["method"] == name]
        write_csv(OUT/name/f"{stage}_metrics.csv", selected)
        failures = [r for r in selected if r["status"] != "OK"]
        write_json(OUT/name/f"{stage}_execution_failures.json", failures)


def run_real() -> None:
    rows = []
    items = inventory()
    write_json(OUT/"raw_inventory.json", items)
    write_csv(OUT/"tables"/"raw_inventory.csv", items)
    all_raw = [r for r in items if r["kind"].startswith("RAW")]
    for index, row in enumerate(all_raw):
        try:
            signals = read_raw(row)
        except Exception as exc:
            for method in METHODS:
                rows.append(dict(method=method, case_id=f"raw{index:02d}", raw_path=row["path"],
                                  stage="real", status="READ_FAILED", reason=str(exc)))
            continue
        for c, signal in enumerate(signals, 1):
            case_id = f"raw{index:02d}_{signal.name}"
            source = dict(raw_path=row["path"], raw_sha256=row["sha256"], voltage_column=c,
                           hardware_channel="filename label only; acquisition mapping unverified",
                           sample_rate_hz=signal.fs, samples=len(signal.time_s))
            new = evaluate_signal(signal, "real", case_id, None, source)
            rows.extend(new)
            print(json.dumps(dict(stage="real", raw_file=index+1, total_files=len(all_raw),
                                  case_id=case_id, failures=sum(r["status"] != "OK" for r in new))),
                  flush=True)
    save_tables(rows, "real")


def freeze() -> None:
    sources = {p.relative_to(ROOT).as_posix(): sha(p)
               for base in (Path(waveform.__file__).parent, Path(__file__).parent)
               for p in base.rglob("*.py") if "__pycache__" not in p.parts
               and "development_sources00" not in p.parts}
    sources.update({p.relative_to(ROOT).as_posix(): sha(p)
                    for p in (ROOT/"tests").rglob("*task008*.py")})
    write_json(OUT/"source_freeze.json", sources)
    write_json(OUT/"environment.json", dict(python=sys.version, executable=sys.executable,
               platform=platform.platform(), numpy=np.__version__, processor=platform.processor(),
               scipy=importlib.import_module("scipy").__version__, threads=1,
               timing="perf_counter wall seconds, single BLAS thread, no export time"))
    for name in METHODS:
        module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
        write_json(OUT/name/"parameters.json", module.PARAMETERS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("development00", "development01", "development02", "fresh",
                        "phase_stress", "real", "freeze"))
    parser.add_argument("--instances", type=int, default=8)
    args = parser.parse_args()
    if args.stage == "freeze":
        freeze()
    elif args.stage == "real":
        run_real()
    else:
        run_synthetic(args.stage, args.instances)


if __name__ == "__main__":
    main()
