"""Postprocessing only: full-denominator metrics and waveform-paired uncertainty."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .audit import OUT
from .common import WAVELENGTH_M
from .catalog import METHODS, run_folder
from .runner import write_csv, write_json


def aggregate(frame: Any, prefix: str) -> dict[str, Any]:
    n = int(frame[prefix+"target_n"].sum())
    valid = int(frame[prefix+"finite_n"].sum())
    failure = int(frame[prefix+"failure_n"].sum())
    wrong = int(frame[prefix+"wrong_finite_n"].sum())
    sse = float(frame[prefix+"sse_hz2"].sum())
    return dict(target_n=n, finite_n=valid, finite_rmse_m_s=np.sqrt(sse/valid)*WAVELENGTH_M/2
                if valid else None, coverage=valid/n if n else None,
                failure_fraction=failure/n if n else None,
                wrong_finite_fraction=wrong/valid if valid else None,
                failure_n=failure, wrong_finite_n=wrong,
                failure50_fraction=float(frame[prefix+"failure_50mhz_n"].sum())/n if n else None,
                failure200_fraction=float(frame[prefix+"failure_200mhz_n"].sum())/n if n else None)


def summary(stage: str) -> list[dict[str, Any]]:
    d = pd.read_csv(OUT/"tables"/f"all_{stage}_metrics.csv")
    rows = []
    for family in ["ALL", *sorted(d.family.unique())]:
        part = d if family == "ALL" else d[d.family == family]
        for method in METHODS:
            selected = part[part.method == method]
            for region in ("motion", "onset40", "fast", "low"):
                for channel in ("candidate", "accepted"):
                    rows.append(dict(stage=stage, family=family, method=method,
                        region=region, channel=channel, waveforms=len(selected),
                        **aggregate(selected, channel+"_"+region+"_")))
    write_csv(OUT/"tables"/f"{stage}_summary.csv", rows)
    for name in METHODS:
        write_csv(OUT/name/f"{stage}_summary.csv", [r for r in rows if r["method"] == name])
    return rows


def paired(stage: str) -> None:
    d = pd.read_csv(OUT/"tables"/f"all_{stage}_metrics.csv")
    d = d[d.candidate_motion_target_n > 0]
    rows = []
    for reference in ("stft512", "stft768", "gated_stft256", "gated_stft512", "legacy_m0_512", "legacy_m0_768"):
        ref = d[d.method == reference].set_index("case_id").sort_index()
        ids = ref.index
        rng = np.random.default_rng(81300001)
        draws = rng.integers(0, len(ids), (2000, len(ids)))
        for name in METHODS:
            current = d[d.method == name].set_index("case_id").reindex(ids)
            for channel in ("candidate", "accepted"):
                prefix = channel+"_motion_"
                failure_delta = ((current[prefix+"failure_n"]/current[prefix+"target_n"])
                                 -(ref[prefix+"failure_n"]/ref[prefix+"target_n"])).to_numpy()
                boot = np.mean(failure_delta[draws], axis=1)
                cover_delta = ((current[prefix+"finite_n"]/current[prefix+"target_n"])
                               -(ref[prefix+"finite_n"]/ref[prefix+"target_n"])).to_numpy()
                joint = np.isfinite(current[prefix+"rmse_m_s"]) & np.isfinite(ref[prefix+"rmse_m_s"])
                rmse_delta = (current.loc[joint, prefix+"rmse_m_s"]
                              -ref.loc[joint, prefix+"rmse_m_s"])
                rows.append(dict(stage=stage, method=name, reference=reference, channel=channel,
                    waveform_n=len(ids), failure_macro_delta=float(np.mean(failure_delta)),
                    failure_macro_delta_ci_low=float(np.quantile(boot, .025)),
                    failure_macro_delta_ci_high=float(np.quantile(boot, .975)),
                    coverage_macro_delta=float(np.mean(cover_delta)),
                    finite_rmse_paired_waveform_n=int(sum(joint)),
                    finite_rmse_macro_delta_m_s=float(rmse_delta.mean()) if len(rmse_delta) else None,
                    note="Failure CI keeps all motion waveforms; RMSE only both-defined subset"))
    write_csv(OUT/"tables"/f"{stage}_paired_bootstrap.csv", rows)


def onset_and_false_outputs() -> None:
    d = pd.read_csv(OUT/"tables/all_fresh_metrics.csv")
    rows = []
    for name in METHODS:
        s = d[d.method == name]
        motion = s[s.truth_onset_s.notna()]
        errors = motion.onset_error_ns.dropna().to_numpy()
        rows.append(dict(method=name, truth_event_n=len(motion), detected_n=len(errors),
            missed_n=int(motion.missed_onset.sum()),
            onset_median_signed_ns=float(np.median(errors)) if len(errors) else None,
            onset_median_absolute_ns=float(np.median(abs(errors))) if len(errors) else None,
            onset_p95_absolute_ns=float(np.quantile(abs(errors), .95)) if len(errors) else None,
            false_events_on_noise=int(s.false_event.sum()),
            noise_waveforms=int(sum(s.family == "noise_only")),
            static_frames=int(s.static_n.sum()), static_accepted_n=int(s.static_accepted_n.sum()),
            dropout_frames=int(s.dropout_n.sum()), dropout_accepted_n=int(s.dropout_accepted_n.sum()),
            static_false_fraction=float(s.static_accepted_n.sum()/s.static_n.sum()),
            dropout_false_fraction=float(s.dropout_accepted_n.sum()/s.dropout_n.sum())
            if s.dropout_n.sum() else None))
    write_csv(OUT/"tables/onset_and_false_outputs.csv", rows)


def real_and_runtime() -> None:
    d = pd.read_csv(OUT/"tables/all_real_metrics.csv")
    # Correct the source schema's legacy name: clutter method fits the residual.
    d["waveform_fit_domain"] = np.where(d.method == "clutter_varpro",
                                        "ORIGINAL_MINUS_PREDICTED_NUISANCE", "ORIGINAL")
    d = d.rename(columns={"raw_fit_r2_median": "model_domain_fit_r2_median"})
    write_csv(OUT/"tables/real_diagnostics.csv", d.to_dict("records"))
    rows = []
    for name in METHODS:
        s = d[d.method == name]
        for samples in (40000, 80000, 200001):
            selected = s[s.samples == samples]
            runtime = selected.total_s.to_numpy()
            rows.append(dict(method=name, samples=samples, records=len(runtime),
                median_total_s=float(np.median(runtime)), p95_total_s=float(np.quantile(runtime, .95)),
                max_total_s=float(np.max(runtime)),
                median_estimator_s=float(np.median(selected.estimator_s)),
                runs_above_three_seconds=int(sum(runtime > 3)),
                note="shared setup plus estimator and quality checks; no export time"))
    write_csv(OUT/"tables/real_runtime.csv", rows)
    write_json(OUT/"checks/exhaustive_coverage.json", dict(
        methods=len(METHODS), expected_raw_files=13, observed_raw_files=int(d.raw_path.nunique()),
        expected_voltage_streams=17, observed_voltage_streams=int(d.case_id.nunique()),
        expected_method_streams=17*len(METHODS), observed_method_streams=len(d),
        all_implemented_methods_on_all_raw=bool(all(len(d[d.method == name]) == 17 for name in METHODS)),
        failed_runs=d[d.status != "OK"].to_dict("records")))


def phase_stress() -> None:
    d = pd.read_csv(OUT/"tables/all_phase_stress_metrics.csv")
    rows = []
    for name in METHODS:
        s = d[d.method == name]
        for velocity in (15, 30, 50, 100, 200):
            instance = s.case_id.str[-2:].astype(int)
            part = s[instance % 5 == (15, 30, 50, 100, 200).index(velocity)]
            rows.append(dict(method=name, specified_velocity_m_s=velocity, waveforms=len(part),
                missed_onsets=int(part.missed_onset.sum()),
                **aggregate(part, "candidate_motion_"),
                accepted_coverage=float(part.accepted_motion_finite_n.sum()/part.accepted_motion_target_n.sum()),
                accepted_failure_fraction=float(part.accepted_motion_failure_n.sum()/part.accepted_motion_target_n.sum())))
    write_csv(OUT/"tables/phase_stress_by_velocity.csv", rows)


def failure_records() -> None:
    main = pd.read_csv(OUT/"tables/all_fresh_metrics.csv")
    for name in METHODS:
        d = main[(main.method == name) & (main.candidate_motion_target_n > 0)]
        worst = d.sort_values("accepted_motion_failure_fraction", ascending=False).head(8)
        write_json(OUT/name/"failure_records.json", dict(
            execution_failures=main[(main.method == name) & (main.status != "OK")].to_dict("records"),
            worst_registered_waveforms=[dict(case_id=r.case_id, family=r.family,
                accepted_failure_fraction=float(r.accepted_motion_failure_fraction),
                accepted_coverage=float(r.accepted_motion_coverage),
                missed_onset=bool(r.missed_onset)) for r in worst.itertuples()],
            criterion="Top eight full-denominator failure rates; selected AFTER evaluation for failure diagnosis only",
            raw_accuracy="Unavailable. Failures include absence of onset/accepted support, not verified physical errors."))


def audit_numeric_exports() -> None:
    checks = []
    # Independent recomputation of saved SSE/missing counts from numeric artifacts.
    for name in METHODS:
        for case_id in ("fresh_step_00", "fresh_dropout_00", "fresh_stationary_spur_00"):
            wave = np.load(OUT/"datasets/fresh"/f"{case_id}.npz")
            path = run_folder(OUT, name, "fresh", case_id)
            result = np.load(path/"trajectory.npz")
            import json
            recorded = json.loads((path/"metrics.json").read_text(encoding="utf-8"))
            truth = wave["truth_hz"][result["sample_indices"]]
            target = np.isfinite(truth)
            for channel, key in (("candidate", "frequency_hz"), ("accepted", "accepted_hz")):
                f = result[key]
                valid = target & np.isfinite(f)
                sse = float(np.sum((f[valid]-truth[valid])**2))
                failure = int(sum(target & ~np.isfinite(f))+sum(abs(f[valid]-truth[valid])>100e6))
                assert np.isclose(sse, recorded[channel+"_motion_sse_hz2"], rtol=1e-12)
                assert failure == recorded[channel+"_motion_failure_n"]
                assert np.isnan(result["corrected_velocity_m_s"]).all()
                checks.append(dict(method=name, case_id=case_id, channel=channel,
                                    sse_and_missing_recomputed=True, corrected_all_nan=True))
    write_json(OUT/"checks/numeric_export_audit.json", checks)


def main() -> None:
    for stage in ("fresh", "phase_stress"):
        summary(stage)
        paired(stage)
    onset_and_false_outputs()
    real_and_runtime()
    phase_stress()
    failure_records()
    audit_numeric_exports()
    print("Summaries, paired intervals, exhaustive raw coverage and numeric audit saved", flush=True)


if __name__ == "__main__":
    main()
