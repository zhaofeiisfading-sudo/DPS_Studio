"""Finalize TASK-023E stopped research with integrity checks and a lightweight log."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from matplotlib.figure import Figure

from scripts.run_task023e_proposal_audit import ROOT, write_csv


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_snapshot(root):
    return {command: subprocess.check_output(
        ["git", *command.split()], cwd=root, encoding="utf-8",
    ).strip() for command in (
        "status --short --branch", "rev-parse HEAD", "diff --stat", "diff --cached --stat",
    )}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts/task023e_cross_scale_evidence"):
        raise ValueError("Output must be the Research TASK-023E artifact")
    before = json.loads((output / "freeze_before.json").read_text(encoding="utf-8"))
    gate = json.loads((output / "phase_a_gate.json").read_text(encoding="utf-8"))
    benchmark = json.loads((output / "phase_b_summary.json").read_text(encoding="utf-8"))
    if not gate["stop_scorer"]:
        raise ValueError("This finalizer is for the declared phase-A stop branch")
    test_text = (output / "pytest_full_env.txt").read_text(encoding="utf-8")
    test_summary = next((line for line in reversed(test_text.splitlines())
                         if "passed" in line and " in " in line), "")
    if not test_summary:
        raise RuntimeError("Full pytest has not completed")
    ruff_text = (output / "ruff_release.txt").read_text(encoding="utf-8").strip()
    prod = Path("D:/Code/Python_Projects/DPS_Studio")
    integrity_rows = []
    for name, base, previous in (
        ("Research", ROOT, before["research_hashes"]),
        ("Production", prod, before["production_hashes"]),
    ):
        for relative, old_hash in previous.items():
            path = base / relative
            current = sha256(path) if path.is_file() else "MISSING"
            integrity_rows.append({"worktree": name, "relative_path": relative,
                                   "sha256_before": old_hash, "sha256_after": current,
                                   "unchanged": current == old_hash})
    write_csv(output / "existing_file_integrity.csv", integrity_rows)
    research_git, production_git = git_snapshot(ROOT), git_snapshot(prod)
    raw_before = {k: v for k, v in before["research_hashes"].items()
                  if Path(k).parts[:2] == ("data", "raw")}
    raw_now = {str(p.relative_to(ROOT)): sha256(p) for p in (ROOT / "data/raw").rglob("*")
               if p.is_file()}
    inputs = []
    for relative, digest in raw_now.items():
        path = ROOT / relative
        classification = (
            "PROCESSED_RESULT_EXCLUDED" if "result" in path.name.casefold()
            and path.suffix.casefold() == ".dat" else (
                "NUMERICAL_RAW_NOT_EVALUATED" if path.suffix.casefold() in {".csv", ".dat"}
                else "NON_NUMERICAL_EXCLUDED"
            )
        )
        inputs.append({"absolute_path": str(path), "sha256": digest,
                       "classification": classification, "reader_called": False})
    write_csv(output / "raw_inventory_read_only.csv", inputs)
    with (output / "phase_a_frame_audit.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    blocked = Counter(r["reason"] for r in rows if r["proposal_blocked"] == "True")
    without_abstention = [r for r in rows if r["case_id"] != "K_LONG_WRONG_BRANCH_NO_RESCUE"]
    sensitivity_correctable = sum(r["candidate_correctable"] == "True"
                                 for r in without_abstention)
    sensitivity_blocked = sum(r["proposal_blocked"] == "True" for r in without_abstention)
    with (output / "phase_a_case_audit.csv").open(encoding="utf-8") as handle:
        cases = list(csv.DictReader(handle))
    source_hashes = {str(p.relative_to(ROOT)): sha256(p)
                     for folder in ("src", "scripts", "tests")
                     for p in (ROOT / folder).rglob("*task023e*.py")}
    legacy_source = ROOT / (
        "artifacts/task023d_smooth_branch_rescue/20260904T092908Z/"
        "synthetic_calibration_split.csv"
    )
    with legacy_source.open(encoding="utf-8") as handle:
        legacy_rows = [{**r, "task023e_evidence_role": "LEGACY_DEVELOPMENT_REGRESSION",
                        "source_sha256": sha256(legacy_source)} for r in csv.DictReader(handle)]
    write_csv(output / "legacy_regression_index.csv", legacy_rows)
    final = {
        "task": "TASK-023E", "verdict": "STOPPED_AT_PROPOSAL_GATE",
        "cross_scale_hypothesis": "NOT_TESTED", "scorer": "NOT_IMPLEMENTED",
        "real_algorithm_evaluation": "NOT_RUN", "ai": "NOT_STARTED",
        "research_git": research_git, "production_git": production_git,
        "existing_files_unchanged": all(r["unchanged"] for r in integrity_rows),
        "raw_before_after_equal": raw_before == raw_now, "raw_count": len(raw_now),
        "source_hashes": source_hashes, "phase_a": gate, "blocked_reasons": dict(blocked),
        "phase_b": benchmark,
        "validation": {"full_pytest": test_summary, "ruff": ruff_text},
        "descriptive_sensitivity_excluding_intentional_abstention": {
            "correctable": sensitivity_correctable, "blocked": sensitivity_blocked,
            "fraction": sensitivity_blocked / sensitivity_correctable,
        },
    }
    if not final["existing_files_unchanged"] or not final["raw_before_after_equal"]:
        raise RuntimeError("Integrity check failed: inspect existing_file_integrity.csv")
    if production_git != before["production_git"]:
        raise RuntimeError("Production Git snapshot changed")
    for field in ("rev-parse HEAD", "diff --stat", "diff --cached --stat"):
        if research_git[field] != before["research_git"][field]:
            raise RuntimeError(f"Research frozen Git baseline changed: {field}")
    with (output / "experiment_metadata.json").open("x", encoding="utf-8") as handle:
        json.dump(final, handle, indent=2)
    figure = Figure(figsize=(10, 4), layout="constrained")
    axis = figure.subplots()
    labels = [r["case_id"].replace("_", " ") for r in cases]
    missing = [int(r["proposal_blocked_frames"]) for r in cases]
    offered = [int(r["candidate_correctable_wrong_frames"]) - m
               for r, m in zip(cases, missing, strict=True)]
    axis.barh(labels, offered, label="Correct candidate offered", color="#287D8E")
    axis.barh(labels, missing, left=offered, label="Correct candidate unavailable to selector",
              color="#D89032")
    axis.set(xlabel="Strongest wrong frames with an available correct Top-K candidate",
             title="Frozen beam feasibility: legacy audit, not fresh held-out")
    axis.legend(loc="lower right", fontsize=8)
    figure.savefig(output / "figures/proposal_bottleneck.png", dpi=140)
    table = "\n".join(
        f"| {r['case_id']} | {r['candidate_correctable_wrong_frames']} | "
        f"{r['proposal_blocked_frames']} |" for r in cases
    )
    report = f"""# TASK-023E: fixed-proposal feasibility and waveform benchmark

