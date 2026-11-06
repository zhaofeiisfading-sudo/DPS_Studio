"""Read-only TASK-011 boundary snapshots; run only from the Research worktree."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT.parent / "DPS_Studio"
ARTIFACT = ROOT / "artifacts/research_clean_task11"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def inventory(root: Path) -> dict[str, dict[str, str | int]]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    print(f"Hashing {root}: {len(files)} files, {sum(p.stat().st_size for p in files)} bytes",
          flush=True)
    return {path.relative_to(root).as_posix(): {
        "sha256": digest(path), "bytes": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
    } for path in files}


def git(root: Path) -> dict[str, str]:
    return {name: subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(root), *args], text=True,
        encoding="utf-8").strip() for name, args in {
            "head": ["rev-parse", "HEAD"], "branch": ["branch", "--show-current"],
            "status": ["status", "--porcelain=v1"],
        }.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after", "final"))
    args = parser.parse_args()
    ARTIFACT.mkdir(exist_ok=True)
    report: dict[str, Any] = {
        "production_all_files_including_git": inventory(PRODUCTION),
        "research_raw": inventory(ROOT / "data/raw"),
        "frozen_task8": inventory(ROOT / "artifacts/research_clean_task8"),
        "frozen_task9": inventory(ROOT / "artifacts/research_clean_task9"),
        "frozen_task10": inventory(ROOT / "artifacts/research_clean_task10"),
        "production_git": git(PRODUCTION), "research_git": git(ROOT),
    }
    destination = ARTIFACT / f"boundary_{args.phase}.json"
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    if args.phase != "before":
        before = json.loads((ARTIFACT / "boundary_before.json").read_text(encoding="utf-8"))
        checks = {key: before[key] == report[key] for key in before
                  if key != "research_git"}
        checks["research_head_unchanged"] = before["research_git"]["head"] == report["research_git"]["head"]
        checks["research_branch_unchanged"] = before["research_git"]["branch"] == report["research_git"]["branch"]
        check_name = "boundary_verification.json" if args.phase == "after" else "boundary_verification_final.json"
        with (ARTIFACT / check_name).open("x", encoding="utf-8") as handle:
            json.dump(checks, handle, indent=2)
        print(json.dumps(checks), flush=True)
        if not all(checks.values()):
            raise SystemExit("Boundary mismatch: inspect snapshots")


if __name__ == "__main__":
    main()
