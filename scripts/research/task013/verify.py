"""Task-specific regression entry with the existing TASK-009 local data adapter."""
from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np

from .cases import load, specifications
from .experiment import OUT, ROOT, write_json
from .git_governance import PRODUCTION, manifest
from .stage import frozen_estimate


def tests(tag: str) -> None:
    import pytest
    from dps_studio.research.task009_data import install

    # Legacy TASK-008 inventory expects 13 logical inputs. Three were explicitly
    # relocated during TASK-009, and must be reached through its owning adapter.
    install()
    names = ["test_task013_stage.py", "test_task013_git_hygiene.py", "test_research_task008.py",
             "test_research_task008_baseline_audit.py", "test_task009_migration.py",
             "test_task009_figures.py", "test_research_task010.py", "test_task011_segmentation.py"]
    temporary = ROOT / f".task13_pytest_{tag}"
    result = OUT / f"checks/pytest_{tag}.xml"
    if temporary.exists() or result.exists():
        raise FileExistsError("Choose a new --tag to preserve previous test outputs")
    status = pytest.main(["-q", *[str(ROOT / "tests/unit" / name) for name in names],
        "--basetemp=" + str(temporary), "--junitxml=" + str(result)])
    raise SystemExit(status)


def parity() -> None:
    checked = 0
    maximum = 0.
    for spec in specifications():
        case = load(spec)
        with np.load(OUT / "runs/evaluation_v01/cases" / f"{case.signal.name}.npz") as z:
            from dps_studio.algorithms.waveform.common import Signal
            stored_signal = Signal(np.array(z["time_s"]), np.array(z["voltage_v"]))
            for method in ("stft512", "stft768"):
                result = frozen_estimate(stored_signal, method)
                for key, actual in (("candidate_hz", result.candidate_hz),
                                    ("accepted_hz", result.accepted_hz)):
                    previous = z[method + "__" + key]
                    np.testing.assert_array_equal(previous, actual)
                    finite = np.isfinite(previous) & np.isfinite(actual)
                    if np.any(finite):
                        maximum = max(maximum, float(np.max(abs(previous[finite] - actual[finite]))))
                checked += 1
    write_json(OUT / "checks/integer_grid_parity.json", {
        "method_case_pairs": checked, "maximum_difference_hz": maximum,
        "all_candidates_and_accepted_exactly_equal": True,
        "reason": "Replace floating-time searchsorted with integer sample alignment for real absolute timestamps.",
        "evaluation_unchanged": True})
    print(f"Integer-grid repair preserves {checked} synthetic method/case trajectories exactly")


def boundaries(tag: str) -> None:
    from dps_studio.research.task009_data import inventory

    before = json.loads((OUT / "checks/boundary_before.json").read_text(encoding="utf-8"))
    production_skip = {"artifacts", "build", "dist", ".mypy_cache", ".pytest_cache",
                       ".ruff_cache", ".git"}
    after: dict[str, Any] = {
        "raw": manifest(ROOT / "data/raw"), "release": manifest(ROOT / "release"),
        "production": manifest(PRODUCTION, skip=production_skip),
        "production_git": manifest(PRODUCTION / ".git"),
        "production_generated_inventory": {
            name: manifest(PRODUCTION / name, metadata_only=True)
            for name in sorted(production_skip - {".git"}) if (PRODUCTION / name).exists()
        },
        "prior_artifacts": {str(n): manifest(ROOT / f"artifacts/research_clean_task{n}", metadata_only=True)
                            for n in (8, 9, 10, 11, 12)},
        "source": manifest(ROOT / "src"), "configs": manifest(ROOT / "configs"),
    }
    write_json(OUT / f"checks/boundary_after_{tag}.json", after)
    verdict: dict[str, Any] = {key + "_unchanged": before[key] == value for key, value in after.items()}
    for section in ("production", "production_git", "source", "raw", "release", "configs"):
        left, right = before[section], after[section]
        verdict[section + "_differences"] = [name for name in sorted(set(left) | set(right))
                                              if left.get(name) != right.get(name)]
    indexed = inventory()  # Re-read every indexed raw file and verify its SHA256.
    previous = json.loads((OUT / "checks/indexed_raw_before.json").read_text(encoding="utf-8"))
    verdict["indexed_13_raw_unchanged"] = previous == indexed
    verdict["large_generated_inventory_check"] = "names/size/mtime; raw, release, source, configs and Git are SHA256"
    write_json(OUT / f"checks/boundary_verification_{tag}.json", verdict)
    print(json.dumps(verdict, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("tests", "parity", "boundaries"))
    parser.add_argument("--tag", default="acceptance")
    args = parser.parse_args()
    if not args.tag.replace("_", "").isalnum():
        raise ValueError("--tag must contain only letters, digits and underscores")
    if args.mode == "parity":
        parity()
    else:
        {"tests": tests, "boundaries": boundaries}[args.mode](args.tag)


if __name__ == "__main__":
    main()
