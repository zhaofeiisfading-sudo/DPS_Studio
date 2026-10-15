"""Grouped TASK-002 statistics, historical replay and compact figure artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from audit_denoising_task001 import safe_output
from run_denoising_task001 import write_csv, write_json
from run_denoising_task002 import OLD, PROFILES, array_hash
from dps_studio.research import denoising_task001 as method
from dps_studio.research import denoising_task001_benchmark as old_bench
from dps_studio.research import denoising_task002 as bench
from dps_studio.research import task028_consolidation as frozen

COUNT_KEYS = tuple(bench.metrics(np.empty(0), np.empty(0), dict(
    truth=np.empty(0), normal=np.empty(0, dtype=bool), fast=np.empty(0, dtype=bool),
    focus=np.empty(0, dtype=bool)))) + ("candidate_recalled", "strongest_correct")


def aggregate(table: Any) -> dict[str, Any]:
    counts = {k: float(table[k].sum()) for k in COUNT_KEYS}
    grouped = table.groupby("case_id")[list(COUNT_KEYS)].sum()
    grouped = grouped[grouped.truth_frames > 0]
    return dict(**counts, **bench.ratios(counts), waveforms=table.case_id.nunique(),
        truth_waveforms=len(grouped),
        candidate_recall=(counts["candidate_recalled"]/counts["truth_frames"]
                          if counts["truth_frames"] else None),
        macro_rmse_hz=float(np.mean(np.sqrt(grouped.sse_hz2/grouped.squared_error_frames)))
                       if len(grouped) else None,
        macro_wrong_branch_fraction=float(np.mean(grouped.wrong_frames/grouped.truth_frames))
                                    if len(grouped) else None,
        total_harm_vs_strongest_fraction=(counts["harmed_frames"]/counts["strongest_correct"]
                                        if counts["strongest_correct"] else None))


def paired_bootstrap(table: Any) -> list[dict[str, Any]]:
    grouped = table[table.reference == "M1"].groupby(["case_id", "method"])[list(COUNT_KEYS)].sum()
    rows = []
    for reference in ("M1", "M0"):
        for chosen in ("M2", "DIAG_NO_AMP"):
            a = grouped.xs(reference, level="method")
            b = grouped.xs(chosen, level="method").loc[a.index]
            mask = a.truth_frames > 0
            a, b = a[mask], b[mask]
            for metric in ("rmse_hz", "wrong_branch_fraction"):
                if metric == "rmse_hz":
                    difference = (np.sqrt(b.sse_hz2/b.squared_error_frames)
                                  - np.sqrt(a.sse_hz2/a.squared_error_frames)).to_numpy(float)
                else:
                    difference = (b.wrong_frames/b.truth_frames-a.wrong_frames/a.truth_frames).to_numpy(float)
                rng = np.random.default_rng(42099002)
                sampled = difference[rng.integers(0, len(difference), (4000, len(difference)))].mean(axis=1)
                low, high = np.quantile(sampled, [.025, .975])
                rows.append(dict(comparison=f"{chosen}-{reference}", metric=metric,
                    waveforms=len(difference), mean_difference=float(difference.mean()),
                    ci_low=float(low), ci_high=float(high), resamples=4000, seed=42099002,
                    improved=int((difference < -1e-8).sum()), worsened=int((difference > 1e-8).sum()),
                    unchanged=int((abs(difference) <= 1e-8).sum())))
    return rows


def summarize(out: Path, split: str) -> None:
    key = split.lower()
    table = pd.read_csv(out/f"{key}_metrics.csv")
    rows = []
    for (chosen, reference), part in table.groupby(["method", "reference"]):
        rows.append(dict(dataset="ALL", method=chosen, reference=reference, **aggregate(part)))
        for dimension in ("family", "profile"):
            for name, group in part.groupby(dimension):
                rows.append(dict(dataset=dimension, name=name, method=chosen, reference=reference,
                                 **aggregate(group)))
    write_csv(out/f"{key}_comparison.csv", rows)
    write_csv(out/f"{key}_paired_waveform_uncertainty.csv", paired_bootstrap(table))
    flags = pd.read_csv(out/f"{key}_flags.csv")
    flag_summaries = []
    for name, group in flags.groupby("flag"):
        sums = group.select_dtypes(include="number").sum()
        flag_summaries.append(dict(flag=name, **{k: int(sums[k]) for k in (
            "flagged", "truth_frames", "inherited_harms", "flagged_inherited_harms",
            "p3_errors", "flagged_p3_errors")},
            inherited_harm_recall=float(sums.flagged_inherited_harms/sums.inherited_harms)
                                   if sums.inherited_harms else None,
            inherited_harm_precision=float(sums.flagged_inherited_harms/sums.flagged)
                                      if sums.flagged else None,
            p3_error_recall=float(sums.flagged_p3_errors/sums.p3_errors) if sums.p3_errors else None,
            p3_error_precision=float(sums.flagged_p3_errors/sums.flagged) if sums.flagged else None))
    write_csv(out/f"{key}_risk_flag_summary.csv", flag_summaries)
    prov = pd.read_csv(out/f"{key}_provenance.csv")
    write_json(out/f"{key}_runtime_summary.json", dict(
        stages={name: dict(median_s=float(prov[name].median()), p95_s=float(prov[name].quantile(.95)),
                          total_s=float(prov[name].sum()))
                for name in ("frontend_s", "p3_entry_s", "repair_s")},
        interpretation="Shared P3 entry includes continuity/quality diagnostics; not standalone speedup"))
    print(pd.DataFrame(rows).query("dataset == 'ALL' and reference == 'M1'")[
        ["method", "rmse_hz", "wrong_branch_fraction", "corrected_frames", "harmed_frames",
         "interventions", "intervention_precision", "fast_truth_accuracy"]].to_string(index=False))


def readiness(out: Path) -> None:
    gate = json.loads((out/"success_gate_registration.json").read_text())
    table = pd.read_csv(out/"held_out_comparison.csv")
    m2 = table[(table.dataset == "ALL") & (table.method == "M2") & (table.reference == "M1")].iloc[0]
    total = table[(table.dataset == "ALL") & (table.method == "M2") & (table.reference == "M0")].iloc[0]
    families = table[(table.dataset == "family") & (table.method.isin(["M1", "M2"]))
                     & (table.reference == "M1")].pivot(index="name", columns="method",
                                                        values="wrong_branch_fraction")
    uncertainty = pd.read_csv(out/"held_out_paired_waveform_uncertainty.csv")
    interval = uncertainty[(uncertainty.comparison == "M2-M1") & (uncertainty.metric == "rmse_hz")].iloc[0]
    earlier_harms = {}
    for split in ("development", "calibration"):
        t = pd.read_csv(out/f"{split}_metrics.csv")
        earlier_harms[split] = int(t[(t.method == "M2") & (t.reference == "M1")].harmed_frames.sum())
    checks = dict(
        zero_extra_harm=m2.harmed_frames <= gate["maximum_extra_harmed_frames"],
        normal_preserved=m2.normal_preservation >= gate["normal_preservation_min"],
        fast_preserved=m2.fast_preservation >= gate["fast_preservation_min"],
        full_coverage=m2.coverage >= gate["coverage_min"],
        enough_corrections=m2.corrected_frames >= gate["minimum_corrected_frames"],
        intervention_precision=m2.intervention_precision >= gate["minimum_intervention_precision"],
        total_harm_bounded=total.total_harm_vs_strongest_fraction
                           <= gate["maximum_total_harm_vs_strongest_fraction"],
        no_family_wrong_increase=bool(((families.M2-families.M1).dropna()
                                      <= gate["maximum_family_wrong_increase"]).all()),
        paired_macro_rmse_improves=interval.ci_high < gate["paired_macro_rmse_upper_bound_max_hz"],
        earlier_splits_no_new_harm=all(value == 0 for value in earlier_harms.values()))
    passed = all(checks.values())
    write_json(out/"readiness_decision.json", dict(
        trajectory_repair_readiness="SUPPORTED_WITH_LIMITATIONS" if passed else "NOT SUPPORTED",
        checks={k: bool(v) for k, v in checks.items()}, passed=passed,
        earlier_new_harms=earlier_harms,
        information_detector_readiness="NOT SUPPORTED; frozen TASK001 complete gates failed",
        modules_logically_separable=True, real_behavior_audit="ALLOWED" if passed else "SKIPPED",
        real_accuracy="UNKNOWN", production="RESEARCH_ONLY_NO_PROMOTION",
        new_harmed_vs_p3=int(m2.harmed_frames), total_harmed_vs_strongest=int(total.harmed_frames),
        verdict="MIXED" if m2.corrected_frames and m2.harmed_frames else
                "SUPPORTED_WITH_LIMITATIONS" if passed else "NOT SUPPORTED"))
    print((out/"readiness_decision.json").read_text())


def historical(out: Path) -> None:
    """Replay only the 28 old profile streams that account for D001's67 harms."""
    source = pd.read_csv(OLD/"held_out_metrics.csv")
    selected = source[(source.method == "M1") & (source.reference == "M0") & (source.harmed_frames > 0)]
    config = json.loads((OLD/"method_configs.json").read_text())
    rows = []
    replays = []
    for _, row in selected.iterrows():
        instance = int(row.case_id.rsplit("_", 1)[1])
        case = old_bench.generate(row.family, instance, "HELD_OUT")
        profile = next(p for p in PROFILES if p.profile_id == row.profile)
        stft, peaks = frozen.frontend(case.record, profile)
        result = frozen.consolidate(stft, peaks, frozen.FinalMethodConfig.from_dict(config["frozen_p3"]))
        m0 = result.trajectories["M0"].frequency_hz
        p3 = result.trajectories["M2"].frequency_hz
        proposals = method.propose_repairs(stft, peaks, p3, method.RepairConfig(**config["repair"]))
        m2, _ = method.apply_repairs(peaks, p3, proposals)
        for name, path in (("M0", m0), ("M1", p3), ("M2", m2)):
            old = source[(source.case_id == row.case_id) & (source.profile == row.profile)
                         & (source.method == name) & (source.reference == "M0")].iloc[0]
            if array_hash(path) != old.path_sha256:
                raise AssertionError(f"Historical path hash mismatch: {row.case_id}/{row.profile}/{name}")
        labels = old_bench.frame_labels(case, stft.time_s, stft.window_length_samples)
        truth = labels["truth"]
        harm = np.isfinite(truth) & (abs(m0-truth) <= bench.TOLERANCE_HZ) & (
            abs(p3-truth) > bench.TOLERANCE_HZ)
        assert int(harm.sum()) == int(row.harmed_frames)
        flags = bench.observational_flags(peaks, m0, p3)
        for i in np.flatnonzero(harm):
            c = min(peaks.candidates_by_frame[i], key=lambda c: abs(c.transition_frequency_hz-p3[i]))
            mechanism = ("TRUE_RETURN_SMOOTHED" if row.family in ("box_return", "real_excursion") else
                         "WEAK_TARGET_FADING" if row.family == "fading" else
                         "AMPLITUDE_IDENTITY_EXCHANGE" if row.family == "core_amplitude_exchange" else
                         "COMPONENT_DIVERGENCE_OR_BOUNDARY")
            rows.append(dict(case_id=row.case_id, family=row.family, seed=int(row.seed),
                profile=row.profile, frame=int(i), time_s=float(stft.time_s[i]), truth_hz=float(truth[i]),
                strongest_hz=float(m0[i]), p3_hz=float(p3[i]), m2_hz=float(m2[i]),
                candidate_rank=c.candidate_rank, background_db=float(c.peak_to_background_db),
                fast=bool(labels["fast"][i]), mechanism=mechanism,
                interpretation="generator/trajectory diagnosis; not P3-stage causal isolation",
                unchanged_by_m2=bool(m2[i] == p3[i]), flags="|".join(flags[i])))
        replays.append(dict(case_id=row.case_id, profile=row.profile, all_three_path_hashes_match=True,
                            harms=int(harm.sum())))
    assert len(rows) == 67
    write_csv(out/"task001_67_harmed_frames.csv", rows)
    write_json(out/"task001_historical_replay.json", dict(
        streams=len(replays), waveforms=selected.case_id.nunique(), harmed_frames=len(rows),
        output_hashes_checked=3*len(replays), all_path_hashes_match=True,
        counted_as_new_independent_experiments=False, streams_audited=replays))
    print(pd.DataFrame(rows).groupby(["family", "mechanism"]).size().to_string())


