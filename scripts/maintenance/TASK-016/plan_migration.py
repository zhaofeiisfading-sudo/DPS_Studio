"""Generate TASK-016's reviewed file-move plan; no source files are changed."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MOVES: list[dict[str, str]] = []
DESTINATIONS: dict[str, Path] = {}
DUPLICATES: list[dict[str, str]] = []


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def move(source: Path, target: str, reason: str) -> None:
    old = source.relative_to(ROOT).as_posix()
    if target in DESTINATIONS:
        other = DESTINATIONS[target]
        if sha(source) != sha(other):
            raise ValueError(f"Different files target {target}: {old}, {other}")
        DUPLICATES.append({"source": old, "keep": target, "sha256": sha(source),
                           "reason": "byte-identical migrated source"})
        return
    if (ROOT / target).exists():
        raise FileExistsError(target)
    DESTINATIONS[target] = source
    MOVES.append({"source": old, "target": target, "sha256": sha(source), "reason": reason})


def main() -> None:
    for path in (ROOT / "src/dps_studio/algorithms/task008").rglob("*.py"):
        suffix = path.relative_to(ROOT / "src/dps_studio/algorithms/task008").as_posix()
        move(path, f"src/dps_studio/algorithms/waveform/{suffix}", "canonical waveform estimators")
    for n in range(8, 16):
        base = ROOT / f"artifacts/research_clean_task{n}"
        for path in sorted(base.glob("*.md")):
            move(path, f"docs/tasks/TASK-{n:03}/{path.name}", "task report/protocol")
        for path in sorted(base.glob("*.py")):
            if n == 13 and path.name == "__init__.py":
                continue  # Empty historical outer-package marker; repro owns its package.
            if n == 8:
                if path.name in {"common.py", "catalog.py", "__init__.py"}:
                    target = f"src/dps_studio/algorithms/waveform/{path.name}"
                else:
                    target = f"src/dps_studio/research/waveform/{path.name}"
            else:
                target = f"scripts/research/task{n:03}/{path.name}"
            move(path, target, "research execution/support code outside generated outputs")
        for path in sorted(base.glob("*.ps1")):
            move(path, f"scripts/research/task{n:03}/{path.name}", "historical execution script")
        for path in sorted(base.glob("*.spec")):
            move(path, f"scripts/build/archive/{path.name}", "historical build configuration")
        if n == 8:
            for path in sorted(base.glob("*/implementation.py")):
                move(path, f"src/dps_studio/algorithms/waveform/{path.parent.name}/{path.name}",
                     "canonical waveform estimator; unchanged numerical implementation")
            for path in sorted(base.glob("*/README.md")):
                move(path, f"docs/tasks/TASK-008/methods/{path.parent.name}/README.md", "method report")
            for name in ("source_freeze.json", "baseline_audit_registration.json"):
                move(base / name, f"docs/tasks/TASK-008/provenance/{name}", "immutable historical fingerprints")
        if n == 9:
            move(base / "data_index.json", "configs/research/task009_data_index.json", "read-only data manifest")
        if n == 10:
            move(base / "config.json", "configs/research/task010.json", "reproduction parameters")
        if n == 13:
            for path in sorted((base / "repro").glob("*")):
                if path.suffix in {".py", ".ps1", ".toml"}:
                    move(path, f"scripts/research/task013/{path.name}", "independent research reproduction")
    for name, target in {
        "COMPARISON.md": "docs/tasks/TASK-008/COMPARISON.md",
        "FIGURE_INDEX.md": "docs/tasks/TASK-009/ROOT_FIGURE_INDEX.md",
        "MIGRATION_REPORT.md": "docs/tasks/TASK-009/ROOT_MIGRATION_REPORT.md",
        "RESEARCH_WORKTREE.md": "docs/development/RESEARCH_WORKTREE.md",
    }.items():
        move(ROOT / name, target, "root documentation belongs under docs")
    for path in (ROOT / "docs").glob("*"):
        if not path.is_file():
            continue
        match = re.match(r"(TASK-\d+[A-Z0-9-]*)_", path.name)
        if match:
            target = f"docs/tasks/inherited/{match[1]}/{path.name}"
        elif path.suffix in {".csv", ".dat"}:
            target = f"data/reference/legacy_docs/{path.name}"
        elif path.suffix == ".png":
            target = f"docs/reference/figures/{path.name}"
        else:
            target = f"docs/development/{path.name}"
        move(path, target, "inherited documentation/reference material")
    for path in (ROOT / "packaging").iterdir():
        target = f"scripts/build/{'specs/' if path.suffix == '.spec' else ''}{path.name}"
        move(path, target, "build entry/configuration ownership")
    for path in ROOT.glob("*.bat"):
        move(path, f"scripts/launchers/{path.name}", "portable launch entry")
    for path in (ROOT / "scripts").iterdir():
        if not path.is_file():
            continue
        match = re.search(r"task(\d+[a-z]*)", path.stem, re.I)
        if path.stem == "check_git_hygiene":
            target = f"scripts/maintenance/{path.name}"
        elif path.stem.startswith("build_"):
            target = f"scripts/build/archive/{path.name}"
        elif match:
            task = match[1].lower()
            if task.startswith(("011", "012")):
                target = f"scripts/research/task{task}/{path.name}"
            else:
                target = f"scripts/research/inherited/task{task}/{path.name}"
        else:
            target = f"scripts/workflows/{path.name}"
        move(path, target, "group inherited execution scripts by responsibility/task")
    for path in (ROOT / "tools").glob("*.py"):
        match = re.search(r"task(\d+[a-z]*)", path.stem, re.I)
        task = match[1].lower() if match else "misc"
        move(path, f"scripts/research/inherited/task{task}/{path.name}", "consolidate developer tools")
    for path in (ROOT / ".codex/tasks").glob("*.md"):
        move(path, f"docs/tasks/inherited/TASK-001/{path.name}", "historical task instruction")
    report = ROOT / "artifacts/TASK-016/audit/migration-plan.json"
    report.write_text(json.dumps({"moves": MOVES, "duplicates": DUPLICATES},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(MOVES)} moves; {len(DUPLICATES)} identical source duplicates; {report}")


if __name__ == "__main__":
    main()
