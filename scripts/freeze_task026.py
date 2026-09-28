"""Exclusive, pre-observation registration of TASK-026."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dps_studio.research.task023e_waveform_benchmark import PROFILES
from dps_studio.research.task026_benchmark import registration
from dps_studio.research.task026_representation import CHIRP_RATES

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path: Path, data: Any) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, allow_nan=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


PROTOCOL = r'''# TASK-026 pre-observation protocol

Research only. Production/main, all existing tracked files and data/raw read-only.
No commit/push/merge/rebase/cherry-pick/promotion. Required new Obsidian note is the
sole explicitly requested external output. Source/git/tests > artifacts > notes.
TASK-024 = task023h_raw_domain_evidence/20260913T132656Z; TASK-025 =
task025_informative_interval/20260914T100937Z. Both LEGACY_DIAGNOSTIC.
Boundary snapshot captured before new source creation. Existing Research/Production
temporary-file deletions are inherited state, not this task's operations.

## Frozen physical inputs and methods
Both original profiles: Hann periodic; windows 768/512, hop128, nfft4096,
band 0.05–6 GHz, fs40 GHz. No detrend, padding, resampling, smoothing or denoising.
Raw bytes/time arrays unchanged; analysis kernels operate on temporary window arrays.
All methods receive only SignalRecord/profile/method, never truth or trajectory.
R0 calls original compute_stft/extract_global_path_candidates/three-point log refinement.
R1 uses f_hat=f-Im(S_dh/S_h)/(2pi), t_hat=t+Re(S_th/S_h), analytic periodic-Hann
derivative in 1/s. Retain power>1e-6*column max, strictly positive; numerical guard,
not an E1 interval gate. Deposit energy on nearest original time-frequency cell.
Exclude out-of-grid coordinates or time shifts exceeding half source window;
report retained energy. Time deposition can aggregate neighboring windows; its
effective data support can reach about two source-window lengths. Report this
support difference; no claim of equal independent sample counts with R0.
R2 is frozen as frequency-only ENERGY squeezing using those same f_hat coordinates,
with original time cells. This is the 'equivalent reassignment' option, not a claim
of invertible complex Fourier-SST or a reconstruction audit. No CWT fallback.
R3 uses raw local chirplet matching: max_c |sum h*x*exp[-i2pi(f*tau+c*tau²/2)]|,
tau centered at the original frame center. Fixed c bank [-2e17,2e17] step1e16 Hz/s.
No truth-seeded search, no phase unwrapping, no residual subtraction, no tracking.
Select frequencies from bank maximum envelope; read c at the selected discrete bin.
f uses original log sub-bin refinement; c stays grid-quantized. Strongest fit uses
weighted real cos/sin least squares, reports weighted SSE/signal energy. This is
evidence/residual quality, not calibrated uncertainty. Bank boundaries flagged.
Rate grid quantization half-step=5e15 Hz/s, not a confidence interval.

All four extract at most K20 with the ORIGINAL 2/T-window nonmaximum-suppression
spacing and background exclusion. This extraction limit is 104.167/156.25 MHz;
it is not a physical impossibility bound. Keeping it makes this a representation
comparison conditional on frozen peak extraction. Report that confound explicitly.
Zero-energy outputs NaN/NO_ESTIMATE; finite candidates HYPOTHESIS_UNCALIBRATED,
never automatically reliable detections. No fresh support threshold is trained.
R0 discrete peak is a diagnostic column only, not a fifth formal method.

## Independent units, split, synthesis
Exact seed list and every parameter in seed_registration.json. Seeds 26010000+row
index; no historical seeds reused. Test-only seeds 26990000..26999999.
Core 8 original families x instances8..23=128; call unchanged original generate_case.
Only seed/id/split changes. Instances8..11 CALIBRATION,12..23 HELD_OUT. No core
distribution adjustment. No profile leaks: both profiles inherit waveform split.
Controlled sweeps separate from core and never pooled to claim core improvement.
Each cell has 3 random-phase/noise waveform realizations: rep0 CALIBRATION,
rep1/2 HELD_OUT. No parameter fitting; calibration only basic sanity eligibility.
Controlled n2048 (51.2 ns), time center25.6 ns, evaluate |t-center|<=9.6 ns. All
original complete-window frames retained in saved arrays; focus is evaluator-only.
Gaussian additive noise, nominal pre-fade target SNR=A²/(2sigma²). Ratio is nuisance
amplitude/target pre-fade amplitude, never recalculated SNR after fades. No raw filter.
Single full factorial SNR[-20,-10,0,10,30] dB, carrier[1.3,3,4.7] GHz,
rate[0,+/-1e15,+/-1e16,+/-4e16] Hz/s, amplitude[.2,1] V. Additional temporary fade,
amplitude ramp, nonlinear chirp: carrier3 GHz, slope4e16, fade parameter[.05,.2,.7].
Temporary fade A*d inside |tau|<8 ns; ramp linearly A->A*d over record. Nonlinear
chirp curvature=(2*d-1)*8e23 Hz/s², phase integral analytic; d there controls curvature,
not amplitude. Linear-phase integration also analytic, unlike legacy left-step core.
Two-component factorial separation[25,50,100,150,250,500] MHz, same SNR grid,
ratio[.25,1,4], slope difference[0,2e15,1e16] Hz/s, fade[1,.1]. Target stationary;
nuisance f0+sep+dc*tau. Separate crossing/merging/diverging at ratio1,
dc=sep/12.8 ns; crossing f2=f0+dc*tau, merging f2=f0-dc*min(tau,0),
diverging f2=f0+dc*max(tau,0). Their exact equal-frequency intervals count unresolved.

## Sanity, order, metrics and gates
After all SINGLE calibration records (no held-out observation yet), method advances
to TWO and CORE iff high-SNR (30dB), stationary macro RMSE<=5MHz, valid>=.99 and
medium-chirp (|c|=1e16) RMSE<=20MHz. Passed/failed methods all retain Phase A results;
failed methods have explicit NOT TESTED Phase B/C rather than invented values.
Then execute SINGLE held-out, TWO/CORE calibration, TWO/CORE held-out once each.
No adjustment based on any benchmark result. Analytic test inputs precede code freeze.

Top-ranked estimate error against target, no oracle selection. Bias, RMSE, p95abs,
valid-estimate fraction, failure fraction (missing or |error|>200MHz), runtime.
Historical candidate recall any <=200MHz; report rank and nearest-candidate error
explicitly as evaluator-only optimistic diagnostics. Sub-bin shift and discrete vs
refined error separate. Missing estimates are misses, never silently removed from
failure/coverage. Conditional RMSE must be read with valid fraction.
Two-component resolution: both truth components present, distinct output indices,
one-to-one matching within min(50MHz, instantaneous separation/4). Exact coincidence
unresolved. Neighborhoods disjoint, unique component identity even if several candidates
are in one neighborhood. One wide peak never counts twice. All candidates <=K20.
Legacy nuisance_hz is latent even off-time: evaluator derives physical existence from
original family amplitude rules (including transient sine burst mask), never latent
finiteness alone. Preserve original raw/truth, no generator repair.
False candidate rate: fraction of finite hypotheses outside 200MHz of EVERY present
physical component, plus candidates/frame in original pure-noise core.
All metrics save numerators/denominators. Pooled rates separately from waveform-macro:
average profile metrics within waveform then average waveforms. Both profiles also
reported separately. Frames/profiles are not independent replicates. No significance
claims; plots use descriptive waveform SD where appropriate, no fabricated p-values.

SUPPORTED requires all on held-out:
1 SINGLE overall waveform-macro RMSE reduced>=10% OR fast linear chirp>=20%;
2 CORE and SINGLE/TWO target Candidate Recall >=R0 (macro AND each profile);
3 TWO resolution gain>=10 percentage points in at least one PREDEFINED hard region:
   CLOSE: instantaneous separation<=150MHz; LOW_SNR: SNR<=0; FADE:depth<1;
   CROSSING: crossing/merging/diverging. Whole benchmark and each region reported.
4 controlled SNR<=0 false-candidate fraction increase<=.02 AND core pure-noise
  mean candidates/frame increase<=1. Both output count and false fraction retained;
5 isolated runtime mean<=5x R0;
6 accuracy criterion (1) also holds at SNR<=0 OR hard-region gain(3) occurs in
  LOW_SNR or FADE. Gains confined to high-SNR cases fail.
Accuracy passes but no >=10pp separation gain -> MIXED; quantitative accuracy or
resolution improvement with any other gate failing -> MIXED; neither -> NOT SUPPORTED.
Only all conditions -> SUPPORTED. No omitted/not-implemented method can pass.
Runtime: full frontend incl STFT axes+candidate extraction; synthesis/evaluation/I/O
excluded. Save per-stream wall time under 4 process workers as throughput diagnostics.
For gate use isolated sequential timings, first registered held-out core waveform in
each of 8 families, plus first held-out stationary/fast/SNR=-20/crossing examples,
both profiles, 3 repeats, method order rotated by stream/repeat. No other work concurrently.
Include paired runtime ratios and mean; amortized library imports excluded.
Failure maps: SNR x separation, SNR x chirp, separation x amplitude ratio,
separation x chirp difference, separately each method/profile. Mask unsampled cells.
Representatives: first registered held-out stationary 10dB/carrier3GHz/amp1,
fast +4e16 same settings, crossing 10dB/sep150MHz. Also show -20dB matched cases.
No visual case selection from outcomes.

## Conditional downstream and interpretation
Phase D optional only if SUPPORTED. Among supported choose largest CORE macro
RMSE improvement, tie lower isolated runtime. Replace only candidate source;
freeze all P3/Beam/E4/acceptance. No backend modifications authorized in this task.
If none supported, Phase D and all real/ch3 evaluation explicitly SKIPPED.
If a method is supported, real remains optional behavioral-only after freeze;
ch3 evaluation-only, never configuration choice, no real accuracy claims.
All-method failure at low SNR/close sep may be LIKELY OBSERVATION-LIMITED only
with explicit caveat frozen extraction caps resolution; no identifiability proof.
Denoising future recommendation only if all methods fail in matched low-SNR cells
(frequency failure>=.2 OR resolution<=.5) but succeed in high-SNR counterpart
(failure<=.05 OR resolution>=.9), or measured noise-driven corruption dominates.
No denoising now. Future priority deterministic band limitation and known-interference
notches, preserving phase/frequency/chirp/edges and auditing false structure.

## Verification and sources
New tests + full pytest + Ruff + strict mypy + git diff --check; raw SHA-256 before/after,
all existing tracked file hashes and Production git state/HEAD/main refs unchanged.
Known inherited launcher tests reported separately if still failing. Exclusive-create
artifacts, never overwrite source data or legacy output. Stop after TASK-026.
Reassignment identities verified against official library source documentation:
https://librosa.org/doc/0.11.0/_modules/librosa/core/spectrum.html
Analytic chirp phase/frequency convention verified against SciPy reference:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.chirp.html
No bibliographic metadata or DOI inferred. Local bank and gate definitions above are
this experiment's methods, not claimed published optimal estimators.
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    assert (output/'boundary_before.json').is_file()
    if (output/'protocol.md').exists():
        assert (output/'protocol.md').read_text(encoding='utf-8') == PROTOCOL
        assert load_json(output/'seed_registration.json') == registration()
        assert not (output/'implementation_freeze.json').exists()
    else:
        with (output/'protocol.md').open('x', encoding='utf-8') as handle:
            handle.write(PROTOCOL)
        write_json(output/'seed_registration.json', registration())
    write_json(output/'method_configs.json', dict(profiles=[asdict(p) for p in PROFILES],
        methods=dict(R0='original Hann STFT + original Top20/refinement',
                     R1='time-frequency reassigned energy', R2='frequency-only energy squeezing',
                     R3='local chirplet bank'), chirp_rates_hz_per_s=CHIRP_RATES.tolist(),
        top_k=20, peak_separation_resolution_factor=2., power_guard_ratio=1e-6,
        historical_tolerance_hz=200e6, resolution_tolerance='min(50e6, separation/4)'))
    write_json(output/'frozen_manifest.json', dict(task='TASK-026',
        files={name: digest(output/name) for name in ('protocol.md', 'seed_registration.json',
                                                     'method_configs.json', 'boundary_before.json')}))
    print(f'Registered {len(registration())} waveforms before observation: {output}')


if __name__ == '__main__':
    main()
