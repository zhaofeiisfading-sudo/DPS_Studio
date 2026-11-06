"""Read-only boundary inventory. Write each snapshot exclusively."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PRODUCTION = ROOT.parent / "DPS_Studio"


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args],
                                   encoding="utf-8", errors="replace")


def state(root: Path) -> dict[str, Any]:
    status = git(root, "status", "--porcelain=v1", "-z").split("\0")
    return {"head": git(root, "rev-parse", "HEAD").strip(),
            "branch": git(root, "branch", "--show-current").strip(),
            "status": [s for s in status if s],
            "status_counts": dict(Counter(s[:2] for s in status if s)),
            "index": sha(Path(git(root, "rev-parse", "--path-format=absolute",
                                  "--git-path", "index").strip()))}


def code_hashes(root: Path) -> dict[str, str]:
    files = [p for folder in ("src", "scripts", "tests", "configs", "tools")
             for p in (root / folder).rglob("*") if p.is_file()
             and "__pycache__" not in p.parts]
    files += [p for p in root.iterdir() if p.is_file() and p.suffix in
              (".bat", ".toml", ".yml", ".md")]
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(files)}


def snapshot(label: str) -> None:
    data = {"research": state(ROOT), "research_code": code_hashes(ROOT),
            "raw": {p.relative_to(ROOT).as_posix(): sha(p)
                    for p in sorted((ROOT / "data/raw").rglob("*")) if p.is_file()},
            "production": state(PRODUCTION), "production_code": code_hashes(PRODUCTION)}
    with (OUT / f"boundary_{label}.json").open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"label": label, "research": data["research"]["status_counts"],
                      "production": data["production"]["status_counts"],
                      "research_files": len(data["research_code"]),
                      "production_files": len(data["production_code"]),
                      "raw_files": len(data["raw"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    snapshot(sys.argv[1])
