"""Bind frozen logical raw identifiers to verified local physical files."""
from __future__ import annotations

import json
import shutil
from typing import Any

from .audit import OUT, ROOT, SOURCE, TASK8, digest, write_json


def main() -> None:
    original = json.loads((TASK8/"raw_inventory.json").read_text(encoding="utf-8"))
    local = {digest(p): p for p in (ROOT/"data/raw").rglob("*") if p.is_file()}
    rows: list[dict[str, Any]] = []
    for archived in original:
        row = dict(archived)
        if row["kind"] != "RAW":
            row["role"] = "ARCHIVED_EXCLUSION_METADATA_NOT_ALGORITHM_INPUT"
            rows.append(row)
            continue
        sha = row["sha256"]
        if sha in local:
            physical = local[sha]
            action = "EXISTING_RAW_IDENTICAL_SHA256"
        else:
            source = SOURCE/row["path"]
            if digest(source) != sha:
                raise RuntimeError(f"Source raw differs from frozen index: {source}")
            physical = OUT/"source_data/raw_supplement"/source.name
            physical.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as read, physical.open("xb") as write:
                shutil.copyfileobj(read, write)
            if digest(physical) != sha:
                raise RuntimeError("Raw supplement copy mismatch")
            action = "COPIED_MISSING_RAW_TO_RESEARCH_ARTIFACT_ONLY"
        row.update(local_path=physical.relative_to(ROOT).as_posix(), action=action,
                   local_sha256=digest(physical), role="READ_ONLY_ALGORITHM_INPUT",
                   source_logical_path=archived["path"])
        rows.append(row)
    raw = [r for r in rows if r["kind"] == "RAW"]
    assert len(raw) == 13 and sum(r["channels"] for r in raw) == 17
    write_json(OUT/"data_index.json", dict(scope="frozen TASK-008 logical dataset, verified local resolution",
        raw_files=13, voltage_streams=17, records=rows,
        existing_raw_directory_modified=False, copied_missing_inputs=sum(
            r.get("action", "").startswith("COPIED") for r in raw)))
    print("Data index complete: 13 logical raw files / 17 streams; three local supplements", flush=True)


if __name__ == "__main__":
    main()
