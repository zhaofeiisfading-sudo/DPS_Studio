# TASK-023 Phase 3B verification

Codex ran the Phase 3B replay on 2026-11-19 in `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`, branch `codex/research_2/global-path-ridge-v2`, HEAD `07416ffd79a00ea7436553f8967ee6a078b218df`.

The runner replayed all ten files and 14 channels with the Phase 2B settings and the inclusive 50 MHz–6 GHz primary frequency band. M4 estimation and regime decoding used each channel's voltage independently. The audit applied the frozen visual labels after estimation and retained the archived baseline evidence calibration. Shot `20260630-1` contributes ch2 to screening and ch1 to heldout. Pairing used the final primary estimates. [TASK-017 inventory](../../../artifacts/TASK-017/data/inventory.json)

## Clipping-harmonic fix

On `20260630-1_ch1`, 20,646 of 200,001 samples (10.32%) were at the −0.083918 V or +0.083265 V rails. The strong third harmonic of the clipped ~0.550 GHz waveform passed the raw-voltage verifier. The Phase 3 selector counted it as a moving rival and capped the fundamental's score when the fundamental lay within 65 MHz of the ~0.5065 GHz CW line. That favored the ~0.6025 GHz sidelobe and led to the third-harmonic track during the decline. Phase 3B excludes orders 2–8 from the rival score when a verified candidate in the same frame explains the harmonic within the frequency tolerance and scores at least as high as the harmonic minus two points. The regression uses a hard-clipped 0.550 GHz waveform coexisting with a 0.506 GHz tail and checks the published frequencies through both intervals. [M4 selector](../../../scripts/research/task023/phase_coherent.py#L365) · [Clipping regression](../../../tests/unit/test_task023_phase2.py#L101)

Across the 854 jointly published M4 centers in this pair, disagreements above 250 MHz fell from 17 to 0. Agreement within 30 MHz rose from 691/854 (80.91%) to 837/854 (98.01%). At the 17 formerly misidentified centers (746.779615–746.830815 µs), ch1 now follows 448.863–524.781 MHz and differs from ch2 by at most 6.874 MHz. At the 126 centers formerly assigned to the 602.527 MHz sidelobe between 746.242015 and 746.754015 µs, the corrected ch1 median is 553.827 MHz. [Phase 3 pair table](../../../artifacts/TASK-023/phase3/tables/phase3_dual_gain_pairs.csv) · [Phase 3B pair table](../../../artifacts/TASK-023/phase3b/tables/phase3_dual_gain_pairs.csv) · [Corrected ch1 centers](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260630-1_ch1.csv)

## Primary results

**M4 published 3,769/6,114 held-out centers** versus 3,686 for B1 and 3,904 for B0. Across the 504 held-out decline centers, M4 published 495 versus 490 for B1. Weak-stage publication was 390/444 versus 391/444 for B1. M4 published at 1,071/3,211 noise or stationary centers versus 990 for B1. Of the 1,071, 897 decoded as persistent CW, leaving 174 outside that regime. These counts measure publication under visual labels. A persistent line can be real without identifying the target branch.

All `screening_5` summary metrics and regime counts match Phase 3 exactly. M4 still publishes 1,831/3,361 primary centers and 539/1,968 noise or stationary centers, with three adjacent jumps above 250 MHz. The single center-level frequency delta against Phase 2B is recorded in the checks below.

