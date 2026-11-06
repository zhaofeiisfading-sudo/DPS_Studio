"""Dependency-free staged/tracked Git guard; never removes local files.

Use --tracked for a full current-tree audit. The repository-local pre-commit
hook invokes the default staged check. Deliberate -f additions are checked too.
"""
from __future__ import annotations

import argparse
from pathlib import PurePosixPath
import subprocess
import sys

LIMIT_BYTES = 2 * 1024 * 1024
BINARY_SUFFIXES = {".exe", ".dll", ".pyd", ".so", ".dylib", ".zip", ".7z", ".gz",
                   ".tar", ".whl", ".bundle", ".npy", ".npz", ".h5", ".hdf5", ".opju",
                   ".tif", ".tiff"}
GENERATED_DIRS = {"release", "build", "dist", "__pycache__", ".pytest_cache", ".ruff_cache",
                  ".mypy_cache", ".venv", "venv"}
LEGACY_DATA = {"docs/原始数据.csv", "docs/旧软件速度时间数据.csv"}


def violations(name: str, size: int) -> list[str]:
    path = PurePosixPath(name)
    reasons = []
    if set(path.parts) & GENERATED_DIRS:
        reasons.append("generated build/cache/environment directory")
    if path.suffix.lower() in BINARY_SUFFIXES:
        reasons.append("binary release or generated numeric/plotting artifact")
    if size > LIMIT_BYTES:
        reasons.append("object exceeds 2 MiB lightweight repository limit")
    if name.startswith("data/raw/") and path.name != ".gitkeep":
        reasons.append("raw acquisition data")
    if name in LEGACY_DATA or (name.startswith("data/reference/") and path.suffix == ".csv"):
        reasons.append("legacy generated/acquisition data; retain locally")
    if name.startswith("artifacts/"):
        parts = path.parts
        allowed = (len(parts) == 3 and parts[1] == "research_clean_task13"
                   and (path.suffix == ".md" or path.name == "__init__.py"))
        allowed |= (len(parts) == 4 and parts[1:3] == ("research_clean_task13", "repro")
                    and path.suffix in {".py", ".ps1", ".toml"})
        if not allowed:
            reasons.append("artifact output outside precise text/source allowlist")
    return reasons


def audit(*, tracked: bool = False) -> list[str]:
    args = ["git", "--no-optional-locks"]
    command = ["ls-files", "--stage", "-z"] if tracked else [
        "diff", "--cached", "--raw", "-z", "--diff-filter=ACMR", "--no-abbrev"]
    raw = subprocess.check_output(args + command)
    entries = []
    if tracked:
        for entry in raw.split(b"\0"):
            if entry:
                header, name = entry.split(b"\t", 1)
                entries.append((header.split()[1].decode(), name.decode("utf-8")))
    else:
        fields = raw.split(b"\0")
        i = 0
        while i < len(fields) - 1:
            header = fields[i].split()
            status = header[-1].decode()
            object_id = header[3].decode()
            name = fields[i + 1].decode("utf-8")
            if status.startswith(("R", "C")):
                name = fields[i + 2].decode("utf-8")
                i += 1
            entries.append((object_id, name))
            i += 2
    failures = []
    for object_id, name in entries:
        size = int(subprocess.check_output(args + ["cat-file", "-s", object_id]).strip())
        failures += [f"{name}: {reason} ({size} bytes)" for reason in violations(name, size)]
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracked", action="store_true")
    args = parser.parse_args()
    failures = audit(tracked=args.tracked)
    if failures:
        print("Git hygiene check rejected staged/tracked output:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Git hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
