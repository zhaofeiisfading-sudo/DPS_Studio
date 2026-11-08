"""Common-support residual and waveform-level bootstrap for the selected stage."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task013 import stage
from scripts.research.task013.cases import VELOCITY, fresh
from scripts.research.task014.study import one_peak

OUT = Path(__file__).resolve().parents[3] / "artifacts/TASK-014"
def main() -> None:
    rows = []
    for index in range(32, 48):
        case = fresh("low_plateau", index)
        old = stage.local_estimate(case.signal, case.plan, "clip_stft2048")
        new = one_peak(case.signal, case.plan)
        keep = np.isfinite(old.accepted_hz) & np.isfinite(new.accepted_hz)
        truth = case.truth_hz[stage.grid(case.signal)][keep]
        if not keep.any():
            rows.append(dict(instance=index, n=0, old_sse=0., new_sse=0.))
            continue
        e0 = (old.accepted_hz[keep] - truth) * VELOCITY
        e1 = (new.accepted_hz[keep] - truth) * VELOCITY
        rows.append(dict(instance=index, n=len(truth), old_sse=float(e0@e0), new_sse=float(e1@e1),
                         bias_m_s=e1.mean(), median_r2=np.median(new.r2[keep]),
                         max_condition=new.condition[keep].max()))
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "low_paired.csv", index=False)
    rng = np.random.default_rng(140014)
    boot = rng.integers(0, len(frame), (5000, len(frame)))
    n = frame.n.to_numpy()[boot].sum(axis=1)
    delta = (np.sqrt(frame.new_sse.to_numpy()[boot].sum(axis=1)/n)
             - np.sqrt(frame.old_sse.to_numpy()[boot].sum(axis=1)/n))
    print("Common centers", frame.n.sum(), "old/new RMSE",
          np.sqrt(frame[["old_sse","new_sse"]].sum()/frame.n.sum()).to_list())
    print("Paired waveform bootstrap delta 95% interval", np.percentile(delta,[2.5,97.5]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    requested = parser.parse_args().run.resolve()
    if not requested.is_dir() or not requested.is_relative_to(OUT.resolve()):
        parser.error("Choose an existing TASK-014 run")
    OUT = requested
    if (OUT / "low_paired.csv").exists():
        parser.error("This run already contains paired results")
    main()
