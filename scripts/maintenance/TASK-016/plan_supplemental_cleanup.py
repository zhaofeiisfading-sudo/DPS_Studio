"""Propose byte-proven array deduplication and reviewed residual tool caches."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    candidates = []

    def cache(path: Path, reason: str) -> None:
        if not path.is_dir():
            return
        if path.is_junction() or path.is_symlink():
            raise ValueError(path)
        files = [p for p in path.rglob("*") if p.is_file()]
        candidates.append({"path": path.relative_to(ROOT).as_posix(), "files": len(files),
                           "bytes": sum(p.stat().st_size for p in files), "reason": reason,
                           "evidence": "tool cache or inspected named pytest fixture tree"})

    for folder in ("src", "scripts", "tests"):
        for current, directories, names in os.walk(ROOT / folder, followlinks=False):
            for name in directories[:]:
                path = Path(current) / name
                if path.is_junction() or path.is_symlink():
                    directories.remove(name)
                elif name == "__pycache__":
                    files = [p for p in path.rglob("*") if p.is_file()]
                    if all(p.suffix == ".pyc" for p in files):
                        cache(path, "Python bytecode only")
                    directories.remove(name)
    for number in (9, 10, 11):
        checks = ROOT / f"artifacts/TASK-{number:03}/checks"
        for path in checks.iterdir():
            if path.is_dir() and (path.name.startswith(("pytest_", "mypy_cache", "core_compat_tmp", "new_final_tmp"))):
                cache(path, "historical tool cache / pytest fixtures; final check reports retained")
    reference = ROOT / "artifacts/TASK-011/checks/real_reference_v2"
    for folder in (ROOT / "artifacts/TASK-011/checks/real_reference",
                   ROOT / "artifacts/TASK-011/checks/real_current",
                   ROOT / "artifacts/TASK-012/numerical_current"):
        for path in sorted(folder.glob("*.npz")):
            keep = reference / path.name
            if not keep.is_file() or keep.stat().st_size != path.stat().st_size:
                continue
            with path.open("rb") as source, keep.open("rb") as target:
                checksum = hashlib.file_digest(source, "sha256").hexdigest()
                identical = checksum == hashlib.file_digest(target, "sha256").hexdigest()
            if identical:
                candidates.append({"path": path.relative_to(ROOT).as_posix(), "files": 1,
                                   "bytes": path.stat().st_size, "keep": keep.relative_to(ROOT).as_posix(),
                                   "sha256": checksum, "reason": "byte-identical numerical regression array",
                                   "evidence": "SHA-256 equality; reference array and each original report.json retained"})
    destination = ROOT / "artifacts/TASK-016/audit/cleanup-supplement-plan.json"
    destination.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(candidates)} supplementary candidates; {sum(row['bytes'] for row in candidates)/2**30:.3f} GiB")


if __name__ == "__main__":
    main()
