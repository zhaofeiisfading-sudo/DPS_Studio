"""Check final links/boundaries and expose original CSV text without compression."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import subprocess

from scripts.research.task017.boundary import manifest
from scripts.research.task017.prepare import OUT, ROOT, records


def main() -> None:
    docs = ROOT / "docs/tasks/TASK-017"
    missing = []
    for document in docs.glob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if target.startswith(("http", "#")):
                continue
            if not (document.parent / target).resolve().exists():
                missing.append({"document": document.name, "target": target})
    if missing:
        raise RuntimeError(f"Broken final links: {missing}")
    before = json.loads((OUT / "data/boundaries/before.json").read_text(encoding="utf-8"))
    checks = {"raw": manifest(ROOT / "data/raw") == before["raw"],
              "source": manifest(ROOT / "src") == before["source"]}
    if not all(checks.values()):
        raise RuntimeError("Raw or src changed after the final boundary audit")
    csv_dir = OUT / "data/csv_final"
    csv_dir.mkdir(exist_ok=False)
    outputs = []
    for item in records():
        source = OUT / "data/analysis_v03" / item["id"] / "candidates.csv.gz"
        target = csv_dir / f"{item['id']}__all_28_methods.csv"
        with gzip.open(source, "rb") as stream, target.open("xb") as result:
            shutil.copyfileobj(stream, result)
        with target.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        outputs.append({"channel": item["id"], "file": target.relative_to(OUT).as_posix(),
                        "bytes": target.stat().st_size, "sha256": sha})
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=ROOT,
                                       encoding="utf-8").strip()
    value = {"report_links_missing": missing, "raw_src_recheck": checks, "plain_csv": outputs,
             "head": git("rev-parse", "HEAD"), "status": git("status", "--short"),
             "staged": git("diff", "--cached", "--stat"),
             "production_full_audit": "boundaries/comparison.json",
             "notes": "No deletes, dependency installs, GUI changes or Git mutations"}
    with (OUT / "data/closeout.json").open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    print("Links verified; raw/src unchanged; 14 plain CSV files exported.", flush=True)


if __name__ == "__main__":
    main()
