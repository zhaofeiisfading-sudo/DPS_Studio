"""Long-support audit for actual low-band candidates; distinct temporal scale."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task017.compare import diagnose, evidence, frozen_plans
from scripts.research.task017.prepare import OUT, load, records


def execute(item: dict[str, Any], output: str, analysis: str) -> list[dict[str, Any]]:
    t, y, fs = load(item)
    onset = next(s for s in frozen_plans()[item["id"]] if s["stage"] == "onset")
    root = Path(analysis) / item["id"]
    base = dict(np.load(root / "M1_balanced.npz"))
    ev = evidence(t, y, fs, base["sample_index"], onset["start_range_s"][0]-2e-9, width=4096)
    available = bool(np.isfinite(ev["background"]).all())
    rows, summary = [], []
    for name in ("M1_balanced", "stft_low", "low_glrt"):
        v = dict(np.load(root / f"{name}.npz"))
        applicable = np.isfinite(v["frequency_hz"]) & (v["frequency_hz"] <= 250e6)
        v["frequency_hz"] = np.where(applicable, v["frequency_hz"], np.nan)
        diag = diagnose(v, ev, fs)
        frame = pd.DataFrame({"time_s": v["time_s"], "method": name, "stage": v["stage"],
                              "frequency_hz": v["frequency_hz"], "applicable_low_band": applicable,
                              "background_available": available,
                              **{key.replace("cycles_256", "cycles_4096"): value
                                 for key, value in diag.items()}})
        rows.append(frame)
        primary = v["primary_common_support"]
        for stage in np.unique(v["stage"]):
            mask = primary & (v["stage"] == stage)
            summary.append({"channel": item["id"], "method": name, "stage": stage,
                            "centers": int(mask.sum()),
                            "applicable_low_band_n": int((mask & applicable).sum()),
                            "long_supported_n": int((mask & diag["spectrally_supported"]).sum())
                            if available else None, "background_available": available,
                            "window_ns": 4096/fs*1e9})
    pd.concat(rows, ignore_index=True).to_csv(Path(output) / f"{item['id']}.csv.gz", index=False)
    print("low support", item["id"], available, flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, default=OUT / "data/analysis_v03")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(OUT / "data"):
        parser.error("Choose a new TASK-017 data directory")
    output.mkdir(exist_ok=False)
    with ProcessPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(execute, records(), [str(output)]*len(records()),
                                   [str(args.analysis)]*len(records())))
    pd.DataFrame([row for result in results for row in result]).to_csv(output / "metrics.csv", index=False)
    (output / "complete.json").write_text(json.dumps({"channels": 14,
        "support_samples": 4096, "time_resolution_claim": False,
        "scope": "Only actual candidates <=250 MHz; original voltage, no subtraction",
        "missing_background_is_not_a_negative_result": True}), encoding="utf-8")


if __name__ == "__main__":
    main()
