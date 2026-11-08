"""Isolate Qt batches and record actual subprocess exits, JUnit and full logs."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARCHIVED_CHECKS = {
    "tests/unit/test_deployment_launchers.py::test_gui_launcher_uses_portable_conda_discovery":
        "Historical Production launcher assumption; Research launchers are intentionally guarded",
    "tests/unit/test_deployment_launchers.py::test_production_launcher_does_not_pin_the_author_python_path":
        "Historical Production demo launcher assumption; this worktree intentionally disables it",
    "tests/unit/test_task023a_imm_mht_tracker.py::test_fixed_upstream_and_raw_guardrails":
        "2026-09 byte freeze superseded by explicitly authorized v0.1.6 migration; preimages preserved",
    "tests/unit/test_task023f_proposal_recovery.py::test_frozen_e4_constants_and_no_production_writes":
        "2026-09 Production snapshot differs from pre-task Production v0.1.6",
    "tests/unit/test_task023g_retention_audit.py::test_frozen_f_source_production_and_raw_hashes":
        "Historical task023f audit snapshot differs from unchanged pre-task Research source",
    "tests/unit/test_task025_informative_interval.py::test_frozen_original_source_and_config_hashes":
        "2026-09 source/config freeze superseded by authorized migration; preimages preserved",
    "tests/unit/test_task025_informative_interval.py::test_calibration_provenance_excludes_held_out_and_is_immutable":
        "Archived T25_CORE_amplitude_exchange_08_balanced.npz absent before TASK-011",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gui-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("Checks must remain inside Research")
    output.mkdir(parents=True, exist_ok=False)
    gui = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "tests/unit/gui").glob("test_*.py"))
    batches = {f"gui_{index // 4 + 1:02}": gui[index:index + 4] for index in range(0, len(gui), 4)}
    if not args.gui_only:
        batches = {"core_research": ["tests/unit", "--ignore=tests/unit/gui",
                    *[f"--deselect={node}" for node in ARCHIVED_CHECKS]], **batches}
        with (output / "archived_exclusions.json").open("x", encoding="utf-8") as handle:
            json.dump(ARCHIVED_CHECKS, handle, indent=2)
    reports = []
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'};{ROOT}", "PYTHONDONTWRITEBYTECODE": "1"}
    for name, selected in batches.items():
        temp_parent = ROOT / ".t11_verify" / output.name[-2:]
        temp_parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-B", str(ROOT / "scripts/research/task011/task011_checks.py"), *selected,
                   "-q", "-o", f"cache_dir={output / (name + '_cache')}",
                   f"--basetemp={temp_parent / name}",
                   f"--junitxml={output / (name + '.xml')}"]
        with (output / f"{name}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        reports.append({"batch": name, "exit_code": result.returncode, "files": selected})
        print(f"{name}: exit {result.returncode}", flush=True)
    with (output / "matrix.json").open("x", encoding="utf-8") as handle:
        json.dump(reports, handle, indent=2)
    raise SystemExit(0 if all(row["exit_code"] == 0 for row in reports) else 1)


if __name__ == "__main__":
    main()
