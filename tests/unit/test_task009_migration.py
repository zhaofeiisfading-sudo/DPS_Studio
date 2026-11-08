"""Migration contracts: no alias, old-worktree access or frozen-byte changes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dps_studio.research import task009_runtime as runtime


def test_frozen_package_is_physical_local_directory() -> None:
    runtime.assert_local()
    assert runtime.TASK8.resolve().is_relative_to(runtime.ROOT)
    assert (runtime.ROOT / "pyproject.toml").is_file()


@pytest.mark.parametrize("event", ["open", "os.listdir", "os.scandir"])
def test_old_worktree_guard_blocks_even_historical_source(event: str) -> None:
    with pytest.raises(RuntimeError, match="old-worktree access denied"):
        runtime.source_guard(event, (str(runtime.OLD_ROOT/"src/dps_studio/__init__.py"),))


def test_target_protocol_is_allowed_and_has_fixed_counts() -> None:
    runtime.source_guard("open", (str(runtime.PROTOCOL),))
    text = runtime.PROTOCOL.read_text(encoding="utf-8")
    assert "96" in text and "50" in text


def test_original_algorithms_and_test_sources_match_frozen_fingerprints() -> None:
    from dps_studio.research.source_records import frozen_source_matches
    frozen = json.loads((runtime.ROOT/"docs/tasks/TASK-008/provenance/source_freeze.json").read_text(encoding="utf-8"))
    assert frozen
    for path, digest in frozen.items():
        assert frozen_source_matches(runtime.ROOT, path, digest), path


def test_excluded_scratch_does_not_include_frozen_results() -> None:
    from scripts.research.task009.migrate import disposition
    assert disposition("varpro/runs/fresh/fresh_step_00/trajectory.npz")[0]
    assert disposition("development_sources00/common.py")[0]
    assert disposition("checks/reproduction_smoke/replay_comparison.json")[0]
    assert not disposition("checks/temp_final/fixture.csv")[0]


def test_runtime_sources_resolve_inside_target() -> None:
    value = runtime.provenance()
    for key in ("dps_studio_source", "algorithm_common_source"):
        assert Path(value[key]).is_relative_to(runtime.ROOT)


def test_index_contains_every_frozen_raw_and_all_seventeen_streams() -> None:
    from dps_studio.research.task009_data import inventory
    records = [r for r in inventory() if r["kind"] == "RAW"]
    assert len(records) == 13
    assert sum(r["channels"] for r in records) == 17
    assert sum(r["action"].startswith("COPIED") for r in records) == 3
