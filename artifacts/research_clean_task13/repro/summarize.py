"""Waveform-level paired summaries; no pseudo-replication of overlapping frames."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .experiment import write_csv, write_json


def aggregate(frame: pd.DataFrame, keys: list[str]) -> list[dict[str, Any]]:
    rows = []
    for group, part in frame.groupby(keys, dropna=False):
        group = (group,) if len(keys) == 1 else group
        n, m = int(part.target_n.sum()), int(part.finite_n.sum())
        absent = int(part.absent_n.sum())
        branch = int(part.branch_eligible_n.sum())
        row = dict(zip(keys, group, strict=True))
        row.update(cases=int(part.case.nunique()), target_cases=int((part.target_n > 0).sum()),
                   target_n=n, finite_n=m,
                   rmse_m_s=float(np.sqrt(part.sse_m2_s2.sum() / m)) if m else None,
                   coverage_percent=float(part.coverage.mean() * 100) if n else None,
                   failure_percent=float(part.failure_fraction.mean() * 100) if n else None,
                   pooled_failure_percent=float(part.failure_n.sum() / n * 100) if n else None,
                   strict_15_percent=float(part.strict_15_n.sum() / n * 100) if n else None,
                   strict_38p75_percent=float(part.strict_38p75_n.sum() / n * 100) if n else None,
                   wrong_branch_percent=float(part.wrong_branch_n.sum() / branch * 100) if branch else None,
                   wrong_branch_n=int(part.wrong_branch_n.sum()), branch_eligible_n=branch,
                   branch_missing_n=int(part.branch_missing_n.sum()), absent_n=absent,
                   absent_output_percent=float(part.absent_output_n.sum() / absent * 100) if absent else None,
                   onset_eligible=int(part.onset_eligible.sum()) if "onset_eligible" in part else 0,
                   onset_missed=int(part.onset_missed.sum()) if "onset_missed" in part else 0,
                   onset_early=int(part.onset_early.sum()) if "onset_early" in part else 0,
                   onset_mae_ns=float(part.onset_abs_error_ns.mean()) if "onset_abs_error_ns" in part
                   and part.onset_abs_error_ns.notna().any() else None)
        rows.append(row)
    return rows


def paired(frame: pd.DataFrame, baseline: str, method: str, region: str,
           split: str, *, repeats: int = 2000) -> dict[str, Any] | None:
    part = frame[(frame.split == split) & (frame.region == region) & (frame.kind == "supported")]
    table = part.pivot(index="case", columns="method", values="failure_fraction")
    if baseline not in table or method not in table:
        return None
    values = (table[method] - table[baseline]).dropna().to_numpy(dtype=float) * 100
    if not len(values):
        return None
    rng = np.random.default_rng(130013)
    bootstrap = values[rng.integers(0, len(values), (repeats, len(values)))].mean(axis=1)
    lo, hi = np.quantile(bootstrap, [.025, .975])
    return {"split": split, "region": region, "baseline": baseline, "method": method,
            "n_waveforms": len(values), "failure_difference_pp": float(values.mean()),
            "ci_low_pp": float(lo), "ci_high_pp": float(hi),
            "bootstrap_repeats": repeats, "exploratory_unadjusted": True}


def summarize(run: Path, destination: Path, cost: Path | None, sensitivity: Path | None) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    frame = pd.read_csv(run / "metrics.csv")
    all_rows = frame[frame.region == "all"]
    write_csv(destination / "overall.csv", aggregate(all_rows, ["split", "method", "kind"]))
    write_csv(destination / "family.csv", aggregate(all_rows, ["split", "family", "method", "kind"]))
    write_csv(destination / "stage.csv", aggregate(frame[frame.region != "all"],
                                                  ["split", "region", "method", "kind"]))
    contrasts = [("current_map", "stage_map", "all"), ("stft768", "stage_map", "all")]
    for region in ("acceleration", "decline", "rebound"):
        contrasts += [(baseline, "bounded_chirp512", region)
                      for baseline in ("clip_stft512", "profile512", "dechirp", "varpro")]
    for region in ("plateau", "low_frequency"):
        contrasts += [(baseline, "profile2048", region)
                      for baseline in ("clip_stft2048", "profile512", "stft768")]
    contrasts += [("varpro", "clutter_varpro", "weak_signal"),
                  ("stft512", "clip_stft512", "onset")]
    pairs = [row for split in sorted(frame.split.unique()) for base, method, region in contrasts
             if (row := paired(frame, base, method, region, str(split))) is not None]
    write_csv(destination / "paired.csv", pairs)
    if cost is not None:
        measurements = pd.read_csv(cost / "measurements.csv")
        cost_rows = []
        for method, part in measurements.groupby("method"):
            values = part.runtime_s.to_numpy(dtype=float) * 1000
            cost_rows.append({"method": method, "measurements": len(values),
                              "median_ms": float(np.median(values)),
                              "p10_ms": float(np.quantile(values, .1)),
                              "p90_ms": float(np.quantile(values, .9)),
                              "maximum_ms": float(np.max(values)),
                              "includes_initialization": True})
        write_csv(destination / "cost.csv", cost_rows)
    if sensitivity is not None:
        stress = pd.read_csv(sensitivity / "metrics.csv")
        write_csv(destination / "annotation_sensitivity.csv", aggregate(stress[stress.region == "all"],
                    ["perturbation", "family", "method", "kind"]))
    # Persist exactly the denominators that every report/plot consumes.
    write_json(destination / "checks.json", {
        "unique_cases": int(frame.case.nunique()),
        "independent_cases": int(frame[frame.split == "independent"].case.nunique()),
        "legacy_cases": int(frame[frame.split.str.startswith("legacy")].case.nunique()),
        "rows": len(frame), "paired_contrasts": len(pairs),
        "all_cases_have_all_methods": bool(all_rows.groupby(["case", "kind"]).method.nunique().eq(13).all()),
        "all_missing_control_failure_one": bool(all_rows[(all_rows.method == "unobservable")
                                                   & (all_rows.target_n > 0)].failure_fraction.eq(1.).all()),
        "finite_never_exceeds_target": bool((frame.finite_n <= frame.target_n).all()),
        "no_failures_omitted": len(list((run / "cases").glob("*.error.json"))) == 0,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cost", type=Path)
    parser.add_argument("--sensitivity", type=Path)
    args = parser.parse_args()
    summarize(args.run, args.output, args.cost, args.sensitivity)


if __name__ == "__main__":
    main()
