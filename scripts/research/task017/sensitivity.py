"""Boundary perturbations on unchanged real voltage; no simulated signals."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Context, Signal
from dps_studio.core.segmentation.models import Segment
from dps_studio.core.segmentation.strategies import STRATEGIES, estimate_strategy
from scripts.research.task017.compare import (
    Trace, diagnose, evidence, frozen_plans, normalize, request,
)
from scripts.research.task017.prepare import OUT, load, records


def execute(item: dict[str, Any], output: str) -> list[dict[str, Any]]:
    t, y, fs = load(item)
    context = Context(Signal(t, y, item["id"]))
    original = frozen_plans()[item["id"]]
    onset_index = next(i for i, seg in enumerate(original) if seg["stage"] == "onset")
    onset = original[onset_index]
    q = np.arange(0, len(t), 128, dtype=np.int64)
    use = (t[q] >= onset["start_s"]-15e-9) & (t[q] <= onset["end_s"]+20e-9)
    ev = evidence(t, y, fs, q[use], onset["start_range_s"][0]-2e-9)
    frames, summary = [], []
    for boundary, shift in [("none", 0.), *[(b, a) for b in ("start", "end")
                                          for a in (-5., -2., 2., 5.)]]:
        plan = copy.deepcopy(original)
        if boundary == "start":
            plan[onset_index]["start_s"] += shift*1e-9
            plan[onset_index-1]["end_s"] = plan[onset_index]["start_s"]
        if boundary == "end":
            plan[onset_index]["end_s"] += shift*1e-9
            plan[onset_index+1]["start_s"] = plan[onset_index]["end_s"]
        # Native methods depend on onset START only; do not rerun identical end-only conditions.
        names = ["stft_short"] if boundary == "end" else ["stft_short", "dechirp", "varpro"]
        for name in names:
            if name == "stft_short":
                result_f = np.full(len(q), np.nan)
                gated = result_f.copy()
                flags = np.full(len(q), "NO_NATIVE_CENTER", dtype="U256")
                for j in range(onset_index-1, onset_index+2):
                    seg = plan[j]
                    result = estimate_strategy(replace(request(t, y, fmin=5e6), segment=Segment(
                        seg["id"], seg["start_s"], seg["end_s"], seg["stage"])), name,
                        replace(STRATEGIES[name], hop=128))
                    centers = np.rint((result.time_s-t[0])*fs).astype(np.int64)
                    positions = centers//128
                    own = (t[centers] >= seg["start_s"]) & (t[centers] < seg["end_s"])
                    result_f[positions[own]] = result.candidate_frequency_hz[own]
                    gated[positions[own]] = result.frequency_hz[own]
                    flags[positions[own]] = np.asarray(result.quality)[own]
                values = {"time_s": t[q][use], "frequency_hz": result_f[use],
                          "gated_frequency_hz": gated[use], "quality": flags[use],
                          "chirp_hz_s": np.zeros(int(use.sum()))}
            else:
                scoped = copy.copy(context)
                selected = np.isin(context.centers, q[use])
                scoped.centers = context.centers[selected]
                scoped.time_s = context.time_s[selected]
                scoped.seed_indices = context.seed_indices[selected]
                scoped.seed = context.seed[selected]
                scoped.contrast = context.contrast[selected]
                scoped.onset = int(np.searchsorted(t, plan[onset_index]["start_s"]))
                module = importlib.import_module(
                    f"dps_studio.algorithms.waveform.{name}.implementation")
                result = module.run(scoped)
                tr = Trace(scoped.time_s, result.frequency_hz, result.accepted_hz, result.flags,
                           result.extra.get("chirp_hz_per_s", np.zeros(len(scoped.centers))),
                           512, 5e6, 8e9, 0., {}, "native + perturbed visual onset")
                values = {key: value[use] for key, value in normalize(tr, t, fs).items()}
            values.update(diagnose(values, ev, fs))
            mask = (values["time_s"] >= onset["start_s"]) & (values["time_s"] < onset["end_s"])
            summary.append({"channel": item["id"], "method": name, "boundary": boundary,
                            "shift_ns": shift, "fixed_onset_centers": int(mask.sum()),
                            "candidate_n": int((mask & np.isfinite(values["frequency_hz"])).sum()),
                            "gated_n": int((mask & np.isfinite(values["gated_frequency_hz"])).sum()),
                            "supported_n": int((mask & values["spectrally_supported"]).sum())})
            frame = pd.DataFrame(values)
            frame["channel"], frame["method"] = item["id"], name
            frame["boundary"], frame["shift_ns"] = boundary, shift
            frames.append(frame)
    pd.concat(frames, ignore_index=True).to_csv(Path(output) / f"{item['id']}.csv.gz", index=False)
    print("sensitivity", item["id"], flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(OUT / "data"):
        parser.error("Choose a new TASK-017 data directory")
    output.mkdir(exist_ok=False)
    with ProcessPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(execute, records(), [str(output)]*len(records())))
    pd.DataFrame([row for result in results for row in result]).to_csv(
        output / "metrics.csv", index=False)
    (output / "complete.json").write_text(json.dumps({
        "channels": len(results), "waveforms_modified": False,
        "shifts_ns": [-5, -2, 0, 2, 5],
        "denominator": "frozen ORIGINAL onset centers, all shifts; no independent repeats"}, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