## Decision

**STOPPED_AT_PROPOSAL_GATE.** Cross-scale scoring is **NOT TESTED**, not disproved.
The authorized phase-A stop condition was met before implementing a scorer.
No margin was selected, no AI was trained, and no new real-data tracker was run.

Of {gate['candidate_correctable_wrong_frames']} strongest wrong frames that have a
truth-near Top-K candidate, {gate['proposal_blocked_frames']} ({gate['proposal_blocked_fraction']:.2%})
cannot obtain a correct replacement from the frozen proposal interface. The
predeclared majority threshold is strictly greater than 50%. This finding is
limited to the six declared legacy diagnostic cases, not a population estimate.

| Legacy case | Candidate-correctable errors | Blocked from scorer |
|---|---:|---:|
{table}

Blocked breakdown: {blocked.get('CORE_LOCKED', 0)} retained-core locks and
{blocked.get('TERMINAL_PROPOSAL_MISSING', 0)} terminal-proposal absences.
The legacy long-wrong-branch case was originally an intentional abstention
guard. Excluding it still leaves {sensitivity_blocked}/{sensitivity_correctable}
({sensitivity_blocked / sensitivity_correctable:.2%}) blocked, so the majority
conclusion is not caused solely by counting that abstention case. This is a
descriptive sensitivity check; the declared gate itself was not changed.
The first-ranked exposed terminal state was checked for exact equality with
the existing TASK-023D search for every audited edge. Beam width, ordering,
costs, anchors, K=20 and extraction were not changed. Terminal states and
candidate ranks are exported in phase_a_terminal_beams.csv.

The geometric truth-connected flag tests a full contiguous truth-valid run;
it is not an anchor-identity certificate. The oracle_error_hz column is an
optimistic pointwise union of beam states and 023C fallback, not an admissible
output trajectory. No oracle or truth label is passed to tracking code.
All 212 candidate-correctable error frames also satisfy the frozen geometric
truth-connectivity diagnostic. Candidate absence and broken truth connectivity
therefore do not explain these selected legacy failures; review-region locks
and retained search hypotheses are the measured obstruction.

## Interpretation

The dominant measured obstacle is the permitted review region: 121 errors
are locked in retained cores. The remaining 27 are absent from the final beam.
A better selector alone cannot repair these errors. Candidate availability
must not be conflated with selectable branch availability, and preserved core
frequencies must not be described as validated physical truth.

Next research should narrowly audit review-region/anchor ownership and loss of
the correct hypothesis at divergence, merge and crossing. Do not increase K,
beam width, smoothing, continuity weights or train an AI scorer on this result.
Changing those mechanisms requires a separate TASK; nothing is promoted here.

## Phase B delivered

