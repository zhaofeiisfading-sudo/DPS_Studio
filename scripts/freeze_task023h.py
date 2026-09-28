"""Create a new, immutable pre-observation audit protocol and boundary snapshot."""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from scripts.run_task023f_proposal_recovery import ROOT, frozen_configs, sha256, write_json
from dps_studio.research.task023e_waveform_benchmark import FAMILIES


PROTOCOL = """# TASK-024 request / TASK-023H artifact: preregistered raw-domain audit

Audit only. No new trajectory, scorer, selector, gate, Beam width, Top-K, STFT,
acceptance, band, budget, production edit, git write, AI or cross-scale evidence.
F/G results are LEGACY_DIAGNOSTIC. Source and git outrank historical reports.

## Fresh input and independent unit
128 new waveforms: original TASK-023E generate_case, all 8 families, instances
8..23; seed=2408000+100*family_index+instance. Only seeds/IDs change. Two frozen
profiles of each waveform are paired repeated measurements, never independent.
Recall is reported both on all valid truth frames and original strongest-error
frames, tolerance 200 MHz. A decrease >1 percentage point on error frames is
operationally called material (representation warning, never a K change).
All streams are processed; no result-based sampling, feature or threshold tuning.

## Frozen four statistics (higher is better)
Analytic z = scipy.signal.hilbert(real voltage), over the complete raw record.
Any nonfinite raw sample invalidates analytic construction; no fill/delete/filter.
This phase is a multicomponent mixture, not the independent target phase.
Frequency knots of the EXISTING proposal are sorted in physical time. Between
knots a declared piecewise-linear trajectory MODEL is evaluated on unchanged raw
sample times; the raw signal is never interpolated/resampled/smoothed. Integrate
this model with trapezoids using each actual raw time difference. No extrapolation.
One-knot paths have insufficient history and are flagged, not extended.
Window = inclusive first..last proposal knot, common to both pair members.
Analytic construction requires a uniform acquisition grid; phase integration
itself supports irregular sample times. No STFT hop replaces raw dt.

E1 = |sum(z exp(-i phi))|^2 / (N sum|z|^2). Complex constant amplitude is eliminated
analytically by least squares. It is scale invariant but can prefer a stronger
real nuisance component; normalization does not establish target identity.
E2 = FFT energy fraction of demodulated signal within |residual f|<=1/T_STFT,
T_STFT=window_length/fs (768 or 512 samples); rectangular analysis, no padding.
E3 = 1/(1+median(|residual phase increment/(2*pi*raw_dt)|)/(1/T_STFT)). Only adjacent
samples both above 0.1*local RMS analytic amplitude and |phase increment|<0.9*pi.
No unwrapping/interpolation. <50% valid adjacent samples => NaN with quality flag.
This is residual-frequency alignment, not pure variance with its mean removed.
E4raw = sum_j |sum_j demod|^2/N_j / sum|z|^2, exactly four contiguous equal-count
segments. Independent complex amplitudes, fixed phase, no frequency correction.
Minimum 16 raw samples. All four are evidence/coherence, NOT likelihood.
No additional feature, bandwidth search, segment search or learned combination.

## Pair construction, before seeing evidence
Use frozen Challengeable Core/Diversity B8 P3 only, original E4 arithmetic.
Terminal: one deterministic pair/window when a complete proposal has all valid
GT knots within 200 MHz and a competitor has at least one error >200 MHz.
Choose truth-near by minimum truth SSE, tie by ID. If E4 best is wrong, compete
against it (Selection loss); otherwise compare selected correct against cheapest
wrong (correct selection control). Unknown GT anywhere excludes strict pairs.
Pruning: source-frame-correct cohort extinction as G, literal G taxonomy via
unchanged four-step diagnostic. Compare lowest-cost complete truth-near prefix
among extinct nodes vs lowest-cost wrong retained prefix. Require all prefix GT
knots valid/near. Missing strict pairs are counted, NEVER fabricated or completed.
Also report source-cohort LOCAL pairs over last <=4 available prefix knots:
require >=2 knots, all GT valid, near on entire local segment, wrong competitor.
These are explicitly LOCAL_SUBPATH, not complete physical lineages. Primary gate
uses strict whole terminal/prefix pairs; local pairs separate exploratory diagnosis.
NO_VALID_DESCENDANT is negative control only and excluded from positive gates.
Save IDs, full frequency/rank provenance, costs, taxonomy, truth error, windows,
candidate hashes, waveform hashes and original immutable DAGs. No GT in evidence.
Legacy G events replay saved F graphs; never merge with fresh evaluation.

## Aggregation and gate
Ties within 1e-12 raw / 1e-9 original cost get 0.5 ranking credit; NaNs count as
unranked failures (0 credit), with finite coverage separately. Preservation and
rescue require strict correct ranking. Report pair-pooled AND waveform-macro,
with 2000 waveform-cluster bootstrap draws, seed 2408999. Original score=-cost.
Score differences reported by quantiles/histograms without cross-score units.
Net gain=(rescued errors - harmed original-correct)/all eligible pairs; also report
ordinary accuracy difference. Gate each of four independently, no blend:
overall improvement >=10 pp, persistent OR selection >=15 pp, preservation>=99%,
identity observation invariance, and positive gains in low-SNR (noise_sd>=.3 V),
fading (amplitude_exchange) AND smooth wrong branch (internal_wrong_core).
Use waveform-macro for primary thresholds, publish pooled sensitivity.
SUPPORTED requires all; MIXED requires >=10 pp overall and >=15 pp major but
failed preservation/strata; NOT SUPPORTED if major improvement <5 pp or otherwise
insufficient. MIXED-with-strong-signal for offline counterfactual additionally
requires preservation>=95%. If no qualifying feature, offline table header only
with reason. If clear failure, stop scorer exploration: complete fixed independent
identifiability and descriptive real diagnostics, no tuning/algorithm phase.

## Identifiability preregistered grid
Reuse original oscillator_phase and SignalRecord synthesis at 40 GHz, 80000
samples, additive iid real Gaussian noise. Controlled TWO-component experiment
is separate from unchanged fresh generator distribution. Full factorial:
separation [0,25,50,100,200,400] MHz; SNR [-10,0,10,20] dB;
amplitude ratio [.5,1,2]; chirp difference [-2e15,0,2e15] Hz/s;
fade depth [0,.8]. Fixed center=1 us, target=2.4 GHz, target phase=0,
nuisance phase=.7; fade applies inside center +/-32 ns; chirp localized continuously
to this region and held at boundary outside. Noise standard-normal samples shared
across grid, seed 24081000, scaled by stated SNR (unfaded target power .5 V^2).
Both profiles. Candidate test uses fixed peaks at central frame, distinct IDs
within half separation (max 200 MHz); zero separation cannot be distinct.
Known physical trajectories are SUPPLIED_TEMPLATE diagnostics, never mislabelled
frozen generated proposals. Generated proposal separability is separately measured
on frozen P3 searches intersecting the center, both branch histories within 200 MHz.
Known-template scores over center +/-T_STFT/2; signed differences and tie fractions
are descriptive of oscillator matching, not target-identity correctness.
Near-evidence tie diagnostic |difference|<=.01 (declared, not an output threshold).
Single-component local stationary iid Gaussian reference:
sigma_f=sqrt(12*sigma_noise^2/[A^2*(2*pi)^2*sum((t-mean(t))^2)*12]); equivalent
sqrt(2*sigma_noise^2/[A^2*(2*pi)^2*sum centered t^2]) after phase-cycle averaging.
Use latter explicit approximate Fisher result, REFERENCE ONLY; no multicomponent
impossibility claim. Verify against an explicit sinusoid Fisher matrix in tests.
Identity swap: 16 existing ambiguity observations, two labels, identical scores
per fixed proposal. OBSERVATIONALLY NON-IDENTIFIABLE regardless of ranking.

## Real data and optional absolute support
Only after synthetic definitions/code frozen: original 34 streams, unchanged
formal reader/analysis and saved F P3 proposals; strongest along every STFT frame
using declared local constant-frequency template over physical STFT window.
Save alternatives by proposal, differences vs strongest on same window; no labels.
ch3 full-record plots both profiles; no threshold/new interval, no real accuracy.
Also output E1..E4 distributions on GT-defined target-present/no-target synthetic
frames along strongest (not GT template). No informative interval threshold.

## Figures and verification
8 requested figures: ranking bars, difference histograms, fixed first available
persistent-pair demodulation, two sweep maps, identity example, two ch3 overlays.
PNG 300 dpi and vector PDF, colourblind palette; inspect rendered outputs.
If strict persistent pair missing, local example is explicitly labelled.
Tests: analytic construction, exact raw dt integration, scale invariance, phase
mask/NaN, identity-swap invariance, complete frozen candidate/proposal/score and
input immutability, source hash guard; pytest/ruff/strict mypy/diff check.
Existing launcher failures stay separate. All new output created exclusively.
"""


