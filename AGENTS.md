# DPS Studio — Bandwidth Research: Codex Rules

## 1. Scope and objective

This worktree is **DPS_Studio_BANDWIDTH**, branch **research/bandwidth**, based on the Production `main` baseline. It is an **independent Research line**, not a Production upgrade. Its goal is to investigate PDV beat-frequency identifiability and estimation when the acquisition chain attenuates frequencies beyond the nominal oscilloscope bandwidth.

- Do not claim that software recovers information absent from the digitized waveform.
- Separate physical feasibility, synthetic evidence, real-data observations, and experimental confirmation.
- Preserve an explicit STFT / frame-wise strongest-peak baseline when assessing new algorithms.
- Do not start a subsequent TASK unless requested.

## 2. Filesystem boundaries — mandatory

**The only code workspace allowed for this project is:**
`D:\Code\Python_Projects\DPS_Studio_BANDWIDTH`

**Protected locations (read-only; do not edit, clean, move, rename, or delete):**
- `D:\Code\Python_Projects\DPS_Studio` (Production)
- `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`
- `D:\Code\Python_Projects\DPS_Studio_TASK021A`
- Any other sibling of this worktree under `D:\Code\Python_Projects`
- The parent directory `D:\Code\Python_Projects` itself (no additional sibling projects created by Codex)

**Only exception for writing outside this worktree:** the required Obsidian TASK log at
`D:\Research\Notes\05项目\DPS_Studio_BANDWIDTH`.
Do not write other external files without explicit authorization.

Do not rename, delete, relocate, or reorganize the project's existing **top-level (first-level) folders**. Do not casually add new top-level directories. The only pre-approved local cache folder is `.local_cache/`; a task-specific `results/bandwidth/` directory may be used for generated experimental artifacts if needed. Prefer new code/tests/docs within existing `src/`, `tests/`, `scripts/`, and `docs/` trees. Changes to existing root-level configuration files require clear task need and review; no unrelated changes.

Beware of Windows junctions/symlinks: resolve the target before writing. A path inside this worktree that points outside it is **not** an authorized write target.

`AGENTS.md` expresses workflow rules; it is not an operating-system write-permission boundary. Respect configured sandbox/workspace permissions as well.

## 3. Git and task boundaries

At the beginning of every TASK, report `git branch --show-current`, `git status --short`, `git diff`, the exact worktree path, applicable configs, relevant source/tests, and whether raw files are present. If the branch is not `research/bandwidth`, stop and report rather than silently switching branches.

- No changes to Production or any other worktree; no automatic cherry-pick, merge, rebase, promotion, or synchronization.
- No commit, push, reset, clean, force operation, or deletion of branches/worktrees without explicit user approval.
- Never use `git clean -fdx`, destructive reset, or rewrite shared Git history as a shortcut.
- Existing user modifications must be preserved. Do not use a cleanup step that may remove untracked or ignored research results.
- Keep code changes focused; avoid large refactors outside the TASK.

## 4. Data and scientific integrity

- `data/raw` and all original experiment data are strictly read-only. Never overwrite, remove, mutate, or silently resample raw files. Record SHA-256 before and after a task when relevant raw data is accessed.
- Do not assume raw data in another worktree is automatically present here. Do not create a writable junction to another worktree's data without approval.
- Internal SI units: s, V, Hz, m/s, m, rad. All imported units and channel mappings must be explicit.
- Distinguish oscilloscope **analog bandwidth**, detector/amplifier/cable response, sampling frequency/Nyquist limit, FFT grid spacing, true resolution, and noise/quantization.
- Do not infer an actual oscilloscope response `H(f)`, model, bandwidth, optical offset, or independent velocity truth from missing metadata. Label unknowns `UNKNOWN`.
- Separate observed signal, candidate frequency, model-based estimate, prior prediction, and validated physical velocity. Never turn missing or rejected estimates into unflagged measurements.
- Use wavelength and optical offset explicitly. Keep apparent velocity, angle-corrected velocity, LiF/window-corrected velocity, and displayed velocity distinct.
- Do not add or modify a formal physical correction without verified sources and a separately authorized scope.
- For uncertain or unreliable frequencies, record quality/uncertainty or rejection; synthetic completion must be labeled as prediction, never measured recovery.

## 5. Research design and tests

- Favor an identifiable physical mechanism over cosmetically smooth output.
- Prioritize reproducible synthetic experiments with known truth, independent seeds/held-out cases, and clear model mismatch tests; real data without truth must be described as observational evidence only.
- Baseline: STFT + frame-wise strongest peak; report accuracy/error, wrong branch, coverage, false recovery, computational cost, and uncertainty calibration as relevant.
- Audit model assumptions (including correlated residual noise); compare on identical data and do not tune on final test labels.
- If evidence is insufficient, write `NOT IDENTIFIABLE`, `UNKNOWN`, or `REQUIRES EXPERIMENTAL CONFIRMATION`, instead of asserting success.
- Add tests for implemented behavior, including failure cases. Run relevant pytest, Ruff, and mypy strict checks as the project supports; record actual pass/fail totals, including pre-existing failures.
- Reports must cite real, verifiable references. Never fabricate papers, DOI, instrument parameters, test output, or Git state.

## 6. Generated files and cache hygiene

All **disposable caches and temporary files** must be redirected to `.local_cache/` inside this worktree, which is Git-ignored. Use `scripts/bandwidth_env.ps1` when working in PowerShell. For pytest, set a dedicated cache and temporary base; for Ruff/mypy/matplotlib/pip, use the corresponding environment cache variables. Avoid repository-root `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `build`, `dist`, temporary `.log`, and accidental `.egg-info` clutter.

Place meaningful, reproducible experiment results under a clearly named task directory (normally `results/bandwidth/taskXXX_*`); generated outputs should not be mistaken for ephemeral caches. Small, reviewable methodology/verdict documents belong in `docs/` and should be tracked if the user later approves a commit. Do not silently delete old results; any cleanup requires an explicit target list and user authorization.

## 7. Mandatory Obsidian TASK log

**Every Codex TASK, including negative, blocked, and audit-only tasks, must produce one concise Markdown log** in:
`D:\Research\Notes\05项目\DPS_Studio_BANDWIDTH`

Filename: `YYYY-MM-DD_TASK-XXXX_简短标题.md` (use the actual execution date and task number).

Include: task/date/branch/status/verdict/artifact; work completed; changed and created files; output paths; key quantitative metrics, including negative results; test outcomes; Git/raw/Production boundary checks; unresolved questions; next recommended step. The log is a navigational index, **not** the source of truth; real code, Git state, tests, and artifacts take precedence.

If the Obsidian path is not accessible, do not claim the log was written. Save the exact pending draft inside the worktree under `docs/bandwidth/pending_logs/` and report the blocker.

## 8. Required TASK delivery

At task end, present:
1. Verdict with explicit evidence boundaries and unanswered questions.
2. Changed/added paths and main output/artifact locations.
3. Exact commands and results for tests/lint/type checks.
4. Final Git status, boundary audit, and raw SHA-256 comparison when applicable.
5. Obsidian log full path (or blocked + in-worktree pending draft).
6. Recommendation only; **do not autonomously start the next TASK**.
