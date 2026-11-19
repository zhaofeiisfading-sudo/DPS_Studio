# TASK-023 Phase 1B verification

Executed by Codex CLI on 2026-11-18 local time in `D:/Code/Python_Projects/DPS_Studio_RESEARCH_CLEAN`. Branch `codex/research_2/global-path-ridge-v2` at `07416ffd79a00ea7436553f8967ee6a078b218df`.

Phase 1B completed all six methods on five frozen channels. B0, B1 and B+S matched all five TASK-020 archived readouts exactly, with candidate, output, legacy support and primary masks checked where applicable. The exported times also matched exactly. The experiment produced eight CSVs and 14 figure pairs, with five overviews and nine zoom cards. [Phase 1B report](../../../artifacts/TASK-023/phase1/PHASE1_REPORT.md)

- M1 restored 56 plateau centers on `20201210m_ch1`. The measured `20201211m_ch1` ramp has no novel publication below 250 MHz, and decline coverage increased to 28/28/26 of 36 centers for M1/M2/M3.
- On `20221017a_ch1`, M1/M2/M3 publish 28/34/29 of 41 weak-stage centers. M2 includes five picks above 4 GHz away from the visible falling ridge.
- On `ch3_ch1`, M2 drops from 25 to 7 noise-stage publications and from 7 to 0 stationary publications, with 43 of 44 weak-stage centers retained.
- The last 28 primary weak-stage centers of `20201211m_ch1` remain unpublished by all methods. Coherent measurements around 0.50 GHz in the labeled `20260630-1_ch2` background remain physically unresolved.

The estimator updates are in `waveform.py`, `common.py`, `coherent.py`, `pursuit.py` and `demod.py`. The five-channel entry point is `phase1_run.py` with rendering in `phase1_plots.py`. All are under `scripts/research/task023/`. The regression coverage is in `tests/unit/test_task023_phase1.py`. The recorded Phase 1A replay and interim Phase 1B audit remain in `artifacts/TASK-023/tmp/`.

Run in PowerShell 7 with the project Python 3.12 interpreter.

```powershell
& scripts/dev/run.ps1 -Task TASK-023 -Python D:/miniconda3/envs/dps-studio/python.exe -m pytest -q tests/unit/test_task023_phase1.py
& scripts/dev/run.ps1 -Task TASK-023 -Python D:/miniconda3/envs/dps-studio/python.exe -m ruff check scripts/research/task023 tests/unit/test_task023_phase1.py
& scripts/dev/run.ps1 -Task TASK-023 -Python D:/miniconda3/envs/dps-studio/python.exe -m mypy --strict --explicit-package-bases scripts/research/task023 tests/unit/test_task023_phase1.py
& scripts/dev/run.ps1 -Task TASK-023 -Python D:/miniconda3/envs/dps-studio/python.exe scripts/maintenance/check_repo_hygiene.py
```

All four checks passed, including 20 unit tests. All ten raw SHA-256 values match the frozen inventory. The HEAD and Git index match the initial state. Code changes stayed in Research task scripts and tests, with report and notebook updates. Open questions are the branch identity and residual background behavior recorded in the report.
