"""Final read-only SHA/Git/frozen-result checks against captured initial state."""
from __future__ import annotations

import json
from typing import Any

from artifacts.research_clean_task9.audit import OUT, ROOT, digest, snapshot, write_json


def main() -> None:
    before = json.loads((OUT / "boundary_before.json").read_text(encoding="utf-8"))
    after = snapshot("after")
    checks: dict[str, Any] = {}
    for name in ("source", "target", "production"):
        a, b = before[name], after[name]
        checks[name] = dict(raw_unchanged=a["raw"] == b["raw"],
            raw_files=len(b["raw"]), head_unchanged=a["git"]["head"] == b["git"]["head"],
            index_unchanged=a["git"]["index_sha256"] == b["git"]["index_sha256"],
            branch=b["git"]["branch"], git_status_counts=b["git"]["status_counts"])
        if name in ("source", "production"):
            checks[name]["code_unchanged"] = a["code"] == b["code"]
            old_status = set(a["git"]["status"])
            if name == "source":
                old_status = {r for r in old_status if r != "?? artifacts/research_clean_task9/"}
                checks[name]["task8_all_source_files_unchanged"] = a["task8"] == b["task8"]
                checks[name]["authorized_probe_directory_absent"] = not (
                    ROOT.parent / "DPS_Studio_TASK021A/artifacts/research_clean_task9").exists()
            checks[name]["initial_git_status_preserved"] = old_status == set(b["git"]["status"])
        else:
            changed = [p for p, sha in a["code"].items() if b["code"].get(p) != sha]
            checks[name]["existing_changed_files"] = changed
            checks[name]["only_allowed_existing_document_changed"] = changed == ["README.md"]
            checks[name]["task8_frozen_copy_unchanged"] = a["task8"] == b["task8"]
            checks[name]["frozen_file_count"] = len(b["task8"])
            backup = OUT / "provenance/target_README_before.md"
            checks[name]["readme_original_bytes_preserved_as_prefix"] = (
                (ROOT / "README.md").read_bytes().startswith(backup.read_bytes())
                and digest(backup) == a["code"]["README.md"])
    indexed = json.loads((OUT / "data_index.json").read_text(encoding="utf-8"))["records"]
    raw = [r for r in indexed if r["kind"] == "RAW"]
    checks["local_index"] = dict(raw_files=len(raw), voltage_streams=sum(r["channels"] for r in raw),
        every_local_raw_sha_matches=all(digest(ROOT / r["local_path"]) == r["sha256"] for r in raw),
        local_paths_inside_target=all((ROOT / r["local_path"]).resolve().is_relative_to(ROOT) for r in raw))
    boolean_results = [v for row in checks.values() for v in row.values() if isinstance(v, bool)]
    checks["all_checks_passed"] = all(boolean_results)
    write_json(OUT / "checks/boundary_verification.json", checks)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    if not checks["all_checks_passed"]:
        raise AssertionError("A protected boundary changed; inspect verification before completion")


if __name__ == "__main__":
    main()