def main() -> None:
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    output = ROOT / 'artifacts/task023h_raw_domain_evidence' / stamp
    output.mkdir(parents=True, exist_ok=False)
    for folder in ('figures', 'streams', 'lineages', 'waveforms', 'tests', 'real_streams'):
        (output / folder).mkdir()
    snapshots = {}
    hashes = {}
    for name, root in (('Research', ROOT), ('Production', ROOT.parent / 'DPS_Studio')):
        snapshots[name] = {cmd: subprocess.check_output(['git', *cmd.split()], cwd=root,
            text=True).strip() for cmd in ('status --short --branch', 'rev-parse HEAD',
            'branch --show-current', 'rev-parse main', 'diff', 'diff --cached')}
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
        files = {root / p for p in tracked if (root / p).is_file()}
        files.update(p for p in (root / 'data/raw').rglob('*') if p.is_file())
        hashes[name] = {p.relative_to(root).as_posix(): sha256(p) for p in sorted(files)}
    write_json(output / 'frozen_manifest.json', dict(git=snapshots, hashes=hashes,
        configs=frozen_configs(), timestamp=stamp, task='TASK-023H', request='TASK-024'))
    with (output / 'protocol.md').open('x', encoding='utf-8') as handle:
        handle.write(PROTOCOL)
    write_json(output / 'seed_registration.json', [dict(family=family, instance=i,
        seed=2408000 + 100*j + i) for j, family in enumerate(FAMILIES) for i in range(8, 24)])
    write_json(output / 'metadata.json', dict(task='TASK-023H', request_title='TASK-024',
        artifact=str(output), timestamp=stamp, protocol_sha256=sha256(output / 'protocol.md'),
        source_priority='SOURCE_GIT_TESTS > ARTIFACT > OBSIDIAN > HISTORY',
        latest_f='20260912T100142Z', latest_g='20260913T082646Z',
        known_legacy_launcher_failures=2))
    print(output, flush=True)


if __name__ == '__main__':
    main()
