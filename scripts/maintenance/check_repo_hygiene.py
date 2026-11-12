"""Inventory root layout, generated files in Git, caches and large local files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath


ROOT_ITEMS = frozenset({
    ".agents", ".claude", ".codex", ".git", ".github", ".gitignore", ".vscode",
    "AGENTS.md", "README.md", "artifacts", "build", "configs", "data", "docs",
    "environment.yml", "logs", "notebooks", "outputs", "packaging", "pyproject.toml",
    "release", "resources", "results", "run_demo_pipeline.bat", "run_pdv_studio_gui.bat",
    "scripts", "src", "tests",
})
CACHES = frozenset({
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".hypothesis",
    ".pytest_tmp", ".venv", "venv", ".ipynb_checkpoints", ".cache",
})
GENERATED_ROOTS = frozenset({"artifacts", "build", "dist", "outputs", "release"})
RELEASE_ARCHIVE = re.compile(r"^(PDV[ _-]Studio.*|release_artifact)\.zip$", re.I)
RELEASE_EXECUTABLE = re.compile(r"^PDV_Studio_v.+_Windows_x64\.exe$", re.I)
LOCAL_DOC_DATA = frozenset({
    "docs/原始数据.csv", "docs/旧软件速度时间数据.csv",
    "docs/user_manual/PDV_Studio_用户使用说明书.html",
    "docs/user_manual/PDV_Studio_用户使用说明书.pdf",
})
INSTALLER_SUFFIXES = {".msi", ".msix", ".dmg", ".deb", ".rpm", ".appimage"}


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *arguments])


def _tracked_generated(path: PurePosixPath) -> bool:
    parts = path.parts
    return (
        parts[0] in GENERATED_ROOTS
        or path.as_posix() in LOCAL_DOC_DATA
        or (parts[:2] == ("docs", "user_manual") and len(parts) >= 3
            and parts[2].startswith("export_example"))
        or (parts[0] in {"logs", "results"} and parts[1:] != (".gitkeep",))
        or (
            parts[:2] in (("data", "raw"), ("data", "processed"))
            and parts[2:] != (".gitkeep",)
        )
        or any(part in CACHES or part.endswith(".egg-info") for part in parts)
        or path.suffix in {".pyc", ".pyo"}
        or _is_package(path)
    )


def _is_package(path: PurePosixPath) -> bool:
    return (bool(RELEASE_ARCHIVE.fullmatch(path.name) or RELEASE_EXECUTABLE.fullmatch(path.name))
            or path.suffix.lower() in INSTALLER_SUFFIXES)


def audit(root: Path, *, large_bytes: int) -> dict[str, list[str]]:
    """Read working files and the index, without changing either."""
    tracked = [
        PurePosixPath(name)
        for name in _git(root, "ls-files", "-z").decode("utf-8").split("\0")
        if name
    ]
    large: list[str] = []
    caches: list[str] = []
    packages: dict[int, list[Path]] = defaultdict(list)
    misplaced: list[str] = []
    raw: dict[int, list[Path]] = defaultdict(list)
    artifacts: list[tuple[int, Path]] = []
    for directory, subdirs, files in root.walk():
        for name in subdirs[:]:
            path = directory / name
            if name in CACHES or name.endswith(".egg-info"):
                caches.append(path.relative_to(root).as_posix())
                subdirs.remove(name)
            elif name == ".git" or path.is_junction() or path.is_symlink():
                subdirs.remove(name)
        for name in files:
            path = directory / name
            if path.is_symlink():
                continue
            relative = path.relative_to(root)
            size = path.stat().st_size
            if size >= large_bytes:
                large.append(relative.as_posix())
            if (_is_package(PurePosixPath(relative.as_posix()))
                    and (path.suffix.lower() != ".zip" or zipfile.is_zipfile(path))):
                packages[size].append(path)
                if relative.parts[0] != "release":
                    misplaced.append(relative.as_posix())
            if relative.parts[:2] == ("data", "raw") and name != ".gitkeep":
                raw[size].append(path)
            elif relative.parts[0] == "artifacts":
                artifacts.append((size, path))
    duplicates: list[str] = []
    for group in packages.values():
        if len(group) < 2:
            continue
        by_hash: dict[str, list[str]] = defaultdict(list)
        for path in group:
            by_hash[_digest(path)].append(path.relative_to(root).as_posix())
        duplicates.extend(" = ".join(sorted(paths)) for paths in by_hash.values() if len(paths) > 1)
    raw_hashes: dict[int, set[str]] = {}
    raw_copies: list[str] = []
    for size, path in artifacts:
        if size in raw:
            if size not in raw_hashes:
                raw_hashes[size] = {_digest(p) for p in raw[size]}
            if _digest(path) in raw_hashes[size]:
                raw_copies.append(path.relative_to(root).as_posix())
    return {
        "unexpected_root": sorted(
            path.name for path in root.iterdir()
            if path.name not in ROOT_ITEMS
        ),
        "tracked_generated": sorted(path.as_posix() for path in tracked if _tracked_generated(path)),
        "large_tracked": sorted(
            path.as_posix() for path in tracked
            if (root / path).is_file() and (root / path).stat().st_size >= large_bytes
        ),
        "caches": sorted(caches),
        "large_local": sorted(large),
        "misplaced_packages": sorted(misplaced),
        "duplicate_packages": sorted(duplicates),
        "raw_copies_in_artifacts": sorted(raw_copies),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--large-mib", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.large_mib < 1:
        parser.error("--large-mib must be positive")
    root = Path(__file__).resolve().parents[2]
    report = audit(root, large_bytes=args.large_mib * 1024**2)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for key, entries in report.items():
            print(f"{key}: {len(entries)}")
            for entry in entries:
                print(f"  {entry}")
    errors = ("unexpected_root", "tracked_generated", "misplaced_packages",
              "duplicate_packages", "raw_copies_in_artifacts")
    return int(args.strict and any(report[key] for key in errors))


if __name__ == "__main__":
    raise SystemExit(main())
