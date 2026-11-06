"""Read-only inventories; exclusive writes only in the TASK-009 output tree."""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
if ROOT.name != "DPS_Studio_RESEARCH_CLEAN" or not OUT.is_relative_to(ROOT):
    raise RuntimeError("TASK-009 must be physically located in RESEARCH_CLEAN; junction access refused")
SOURCE = ROOT.parent/"DPS_Studio_TASK021A"
PRODUCTION = ROOT.parent/"DPS_Studio"
TASK8 = ROOT/"artifacts/research_clean_task8"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args],
                                   encoding="utf-8", errors="replace")


def state(root: Path) -> dict[str, Any]:
    status = [r for r in git(root, "status", "--porcelain=v1", "-z").split("\0") if r]
    index = Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").strip())
    return dict(head=git(root, "rev-parse", "HEAD").strip(),
                branch=git(root, "branch", "--show-current").strip(),
                status=status, status_counts=dict(Counter(r[:2] for r in status)),
                index_sha256=digest(index))


def inventory(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def code_inventory(root: Path) -> dict[str, str]:
    paths = [p for name in ("src", "scripts", "tests", "configs", "docs", "tools")
             for p in (root/name).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths += [p for p in root.iterdir() if p.is_file() and p.suffix in
              (".py", ".md", ".bat", ".toml", ".yml")]
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def snapshot(label: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for key, root in (("source", SOURCE), ("target", ROOT), ("production", PRODUCTION)):
        info[key] = dict(root=str(root), git=state(root), code=code_inventory(root),
                         raw=inventory(root/"data/raw"))
        if key != "production":
            info[key]["task8"] = inventory(root/"artifacts/research_clean_task8")
    write_json(OUT/f"boundary_{label}.json", info)
    print(json.dumps({k: dict(branch=v["git"]["branch"], status=v["git"]["status_counts"],
          code_files=len(v["code"]), raw_files=len(v["raw"]), task8_files=len(v.get("task8", {})))
          for k, v in info.items()}, ensure_ascii=False), flush=True)
    return info


if __name__ == "__main__":
    snapshot("before")
