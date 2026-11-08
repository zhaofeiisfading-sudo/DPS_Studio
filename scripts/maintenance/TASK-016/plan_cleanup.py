"""Create a read-only cleanup proposal from inspected tool/package evidence."""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def physical_files(folder: Path) -> list[Path]:
    files = []
    for current, directories, names in os.walk(folder, followlinks=False):
        for name in directories:
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"Cleanup candidate has a link: {path}")
        files += [Path(current) / name for name in names]
    return files


def archive_matches(folder: Path, archive: Path) -> dict[str, object]:
    checks = []
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if item.is_dir():
                continue
            relative = Path(item.filename)
            if relative.parts[0] == folder.name:
                relative = Path(*relative.parts[1:])
            local = folder / relative
            if not local.is_file():
                return {"matched": False, "missing": str(local)}
            with bundle.open(item) as stream:
                archived_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            with local.open("rb") as stream:
                local_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            if archived_hash != local_hash:
                return {"matched": False, "different": str(local)}
            checks.append(local.relative_to(folder).as_posix())
    extras = [path.relative_to(folder).as_posix() for path in physical_files(folder)
              if path.relative_to(folder).as_posix() not in checks]
    return {"matched": True, "members": len(checks), "extra_files": extras}


def main() -> None:
    candidates = []

    def add(folder: Path, reason: str, evidence: str) -> None:
        if not folder.exists():
            return
        files = physical_files(folder) if folder.is_dir() else [folder]
        if not folder.resolve().is_relative_to(ROOT) or folder.is_junction() or folder.is_symlink():
            raise ValueError(folder)
        candidates.append({"path": folder.relative_to(ROOT).as_posix(), "reason": reason,
                           "evidence": evidence, "bytes": sum(path.stat().st_size for path in files),
                           "files": len(files)})

    add(ROOT / "build", "rebuildable venvs, frozen install and test scratch",
        "task14-ci/task14-env pyvenv.cfg; installed onedir; named pytest fixture trees")
    for path in ROOT.iterdir():
        if path.is_dir() and path.name.startswith((".task", ".t11_", ".t28_", ".pytest_tmp")):
            add(path, "old pytest fixture outputs", "inspected test_* trees, source.csv fixtures and layout.ini")
    add(ROOT / "CodePython_ProjectsDPS_Studio_RESEARCH_CLEANartifactsresearch_clean_task15",
        "mistyped-path pytest cache", "only cache/pytest CACHEDIR.TAG, nodeids and lastfailed")
    for number in (11, 12):
        task = ROOT / f"artifacts/TASK-{number:03}"
        for path in task.iterdir():
            if not path.is_dir():
                continue
            if path.name.startswith("build"):
                toc = list(path.rglob("*.toc"))
                if toc:
                    add(path, "PyInstaller intermediate outputs", f"{len(toc)} .toc metadata files")
            elif path.name.startswith("tmp_"):
                add(path, "regenerable acceptance/test fixtures", "inspected pytest-generated test trees; final QA retained")
            elif path.name.startswith(("portable", "staging", "delivery")) or path.name in {
                "release_final", "superseded_axis_validation_package", "superseded_candidate_package",
                "superseded_initial_package",
            }:
                executables = list(path.rglob("*.exe"))
                if any("PDV" in p.name for p in executables):
                    add(path, "superseded/rebuildable onedir staging package",
                        "PyInstaller _internal + PDV executable; existing final ZIP retained in release")
                elif not physical_files(path):
                    add(path, "empty staging directory", "no physical files")
    archive_checks = []
    for number, folder in ((12, ROOT / "release/PDV_Studio_Research_TASK012"),
                           (14, ROOT / "artifacts/TASK-014/portable/PDV_Studio_Research_TASK014")):
        archive = ROOT / f"release/TASK-{number:03}/PDV_Studio_Research_TASK{number:03}_Windows_x64.zip"
        result = archive_matches(folder, archive)
        archive_checks.append({"folder": str(folder), "archive": str(archive), **result})
        if result["matched"] and not result["extra_files"]:
            add(folder if number == 12 else folder.parent, "exact extracted copy of retained ZIP",
                f"all {result['members']} archive members SHA-256 identical; no extra files")
    for number in (15,):
        for name in ("cache", "tmp"):
            add(ROOT / f"artifacts/TASK-{number:03}/{name}", "tool cache / pytest fixtures",
                "run.ps1-configured Matplotlib/tool caches and named test outputs")
    report = {"candidates": candidates, "archive_checks": archive_checks}
    (ROOT / "artifacts/TASK-016/audit/cleanup-plan.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(candidates)} reviewed candidates; {sum(int(x['bytes']) for x in candidates)/2**30:.3f} GiB")
    print(json.dumps(archive_checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
