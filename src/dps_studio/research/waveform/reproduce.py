"""Replay frozen estimators into a NEW output tree without editing the source.

Invoke as a module from the Research repository. The core package and raw files
remain in the source worktree. Output redirection applies only to writers.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path

import numpy as np

from . import runner
from .audit import OUT, PRODUCTION, ROOT, sha
from dps_studio.algorithms.waveform.catalog import METHODS, run_folder
from .data import FAMILIES
from dps_studio.research.source_records import frozen_source_matches, relocated_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true",
                        help="12 first-instance cases; compare saved trajectories against frozen run")
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {destination}")
    if destination.is_relative_to((ROOT/"data").resolve()) or destination.is_relative_to(PRODUCTION):
        raise ValueError("Output cannot be inside raw/data or Production")
    records = ROOT/"docs/tasks/TASK-008/provenance"
    frozen = json.loads((records/"source_freeze.json").read_text(encoding="utf-8"))
    changed = [p for p, digest in frozen.items() if not frozen_source_matches(ROOT, p, digest)]
    amendment = json.loads((records/"baseline_audit_registration.json").read_text(encoding="utf-8"))
    changed += [p for p, digest in amendment["sources"].items()
                if not frozen_source_matches(ROOT, p, digest)]
    if changed:
        raise RuntimeError(f"Frozen estimator or test source changed: {changed}")
    raw_before = {p.relative_to(ROOT).as_posix(): sha(p)
                  for p in (ROOT/"data/raw").rglob("*") if p.is_file()}
    destination.mkdir(parents=True, exist_ok=False)
    setattr(runner, "OUT", destination)
    setattr(runner, "METHODS", METHODS)
    runner.write_json(destination/"source_freeze.json", frozen)
    runner.write_json(destination/"environment.json", dict(python=sys.version,
        executable=sys.executable, platform=platform.platform(), numpy=np.__version__,
        scipy=importlib.import_module("scipy").__version__,
        threads=os.environ.get("OPENBLAS_NUM_THREADS", "UNSPECIFIED"),
        source_worktree=str(ROOT), source_artifacts=str(OUT)))
    for relative in frozen:
        target = destination/"source_snapshot"/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relocated_path(ROOT, relative), target)
    shutil.copyfile(ROOT/"docs/tasks/TASK-008/PROTOCOL.md", destination/"PROTOCOL.md")
    for name in METHODS:
        module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
        runner.write_json(destination/name/"parameters.json", module.PARAMETERS)
    if args.smoke:
        runner.run_synthetic("smoke", 1)
        checks = []
        for name in METHODS:
            for family in FAMILIES:
                case_id = f"fresh_{family}_00"
                a = np.load(run_folder(OUT, name, "fresh", case_id)/"trajectory.npz")
                b = np.load(destination/name/"runs/smoke"/case_id/"trajectory.npz")
                for key in ("time_s", "frequency_hz", "accepted_hz", "r2"):
                    np.testing.assert_allclose(a[key], b[key], rtol=1e-11, atol=1e-3,
                                               equal_nan=True)
                checks.append(dict(method=name, family=family, trajectory_reproduced=True))
        runner.write_json(destination/"replay_comparison.json", checks)
    else:
        runner.run_synthetic("fresh", 8)
        runner.run_synthetic("phase_stress", 50)
        runner.run_real()
        for stage in ("fresh", "phase_stress", "real"):
            shutil.copyfile(destination/"tables"/f"{stage}_metrics.csv",
                            destination/"tables"/f"all_{stage}_metrics.csv")
        for name in ("summarize", "diagnose"):
            module = importlib.import_module(f"dps_studio.research.waveform.{name}")
            setattr(module, "OUT", destination)
            module.main()
        if args.figures:
            module = importlib.import_module("dps_studio.research.waveform.plot")
            setattr(module, "OUT", destination)
            module.main()
    raw_after = {p.relative_to(ROOT).as_posix(): sha(p)
                 for p in (ROOT/"data/raw").rglob("*") if p.is_file()}
    if raw_before != raw_after:
        raise AssertionError("Raw files changed during reproduction")
    runner.write_json(destination/"raw_invariance.json", dict(before=raw_before,
        after=raw_after, unchanged=True))
    print(f"Reproduction complete; original output preserved: {destination}", flush=True)


if __name__ == "__main__":
    main()
