"""Bounded CPU TASK-001 experiment, grouped splits and compact retained outputs.

Use python -B, PYTHONDONTWRITEBYTECODE=1 and an external MPLCONFIGDIR. All writes
are exclusive: a completed split cannot accidentally be rerun or overwritten.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import platform
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from audit_denoising_task001 import ROOT, digest, safe_output
from dps_studio.core.analysis_profiles import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.research import denoising_task001 as method
from dps_studio.research import denoising_task001_benchmark as bench
from dps_studio.research import task028_consolidation as frozen

PROFILES = (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)
COUNTS = {"TRAIN": (4, 2), "CALIBRATION": (4, 2), "VALIDATION": (2, 1), "HELD_OUT": (8, 4)}
REPRESENTATIVES = {"normal", "jump", "pre_event", "fast_descent", "real_excursion", "fading",
                   "box_return"}


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def registrations(split: str) -> list[dict[str, Any]]:
    stress, core = COUNTS[split]
    return [dict(split=split, family=f, instance=i,
                 seed=bench.SPLIT_BASES[split] + 100 * j + i,
                 case_id=f"D001_{split}_{f}_{i:02d}")
            for j, f in enumerate((*bench.FAMILIES, *("core_" + f for f in bench.CORE_FAMILIES),
                                   *bench.EXTRA_FAMILIES))
            if not (split == "TRAIN" and f in bench.EXTRA_FAMILIES)
            for i in range(core if f.startswith("core_") else stress)]


PROTOCOL = """# DPS Denoising Research — TASK-001

Registered before examining any D001 experimental outcome. Research only.

## Audit and routes
Actual CLEAN branch codex/research_2/global-path-ridge-v2, initial HEAD
c184dd531e59c9e04b2e18983b3bf8ed98b2cc58, initial tracked/untracked status clean.
Production has an existing modified release document; OLD has historical deleted
test artifacts. Neither is repaired. Artifacts junction is read-only. Historical
TASK023F/G/H (024), 025–028 reports/source/configs and CLEAN sync were inspected.
Candidate availability alone does not establish target identity or a usable path.

R1 hypothesis: a maximum-selection-corrected spectral noise-null score rejects
white-noise maxima without E1's low-recall threshold or context dilation. Test
pure/colored noise, weak target, fading, coherent non-target and onset. Cost O(FT).
Risk: colored noise and estimated floor invalidate exact tail calibration; a
coherent non-target is intrinsically confusable. No identity certificate.

R2 hypothesis: independent left/right frequency predictions PLUS continuation of
observed anchor amplitude can select a few wrong-branch candidates above P3.
It shares an anchor prior with old B/C/D/F; it is NOT a new continuity optimizer.
Difference tested: disjoint-window extrapolation agreement and an amplitude
identity veto, without beam costs, rank preferences or boundary extrapolation.
Minimal falsifier: a real fall-and-return with a faint persistent alternative;
also rapid descent, crossing, fading, long wrong branches. Cost small vs P3.
Physical risk: real motion may return and amplitudes may genuinely change.

R3 hypothesis: a small supervised logistic classifier of proposed candidates can
reject unsafe R2 proposals using synthetic truth, beyond fixed amplitude gates.
CPU NumPy/SciPy, L2=.03, <=200 L-BFGS iterations; no framework installation.
TRAIN only fits coefficients; calibration chooses one of .8/.9/.95/.99 whole-
window probability cutoffs. Both profiles of a waveform always share a split.
Test calibration, independent validation and held-out, report classification and
trajectory results separately. Risks: synthetic shortcut learning, poor probability
calibration, inherited inability to generate missing candidates.

R4 considered but NOT TESTED: waveform shrinkage/robust pulse replacement.
No verified isolated-electronic-pulse mechanism; risks phase/chirp attenuation,
new harmonics and interference of two tones. Repeating FIR/whitening is low value.

## Frozen processing and data
M0 = frame-wise strongest; M1 = current TASK028 literal frozen P3, calling
task028_consolidation.consolidate(...).trajectories['M2']; its historical M1
simple-continuity output is NOT this task's M1. M2 = R2 after M1; M3 = R3-gated
M2 proposals after M1. M4_NO_AMP is development-only amplitude-veto ablation.
No voltage preprocessing, resampling, smoothing, interpolation or changing STFT.
Hann: Balanced 768/640/4096; High-time 512/384/4096; fs40 GHz, band .05–6 GHz,
Top20; both profiles are paired observations, never independent samples.

