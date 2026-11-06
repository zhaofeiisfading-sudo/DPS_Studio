"""Selective physical migration: preserve frozen bytes and document every file."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from .audit import OUT, ROOT, SOURCE, TASK8, digest, write_json


def disposition(relative: str) -> tuple[bool, str]:
    parts = Path(relative).parts
    if "__pycache__" in parts:
        return False, "bytecode cache; not research evidence"
    if parts[0] == "checks" and len(parts) > 1:
        key = parts[1]
        if key.startswith(("temp_", "pytest_cache", "mypy_")):
            return False, "pytest scratch/tool cache; reproducible, not frozen scientific output"
        if key == "reproduction_smoke" and len(parts) > 2:
            if parts[2] not in ("replay_comparison.json", "raw_invariance.json", "environment.json"):
                return False, "duplicate smoke inputs/outputs/source copy; replay comparison retained"
    return True, "frozen implementation/protocol/parameters/data/results/failure/figure/evidence"


def main() -> None:
    if (OUT/"migration_files.csv").exists():
        raise FileExistsError("Migration manifest already exists")
    original = json.loads((OUT/"provenance/junction_probe/boundary_before.json").read_text(encoding="utf-8"))
    source_hashes = original["source"]["task8"]
    TASK8.mkdir(exist_ok=False)
    rows: list[dict[str, Any]] = []
    for relative, expected in source_hashes.items():
        copy, reason = disposition(relative)
        src = SOURCE/"artifacts/research_clean_task8"/relative
        dst = TASK8/relative
        row = dict(source=str(src), destination=str(dst), relative=relative,
                   source_sha256=expected, bytes=src.stat().st_size,
                   action="COPY_LOCAL" if copy else "EXCLUDE_SCRATCH", reason=reason,
                   validation="not copied" if not copy else "")
        if copy:
            if not dst.resolve().is_relative_to(ROOT):
                raise RuntimeError(f"Destination escapes target: {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            with src.open("rb") as read, dst.open("xb") as write:
                shutil.copyfileobj(read, write, 1024*1024)
            actual = digest(dst)
            if actual != expected:
                raise RuntimeError(f"Frozen bytes mismatch: {relative}")
            row["target_sha256"] = actual
            row["validation"] = "SHA256_IDENTICAL"
        rows.append(row)
    for relative in ("tests/unit/test_research_task008.py",
                     "tests/unit/test_research_task008_baseline_audit.py", "COMPARISON.md"):
        src, dst = SOURCE/relative, ROOT/relative
        if dst.exists():
            if digest(src) != digest(dst):
                raise RuntimeError(f"Existing target differs; no overwrite: {dst}")
            action = "ALREADY_IDENTICAL"
        else:
            with src.open("rb") as read, dst.open("xb") as write:
                shutil.copyfileobj(read, write)
            action = "COPY_MISSING"
        rows.append(dict(source=str(src), destination=str(dst), relative=relative,
                         source_sha256=digest(src), target_sha256=digest(dst),
                         bytes=src.stat().st_size, action=action,
                         reason="missing test/dependency or root comparison with working relative links",
                         validation="SHA256_IDENTICAL"))
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT/"migration_files.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    residues = []
    for src in sorted((SOURCE/"artifacts/research_clean_task9").rglob("*")):
        if not src.is_file():
            continue
        relative = src.relative_to(SOURCE/"artifacts/research_clean_task9")
        backup = OUT/"provenance/junction_probe"/relative
        assert digest(src) == digest(backup)
        residues.append(dict(path=str(src), backup=str(backup), sha256=digest(src),
                             bytes=src.stat().st_size))
    write_json(OUT/"checks/source_probe_residue.json", dict(
        source_directory=str(SOURCE/"artifacts/research_clean_task9"), files=residues,
        new_this_task=True, preexisting_task8_untouched=True, deletion_authorization="PENDING"))
    write_json(OUT/"checks/migration_summary.json", dict(
        copied_files=sum(r["action"].startswith("COPY") for r in rows),
        copied_bytes=sum(r["bytes"] for r in rows if r["action"].startswith("COPY")),
        excluded_scratch_files=sum(r["action"] == "EXCLUDE_SCRATCH" for r in rows),
        every_copied_file_sha256_identical=True, target_task8_physical_directory=not TASK8.is_junction(),
        source_probe_residue_files=len(residues)))
    print(json.dumps(dict(copied=sum(r["action"].startswith("COPY") for r in rows),
        excluded=sum(r["action"] == "EXCLUDE_SCRATCH" for r in rows),
        bytes=sum(r["bytes"] for r in rows if r["action"].startswith("COPY"))), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
