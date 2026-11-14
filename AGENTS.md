# DPS Studio Production

- Work in this Production checkout. Check the Git root, branch, common directory, worktree list
  and status before editing. Preserve existing user changes. The Research checkout has its own
  history; do not write there or promote algorithms without separate authorization and validation.
- Never change, move or delete `data/raw/`. Keep the chain explicit:
  time and voltage → column mapping and SI conversion → STFT and candidates → ridge →
  quality diagnostics → apparent speed → angle and window correction → display and export.
  Core code must not import GUI code.
- Keep apparent and corrected velocities separate, and keep display priors distinguishable from
  measurements. Keep unreliable formal values NaN with quality flags. Do not silently smooth,
  interpolate, fill gaps, change defaults or relabel quality. Preserve the current LiF and custom
  window parameters; do not add unverified correction formulas. Do not infer wavelength, angle or
  material. Hop equals window length minus overlap; FFT bin spacing is not physical resolution.
- Put maintained code in `src/`, regression tests in `tests/`, build entry points in
  `scripts/build/`, packaging inputs in `packaging/`, development tools in `scripts/dev/`,
  and maintenance tools in `scripts/maintenance/`. Use `docs/tasks/<task-id>/` for task reports
  and `artifacts/<task-id>/` for generated evidence and task caches. Do not put caches, task
  outputs or packaging files at the repository root. Keep build scripts and their outputs
  separate: use ignored `build/<task-id>/` for intermediates and publish a single verified archive
  per version and platform under `release/` only for explicitly requested builds.
  Keep packages and copies of raw out of `artifacts/`. The CLI's existing
  `outputs/production_runs/` location is part of its local output interface.
- Before and after each task, run `python scripts/maintenance/check_repo_hygiene.py`. Inspect new
  files, generated files in the index, root layout, caches, package placement and temporary
  outputs. Ignoring a file does not untrack it. Update this file and `.gitignore` only if a durable
  rule changes. Automated cleanup must preserve maintained source, raw, and unique user data.
  Follow
  [repo-hygiene](.agents/skills/repo-hygiene/SKILL.md) for cleanup and migrations.
- Add regression tests for behavior changes. Run pytest, Ruff and strict mypy as appropriate
  to the affected code. Use explicit test cache and basetemp paths under the task artifacts.
  If GUI work affects scientific workflows, exercise real data and compare arrays and exports.
- Do not automatically commit, push, merge, rebase, rewrite Git history, or build releases.
  Keep raw data, artifacts, caches, build intermediates and packages out of Git. Avoid unrelated
  changes and stop once the requested task is complete.

## Multi-Agent Coordination

- Single-writer rule: At most one write-acting agent may operate on this repository at a time.
  Gemini and Codex CLI (or multiple agent sessions) must never concurrently edit files, run tests
  or builds, or perform cleanup in the same repository.
- Cross-repository boundary: Gemini may perform read-only cross-repository reference (including
  inspecting the Research checkout), but any cross-repository write or Research → Production
  promotion requires separate explicit authorization and validation.
- Pre-flight inspection: Before modifying files or starting write/test/build/cleanup actions,
  check the active branch, Git status (`git --no-optional-locks status -sb`), staged/unstaged
  uncommitted changes, registered worktrees (`git worktree list --porcelain`), `git-common-dir`,
  and active agent sessions/processes (`codex`, `Antigravity`). Preserve peer or user changes.
- Protect worktree metadata and junctions: Preserve historical `.git/worktrees/*` registrations in
  Production and NTFS junctions (`artifacts/*` reparse points) in Research. Never run
  `git worktree prune`, recursively delete/traverse across junctions or linked directories, or
  modify sibling worktrees without explicit user approval.
- Root cleanliness and directory discipline: Never create caches, test outputs, build packages,
  or temporary task files at the repository root. Keep maintained scripts in `scripts/`
  (`scripts/build/`, `scripts/dev/`, `scripts/maintenance/`), verified release archives in
  `release/`, research/task outputs and caches in `artifacts/` (`artifacts/<task-id>/`), build
  intermediates in `build/<task-id>/`, and task reports in `docs/` (`docs/tasks/<task-id>/`),
  strictly honoring `.gitignore`.
- Explicit Python environment: Run maintenance scripts, hygiene checks, tests, and builds using
  the project Python 3.12 environment (`D:\miniconda3\envs\dps-studio\python.exe`, with `-B` to
  avoid bytecode scatter); do not rely on an older default `python` on `PATH` (e.g., Python 3.9.1
  fails `check_repo_hygiene.py`).
- Ground-truth closeout: At task completion (unless explicitly restricted to scoped governance-only
  edits), update the required verification reports (`docs/tasks/<task-id>/`) and lightweight
  Obsidian log (`D:\Research\Notes\05项目\dps`). Live Git state, actual test results, and real
  filesystem/hash state always take precedence over historical docs or logs.
- Strict authorization gates: Never commit, push, clean history or historical artifacts, alter
  scientific default configurations (`configs/` or core defaults), build releases, or launch new
  Codex CLI tasks without explicit user authorization.
