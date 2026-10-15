"""Summarize registered metrics; no estimator tuning and no waveform regeneration."""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from scipy.stats import rankdata  # type: ignore[import-untyped]

from audit_denoising_task001 import safe_output
from run_denoising_task001 import COUNTS, aggregate, write_csv, write_json
from dps_studio.research import denoising_task001 as method


def meaningful(value: Any, fallback: float = 1.) -> float:
    return fallback if value is None else float(value)


def activation(row: dict[str, Any]) -> dict[str, bool]:
    return dict(corrected_at_least_5=row["corrected_frames"] >= 5,
        intervention_precision=meaningful(row["intervention_precision"], 0) >= .95,
        harmed_at_most_1=row["harmed_frames"] <= 1,
        normal_preservation=meaningful(row["normal_preservation"]) >= .999,
        fast_preservation=meaningful(row["fast_preservation"]) >= .995,
        complete_output=row["coverage"] == 1.)


def screen(out: Path) -> None:
    rows, decisions = [], {}
    for split in ("TRAIN", "CALIBRATION", "VALIDATION"):
        table = pd.read_csv(out / f"{split.lower()}_metrics.csv")
        for name in ("M0", "M1", "M2", "M3", "M4_NO_AMP"):
            selected = table[(table.method == name) & (table.reference == "M1")]
            if selected.empty:
                continue
            row = aggregate(selected)
            rows.append(dict(split=split, method=name, **row))
            if split == "VALIDATION" and name in ("M2", "M3"):
                checks = activation(row)
                decisions[name] = dict(checks=checks, eligible=all(checks.values()), metrics=row)
    write_csv(out / "screening_summary.csv", rows)
    write_json(out / "validation_activation.json", decisions)
    print(json.dumps(decisions, ensure_ascii=False, indent=2))