Fresh D001 stress: 14 families including all ten requested scenes, plus colored
noise, coherent non-target, true rapid fall/return, -22/-15/-8/0 dB weak target.
Fresh original E23 core distribution retained separately (80,000 samples, 8
families). D001 stress has 32,000 samples. All inputs time-voltage -> actual
frozen STFT -> original candidates -> P3 -> proposed quality/selection.
72 TRAIN, 72 CALIBRATION, 36 VALIDATION, 144 HELD_OUT independent waveforms,
648 profile streams. Seed ranges 41010000/41020000/41030000/41040000 plus family
offsets; exact seeds in seed_registration.json. No same-waveform frame leakage.
Input hash recorded; no synthetic waveform is passed to an external AI service.

## Metrics and decisions
Wrong = absent output or |f-f_truth|>200 MHz on target-present frame centers.
Trajectory evaluation includes transition-mixed windows, which are also flagged.
Signal detection evaluates fully-present/fully-absent STFT support windows only;
no-target coherent oscillators remain target-absent. Weak labels are generator
presence, not a guarantee of physical observability. Complete frequency
hypotheses remain separate from quality and validated-frequency NaNs.
R1 proxy 'supported' is NOT VALID target identity; false-supported, recall,
precision, weak rejection and no-target rejection are reported explicitly.
No 'all invalid' success; no reduction in candidate-output coverage allowed.

Both pooled and waveform macro metrics, candidate recall, wrong->correct and
correct->wrong counts, >1 MHz error improvement/worsening, exact normal/fast
preservation and intervention precision/harm are saved vs M0 and vs M1. Include
family/profile stratification. Bootstrap 4000 paired resamples of waveforms
(two profiles combined first), seed41099001. Primary inference M2-M1 and M3-M1.

Calibration cutoff selection: maximize corrected-harmed vs M1 subject to <=1
harmed, normal preservation>=.999, fast preservation>=.995, >=5 corrected;
ties prefer higher cutoff. If none passes, retain .95 as an explicitly failed
research operating point; do not tune on VALIDATION or HELD_OUT.
Validation activation: >=5 corrections, >=95% correction precision among all
truth interventions, <=1 harm, normal>=.999, fast>=.995, coverage1. A failed
method may still be measured once on held-out as a NEGATIVE/DIAGNOSTIC result,
never revived by tuning. Final code/config/model frozen before held-out.

Held-out repair success: >=20 extra corrected, corrected/truth interventions
>=.95, harmed/truth interventions<=.01, normal>=.999, fast>=.995, coverage1,
wrong rate improves and bootstrap upper bound on macro RMSE difference<0.
Core pooled RMSE may not worsen by >max(1 MHz,1%), core wrong <=+0.1pp.
Each affected family must disclose harm; benefits with material subgroup harm
receive MIXED, not SUPPORTED. Detector success: present recall>=.98, weak-focus
recall>=.95, pure-noise rejection>=.99, colored-noise rejection>=.95, overall
no-target rejection>=.95 including coherent non-target. Impossible identity
requirements must fail honestly; do not relabel negative samples.

Real-data activation requires repair and detection safety/effectiveness gates.
Otherwise SKIPPED. CLEAN raw is absent; OLD read-only sources are available;
result*.dat excluded. Reader/columns/units must be audited before any real run.
No manual labels, no real ground-truth accuracy claim. No ch3 tuning.

## Resources, checkpoints and retention
Ryzen7 H255 8C/16T, Radeon780M; no nvidia-smi/CUDA, torch/sklearn absent in
dps-studio Python3.12.13, NumPy2.5.1/SciPy1.18.0. CPU only, serial waveform
processing, one BLAS thread, waveforms/STFT in memory, no model downloads.
Save one summary per completed split, immutable configs/seeds/source hashes,
small feature tables, six preselected held-out examples and six useful figures.
Target retained output <50 MB (far below 1–2 GB allowance). No new repo caches:
python -B, pytest no cacheprovider, Ruff --no-cache, mypy /dev/null cache.
Test scratch and Matplotlib config use one owned external TemporaryDirectory.
No cleaning or overwriting historical files; no writes through artifacts.
No git commit/push/merge/rebase/cherry-pick/promotion. Stop after TASK-001.

