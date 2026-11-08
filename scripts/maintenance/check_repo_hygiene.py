"""Read-only layout, cache and Git-index audit. Exit 0=clean, 1=findings, 2=error."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

LIMIT_BYTES = 2 * 1024 * 1024
ROOT_DIRECTORIES = {
    ".git", ".github", ".githooks", ".agents", ".vscode", ".codex",
    "src", "scripts", "tests", "configs", "docs", "artifacts", "release", "data",
}
ROOT_FILES = {
    "AGENTS.md", "README.md", "pyproject.toml", "environment.yml", ".gitignore", ".git",
    ".gitattributes", ".editorconfig", ".python-version", ".pre-commit-config.yaml",
    "LICENSE", "LICENSE.md", "LICENSE.txt", "CHANGELOG.md", "SECURITY.md",
}
CACHE_NAMES = {
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".hypothesis",
    ".ipynb_checkpoints", ".cache", ".venv", "venv", "env", "pip-cache",
    ".tox", ".nox", ".eggs",
}
GENERATED_DIRECTORIES = {"artifacts", "release", "build", "dist", "outputs", "results", "logs"}
BINARY_SUFFIXES = {
    ".exe", ".dll", ".pyd", ".so", ".dylib", ".zip", ".7z", ".tar", ".gz",
    ".whl", ".bundle", ".npy", ".npz", ".h5", ".hdf5", ".opju", ".tif",
    ".tiff", ".pyc", ".pyo", ".mat", ".pkl", ".pickle", ".parquet", ".feather",
}


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    message: str


def git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(root), *args], input=input_data,
        stderr=subprocess.PIPE,
    )


def violations(name: str, size: int) -> list[str]:
    """Rules shared by the staged hook and full audit; no TASK allowlists."""
    path = PurePosixPath(name)
    reasons = []
    if path.parts[0] in GENERATED_DIRECTORIES or any(cache_component(part) for part in path.parts):
        reasons.append("generated output, cache or environment is indexed")
    if path.suffix.lower() in BINARY_SUFFIXES:
        reasons.append("generated binary/archive is indexed")
    if size > LIMIT_BYTES:
        reasons.append(f"indexed blob exceeds {LIMIT_BYTES // 1024**2} MiB ({size} bytes)")
    if name.startswith("data/raw/") and path.name != ".gitkeep":
        reasons.append("raw acquisition data is indexed")
    if path.suffix.lower() in {".csv", ".tsv", ".dat"} and not (
        name.startswith("tests/fixtures/") or name.startswith("docs/maintenance/")
    ):
        reasons.append("numeric data outside lightweight test fixtures/maintenance inventories")
    return reasons


def indexed_findings(root: Path, *, staged_only: bool = False) -> list[Finding]:
    staged = set(git(root, "diff", "--cached", "--name-only", "--no-renames",
                     "--diff-filter=ACMT", "-z").decode("utf-8").split("\0"))
    entries = []
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, oid, stage = header.decode("ascii").split()
        name = raw_name.decode("utf-8")
        if staged_only and name not in staged:
            continue
        entries.append((mode, oid, stage, name))
    if not entries:
        return []
    object_ids = list(dict.fromkeys(entry[1] for entry in entries))
    response = git(root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                   input_data=("\n".join(object_ids) + "\n").encode("ascii"))
    sizes = {}
    for row in response.decode("ascii").splitlines():
        oid, kind, size = row.split()
        sizes[oid] = int(size) if kind == "blob" else 0
    findings = []
    for mode, oid, stage, name in entries:
        scope = "staged" if name in staged else "tracked"
        if stage != "0":
            findings.append(Finding("unmerged", name, "unresolved Git index entry"))
        if mode == "160000":
            findings.append(Finding(scope, name, "submodule requires an explicit dependency review"))
        findings.extend(Finding(scope, name, reason) for reason in violations(name, sizes[oid]))
    return findings


def is_link(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
    )


def cache_component(name: str) -> bool:
    return name in CACHE_NAMES or name.lstrip(".").startswith(
        ("pytest_cache", "pytest_tmp", "mypy_cache", "ruff_cache", "pip_cache", "pip-cache"),
    )


def managed_temporary(parts: tuple[str, ...]) -> bool:
    return len(parts) >= 3 and parts[0] == "artifacts" and parts[2] == "tmp"


def layout_findings(root: Path) -> list[Finding]:
    findings = []
    for path in sorted(root.iterdir()):
        allowed = ROOT_DIRECTORIES if path.is_dir() else ROOT_FILES
        if path.name not in allowed:
            findings.append(Finding("root", path.name, "unexpected root entry; classify using AGENTS.md"))
        elif is_link(path) and path.name != ".git":
            findings.append(Finding("link", path.name, "root entry is a link; inspect its actual owner"))
    def scan_error(error: OSError) -> None:
        raise error

    for current, directories, files in os.walk(root, followlinks=False, onerror=scan_error):
        folder = Path(current)
        for name in directories[:]:
            path = folder / name
            parts = path.relative_to(root).parts
            if is_link(path) or parts[0] in {".git", "release"} or managed_temporary(parts):
                directories.remove(name)
            elif cache_component(name) or name.endswith(".egg-info"):
                findings.append(Finding("cache", path.relative_to(root).as_posix(),
                                        "cache/environment outside artifacts/<task>/tmp"))
                directories.remove(name)
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                path = folder / name
                if not managed_temporary(path.relative_to(root).parts):
                    findings.append(Finding("cache", path.relative_to(root).as_posix(),
                                            "Python bytecode outside managed temporary directory"))
    return findings


def audit(root: Path, *, staged_only: bool = False) -> list[Finding]:
    return ([] if staged_only else layout_findings(root)) + indexed_findings(
        root, staged_only=staged_only,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--staged-only", action="store_true", help="Only inspect changed index blobs")
    parser.add_argument("--json", action="store_true", help="JSON on stdout; no report file is written")
    args = parser.parse_args()
    try:
        root = Path(git(args.root.resolve(), "rev-parse", "--show-toplevel").decode().strip())
        findings = audit(root, staged_only=args.staged_only)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Repository hygiene audit failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": str(root), "read_only": True,
                          "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"[{item.kind}] {item.path}: {item.message}", file=sys.stderr)
        print(f"Repository hygiene: {len(findings)} finding(s)", file=sys.stderr)
    else:
        print("Repository hygiene: clean (read-only audit)")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
