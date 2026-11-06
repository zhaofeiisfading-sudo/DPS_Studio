"""Replay three fixed raw records across all frozen methods with source denied."""
from __future__ import annotations

import importlib
import json
import os
import sys

import numpy as np

from dps_studio.research.task009_data import install, inventory, read_raw
from dps_studio.research.task009_runtime import ROOT, TASK8, TASK9, provenance, source_guard


def main() -> None:
    output = TASK9 / "checks/raw_replay.json"
    if output.exists():
        raise FileExistsError(output)
    sys.addaudithook(source_guard)
    install()
    from artifacts.research_clean_task8.catalog import METHODS, run_folder
    from artifacts.research_clean_task8.common import Context
    records = [r for r in inventory() if r["kind"] == "RAW"]
    selected = [(0, "raw00_20260607_ch1"), (6, "raw06_ch3_ch1"),
                (11, "raw11_20231019-ch1_ch1")]
    checks = []
    for index, case in selected:
        row = records[index]
        signal = read_raw(row)[0]
        context = Context(signal)
        for method in METHODS:
            module = importlib.import_module(f"artifacts.research_clean_task8.{method}.implementation")
            result = module.run(context)
            with np.load(run_folder(TASK8, method, "real", case) / "trajectory.npz") as frozen:
                for key, values in [("time_s", context.time_s), ("frequency_hz", result.frequency_hz),
                                    ("accepted_hz", result.accepted_hz), ("r2", result.extra["r2"])]:
                    np.testing.assert_allclose(frozen[key], values, rtol=1e-11, atol=1e-3, equal_nan=True)
            checks.append(dict(case=case, method=method, numerical_match=True,
                               raw_logical_path=row["path"], raw_local_path=row["local_path"],
                               raw_sha256=row["sha256"], frames=len(context.time_s)))
        print(f"Raw replay matched: {case}: {len(METHODS)} methods", flush=True)
    output.write_text(json.dumps(dict(checks=checks, provenance=provenance(),
        guard_active=True, thread_count=os.environ.get("OPENBLAS_NUM_THREADS"),
        target=str(ROOT)), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
