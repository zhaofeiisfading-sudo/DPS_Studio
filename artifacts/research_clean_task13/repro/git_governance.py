"""TASK-013 local-only Git isolation and read-only boundary evidence.

Run with the existing dps-studio Python. No remote writes, deletions, checkout,
reset or cleanup. Original worktree registration in Production is left intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/research_clean_task13"
PRODUCTION = ROOT.parent / "DPS_Studio"
BRANCH = "codex/research_2/global-path-ridge-v2"
BASE = "26066704fbb924a1c70ef208d97ba81bc70407a0"
ORIGINAL = "b8faed27ad63cfd19a7acfb657d6afddc149a98f"


def git(*args: str, git_dir: Path | None = None) -> bytes:
    command = ["git", "--no-optional-locks"]
    if git_dir is not None:
        command += [f"--git-dir={git_dir}"]
    result = subprocess.run(command + list(args), cwd=ROOT, check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(root: Path, *, skip: set[str] | None = None,
             metadata_only: bool = False) -> dict[str, Any]:
    """Hash regular files without traversing Windows junctions or symlinks."""
    entries: dict[str, Any] = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        kept = []
        for name in dirs:
            path = parent / name
            rel = path.relative_to(root).as_posix()
            if skip and rel in skip:
                continue
            if path.is_symlink() or path.is_junction():
                entries[rel] = {"link": os.readlink(path)}
            else:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            path = parent / name
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            entries[rel] = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns} \
                if metadata_only else {"bytes": stat.st_size, "sha256": sha(path)}
    return entries


def before() -> None:
    if not (ROOT / ".git").is_file():
        raise RuntimeError("Expected original linked worktree")
    backup = OUT / "git_backup"
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "original_gitlink.txt").write_bytes((ROOT / ".git").read_bytes())
    (backup / "original_gitignore.txt").write_bytes((ROOT / ".gitignore").read_bytes())
    status = git("status", "--porcelain=v1", "--untracked-files=all").decode()
    if status.strip():
        raise RuntimeError(f"Unexpected initial modifications: {status}")
    if git("rev-parse", "HEAD").decode().strip() != ORIGINAL:
        raise RuntimeError("HEAD drift")
    remote = git("ls-remote", "--heads", "origin").decode()
    if f"{BASE}\trefs/heads/{BRANCH}" not in remote:
        raise RuntimeError("Remote drift; inspect before proceeding")
    save(OUT / "checks/git_before.json", {
        "head": ORIGINAL, "branch": BRANCH, "status": status, "remote_heads": remote,
        "common_dir": git("rev-parse", "--git-common-dir").decode().strip(),
        "unpushed_commit": True,
        "source_only_changes": git("diff-tree", "--no-commit-id", "--name-only", "-r",
                                   ORIGINAL, "--", ".", ":!release").decode().splitlines(),
        "user_name": git("config", "user.name").decode().strip(),
        "user_email": git("config", "user.email").decode().strip(),
    })
    git("bundle", "create", str(backup / "unpushed_task012.bundle"), "HEAD", f"^{BASE}")
    git("bundle", "verify", str(backup / "unpushed_task012.bundle"))
    print("Backup bundle verified; hashing read-only boundaries", flush=True)
    snapshot()


def snapshot() -> None:
    started = time.perf_counter()
    production_skip = {"artifacts", "build", "dist", ".mypy_cache", ".pytest_cache",
                       ".ruff_cache", ".git"}
    sections = {
        "raw": manifest(ROOT / "data/raw"),
        "release": manifest(ROOT / "release"),
        "production": manifest(PRODUCTION, skip=production_skip),
        "production_git": manifest(PRODUCTION / ".git"),
        "production_generated_inventory": {
            name: manifest(PRODUCTION / name, metadata_only=True)
            for name in sorted(production_skip - {".git"}) if (PRODUCTION / name).exists()
        },
        "prior_artifacts": {
            str(n): manifest(ROOT / f"artifacts/research_clean_task{n}", metadata_only=True)
            for n in (8, 9, 10, 11, 12)
        },
        "source": manifest(ROOT / "src"),
        "configs": manifest(ROOT / "configs"),
    }
    save(OUT / "checks/boundary_before.json", sections)
    print(json.dumps({"hash_seconds": time.perf_counter() - started,
                      "raw_files": len(sections["raw"]),
                      "production_files": len(sections["production"]),
                      "bundle_bytes": (OUT / "git_backup/unpushed_task012.bundle").stat().st_size}))


def isolate() -> None:
    backup = OUT / "git_backup"
    before_info = json.loads((OUT / "checks/git_before.json").read_text(encoding="utf-8"))
    if not (OUT / "checks/boundary_before.json").exists():
        raise RuntimeError("Boundary evidence required")
    source = Path(before_info["common_dir"])
    seed = backup / "standalone_seed.git"
    if seed.exists() or not (ROOT / ".git").is_file():
        raise RuntimeError("Refusing to reuse metadata or overwrite independent repository")
    git("init", "--bare", str(seed))
    # Local file transport only. A shallow copy preserves the shared remote
    # ancestor without importing multi-GB legacy objects. upload-pack is read-only.
    git("fetch", "--depth=1", "--no-tags", "--no-auto-maintenance",
        "--no-write-fetch-head", source.as_uri(), f"{BASE}:refs/heads/{BRANCH}", git_dir=seed)
    git("symbolic-ref", "HEAD", f"refs/heads/{BRANCH}", git_dir=seed)
    for key, value in (
        ("core.bare", "false"), ("core.worktree", str(ROOT)), ("core.autocrlf", "true"),
        ("gc.auto", "0"), ("maintenance.auto", "false"),
        ("user.name", before_info["user_name"]), ("user.email", before_info["user_email"]),
        ("remote.origin.url", "https://github.com/zhaofeiisfading-sudo/DPS_Studio.git"),
        ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
        (f"branch.{BRANCH}.remote", "origin"),
        (f"branch.{BRANCH}.merge", f"refs/heads/{BRANCH}"),
    ):
        git("config", "--local", key, value, git_dir=seed)
    git("update-ref", f"refs/remotes/origin/{BRANCH}", BASE, git_dir=seed)
    git("read-tree", BASE, git_dir=seed)
    # Both moves stay inside the explicitly authorized Research directory.
    # The original link and source Git metadata remain recoverable and untouched.
    link = ROOT / ".git"
    if link.read_bytes() != (backup / "original_gitlink.txt").read_bytes():
        raise RuntimeError("Gitlink changed")
    link.rename(backup / "original_worktree.gitlink")
    seed.rename(ROOT / ".git")
    git("config", "--local", "--unset", "core.worktree")
    save(OUT / "checks/git_isolation.json", {
        "git_dir": git("rev-parse", "--absolute-git-dir").decode().strip(),
        "common_dir": git("rev-parse", "--git-common-dir").decode().strip(),
        "shallow": git("rev-parse", "--is-shallow-repository").decode().strip(),
        "base": BASE, "preserved_original_commit": ORIGINAL,
        "source_registration_untouched": True, "remote_write": False,
        "recovery": "Original gitlink + verified one-commit bundle; source refs retained.",
    })
    print("Research now has independent .git; no Production metadata writes performed")


def preserve_sources() -> None:
    info = json.loads((OUT / "checks/git_before.json").read_text(encoding="utf-8"))
    if (ROOT / ".git").is_file():
        raise RuntimeError("Must isolate Research metadata first")
    paths = info["source_only_changes"]
    for name in paths:
        path = ROOT / name
        if (not path.is_file() or path.stat().st_size > 1024 * 1024
                or path.suffix not in {".py", ".ps1", ".spec", ".svg"}):
            raise RuntimeError(f"Non-lightweight source in preservation list: {name}")
    original_source = json.loads((OUT / "checks/boundary_before.json").read_text(encoding="utf-8"))["source"]
    if manifest(ROOT / "src") != original_source:
        raise RuntimeError("Existing source bytes changed")
    git("add", "--", *paths)
    staged = git("diff", "--cached", "--name-only").decode().splitlines()
    if set(staged) != set(paths):
        raise RuntimeError("Unexpected staged paths")
    # Preserve existing TASK-012 bytes, including three pre-existing blank EOFs.
    # Do not turn this preservation step into an unrelated source cleanup.
    git("-c", "core.whitespace=-blank-at-eof", "diff", "--cached", "--check")
    git("commit", "-m", "Preserve TASK-012 source changes without generated release bundle")
    save(OUT / "checks/task012_source_preservation.json", {
        "old_commit": ORIGINAL, "new_commit": git("rev-parse", "HEAD").decode().strip(),
        "preserved_paths": paths, "source_sha256_unchanged": True,
        "release_tracked": git("ls-files", "release").decode().splitlines(),
    })
    print("Preserved all pending TASK-012 source changes in lightweight local commit")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("before", "snapshot", "isolate", "preserve"))
    args = parser.parse_args()
    {"before": before, "snapshot": snapshot, "isolate": isolate,
     "preserve": preserve_sources}[args.mode]()


if __name__ == "__main__":
    main()
