"""Activate the local data index, then run the migrated Research contracts."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> None:
    from dps_studio.research.task009_data import install
    install()
    import pytest
    arguments = sys.argv[1:]
    sys.argv = ["pytest"]  # Qt tests must not inherit this launcher's arguments.
    if not arguments:
        arguments = ["-q", "tests/unit/test_research_task008.py",
            "tests/unit/test_research_task008_baseline_audit.py", "tests/unit/test_task009_migration.py",
            "tests/unit/test_task009_figures.py", "-o",
            "cache_dir=artifacts/TASK-009/checks/pytest_task9_cache"]
    raise SystemExit(pytest.main(arguments))


if __name__ == "__main__":
    main()
