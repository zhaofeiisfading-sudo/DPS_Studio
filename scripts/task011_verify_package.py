"""Launch the portable EXE with Conda/Python/Qt source paths removed."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task11"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("normal", "difficult", "all"), default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ARTIFACT):
        raise ValueError("Verification output must remain in the artifact")
    output.mkdir(parents=True, exist_ok=False)
    executable = ARTIFACT / "portable_v4/PDV_Studio_Research_TASK011/PDV Studio Research TASK011.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    cases = {"normal": ROOT / "data/raw/20260607.csv"}
    if args.case != "normal":
        cases.update({f"ch{index}": ROOT / ("data/raw/ch3.csv" if index == 3 else
            f"artifacts/research_clean_task9/source_data/raw_supplement/ch{index}.csv")
            for index in range(1, 5)})
    if args.case == "difficult":
        cases.pop("normal")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("CONDA", "PYTHON", "QT_", "QML"))}
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = f"{windows / 'System32'};{windows}"
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    reports = []
    for name, source in cases.items():
        print(f"Starting frozen visible GUI acceptance: {name}", flush=True)
        destination = output / name
        command = [str(executable), "--task011-smoke", str(destination), "--input", str(source)]
        with (output / f"{name}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=executable.parent, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=1200)
        report_path = destination / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        independent = bool(report.get("module_paths")) and all(
            Path(path).is_relative_to(executable.parent) for path in report.get("module_paths", {}).values())
        passed = (result.returncode == 0 and report.get("passed") and report.get("frozen")
                  and report.get("window_visible") and report.get("qt_platform") == "windows"
                  and report.get("roi_edit_and_invalidation_validated") and independent)
        reports.append({"case": name, "exit_code": result.returncode, "passed": bool(passed),
                        "all_application_modules_inside_bundle": independent,
                        "conda_python_source_environment_removed": True,
                        "report": str(report_path)})
        print(f"Frozen {name}: {'PASS' if passed else 'FAIL'}", flush=True)
    with (output / "verification.json").open("x", encoding="utf-8") as handle:
        json.dump(reports, handle, indent=2)
    raise SystemExit(0 if all(row["passed"] for row in reports) else 1)


if __name__ == "__main__":
    main()
