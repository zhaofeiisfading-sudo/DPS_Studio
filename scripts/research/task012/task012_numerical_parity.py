"""Re-run all 17 real streams against the archived TASK-011 numerical arrays."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from dps_studio.research.source_records import relocated_path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from scripts.research.task011.task011_real_regression import run  # noqa: E402


def main() -> None:
    artifact = ROOT / "artifacts/TASK-012"
    output = artifact / "numerical_current"
    output.mkdir(exist_ok=False)
    run("current", output)
    reference = ROOT / "artifacts/TASK-011/checks/real_current"
    old = json.loads((reference / "report.json").read_text(encoding="utf-8"))
    new = json.loads((output / "report.json").read_text(encoding="utf-8"))
    rows = []
    for before, after in zip(old["results"], new["results"], strict=True):
        assert before == after, after["key"]
        historical = (reference / f"{before['key']}.npz").relative_to(ROOT).as_posix()
        with np.load(relocated_path(ROOT, historical)) as left, np.load(output / f"{after['key']}.npz") as right:
            for field in left.files:
                np.testing.assert_array_equal(left[field], right[field])
            rows.append({"stream": after["key"], "exact_arrays": len(left.files), "flags_exact": True})
    assert len(rows) == 17
    (artifact / "numerical_parity.json").write_text(json.dumps({
        "passed": True, "raw_files": old["raw_files"], "streams": rows,
        "reference": str(reference), "meaning": "Exact TASK-011 parity; real physical truth unavailable"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
