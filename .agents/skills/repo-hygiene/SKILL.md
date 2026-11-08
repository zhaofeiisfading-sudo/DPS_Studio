---
name: repo-hygiene
description: Audit this DPS Studio Research repository's layout, caches, Git ignore/index rules and migration dependencies. Use for repository restructuring, Git hygiene, build-directory management and TASK closeout checks.
---

# Repository hygiene

Read the repository-root `AGENTS.md` for directory ownership and protected boundaries. Work from this checkout; an artifact directory link does not authorize changes to its external target.

## Inspect and classify

1. Read Git status and the staged diff with optional locks disabled. Preserve pre-existing staged/unstaged work and record its identity before moving it. Inspect the first two directory levels and, when storage matters, physical sizes without following symlinks/junctions.
2. Classify new files using `AGENTS.md`: source, scripts, tests, configs, documents, generated artifacts, release or read-only data. Inspect contents and callers before treating a root entry as garbage.
3. Run the dependency-free, read-only checker from the repository root:

   ```powershell
   python -B scripts/maintenance/check_repo_hygiene.py
   python -B scripts/maintenance/check_repo_hygiene.py --json
   python -B scripts/maintenance/check_repo_hygiene.py --staged-only
   ```

   Exit 0 = clean, 1 = findings, 2 = audit error. Indexed blob sizes are checked even when local files differ or outputs were force-added. The script does not inspect Git history or prove scientific uniqueness.
4. Compare `.gitignore`, tracked files and staged files; use `git check-ignore --no-index -v <path>` for representative outputs and required resources. Check new file types/caches. Change rules only for a real gap; never add per-TASK artifact exceptions. Review `AGENTS.md` when structure, development/build workflow or durable constraints change. Leave adequate files unchanged.

## Clean or migrate when authorized

- Inspect root scratch, test environments, pip caches and repeated build trees. Establish reproducibility from tool metadata/callers, or establish byte identity with hashes and archive-member comparison. Names alone are insufficient.
- Use existing task authorization. Without cleanup authorization, report concrete candidates and obtain permission before deletion. With authorization, remove only confirmed regenerable junk; no backup copy is needed unless requested. List uncertain objects for manual review.
- Protect `data/raw`, effective uncommitted source, unique research results, frozen protocols/results and `.git`/history. Untracking generated files must preserve their local unique content. Never use destructive workspace resets.
- Before recursive moves/deletes, resolve exact absolute paths and verify they remain inside this checkout and outside protected paths. Reject nested symlinks/junctions. Use native PowerShell 7 operations end to end; remove a reviewed directory link only as a link, never recurse through it.
- Record important old/new paths and reasons. Repair Python/dynamic imports, relative roots, resources/configs, tests, launchers, PyInstaller specs and GitHub Actions. Verify core remains GUI-independent and installed software needs no artifacts or Production code. Keep formulas and parameters unchanged during structural work.

## Close out

Use `scripts/dev/run.ps1 -Task TASK-NNN -Python <python> ...` so configurable caches stay in the task's `artifacts/.../tmp/`. Run relevant pytest/Ruff/mypy and import/startup/build-path checks. Inspect the index, new root entries and required build resources; rerun the hygiene checker. Remove confirmed regenerable temporary files and compare protected-boundary evidence where relevant.

Report a short outcome: findings/actual changes, checks, preserved pre-existing work and unresolved manual-review items. Propose edits only for discovered problems. Follow task-document and Obsidian requirements without adding repeated rules to `AGENTS.md`.
