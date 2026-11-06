"""Compare every bundled application code object against the delivered source."""
from __future__ import annotations

import argparse
import hashlib
import json
import types
from pathlib import Path
from typing import Any

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def normalize(value: Any) -> Any:
    if isinstance(value, types.CodeType):
        return value.replace(co_filename="<source>", co_consts=tuple(normalize(item) for item in value.co_consts))
    if isinstance(value, tuple):
        return tuple(normalize(item) for item in value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    archive = CArchiveReader(str(args.executable))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    rows = []
    for name in sorted(pyz.toc):
        if not name.startswith("dps_studio"):
            continue
        relative = Path(*name.split("."))
        path = ROOT / "src" / relative.with_suffix(".py")
        if not path.is_file():
            path = ROOT / "src" / relative / "__init__.py"
        actual = pyz.extract(name)
        expected = compile(path.read_bytes(), str(path), "exec", dont_inherit=True, optimize=0)
        rows.append({"module": name, "matches_source": normalize(actual) == normalize(expected)})
    passed = bool(rows) and all(row["matches_source"] for row in rows)
    args.output.write_text(json.dumps({"passed": passed, "modules": rows,
        "executable": str(args.executable.resolve()),
        "executable_sha256": hashlib.sha256(args.executable.read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    print(f"Bundled code parity: {sum(row['matches_source'] for row in rows)}/{len(rows)}")
    if not passed:
        print([row for row in rows if not row["matches_source"]])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
