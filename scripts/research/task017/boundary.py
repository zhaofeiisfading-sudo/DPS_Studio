"""Read-only before/after manifests; never follows directory links or writes Git."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/TASK-017/data/boundaries"
PRODUCTION = ROOT.parent / "DPS_Studio"


def manifest(root: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(folder) / d).is_junction()
                         and not (Path(folder) / d).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if path.is_symlink():
                continue
            stat = path.stat()
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            result[path.relative_to(root).as_posix()] = {
                "sha256": digest, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return result


def git(root: Path) -> dict[str, str]:
    def command(*args: str) -> str:
        return subprocess.check_output(
            ["git", "--no-optional-locks", "-C", str(root), *args], encoding="utf-8").strip()
    return {"head": command("rev-parse", "HEAD"), "branch": command("branch", "--show-current"),
            "status": command("status", "--porcelain=v1"),
            "staged": command("diff", "--cached", "--stat"),
            "common": command("rev-parse", "--path-format=absolute", "--git-common-dir")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    phase = parser.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    value = {"research_git": git(ROOT), "production_git": git(PRODUCTION),
             "raw": manifest(ROOT / "data/raw"), "source": manifest(ROOT / "src"),
             "production": manifest(PRODUCTION), "python": sys.executable}
    with (OUT / f"{phase}.json").open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    if phase == "after":
        before = json.loads((OUT / "before.json").read_text(encoding="utf-8"))
        checks = {key: before[key] == value[key] for key in
                  ("production_git", "production", "raw", "source")}
        with (OUT / "comparison.json").open("x", encoding="utf-8") as handle:
            json.dump(checks, handle, indent=2)
        print(checks, flush=True)
        if not all(checks.values()):
            raise RuntimeError("Boundary changed; inspect complete manifests")
    print(f"{phase} snapshot complete", flush=True)


if __name__ == "__main__":
    main()
