"""Add historical M0 controls without changing the frozen estimator experiments."""
from __future__ import annotations

import importlib
import json

import pandas as pd  # type: ignore[import-untyped]

from . import runner
from .audit import OUT, ROOT, sha
from .common import METHODS
from .data import FAMILIES, generate, read_raw

EXTRA = ("legacy_m0_512", "legacy_m0_768")


def main() -> None:
    registration = dict(
        reason="Historical M0 retains discrete rank-one frequency when refinement fails; audit both contracts",
        no_estimator_retuning=True, original_source_freeze_unchanged=True,
        methods=list(EXTRA), original_methods=list(METHODS),
        sources={p.relative_to(ROOT).as_posix(): sha(p) for p in
                 [OUT/"legacy_m0_512/implementation.py", OUT/"legacy_m0_768/implementation.py"]})
    if not (OUT/"baseline_audit_registration.json").exists():
        runner.write_json(OUT/"baseline_audit_registration.json", registration)
    else:
        saved = json.loads((OUT/"baseline_audit_registration.json").read_text(encoding="utf-8"))
        assert saved["sources"] == registration["sources"]
    setattr(runner, "METHODS", EXTRA)
    for name in EXTRA:
        module = importlib.import_module(f"artifacts.research_clean_task8.{name}.implementation")
        if not (OUT/name/"parameters.json").exists():
            runner.write_json(OUT/name/"parameters.json", module.PARAMETERS)
    for stage, cases in (("fresh", [(f, i) for f in FAMILIES for i in range(8)]),
                         ("phase_stress", [("low_ramp", i) for i in range(50)])):
        rows = []
        for family, i in cases:
            case = generate(family, i, phase_stress=stage == "phase_stress")
            rows.extend(runner.evaluate_signal(case.signal, "baseline_"+stage, case.signal.name, case, {}))
        runner.write_csv(OUT/"tables"/f"baseline_{stage}_metrics.csv", rows)
        for name in EXTRA:
            runner.write_csv(OUT/name/f"{stage}_metrics.csv", [r for r in rows if r["method"] == name])
        print(f"Historical M0 controls complete: {stage}", flush=True)
    inventory = json.loads((OUT/"raw_inventory.json").read_text(encoding="utf-8"))
    rows = []
    for i, item in enumerate(r for r in inventory if r["kind"].startswith("RAW")):
        for c, signal in enumerate(read_raw(item), 1):
            case_id = f"raw{i:02d}_{signal.name}"
            source = dict(raw_path=item["path"], raw_sha256=item["sha256"], voltage_column=c,
                hardware_channel="filename label only; acquisition mapping unverified",
                sample_rate_hz=signal.fs, samples=len(signal.time_s))
            rows.extend(runner.evaluate_signal(signal, "baseline_real", case_id, None, source))
        print(f"Historical M0 controls on raw {i+1}/13", flush=True)
    runner.write_csv(OUT/"tables/baseline_real_metrics.csv", rows)
    for name in EXTRA:
        runner.write_csv(OUT/name/"real_metrics.csv", [r for r in rows if r["method"] == name])
    for stage in ("fresh", "phase_stress", "real"):
        old = pd.read_csv(OUT/"tables"/f"{stage}_metrics.csv")
        extra = pd.read_csv(OUT/"tables"/f"baseline_{stage}_metrics.csv")
        runner.write_csv(OUT/"tables"/f"all_{stage}_metrics.csv", pd.concat([old, extra]).to_dict("records"))
    print("All fourteen methods have exhaustive final data coverage", flush=True)


if __name__ == "__main__":
    main()
