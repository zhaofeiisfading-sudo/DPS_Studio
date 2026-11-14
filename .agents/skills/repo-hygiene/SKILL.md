---
name: repo-hygiene
description: Audit the DPS Studio Production repository layout and generated files, plan safe cleanup, or move maintained files with their callers. Use for repository audits and directory migrations in Production.
---

# Production repository hygiene

1. Ensure single-writer isolation: check active agent sessions/processes (`codex`, `Antigravity`)
   before auditing or cleaning, and never modify, test, build, or clean concurrently with another
   write-acting agent. Confirm the Production root and branch using
   `git --no-optional-locks rev-parse --show-toplevel`, `git rev-parse --git-common-dir`,
   `git worktree list --porcelain`, and `git --no-optional-locks status --short`. Check staged and
   unstaged changes separately. Leave Research, raw data, and Git history alone.
2. From the repository root, explicitly invoke the project Python 3.12+ environment rather than an
   older default `python` on `PATH` (for example,
   `D:\miniconda3\envs\dps-studio\python.exe -B scripts/maintenance/check_repo_hygiene.py`).
   Use `--json` to capture evidence and `--strict` to fail on unexpected root items, generated
   files in the index, misplaced or duplicate packages, or raw copies under `artifacts/`.
   Large files and cache locations are inventory, not deletion targets.
3. Distinguish maintained source/config, unique results, and files that can be regenerated.
   Compare the hashes of any claimed duplicate package. Check imports, workflows, tests, specs,
   launchers and current docs before a move. Keep historical reports and their evidence usable.
4. Clean only named, verified paths within the Production root and only under the task's
   authorization. Protect Production's historical `.git/worktrees/*` metadata and Research's NTFS
   junctions: never run `git worktree prune`, recursively clean across junctions or linked
   directories, modify sibling checkouts, or use blanket Git cleanup (or clean history/scientific
   defaults) without explicit authorization.
   When untracking historical generated files, retain their working copies and document the
   index change; never remove an unfamiliar file just because it appears on the report.
   Inspect source-like subtrees for maintained or unique content before removal. Keep unresolved
   candidates in the report with their source, hashes and exact paths.
5. Keep a compact before/after inventory, paths moved or removed, and any unresolved items in
   the task report under `docs/tasks/<task-id>/` and sync the lightweight Obsidian log when
   applicable. Live Git, test, and filesystem/hash state take precedence over historical logs.
   Rerun the checker and applicable tests. For ordinary tasks use the layout in `AGENTS.md` without
   adding task-specific rules.
6. Keep build entry points in `scripts/build/`, intermediates in ignored `build/<task-id>/`,
   and verified final packages in `release/`. Do not duplicate them or raw in `artifacts/`.
   Keep task caches and generated evidence in `artifacts/`, strictly obey `.gitignore`, and never
   create or commit caches, test outputs, build packages, or temporary task files at the repository
   root. Review `AGENTS.md` and `.gitignore` only for durable rule changes.