| Pool | Method | Published / primary | Published / noise or stationary | Adjacent jumps >250 MHz | Median 6.4 ns raw chirp R² | Median 25.6 ns raw chirp R² | Median split-half coherence |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| screening_5 | B0 | 1340/3361 | 584/1968 | 0 | 0.7390 | 0.6372 | 0.9632 |
| screening_5 | B1 | 1711/3361 | 484/1968 | 12 | 0.8020 | 0.6328 | 0.9147 |
| screening_5 | B+S | 1719/3361 | 488/1968 | 26 | 0.8011 | 0.6314 | 0.9139 |
| screening_5 | M1 | 1775/3361 | 500/1968 | 11 | 0.7810 | 0.6761 | 0.9284 |
| screening_5 | M2 | 1770/3361 | 505/1968 | 18 | 0.7894 | 0.6830 | 0.9671 |
| screening_5 | M3 | 1700/3361 | 483/1968 | 6 | 0.7979 | 0.6260 | 0.8414 |
| screening_5 | M4 | 1831/3361 | 539/1968 | 3 | 0.7702 | 0.6709 | 0.9572 |
| heldout_9 | B0 | 3904/6114 | 1294/3211 | 0 | 0.9408 | 0.8503 | 0.9891 |
| heldout_9 | B1 | 3686/6114 | 990/3211 | 9 | 0.9463 | 0.8705 | 0.9799 |
| heldout_9 | B+S | 3632/6114 | 976/3211 | 11 | 0.9472 | 0.8742 | 0.9810 |
| heldout_9 | M1 | 3624/6114 | 951/3211 | 9 | 0.9468 | 0.8923 | 0.9526 |
| heldout_9 | M2 | 3356/6114 | 981/3211 | 6 | 0.9528 | 0.8669 | 0.9886 |
| heldout_9 | M3 | 3570/6114 | 928/3211 | 7 | 0.9486 | 0.9003 | 0.9552 |
| heldout_9 | M4 | 3769/6114 | 1071/3211 | 4 | 0.9432 | 0.8872 | 0.9838 |
| all_14 | B0 | 5244/9475 | 1878/5179 | 0 | 0.9263 | 0.7979 | 0.9820 |
| all_14 | B1 | 5397/9475 | 1474/5179 | 21 | 0.9298 | 0.7897 | 0.9597 |
| all_14 | B+S | 5351/9475 | 1464/5179 | 37 | 0.9302 | 0.7914 | 0.9597 |
| all_14 | M1 | 5399/9475 | 1451/5179 | 20 | 0.9258 | 0.8309 | 0.9441 |
| all_14 | M2 | 5126/9475 | 1486/5179 | 24 | 0.9118 | 0.7977 | 0.9812 |
| all_14 | M3 | 5270/9475 | 1411/5179 | 13 | 0.9303 | 0.8040 | 0.9247 |
| all_14 | M4 | 5600/9475 | 1610/5179 | 7 | 0.9122 | 0.8184 | 0.9757 |

Counts are exact. Medians use published centers with finite diagnostics. Jump counts require two adjacent published centers on the frozen hop grid. [Summary CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_summary.csv) · [Per-channel and stage CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_per_channel_stage.csv)

### Regime labels

| Pool | Visual mapping agreement | Onset → step | Plateau → steady | Decline → chirp | Weak → weak tail | Noise → quiet | Noise → persistent CW |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| screening_5 | 2,233/3,361 (66.44%) | 2/24 | 690/722 | 128/195 | 0/180 | 360/888 | 490/888 |
| heldout_9 | 3,656/6,114 (59.80%) | 4/45 | 1,244/1,620 | 252/504 | 2/444 | 257/1,267 | 897/1,267 |
| all_14 | 5,889/9,475 (62.15%) | 6/69 | 1,934/2,342 | 380/699 | 2/624 | 617/2,155 | 1,387/2,155 |

Held-out visual weak centers mostly decoded as steady ridge (198), multibranch (97), or persistent CW (77). The weak-tail label has little correspondence with the frozen weak-stage annotation. STEP_ONSET also marks few of the visual onset centers. Held-out stationary-to-quiet agreement was 1,863/1,944. The annotations describe the complete physical record, so the out-of-band plateau on `20201214m_ch1` also contributes to disagreement. [Regime confusion CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_regime_confusion.csv)

### Held-out exceptions and successes