def finalize_tables(out: Path) -> None:
    table = pd.read_csv(out/"held_out_comparison.csv")
    for name, kind in (("baseline_comparison", "ALL"), ("error_case_breakdown", "family"),
                       ("profile_comparison", "profile")):
        write_csv(out/f"{name}.csv", table[table.dataset == kind].to_dict("records"))
    write_csv(out/"paired_waveform_uncertainty.csv", pd.read_csv(
        out/"held_out_paired_waveform_uncertainty.csv").to_dict("records"))
    write_csv(out/"intervention_audit.csv", pd.read_csv(
        out/"held_out_interventions.csv").to_dict("records"))
    trace = []
    distribution = []
    for split in ("development", "calibration", "held_out"):
        interventions = pd.read_csv(out/f"{split}_interventions.csv")
        proposals = pd.read_csv(out/f"{split}_proposals.csv")
        harmed = interventions[(interventions.kind == "M2_INTERVENTION") & interventions.harmed]
        for _, row in harmed.iterrows():
            proposal = proposals[(proposals.case_id == row.case_id) & (proposals.profile == row.profile)
                & (proposals.kind == "M2") & (proposals.proposal_id == row.proposal_id)].iloc[0]
            near_competitor = abs(row.selected_hz-row.competitor_hz) <= 85e6
            mechanism = ("TRUE_RETURN_REPLACED_BY_ANCHOR_BAND_COMPETITOR"
                         if "return" in row.family and near_competitor else "NEEDS_FRAME_REVIEW")
            trace.append(dict(**row.to_dict(), mechanism=mechanism,
                destination_near_competitor=bool(near_competitor),
                selected_to_truth_error_hz=abs(row.selected_hz-row.truth_hz),
                prediction_to_truth_error_hz=abs(row.prediction_hz-row.truth_hz),
                cofrequency_anchors=int(proposal.cofrequency_anchors),
                candidate_frequency_generated_by_predictor=False))
        prov = pd.read_csv(out/f"{split}_provenance.csv")
        for family, group in prov.groupby("family"):
            strict = proposals[(proposals.family == family) & (proposals.kind == "M2")]
            loose = proposals[(proposals.family == family) & (proposals.kind == "DIAG_NO_AMP")]
            distribution.append(dict(split=split.upper(), family=family,
                independent_waveforms=group.case_id.nunique(), streams=len(group),
                jump_triggers=int(group.jumps.sum()), strict_proposals=len(strict),
                ablation_proposals=len(loose), strict_frames=int(strict.frames.sum()),
                strict_corrected=int(strict.corrected.sum()), strict_harmed=int(strict.harmed.sum()),
                strict_harmful_proposals=int((strict.harmed > 0).sum()),
                strict_support_min=float(strict.support_fraction.min()) if len(strict) else None,
                strict_support_max=float(strict.support_fraction.max()) if len(strict) else None,
                interpretation="Separate admissible sets; overlap consumption can change pairing"))
    write_csv(out/"all_new_harmed_frame_mechanisms.csv", trace)
    write_csv(out/"proposal_acceptance_distribution.csv", distribution)
    unknown = sum(r["mechanism"] == "NEEDS_FRAME_REVIEW" for r in trace)
    write_json(out/"harm_trace_validation.json", dict(
        traced_new_harmed_frames=len(trace), unknown_mechanisms=unknown,
        all_frames_linked_to_original_proposal=True, official_labels_unchanged=True,
        all_new_harm_references="P3", full_pipeline_harms_separately_in="baseline_comparison.csv"))
    print(f"Traced {len(trace)} new harmed frames across splits; unresolved mechanisms={unknown}")


