"""Post-hoc mechanism ablation of routing; not an independent confirmation.

Reuse every existing trace. Replace profile2048 by matched long STFT control,
and bounded_chirp512 by frozen Dechirp, retaining identical annotation rules.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .cases import load, specifications
from .experiment import score, write_csv, write_json
from .stage import annotation_at, empty, grid, recommended
from .summarize import aggregate, paired


def ablate(run: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    rows = []
    for spec in specifications():
        case = load(spec)
        result = empty(len(grid(case.signal)))
        with np.load(run / "cases" / f"{case.signal.name}.npz") as z:
            for i, center in enumerate(grid(case.signal)):
                chosen = recommended(annotation_at(case.plan, float(case.signal.time_s[center])))
                chosen = {"profile2048": "clip_stft2048", "bounded_chirp512": "dechirp"}.get(chosen, chosen)
                for key in ("candidate_hz", "accepted_hz", "chirp_hz_s", "quality", "r2",
                            "condition", "support_samples"):
                    getattr(result, key)[i] = z[chosen + "__" + key][i]
        rows.extend(score(case, {"simple_stage_map": result}))
    write_csv(destination / "metrics.csv", rows)
    frame = pd.concat([pd.read_csv(run / "metrics.csv"), pd.DataFrame(rows)], ignore_index=True)
    write_csv(destination / "overall.csv", aggregate(frame[frame.region == "all"],
                                                     ["split", "method", "kind"]))
    pairs = [row for split in sorted(frame.split.unique())
             for method in ("stage_map", "current_map")
             if (row := paired(frame, "simple_stage_map", method, "all", str(split))) is not None]
    write_csv(destination / "paired.csv", pairs)
    write_json(destination / "status.json", {"status": "POSTHOC_MECHANISM_ABLATION",
               "uses_truth_for_routing": False, "new_estimator_runs": 0,
               "waveforms": len(specifications()), "independent_confirmation": False})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ablate(args.run, args.output)


if __name__ == "__main__":
    main()
