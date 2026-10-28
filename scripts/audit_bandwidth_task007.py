"""Read-only TASK007 workspace/raw audit; always creates a new output file."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def audit() -> dict[str, Any]:
    raw = []
    for path in sorted((ROOT / "data/raw").iterdir()):
        if not path.is_file():
            continue
        row: dict[str, Any] = dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size)
        if path.suffix.lower() in {".csv", ".dat"} and "result" not in path.stem.lower():
            try:
                data = np.loadtxt(path, delimiter=",")
                dt = np.diff(data[:, 0])
                step = float(np.median(dt))
                row.update(rows=len(data), columns=data.shape[1], time_step_s=step,
                           exported_grid_rate_hz=1 / step, nyquist_hz=.5 / step,
                           max_relative_step_deviation=float(np.max(abs(dt / step - 1))),
                           span_s=float(data[-1, 0] - data[0, 0]),
                           voltage_rms_v=np.std(data[:, 1:], axis=0).tolist(),
                           units="s,V: project import convention; no instrument header",
                           instrument_model="UNKNOWN", analog_bandwidth_hz="UNKNOWN",
                           native_adc_rate_hz="UNKNOWN", acquisition_mode="UNKNOWN",
                           bandwidth_limiter="UNKNOWN", adc_bits="UNKNOWN",
                           detector_cable_amplifier_response="UNKNOWN",
                           wavelength_m="UNKNOWN", optical_offset_hz="UNKNOWN",
                           independent_velocity_truth="UNKNOWN")
            except (ValueError, OSError) as exc:
                row["parse_error"] = str(exc)
        raw.append(row)
    protected = {}
    for directory in ("src/dps_studio/core", "src/dps_studio/gui", "configs"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                protected[str(path.relative_to(ROOT))] = digest(path)
    return dict(root=str(ROOT), python=sys.version, branch=git("branch", "--show-current"),
                head=git("rev-parse", "HEAD"), status=git("status", "--short"),
                diff_stat=git("diff", "--stat"), raw=raw, protected_sha256=protected,
                artifacts_resolves_to=str((ROOT / "artifacts").resolve()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(audit(), stream, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
