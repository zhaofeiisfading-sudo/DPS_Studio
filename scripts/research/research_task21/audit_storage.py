"""Read-only classification of TASK-019 quarantine and historical archives."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parents[3]
TASK19 = ROOT / "artifacts/research_TASK19"
QUARANTINE = TASK19 / "quarantine"
PACKAGE = re.compile(r"^(PDV_Studio.*|release_artifact)\.zip$", re.I)


def digest(stream: IO[bytes]) -> str:
    sha = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        sha.update(chunk)
    return sha.hexdigest()


def hash_path(path: Path) -> str:
    with path.open("rb") as handle:
        return digest(handle)


def files(path: Path) -> list[Path]:
    result: list[Path] = []
    for folder, dirs, names in path.walk():
        dirs[:] = [d for d in dirs if not (folder / d).is_junction()
                   and not (folder / d).is_symlink()]
        result.extend(folder / n for n in names if not (folder / n).is_symlink())
    return sorted(result)


def tree_matches_archive(tree: Path, archive: Path) -> bool:
    if not archive.is_file():
        return False
    with zipfile.ZipFile(archive) as packed:
        contents = {n for n in packed.namelist() if not n.endswith("/")}
        local = {f"{tree.name}/{p.relative_to(tree).as_posix()}": p for p in files(tree)}
        if set(local) != contents:
            return False
        for name, path in local.items():
            with packed.open(name) as stream:
                if digest(stream) != hash_path(path):
                    return False
    return True


def allocation(path: Path) -> int:
    """Allocated bytes of a single-link file, excluding directory metadata."""
    info = path.stat()
    if info.st_nlink != 1:
        return 0
    if sys.platform != "win32":
        return int(getattr(info, "st_blocks", 0)) * 512

    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileStandardInfo(ctypes.Structure):
        _fields_ = [
            ("allocation_size", ctypes.c_longlong), ("end_of_file", ctypes.c_longlong),
            ("links", wintypes.DWORD), ("delete_pending", ctypes.c_ubyte),
            ("directory", ctypes.c_ubyte),
        ]

    standard = FileStandardInfo()
    query = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    with path.open("rb") as stream:
        handle = msvcrt.get_osfhandle(stream.fileno())
        if not query(handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)):
            raise ctypes.WinError(ctypes.get_last_error())
    return int(standard.allocation_size)


def inspect_storage() -> dict[str, object]:
    manifest = json.loads((TASK19 / "checks/cleanup_manifest.json").read_text("utf-8-sig"))
    decisions: dict[str, dict[str, object]] = {}
    covered: set[Path] = set()
    for name, entry in manifest.items():
        path = QUARANTINE / name
        local = files(path) if path.is_dir() else ([path] if path.is_file() else [])
        if not local:
            continue
        covered.update(local)
        reason = entry["reason"]
        size = sum(p.stat().st_size for p in local)
        matched = len(local) == entry["files"] and size == entry["bytes"]
        if reason.startswith("Byte-identical to "):
            other = ROOT / reason.removeprefix("Byte-identical to ")
            safe = matched and other.is_file() and hash_path(path) == hash_path(other)
        elif reason.startswith("Every file has byte-identical counterpart in "):
            other = ROOT / reason.split(" in ", 1)[1]
            archive = other.with_name(other.name + ".zip")
            if not tree_matches_archive(path, archive):
                # The v0.1.4 TASK-030 candidate differs from the final ZIP.
                archive = ROOT / "build/task030_release_v014" / archive.name
            safe = matched and tree_matches_archive(path, archive)
            reason = f"Member set and SHA-256 comparison with {archive.relative_to(ROOT).as_posix()}"
        elif reason == "Python or tool cache":
            safe = matched and (
                path.name in {".pytest_cache", ".mypy_cache", ".ruff_cache"}
                or (path.name == "__pycache__" and all(p.suffix == ".pyc" for p in local))
            )
        else:
            safe = matched and reason.startswith("PyInstaller intermediate")
        decisions[path.relative_to(ROOT).as_posix()] = {
            "safe": safe, "reason": reason, "bytes": size,
            "allocated_bytes": sum(allocation(p) for p in local), "files": len(local),
        }
    unexpected = [p.relative_to(ROOT).as_posix() for p in files(QUARANTINE) if p not in covered]
    packages: dict[str, list[str]] = defaultdict(list)
    inventory = {}
    for name in ("artifacts", "build", "dist", "release", "outputs", "logs", "results"):
        paths = files(ROOT / name)
        inventory[name] = {"files": len(paths), "bytes": sum(p.stat().st_size for p in paths)}
        for p in paths:
            if PACKAGE.fullmatch(p.name) and zipfile.is_zipfile(p):
                packages[hash_path(p)].append(p.relative_to(ROOT).as_posix())
    return {
        "quarantine": decisions, "unexpected_quarantine_files": unexpected,
        "archives_by_sha256": dict(packages), "inventory": inventory,
        "volume_free_bytes": shutil.disk_usage(ROOT).free,
    }


if __name__ == "__main__":
    # Keep scans read-only; the caller chooses where to save the JSON.
    print(json.dumps(inspect_storage(), ensure_ascii=True, indent=2))
