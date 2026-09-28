"""Create the TASK-025 registration before generating any benchmark samples."""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.run_task023f_proposal_recovery import ROOT, frozen_configs, sha256, write_json
from dps_studio.research.task023e_waveform_benchmark import FAMILIES

POSITIVE = ('low_snr', 'temporary_fading', 'amplitude_fading', 'fast_descent',
            'branch_crossing', 'branch_merge', 'broadband_target', 'leading_edge',
            'trailing_edge', 'short_segment')
NEGATIVE = tuple(f'H{i}' for i in range(8))

PROTOCOL = """# TASK-025: pre-observation protocol

TASK-024 is the historical task023h artifact 20260913T132656Z. All its observations,
and earlier observations, are LEGACY_DIAGNOSTIC and excluded from calibration/evaluation.
Source/git/tests > artifacts > Obsidian. Research only, production/main frozen.
No commit, push, merge, rebase, cherry-pick, promotion or raw modification.

## Independent units and seeds
Core: original generate_case, 8 families x instances 8..23 = 128 waveforms;
ONLY seed/ID/split changes. Instances 8..12 calibration, 13..23 held-out.
Separate H0..H7 and 10 positive stress families: 8 waveforms each; instances 0..2
calibration, 3..7 held-out. Two original profiles always share the waveform split.
272 independent waveform groups, 544 profile streams; no inference of independence
from profile count. No stress sample replaces a core waveform. Raw synthesis is
40 GHz, 80000 samples, original oscillator_phase and SignalRecord. No preprocessing.
Core seed=25010000+100*family_index+instance; H=25020000+100*family_index+instance;
positive=25030000+100*family_index+instance. Test-only seeds=25990000..25999999.

## Stress distribution (fixed before observation)
All stress records: carrier U[1.8,3.0] GHz, center U[0.7,1.2] us,
duration U[20,150] ns, phase U[-pi,pi], iid Gaussian noise sd U[0.15,0.5] V.
H0: noise only. H1: noise plus sd 3 V Gaussian burst on [center,center+duration).
H2: stationary unit-amplitude coherent component. H3: unit component slope
-1.5e15 Hz/s. H4: unit component only on [center,center+duration).
H5: unit component plus 0.8 V component at carrier+0.7 GHz, phase offset .7.
H6: H2 plus H1 burst. H7: .4 V stationary pickup at 1.25 GHz with fixed phase .3.
All H labels remain TARGET_ABSENT. H0/H1 and H4 off-time are LOW_INFORMATION;
H2..H7 on-time are STRUCTURED_BUT_AMBIGUOUS, including H6 burst. These labels
come from synthesis components, never from E1 or observed detector outcomes.
Positive default: unit target, 2.4 GHz nominal randomized carrier, no nuisance.
low_snr: entire-record target SNR cycles [-10,-5,0] dB by instance modulo 3,
noise sd=sqrt(.5/10^(SNR/10)); target stays present regardless of detectability.
temporary_fading: target amplitude .05 V in focus, 1 V elsewhere.
amplitude_fading: amplitude decreases linearly 1 -> .02 V through focus, then
remains .02 V; focus for evaluation is all time at/after center.
fast_descent: target 5 -> .7 GHz linearly during original duration, held outside.
crossing/merge: unit target plus 1.2 V nuisance in focus, separation
1.2 GHz*(1-2*ramp) or 1.2 GHz*(1-ramp), respectively.
broadband_target: H1 burst plus target. leading_edge: target begins at center;
trailing_edge: target ends at center; short_segment: target only in
[center,center+U[10,40]ns). Hard boundaries are intentional stress, no taper.

## Frozen detectors and calibration
Primary E1: directly call TASK-024 analytic_signal on full raw waveform and
demodulated_evidence on unchanged raw samples center-T_STFT/2 <= t < center+T_STFT/2,
constant strongest candidate frequency. No GT, final path, manual interval or
proposal input. Exact existing normalization, phase integration, Hilbert, bandwidth,
four segments; no new E1 implementation. Only B0=returned analytic RMS in V and
B1=strongest candidate peak_to_background_db. No stacking or extra features.
One threshold per detector shared across both profiles and all datasets.
Calibration positives are ALL target-present frames from core and positive stress.
Choose highest observed finite calibration value satisfying pooled target recall
>=.995, including nonfinite values as misses. Compare with >=, count ties exactly.
No feasible threshold => NOT SUPPORTED, no threshold retuning. Baselines follow
the same rule. Save thresholds before held-out generation/evaluation. No held-out
or real value participates. Descriptive curves use saved scores after final
evaluation, separately by split; curves never feed threshold selection.

## Frames, intervals and estimands
SUPPORTED_FRAME = finite statistic >= threshold. At least 4 consecutive supported
frames create a segment, then extend by existing context_time_s=16 ns in actual
frame-center time on each side; union overlaps. No gap filling beyond this fixed
context. Thresholding changes only a Boolean search permission mask.
An undefined E1 is a flagged miss, never filled; finite strongest output is copied
for the entire record, including rejected frames. No NaN, crop, resample, smooth,
interpolate, delete or gate-induced frequency replacement in the complete output.
GT target presence = finite truth at the STFT frame center. Structured support =
target-present OR known coherent nuisance on-time. For core, absent truth is
noise/dropout (original generator has no nuisance there). Positive stress weak
target frames remain target-present, never relabelled as LOW_INFORMATION.
Fast-descent stratum is the actual ramp only (not whole waveform); temporary
fading is .05 V focus only; amplitude fading is at/after center. Core fast ramp
uses registered center/duration, core amplitude_exchange focus separately reported.
Target edge = first and last 4 target frames of EVERY maximal truth-present run.
Also report leading/trailing separately. Low SNR core is noise sd>=.3 V;
stress low SNR separately. Crossing, merge, broadband and short segments separate.
Pooled ratios sum numerators/denominators. Waveform-macro first combines profiles
within a waveform, then averages defined waveform ratios. Also stratify profile,
dataset and family; profile is never an independent experimental unit. Missing
denominators are NA, not zero. No population claim or unregistered significance test.
Both raw SUPPORTED_FRAME and final SEARCH_ACTIVE masks are evaluated. FNR=1-recall;
search-active fraction and 100% finite output coverage explicit.
Target-segment recall: fraction of true runs overlapped by >=1 active frame;
also >=99% run coverage and fully-covered run fractions to prevent weak overlap
from hiding misses. Boundary miss: missed leading/trailing truth frames, plus
prefix/suffix consecutive missed frames and corresponding physical seconds.
Fragmentation: number of disjoint active runs intersecting each truth run; publish
mean fragments and excess max(fragments-1,0). Segments stay nested within waveform.

## Phase B and verdict gates (no tuning after results)
For BOTH supported-frame and final interval-active masks, BOTH pooled and waveform
macro on held-out require target recall>=.99, actual fast-descent recall>=.99,
temporary-fading focus recall>=.98, leading AND trailing target-edge recall>=.98,
pure-noise/dropout rejection>=.80, finite full-output coverage=1.
Test these on combined datasets and separately on each profile, avoiding profile
averaging hiding a failure. No post-hoc stress exclusion. Failure of any gate
stops before Phase C and before new real-data evaluation; all skipped tables retain
headers and skipped_stages.json gives reasons. Complete fixed Phase B reporting,
plots and validation only; no rerun of held-out or new threshold/features.
Signal-support separability SUPPORTED requires .99 structured recall and .80 low
information rejection on held-out, both aggregation modes; MIXED if either alone;
otherwise NOT SUPPORTED. Hard-negative robustness applies to STRUCTURE, not target
identity: require .80 rejection separately H0/H1 and .99 activation for coherent
H2..H7 on-time; both aggregation modes. MIXED if only some pass. Always separately
report target false positives in coherent negatives without changing their labels.
Informative interval SUPPORTED only if Phase B all pass, otherwise NOT SUPPORTED.

## Conditional Phase C / real evaluation
Only after B passes, same original frozen P3 core/diversity B8/E4/acceptance.
G0 searches all original eligible windows. G1 searches a window only if its ENTIRE
original search-frame set lies in automatic intervals; no clipping/reanchoring or
proposal redesign. Outside automatic intervals final equals strongest exactly.
Report boundary-crossing skipped windows, since all-or-none gating can lose rescue.
Compare on fresh held-out core and stress separately: original auditor Candidate,
Terminal Proposal, Final Correction Recall, RMSE, wrong, precision/harm, corrected
and harmed frames, 100% coverage; harms split by known states (no causal presumption).
Measure proposal count, windows, active fraction, wall search seconds, mean/p95 and
process lifetime peak memory. Include detector and original preparation costs
separately; generating original diagnostics can itself be expensive.
Engineering support: proposal or time reduction>=40%, RMSE ratio<=1.02,
wrong increase<=.001 and no coverage loss. Cost gain with excessive loss=MIXED
performance, engineering NOT SUPPORTED; otherwise explicit gates per requirement.
If B passes, real 34 streams only after thresholds/code/config freeze: behavioral
E1/support/quality, intervals, modifications/ranks, timing and proposals. Any
relatively-good stream modification>5% flags risk. No real truth/accuracy claims.
ch3 manual middle-region statement is qualitative (no numeric bounds supplied),
annotate as such without inventing a numerical manual mask. It never enters code.
If B fails, ch3/real artifacts and plots explicitly SKIPPED, not reused legacy as
fresh evaluation. Production potential RESEARCH_ONLY if B fails; PROMISING only
if B and conditional engineering/performance gates all pass; never promotion.

## Integrity / delivery
Freeze all pre-existing tracked files, both raw trees and production tracked files;
verify SHA-256 at completion and both main refs/HEAD/status. No legacy overwrite.
New tests, full pytest (known launcher failures separate), Ruff, strict mypy and
git diff --check. All benchmark outputs exclusive-create. Required light Obsidian
log is the sole explicitly requested external output; all code/data/artifacts stay
Research. This is inference scheduling research, NOT waveform denoising.
"""


