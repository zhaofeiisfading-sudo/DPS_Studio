"""Run Qt test modules in separate processes to isolate application lifecycles."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="DEV")
    parser.add_argument("--only", nargs="*", help="Test module stems to rerun")
    parser.add_argument("--isolate-cases", action="store_true", help="Fresh Qt process per test case")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not args.task.replace("-", "").isalnum():
        parser.error("Invalid task directory")
    output = ROOT / "artifacts" / args.task
    reports = output / "validation"
    reports.mkdir(parents=True, exist_ok=True)
    temporary = output / "tmp/gui"
    temporary.mkdir(parents=True, exist_ok=True)
    results = []
    combined = ET.Element("testsuites")
    jobs = []
    for module in sorted((ROOT / "tests/unit/gui").glob("test_*.py")):
        if args.only and module.stem not in args.only:
            continue
        if args.isolate_cases:
            collected = subprocess.run([sys.executable, "-B", "-m", "pytest", "--collect-only",
                                        "-q", str(module)], cwd=ROOT, capture_output=True,
                                       text=True, timeout=30, check=True)
            jobs += [(module, line.strip()) for line in collected.stdout.splitlines()
                     if "::" in line and not line.startswith(" ")]
        else:
            jobs.append((module, str(module)))
    for index, (module, selection) in enumerate(jobs):
        identifier = f"{module.stem}-{index}" if args.isolate_cases else module.stem
        report = temporary / f"{identifier}.xml"
        started = time.monotonic()
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        command = [sys.executable, "-B", "-m", "pytest", "-q", selection,
                   "--basetemp", str(temporary / identifier), "--junitxml", str(report)]
        try:
            run = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=args.timeout_seconds)
            code, log = run.returncode, run.stdout + run.stderr
        except subprocess.TimeoutExpired as exc:
            def decoded(value: str | bytes | None) -> str:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            code, log = 124, f"Qt test timed out after {args.timeout_seconds} s: {exc}\n" + decoded(exc.stdout) + decoded(exc.stderr)
        row = {"module": module.relative_to(ROOT).as_posix(), "selection": selection, "exit_code": code,
               "seconds": round(time.monotonic() - started, 2), "tests": 0,
               "failures": 0, "errors": 0, "skipped": 0}
        if report.exists():
            suites = ET.parse(report).getroot()
            for suite in suites:
                combined.append(suite)
                for key in ("tests", "failures", "errors", "skipped"):
                    row[key] += int(suite.get(key, "0"))
        else:
            row["errors"] = 1
            suite = ET.SubElement(combined, "testsuite", name=module.stem, tests="1", errors="1")
            case = ET.SubElement(suite, "testcase", name="module_process")
            ET.SubElement(case, "error", message=f"Process exit {code}").text = log[-10000:]
        if code:
            (reports / f"gui-{identifier}-failure.log").write_text(log, encoding="utf-8")
        results.append(row)
        print(f"{selection}: exit={code}, tests={row['tests']}, {row['seconds']}s", flush=True)
    prefix = "gui-cases-regression" if args.isolate_cases else "gui-regression"
    ET.ElementTree(combined).write(reports / f"{prefix}.xml", encoding="utf-8", xml_declaration=True)
    (reports / f"{prefix}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return int(any(row["exit_code"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
