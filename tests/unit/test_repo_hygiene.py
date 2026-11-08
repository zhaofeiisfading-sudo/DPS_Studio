"""Exercise real Git blobs, read-only behavior, cache routing and build inputs."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from scripts.build.check_build_inputs import DEFAULT_SPEC, validate_spec
from scripts.maintenance.check_repo_hygiene import LIMIT_BYTES, audit, violations
from dps_studio.research.source_records import frozen_source_matches, relocated_path


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("answer = 42\n", encoding="utf-8")
    git(tmp_path, "add", "src/app.py")
    return tmp_path


@pytest.mark.parametrize("name", ["artifacts/TASK-999/README.md", "release/result.unknown"])
def test_force_added_outputs_are_reported_and_local_content_is_preserved(
    repository: Path, name: str,
) -> None:
    path = repository / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unique local result")
    (repository / ".gitignore").write_text("/artifacts/\n/release/\n", encoding="utf-8")
    git(repository, "add", "-f", name)
    before = (repository / ".git/index").read_bytes()
    result = audit(repository, staged_only=True)
    assert any(item.path == name and item.kind == "staged" for item in result)
    assert path.read_bytes() == b"unique local result"
    assert (repository / ".git/index").read_bytes() == before


@pytest.mark.parametrize("remove_local", [False, True])
def test_large_indexed_blob_is_detected_when_worktree_is_small_or_missing(
    repository: Path, remove_local: bool,
) -> None:
    path = repository / "src/payload.png"
    path.write_bytes(b"\0" * (LIMIT_BYTES + 1))
    git(repository, "add", "src/payload.png")
    if remove_local:
        path.unlink()
    else:
        path.write_bytes(b"small replacement")
    result = audit(repository, staged_only=True)
    assert any(item.path == "src/payload.png" and "indexed blob exceeds" in item.message
               for item in result)


def test_clean_audit_changes_no_file_or_index(repository: Path) -> None:
    def hashes() -> dict[str, str]:
        return {str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in repository.rglob("*") if path.is_file()}
    before = hashes()
    assert not audit(repository)
    assert hashes() == before


def test_caches_are_allowed_only_under_managed_task_tmp(repository: Path) -> None:
    proper = repository / "artifacts/TASK-999/tmp/venv/__pycache__"
    proper.mkdir(parents=True)
    (proper / "sample.pyc").write_bytes(b"temporary")
    assert not audit(repository)
    stray = repository / "src/__pycache__"
    stray.mkdir()
    (stray / "sample.pyc").write_bytes(b"stray")
    assert any(item.kind == "cache" and item.path == "src/__pycache__" for item in audit(repository))


def test_untracking_preserves_local_unique_result(repository: Path) -> None:
    folder = repository / "artifacts"
    folder.mkdir()
    path = folder / "result.txt"
    path.write_text("preserve", encoding="utf-8")
    git(repository, "add", "artifacts/result.txt")
    git(repository, "rm", "--cached", "artifacts/result.txt")
    assert not audit(repository)
    assert path.read_text(encoding="utf-8") == "preserve"


def test_unicode_and_space_index_paths_are_read_correctly(repository: Path) -> None:
    path = repository / "src/中文 脚本.py"
    path.write_text("value = 1\n", encoding="utf-8")
    git(repository, "add", "src/中文 脚本.py")
    assert not audit(repository)


def test_build_validation_resolves_resources_and_dynamic_algorithms_without_building() -> None:
    result = validate_spec(DEFAULT_SPEC)
    assert result["built"] is False
    assert all(Path(name).is_file() for name in result["resources"])
    assert any(name.endswith(".ico") for name in result["resources"])
    assert any(name.endswith(".qm") for name in result["resources"])
    assert "dps_studio.algorithms.waveform.varpro.implementation" in result["hidden_imports"]
    assert not violations("src/dps_studio/gui/icons/pdv_studio.ico", 100)
    assert not violations("src/dps_studio/gui/translations/pdv_studio_en.qm", 100)


def test_migration_lineage_rejects_tampering_and_unmatched_historical_hash(tmp_path: Path) -> None:
    import json
    target = tmp_path / "new.py"
    target.write_bytes(b"migrated source")
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = tmp_path / "docs/tasks/TASK-016/SOURCE_MIGRATION.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"directories": {}, "files": {
        "old.py": {"target": "new.py", "before_sha256": "original", "after_sha256": checksum},
    }}), encoding="utf-8")
    assert frozen_source_matches(tmp_path, "old.py", "original")
    assert not frozen_source_matches(tmp_path, "old.py", "pre-existing mismatch")
    target.write_bytes(b"changed after migration")
    assert not frozen_source_matches(tmp_path, "old.py", "original")


def test_historical_directory_and_deduplicated_file_resolve_to_preserved_bytes(tmp_path: Path) -> None:
    import json
    keep = tmp_path / "kept/result.npz"
    keep.parent.mkdir()
    keep.write_bytes(b"unique frozen numerical result")
    checksum = hashlib.sha256(keep.read_bytes()).hexdigest()
    manifest = tmp_path / "docs/tasks/TASK-016/SOURCE_MIGRATION.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"directories": {"old_artifacts": "artifacts"}, "files": {
        "artifacts/duplicate/result.npz": {"target": "kept/result.npz", "before_sha256": checksum,
                                          "after_sha256": checksum},
    }}), encoding="utf-8")
    assert relocated_path(tmp_path, "old_artifacts/duplicate/result.npz") == keep
    assert frozen_source_matches(tmp_path, "old_artifacts/duplicate/result.npz", checksum)
    with pytest.raises(ValueError, match="escapes"):
        relocated_path(tmp_path, "../outside.npz")