| Channel | M4 onset | M4 decline | M4 weak | M4 noise | Observation |
| --- | ---: | ---: | ---: | ---: | --- |
| 20201214m_ch1 | 0/5 | 44/53 | 2/19 | 0/20 | The 6 GHz plateau is empty. At 83.442402 µs M4 jumps from 4.8110 to 1.8536 GHz ahead of the nominal stage boundary. Branch identity at the visual handoff remains unresolved. |
| 20231019-ch1_ch1 | 4/4 | 137/137 | 22/50 | 0/107 | Full plateau and acceleration coverage, no stationary publications or >250 MHz adjacent jumps, and 34/35 unknown-stage publications. The weak branch remains intermittent and visually ambiguous. |
| 20260607_ch1 | 4/4 | 53/53 | 53/53 | 85/86 | M4 tracks the common decline and weak tail. At 555.704254 µs ch1 switches to a higher late branch. Pair disagreements above 250 MHz fall from 16 in Phase 3 to 14 in Phase 3B, through 555.745854 µs. |
| 20260607_ch2 | 4/4 | 53/53 | 53/53 | 84/86 | 45/53 visually weak centers decode as persistent CW despite close cross-gain agreement. The late noisy interval has 67 CW-labeled publications. Its target association is unresolved. |
| 20260630-1_ch1 | 6/8 | 58/58 | 67/67 | 526/526 | M4 retains the lower branch through the clipped decline. It publishes 60/699 stationary centers, including a ~1.83 GHz early streak, and 490/526 noise centers decode as CW. |
| 20260630-2_ch1 | 5/5 | 42/42 | 62/62 | 125/125 | Both channels switch from ~0.45 to ~0.86 GHz late in the weak interval. ch1 switches at 541.249250 µs, one center earlier than ch2. |
| 20260630-2_ch2 | 5/5 | 42/42 | 62/62 | 125/125 | The late line agrees across gain but its source is unresolved. M4 noise publications decode as CW at 116/125 centers in ch2 and 120/125 in ch1. |
| 20260701_ch1 | 5/5 | 33/33 | 38/39 | 65/96 | ch1 alone publishes late noise-stage frequencies at 0.680–0.747 GHz. Fifty decode as persistent CW. The same regime accounts for 130 plateau centers in ch1. |
| 20260701_ch2 | 5/5 | 33/33 | 31/39 | 0/96 | M4 rejects the entire noise stage, while B1 publishes 24/96. Among 31 mutually published weak centers, all M4 differences are within 30 MHz. |

## Natural paired-channel agreement audit

Pairs joined the intersection of exact raw acquisition timestamps on the primary center grid. Each shot had zero unmatched primary centers in either channel. The separate raw lag diagnostic maximized the Pearson correlation of `ch1[i + lag]` and `ch2[i]` over ±20 samples (±0.5 ns) with fixed overlap. A negative lag indicates that ch2 trails ch1 under this convention. Pair scoring used the original timestamps. Near-tied lag peaks, clipping and receiver shape differences limit interpretation as a physical delay measurement.

| Shot | Exact centers | Raw lag (samples) | Raw lag (ps) | Peak correlation | Peak minus runner-up | Rail-window centers ch1 / ch2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260607 | 610 | −7 | −175.000 | 0.957662 | 0.004580 | 0 / 61 |
| 20260630-1 | 1,547 | 0 | 0 | 0.953641 | 0.000467 | 265 / 157 |
| 20260630-2 | 610 | 0 | 0 | 0.972873 | 0.002971 | 286 / 4 |
| 20260701 | 610 | 0 | 0 | 0.992352 | 0.003786 | 41 / 0 |

### All-center agreement by method

