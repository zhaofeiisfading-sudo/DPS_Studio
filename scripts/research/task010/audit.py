"""Exclusive-write boundary snapshots for the STFT experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[3] / "artifacts/TASK-010"
PRODUCTION = ROOT.parent / "DPS_Studio"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def inventory(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args],
                                   encoding="utf-8", errors="replace").strip()


def code(root: Path) -> dict[str, str]:
    paths = [p for folder in ("src", "scripts", "tests", "configs", "docs", "tools")
             for p in (root / folder).rglob("*") if p.is_file()
             and "__pycache__" not in p.parts]
    paths += [p for p in root.iterdir() if p.is_file() and p.suffix in
              (".md", ".py", ".toml", ".yml", ".bat")]
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(paths)}


def state(root: Path) -> dict[str, Any]:
    index = Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    return dict(root=str(root), head=git(root, "rev-parse", "HEAD"),
                branch=git(root, "branch", "--show-current"),
                status=git(root, "status", "--porcelain=v1"), index_sha256=sha(index),
                code=code(root), raw=inventory(root / "data/raw"))


def snapshot(label: str) -> dict[str, Any]:
    if OUT.parent.is_symlink():
        raise RuntimeError("Research must execute in the physical target worktree")
    value = dict(target=state(ROOT), production=state(PRODUCTION),
                 task8=inventory(ROOT / "artifacts/TASK-008"),
                 task9=inventory(ROOT / "artifacts/TASK-009"),
                 cloud_parent_accessible=Path(
                     "G:/我的云端硬盘/codex/pdv_studio_research").is_dir())
    write_json(OUT / f"boundary_{label}.json", value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", choices=("before", "after"))
    args = parser.parse_args()
    value = snapshot(args.label)
    if args.label == "after":
        before = json.loads((OUT / "boundary_before.json").read_text(encoding="utf-8"))
        checks: dict[str, Any] = {}
        for name in ("target", "production"):
            a, b = before[name], value[name]
            checks[name] = {k + "_unchanged": a[k] == b[k]
                            for k in ("head", "branch", "index_sha256", "raw")}
            checks[name]["existing_code_unchanged"] = all(
                b["code"].get(p) == digest for p, digest in a["code"].items())
            checks[name]["raw_file_count"] = len(b["raw"])
            if name == "production":
                checks[name]["status_unchanged"] = a["status"] == b["status"]
        for name in ("task8", "task9"):
            checks[name + "_unchanged"] = before[name] == value[name]
        passed = all(v for row in checks.values() if isinstance(row, dict)
                     for v in row.values() if isinstance(v, bool))
        passed = passed and checks["task8_unchanged"] and checks["task9_unchanged"]
        checks["all_passed"] = passed
        write_json(OUT / "checks/boundary_verification.json", checks)
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        if not passed:
            raise AssertionError("Protected boundary changed")
    else:
        print(json.dumps(dict(branch=value["target"]["branch"],
                              raw_files=len(value["target"]["raw"]),
                              task8_files=len(value["task8"]),
                              cloud=value["cloud_parent_accessible"])))


if __name__ == "__main__":
    main()
