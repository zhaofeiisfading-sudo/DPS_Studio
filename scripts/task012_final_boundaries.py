"""Final read-only boundary check after the full before/after SHA-256 inventories."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task12"


def git(directory: Path) -> dict[str, str]:
    return {name: subprocess.check_output(["git", "--no-optional-locks", "-C", str(directory), *args],
            text=True, encoding="utf-8").strip() for name, args in {
                "head": ["rev-parse", "HEAD"], "branch": ["branch", "--show-current"],
                "status": ["status", "--porcelain=v1"],
            }.items()}


def main() -> None:
    before = json.loads((ARTIFACT / "boundary_before.json").read_text(encoding="utf-8"))
    after = json.loads((ARTIFACT / "boundary_after.json").read_text(encoding="utf-8"))
    verification = json.loads((ARTIFACT / "boundary_verification.json").read_text(encoding="utf-8"))
    assert all(verification.values())
    production = ROOT.parent / "DPS_Studio"
    current_metadata = {path.relative_to(production).as_posix(): {
        "bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        for path in production.rglob("*") if path.is_file()}
    expected_metadata = {key: {field: value[field] for field in ("bytes", "mtime_ns")}
                         for key, value in after["production_all_files_including_git"].items()}
    raw_rows: list[dict[str, Any]] = []
    for relative, record in before["research_raw"].items():
        source = ROOT / "data/raw" / relative
        with source.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        raw_rows.append({"path": str(source), "sha256": digest, "unchanged": digest == record["sha256"]})
    index = json.loads((ROOT / "artifacts/research_clean_task9/data_index.json").read_text(encoding="utf-8"))
    for row in index["records"]:
        if row["kind"] == "RAW":
            source = ROOT / row["local_path"]
            with source.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            assert digest == row["sha256"], source
    current_git = git(ROOT)
    checks = {"production_sha256_before_after": all(verification.values()),
              "production_final_file_metadata_unchanged": current_metadata == expected_metadata,
              "production_final_git_unchanged": git(production) == before["production_git"],
              "raw_final_sha256_unchanged": all(row["unchanged"] for row in raw_rows),
              "all_13_indexed_raw_inputs_sha256_match": True,
              "research_head_unchanged": current_git["head"] == before["research_git"]["head"],
              "research_branch_unchanged": current_git["branch"] == before["research_git"]["branch"]}
    (ARTIFACT / "boundary_final_check.json").write_text(json.dumps({
        "checks": checks, "raw": raw_rows,
        "production_full_sha256_evidence": ["boundary_before.json", "boundary_after.json"],
        "final_production_check_method": "Complete path/size/mtime_ns and Git check against the full SHA-256 after-inventory",
        "research_git": current_git}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks), flush=True)
    assert all(checks.values())


if __name__ == "__main__":
    main()
