"""Block accidental binaries even if explicitly force-added, retain source specs."""
from __future__ import annotations

import pytest

from scripts.check_git_hygiene import LIMIT_BYTES, violations


@pytest.mark.parametrize("name", [
    "release/PDV_Studio/a.exe", "release/notes.md", "dist/file.txt", "build/generated.c",
    "random.dll", "result.npz", "backup.bundle", "figures/huge.png",
    "artifacts/research_clean_task13/figures/a.png", "data/raw/wave.csv",
    "docs/原始数据.csv", "data/reference/legacy(旧软件参考速度)/legacy_velocity_time.csv",
])
def test_generated_or_oversized_objects_are_rejected(name: str) -> None:
    assert violations(name, LIMIT_BYTES + 1 if name == "figures/huge.png" else 100)


@pytest.mark.parametrize("name", [
    "packaging/pdv_research_task012.spec", "configs/research/task028_final_method.json",
    "scripts/build_task012.ps1", "src/dps_studio/gui/icons/pdv_studio.ico",
    "artifacts/research_clean_task13/README.md",
    "artifacts/research_clean_task13/repro/stage.py", "tests/unit/test_task013_stage.py",
])
def test_maintained_sources_and_precise_artifact_text_are_allowed(name: str) -> None:
    assert not violations(name, 100)
