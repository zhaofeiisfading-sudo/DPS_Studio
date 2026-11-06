"""Read PE import/export names to diagnose the portable Qt dependency closure."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pefile  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/research_clean_task11/portable/PDV_Studio_Research_TASK011/_internal"


def main() -> None:
    names = ["PySide6/QtCore.pyd", "PySide6/pyside6.abi3.dll", "PySide6/Qt6Core.dll",
             "shiboken6/shiboken6.abi3.dll", "icuuc.dll", "icudt78.dll"]
    reports: list[dict[str, Any]] = []
    for name in names:
        source = BUNDLE / name
        if not source.is_file():
            continue
        parsed = pefile.PE(str(source), max_symbol_exports=100_000)
        for dependency in getattr(parsed, "DIRECTORY_ENTRY_IMPORT", []):
            dll = dependency.dll.decode()
            candidates = [source.parent / dll, BUNDLE / dll, BUNDLE / "PySide6" / dll,
                          BUNDLE / "shiboken6" / dll, Path(os.environ["SystemRoot"]) / "System32" / dll]
            target = next((path for path in candidates if path.is_file()), None)
            if target is None:
                reports.append({"source": name, "dependency": dll, "missing_file": True})
                continue
            table = getattr(pefile.PE(str(target), max_symbol_exports=100_000),
                            "DIRECTORY_ENTRY_EXPORT", None)
            exports = {symbol.name for symbol in table.symbols} if table else set()
            missing = [symbol.name.decode() for symbol in dependency.imports
                       if symbol.name and symbol.name not in exports]
            if missing:
                reports.append({"source": name, "dependency": dll, "target": str(target),
                                "missing_symbols": missing})
    destination = ROOT / "artifacts/research_clean_task11/checks/dll_audit_v2.json"
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(reports, handle, indent=2)
    print(json.dumps([{"source": row["source"], "dependency": row["dependency"],
                      "missing_symbol_count": len(row.get("missing_symbols", []))}
                     for row in reports], indent=2))


if __name__ == "__main__":
    main()
