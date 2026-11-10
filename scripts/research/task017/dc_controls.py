"""Post-freeze diagnostic controls isolating DC/trend removal from window/phase."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import gzip
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from dps_studio.core.segmentation.strategies import Strategy, estimate_strategy
from scripts.research.task017.compare import (
    Trace, diagnose, evidence, frozen_plans, json_default, normalize, request,
)
from scripts.research.task017.prepare import OUT, load, records


def execute(item: dict[str, Any], output: str) -> None:
    dest = Path(output) / item["id"]
    dest.mkdir()
    t, y, fs = load(item)
    onset = next(s for s in frozen_plans()[item["id"]] if s["stage"] == "onset")
    metadata = {}
    q = np.arange(0, len(t), 128, dtype=np.int64)
    ev = evidence(t, y, fs, q, onset["start_range_s"][0]-2e-9)
    for name, width, degree in (("demean1024_control", 1024, 0),
                                 ("detrend1024_control", 1024, 1),
                                 ("demean512_control", 512, 0)):
        spec = Strategy(width=width, hop=128, nfft=4096, boundary="full", degree=degree)
        started = perf_counter()
        result = estimate_strategy(replace(request(t, y, width), segment=None), name, spec)
        runtime = perf_counter()-started
        trace = Trace(result.time_s, result.candidate_frequency_hz, result.frequency_hz,
                      np.asarray(result.quality), np.zeros(len(result.time_s)), width, 50e6, 6e9,
                      runtime, dict(result.details), "Shared strategy engine / matched Hann NFFT4096; "
                      f"full support; polynomial nuisance degree {degree}; original 50 MHz-6 GHz band")
        values = normalize(trace, t, fs)
        values.update(diagnose(values, ev, fs))
        values["stage"] = np.full(len(q), "unknown", dtype="U32")
        values["segment_id"] = np.full(len(q), "", dtype="U16")
        plan = frozen_plans()[item["id"]]
        for i, seg in enumerate(plan):
            own = (t[q] >= seg["start_s"]) & ((t[q] <= seg["end_s"]) if i == len(plan)-1
                                             else (t[q] < seg["end_s"]))
            values["stage"][own], values["segment_id"][own] = seg["stage"], seg["id"]
        values["primary_common_support"] = (q >= 1024) & (q <= len(t)-1024)
        np.savez_compressed(dest / f"{name}.npz", **values)
        np.savez_compressed(dest / f"{name}__native.npz", time_s=result.time_s,
                            raw_frequency_hz=result.candidate_frequency_hz,
                            gated_frequency_hz=result.frequency_hz, quality=np.asarray(result.quality))
        with gzip.open(dest / f"{name}__details.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(dict(result.details), handle, default=json_default)
        metadata[name] = {"runtime_s": runtime, "source": trace.source,
                          "nominal_width_samples": width, "band_hz": [50e6, 6e9],
                          "posthoc_diagnostic_control": True,
                          "gate_differs_from_formal": True}
    (dest / "metadata.json").write_text(json.dumps({"methods": metadata}, indent=2), encoding="utf-8")
    print("DC controls", item["id"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dest = args.output.resolve()
    if not dest.is_relative_to(OUT / "data"):
        parser.error("Choose a new TASK-017 data directory")
    dest.mkdir(exist_ok=False)
    with ProcessPoolExecutor(max_workers=3) as executor:
        list(executor.map(execute, records(), [str(dest)]*len(records())))
    (dest / "complete.json").write_text(json.dumps({"channels": 14, "controls": 3,
        "rationale": "Posthoc control after observed formal DC-leakage candidates; no held-out claim",
        "raw_modified": False}), encoding="utf-8")


if __name__ == "__main__":
    main()
