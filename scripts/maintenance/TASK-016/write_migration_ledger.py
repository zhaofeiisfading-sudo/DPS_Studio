"""Record original/migrated fingerprints without editing historical freezes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    output = ROOT / "artifacts/TASK-016/audit"
    plan = json.loads((output / "migration-plan.json").read_text(encoding="utf-8"))
    repairs = json.loads((output / "reference-repairs.json").read_text(encoding="utf-8"))
    records = {}
    followups = json.loads((output / "followup-migrations.json").read_text(encoding="utf-8"))
    retired = {row["source"]: row["target"] for row in followups}

    def record(source: str, target: str, before: str, reason: str) -> None:
        target = retired.get(target, target)
        path = ROOT / target
        if not path.is_file():
            return
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        records[source] = {"target": target, "before_sha256": before, "after_sha256": after,
                           "byte_identical": before == after, "reason": reason}

    for row in plan["moves"]:
        record(row["source"], row["target"], row["sha256"], row["reason"])
    for row in plan["duplicates"]:
        record(row["source"], row["keep"], row["sha256"], "identical duplicate consolidated")
    moved = {row["target"]: row["source"] for row in plan["moves"]}
    for row in repairs:
        if row["path"] not in moved:
            record(row["path"], row["path"], row["before_sha256"], "updated imports/resource references")
    supplementary = output / "cleanup-supplement-plan.json"
    if supplementary.is_file():
        for row in json.loads(supplementary.read_text(encoding="utf-8"))["candidates"]:
            if "keep" in row:
                record(row["path"], row["keep"], row["sha256"], row["reason"])
    directories = {f"artifacts/research_clean_task{number}": f"artifacts/TASK-{number:03}"
                   for number in range(8, 16)}
    directories["artifacts/research_clean_task9/source_data"] = "data/research/TASK-009/source_data"
    manifest = {"purpose": "TASK-016 relocation lineage; historical freezes remain unchanged",
                "directories": directories, "files": records}
    destination = ROOT / "docs/tasks/TASK-016/SOURCE_MIGRATION.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    algorithm_records = [row for row in records.values()
                         if row["target"].startswith("src/dps_studio/algorithms/waveform/")]
    assert all(row["byte_identical"] for row in algorithm_records), "Estimator bytes changed"
    print(f"Recorded {len(records)} sources; all {len(algorithm_records)} estimator-source entries byte-identical")


if __name__ == "__main__":
    main()
