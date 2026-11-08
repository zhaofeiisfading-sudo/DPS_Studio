"""Rebase existing local Markdown links after the reviewed file migrations."""
from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    ledger = json.loads((ROOT / "docs/tasks/TASK-016/SOURCE_MIGRATION.json").read_text(encoding="utf-8"))
    files = ledger["files"]
    directories = ledger["directories"]
    changes = []
    for old, row in files.items():
        path = ROOT / row["target"]
        if path.suffix != ".md" or not path.is_file() or path.is_relative_to(ROOT / "docs/tasks/TASK-016"):
            continue
        text = path.read_text(encoding="utf-8")

        def replace(match: re.Match[str]) -> str:
            target = match[1]
            if ":" in target or target.startswith(("#", "/")):
                return match[0]
            address, separator, anchor = target.partition("#")
            if (path.parent / address).is_file():
                return match[0]
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(old), address))
            if relative in files:
                relative = files[relative]["target"]
            else:
                for source, destination in sorted(directories.items(), key=lambda pair: -len(pair[0])):
                    if relative.startswith(source + "/"):
                        relative = destination + relative[len(source):]
                        break
                if relative in files:
                    relative = files[relative]["target"]
            candidate = (ROOT / relative).resolve()
            if not candidate.is_relative_to(ROOT) or not candidate.exists():
                return match[0]
            updated = Path(os.path.relpath(candidate, path.parent)).as_posix()
            return match[0].replace(target, updated + separator + anchor)

        revised = re.sub(r"\]\(([^\s)]+)\)", replace, text)
        if revised != text:
            path.write_text(revised, encoding="utf-8")
            changes.append(path.relative_to(ROOT).as_posix())
    (ROOT / "artifacts/TASK-016/audit/document-link-repairs.json").write_text(
        json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rebased local links in {len(changes)} migrated documents")


if __name__ == "__main__":
    main()
