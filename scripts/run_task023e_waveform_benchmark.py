"""Build frozen phase-B inputs after phase-A scorer stop; no model selection."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES,
    PROFILES,
    SAMPLE_COUNT,
    SAMPLE_RATE_HZ,
    ambiguous_pair,
    array_hash,
    generate_case,
    profile_input,
    strongest_metrics,
)
from scripts.run_task023e_proposal_audit import ROOT, write_csv


def save_case(path, case):
    with path.open("xb") as handle:
        np.savez_compressed(handle, time_s=case.record.time_s, voltage_v=case.record.voltage_v,
                            truth_hz=case.truth_hz, nuisance_hz=case.nuisance_hz,
                            focus=case.focus)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts/task023e_cross_scale_evidence"):
        raise ValueError("Output must be a TASK-023E Research artifact")
    gate = json.loads((output / "phase_a_gate.json").read_text(encoding="utf-8"))
    if not gate["stop_scorer"]:
        raise ValueError("This runner implements the declared scorer-stop branch only")
    generated = output / "generated_waveforms"
    generated.mkdir(exist_ok=False)
    figures = output / "figures"
    figures.mkdir(exist_ok=False)
    protocol = {
        "families": FAMILIES, "instances_per_family": 24,
        "calibration_instances": list(range(8)), "held_out_instances": list(range(8, 24)),
        "sample_rate_hz": SAMPLE_RATE_HZ, "samples": SAMPLE_COUNT,
        "profiles": [{"id": p.profile_id.value, "window": p.window_length_samples,
                      "overlap": p.overlap_samples, "nfft": p.nfft} for p in PROFILES],
        "model_evaluation": "NOT_RUN_PHASE_A_STOP",
        "strongest_only": "Input validation, not calibration or winner selection",
        "legacy_split": "Historical split preserved; all legacy cases are development evidence",
        "ambiguity_pairs": 16, "ch3_tuning": False, "real_evaluation": "NOT_RUN_PHASE_A_STOP",
    }
    with (output / "phase_b_protocol.json").open("x", encoding="utf-8") as handle:
        json.dump(protocol, handle, indent=2)
    manifest = []
    all_rows = []
    with (output / "fresh_strongest_input_validation.csv").open(
        "x", newline="", encoding="utf-8",
    ) as handle:
        writer = None
        for family in FAMILIES:
            for instance in range(24):
                case = generate_case(family, instance)
                filename = f"{case.case_id}.npz"
                save_case(generated / filename, case)
                manifest.append({
                    "case_id": case.case_id, "family": family, "instance": instance,
                    "split": case.split, "seed": case.seed,
                    "observation_group": case.observation_group, "filename": filename,
                    "voltage_sha256": array_hash(case.record.voltage_v),
                    "truth_sha256": array_hash(case.truth_hz),
                    "parameters_json": json.dumps(case.parameters, sort_keys=True),
                })
                for profile in PROFILES:
                    row = strongest_metrics(case, profile)
                    if writer is None:
                        writer = csv.DictWriter(handle, fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow(row)
                    handle.flush()
                    all_rows.append(row)
                if instance == 8:
                    stft, _, truth, _ = profile_input(case, PROFILES[0])
                    figure = Figure(figsize=(10, 4), layout="constrained")
                    axis = figure.subplots()
                    magnitude = np.abs(stft.spectrum)
                    db = 20 * np.log10(np.maximum(magnitude / magnitude.max(), 1e-12))
                    axis.pcolormesh(stft.time_s * 1e6, stft.frequency_hz / 1e9, db,
                                    shading="auto", vmin=-60, vmax=0, cmap="magma")
                    axis.plot(stft.time_s * 1e6, truth / 1e9, "c--", label="generator target")
                    axis.set(xlabel="Time (us)", ylabel="Frequency (GHz)", ylim=(0, 6),
                             title=f"{case.case_id}: waveform-derived STFT (input validation)")
                    axis.legend()
                    figure.savefig(figures / f"{case.case_id}.png", dpi=130)
                print(f"{case.case_id}: both original profiles validated", flush=True)
    ambiguous = []
    for index in range(16):
        pair = ambiguous_pair(index)
        for case in pair:
            save_case(generated / f"{case.case_id}.npz", case)
            ambiguous.append({
                "case_id": case.case_id, "observation_group": case.observation_group,
                "split": case.split, "voltage_sha256": array_hash(case.record.voltage_v),
                "truth_sha256": array_hash(case.truth_hz),
                "identity_status": "UNIDENTIFIABLE_FROM_OBSERVATION",
                "algorithm_confidence": "NOT_EVALUATED_SCORER_NOT_IMPLEMENTED",
            })
    write_csv(output / "fresh_waveform_manifest.csv", manifest)
    write_csv(output / "ambiguity_pairs.csv", ambiguous)
    summary = {
        "waveforms": len(manifest), "profile_rows": len(all_rows), "ambiguity_pairs": 16,
        "calibration_waveforms": sum(r["split"] == "CALIBRATION" for r in manifest),
        "held_out_waveforms": sum(r["split"] == "FRESH_HELD_OUT" for r in manifest),
        "unique_voltage_hashes": len({r["voltage_sha256"] for r in manifest}),
        "minimum_strongest_coverage": min(r["coverage"] for r in all_rows),
        "selector_status": "NOT_IMPLEMENTED_PHASE_A_STOP",
        "cross_scale_hypothesis": "NOT_TESTED",
        "ai": "NOT_STARTED",
    }
    with (output / "phase_b_summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
