"""Run only metadata/real-input tests, avoiding synthetic-waveform tests by design."""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys

import matplotlib
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import scipy  # type: ignore[import-untyped]

from scripts.research.task017.prepare import OUT, ROOT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="validation_v01")
    parser.add_argument("--reuse-pytest-from")
    options = parser.parse_args()
    output = OUT / "data" / options.output
    if not output.resolve().is_relative_to(OUT / "data"):
        parser.error("Choose a directory name inside TASK-017/data")
    output.mkdir(exist_ok=False)
    commands = {
        "pytest": ["-m", "pytest", "-q", "tests/unit/test_task017_real_research.py",
                   "tests/unit/test_task013_git_hygiene.py", "tests/unit/test_task009_migration.py",
                   "tests/unit/test_task015_stage_strategies.py::"
                   "test_motion_and_observation_quality_are_independent_and_legacy_noise_loads"],
        "ruff": ["-m", "ruff", "check", "scripts/research/task017",
                 "tests/unit/test_task017_real_research.py"],
        "mypy": ["-m", "mypy", "--explicit-package-bases", "--follow-imports=silent",
                 "scripts/research/task017", "tests/unit/test_task017_real_research.py"],
        "hygiene": ["scripts/maintenance/check_repo_hygiene.py"],
        "hygiene_json": ["scripts/maintenance/check_repo_hygiene.py", "--json"],
        "hygiene_staged": ["scripts/maintenance/check_repo_hygiene.py", "--staged-only"],
    }
    results = {}
    for name, args in commands.items():
        if name == "pytest" and options.reuse_pytest_from:
            prior = OUT / "data" / options.reuse_pytest_from
            old = json.loads((prior / "results.json").read_text(encoding="utf-8"))["pytest"]
            if old["exit_code"] != 0:
                raise RuntimeError("Only reuse an actually passing test run")
            (output / "pytest.txt").write_text((prior / "pytest.txt").read_text(encoding="utf-8"),
                                               encoding="utf-8")
            results[name] = {**old, "reused_from": str(prior)}
            print("pytest 0 (reused passing log)", flush=True)
            continue
        process = subprocess.run([sys.executable, "-B", *args], cwd=ROOT, capture_output=True,
                                 encoding="utf-8", errors="replace")
        (output / f"{name}.txt").write_text(process.stdout+process.stderr, encoding="utf-8")
        results[name] = {"exit_code": process.returncode, "args": args}
        print(name, process.returncode, flush=True)
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (output / "environment.json").write_text(json.dumps({
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "numpy": np.__version__, "scipy": scipy.__version__, "pandas": pd.__version__,
        "matplotlib": matplotlib.__version__,
        "test_scope": "Existing non-waveform unit tests + all-channel real-input contracts; "
                      "synthetic-waveform tests intentionally not executed per TASK-017 constraint",
        "no_dependency_install": True}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
