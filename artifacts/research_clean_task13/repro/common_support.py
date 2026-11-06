"""Descriptive paired RMSE on identical accepted points, alongside full-denominator tables."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

from .cases import VELOCITY, load, specifications
from .experiment import write_csv
from .stage import grid


def compare(run: Path, output: Path) -> None:
    contrasts = [("clip_stft2048", "profile2048", "low_frequency"),
                 ("clip_stft2048", "profile2048", "plateau"),
                 ("stft768", "profile2048", "plateau"),
                 ("profile512", "bounded_chirp512", "acceleration"),
                 ("profile512", "bounded_chirp512", "decline"),
                 ("dechirp", "bounded_chirp512", "acceleration"),
                 ("dechirp", "bounded_chirp512", "decline"),
                 ("current_map", "stage_map", "all")]
    sums: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for spec in specifications():
        case = load(spec)
        idx = grid(case.signal)
        truth = case.truth_hz[idx]
        labels = case.stage_truth[idx]
        with np.load(run / "cases" / f"{case.signal.name}.npz") as z:
            arrays = {name + "__accepted_hz": z[name + "__accepted_hz"]
                      for name in set(n for a, b, _ in contrasts for n in (a, b))}
        for baseline, method, region in contrasts:
            mask = np.isfinite(truth) & ((labels == region) if region != "all" else True)
            key = (case.split, region, baseline, method)
            row = sums.setdefault(key, {"target_n": 0, "common_finite_n": 0,
                                        "baseline_sse": 0., "method_sse": 0.})
            base, new = arrays[baseline + "__accepted_hz"], arrays[method + "__accepted_hz"]
            joint = mask & np.isfinite(base) & np.isfinite(new)
            row["target_n"] += int(mask.sum())
            row["common_finite_n"] += int(joint.sum())
            row["baseline_sse"] += float(np.sum(((base[joint] - truth[joint]) * VELOCITY)**2))
            row["method_sse"] += float(np.sum(((new[joint] - truth[joint]) * VELOCITY)**2))
    rows = []
    for (split, region, baseline, method), row in sums.items():
        n = row["common_finite_n"]
        rows.append({"split": split, "region": region, "baseline": baseline, "method": method,
                     **row, "baseline_rmse_m_s": float(np.sqrt(row["baseline_sse"] / n)) if n else None,
                     "method_rmse_m_s": float(np.sqrt(row["method_sse"] / n)) if n else None,
                     "scope": "descriptive intersection; use full-denominator failure tables too"})
    write_csv(output, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compare(args.run, args.output)


if __name__ == "__main__":
    main()