def paired_uncertainty(table: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for dataset in ("ALL", "STRESS", "CORE"):
        selected = table[table.reference == "M1"]
        if dataset != "ALL":
            is_core = selected.family.str.startswith("core_")
            selected = selected[is_core if dataset == "CORE" else ~is_core]
        waveform = selected.groupby(["case_id", "method"])[
            ["sse_hz2", "squared_error_frames", "wrong_frames", "truth_frames"]].sum()
        waveform["rmse_hz"] = np.sqrt(waveform.sse_hz2 / waveform.squared_error_frames)
        waveform["wrong_branch_fraction"] = waveform.wrong_frames / waveform.truth_frames
        for name in ("M2", "M3"):
            for metric in ("rmse_hz", "wrong_branch_fraction"):
                values = waveform[metric].unstack("method")
                delta = (values[name] - values.M1).dropna().to_numpy()
                rng = np.random.default_rng(41099001)
                bootstrap = np.mean(delta[rng.integers(0, len(delta), (4000, len(delta)))], axis=1)
                low, high = np.quantile(bootstrap, [.025, .975])
                rows.append(dict(dataset=dataset, comparison=f"{name}-M1", metric=metric,
                    waveforms=len(delta), mean_difference=float(delta.mean()),
                    ci_low=float(low), ci_high=float(high), improved=int((delta < 0).sum()),
                    worsened=int((delta > 0).sum()), unchanged=int((delta == 0).sum()),
                    resamples=4000, seed=41099001))
    return rows


def classification(out: Path) -> list[dict[str, Any]]:
    model = method.LogisticModel.from_dict(json.loads((out / "model.json").read_text()))
    cutoff = json.loads((out / "calibration_selection.json").read_text())["threshold"]
    rows = []
    for split in COUNTS:
        path = out / ("train_v2_features.csv" if split == "TRAIN" else f"{split.lower()}_features.csv")
        if split == "TRAIN" and not path.exists():
            path = out / "train_features.csv"
        if not path.exists():
            continue
        table = pd.read_csv(path)
        for kind, group in table.groupby("kind"):
            y = group.label.to_numpy(bool)
            p = model.predict(group[list(method.FEATURE_NAMES)].to_numpy(float))
            positive = p >= cutoff
            tp, fp = int((positive & y).sum()), int((positive & ~y).sum())
            fn, tn = int((~positive & y).sum()), int((~positive & ~y).sum())
            n1, n0 = int(y.sum()), int((~y).sum())
            auc = float((rankdata(p)[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 * n0 else None
            ece = 0.
            for left in np.linspace(0, .9, 10):
                mask = (p >= left) & (p < left + .1 + (1e-12 if left > .89 else 0))
                if mask.any():
                    ece += float(mask.mean() * abs(p[mask].mean() - y[mask].mean()))
            sizes = group.groupby("case_id").case_id.transform("size").to_numpy(float)
            weights = 1 / sizes
            weights /= weights.sum()
            rows.append(dict(split=split, kind=kind, candidates=len(y),
                contributing_waveforms=int(group.case_id.nunique()), positive=n1, negative=n0,
                tp=tp, fp=fp, fn=fn, tn=tn, precision=tp / (tp + fp) if tp + fp else None,
                recall=tp / (tp + fn) if tp + fn else None, pooled_auroc=auc,
                brier=float(np.mean((p - y)**2)), waveform_weighted_brier=float(np.sum(weights * (p-y)**2)),
                log_loss=float(np.mean(-(y * np.log(np.maximum(p, 1e-12)))
                                      - (~y) * np.log(np.maximum(1 - p, 1e-12)))),
                ece_10_bins=ece, cutoff=cutoff))
    return rows


def training_trace(out: Path) -> None:
    """Replay TRAIN optimizer to retain coefficients; never select an iteration."""
    original = method.LogisticModel.from_dict(json.loads((out / "model.json").read_text()))
    training_path = out / "train_v2_features.csv"
    if not training_path.exists():
        training_path = out / "train_features.csv"
    table = pd.read_csv(training_path)
    table = table[table.kind == "all_candidates"]
    x = table[list(method.FEATURE_NAMES)].to_numpy(float)
    y = table.label.to_numpy(bool)
    sizes = table.groupby("case_id").case_id.transform("size").to_numpy(float)
    snapshots: list[method.FloatArray] = []
    replay, objective = method.fit_logistic(x, y, 1 / sizes, split="TRAIN",
        iteration_callback=snapshots.append)
    for a, b in ((original.mean, replay.mean), (original.scale, replay.scale),
                 (original.coefficients, replay.coefficients)):
        if not np.array_equal(a, b):
            raise AssertionError("Optimizer replay differs from frozen model; no trace claimed")
    datasets = {"train": (x, y)}
    for split in ("CALIBRATION", "VALIDATION"):
        frame = pd.read_csv(out / f"{split.lower()}_features.csv")
        frame = frame[frame.kind == "all_candidates"]
        datasets[split.lower()] = (frame[list(method.FEATURE_NAMES)].to_numpy(float),
                                   frame.label.to_numpy(bool))
    rows = []
    for i, coefficients in enumerate(snapshots):
        point = method.LogisticModel(original.mean, original.scale, coefficients)
        row = dict(iteration=i + 1, regularized_train_objective=objective[i])
        for split, (features, labels) in datasets.items():
            p = np.clip(point.predict(features), 1e-12, 1 - 1e-12)
            row[split + "_log_loss"] = float(np.mean(-(labels * np.log(p))
                                                       - (~labels) * np.log(1 - p)))
        rows.append(row)
    write_csv(out / "training_validation_curve.csv", rows)
    write_json(out / "optimizer_trace_replay.json", dict(
        final_mean_scale_coefficients_exact=True, iterations=len(snapshots),
        used_for_iteration_selection=False, held_out_evaluated_per_iteration=False,
        purpose="Deterministic TRAIN replay for audit/curves only; original model file untouched"))


def final_gates(comparisons: list[dict[str, Any]], paired: list[dict[str, Any]],
                family: list[dict[str, Any]]) -> dict[str, Any]:
    def get(name: str, dataset: str) -> dict[str, Any]:
        return next(r for r in comparisons if r["method"] == name
                    and r["dataset"] == dataset and r["reference"] == "M1")
    decisions: dict[str, Any] = {}
    for name in ("M2", "M3"):
        row, core, p3 = get(name, "ALL"), get(name, "CORE"), get("M1", "CORE")
        interval = next(r for r in paired if r["comparison"] == f"{name}-M1"
                        and r["metric"] == "rmse_hz" and r["dataset"] == "ALL")
        checks = dict(corrected_at_least_20=row["corrected_frames"] >= 20,
            precision_at_least_95pct=meaningful(row["intervention_precision"], 0) >= .95,
            harm_at_most_1pct=meaningful(row["harm_rate"]) <= .01,
            normal_at_least_999=meaningful(row["normal_preservation"]) >= .999,
            fast_at_least_995=meaningful(row["fast_preservation"]) >= .995,
            coverage_one=row["coverage"] == 1.,
            wrong_improves=row["wrong_frames"] < get("M1", "ALL")["wrong_frames"],
            paired_rmse_ci_below_zero=interval["ci_high"] < 0,
            core_rmse_preserved=core["rmse_hz"] <= p3["rmse_hz"] + max(1e6, .01 * p3["rmse_hz"]),
            core_wrong_preserved=core["wrong_branch_fraction"] <= p3["wrong_branch_fraction"] + .001)
        decisions[name] = dict(checks=checks, passed=all(checks.values()))
    signal = get("M2", "ALL")
    fam = {r["family"]: r for r in family if r["method"] == "M2" and r["reference"] == "M1"}
    checks = dict(target_recall=meaningful(signal["target_present_recall"], 0) >= .98,
        weak_recall=1 - meaningful(signal["weak_target_false_rejection"]) >= .95,
        pure_noise_rejection=meaningful(fam["pure_noise"]["no_target_rejection"], 0) >= .99,
        colored_noise_rejection=meaningful(fam["colored_noise"]["no_target_rejection"], 0) >= .95,
        all_no_target_rejection=meaningful(signal["no_target_rejection"], 0) >= .95)
    decisions["detector"] = dict(checks=checks, passed=all(checks.values()))
    decisions["real_data_ready"] = bool(decisions["M2"]["passed"] and decisions["detector"]["passed"])
    return decisions


def table_markdown(rows: list[dict[str, Any]], columns: list[tuple[str, str, float]]) -> str:
    lines = ["| " + " | ".join(label for _, label, _ in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for key, _, scale in columns:
            value = row.get(key)
            values.append("—" if value is None else f"{value * scale:.4f}" if isinstance(value, (float, np.floating))
                          else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def finalize(out: Path) -> None:
    table = pd.read_csv(out / "held_out_metrics.csv")
    comparisons, families, profiles = [], [], []
    for (name, reference), group in table.groupby(["method", "reference"]):
        for dataset in ("ALL", "CORE", "STRESS"):
            core = group.family.str.startswith("core_")
            selected = group if dataset == "ALL" else group[core if dataset == "CORE" else ~core]
            row = aggregate(selected)
            macro_rows = [aggregate(wave) for _, wave in selected.groupby("case_id")]
            for metric in ("rmse_hz", "wrong_branch_fraction", "target_present_recall",
                           "no_target_rejection", "weak_target_false_rejection"):
                values = [r[metric] for r in macro_rows if r[metric] is not None]
                row["macro_" + metric] = float(np.mean(values)) if values else None
            comparisons.append(dict(dataset=dataset, method=name, reference=reference, **row))
        for family, selected in group.groupby("family"):
            families.append(dict(family=family, method=name, reference=reference, **aggregate(selected)))
        for profile, selected in group.groupby("profile"):
            profiles.append(dict(profile=profile, method=name, reference=reference, **aggregate(selected)))
    paired = paired_uncertainty(table)
    gates = final_gates(comparisons, paired, families)
    detector_table = pd.read_csv(out / "held_out_detectors.csv")
    detector_rows = []
    detector_decisions = {}
    detector_paired = []
    for name, group in detector_table.groupby("detector"):
        for family, selected in [("ALL", group), *list(group.groupby("family"))]:
            counts = aggregate(selected.assign(candidate_recalled=0))
            counts["truth_near_supported"] = int(selected.truth_near_supported.sum())
            counts["weak_truth_near_supported"] = int(selected.weak_truth_near_supported.sum())
            counts["truth_near_support_recall"] = (counts["truth_near_supported"] / counts["target_frames"]
                                                   if counts["target_frames"] else None)
            counts["weak_truth_near_support_recall"] = (counts["weak_truth_near_supported"] / counts["weak_frames"]
                                                        if counts["weak_frames"] else None)
            waveform_rows = [aggregate(wave.assign(candidate_recalled=0))
                             for _, wave in selected.groupby("case_id")]
            for metric in ("target_present_recall", "no_target_rejection", "weak_target_false_rejection"):
                values = [r[metric] for r in waveform_rows if r[metric] is not None]
                counts["macro_" + metric] = float(np.mean(values)) if values else None
            detector_rows.append(dict(detector=name, family=family, **counts))
        counts = aggregate(group.assign(candidate_recalled=0))

        def reject(family: str) -> float:
            selected = group[group.family == family]
            return float(selected.absent_rejected.sum() / selected.absent_frames.sum())

        checks = dict(target_recall=meaningful(counts["target_present_recall"], 0) >= .98,
            weak_recall=1 - meaningful(counts["weak_target_false_rejection"]) >= .95,
            pure_noise_rejection=reject("pure_noise") >= .99,
            colored_noise_rejection=reject("colored_noise") >= .95,
            all_no_target_rejection=meaningful(counts["no_target_rejection"], 0) >= .95)
        detector_decisions[str(name)] = dict(checks=checks, passed=all(checks.values()))
    for family, group in [("ALL", detector_table), *list(detector_table.groupby("family"))]:
        wave_rows = []
        for (case_id, name), wave in group.groupby(["case_id", "detector"]):
            counts = aggregate(wave.assign(candidate_recalled=0))
            wave_rows.append(dict(case_id=case_id, detector=name,
                **{metric: counts[metric] for metric in
                   ("target_present_recall", "no_target_rejection", "weak_target_false_rejection")}))
        waves = pd.DataFrame(wave_rows)
        for metric in ("target_present_recall", "no_target_rejection", "weak_target_false_rejection"):
            paired_values = waves.pivot(index="case_id", columns="detector", values=metric)
            delta = (paired_values.LOCAL_A001 - paired_values.GLOBAL_A01).dropna().to_numpy()
            if not len(delta):
                continue
            rng = np.random.default_rng(41099001)
            intervals = np.mean(delta[rng.integers(0, len(delta), (4000, len(delta)))], axis=1)
            low, high = np.quantile(intervals, [.025, .975])
            detector_paired.append(dict(family=family, metric=metric, comparison="LOCAL-GLOBAL",
                waveforms=len(delta), mean_difference=float(delta.mean()), ci_low=float(low),
                ci_high=float(high), resamples=4000, seed=41099001))
    gates["detectors"] = detector_decisions
    gates["real_data_ready"] = bool(gates["M2"]["passed"] and
                                    any(d["passed"] for d in detector_decisions.values()))
    write_csv(out / "experiment_summary.csv", table.to_dict("records"))
    write_csv(out / "baseline_comparison.csv", comparisons)
    write_csv(out / "error_case_breakdown.csv", families)
    write_csv(out / "profile_comparison.csv", profiles)
    write_csv(out / "paired_waveform_uncertainty.csv", paired)
    write_csv(out / "classifier_metrics.csv", classification(out))
    write_csv(out / "detector_comparison.csv", detector_rows)
    write_csv(out / "detector_paired_waveform_uncertainty.csv", detector_paired)
    intervention = out / "held_out_interventions.csv"
    if intervention.exists():
        write_csv(out / "intervention_audit.csv", pd.read_csv(intervention).to_dict("records"))
    write_json(out / "success_gates.json", gates)
    (out / "results_narrative.md").write_text(results_narrative(out, comparisons, families, paired, gates),
                                             encoding="utf-8")
    print(json.dumps(gates, indent=2))


def results_narrative(out: Path, comparisons: list[dict[str, Any]],
                      families: list[dict[str, Any]], paired: list[dict[str, Any]],
                      gates: dict[str, Any]) -> str:
    overall = [r for r in comparisons if r["dataset"] == "ALL" and r["reference"] == "M1"]
    selected = [r for r in families if r["reference"] == "M1"]
    columns = [("method", "Method", 1), ("rmse_hz", "RMSE / MHz", 1e-6),
               ("wrong_branch_fraction", "Wrong / %", 100), ("coverage", "Coverage / %", 100),
               ("interventions", "Changes vs P3", 1), ("corrected_frames", "Corrected", 1),
               ("harmed_frames", "Harmed", 1), ("intervention_precision", "Precision / %", 100)]
    text = "# Registered held-out results\n\n" + table_markdown(overall, columns)
    text += "\n\n## By family, compared with frozen P3\n\n"
    text += table_markdown(selected, [("family", "Family", 1), *columns])
    text += "\n\n## Independent waveform paired bootstrap\n\n"
    text += table_markdown([r for r in paired if r["metric"] == "rmse_hz"], [
        ("dataset", "Dataset", 1), ("comparison", "Comparison", 1),
        ("waveforms", "Independent waveforms", 1), ("mean_difference", "Mean delta / MHz", 1e-6),
        ("ci_low", "95% low / MHz", 1e-6), ("ci_high", "95% high / MHz", 1e-6),
        ("improved", "Improved", 1), ("worsened", "Worsened", 1)])
    detector = next(r for r in overall if r["method"] == "M2")
    text += ("\n\n## Signal support is not target identity\n\n"
        f"Target-present recall {detector['target_present_recall']:.3%}; "
        f"no-target rejection {detector['no_target_rejection']:.3%}; "
        f"weak-target false rejection {detector['weak_target_false_rejection']:.3%}. "
        "False-supported is a spectral qualification proxy, not a VALID measurement. "
        "Validated frequency remains NaN throughout; this semantic safeguard is not counted "
        "as perfect detection. Coherent non-target remains in the negative denominator.\n")
    text += "\n## Registered gates\n\n```json\n" + json.dumps(gates, indent=2) + "\n```\n"
    return text


def figures(out: Path) -> None:
    # A single owned temporary font/config cache disappears on success or failure.
    with tempfile.TemporaryDirectory(prefix="d1_plot_", dir="D:/") as scratch:
        os.environ["MPLCONFIGDIR"] = scratch
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
            "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none"})
        folder = out / "figures"
        folder.mkdir(exist_ok=True)
        palette = {"M0": "#999999", "M1": "#0072B2", "M2": "#D55E00", "M3": "#009E73"}

        def save(fig: Any, name: str) -> None:
            fig.savefig(folder / f"{name}.png", dpi=300, bbox_inches="tight")
            fig.savefig(folder / f"{name}.svg", bbox_inches="tight")
            plt.close(fig)

        family = pd.read_csv(out / "error_case_breakdown.csv")
        family = family[(family.reference == "M1") & ~family.family.str.startswith("core_")]
        fig, ax = plt.subplots(figsize=(10.5, 4.3))
        order = ["normal", "jump", "broadband", "fading", "competition", "fast_descent",
                 "smooth_wrong", "crossing", "real_excursion", "weak_target"]
        for offset, name in enumerate(palette):
            subset = family[family.method == name].set_index("family")
            ax.bar(np.arange(len(order)) + (offset - 1.5) * .18,
                   [subset.loc[f, "rmse_hz"] / 1e6 for f in order], width=.18,
                   label=name, color=palette[name])
        ax.set_xticks(np.arange(len(order)), [f.replace("_", " ") for f in order],
                      rotation=25, ha="right")
        ax.set_ylabel("Frequency RMSE (MHz)")
        ax.legend(ncol=4, loc="upper left")
        ax.text(.99, .98, "Held-out synthetic truth; 8 waveforms/family, paired profiles",
                ha="right", va="top", transform=ax.transAxes, fontsize=8)
        fig.tight_layout()
        save(fig, "01_difficult_scenes")
        for name, filename in (("normal", "02_normal_protection"),
                               ("jump", "03_jump_case"),
                               ("pre_event", "04_no_information")):
            with np.load(out / "examples" / f"{name}.npz") as data:
                fig, axes = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True,
                                         gridspec_kw={"height_ratios": [3, 1]})
                db = 20 * np.log10(np.maximum(data["magnitude"], 1e-8))
                mesh = axes[0].pcolormesh(data["time_s"] * 1e9, data["frequency_hz"] / 1e9,
                                   db, shading="auto", cmap="magma", vmin=-65, vmax=-6,
                                   rasterized=True)
                axes[0].plot(data["time_s"] * 1e9, data["truth_hz"] / 1e9,
                             color="white", lw=2.5, label="Synthetic truth")
                for method_name in palette:
                    axes[0].plot(data["time_s"] * 1e9, data[method_name] / 1e9,
                                 color=palette[method_name], lw=1, ls=":" if method_name == "M3" else "-",
                                 label=method_name)
                axes[0].set_ylabel("Frequency (GHz)")
                axes[0].set_ylim(.05, 6.0)
                axes[0].legend(ncol=5, loc="upper right", fontsize=8,
                               facecolor="#333333", labelcolor="white", framealpha=.85)
                axes[0].text(.01, .04, f"{name.replace('_', ' ')}; preselected first held-out waveform",
                             color="white", transform=axes[0].transAxes, fontsize=8)
                changes = int(np.sum(data["M2"] != data["M1"]))
                old_error, new_error = abs(data["M1"] - data["truth_hz"]), abs(data["M2"] - data["truth_hz"])
                corrected = int(np.sum((old_error > 200e6) & (new_error <= 200e6)))
                harmed = int(np.sum((old_error <= 200e6) & (new_error > 200e6)))
                axes[0].text(.01, .10, f"M2 vs P3: {changes} changes, {corrected} corrected, {harmed} harmed",
                             color="white", transform=axes[0].transAxes, fontsize=8)
                axes[1].step(data["time_s"] * 1e9, data["supported"], color="#0072B2",
                             where="mid", label="Global floor")
                axes[1].step(data["time_s"] * 1e9, data["local_supported"], color="#D55E00",
                             ls=":", where="mid", label="Local floor")
                axes[1].set_yticks([0, 1], ["No evidence", "Support"])
                axes[1].set_xlabel("Time (ns)")
                axes[1].set_ylabel("Quality proxy")
                axes[1].legend(ncol=2, fontsize=8, loc="lower right")
                fig.tight_layout()
                fig.subplots_adjust(right=.86)
                color_axis = fig.add_axes((.89, .36, .018, .49))
                fig.colorbar(mesh, cax=color_axis, label="STFT magnitude (dB re 1 V)")
                save(fig, filename)
        fig, axes = plt.subplots(3, 1, figsize=(9, 7.0), sharex=True)
        for ax, name in zip(axes, ("fast_descent", "real_excursion", "box_return"), strict=True):
            with np.load(out / "examples" / f"{name}.npz") as data:
                ax.plot(data["time_s"] * 1e9, data["truth_hz"] / 1e9, color="black", lw=2,
                        label="Synthetic truth")
                for method_name in palette:
                    ax.plot(data["time_s"] * 1e9, data[method_name] / 1e9, color=palette[method_name],
                            lw=1, ls=":" if method_name == "M3" else "-", label=method_name)
                ax.set_ylabel("Frequency (GHz)")
                ax.text(.01, .07, name.replace("_", " "), transform=ax.transAxes)
                ax.set_xlim(220, 500)
        axes[0].legend(ncol=5, fontsize=8)
        axes[-1].set_xlabel("Time (ns)")
        fig.tight_layout()
        save(fig, "05_fast_change_audit")
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
        curve = pd.read_csv(out / "training_validation_curve.csv")
        axes[0].plot(curve.iteration, curve.train_log_loss, marker="o", ms=3,
                     color="#0072B2", label="Train")
        axes[0].plot(curve.iteration, curve.validation_log_loss, marker="o", ms=3,
                     color="#D55E00", label="Validation (diagnostic)")
        axes[0].set_xlabel("L-BFGS iteration (exact TRAIN replay)")
        axes[0].set_ylabel("Candidate log loss")
        axes[0].legend(fontsize=8)
        classification_table = pd.read_csv(out / "classifier_metrics.csv")
        classification_table = classification_table[classification_table.kind == "all_candidates"].set_index("split")
        splits = list(COUNTS)
        axes[1].bar(np.arange(4), [classification_table.loc[s, "brier"] for s in splits], color="#0072B2")
        axes[1].set_xticks(np.arange(4), ["Train", "Cal", "Validation", "Held-out"], rotation=20)
        axes[1].set_ylabel("Candidate Brier score (fixed model)")
        axes[1].text(.5, 1.04, "Fixed model; independent waveform groups",
                     transform=axes[1].transAxes, ha="center", va="bottom", fontsize=8)
        fig.tight_layout()
        save(fig, "06_classifier_training_test")
        detector = pd.read_csv(out / "detector_comparison.csv")
        fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.6))
        for offset, name in enumerate(("GLOBAL_A01", "LOCAL_A001")):
            selected = detector[detector.detector == name].set_index("family")
            negatives = ["pure_noise", "colored_noise", "coherent_nontarget"]
            axes[0].bar(np.arange(3) + (offset - .5) * .36,
                        [100 * selected.loc[f, "no_target_rejection"] for f in negatives],
                        width=.36, label=name, color=("#0072B2", "#D55E00")[offset])
            axes[1].bar(offset, 100 * selected.loc["weak_target", "weak_target_false_rejection"],
                        color=("#0072B2", "#D55E00")[offset])
        axes[0].set_xticks(np.arange(3), ["White noise", "Colored noise", "Coherent non-target"])
        axes[0].set_ylabel("No-target rejection (%)")
        axes[0].legend(fontsize=8, loc="upper right")
        axes[1].set_xticks(np.arange(2), ["Global floor", "Local floor"])
        axes[1].set_ylabel("Weak-target false rejection (%)")
        for ax in axes:
            ax.set_ylim(0, 108)
        fig.tight_layout()
        save(fig, "07_detection_tradeoff")


def added_repair_example(out: Path) -> None:
    """First improving jump example, explicitly selected after the result table.

    Illustrative replay only: exact hashes must equal the one formal held-out run.
    The original preselected first case remains saved even when M2 did not change it.
    """
    from dps_studio.core.analysis_profiles import BALANCED_PROFILE
    from dps_studio.research import denoising_task001_benchmark as benchmark
    from dps_studio.research import task028_consolidation as baseline
    manifest = json.loads((out / "held_out_source_freeze.json").read_text())
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p, h in manifest.items()):
        raise RuntimeError("Cannot replay changed held-out sources")
    table = pd.read_csv(out / "held_out_metrics.csv")
    candidates = table[(table.method == "M2") & (table.reference == "M1")
        & (table.family == "jump") & (table.profile == "balanced") & (table.corrected_frames > 0)]
    row = candidates.sort_values("case_id").iloc[0]
    instance = int(row.case_id.rsplit("_", 1)[1])
    case = benchmark.generate("jump", instance, "HELD_OUT")
    cfg = json.loads((out / "method_configs.json").read_text())
    stft, peaks = baseline.frontend(case.record, BALANCED_PROFILE)
    frozen = baseline.consolidate(stft, peaks, baseline.FinalMethodConfig.from_dict(cfg["frozen_p3"]))
    m1 = frozen.trajectories["M2"].frequency_hz
    proposals = method.propose_repairs(stft, peaks, m1, method.RepairConfig(**cfg["repair"]))
    m2, _ = method.apply_repairs(peaks, m1, proposals)
    model = method.LogisticModel.from_dict(json.loads((out / "model.json").read_text()))
    cutoff = json.loads((out / "calibration_selection.json").read_text())["threshold"]
    m3, _ = method.apply_repairs(peaks, m1, proposals, model=model, probability_threshold=cutoff)
    paths = {"M0": frozen.trajectories["M0"].frequency_hz, "M1": m1, "M2": m2, "M3": m3}
    hashes = {}
    for name, path in paths.items():
        h = hashlib.sha256(path.tobytes()).hexdigest()
        expected = table[(table.case_id == case.case_id) & (table.method == name)
                         & (table.reference == "M1") & (table.profile == "balanced")].iloc[0].path_sha256
        if h != expected:
            raise AssertionError("Illustrative replay differs from registered output")
        hashes[name] = h
    labels = benchmark.frame_labels(case, stft.time_s, stft.window_length_samples)
    band = stft.frequency_hz <= 6e9
    arrays: dict[str, Any] = dict(time_s=stft.time_s, frequency_hz=stft.frequency_hz[band],
        magnitude=np.abs(stft.spectrum[band]).astype(np.float32), truth_hz=labels["truth"],
        raw_time_s=case.record.time_s, raw_voltage_v=case.record.voltage_v, **paths)
    with (out / "examples/jump_added_repair.npz").open("xb") as handle:
        np.savez_compressed(handle, **arrays)
    write_json(out / "illustrative_replay_audit.json", dict(case_id=case.case_id, profile="balanced",
        selection="Lexicographically first jump with extra corrected frames; post-result illustration",
        formal_metrics_recomputed=False, counted_as_new_experiment=False, exact_output_hashes=True,
        hashes=hashes, added_corrected=int(row.corrected_frames), added_harmed=int(row.harmed_frames)))
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(9, 4.2))
    mesh = ax.pcolormesh(stft.time_s * 1e9, stft.frequency_hz[band] / 1e9,
        20 * np.log10(np.maximum(np.abs(stft.spectrum[band]), 1e-8)), cmap="magma",
        vmin=-65, vmax=-6, shading="auto", rasterized=True)
    ax.plot(stft.time_s * 1e9, labels["truth"] / 1e9, color="white", lw=3, label="Synthetic truth")
    for name, color in zip(paths, ("#999999", "#0072B2", "#D55E00", "#009E73"), strict=True):
        ax.plot(stft.time_s * 1e9, paths[name] / 1e9, color=color, lw=1.2,
                ls=":" if name == "M3" else "-", label=name)
    ax.set(xlabel="Time (ns)", ylabel="Frequency (GHz)", ylim=(.05, 6.0))
    ax.legend(ncol=5, loc="upper right", fontsize=8, facecolor="#333333", labelcolor="white")
    ax.text(.01, .06, f"{case.case_id}; added corrections={int(row.corrected_frames)}, harm=0\n"
        "First improving jump (post-result illustration); exact frozen hash replay",
        color="white", transform=ax.transAxes, fontsize=8)
    fig.colorbar(mesh, ax=ax, label="STFT magnitude (dB re 1 V)")
    fig.tight_layout()
    fig.savefig(out / "figures/08_added_repair.png", dpi=300, bbox_inches="tight")
    fig.savefig(out / "figures/08_added_repair.svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("screen", "trace", "finalize", "figures", "added-example"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = safe_output(args.output)
    {"screen": screen, "trace": training_trace, "finalize": finalize, "figures": figures,
     "added-example": added_repair_example}[args.command](out)


if __name__ == "__main__":
    main()
