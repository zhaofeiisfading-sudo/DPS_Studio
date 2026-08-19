# TASK-020A Background Whitening Research Report

> EXPERIMENTAL — Background-normalized — Not production result

## Scope and mathematical definition

The tool computes linear STFT power `P=|Z|²`, then `N(f)=median_bg P`, `R=P/(N+epsilon)`, and `C=10 log10((P+epsilon)/(N+epsilon))`. The deterministic scale-aware epsilon is `max(float64.eps*max(N), float64.smallest_subnormal)`. MAD is diagnostic only.

## Quantitative results

| Case | Source | Channel | Raw bg spread dB | White bg spread dB | Baseline measured | Experimental gate-passing | New | Lost | Δf p95 abs Hz |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Good Case | 20260607.csv | pdv_channel_1 | 7.490 | 9.64e-14 | 390 | 397 | 10 | 3 | 2314338945.6695786 |
| Good Case | 20260607.csv | pdv_channel_2 | 4.458 | 7.75e-14 | 379 | 376 | 5 | 8 | 18698968.945881795 |
| Hard Case | ch1.csv | ch1 | 10.819 | 4.85e-14 | 51 | 55 | 7 | 3 | 4365945726.920845 |
| Hard Case | ch2.csv | ch2 | 3.535 | 1.38e-14 | 127 | 124 | 11 | 14 | 3172448969.794419 |
| Hard Case | ch3.csv | ch3 | 8.806 | 5.4e-14 | 44 | 52 | 19 | 11 | 3318469304.0735664 |
| Hard Case | ch4.csv | ch4 | 15.283 | 5.77e-14 | 52 | 62 | 24 | 14 | 4149289341.511249 |

Experimental weak-ridge assessment: **无明显改善**. This classification is based on gate-passing-frame balance plus frame-median spectral contrast; it is not a calibrated SNR claim.

## Production regression

Production changed: **NO**. STFT arrays, formal ridge, quality states, apparent velocity, corrected velocity, event candidate, and formal export content (excluding export timestamp) exactly match the pre-assessment baseline.

## Risks and boundary checks

The summary records DC and below-50-MHz contrast diagnostics separately. The production 0.05–6 GHz search band is unchanged. Frequency shifts, lost frames, and pre-event gate-passing frames must be reviewed channel by channel. MAD bands in figures are robust-scale diagnostics, not confidence intervals.

## Next step

Do not promote this algorithm. If the measured trade-off is accepted after human review, the only recommended continuation is TASK-020B: whitened candidate/ridge selection. Do not start it automatically.
