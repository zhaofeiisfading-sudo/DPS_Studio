# TASK-015 preregistered engineering experiment

2026-11-07. User request governs; attachment is a hypothesis source, not an execution specification. Python 3.12 canonical conda dps-studio environment; single-threaded numerical kernels. Independent Research .git; Production including .git and raw SHA-256 inventory precedes experiments. No push, merge, promotion, dependency installation or historical result deletion.

## Questions and frozen decision rules

1. Can a stationary low-frequency prior distinguish observable creep from a stronger high-frequency spur, without manufacturing zero velocity on drift/AC-coupled sub-cycle signals?
2. Do clipped short windows improve steps and turns on an integer physical time grid, and how does error in the operator boundary propagate?
3. Does a prefix background model help fixed clutter, and fail under drift/target-in-prefix/crossing as earlier evidence predicts?

Primary historical failure is missing OR |error| >77.5 m/s. Preserve historical branch definition: closer to labelled interfering component where separation >20 MHz, with missing reported separately. Add >30 m/s failure and >50 m/s error rates (these are NOT identical to branch identity error). Report candidate and gated RMSE, coverage, absence outputs, duration of support, boundary timing, step/valley distortion and cost. Use only exact common sample centers; never interpolate estimates or choose candidates with truth. Missing results stay in failure denominators. Bootstrap resamples paired RECORDS, not overlapping frames.

Controls: formal Balanced STFT 1024/64/4096; exact TASK-014 GUI stage mapping (Dechirp for acceleration, exclusion for noise, STFT elsewhere); TASK-014 research simple mapping as an additional replay control; simple stage parameter/window adaptation; specialized pool. Matching support/gates controls isolate low-frequency scoring, polynomial detrending, local nuisance projection/GLRT, boundary clipping, window length, slope sign and prefix background subtraction. Full candidate arrays and diagnostic flags remain available after rejection.

Development and held-out RNG blocks use 150000000 and 151000000 plus disjoint family offsets; no old TASK-008–014 seeds are reused. Novel families include low tone+strong spur, quadratic/exponential drift+spur, AC-coupled sub-cycle creep, high-tone stationary mislabel, boundary misplacement, positive/negative chirps, turns, fixed/drifting clutter, two branches, dropout, colored noise and pure noise. Additional historical generator replay uses fresh disjoint instance indices. Development may tune gate/strategy constants; freeze source hashes and routing before held-out execution. Do not tune on held-out outcomes; failures restrict recommendations.

Default promotion requires paired held-out failure non-inferiority (no material >2 percentage point increase in relevant strata), no material increase in absent-signal outputs, and benefit on accuracy or timing at reported cost. A win under accurate labels alone does not establish safety under incorrect labels. No default clutter subtraction without verified background identity. Research-only methods may remain available with explicit limits.

## Measurement semantics and scope

All frequencies are nonnegative real single-channel beat magnitudes. Synthetic apparent velocity = 1550e-9*f/2; real diagnostics remain Hz without a claimed optical calibration or physical identity. Motion state and observation quality are independent internally. Stationary label records an operator prior of zero, but never fills frequency/measurement arrays. Unreliable measurements are NaN; candidate values survive. No bridging/smoothing or prior-zero measurements are introduced.

Low-frequency raw model: polynomial baseline + optional locally fitted high-frequency sinusoid nuisance; alternative adds cosine/sine at trial f. Profile least squares estimates amplitudes and random phase. The residual improvement statistic is heuristic after nuisance estimation and frequency search, NOT a calibrated CFAR p-value or proof of physical target identity. Minimum cycles and conditioning prevent sub-cycle fits being advertised as measurements. AC-coupling and incorrect nuisance assumptions may remain non-identifiable.

All 13 raw files / 17 streams are diagnosed over full records. Real annotations, if used for sensitivity, must be labelled hypothetical; unknown full-record runs are the non-annotated control. No real RMSE/accuracy/physical branch claims.

## Figure contract

Quantitative grids in Python/matplotlib, 180 mm width, editable SVG + 300 dpi PNG, Arial, Okabe–Ito palette, closed axes and inward ticks. Figure 1: low-frequency counterexamples with candidate/accepted distinction. Figure 2: held-out failure/coverage and boundary timing, uncertainty across records. Figure 3: fixed/drifting clutter and retained failures. Figure 4: real Hz agreement/coverage, explicitly no truth. Source numerical tables and waveform/traces are retained. Plot conclusions follow outcomes, not expected wins.

## External literature verification

Report references are not accepted wholesale. Verified bibliographic leads: D. H. Dolan, Review of Scientific Instruments 81, 053905 (2010), DOI 10.1063/1.3429257 (PubMed 20515153); D. H. Dolan, RSI 91, 051501 (2020) (PubMed 32486719). Allison et al. time-domain Bayesian paper exists at arXiv:2508.13695 and RSI 96, 085203 (2025); numerical predictions from the attachment remain unverified and are not performance evidence. This task evaluates its own explicitly stated local models, not a reproduction of those full papers.
