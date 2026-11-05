"""Research-only data relocation adapter. Never edits the frozen package/raw."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
INDEX = ROOT/"artifacts/research_clean_task9/data_index.json"


def inventory() -> list[dict[str, Any]]:
    value = json.loads(INDEX.read_text(encoding="utf-8"))
    result = []
    for original in value["records"]:
        row = dict(original)
        if row["kind"] == "RAW":
            local = (ROOT/row["local_path"]).resolve()
            if not local.is_relative_to(ROOT):
                raise RuntimeError("Indexed raw input escapes target")
            with local.open("rb") as handle:
                sha = hashlib.file_digest(handle, "sha256").hexdigest()
            if sha != row["sha256"]:
                raise RuntimeError(f"Indexed raw SHA256 mismatch: {local}")
        result.append(row)
    return result


def read_raw(row: dict[str, Any]) -> list[Any]:
    from artifacts.research_clean_task8.common import Signal
    records = json.loads(INDEX.read_text(encoding="utf-8"))["records"]
    item = next(r for r in records if r["path"] == row["path"] and r["kind"] == "RAW")
    path = ROOT/item["local_path"]
    x = np.loadtxt(path, delimiter=",", ndmin=2)
    return [Signal(np.array(x[:, 0]), np.array(x[:, c]), f"{Path(row['path']).stem}_ch{c}")
            for c in range(1, x.shape[1])]


def install() -> None:
    """Bind only Research data functions; physics/algorithms/parameters unchanged."""
    for name in ("data", "runner"):
        module = importlib.import_module(f"artifacts.research_clean_task8.{name}")
        setattr(module, "inventory", inventory)
        setattr(module, "read_raw", read_raw)