Technical source verified: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.stft.html
Only scaling/axes semantics are sourced; algorithm/noise-null approximation
and all synthetic conclusions are this task's explicitly tested hypotheses.
"""


def prepare(out: Path) -> None:
    config = method.configuration()
    config["frozen_p3"] = json.loads((ROOT / "configs/research/task028_final_method.json").read_text())
    config["amplitude_ablation"] = asdict(replace(method.RepairConfig(),
        minimum_anchor_amplitude_ratio=.05, maximum_anchor_amplitude_ratio=20.))
    write_json(out / "method_configs.json", config)
    (out / "protocol.md").write_text(PROTOCOL, encoding="utf-8")
    seed_rows = [r for split in COUNTS for r in registrations(split)
                 if r["family"] not in bench.EXTRA_FAMILIES]
    assert len({r["seed"] for r in seed_rows}) == len(seed_rows)
    write_json(out / "seed_registration.json", seed_rows)
    write_json(out / "seed_registration_addendum.json", [r for split in COUNTS for r in registrations(split)
               if r["family"] in bench.EXTRA_FAMILIES])
    write_json(out / "detector_configs.json", {
        "GLOBAL_A01": {"alpha": .01, "background_half_width_hz": None},
        "LOCAL_A001": {"alpha": .001, "background_half_width_hz": .6e9}})
    (out / "protocol_amendment_01.md").write_text(
        "# Frozen study amendment 01 (reproduction)\n\n"
        "Final code collects ALL original candidates in loose proposal windows on TRAIN.\n"
        "The initial historical study first exposed a one-class sample selection error,\n"
        "then reanalyzed the same TRAIN waveforms. A fresh reproduction needs one TRAIN pass.\n"
        "box_return adds 4CAL/2VAL/8HELD (seed family index22); total338 independent waveforms.\n"
        "No criterion or geometry parameter changed. See original TASK001 report for history.\n",
        encoding="utf-8")
    (out / "protocol_amendment_02.md").write_text(
        "# Frozen study amendment 02 (reproduction)\n\n"
        "Add LOCAL_A001: reflected frequency median in +-0.6GHz, alpha=.001.\n"
        "GLOBAL_A01 stays unchanged. No grid search; same detection success criteria.\n"
        "Both report target-absent coherent components and weak targets without relabeling.\n",
        encoding="utf-8")
    files = [p for folder in ("src", "scripts", "tests", "configs")
             for p in (ROOT / folder).rglob("*.py" if folder != "configs" else "*")
             if p.is_file() and "__pycache__" not in str(p)]
    write_json(out / "initial_source_hashes.json",
               {p.relative_to(ROOT).as_posix(): digest(p) for p in files})
    write_json(out / "environment.json", dict(
        utc_start=datetime.now(timezone.utc).isoformat(), python=sys.executable,
        version=sys.version, platform=platform.platform(), numpy=np.__version__,
        modules={name: bool(importlib.util.find_spec(name))
                 for name in ("scipy", "torch", "sklearn", "pytest", "ruff", "mypy")}))
    (out / "README.md").write_text(
        "# TASK-001 outputs\n\nSee protocol.md, seed_registration.json and final_research_report.md.\n"
        "Run with Python -B and repository src on PYTHONPATH.\n"
        "Commands: prepare; run --split TRAIN; train; run --split CALIBRATION; "
        "calibrate; run --split VALIDATION; report_denoising_task001.py screen; "
        "freeze; run --split HELD_OUT; report_denoising_task001.py finalize; figures.\n"
        "Each command also takes --output pointing to this non-junction directory.\n"
        "Existing split outputs are never overwritten. M0=strongest, M1=frozen P3, "
        "M2=deterministic guard, M3=learned gate. No Production integration.\n",
        encoding="utf-8")


def source_freeze(out: Path) -> None:
    if not (out / "validation_activation.json").is_file():
        raise RuntimeError("Run independent validation and report screen before held-out freeze")
    files = list((ROOT / "src").rglob("*.py")) + [Path(__file__),
        ROOT / "configs/research/task028_final_method.json"]
    write_json(out / "held_out_source_freeze.json",
               {str(p): digest(p) for p in files})
    write_json(out / "held_out_activation.json", dict(
        utc=datetime.now(timezone.utc).isoformat(), model_sha256=digest(out / "model.json"),
        calibration_sha256=digest(out / "calibration_selection.json"),
        config_sha256=digest(out / "method_configs.json"),
        protocol_sha256=digest(out / "protocol.md"),
        seed_sha256=digest(out / "seed_registration.json"),
        seed_addendum_sha256=digest(out / "seed_registration_addendum.json"),
        amendment_sha256=digest(out / "protocol_amendment_01.md"),
        detector_amendment_sha256=digest(out / "protocol_amendment_02.md"),
        detector_config_sha256=digest(out / "detector_configs.json")))


def run_split(out: Path, split: str, *, development_reanalysis: bool = False) -> None:
    if development_reanalysis and split != "TRAIN":
        raise ValueError("Reanalysis is TRAIN only")
    prefix = "train_v2" if development_reanalysis else split.lower()
    destination = out / f"{prefix}_metrics.csv"
    if destination.exists() or (out / f"{prefix}_started.json").exists():
        raise FileExistsError(f"Split already started: {split}")
    if split == "HELD_OUT":
        manifest = json.loads((out / "held_out_source_freeze.json").read_text())
        if any(digest(Path(p)) != value for p, value in manifest.items()):
            raise RuntimeError("Source changed after held-out freeze")
        activation = json.loads((out / "held_out_activation.json").read_text())
        for key, name in (("model_sha256", "model.json"),
                          ("calibration_sha256", "calibration_selection.json"),
                          ("config_sha256", "method_configs.json"),
                          ("protocol_sha256", "protocol.md"),
                          ("seed_sha256", "seed_registration.json"),
                          ("seed_addendum_sha256", "seed_registration_addendum.json"),
                          ("amendment_sha256", "protocol_amendment_01.md"),
                          ("detector_amendment_sha256", "protocol_amendment_02.md"),
                          ("detector_config_sha256", "detector_configs.json")):
            if digest(out / name) != activation[key]:
                raise RuntimeError(f"Frozen input changed: {name}")
    model = (method.LogisticModel.from_dict(json.loads((out / "model.json").read_text()))
             if split != "TRAIN" else None)
    threshold = (.95 if split in ("TRAIN", "CALIBRATION") else
                 json.loads((out / "calibration_selection.json").read_text())["threshold"])
    write_json(out / f"{prefix}_started.json", dict(
        utc=datetime.now(timezone.utc).isoformat(), split=split, threshold=threshold))
    metric_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    detector_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    saved_config = json.loads((out / "method_configs.json").read_text())
    config = frozen.FinalMethodConfig.from_dict(saved_config["frozen_p3"])
    repair_config = method.RepairConfig(**saved_config["repair"])
    evidence_config = method.EvidenceConfig(**saved_config["evidence"])
    local_config = method.EvidenceConfig(**json.loads(
        (out / "detector_configs.json").read_text())["LOCAL_A001"])
    for index, registration in enumerate(registrations(split)):
        case = bench.generate(registration["family"], registration["instance"], split)
        voltage_hash = hashlib.sha256(case.record.voltage_v.tobytes()).hexdigest()
        time_hash = hashlib.sha256(case.record.time_s.tobytes()).hexdigest()
        for profile in PROFILES:
            before = time.perf_counter()
            stft, peaks = frozen.frontend(case.record, profile)
            frontend_seconds = time.perf_counter() - before
            before = time.perf_counter()
            result = frozen.consolidate(stft, peaks, config)
            p3_seconds = time.perf_counter() - before
            m0, m1 = result.trajectories["M0"].frequency_hz, result.trajectories["M2"].frequency_hz
            before = time.perf_counter()
            evidence = method.spectral_evidence(stft, peaks, evidence_config)
            proposals = method.propose_repairs(stft, peaks, m1, repair_config)
            m2, det_audit = method.apply_repairs(peaks, m1, proposals)
            method_seconds = time.perf_counter() - before
            paths = {"M0": m0, "M1": m1, "M2": m2}
            audits = {"M2": det_audit}
            model_seconds = 0.
            if model is not None:
                model_started = time.perf_counter()
                m3, ai_audit = method.apply_repairs(peaks, m1, proposals, model=model,
                                                   probability_threshold=threshold)
                model_seconds = time.perf_counter() - model_started
                paths["M3"] = m3
                audits["M3"] = ai_audit
            loose = method.propose_repairs(stft, peaks, m1, replace(repair_config,
                minimum_anchor_amplitude_ratio=.05, maximum_anchor_amplitude_ratio=20.))
            if split != "HELD_OUT":
                paths["M4_NO_AMP"], _ = method.apply_repairs(peaks, m1, loose)
            if split == "CALIBRATION":
                assert model is not None
                for cutoff in (.8, .9, .95, .99):
                    paths[f"M3_p{cutoff}"] = method.apply_repairs(
                        peaks, m1, proposals, model=model, probability_threshold=cutoff)[0]
            labels = bench.frame_labels(case, stft.time_s, stft.window_length_samples)
            recall_frames = sum(any(abs(c.transition_frequency_hz - labels["truth"][i])
                <= bench.TOLERANCE_HZ for c in frame)
                for i, frame in enumerate(peaks.candidates_by_frame)
                if np.isfinite(labels["truth"][i]))
            meta = dict(case_id=case.case_id, family=case.family, split=split, seed=case.seed,
                        profile=profile.profile_id.value)
            # Pre-calibration amendment 02: one fixed local-noise-floor contrast.
            local_started = time.perf_counter()
            local_evidence = method.spectral_evidence(stft, peaks, local_config)
            local_detector_seconds = time.perf_counter() - local_started
            for detector_name, detected in (("GLOBAL_A01", evidence), ("LOCAL_A001", local_evidence)):
                detection_counts = bench.evaluate(m1, m1, labels, detected.signal_supported)
                alpha = .01 if detector_name == "GLOBAL_A01" else .001
                truth_near_supported = np.asarray([any(
                    abs(candidate.transition_frequency_hz - labels["truth"][i]) <= bench.TOLERANCE_HZ
                    and log_evidence >= -np.log(alpha)
                    for candidate, log_evidence in zip(frame, detected.candidate_log_evidence[i], strict=True))
                    for i, frame in enumerate(peaks.candidates_by_frame)])
                truth_near_count = int((truth_near_supported & labels["homogeneous"]
                                       & labels["present"]).sum())
                weak_near_count = int((truth_near_supported & labels["homogeneous"]
                                      & labels["present"] & labels["weak"]).sum())
                detector_rows.append(dict(**meta, detector=detector_name, **detection_counts,
                    **bench.ratios(detection_counts), truth_near_supported=truth_near_count,
                    weak_truth_near_supported=weak_near_count))
            for name, path in paths.items():
                # Provenance proof: no generated frequency enters the output.
                if not all(any(c.transition_frequency_hz == path[i] for c in frame)
                           for i, frame in enumerate(peaks.candidates_by_frame)):
                    raise AssertionError("Off-candidate output")
                for reference_name, reference in (("M0", m0), ("M1", m1)):
                    counts = bench.evaluate(path, reference, labels, evidence.signal_supported)
                    metric_rows.append(dict(**meta, method=name, reference=reference_name,
                        **counts, **bench.ratios(counts), candidate_recalled=recall_frames,
                        candidate_recall=recall_frames / max(1, counts["truth_frames"]),
                        frontend_seconds=frontend_seconds, p3_seconds=p3_seconds,
                        method_seconds=method_seconds, model_seconds=model_seconds,
                        local_detector_seconds=local_detector_seconds,
                        path_sha256=hashlib.sha256(path.tobytes()).hexdigest()))
            for name, audit in audits.items():
                for row in audit:
                    i = row["frame"]
                    truth = labels["truth"][i]
                    error0, error1 = abs(row["previous_hz"] - truth), abs(row["proposed_hz"] - truth)
                    audit_rows.append(dict(**meta, method=name, **row,
                        truth_hz=float(truth) if np.isfinite(truth) else None,
                        corrected=bool(row["accepted"] and error0 > bench.TOLERANCE_HZ
                                       and error1 <= bench.TOLERANCE_HZ),
                        harmed=bool(row["accepted"] and error0 <= bench.TOLERANCE_HZ
                                    and error1 > bench.TOLERANCE_HZ)))
            # Loose proposals produce both positive and negative training labels;
            # feature scales are fixed and identical in strict inference proposals.
            for kind, collection in (("loose", loose), ("strict", proposals)):
                for proposal in collection:
                    for i, j, features in zip(proposal.frame_indices, proposal.candidate_indices,
                                               proposal.features, strict=True):
                        candidate = peaks.candidates_by_frame[i][j]
                        truth = labels["truth"][i]
                        feature_rows.append(dict(**meta, kind=kind, frame=int(i),
                            label=int(np.isfinite(truth) and abs(candidate.transition_frequency_hz
                                      - truth) <= bench.TOLERANCE_HZ),
                            **dict(zip(method.FEATURE_NAMES, features, strict=True))))
            # Amendment 01: classification must see original wrong competitors,
            # rather than training on the already accepted nearest candidates only.
            for proposal in loose:
                for i, prediction in zip(proposal.frame_indices, proposal.prediction_hz, strict=True):
                    for j, candidate in enumerate(peaks.candidates_by_frame[i]):
                        features = method.candidate_features(peaks, int(i), j, float(prediction),
                            proposal.reference_amplitude_v, proposal.side_disagreement_hz,
                            proposal.anchor_residual_hz)
                        truth = labels["truth"][i]
                        feature_rows.append(dict(**meta, kind="all_candidates", frame=int(i),
                            label=int(np.isfinite(truth) and abs(candidate.transition_frequency_hz
                                      - truth) <= bench.TOLERANCE_HZ),
                            **dict(zip(method.FEATURE_NAMES, features, strict=True))))
            if (split == "HELD_OUT" and registration["instance"] == 0
                    and case.family in REPRESENTATIVES and profile == BALANCED_PROFILE):
                examples = out / "examples"
                examples.mkdir(exist_ok=True)
                band = (stft.frequency_hz <= 6e9)
                arrays: dict[str, Any] = dict(time_s=stft.time_s, frequency_hz=stft.frequency_hz[band],
                    magnitude=np.abs(stft.spectrum[band]).astype(np.float32),
                    truth_hz=labels["truth"], supported=evidence.signal_supported,
                    evidence=evidence.maximum_log_evidence, states=np.asarray(evidence.states),
                    local_supported=local_evidence.signal_supported,
                    raw_time_s=case.record.time_s, raw_voltage_v=case.record.voltage_v,
                    **paths)
                with (examples / f"{case.family}.npz").open("xb") as handle:
                    np.savez_compressed(handle, **arrays)
            provenance.append(dict(**meta, voltage_sha256=voltage_hash, time_sha256=time_hash,
                frame_axis_sha256=hashlib.sha256(stft.time_s.tobytes()).hexdigest(),
                parameters=json.dumps(case.parameters, sort_keys=True),
                proposals=len(proposals), loose_proposals=len(loose)))
        if hashlib.sha256(case.record.voltage_v.tobytes()).hexdigest() != voltage_hash:
            raise AssertionError("Waveform mutated")
        print(f"{split} {index + 1}/{len(registrations(split))} {case.family} "
              f"elapsed={time.perf_counter() - started:.1f}s", flush=True)
    write_csv(destination, metric_rows)
    write_csv(out / f"{prefix}_features.csv", feature_rows)
    write_csv(out / f"{prefix}_interventions.csv", audit_rows)
    write_csv(out / f"{prefix}_provenance.csv", provenance)
    write_csv(out / f"{prefix}_detectors.csv", detector_rows)
    write_json(out / f"{prefix}_completed.json", dict(
        split=split, waveforms=len(registrations(split)), streams=len(provenance),
        seconds=time.perf_counter() - started, feature_rows=len(feature_rows),
        utc=datetime.now(timezone.utc).isoformat()))


def train(out: Path) -> None:
    import pandas as pd  # type: ignore[import-untyped]
    features_path = out / "train_v2_features.csv"
    if not features_path.exists():
        features_path = out / "train_features.csv"
    table = pd.read_csv(features_path)
    table = table[table.kind == "all_candidates"]
    features = table[list(method.FEATURE_NAMES)].to_numpy(float)
    labels = table.label.to_numpy(bool)
    sizes = table.groupby("case_id").case_id.transform("size").to_numpy(float)
    penalty = json.loads((out / "method_configs.json").read_text())["model"]["l2"]
    model, history = method.fit_logistic(features, labels, 1 / sizes, split="TRAIN", penalty=penalty)
    write_json(out / "model.json", model.to_dict())
    write_json(out / "training_summary.json", dict(
        samples=len(labels), positive=int(labels.sum()), negative=int((~labels).sum()),
        contributing_waveforms=int(table.case_id.nunique()),
        excluded_waveforms_without_proposals=len(registrations("TRAIN")) - int(table.case_id.nunique()),
        objective_history=history, optimizer="L-BFGS-B", iterations=len(history),
        train_loss=float(np.mean(-(labels * np.log(np.maximum(model.predict(features), 1e-12)))
                     - (~labels) * np.log(np.maximum(1 - model.predict(features), 1e-12))))))


def aggregate(table: Any) -> dict[str, Any]:
    # Summable evaluator counts are explicitly selected, never sum ratio columns.
    keys = ("frames", "finite_frames", "truth_frames", "sse_hz2", "squared_error_frames",
            "wrong_frames", "interventions", "truth_interventions", "corrected_frames",
            "harmed_frames", "improved_error_frames", "worsened_error_frames", "normal_frames",
            "normal_preserved", "fast_frames", "fast_preserved", "fast_all", "fast_wrong",
            "focus_wrong", "focus_frames", "target_frames", "target_detected", "absent_frames",
            "absent_rejected", "false_supported", "weak_frames", "weak_rejected",
            "detection_tp", "detection_fp", "mixed_boundary_frames", "candidate_recalled")
    counts = {key: float(table[key].sum()) for key in keys}
    result = dict(**counts, **bench.ratios(counts), waveforms=int(table.case_id.nunique()))
    result["candidate_recall"] = (counts["candidate_recalled"] / counts["truth_frames"]
                                  if counts["truth_frames"] else None)
    return result


def calibrate(out: Path) -> None:
    import pandas as pd
    table = pd.read_csv(out / "calibration_metrics.csv")
    rows = []
    for cutoff in (.8, .9, .95, .99):
        result = aggregate(table[(table.method == f"M3_p{cutoff}") & (table.reference == "M1")])
        eligible = (result["corrected_frames"] >= 5 and result["harmed_frames"] <= 1
                    and (result["normal_preservation"] is None or result["normal_preservation"] >= .999)
                    and (result["fast_preservation"] is None or result["fast_preservation"] >= .995))
        rows.append(dict(threshold=cutoff, eligible=eligible, **result))
    eligible_rows = [r for r in rows if r["eligible"]]
    chosen = max(eligible_rows, key=lambda r: (r["corrected_frames"] - r["harmed_frames"],
                                               r["threshold"])) if eligible_rows else None
    write_json(out / "calibration_selection.json", dict(
        threshold=chosen["threshold"] if chosen else .95,
        verdict="ELIGIBLE" if chosen else "FAILED_RESEARCH_OPERATING_POINT", candidates=rows))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run", "train", "calibrate", "freeze"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--split", choices=tuple(COUNTS))
    parser.add_argument("--development-reanalysis", action="store_true")
    args = parser.parse_args()
    out = safe_output(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "prepare":
        prepare(out)
    elif args.command == "run":
        if not args.split:
            parser.error("run requires --split")
        run_split(out, args.split, development_reanalysis=args.development_reanalysis)
    elif args.command == "train":
        train(out)
    elif args.command == "calibrate":
        calibrate(out)
    elif args.command == "freeze":
        source_freeze(out)


if __name__ == "__main__":
    main()