| Shot | Method | Both published / paired | Only ch1 / only ch2 | Median / mean absolute difference (MHz) | Within 30 / 100 MHz | >250 MHz |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 20260607 | B0 | 375/610 | 21 / 22 | 0.187 / 3.211 | 99.73% / 99.73% | 1 |
| 20260607 | B1 | 373/610 | 1 / 7 | 0.274 / 8.611 | 98.66% / 98.93% | 4 |
| 20260607 | B+S | 362/610 | 8 / 14 | 0.224 / 10.434 | 98.34% / 98.62% | 5 |
| 20260607 | M1 | 366/610 | 11 / 11 | 0.003 / 17.280 | 93.72% / 95.63% | 6 |
| 20260607 | M2 | 350/610 | 25 / 10 | 0.288 / 12.498 | 98.00% / 98.00% | 6 |
| 20260607 | M3 | 354/610 | 19 / 12 | 0.706 / 26.534 | 92.94% / 94.63% | 12 |
| 20260607 | M4 | 390/610 | 3 / 2 | 0.196 / 24.694 | 93.85% / 95.64% | 14 |
| 20260630-1 | B0 | 879/1547 | 110 / 10 | 0.435 / 1.056 | 99.89% / 100.00% | 0 |
| 20260630-1 | B1 | 802/1547 | 59 / 0 | 0.724 / 2.025 | 99.75% / 99.88% | 0 |
| 20260630-1 | B+S | 800/1547 | 33 / 0 | 0.722 / 2.067 | 99.75% / 99.88% | 0 |
| 20260630-1 | M1 | 812/1547 | 38 / 0 | 0.000 / 1.044 | 99.51% / 100.00% | 0 |
| 20260630-1 | M2 | 591/1547 | 37 / 215 | 0.887 / 2.170 | 99.15% / 99.83% | 0 |
| 20260630-1 | M3 | 801/1547 | 36 / 1 | 3.090 / 6.153 | 98.00% / 99.88% | 0 |
| 20260630-1 | M4 | 854/1547 | 51 / 1 | 0.918 / 2.993 | 98.01% / 100.00% | 0 |
| 20260630-2 | B0 | 457/610 | 22 / 4 | 0.095 / 0.629 | 100.00% / 100.00% | 0 |
| 20260630-2 | B1 | 442/610 | 12 / 0 | 0.136 / 1.144 | 100.00% / 100.00% | 0 |
| 20260630-2 | B+S | 444/610 | 9 / 1 | 0.137 / 1.185 | 100.00% / 100.00% | 0 |
| 20260630-2 | M1 | 443/610 | 6 / 1 | 0.000 / 0.970 | 99.32% / 100.00% | 0 |
| 20260630-2 | M2 | 394/610 | 4 / 51 | 0.668 / 1.159 | 100.00% / 100.00% | 0 |
| 20260630-2 | M3 | 444/610 | 2 / 1 | 1.349 / 3.286 | 99.32% / 100.00% | 0 |
| 20260630-2 | M4 | 460/610 | 0 / 0 | 0.468 / 2.331 | 99.13% / 99.78% | 1 |
| 20260701 | B0 | 373/610 | 52 / 2 | 0.090 / 0.655 | 100.00% / 100.00% | 0 |
| 20260701 | B1 | 334/610 | 48 / 0 | 0.183 / 0.701 | 100.00% / 100.00% | 0 |
| 20260701 | B+S | 338/610 | 30 / 3 | 0.186 / 0.751 | 100.00% / 100.00% | 0 |
| 20260701 | M1 | 316/610 | 33 / 1 | 0.000 / 0.266 | 100.00% / 100.00% | 0 |
| 20260701 | M2 | 336/610 | 28 / 0 | 0.206 / 0.697 | 100.00% / 100.00% | 0 |
| 20260701 | M3 | 319/610 | 24 / 0 | 0.368 / 0.857 | 99.69% / 100.00% | 0 |
| 20260701 | M4 | 309/610 | 73 / 0 | 0.076 / 0.689 | 99.35% / 100.00% | 0 |

Agreement fractions and frequency differences use centers published by both channels. Clipped means at least one channel has a repeated-rail sample in a common 6.4 ns window about the center. The CSV crosses the frozen, shared visual stage with the all, clipped and unclipped strata for every method. It records acceptance and both-rejected counts so frequency agreement can be read alongside coverage. Agreement supports reproducibility of the observed line across gain. Source and velocity require independent ground truth. [Full dual-gain CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_dual_gain_pairs.csv)

| Shot | M4 clipped / unclipped within 30 MHz | M4 onset both / paired | M4 weak both / paired | M4 noise both / paired | Pair overlay |
| --- | ---: | ---: | ---: | ---: | --- |
| 20260607 | 61/61 / 305/329 | 4/4 | 53/53 | 84/86 | [Overlay PNG](../../../artifacts/TASK-023/phase3b/figures/pair_20260607.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/pair_20260607.svg) |
| 20260630-1 | 261/262 / 576/592 | 6/8 | 67/67 | 524/526 | [Overlay PNG](../../../artifacts/TASK-023/phase3b/figures/pair_20260630-1.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/pair_20260630-1.svg) |
| 20260630-2 | 285/285 / 171/175 | 5/5 | 62/62 | 125/125 | [Overlay PNG](../../../artifacts/TASK-023/phase3b/figures/pair_20260630-2.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/pair_20260630-2.svg) |
| 20260701 | 38/40 / 269/269 | 5/5 | 31/39 | 0/96 | [Overlay PNG](../../../artifacts/TASK-023/phase3b/figures/pair_20260701.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/pair_20260701.svg) |