def snapshot(root: Path) -> dict[str, Any]:
    commands = ('status --short --branch', 'rev-parse HEAD', 'branch --show-current',
                'rev-parse main', 'diff', 'diff --cached')
    git = {cmd: subprocess.check_output(['git', *cmd.split()], cwd=root,
                                       text=True).strip() for cmd in commands}
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    files = {root / p for p in tracked if (root / p).is_file()}
    files.update(p for p in (root / 'data/raw').rglob('*') if p.is_file())
    return dict(git=git, hashes={p.relative_to(root).as_posix(): sha256(p)
                                for p in sorted(files)})


def main() -> None:
    output = ROOT / 'artifacts/task025_informative_interval' / datetime.now(UTC).strftime(
        '%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True, exist_ok=False)
    for name in ('waveforms', 'streams', 'figures', 'tests'):
        (output / name).mkdir()
    registration = []
    for dataset, families, indices, base in (
        ('CORE', FAMILIES, range(8, 24), 25010000),
        ('HARD_NEGATIVE', NEGATIVE, range(8), 25020000),
        ('POSITIVE_STRESS', POSITIVE, range(8), 25030000),
    ):
        for j, family in enumerate(families):
            for i in indices:
                split = 'CALIBRATION' if i < (13 if dataset == 'CORE' else 3) else 'HELD_OUT'
                registration.append(dict(dataset=dataset, family=family, instance=i,
                    seed=base+100*j+i, waveform=f'T25_{dataset}_{family}_{i:02d}', split=split))
    with (output / 'protocol.md').open('x', encoding='utf-8') as handle:
        handle.write(PROTOCOL)
    write_json(output / 'seed_registration.json', registration)
    write_json(output / 'threshold_protocol.json', dict(recall=.995, operator='>=',
        rule='highest observed calibration value meeting pooled recall',
        detectors=['E1', 'B0_RMS', 'B1_SPECTRAL'], shared_profiles=True,
        minimum_frames=4, context_time_s=16e-9, held_out_runs=1))
    write_json(output / 'frozen_manifest.json', dict(task='TASK-025',
        Research=snapshot(ROOT), Production=snapshot(ROOT.parent / 'DPS_Studio'),
        configs=frozen_configs(), protocol_sha256=sha256(output / 'protocol.md'),
        seed_sha256=sha256(output / 'seed_registration.json'),
        threshold_protocol_sha256=sha256(output / 'threshold_protocol.json')))
    print(output, flush=True)


if __name__ == '__main__':
    main()
