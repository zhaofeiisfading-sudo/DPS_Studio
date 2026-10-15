"""Exclusive-output TASK-002 runner. Use the registered dps-studio environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from audit_denoising_task001 import ROOT, digest, git, safe_output, snapshot
from run_denoising_task001 import write_csv, write_json
from dps_studio.core.analysis_profiles import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.research import denoising_task001 as method
from dps_studio.research import denoising_task002 as bench
from dps_studio.research import task028_consolidation as frozen

OLD = Path("D:/Research/DPS_Denoising_Runs/TASK-001/20261014T115200Z")
PROFILES = (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)
SOURCE_FILES = ("src/dps_studio/research/denoising_task002.py",
                "scripts/run_denoising_task002.py", "tests/unit/test_denoising_task002.py")
GATES = dict(maximum_extra_harmed_frames=0, normal_preservation_min=.999,
             fast_preservation_min=.995, minimum_corrected_frames=20,
             minimum_intervention_precision=.95, maximum_total_harm_vs_strongest_fraction=.001,
             coverage_min=1., maximum_family_wrong_increase=0.,
             paired_macro_rmse_upper_bound_max_hz=0.)

PROTOCOL = """# DPS Denoising Research — TASK-002

Registered before viewing any D002 experimental result. Date 2026-10-15 Asia/Shanghai.
Only fresh time-voltage -> current real STFT -> original Top20 candidates.
M0 strongest; M1 frozen TASK028 P3 (consolidate's historical M2); M2 TASK001
bilateral amplitude-consistent candidate repair. Load actual TASK001 method_configs,
check current defaults and frozen P3 config for semantic equality, and hash sources.
No change to formal STFT, P3, M2, TopK, voltage, or frequency time axis.
Hann 768/512; hop128 samples; nfft4096; fs40GHz; 0.05–6GHz. 800ns records.

## Phase A: counterexamples and splits
20 families, 3 DEVELOPMENT + 3 CALIBRATION + 8 HELD_OUT each =280 independent
waveforms /560 paired profile streams. 252 target-present,28 target-absent.
Primary confirmatory result =160 HELD_OUT waveforms (144 with frequency GT),
not the pooled280; DEVELOPMENT/CALIBRATION remain separate replications.
Seeds42010000/42020000/42040000 +100*family_index+instance; registration lists all.
No waveform/profile split; no old D001 seed reuse. Hash voltage and all paths.
Use DEVELOPMENT only to decide if any explainable, identifiable M3 mechanism is
worth pursuing. Freeze this decision before CALIBRATION and HELD_OUT. If M3 is
not justified, skip C explicitly; never retrofit a rule after seeing held-out.
If M3 is pursued, preregister a separate mechanism/config before calibration,
then freeze once before held-out. No large search or threshold relaxation.

Normal platform, permanent fast step, and clean fast-return controls; faint and
near-equal coherent alternatives during real returns; left/right amplitude
exchange between different components; quadratic and Gaussian curvature, with
and without contamination; continuous decay, amplitude valleys, asymmetric
envelopes and random Fourier log-amplitude proxy; transient/long/edge wrong
branches; approaching and crossing components; coherent non-target and colored
noise. No claim these envelopes reproduce instrument speckle statistics.
base2.6–3.2GHz; slopes+-0.25e15Hz/s; return depths0.8–1.45GHz; durations
40/72/112/160ns; ramps2/5/10ns. Curvature scales32/55/85/125ns; competing
return ratios.58/.72/.86/.96; explicit relative phase0/pi/2/pi on coherent
returns. Long branches230/300/370/440ns; gaussian noise SD.1–.28V.
Full generation equations and actual draws saved as config and provenance.
Phase integration uses phi[n+1]-phi[n]=2*pi*f[n]/fs; output GT is generated f.
Within one sample, discrete/center convention discrepancy is bounded by the
local frequency slope /fs, disclosed separately from STFT mixing.

## Phase B: estimands and fixed diagnostics
wrong=missing hypothesis or error>200MHz, same as D001. Include ALL target-present
frame centers, including mixed fast-change windows and weak target. No-target
does not have frequency truth. Frame support touching a >5e15Hz/s true ramp is
fast; normal excludes windows touching focus/fast (more conservative than D001).
Report pooled RMSE and waveform-level RMSE, wrong fractions, normal/fast absolute
truth accuracy AND preservation of already correct reference frames, vs both
P3 and strongest. Corrected=wrong->correct, harmed=correct->wrong. Intervention
precision=corrected/all target-present changed frames, includes wrong->wrong.
Candidate Recall at200MHz; complete coverage is hypotheses, never validated speed.
4000 paired bootstrap resamples with replacement of whole independent waveform
IDs, seed42099002, combine two profiles SSE/count before RMSE. Primary macro
RMSE/wrong differences M2-M1; profile/subgroup analyses descriptive.
No significance claim from treating correlated frames or profiles as independent.

Frozen amplitude-ablation from D001 config is a DIAGNOSTIC ONLY, not M3 and not
eligible for real evaluation. Record proposals, support fraction, side residuals,
disagreement, all anchor frequencies/amplitudes and synthetic identity labels.
Compare strict versus no-amplitude proposal counts (overlap consumption can
change pairing, so they are separate admissible sets, not literal veto counts).
Fixed observation-only P3 risk flags: disagreement with strongest>200MHz,
selected background<12dB, alternative>200MHz with background>=12dB and amplitude
>=.55*selected. No thresholds tuned. Evaluate recall/precision of flags for
inherited harm and ALL P3 errors; disagreement is partly tautological for harm,
so disclose false positives and never call it a truth/identity detector.
Save per-frame every M2 intervention, every P3-vs-strongest harm, and all
remaining P3 error runs. All newly harmed frames have an explicit case/seed/
profile/frame, truth, original candidate, anchor and proposal reference.

## Phase D/E: separate readiness gates, frozen now
Information detector remains NOT SUPPORTED based on D001 complete gates; no
retraining and no claim of target identity. Trajectory-only read-only behavior
evaluation is conceptually permitted independently, ONLY if trajectory safety
checks pass. In held-out require zero extra harms vs P3, normal>=.999,
fast>=.995, complete coverage, >=20 new corrections, precision>=.95, no family
wrong fraction increase, paired macro RMSE95%CI upper<0, and full M2 harm vs
strongest / strongest-correct frames<=.001. Protecting an unsafe P3 alone is
insufficient. Also demand no new harms in DEVELOPMENT or CALIBRATION.
All checks conjunctive. Failing any means no NEW formal real-data run; existing
real source metadata may be read without running new STFT/trajectories.
Gate is for limited research observation, never Production approval or accuracy.
No real ch3 tuning. No automatic modification of experimental results.

## Phase C and constraints
Unidentifiable label identity is not solved by extra continuity weights. A
mechanism showing ambiguity without an observation-only discriminator warrants
skipping M3. Preserve both benefits and harms and allow MIXED/NOT SUPPORTED.
No AI training unless independently learnable information is demonstrated.
Audit D00167 inherited harms by hash-verified replay of ONLY affected old streams.
These replays are historical diagnostics, never new independent observations.
No commit/push/merge/rebase/cherry-pick/promotion. Production/OLD/raw immutable;
no results through artifacts Junction; do not restore cleaned large artifacts.
All writes exclusive into new TASK002 paths; retain compact CSV/JSON, small
diagnostic examples and PNG/PDF. Test scratch/cache paths outside repositories.
Run pytest, Ruff, strict mypy, diff check; disclose known unrelated failures.
Stop after TASK002 and write the requested Obsidian log.
"""


def array_hash(value: np.ndarray[Any, Any]) -> str:
    return hashlib.sha256(value.tobytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): digest(p)
            for folder in ("src", "configs") for p in (ROOT/folder).rglob("*")
            if p.is_file() and "__pycache__" not in str(p)} | {
                name: digest(ROOT/name) for name in SOURCE_FILES}


def prepare(out: Path) -> None:
    cfg = json.loads((OLD/"method_configs.json").read_text(encoding="utf-8"))
    actual = method.configuration()
    if actual["repair"] != cfg["repair"]:
        raise AssertionError("TASK001 repair defaults have drifted")
    p3 = frozen.FinalMethodConfig.from_dict(cfg["frozen_p3"])
    saved_p3 = json.loads((ROOT/"configs/research/task028_final_method.json").read_text())
    if p3.to_dict() != frozen.FinalMethodConfig().to_dict() or saved_p3 != p3.to_dict():
        raise AssertionError("Frozen P3 source/config differ")
    write_json(out/"method_configs.json", cfg)
    write_json(out/"success_gate_registration.json", GATES)
    write_json(out/"seed_registration.json", bench.registration())
    historical_seeds: set[int] = set()
    for name in ("seed_registration.json", "seed_registration_addendum.json"):
        historical_seeds.update(r["seed"] for r in json.loads((OLD/name).read_text()))
    fresh_seeds = {r["seed"] for r in bench.registration()}
    assert len(fresh_seeds) == len(bench.registration())
    assert not fresh_seeds & historical_seeds
    write_json(out/"historical_seed_audit.json", dict(
        compared_to="TASK001 two actual registrations", overlap=[],
        unique_fresh=len(fresh_seeds), other_historical_registrations="NOT_CLAIMED"))
    with (out/"protocol.md").open("x", encoding="utf-8") as handle:
        handle.write(PROTOCOL)
    write_json(out/"source_freeze.json", source_hashes())
    write_json(out/"environment.json", dict(utc_start=datetime.now(timezone.utc).isoformat(),
        python=sys.executable, python_version=sys.version, platform=platform.platform(),
        numpy=np.__version__, head=git(ROOT, "rev-parse", "HEAD"),
        branch=git(ROOT, "branch", "--show-current"),
        profiles=[asdict(p) for p in PROFILES]))
    (out/"examples").mkdir(exist_ok=False)
    print(f"Prepared {len(fresh_seeds)} independent waveforms at {out}", flush=True)


def verify_freeze(out: Path) -> None:
    manifest = out/"pre_evaluation_source_freeze.json"
    if not manifest.is_file():
        manifest = out/"source_freeze.json"
    old = json.loads(manifest.read_text())
    now = source_hashes()
    if old != now:
        raise AssertionError(f"Inference/source drift: {[k for k in old if old[k] != now.get(k)]}")


def _rows_for_interventions(meta: dict[str, Any], path: np.ndarray[Any, Any],
                            reference: np.ndarray[Any, Any], labels: dict[str, Any],
                            peaks: Any, flags: tuple[tuple[str, ...], ...],
                            kind: str) -> list[dict[str, Any]]:
    truth = labels["truth"]
    valid = np.isfinite(truth)
    old_bad = abs(reference-truth) > bench.TOLERANCE_HZ
    bad = abs(path-truth) > bench.TOLERANCE_HZ
    selected = (path != reference) if kind == "M2_INTERVENTION" else (valid & ~old_bad & bad)
    rows = []
    for i in np.flatnonzero(selected):
        c = min(peaks.candidates_by_frame[i], key=lambda c: abs(c.transition_frequency_hz-path[i]))
        rows.append(dict(**meta, kind=kind, frame=int(i), time_s=float(peaks.time_s[i]),
            truth_hz=float(truth[i]) if valid[i] else None,
            previous_hz=float(reference[i]), selected_hz=float(path[i]),
            selected_rank=c.candidate_rank, background_db=float(c.peak_to_background_db),
            amplitude_v=float(c.peak_amplitude), corrected=bool(valid[i] and old_bad[i] and not bad[i]),
            harmed=bool(valid[i] and not old_bad[i] and bad[i]), normal=bool(labels["normal"][i]),
            fast=bool(labels["fast"][i]), flags="|".join(flags[i]),
            target_amplitude_v=float(labels["target_amplitude_v"][i]),
            competitor_hz=float(labels["competitor_hz"][i]),
            competitor_amplitude_v=float(labels["competitor_amplitude_v"][i])))
    return rows


def run_split(out: Path, split: str) -> None:
    verify_freeze(out)
    if split != "DEVELOPMENT" and not (out/"phase_c_decision.json").is_file():
        raise ValueError("Freeze the development-only Phase C decision first")
    if split == "HELD_OUT" and not (out/"calibration_completed.json").is_file():
        raise ValueError("Calibration replication must finish before held-out")
    key = split.lower()
    write_json(out/f"{key}_started.json", dict(utc=datetime.now(timezone.utc).isoformat(),
                                             source_freeze_sha256=digest(out/"source_freeze.json")))
    cfg = json.loads((out/"method_configs.json").read_text())
    repair_cfg = method.RepairConfig(**cfg["repair"])
    assert repair_cfg.anchors_per_side == 4
    p3_cfg = frozen.FinalMethodConfig.from_dict(cfg["frozen_p3"])
    loose_cfg = method.RepairConfig(**cfg["amplitude_ablation"])
    metrics_rows: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    proposal_rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    error_runs: list[dict[str, Any]] = []
    flag_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    registered = [r for r in bench.registration() if r["split"] == split]
    for n, registered_case in enumerate(registered):
        case = bench.generate(registered_case["family"], registered_case["instance"], split)
        voltage_hash = array_hash(case.record.voltage_v)
        for profile in PROFILES:
            meta = dict(case_id=case.case_id, family=case.family, split=split, seed=case.seed,
                        instance=case.instance, profile=profile.profile_id)
            tick = time.perf_counter()
            stft, peaks = frozen.frontend(case.record, profile)
            frontend_s = time.perf_counter()-tick
            tick = time.perf_counter()
            result = frozen.consolidate(stft, peaks, p3_cfg)
            p3_s = time.perf_counter()-tick
            m0 = result.trajectories["M0"].frequency_hz
            m1 = result.trajectories["M2"].frequency_hz
            tick = time.perf_counter()
            proposals = method.propose_repairs(stft, peaks, m1, repair_cfg)
            m2, _ = method.apply_repairs(peaks, m1, proposals)
            repair_s = time.perf_counter()-tick
            labels = bench.frame_labels(case, stft.time_s, stft.window_length_samples)
            loose = method.propose_repairs(stft, peaks, m1, loose_cfg)
            loose_path, _ = method.apply_repairs(peaks, m1, loose)
            flags = bench.observational_flags(peaks, m0, m1)
            truth = labels["truth"]
            valid = np.isfinite(truth)
            recall = np.array([any(abs(c.transition_frequency_hz-truth[i]) <= bench.TOLERANCE_HZ
                                   for c in frame) for i, frame in enumerate(peaks.candidates_by_frame)])
            strongest_correct = valid & (abs(m0-truth) <= bench.TOLERANCE_HZ)
            inherited_harm = strongest_correct & (abs(m1-truth) > bench.TOLERANCE_HZ)
            p3_error = valid & (abs(m1-truth) > bench.TOLERANCE_HZ)
            for flag_name in ("ANY", "P3_DISAGREES_STRONGEST", "P3_LOW_BACKGROUND_SUPPORT",
                              "COMPETING_OBSERVED_BAND"):
                mask = np.array([bool(f) if flag_name == "ANY" else flag_name in f for f in flags])
                flag_rows.append(dict(**meta, flag=flag_name, flagged=int((valid & mask).sum()),
                    truth_frames=int(valid.sum()), inherited_harms=int(inherited_harm.sum()),
                    flagged_inherited_harms=int((mask & inherited_harm).sum()),
                    p3_errors=int(p3_error.sum()), flagged_p3_errors=int((mask & p3_error).sum())))
            paths = {"M0": m0, "M1": m1, "M2": m2, "DIAG_NO_AMP": loose_path}
            for name, path in paths.items():
                assert all(any(c.transition_frequency_hz == path[i] for c in frame)
                           for i, frame in enumerate(peaks.candidates_by_frame))
                for reference_name, reference in (("M0", m0), ("M1", m1)):
                    counts = bench.metrics(path, reference, labels)
                    metrics_rows.append(dict(**meta, method=name, reference=reference_name, **counts,
                        candidate_recalled=int((valid & recall).sum()),
                        strongest_correct=int(strongest_correct.sum()), **bench.ratios(counts),
                        path_sha256=array_hash(path)))
            new_rows = _rows_for_interventions(meta, m2, m1, labels, peaks, flags,
                                               "M2_INTERVENTION")
            for row in new_rows:
                for p_index, proposal in enumerate(proposals):
                    matches = np.flatnonzero(proposal.frame_indices == row["frame"])
                    if len(matches):
                        k = int(matches[0])
                        row.update(proposal_id=p_index, first=proposal.first, stop=proposal.stop,
                            prediction_hz=float(proposal.prediction_hz[k]),
                            reference_amplitude_v=proposal.reference_amplitude_v,
                            amplitude_ratio=row["amplitude_v"]/proposal.reference_amplitude_v,
                            side_disagreement_hz=proposal.side_disagreement_hz,
                            anchor_residual_hz=proposal.anchor_residual_hz)
                        break
                assert "proposal_id" in row
            interventions.extend(new_rows)
            interventions.extend(_rows_for_interventions(meta, m1, m0, labels, peaks, flags,
                                                        "P3_INHERITED_HARM"))
            for method_name, path in (("M1", m1), ("M2", m2)):
                bad = valid & (abs(path-truth) > bench.TOLERANCE_HZ)
                starts = np.flatnonzero(bad & ~np.r_[False, bad[:-1]])
                stops = np.flatnonzero(bad & ~np.r_[bad[1:], False])+1
                for first, stop in zip(starts, stops, strict=True):
                    error_runs.append(dict(**meta, method=method_name, first=int(first), stop=int(stop),
                        frames=int(stop-first), start_s=float(stft.time_s[first]),
                        stop_s=float(stft.time_s[stop-1]),
                        fast_frames=int(labels["fast"][first:stop].sum()),
                        candidate_missed=int((~recall[first:stop]).sum()),
                        maximum_error_hz=float(np.max(abs(path[first:stop]-truth[first:stop])))))
            for kind, collection in (("M2", proposals), ("DIAG_NO_AMP", loose)):
                for p_index, proposal in enumerate(collection):
                    audit = bench.proposal_truth_audit(proposal, peaks, labels,
                        int(np.ceil(stft.window_length_samples/stft.hop_samples)), m1)
                    indices = proposal.frame_indices
                    output = paths[kind]
                    old_wrong = abs(m1[indices]-truth[indices]) > bench.TOLERANCE_HZ
                    new_wrong = abs(output[indices]-truth[indices]) > bench.TOLERANCE_HZ
                    pmeta = dict(**meta, kind=kind, proposal_id=p_index,
                                 first=proposal.first, stop=proposal.stop)
                    proposal_rows.append(dict(**pmeta, frames=len(indices),
                        support_fraction=len(indices)/(proposal.stop-proposal.first),
                        anchor_residual_hz=proposal.anchor_residual_hz,
                        side_disagreement_hz=proposal.side_disagreement_hz,
                        reference_amplitude_v=proposal.reference_amplitude_v,
                        corrected=int((valid[indices] & old_wrong & ~new_wrong).sum()),
                        harmed=int((valid[indices] & ~old_wrong & new_wrong).sum()),
                        cofrequency_anchors=audit["cofrequency_anchors"],
                        target_near_anchors=audit["target_near_anchors"]))
                    anchors.extend(dict(**pmeta, **r) for r in audit["anchors"])
            if case.instance == 0 or (np.any(inherited_harm) or np.any(
                    valid & (abs(m1-truth) <= bench.TOLERANCE_HZ)
                    & (abs(m2-truth) > bench.TOLERANCE_HZ))):
                # Keep small spectra only for first example or any actual harmful stream.
                band = (stft.frequency_hz >= .05e9) & (stft.frequency_hz <= 6e9)
                with (out/"examples"/f"{case.case_id}_{profile.profile_id}.npz").open("xb") as handle:
                    np.savez_compressed(handle, time_s=stft.time_s,
                        frequency_hz=stft.frequency_hz[band],
                        magnitude=np.abs(stft.spectrum[band]).astype(np.float32),
                        truth_hz=truth, M0=m0, M1=m1, M2=m2, changed=m2 != m1,
                        fast=labels["fast"], normal=labels["normal"],
                        validated_frequency_hz=np.full(len(m2), np.nan),
                        corrected_velocity_m_per_s=np.full(len(m2), np.nan))
            provenance.append(dict(**meta, voltage_sha256=voltage_hash,
                parameters=json.dumps(case.parameters, sort_keys=True), frontend_s=frontend_s,
                p3_entry_s=p3_s, repair_s=repair_s, frames=len(m0),
                jumps=int((abs(np.diff(m1)) >= repair_cfg.jump_hz).sum()),
                strict_proposals=len(proposals), amplitude_ablation_proposals=len(loose)))
            assert array_hash(case.record.voltage_v) == voltage_hash
        if (n+1) % 5 == 0:
            print(f"{split}: {n+1}/{len(registered)} waveforms; "
                  f"elapsed {time.perf_counter()-started:.1f}s", flush=True)
    for name, rows in (("metrics", metrics_rows), ("interventions", interventions),
                       ("proposals", proposal_rows), ("anchors", anchors),
                       ("provenance", provenance), ("error_runs", error_runs), ("flags", flag_rows)):
        write_csv(out/f"{key}_{name}.csv", rows)
    verify_freeze(out)
    write_json(out/f"{key}_completed.json", dict(waveforms=len(registered), streams=len(provenance),
        seconds=time.perf_counter()-started, utc=datetime.now(timezone.utc).isoformat()))


def boundary(out: Path) -> None:
    before = json.loads((out/"boundary_before.json").read_text(encoding="utf-8"))
    after = snapshot()
    checks = {}
    for root, old in before.items():
        if root == "untracked_task001":
            continue
        current = after[root]
        checks[root] = dict(changed_existing_files=[name for name, value in old["files"].items()
                            if current["files"].get(name) != value],
            raw_identical=old["raw"] == current["raw"], head_identical=old["head"] == current["head"],
            tracked_diff_identical=old["diff_sha256"] == current["diff_sha256"],
            status_identical=old["status_sha256"] == current["status_sha256"])
    untracked = {name: digest(ROOT/name) for name in before["untracked_task001"]}
    write_json(out/"boundary_after.json", dict(verification=checks, after=after,
        existing_untracked_task001_identical=untracked == before["untracked_task001"]))
    print(json.dumps(checks, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run", "boundary"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=tuple(bench.SPLITS))
    args = parser.parse_args()
    out = safe_output(args.output)
    if args.command == "prepare":
        prepare(out)
    elif args.command == "boundary":
        boundary(out)
    else:
        if args.split is None:
            raise ValueError("run requires a split")
        run_split(out, args.split)


if __name__ == "__main__":
    main()
