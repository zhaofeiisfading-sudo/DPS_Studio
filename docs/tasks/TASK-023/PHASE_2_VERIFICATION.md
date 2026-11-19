# TASK-023 Phase 2 verification

Codex ran the five-channel gate on 2026-11-18 in `D:/Code/Python_Projects/DPS_Studio_RESEARCH_CLEAN`, branch `codex/research_2/global-path-ridge-v2`, HEAD `07416ffd79a00ea7436553f8967ee6a078b218df`.

**Phase 3 remains No-Go.** M4 recovers the late decline on `20201211m_ch1` while its frozen weak interval remains empty. It removes all strict short noise islands on `ch3_ch1` and retains all 44 weak centers. Longer noise-stage publications rise from 9 for M1 to 29 for M4. The real competing window on `20260630-1_ch2` has one missing center. Its persistent line remains physically ambiguous even where the regime flag is clear. [Phase 2 report](../../../artifacts/TASK-023/phase2/PHASE2_REPORT.md)

- Implementation is in `scripts/research/task023/phase_coherent.py`, with the reusable raw evidence, pursuit and kinematic code in the same package. `regime.py` takes raw and M4 observables. `phase2_run.py` audits against frozen annotations after inference and writes the nine tables and 11 figure pairs.
- Every field of the five Phase 1B center CSVs replayed exactly. All 37 Phase 1 artifact hashes and all ten raw hashes matched. The TASK-017 visual annotation and raw inventory hashes matched their freeze. Git HEAD and the empty index remained at their original state. Research `src/`, `configs/`, `AGENTS.md`, `.gitignore` and Production received no writes.
- All 28 focused Phase 1 and Phase 2 tests passed. The eight new cases cover −11.3 and −6 dB band-limited chirps, both Gaussian null sample rates, two-branch selection, both sides of the cycle guard, and label-free regime decoding. Repository-wide Ruff, strict mypy on 120 source files including Research core and GUI, and the repository hygiene checker all passed.

The full pytest run ended with 1,538 passed and seven failed. Two TASK-022 parity tests had passed their equality assertions and failed writing JSON to the missing `artifacts/TASK-022/tmp/` directory. Both passed on rerun using the TASK-022 development runner, which provisions that directory. Five inherited checks reproduced on rerun.

| Check | Observed failure |
| --- | --- |
| `test_task023a_imm_mht_tracker.py` | Historical SHA-256 differs for Research `stft.py` and `candidates.py`. |
| `test_task023f_proposal_recovery.py` | Production `src/dps_studio/__init__.py` differs from the archived TASK-023F checksum. |
| `test_task023g_retention_audit.py` | Research `src/dps_studio/research/task023f_audit.py` differs from the archived checksum. |
| `test_task025_informative_interval.py` | Research `configs/pdv_studio_defaults.toml` differs from the frozen checksum. |
| `test_task025_informative_interval.py` | The frozen `streams/T25_CORE_amplitude_exchange_08_balanced.npz` is absent. |

These checks require the matching historical versions and TASK-025 calibration streams. The underlying protected Research and Production files were outside the Phase 2 write scope.

Reproduce under PowerShell 7 with the project Python 3.12 environment.

```powershell
$py = 'D:/miniconda3/envs/dps-studio/python.exe'
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m scripts.research.task023.phase2_run --output artifacts/TASK-023/phase2_repeat
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m pytest -q tests/unit/test_task023_phase1.py tests/unit/test_task023_phase2.py
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m ruff check scripts/research/task023 tests/unit/test_task023_phase1.py tests/unit/test_task023_phase2.py
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m mypy --strict --explicit-package-bases scripts/research/task023 tests/unit/test_task023_phase1.py tests/unit/test_task023_phase2.py
& scripts/dev/run.ps1 -Task TASK-023 -Python $py scripts/maintenance/check_repo_hygiene.py
```
