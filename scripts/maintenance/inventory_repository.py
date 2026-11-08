"""Inventory physical files without traversing junctions; write only an explicit report.

This does not delete files, refresh Git indexes, or follow directory links. Hash
manifests can be compared before and after maintenance without touching raw data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


def linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def inventory(root: Path, *, include_git: bool = False) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"bytes": 0, "files": 0})
    files: dict[str, list[int]] = {}
    links: dict[str, str] = {}
    errors: list[str] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        folder = Path(current)
        for name in directories[:]:
            path = folder / name
            if linked(path):
                links[path.relative_to(root).as_posix()] = str(path.resolve())
                directories.remove(name)
            elif not include_git and path == root / ".git":
                directories.remove(name)
        for name in filenames:
            path = folder / name
            relative = path.relative_to(root).as_posix()
            if linked(path):
                links[relative] = str(path.resolve())
                continue
            try:
                stat = path.stat()
            except OSError as exc:
                errors.append(f"{relative}: {exc}")
                continue
            files[relative] = [stat.st_size, stat.st_mtime_ns]
            parts = Path(relative).parts
            for depth in (1, 2):
                key = "/".join(parts[:depth])
                if depth == 2 and len(parts) == 1:
                    continue
                groups[key]["bytes"] += stat.st_size
                groups[key]["files"] += 1
    return {"root": str(root), "groups": dict(sorted(groups.items())),
            "files": files, "links": links, "errors": errors}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args])


def snapshot(root: Path, production: Path | None = None) -> dict[str, Any]:
    result = inventory(root)
    result["head"] = git(root, "rev-parse", "HEAD").decode().strip()
    result["branch"] = git(root, "branch", "--show-current").decode().strip()
    result["status"] = git(root, "status", "--porcelain=v1", "-z").decode("utf-8")
    result["index"] = git(root, "ls-files", "--stage", "-z").decode("utf-8")
    staged = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    result["staged_worktree_sha256"] = {
        name: sha256(root / name) for name in staged.decode("utf-8").split("\0")
        if name and (root / name).is_file()
    }
    raw = root / "data/raw"
    raw_inventory = inventory(raw)
    result["raw_sha256"] = {name: sha256(raw / name) for name in raw_inventory["files"]}
    result["raw_links"] = raw_inventory["links"]
    if production is not None:
        boundary = inventory(production, include_git=True)
        names = git(production, "ls-files", "-z").decode("utf-8").split("\0")
        # Hash tracked content and mutable Git metadata; object-store metadata
        # is captured above without repeatedly reading immutable pack files.
        names += [name for name in boundary["files"]
                  if name.startswith(".git/") and not name.startswith(".git/objects/")]
        boundary["sha256"] = {name: sha256(production / name) for name in names
                              if name and (production / name).is_file()
                              and not linked(production / name)}
        result["production"] = boundary
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--production", type=Path)
    parser.add_argument("--output", type=Path, help="New JSON report; never overwrite an existing file")
    args = parser.parse_args()
    result = snapshot(args.root.resolve(), args.production)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        print(f"Inventory: {args.output}")
        for name, value in sorted(result["groups"].items(),
                                  key=lambda pair: pair[1]["bytes"], reverse=True)[:35]:
            print(f"{value['bytes'] / 2**30:9.3f} GiB {value['files']:7d} files {name}")
        print(f"Links skipped: {len(result['links'])}; raw hashes: {len(result['raw_sha256'])}")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