On `20260630-1`, the clipped-window M4 median absolute difference fell from 47.692 to 1.870 MHz. The Phase 3B median on unclipped windows is 0.616 MHz. On `20260607`, all 61 clipped centers agree within 30 MHz and all 14 disagreements above 250 MHz lie in the late unclipped noise stage. On `20260701`, the 0.076 MHz whole-pair median uses 309 jointly published centers. Another 73 centers were ch1-only.

## Separate 8 GHz diagnostic on 20201214m_ch1

B1 used its existing 8 GHz strategy call. M4 used a separate channel copy with an 8 GHz candidate ceiling and matching quiet spectrum, retaining its Phase 2B gates and fixed long-window background probes. The table reports exact centers using the same primary support mask and visual stage annotations for both bands.

| Stage | Centers | B1 6 GHz published | M4 6 GHz published | B1 8 GHz published (above 6 GHz) | M4 8 GHz published (above 6 GHz) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Onset | 5 | 2 | 0 | 3 (1) | 3 (3) |
| Plateau 82.974–83.340 µs | 114 | 0 | 0 | 113 (113) | 114 (114) |
| Decline | 53 | 40 | 44 | 51 (11) | 53 (11) |
| Weak signal | 19 | 0 | 2 | 0 (0) | 2 (0) |
| Unknown | 28 | 9 | 13 | 9 (0) | 13 (0) |
| Noise | 20 | 0 | 0 | 0 (0) | 0 (0) |

The plateau medians were 6.400800 GHz for B1 and 6.399959 GHz for M4. The median absolute difference on the 113 jointly published centers was 2.910 MHz, the mean 3.393 MHz and the maximum 16.508 MHz. Median raw 6.4 ns chirp R² across published plateau centers was 0.93525 for B1 and 0.93356 for M4. The expanded band recovers the plateau and early decline. M4 still publishes at only two weak centers, with the same median frequency of 0.812561 GHz and median short-window raw R² of 0.09712. The 8 GHz diagnostic is a separate comparison and contributes no rows to the primary aggregate or regime analysis. [Diagnostic CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_20201214m_8ghz_diagnostic.csv) · [Diagnostic PNG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__oob_8ghz.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__oob_8ghz.svg)

## Reproduction and verification

| Check | Result |
| --- | --- |
| Phase 3B runner | Exit 0, 585.461 s wall time |
| TASK-020 `verify_baselines` | Exact primary masks, native gates and frequency columns for B0, B1 and B+S on all 14 channels |
| Phase 1B | 317,223 exact archived fields across five screening channels |
| Phase 2B delta | One center and 18 fields across the five screening channels. At `20260630-1_ch2` 748.350815 µs, M4's published and candidate frequency both rose from 509.771220 to 510.076846 MHz (+0.305625 MHz). The remaining 16 fields are diagnostics. |
| Output QA | 20 CSVs, 43 decoded PNGs, 43 parsed SVGs. CSV row counts 119 summary, 623 stage, 159 timing, 920 confusion, 630 pair and 307 diagnostic. |
| TASK-023 Phase 1–3 pytest | `42 passed in 69.22s`. The clipping regression fails with the original selector at 8 of 10 overlap centers. |
| Repository-wide Ruff | `All checks passed!` |
| Strict mypy | `Success: no issues found in 215 source files` |
| Repository hygiene | `Repository hygiene: clean (read-only audit)` |
| Protected paths | SHA-256 matched all 219 files in raw, the four frozen phase trees, `AGENTS.md` and `.gitignore`. Git index and HEAD matched their initial state. |

M4 consumed 215.011 s across the 14 channels, with a median of 13.209 s and maximum of 31.506 s per channel. Regime inference and adaptive-window evidence consumed 2.023 s. Other estimator totals in seconds were B0 25.454, B1 18.990, B+S 0.000368 (incremental mask), M1 86.083, M2 53.246 and M3 73.582. Per-channel figures consumed 83.579 s. The wall time includes concurrent validation for part of the run. [Timing CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_timing.csv)

