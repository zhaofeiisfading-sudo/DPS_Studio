"""Selective local migration with preimage backups and SHA provenance."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT.parent / "DPS_Studio"
ARTIFACT = ROOT / "artifacts/research_clean_task11"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not (ARTIFACT / "boundary_before.json").is_file():
        raise RuntimeError("Complete boundary snapshot before migration")
    manifest = []
    # Resume after a failed copy without replacing backups or losing provenance.
    reference_root = ARTIFACT / "production_reference"
    if reference_root.exists():
        for reference in reference_root.rglob("*"):
            if reference.is_file():
                relative = reference.relative_to(reference_root)
                previous = ARTIFACT / "pre_migration" / relative
                manifest.append(dict(path=relative.as_posix(), source_sha256=sha(reference),
                                     previous_sha256=sha(previous) if previous.exists() else None))
    selected = [path for part in ("core", "gui")
                for path in (PRODUCTION / "src/dps_studio" / part).rglob("*")
                if path.is_file() and "__pycache__" not in path.parts]
    selected += [PRODUCTION / "src/dps_studio/runtime_paths.py",
                 PRODUCTION / "configs/pdv_studio_defaults.toml"]
    # Preserve every original Research file; migrate only shared runtime layers.
    # No research/, data/, artifact/, launchers, Git or release trees are copied.
    for source in selected:
        relative = source.relative_to(PRODUCTION)
        target = ROOT / relative
        source_sha = sha(source)
        old_sha = sha(target) if target.exists() else None
        if old_sha == source_sha:
            continue
        if target.exists():
            backup = ARTIFACT / "pre_migration" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                raise FileExistsError(backup)
            shutil.copyfile(target, backup)
        # A reference copy is validation evidence, never an application import path.
        reference = ARTIFACT / "production_reference" / relative
        reference.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, reference)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest.append(dict(path=relative.as_posix(), source_sha256=source_sha,
                             previous_sha256=old_sha))
    # Ship the small frozen runtime subset instead of importing artifacts at runtime.
    origin = ROOT / "artifacts/research_clean_task8"
    destination = ROOT / "src/dps_studio/algorithms/task008"
    for frozen_name in ["__init__.py", "common.py", *[f"{name}/{file}"
            for name in ("dechirp", "varpro", "clutter_varpro")
            for file in ("__init__.py", "implementation.py")]]:
        source, target = origin / frozen_name, destination / frozen_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            if target.exists() and sha(target) != sha(source):
                raise FileExistsError(target)
            if not target.exists():
                shutil.copyfile(source, target)
        elif not target.exists() and source.name == "__init__.py":
            target.write_text('"""Local frozen algorithm package."""\n', encoding="utf-8")
        else:
            raise FileNotFoundError(source)
        manifest.append(dict(path=target.relative_to(ROOT).as_posix(),
                             source=source.relative_to(ROOT).as_posix(),
                             source_sha256=sha(source) if source.exists() else "generated package marker"))
    with (ARTIFACT / "migration_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print(f"Migrated {len(manifest)} changed/new runtime files, all preimages preserved")


if __name__ == "__main__":
    main()
