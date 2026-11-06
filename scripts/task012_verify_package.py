"""Run the frozen GUI with a Windows-only PATH and isolated per-case settings."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task12"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=("normal", "real", "layout"), default="normal")
    parser.add_argument("--hold", action="store_true", help="Keep normal acceptance open for native input, then close it to finish")
    args = parser.parse_args()
    executable = args.executable.resolve()
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    output = args.output.resolve()
    if not executable.is_relative_to(ROOT) or not output.is_relative_to(ARTIFACT):
        raise ValueError("Verification paths must remain inside Research")
    output.mkdir(parents=True, exist_ok=False)
    cases: dict[str, tuple[Path, str | None]] = {"20260607_native": (ROOT / "data/raw/20260607.csv", None)}
    if args.suite == "real":
        cases = {f"ch{i}_native": (ROOT / ("data/raw/ch3.csv" if i == 3 else
                 f"artifacts/research_clean_task9/source_data/raw_supplement/ch{i}.csv"), None)
                 for i in range(1, 5)}
    elif args.suite == "layout":
        # This host's native devicePixelRatio is 2.0. Process-local Qt factors
        # exercise effective 100/125/150%; the OS/user settings are never changed.
        cases = {f"scale_{percent}": (ROOT / "data/raw/20260607.csv", str(percent / 200))
                 for percent in (100, 125, 150)}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CONDA", "PYTHON", "QT_", "QML"))}
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = f"{windows / 'System32'};{windows}"
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")

    def run_case(item: tuple[str, tuple[Path, str | None]]) -> dict[str, Any]:
        name, (source, factor) = item
        case_env = dict(env)
        if factor:
            case_env["QT_SCALE_FACTOR"] = factor
        command = [str(executable), "--task012-smoke", str(output / name), "--input", str(source)]
        if args.hold and args.suite == "normal":
            command.append("--hold")
        print(f"Starting frozen visible GUI: {name}", flush=True)
        with (output / f"{name}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=executable.parent, env=case_env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        report_path = output / name / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        independent = bool(report.get("module_paths")) and all(
            Path(path).is_relative_to(executable.parent) for path in report.get("module_paths", {}).values())
        passed = bool(result.returncode == 0 and report.get("passed") and report.get("frozen")
                      and report.get("window_visible") and report.get("qt_platform") == "windows" and independent)
        if factor:
            passed = passed and abs(report.get("device_pixel_ratio", 0) - float(factor) * 2) < .01
        print(f"{name}: {'PASS' if passed else 'FAIL'}", flush=True)
        return {"case": name, "passed": passed, "exit_code": result.returncode,
                "executable_sha256": executable_sha256,
                "executable_at_test": str(executable),
                "bundle_independent": independent, "environment_clean": True,
                "qt_scale_factor": factor, "device_pixel_ratio": report.get("device_pixel_ratio"),
                "report": str(report_path)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(run_case, cases.items()))
    (output / "verification.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    raise SystemExit(0 if all(row["passed"] for row in reports) else 1)


if __name__ == "__main__":
    main()