Generated {benchmark['waveforms']} time-domain waveforms: 8 families x 24, with
64 calibration and 128 fresh held-out instances, each using both original
profiles ({benchmark['profile_rows']} input-validation rows). Sampling is 40 GHz,
record length 2 us. Original Hann STFT and Top-20 extraction are called directly.
All {benchmark['unique_voltage_hashes']} main voltage hashes are unique. No raw
experimental record was used for generator tuning. Parameters, seeds and truth
are saved with each input in fresh_waveform_manifest.csv and generated_waveforms/.

Another 16 label-swap pairs have bitwise identical voltage within each pair,
different target identities and a shared observation group. They are a separate
identifiability diagnostic, not part of accuracy rankings. Scorer confidence
on these inputs is NOT EVALUATED because the scorer was not implemented.

fresh_strongest_input_validation.csv contains baseline-only validation, not
an algorithm comparison. Zero-truth cases have blank RMSE/wrong fraction;
zero-intervention precision/harm are blank, never reported as perfect scores.
NO_SIGNAL in that table is an explicit generator reference, not a detector
prediction. Target truth is sampled at the STFT frame center; near-window
dropouts and unresolved overlapping components need separate stratification
before any future accuracy claim. These are simplified oscillator mixtures,
not a validated forward model of the ch3 experiment or optical scattering.

All old synthetic cases remain legacy development/regression evidence. No
fresh multi-method aggregate gate or bootstrap winner test was executed after
the feasibility stop. Auxiliary W/2 and 2W STFTs, the selector and real-data
34-stream comparison were deliberately not implemented/run. These are skipped
conditional phases, not successful cross-scale results.

## Validation and integrity

- Full pytest: `{test_summary}`.
- Ruff: `{ruff_text}`.
- Phase-A/B new unit tests cover fixed-beam equivalence/provenance, majority
  decisions, NaN truth denominators, phase integration, deterministic seeds,
  split grouping, label swaps, unchanged voltage and original STFT axes.
- Existing Research/Production files compared: {len(integrity_rows)}; all unchanged.
- Research raw entries: {len(raw_now)}; before/after SHA-256 sets equal.
- Processed result DAT files are classified before any raw reader; raw readers
  were not called for a real-data experiment in this stopped TASK.
- Research HEAD: {research_git['rev-parse HEAD']}; tracked/staged diffs unchanged.
- Production main HEAD: {production_git['rev-parse HEAD']}; Git snapshot unchanged.
- New Research files remain untracked. No commit/push/merge/rebase/cherry-pick.

The first invocation (pytest_full.txt) had two additional harness failures:
CLI parsed pytest command-line arguments, and a deeply nested Windows temporary
path exceeded the legacy path limit. The complete suite was rerun with options
in PYTEST_ADDOPTS and a new short Research-local basetemp (pytest_full_env.txt).
No tests were excluded or assertions changed. The two historical launcher
assertion failures remain failures; no launcher was modified to hide them.

## Reproduction

Use the existing dps-studio Python environment, with PYTHONPATH=src;.
Run freeze_task023e.py --output <new-timestamp-directory> to create the freeze. Run
run_task023e_proposal_audit.py --output <new-directory>, then, only if its stop
gate is true, run_task023e_waveform_benchmark.py --output <new-directory>.
All artifact writers use exclusive creation; do not reuse or clean this run.
The immutable starting freeze is freeze_before.json; final source hashes and
status are experiment_metadata.json. Test outputs are pytest_full*.txt.
"""
    with (output / "final_research_report.md").open("x", encoding="utf-8") as handle:
        handle.write(report)
    log_path = Path("D:/Research/Notes/05项目/dps/2026-09-11_TASK-023E_支路提案审计与时域benchmark.md")
    log = f"""---
task: TASK-023E
date: 2026-09-11
branch: codex/research_2/global-path-ridge
status: completed-with-planned-stop
verdict: STOPPED_AT_PROPOSAL_GATE
artifact: {output}
---

# TASK-023E

- 已执行阶段 A；正确候选可用的 212 个错误帧中，148 个无可用正确提案（69.81%），触发 >50% 停止门槛。
- 121 帧被 retained core 锁定，27 帧未进入终端提案；最佳 beam 与旧搜索完全一致。
- 阶段 B：192 条时域波形、384 个原 profile 输入验证、16 组身份交换歧义对。
- 跨尺度 scorer 未实现/未检验；未启动 AI，未开展新的真实数据算法评价。
- 输入证据：023D 20260904T092908Z metadata、既有六类失败/对照案例、当前源码和 TASK-023E CSV。
- 下一步：限定研究可审查区域/锚点归属与正确提案保留，暂不训练 scorer；需独立 TASK 授权。
- pytest：{test_summary}；ruff：{ruff_text}。
- 24 个 raw 哈希及既有文件未变；Production/main HEAD 07a1e0f，clean，冻结。
- 未 commit/push/promotion。详细结论见 artifact/final_research_report.md。
"""
    with log_path.open("x", encoding="utf-8") as handle:
        handle.write(log)
    print(output / "final_research_report.md")
    print(log_path)


if __name__ == "__main__":
    main()
