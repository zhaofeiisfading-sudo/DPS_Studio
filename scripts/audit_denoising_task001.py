"""Read-only boundary snapshot; TASK-001 outputs must be outside all worktrees."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKTREES = (ROOT, ROOT.with_name("DPS_Studio"), ROOT.with_name("DPS_Studio_TASK021A"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def safe_output(path: Path) -> Path:
    absolute = path.absolute()
    for parent in (absolute, *absolute.parents):
        if parent.exists() and (parent.is_symlink() or parent.is_junction()):
            raise ValueError(f"Reparse point forbidden: {parent}")
    resolved = absolute.resolve()
    if any(resolved.is_relative_to(w.resolve()) for w in WORKTREES):
        raise ValueError("Output must be outside all three worktrees")
    return resolved


def git(root: Path, *args: str) -> str:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return subprocess.check_output(["git", "-C", str(root), *args], env=env).decode(
        "utf-8", errors="replace"
    ).strip()


def snapshot() -> dict[str, Any]:
    output: dict[str, Any] = {}
    for root in WORKTREES:
        tracked = git(root, "ls-files", "-z").split("\0")
        # Source/config/docs and raw, never follow artifacts or historical test outputs.
        files = {
            name: digest(root / name) if (root / name).is_file() else "MISSING"
            for name in tracked
            if name and (name.startswith(("src/", "scripts/", "tests/", "configs/", "docs/"))
                         or "/" not in name)
        }
        raw = {p.relative_to(root).as_posix(): digest(p)
               for p in sorted((root / "data/raw").rglob("*")) if p.is_file()}
        output[str(root)] = dict(
            head=git(root, "rev-parse", "HEAD"), branch=git(root, "branch", "--show-current"),
            status_sha256=hashlib.sha256(git(root, "status", "--porcelain=v1").encode()).hexdigest(),
            diff_sha256=hashlib.sha256(git(root, "diff", "--raw").encode()).hexdigest(),
            files=files, raw=raw,
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    destination = safe_output(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    current = snapshot()
    if args.before:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        changes: dict[str, Any] = {}
        for root, old in before.items():
            now = current[root]
            changes[root] = dict(
                changed_existing_files=[name for name, h in old["files"].items()
                                        if now["files"].get(name) != h],
                raw_identical=old["raw"] == now["raw"],
                head_identical=old["head"] == now["head"],
                status_identical=old["status_sha256"] == now["status_sha256"],
                tracked_diff_identical=old["diff_sha256"] == now["diff_sha256"],
            )
        current = {"verification": changes, "after": current}
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
    print(destination)


if __name__ == "__main__":
    main()
