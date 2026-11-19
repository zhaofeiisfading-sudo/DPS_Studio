# TASK-023 Phase 2B verification

Codex ran the five-channel screen on 2026-11-19 from the Research checkout on branch `codex/research_2/global-path-ridge-v2` at HEAD `07416ffd79a00ea7436553f8967ee6a078b218df`.

## Changes

- M4 clears isolated pass-one picks from the seed path. Surviving neighbors can propose candidates at those centers, and the candidates must pass the raw-voltage gate.
- The 38.4 ns retry uses its own quadratic raw R², including the full-window refit when the window crosses a detected DC step. A proposal at or above the OFF score can retry after a subthreshold 25.6 ns R².
- Long verification with failed short-fit support uses 107 fixed probes at 50 MHz spacing over 0.30–5.60 GHz. The full-window degree-2 powers are scaled to the candidate’s quiet floor and exclude probes within 250 MHz of the candidate. The 35th percentile divided by −ln(0.65) estimates the local bed. Both SNR measurements use the larger of this bed and twice the quiet floor and must reach 11.5 dB full and 5.0 dB in the weaker half. The R², cycle and coherence checks remain in force.
- The sub-250 MHz floor uses 38.4 ns projections from the lower-energy half of complete, step-free quiet windows. M4 uses the larger of the inherited and empirical quiet floors. Below 200 MHz, a candidate without a one-cycle 6.4 ns anchor needs 38.4 ns R² ≥ 0.15 as well as two-sided coherence and amplitude support.
- The label-free regime decoder makes weak-tail eligibility depend on long-window support and weak short R². A verification window ≤ 12.8 ns or 6.4 ns raw chirp R² ≥ 0.25 prevents a weak-tail assignment even where the BIC RMS split is elevated. Step, multi-branch and CW diagnostics remain available.

## Five recorded channels

| Channel | Phase 2 → Phase 2B on the frozen primary mask |
| --- | --- |
| 20201210m_ch1 | Onset 3/3 → 3/3, decline 42/42 → 42/42, unknown 35/46 → 35/46. Those publication masks match at every center. First onset remains 138.757608 µs. |
| 20201211m_ch1 | Decline 35/36 → 35/36. All five centers at 108.370402–108.383202 µs retain the same frequencies, 0.836–0.748 GHz. The one decline gap shifts by one center from 108.290402 to 108.293602 µs. The later weak interval remains 0/28. |
| 20221017a_ch1 | Weak 30/41 → 30/41 on the same centers, with zero picks above 4 GHz. Visual noise 0/85 → 0/85. All 178 short-supported plateau centers previously assigned to the weak tail now decode as steady ridge. All 265 plateau centers decode as steady ridge. |
| 20260630-1_ch2 | Weak 66/67 → 67/67. The 747.20–747.24 µs competing window is 11/12 → 12/12. At 747.205215 µs, 38.4 ns verification selects 0.243236 GHz with a 0.514947 GHz secondary. The 744.30–744.34 µs stationary run is 11/12 → 0/12. The 746.16–746.20 µs run is 11/12 → 11/12 on the same centers. First post-rail publication remains 746.222815 µs. |
| ch3_ch1 | Weak 44/44 → 44/44. Visual noise 29/213 → 3/213 and stationary 0/326 → 0/326. The two late streaks at 184.131753–184.170153 and 184.506153–184.538153 µs are 13/13 → 0/13 and 11/11 → 0/11. |

Reprojecting the former ch3 streak picks gives median CA-CFAR corrections of 3.85 and 4.08 dB at 25.6 ns and 3.86 and 4.31 dB at 38.4 ns. The rejected 744.30–744.34 µs picks had 38.4 ns R² of 0.103–0.136. The ten published sub-120 MHz picks in the retained 746.16–746.20 µs run have 38.4 ns R² of 0.156–0.310 and receive 1.36–2.92 dB of low-frequency SNR correction. The remaining center in that run uses the short continuation route. [Stage table](../../../artifacts/TASK-023/phase2b/tables/phase2_per_channel_stage.csv) · [Competing-window figure](../../../artifacts/TASK-023/phase2b/figures/20260630-1_ch2__zoom_competing.png)

M4 publishes 1,862 → 1,831 of 3,361 primary centers. Under frozen noise or stationary labels, publications fall from 574 to 539 and from 87 to 49 outside the persistent-CW regime. Agreement with the frozen visual-to-regime mapping rises from 2,017 to 2,233 of 3,361 (60.0% → 66.4%). Adjacent jumps above 250 MHz rise from two to three with an added ch3 transition at 183.853353 µs in the unknown interval. Three ch3 noise-labeled picks remain near 183.876–183.882 µs. On `20260630-1_ch2`, 490 of 524 late noise-labeled publications decode as persistent CW. Their physical origin remains unresolved. [Summary](../../../artifacts/TASK-023/phase2b/tables/phase2_summary.csv) · [Regime confusion](../../../artifacts/TASK-023/phase2b/tables/phase2_regime_confusion.csv)

## Reproduction and checks

`phase2_run.py` exited 0 in 194.61 s wall time and wrote nine CSVs and 11 PNG/SVG pairs. All PNGs decoded and all SVGs parsed. M4 time was 76.11 s versus 45.49 s in the archived Phase 2 run. The summed timed stages were 183.53 s versus 126.64 s. The six inherited methods also took longer in this run, so the wall-time difference includes run-to-run effects. [Timing CSV](../../../artifacts/TASK-023/phase2b/tables/phase2_timing.csv)

All 317,223 exported Phase 1B CSV fields matched the five frozen center tables exactly, including raw diagnostics and all six methods. SHA-256 checks matched for 37 Phase 1 files, 32 Phase 2 files, 11 files under `data/raw/`, `AGENTS.md` and `.gitignore`. Research `src/` and `configs/` had no Git changes. Production received no writes, and HEAD and the empty index were preserved.

| Check | Output |
| --- | --- |
| Focused pytest | `37 passed in 49.15s` |
| Repository-wide Ruff | `All checks passed!` |
| Strict mypy | `Success: no issues found in 211 source files` |
| Repository hygiene | `Repository hygiene: clean (read-only audit)` |

The weakest synthetic fixture now requires at least 50% recovery and 25 recovered centers below raw R² 0.10, compared with the former 65% and 30-center checks. The fixture serves as a unit regression check for the stricter long gate.

```powershell
$py = 'D:/miniconda3/envs/dps-studio/python.exe'
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m scripts.research.task023.phase2_run --output artifacts/TASK-023/phase2b
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m pytest -q tests/unit/test_task023_phase1.py tests/unit/test_task023_phase2.py
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m ruff check
& scripts/dev/run.ps1 -Task TASK-023 -Python $py -m mypy --strict --explicit-package-bases src/dps_studio scripts/research/task023 tests/unit/test_task023_phase1.py tests/unit/test_task023_phase2.py
& scripts/dev/run.ps1 -Task TASK-023 -Python $py scripts/maintenance/check_repo_hygiene.py
```

The screening command requires a fresh output directory. The runner uses Python 3.12 with bytecode disabled.
