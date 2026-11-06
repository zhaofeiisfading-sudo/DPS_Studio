"""Block accidental binaries even if explicitly force-added, retain source specs."""
from __future__ import annotations

import pytest
from pathlib import Path
import subprocess
import sys

from scripts.check_git_hygiene import LIMIT_BYTES, violations


@pytest.mark.parametrize("name", [
    "release/PDV_Studio/a.exe", "release/notes.md", "dist/file.txt", "build/generated.c",
    "random.dll", "result.npz", "backup.bundle", "figures/huge.png",
    "artifacts/research_clean_task13/figures/a.png", "data/raw/wave.csv",
    "docs/原始数据.csv", "data/reference/legacy(旧软件参考速度)/legacy_velocity_time.csv",
    "new_results.csv", "docs/旧软件新参数.dat", "temporary.pyc",
])
def test_generated_or_oversized_objects_are_rejected(name: str) -> None:
    assert violations(name, LIMIT_BYTES + 1 if name == "figures/huge.png" else 100)


@pytest.mark.parametrize("name", [
    "packaging/pdv_research_task012.spec", "configs/research/task028_final_method.json",
    "scripts/build_task012.ps1", "src/dps_studio/gui/icons/pdv_studio.ico",
    "artifacts/research_clean_task13/README.md",
    "artifacts/research_clean_task13/repro/stage.py", "tests/unit/test_task013_stage.py",
    "artifacts/research_clean_task8/dechirp/implementation.py",
    "artifacts/research_clean_task9/data_index.json",
    "artifacts/research_clean_task10/experiment.py",
    "artifacts/research_clean_task12/VALIDATION.md",
    "docs/maintenance/artifact_keep_manifest.csv", "tests/fixtures/test.csv",
])
def test_maintained_sources_and_precise_artifact_text_are_allowed(name: str) -> None:
    assert not violations(name, 100)


def test_forced_staged_binary_is_rejected_without_deleting_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    release = tmp_path / "release"
    release.mkdir()
    package = release / "test.bin"
    package.write_bytes(b"local package stays here")
    subprocess.run(["git", "add", "-f", "--", "release/test.bin"], cwd=tmp_path,
                   check=True, capture_output=True)
    script = Path(__file__).resolve().parents[2] / "scripts/check_git_hygiene.py"
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True,
                            text=True)
    assert result.returncode == 1
    assert "release/test.bin" in result.stderr
    assert package.read_bytes() == b"local package stays here"
