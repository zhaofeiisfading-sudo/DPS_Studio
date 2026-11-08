"""Bring owning Production regression contracts alongside migrated modules."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = ROOT.parent / "DPS_Studio"
ARTIFACT = ROOT / "artifacts/TASK-011"
CORE_TESTS = (
    "test_acceleration.py", "test_local_acceleration.py", "test_acceleration_export.py",
    "test_velocity_corrections.py", "test_window_presets.py", "test_window_length_diagnostics.py",
    "test_manual_frequency_region.py", "test_runtime_paths.py", "test_task016r6_working_results.py",
    "test_production_feedback_audit.py", "test_workflow_analysis.py", "test_workflow_config.py",
    "test_formal_result_export.py", "test_analysis_run_parameters.py", "test_display_velocity.py",
    "test_ridge_spectral_quality.py", "test_signal_detection.py", "test_task019a_time_and_postprocessing.py",
)


def main() -> None:
    selected = list((PRODUCTION / "tests/unit/gui").glob("test_*.py"))
    selected += [PRODUCTION / "tests/unit" / name for name in CORE_TESTS]
    manifest = []
    for source in selected:
        relative = source.relative_to(PRODUCTION)
        target = ROOT / relative
        raw = source.read_bytes()
        if target.exists() and target.read_bytes() == raw:
            continue
        previous_sha = None
        if target.exists():
            previous_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            backup = ARTIFACT / "pre_migration" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                raise FileExistsError(backup)
            shutil.copyfile(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest.append(dict(path=relative.as_posix(), previous_sha256=previous_sha,
                             production_sha256=hashlib.sha256(raw).hexdigest()))
    with (ARTIFACT / "test_migration_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(f"Migrated {len(manifest)} owning regression files with original backups")


if __name__ == "__main__":
    main()
