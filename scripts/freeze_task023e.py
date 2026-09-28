"""Create a NEW Research-only run and freeze files before any experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.finalize_task023e import git_snapshot, sha256
from scripts.run_task023e_proposal_audit import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts/task023e_cross_scale_evidence"):
        raise ValueError("Output must be a TASK-023E Research artifact")
    if output.exists():
        raise FileExistsError("Never reuse or clean an existing run")
    prod = Path("D:/Code/Python_Projects/DPS_Studio")
    research_git, production_git = git_snapshot(ROOT), git_snapshot(prod)
    if not research_git["status --short --branch"].startswith(
        "## codex/research_2/global-path-ridge",
    ):
        raise RuntimeError("Expected the Research branch")
    if not production_git["status --short --branch"].startswith("## main") or len(
        production_git["status --short --branch"].splitlines(),
    ) != 1:
        raise RuntimeError("Expected clean frozen Production main")

    def hashes(base, directories):
        return {str(path.relative_to(base)): sha256(path) for folder in directories
                for path in sorted((base / folder).rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts}

    snapshot = {
        "research_git": research_git, "production_git": production_git,
        "research_hashes": hashes(ROOT, ("src", "scripts", "tests", "configs", "data/raw")),
        "production_hashes": hashes(prod, ("src", "configs", "tools", "packaging", "data/raw")),
        "stage": "PRE_EXPERIMENT",
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / "freeze_before.json").open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2)
    print(output)


if __name__ == "__main__":
    main()