def figures(out: Path, destination_name: str = "figures") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination = out/destination_name
    destination.mkdir(exist_ok=False)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42})
    manifest = []

    def save(fig: Any, name: str, purpose: str) -> None:
        fig.savefig(destination/f"{name}.png", dpi=300, bbox_inches="tight")
        fig.savefig(destination/f"{name}.pdf", bbox_inches="tight")
        plt.close(fig)
        manifest.append(dict(name=name, purpose=purpose, selection="post-result descriptive",
                             counts_as_additional_experiment=False))

    table = pd.read_csv(out/"held_out_comparison.csv")
    fam = table[(table.dataset == "family") & (table.reference == "M1")]
    order = [f for f in bench.FAMILIES if f not in ("coherent_nontarget", "colored_noise")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 7), layout="constrained")
    for name, color, label, offset in (
        ("M0", "#777777", "Strongest", -.18), ("M1", "#E69F00", "Frozen P3", 0.),
        ("M2", "#0072B2", "Frozen bilateral repair", .18)):
        data = fam[fam.method == name].set_index("name").loc[order]
        axes[0].plot(data.rmse_hz/1e6, np.arange(len(order))+offset, marker="o",
                     linestyle="none", markersize=4, color=color, label=label)
    axes[0].set_yticks(np.arange(len(order)), [f.replace("_", " ") for f in order])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Pooled RMSE (MHz)")
    axes[0].legend(fontsize=9)
    data = fam[fam.method == "M2"].set_index("name").loc[order]
    axes[1].barh(np.arange(len(order))-.17, data.corrected_frames, height=.32,
                 color="#0072B2", label="Corrected vs P3")
    axes[1].barh(np.arange(len(order))+.17, data.harmed_frames, height=.32,
                 color="#D55E00", label="Harmed vs P3")
    axes[1].set_yticks(np.arange(len(order)), [f.replace("_", " ") for f in order])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Frame count (correlated observations)")
    axes[1].legend(fontsize=9)
    save(fig, "01_family_outcomes", "Benefits and harms in every target-present family")

    all_m2 = pd.read_csv(out/"held_out_interventions.csv")
    harmed = all_m2[(all_m2.kind == "M2_INTERVENTION") & all_m2.harmed]
    beneficial = all_m2[(all_m2.kind == "M2_INTERVENTION") & all_m2.corrected]
    cases = []

    def example_for(case_id: str, profile: str) -> Path:
        registered_profile = next(p for p in PROFILES if p.profile_id == profile)
        return out/"examples"/f"{case_id}_{registered_profile.profile_id}.npz"

    for selected, label in ((harmed, "new_harm"), (beneficial, "new_correction")):
        if len(selected):
            ranked = selected.groupby(["case_id", "profile"]).size().sort_values(ascending=False)
            for first in ranked.index:
                if example_for(first[0], first[1]).is_file():
                    cases.append((first[0], first[1], label))
                    break
    for family in ("normal_fast_return", "return_anchor_exchange", "quadratic_competition",
                   "amplitude_valley", "long_wrong", "anchor_switch"):
        candidates = sorted((out/"examples").glob(
            f"D002_HELD_OUT_{family}_*_AnalysisProfileId.BALANCED.npz"))
        if candidates:
            cases.append((candidates[0].stem.rsplit("_AnalysisProfileId.BALANCED", 1)[0],
                          "balanced", family))
    unique: set[tuple[str, str]] = set()
    for case_id, profile, label in cases:
        if (case_id, profile) in unique:
            continue
        unique.add((case_id, profile))
        path = example_for(case_id, profile)
        if not path.is_file():
            continue
        arrays = np.load(path)
        t = arrays["time_s"]*1e9
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
        amplitude = arrays["magnitude"]
        db = 20*np.log10(np.maximum(amplitude/max(float(amplitude.max()), 1e-30), 1e-8))
        mesh = axes[0].pcolormesh(t, arrays["frequency_hz"]/1e9, db,
                                  shading="nearest", cmap="magma", vmin=-50, vmax=0, rasterized=True)
        fig.colorbar(mesh, ax=axes[0], label="Relative amplitude (dB)", pad=.01)
        for ax in axes:
            for name, color, width, style, legend in (
                ("truth_hz", "#009E73", 2.4, "-", "Synthetic truth"),
                ("M0", "#888888", 1.1, ":", "Strongest"),
                ("M1", "#E69F00", 1.7, "--", "Frozen P3"),
                ("M2", "#0072B2", 1.2, "-", "Frozen bilateral repair")):
                ax.plot(t, arrays[name]/1e9, color=color, lw=width, ls=style, label=legend)
            changed = arrays["changed"]
            ax.scatter(t[changed], arrays["M2"][changed]/1e9, s=19, facecolors="none",
                       edgecolors="#D55E00", lw=.8, label="M2 modification", zorder=6)
            ax.set_ylabel("Frequency (GHz)")
        axes[1].set_xlabel("Time (ns)")
        handles, labels = axes[1].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, -.08),
                   ncol=3, fontsize=9, frameon=False)
        # Captions in manifest keep panels free of long case identifiers.
        save(fig, f"{len(manifest)+1:02d}_{label}", f"{case_id}/{profile}: {label}")
    proposals = pd.read_csv(out/"held_out_proposals.csv")
    strict = proposals[proposals.kind == "M2"]
    if len(strict):
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
        for bad, label, color in ((False, "No new harmed frame", "#0072B2"),
                                  (True, "At least one new harmed frame", "#D55E00")):
            subset = strict[(strict.harmed > 0) == bad]
            for ax in axes:
                ax.scatter(subset.anchor_residual_hz/1e6, subset.side_disagreement_hz/1e6,
                           s=28, alpha=.8, label=label, color=color)
        axes[0].axvline(35, color="black", ls=":", lw=1)
        axes[0].axhline(80, color="black", ls=":", lw=1)
        for ax in axes:
            ax.set(xlabel="Maximum anchor fit residual (MHz)",
                   ylabel="Left/right disagreement (MHz)")
        handles, labels = axes[1].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, -.12),
                   ncol=2, fontsize=9, frameon=False)
        save(fig, "10_certificate_overlap", "Low fit residual does not certify target identity")
    manifest_name = ("figure_manifest.json" if destination_name == "figures"
                     else destination_name+"_manifest.json")
    write_json(out/manifest_name, manifest)
    print(f"Saved {len(manifest)} PNG/PDF figure pairs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("summarize", "readiness", "historical", "figures",
                                           "figures-reviewed", "tables"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=tuple(bench.SPLITS))
    args = parser.parse_args()
    out = safe_output(args.output)
    if args.command == "summarize":
        if not args.split:
            raise ValueError("Choose a split")
        summarize(out, args.split)
    else:
        {"readiness": readiness, "historical": historical, "figures": figures,
         "figures-reviewed": lambda p: figures(p, "figures_reviewed"),
         "tables": finalize_tables}[args.command](out)


if __name__ == "__main__":
    main()
