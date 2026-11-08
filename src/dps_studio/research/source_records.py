"""Resolve preserved historical records through an explicit source-migration ledger.

The ledger records both original and migrated hashes. Historical expectations
that were already false before a move remain false; this never rewrites them.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def ledger(root: Path) -> dict[str, Any]:
    path = root / "docs/tasks/TASK-016/SOURCE_MIGRATION.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Source-migration ledger must contain a JSON object")
    return value


def relocated_path(root: Path, relative: str) -> Path:
    records = ledger(root)
    entry = records["files"].get(relative)
    if entry:
        relative = entry["target"]
    else:
        for old, new in sorted(records["directories"].items(), key=lambda pair: -len(pair[0])):
            if relative == old or relative.startswith(old + "/"):
                relative = new + relative[len(old):]
                break
        entry = records["files"].get(relative)
        if entry:
            relative = entry["target"]
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Historical record escapes the repository")
    return result


def frozen_source_matches(root: Path, relative: str, expected: str) -> bool:
    records = ledger(root)
    entry = records["files"].get(relative)
    path = relocated_path(root, relative)
    if not path.is_file():
        return False
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if entry:
        return bool(entry["before_sha256"] == expected and entry["after_sha256"] == actual)
    return actual == expected