```powershell
$phaseTests = (Get-ChildItem -LiteralPath tests/unit -Filter 'test_task023_phase*.py' -File | Sort-Object Name).FullName
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -B -m scripts.research.task023.phase3_run --output artifacts/TASK-023/phase3b
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -B -m pytest -q @phaseTests
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -B -m ruff check
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -B -m mypy --strict --explicit-package-bases src/dps_studio scripts/research/task023 @phaseTests
pwsh -NoProfile -File scripts/dev/run.ps1 -Task TASK-023 -Python D:\miniconda3\envs\dps-studio\python.exe -B scripts/maintenance/check_repo_hygiene.py
```

The runner defaults to `artifacts/TASK-023/phase3b` and requires a fresh destination. Use an unused TASK-023 output directory for another replay. [Phase 3B runner](../../../scripts/research/task023/phase3_run.py) · [Pair calculation](../../../scripts/research/task023/phase3_pairs.py) · [Phase 3 tests](../../../tests/unit/test_task023_phase3.py)

### Center tables and channel cards

| Channel | Center table | Overview | Hard regions |
| --- | --- | --- | --- |
| 20201210m_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20201210m_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20201210m_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201210m_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20201210m_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201210m_ch1__zoom_onset.svg) |
| 20201211m_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20201211m_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20201211m_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201211m_ch1__overview.svg) | [weak PNG](../../../artifacts/TASK-023/phase3b/figures/20201211m_ch1__zoom_weak.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201211m_ch1__zoom_weak.svg) |
| 20201214m_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20201214m_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__zoom_onset.svg) · [decline_weak PNG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__zoom_decline_weak.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20201214m_ch1__zoom_decline_weak.svg) |
| 20221017a_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20221017a_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20221017a_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20221017a_ch1__overview.svg) | [weak PNG](../../../artifacts/TASK-023/phase3b/figures/20221017a_ch1__zoom_weak.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20221017a_ch1__zoom_weak.svg) |
| 20231019-ch1_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20231019-ch1_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20231019-ch1_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20231019-ch1_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20231019-ch1_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20231019-ch1_ch1__zoom_onset.svg) · [weak PNG](../../../artifacts/TASK-023/phase3b/figures/20231019-ch1_ch1__zoom_weak.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20231019-ch1_ch1__zoom_weak.svg) |
| 20260607_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260607_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch1__zoom_onset.svg) · [weak_unknown PNG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch1__zoom_weak_unknown.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch1__zoom_weak_unknown.svg) |
| 20260607_ch2 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260607_ch2.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch2__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch2__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch2__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch2__zoom_onset.svg) · [weak_unknown PNG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch2__zoom_weak_unknown.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260607_ch2__zoom_weak_unknown.svg) |
| 20260630-1_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260630-1_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch1__zoom_onset.svg) · [competing PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch1__zoom_competing.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch1__zoom_competing.svg) |
| 20260630-1_ch2 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260630-1_ch2.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch2__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch2__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch2__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch2__zoom_onset.svg) · [competing PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch2__zoom_competing.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-1_ch2__zoom_competing.svg) |
| 20260630-2_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260630-2_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch1__zoom_onset.svg) · [weak_competing PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch1__zoom_weak_competing.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch1__zoom_weak_competing.svg) |
| 20260630-2_ch2 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260630-2_ch2.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch2__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch2__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch2__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch2__zoom_onset.svg) · [weak_competing PNG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch2__zoom_weak_competing.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260630-2_ch2__zoom_weak_competing.svg) |
| 20260701_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260701_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch1__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch1__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch1__zoom_onset.svg) · [weak PNG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch1__zoom_weak.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch1__zoom_weak.svg) |
| 20260701_ch2 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_20260701_ch2.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch2__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch2__overview.svg) | [onset PNG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch2__zoom_onset.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch2__zoom_onset.svg) · [weak PNG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch2__zoom_weak.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/20260701_ch2__zoom_weak.svg) |
| ch3_ch1 | [CSV](../../../artifacts/TASK-023/phase3b/tables/phase3_centers_ch3_ch1.csv) | [Overview PNG](../../../artifacts/TASK-023/phase3b/figures/ch3_ch1__overview.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/ch3_ch1__overview.svg) | [active PNG](../../../artifacts/TASK-023/phase3b/figures/ch3_ch1__zoom_active.png) · [SVG](../../../artifacts/TASK-023/phase3b/figures/ch3_ch1__zoom_active.svg) |
