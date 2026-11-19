# TASK-023 Phase 1A verification

**2026-11-18 · Codex CLI**  
Research checkout `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`  
Branch `codex/research_2/global-path-ridge-v2`, HEAD `07416ffd79a00ea7436553f8967ee6a078b218df`

## Implementation

The research entry points are in [methods.py](../../../scripts/research/task023/methods.py).
[common.py](../../../scripts/research/task023/common.py) loads the frozen TASK-017 inventory and
visual plans, replays the TASK-020 baselines, and evaluates hypotheses on the measured voltage.
The center grid is `np.arange(384, N - 383, 128, dtype=np.int64)` and the candidate band is
50 MHz–6 GHz. B+S publishes the B1 candidate where the original TASK-017 support rule passes.
That rule retains its 256-sample fit, its 8 GHz spectral reference band and its frozen background
cutoff. The new method searches and quiet statistics are derived from voltage without visual stages.

- **M1** searches the four physical scales with batched dechirp FFTs and 17 rates from −40 to
  +40 GHz/µs. Persistent steps trigger split-linear projection. A smoothed 500 MHz quiet spectrum
  whitens the split-half coherent power. An empirical quiet-frame cutoff gates the profiled
  likelihood score before the kinematic recurrence over up to 16 peaks, OFF and JUMP.
- **M2** separates a robust local trend and gates isolated impulses. It estimates up to three
  chirps using successive residual nominations and joint real-voltage refits with zero weight
  for repeated rails. Harmonic comparison uses both frequency ratios and chirp rates.
- **M3** seeds from whitened proposals verified at raw R² ≥ 0.40 and half coherence ≥ 0.65.
  It propagates phase, frequency and chirp rate in both directions at a nominal 0.8 ns update
  cadence. A real two-quadrature solve handles sub-cycle blocks. The estimator lengthens the
  integration when quadrature SNR is low and terminates propagation on loss of lock.

The column names follow the Phase 1A specification. `64ns` and `256ns` denote 6.4 ns and
25.6 ns. `local_center_snr_32ns` is the detrended power relative to the quiet floor in dB,
using ±3.2 ns. Near a detected step, the center-energy guard uses only samples on the
center's side. M1's supplementary raw verification just after a step also uses the original
voltage with time relative to the published center. Incomplete long windows produce NaN.

## Verification

The [unit suite](../../../tests/unit/test_task023_phase1.py) passed all 10 tests in 7.94 s. It
checks chirp phase continuation, dropout and impulsive artifacts, DC-step rejection before
onset at both sample rates, clipped-tone recovery and harmonic distortion, independent
components, physical-window invariance, 250 MHz quadrature in both directions, OFF/JUMP
transitions, and real-channel shape and runtime. Ruff and strict mypy passed. Mypy used
`--explicit-package-bases` for the existing `scripts.research` namespace.

Run from the Research root with PowerShell 7.

```powershell
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -m pytest -q tests/unit/test_task023_phase1.py
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -m ruff check scripts/research/task023 tests/unit/test_task023_phase1.py
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -m mypy --strict --explicit-package-bases scripts/research/task023 tests/unit/test_task023_phase1.py
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -m scripts.research.task023.benchmark
```

| Channel | Centers | B0/B1/B+S + parity | M1 | M2 | M3 |
|---|---:|---:|---:|---:|---:|
| `20201211m_ch1` | 307 | 0.559 s | 1.202 s · 127 | 0.308 s · 185 | 0.653 s · 140 |
| `20260630-1_ch2` | 1,557 | 2.974 s | 5.922 s · 788 | 1.533 s · 802 | 3.576 s · 744 |

Each method timing includes quiet calibration and the raw-voltage evaluator, with channel
loading excluded. The integer after each method time counts accepted centers. Both recordings
are 40 GS/s. The 80 GS/s invariants were checked on deterministic signals. B0, B1 and B+S agree
with the frozen TASK-020 centers on both real channels, including S and the NaN masks.

## Closeout

The repository hygiene audit passed. All ten raw files matched the frozen SHA-256 inventory.
The Research HEAD and index remained at their original state. Runner caches were confined
to `artifacts/TASK-023/tmp/`. Work was confined to Phase 1A research source, tests and
verification notes. Phase 1B is reserved for the five-channel plots, stage-level audits and
physical branch comparison after Gemini's review.
