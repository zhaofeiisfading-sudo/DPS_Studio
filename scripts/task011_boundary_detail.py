"""Explain strict boundary drift without modifying any Production file."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task11"


def main() -> None:
    before = json.loads((ARTIFACT / "boundary_before.json").read_text(encoding="utf-8"))
    after = json.loads((ARTIFACT / "boundary_final.json").read_text(encoding="utf-8"))
    first, second = [record["production_all_files_including_git"] for record in (before, after)]
    added = sorted(set(second) - set(first))
    removed = sorted(set(first) - set(second))
    changed = sorted(name for name in set(first) & set(second) if first[name] != second[name])
    content_changed = sorted(name for name in changed if first[name]["sha256"] != second[name]["sha256"])
    outside_git = {name: value for name, value in first.items() if not name.startswith(".git/")}
    final_outside_git = {name: value for name, value in second.items() if not name.startswith(".git/")}
    changed_names = added + removed + changed
    expected_prefixes = (".git/objects/", ".git/refs/codex/turn-diffs/")
    detail: dict[str, Any] = {
        "strict_production_all_files_unchanged": first == second,
        "production_files_outside_git_unchanged": outside_git == final_outside_git,
        "production_git_branch_head_status_unchanged": before["production_git"] == after["production_git"],
        "production_main_index_unchanged": first.get(".git/index") == second.get(".git/index"),
        "research_head_unchanged": before["research_git"]["head"] == after["research_git"]["head"],
        "research_branch_unchanged": before["research_git"]["branch"] == after["research_git"]["branch"],
        "research_raw_unchanged": before["research_raw"] == after["research_raw"],
        "frozen_task8_unchanged": before["frozen_task8"] == after["frozen_task8"],
        "frozen_task9_unchanged": before["frozen_task9"] == after["frozen_task9"],
        "frozen_task10_unchanged": before["frozen_task10"] == after["frozen_task10"],
        "drift_confined_to_codex_refs_and_git_objects": all(
            name.startswith(expected_prefixes) for name in changed_names),
        "added": added, "removed": removed, "changed_stat_or_content": changed,
        "changed_content": content_changed,
        "attribution": "Codex client turn-diff metadata inferred from refs/codex/turn-diffs paths "
                       "and capture timestamps corresponding to chat resume; no Git write command issued by agent",
        "action_taken": "READ_ONLY_INSPECTION; no cleanup, restore, Git write, commit, push, merge or promotion",
        "strict_git_invariance": "NOT_PASSED" if first != second else "PASSED",
        "user_exception_acceptance": "PENDING; async clarification requested, not assumed",
    }
    with (ARTIFACT / "boundary_detail.json").open("x", encoding="utf-8") as handle:
        json.dump(detail, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in detail.items()
                      if key not in {"added", "removed", "changed_stat_or_content", "changed_content"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
