"""Timeout recovery must preserve evidence and never retry assertion failures."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.dev import check_gui


@pytest.mark.parametrize("failure", ["module-timeout", "assertion", "case-timeout"])
def test_gui_runner_recovery_and_failure_reporting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    module = tmp_path / "tests/unit/gui/test_example.py"
    module.parent.mkdir(parents=True)
    module.write_text("def test_first(): pass\ndef test_second(): pass\n", encoding="utf-8")
    monkeypatch.setattr(check_gui, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_gui.py", "--timeout-seconds", "1"])
    selections: list[str] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        if "--collect-only" in command:
            return subprocess.CompletedProcess(command, 0,
                f"{module}::test_first\n{module}::test_second\n", "")
        selection = command[5]
        selections.append(selection)
        if (selection == str(module) and failure != "assertion") or (
            failure == "case-timeout" and selection.endswith("::test_first")
        ):
            raise subprocess.TimeoutExpired(command, 1, output=b"captured progress")
        failed = failure == "assertion"
        report = Path(command[command.index("--junitxml") + 1])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            f'<testsuites><testsuite tests="1" failures="{int(failed)}" errors="0" skipped="0">'
            '<testcase name="example"/></testsuite></testsuites>', encoding="utf-8")
        return subprocess.CompletedProcess(command, int(failed), "test output", "")

    monkeypatch.setattr(check_gui.subprocess, "run", run)
    assert check_gui.main() == (0 if failure == "module-timeout" else 1)
    report_root = tmp_path / "artifacts/DEV/tmp/validation"
    rows = json.loads((report_root / "gui-regression.json").read_text(encoding="utf-8"))
    attempts = json.loads((report_root / "gui-regression-attempts.json").read_text(encoding="utf-8"))
    if failure == "assertion":
        assert selections == [str(module)]
        assert not attempts and rows[0]["failures"] == 1
    else:
        assert len(selections) == 3 and len(attempts) == 1
        assert attempts[0]["exit_code"] == 124 and attempts[0]["retry_cases"] == 2
        assert "captured progress" in Path(attempts[0]["log"]).read_text(encoding="utf-8")
        assert len(rows) == 2
        assert sum(row["errors"] for row in rows) == (1 if failure == "case-timeout" else 0)
