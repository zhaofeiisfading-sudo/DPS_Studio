"""TASK-023E phase A: stop before scorer work if fixed proposals are inadequate."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from dps_studio.research import task023d_smooth_branch_rescue as old
from dps_studio.research.task023e_proposal_audit import (
    audit_frames,
    collect_beams,
    feasibility_gate,
)
from scripts import run_task023d_smooth_branch_rescue as runner

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / (
    "artifacts/task023d_smooth_branch_rescue/20260904T092908Z/experiment_metadata.json"
)
# Known failures plus separated-edge positive controls. No new held-out tuning.
AUDIT_IDS = (
    "O_LEADING_SMOOTH_WRONG_BRANCH",
    "P_TRAILING_SMOOTH_WRONG_BRANCH",
    "D23_BRANCH_DIVERGENCE",
    "D23_BRANCH_MERGE",
    "T_BRANCH_CROSSING",
    "K_LONG_WRONG_BRANCH_NO_RESCUE",
)


def write_csv(path, rows):
    if not rows:
        return
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts/task023e_cross_scale_evidence"):
        raise ValueError("Output must be a TASK-023E Research artifact")
    if not (output / "freeze_before.json").is_file():
        raise ValueError("Pre-implementation freeze is required")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    trim = old.CoreTrimConfig(**metadata["trim_config"])
    branch = old.BranchCompetitionConfig(**metadata["branch_config"])
    protocol = {
        "task": "TASK-023E", "stage": "A", "case_ids": AUDIT_IDS,
        "split": "LEGACY_DEVELOPMENT_AUDIT_NOT_FRESH_HELD_OUT",
        "majority_threshold": 0.5, "beam_width": 8, "top_k": 20,
        "wrong_tolerance_hz": 200e6, "trim": asdict(trim), "branch": asdict(branch),
        "oracle": "Optimistic pointwise union of unchanged terminal beams and 023C fallback",
        "stop_action": "Do not implement or calibrate scorer; no real-data algorithm evaluation",
    }
    with (output / "phase_a_protocol.json").open("x", encoding="utf-8") as handle:
        json.dump(protocol, handle, indent=2)
    cases = runner._deduplicated_cases((
        *runner._synthetic_cases(), *runner._additional_synthetic_cases(),
        *runner._edge_synthetic_cases(), *runner._expanded_cases(),
    ))
    cases_by_id = {case.case_id: case for case in cases}
    rows, summaries, state_rows = [], [], []
    for case_id in AUDIT_IDS:
        case = cases_by_id[case_id]
        candidates = runner._candidate_set(case)
        result = runner._optimize(
            candidates, old.SmoothBranchMethod.E3_CORE_TRIM_BRANCH, trim, branch, case.stft,
        )
        beams = collect_beams(result, candidates, runner.AMBIGUITY_CONFIG, branch, case.stft)
        current = audit_frames(case_id, candidates, case.truth_hz, result, beams)
        rows.extend(current)
        summary = {"case_id": case_id, **feasibility_gate(current)}
        summaries.append(summary)
        for beam in beams:
            for state_index, state in enumerate(beam.states):
                for frame, frequency, rank in zip(
                    beam.indices, state.frequencies_hz, state.ranks, strict=True,
                ):
                    state_rows.append({
                        "case_id": case_id, "anchor_frame": beam.anchor,
                        "state_index": state_index, "frame": frame,
                        "frequency_hz": frequency, "candidate_rank": rank,
                        "state_total_cost": state.total_cost,
                    })
        print(json.dumps(summary), flush=True)
    gate = feasibility_gate(rows)
    write_csv(output / "phase_a_frame_audit.csv", rows)
    write_csv(output / "phase_a_case_audit.csv", summaries)
    write_csv(output / "phase_a_terminal_beams.csv", state_rows)
    with (output / "phase_a_gate.json").open("x", encoding="utf-8") as handle:
        json.dump(gate, handle, indent=2)
    print(json.dumps(gate), flush=True)


if __name__ == "__main__":
    main()
