"""Waveform-level summaries and paired intervals; no frame pseudoreplication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from artifacts.research_clean_task10.audit import OUT, write_json
from artifacts.research_clean_task10.experiment import Spec
from artifacts.research_clean_task10.run import write_csv


def aggregate(group: Any, region: str, state: str, grid: str = "common") -> dict[str, Any]:
    prefix = f"{grid}_{state}_{region}_"
    n = float(group[prefix + "target_n"].sum())
    finite = float(group[prefix + "finite_n"].sum())
    sse = float(group[prefix + "sse_m2_s2"].sum())
    failure = float(group[prefix + "failure_n"].sum())
    return dict(grid=grid, state=state, region=region,
        target_n=int(n), finite_n=int(finite), waveforms=int((group[prefix+"target_n"] > 0).sum()),
        rmse_pooled_m_s=float(np.sqrt(sse/finite)) if finite else None,
        rmse_macro_m_s=float(group[prefix+"rmse_m_s"].mean())
        if group[prefix+"rmse_m_s"].notna().any() else None,
        coverage_pooled=finite/n if n else None, failure_pooled=failure/n if n else None,
        coverage_macro=float(group[prefix+"coverage"].mean())
        if group[prefix+"coverage"].notna().any() else None,
        failure_macro=float(group[prefix+"failure_fraction"].mean())
        if group[prefix+"failure_fraction"].notna().any() else None)


def summarize(data: Any, *, frozen: bool = False) -> list[dict[str, Any]]:
    rows = []
    for (stage, name), group in data.groupby(["stage", "name"], sort=False):
        base = dict(stage=stage, name=name)
        if not frozen:
            base.update({k: group.iloc[0][k] for k in ("label", "window", "hop", "nfft")})
        regions = ("motion", "low") if frozen else ("motion", "low", "fast", "onset40")
        for region in regions:
            for state in ("candidate", "supported"):
                for grid in (("common",) if frozen else ("common", "native")):
                    rows.append({**base, **aggregate(group, region, state, grid)})
    return rows


def bootstrap(data: Any) -> list[dict[str, Any]]:
    rows = []
    candidates = [Spec(w, 32).name for w in (512, 768, 1024, 1536, 2048)]
    for stage in ("fresh", "phase_stress", "confirmation"):
        subset = data[data.stage == stage]
        comparisons = [(Spec(512, 128).name, candidate) for candidate in candidates]
        if stage != "confirmation":
            base = "wide_demean_w512_h32_n4096"
            comparisons += [(base, "wide_demean_w2048_h32_n4096"),
                            (base, "adaptive512_2048_w2048_h32_n4096")]
        for baseline, candidate in comparisons:
            left = subset[subset.name == baseline].set_index("case_id")
            right = subset[subset.name == candidate].set_index("case_id")
            ids = left.index.intersection(right.index)
            if not len(ids):
                continue
            for state in ("candidate", "supported"):
                for region in ("motion", "low"):
                    for outcome in ("failure_fraction", "coverage", "rmse_m_s"):
                        key = f"common_{state}_{region}_{outcome}"
                        a, b = left.loc[ids, key].to_numpy(float), right.loc[ids, key].to_numpy(float)
                        valid = np.isfinite(a) & np.isfinite(b)
                        delta = b[valid] - a[valid]
                        if not len(delta):
                            continue
                        rng = np.random.default_rng(10020261105)
                        indices = rng.integers(0, len(delta), size=(4000, len(delta)))
                        distribution = delta[indices].mean(axis=1)
                        lo, hi = np.quantile(distribution, [.025, .975])
                        rows.append(dict(stage=stage, baseline=baseline, candidate=candidate,
                            state=state, region=region, outcome=outcome,
                            paired_waveforms=len(delta), mean_delta=float(delta.mean()),
                            ci95_lower=float(lo), ci95_upper=float(hi), replicates=4000,
                            family_stratified=False, exploratory_unadjusted=True))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cost", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(OUT):
        parser.error("Output must be a new TASK-010 subdirectory")
    output.mkdir(parents=True, exist_ok=False)
    data = pd.read_csv(args.run / "tables/synthetic_metrics.csv")
    frozen = pd.read_csv(args.run / "tables/frozen_common_rescored.csv")
    write_csv(output / "summary.csv", summarize(data))
    write_csv(output / "frozen_summary.csv", summarize(frozen, frozen=True))
    write_csv(output / "paired_bootstrap.csv", bootstrap(data))
    by_family = []
    for family, group in data[data.stage == "fresh"].groupby("family"):
        for row in summarize(group):
            row["family"] = family
            by_family.append(row)
    write_csv(output / "family_summary.csv", by_family)
    onset = []
    for (stage, name), group in data.groupby(["stage", "name"]):
        for method in ("spectral", "raw_energy"):
            error = group[method + "_onset_error_ns"].dropna()
            motion = group[group.truth_onset_s.notna()]
            noise = group[group.truth_onset_s.isna()]
            onset.append(dict(stage=stage, name=name, method=method, detected_n=len(error),
                true_event_waveforms=len(motion),
                mean_abs_error_ns=float(abs(error).mean()) if len(error) else None,
                median_abs_error_ns=float(abs(error).median()) if len(error) else None,
                mean_signed_error_ns=float(error.mean()) if len(error) else None,
                missed_n=int(motion[method + "_onset_missed"].sum()),
                false_event_n=int(noise[method + "_false_event"].sum())))
    write_csv(output / "onset.csv", onset)
    corr = data[(data.stage == "fresh") & (data.family == "step") & (data.label == "strict")]
    write_csv(output / "correlation.csv", corr[["name", "window", "hop", "case_id",
        "lag1_residual_correlation", "lag_128samples_residual_correlation",
        "window_overlap_inner_product", "frames"]].to_dict("records"))
    failures = data[(data.common_supported_motion_target_n > 0)].sort_values(
        ["common_supported_motion_failure_fraction", "common_supported_motion_rmse_m_s"],
        ascending=False).head(80)
    write_csv(output / "worst_cases_posthoc.csv", failures.to_dict("records"))
    invariance = []
    subset = data[(data.label == "strict") & (data.stage != "confirmation")]
    for (stage, case_id, width), group in subset.groupby(["stage", "case_id", "window"]):
        keys = [k for k in group.columns if k.startswith("common_") and
                any(suffix in k for suffix in ("sse_m2_s2", "failure_n", "finite_n", "target_n"))]
        equal = all(group[k].dropna().nunique() <= 1 for k in keys)
        invariance.append(dict(stage=stage, case_id=case_id, window=width,
                               all_common_scores_equal=equal, hop_configurations=len(group)))
    write_csv(output / "hop_invariance.csv", invariance)
    write_json(output / "summary_checks.json", dict(synthetic_records=len(data),
        frozen_records=len(frozen), exception_records=json.loads(
            (args.run / "checks/exceptions.json").read_text(encoding="utf-8")),
        all_common_hop_scores_equal=all(r["all_common_scores_equal"] for r in invariance),
        uncertainty_unit="paired waveforms; finite-pair RMSE intervals exclude unavailable RMSE",
        inference="exploratory unadjusted percentile bootstrap; no frame-level p-values"))
    if args.cost:
        cost = pd.read_csv(args.cost / "measurements.csv")
        values = []
        for (dataset, name, backend), group in cost.groupby(["dataset", "name", "backend"]):
            first = group.iloc[0]
            values.append(dict(dataset=dataset, name=name, backend=backend,
                window=int(first.window), hop=int(first.hop), repeats=len(group),
                median_runtime_s=float(group.runtime_s.median()),
                min_runtime_s=float(group.runtime_s.min()), max_runtime_s=float(group.runtime_s.max()),
                allocated_peak_mib=float(group.tracemalloc_peak_bytes.max()/2**20),
                process_peak_rss_mib=float(group.measured_process_peak_working_set_bytes.max()/2**20),
                dense_complex_mib=float(first.retained_dense_complex_bytes/2**20)))
        write_csv(output / "cost_summary.csv", values)


if __name__ == "__main__":
    main()
