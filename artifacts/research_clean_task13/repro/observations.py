"""Full-record real observations and independent manual-annotation sensitivity."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.algorithms.task008.common import Signal
from dps_studio.research.task009_data import inventory, read_raw
from .cases import load, plan_dict
from .experiment import freeze, score, single, write_csv, write_json
from .stage import Annotation, grid, run_all


def real(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    freeze(destination, [])
    rows: list[dict[str, Any]] = []
    for item in inventory():
        if item["kind"] != "RAW":
            continue
        for original in read_raw(item):
            signal = Signal(np.array(original.time_s), np.array(original.voltage_v), original.name)
            before = hashlib.sha256(signal.voltage_v.tobytes()).hexdigest()
            plan = (Annotation(float(signal.time_s[0]),
                               float(signal.time_s[-1] + 1 / signal.fs), "unknown"),)
            traces = run_all(signal, plan)
            if before != hashlib.sha256(signal.voltage_v.tobytes()).hexdigest():
                raise AssertionError("Real input bytes changed")
            arrays: dict[str, Any] = {"time_s": signal.time_s, "voltage_v": signal.voltage_v,
                                      "centers": grid(signal),
                                      "corrected_velocity_m_s": np.full(len(grid(signal)), np.nan)}
            for name, trace in traces.items():
                arrays[name + "__candidate_hz"] = trace.candidate_hz
                arrays[name + "__accepted_hz"] = trace.accepted_hz
                arrays[name + "__quality"] = trace.quality
                finite = trace.accepted_hz[np.isfinite(trace.accepted_hz)]
                pair = np.isfinite(trace.accepted_hz) & np.isfinite(traces["stft768"].accepted_hz)
                difference = abs(trace.accepted_hz[pair] - traces["stft768"].accepted_hz[pair])
                rows.append({"case": signal.name, "method": name,
                             "centers": len(grid(signal)),
                             "finite_n": int(np.isfinite(trace.accepted_hz).sum()),
                             "finite_fraction": float(np.isfinite(trace.accepted_hz).mean()),
                             "median_frequency_hz": float(np.median(finite)) if len(finite) else None,
                             "paired_stft768_n": int(pair.sum()),
                             "disagreement_over_100MHz_n": int((difference > 100e6).sum()),
                             "input_unchanged": True, "physical_truth": "UNAVAILABLE",
                             "velocity_rmse": "UNAVAILABLE", "stage": "unknown",
                             "manual_stage_interpretation": "not assigned from waveform appearance",
                             "runtime_s": trace.runtime_s})
            with (destination / f"{signal.name}.npz").open("xb") as stream:
                np.savez_compressed(stream, **arrays)
            write_json(destination / f"{signal.name}.json", {"input_sha256": before,
                       "local_raw_path": item["local_path"], "manual_plan": plan_dict(plan),
                       "truth": "UNAVAILABLE", "frequency_is_nonnegative_magnitude": True,
                       "no_velocity_calibration_assumed": True})
            print(f"real_observation {signal.name}", flush=True)
    write_csv(destination / "diagnostics.csv", rows)
    write_json(destination / "completion.json", {"streams": len({row["case"] for row in rows}),
               "rows": len(rows), "raw_records": sum(item["kind"] == "RAW" for item in inventory())})


def sensitivity(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    specs = [("independent", family, i) for family in ("fast_accel", "fast_decel", "turnaround")
             for i in range(4)]
    freeze(destination, specs)
    rows = []
    for spec in specs:
        original = load(spec)
        for perturbation in ("base", "boundaries_minus5ns", "boundaries_plus5ns", "wrong_slope_sign"):
            plan = original.plan
            if "boundaries" in perturbation:
                offset = -5e-9 if "minus" in perturbation else 5e-9
                starts = [plan[0].start_s] + [p.start_s + offset for p in plan[1:]]
                ends = starts[1:] + [plan[-1].end_s]
                plan = tuple(replace(p, start_s=start, end_s=end)
                             for p, start, end in zip(plan, starts, ends, strict=True))
            elif perturbation == "wrong_slope_sign":
                opposite = {"acceleration": "decline", "decline": "acceleration", "rebound": "decline"}
                plan = tuple(replace(p, stage=opposite.get(p.stage, p.stage)) for p in plan)
            case = replace(original, plan=plan)
            traces = {name: single(case, name) for name in
                      ("clip_stft512", "bounded_chirp512", "stage_map")}
            for row in score(case, traces):
                row["perturbation"] = perturbation
                rows.append(row)
        print(f"annotation_sensitivity {original.signal.name}", flush=True)
    write_csv(destination / "metrics.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("real", "sensitivity"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"real": real, "sensitivity": sensitivity}[args.mode](args.output)


if __name__ == "__main__":
    main()
