"""Exclusive pre-registration, safety and held-out stages for TASK-027."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import hilbert  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.research import task027_denoising as m
from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, PROFILES, SAMPLE_RATE_HZ, WaveformCase, array_hash, generate_case, oscillator_phase,
)

ROOT = Path(__file__).resolve().parents[1]
FROOT = ROOT / 'artifacts/task023f_proposal_recall_recovery/20260912T100142Z'


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, default=lambda v: v.item())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


REVIEW = '''# Phase A evidence review / TASK-027

## A–D: route, actual experiment, rationale, early-stop plan
Route 1 selected: fixed linear-phase FIR low-pass with a guard band beyond the
existing 6 GHz analysis ceiling. Only one route enters experimentation.
It targets out-of-band noise/transient leakage through the finite Hann window.
TASK-024 scored unmodified raw; TASK-025 gated search permission; TASK-026 changed
representations without waveform filtering. None tested this intervention with
the complete fixed P3 backend. TASK-020 whitening is not present in current source;
docs/TASK-021A_REPORT.md says not merged. Its historical efficacy is UNVERIFIED,
not evidence that this different fixed linear filter has already succeeded/failed.
Expected benefit is modest: STFT already selects in-band peaks; a flat passband
cannot remove in-band noise or tell a strong nuisance from the physical target.
Risk: reflection transients, temporal spreading, passband droop and candidate-rank
changes that affect P3 support. Linear phase alone does not certify chirp safety.
Smallest falsification: independent clean safety battery, then 32 unchanged-core
and 32 O1–O8 fresh waveforms, two fixed profiles. Fail either gate -> stop.

Route 2 considered, NOT TESTED: impulsive robust sample replacement. It targets
isolated electronic spikes before their spectrum contaminates many bins; differs
from old path rescoring. It may help only documented sparse impulses, but nonlinear
replacement can clip real beat extrema and generate harmonics. Current legacy
reports do not establish isolated electronic clipping as the dominant failure.
A future known-impulse injection audit would falsify it via chirp/phase distortion;
no threshold or implementation is proposed for immediate testing here.

Route 3 considered, NOT TESTED: local candidate repair based on flanking anchors.
Targets O2/O5 but TASK-023B/C/D/F already contains excursion, jump, support, anchors,
core permission and local rescue. No independent new evidence justifies another
equivalent continuity rule. Fast physical drops and branch identity are the main
risks; O6/O8 would falsify it. No waveform phase change, but wrong selection directly
biases inferred frequency. Rejected as redundant, not a new negative experiment.

## Evidence read and interpretation
Current source, F frozen activation, F fresh_final_aggregates.csv, G report,
TASK-024 (historically task023h) report, TASK-025 report, TASK-026 report,
high_snr_chirp_bias_summary.csv and latest F/G/024/025/026 Obsidian logs reviewed.
F/P3 pooled RMSE 110.484 MHz vs strongest 137.676; harm 41 frames, fast harm 3.
G strict temporary score dip only 6/1699 legacy missing frames: no wider beam.
024 E1 +0.203 pp on an already 98.614% correct pair set; no low-SNR/fade gain.
025 active pure-noise rejection ~6%, temporary-fade recall ~95.7%: no E1 gate.
026 four-method low/high-SNR matched failure/success 83/84: noise is relevant,
but does not prove band limitation will help in-band noise.
Inspected F figure 07 and 026 frequency_error_vs_snr: the fixed F example is largely
unchanged, while low-SNR variance dominates the representation comparison.
All these observations are LEGACY_DIAGNOSTIC, never fresh TASK-027 performance.
Inherited Research deletions and untracked TASK-026 files are retained.

Authority for FIR convention: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.firwin.html
Odd tap count gives Type-I linear phase; cutoff is half amplitude. Our choice of
7 GHz, 129 taps and gates below is a preregistered engineering hypothesis, not a
published optimal PDV parameter set. No unverifiable DOI or physical claim is added.
'''

PROTOCOL = '''# TASK-027 pre-observation protocol

One route R1: 129-tap firwin lowpass, cutoff=7e9 Hz, Kaiser beta=8, scale=True.
Centered single-pass convolution after reflection by64 samples on both ends.
At40GHz support extends1.6ns each side. No filtfilt, decimation, resampling,
missing-value filling or data deletion. Original time array exactly preserved.
Nonuniform sampling or cutoff>=Nyquist is rejected. Save processed copies only.
Frequency passband of interest remains original0.05–6GHz. No adaptive cutoff.
Strongest and complete F/P3 are frozen controls; new=filtered waveform + same P3.
P3 activation/effective E4 copied literally from F, core/diversity enabled.
Hann windows768/512, hop128, nfft4096, Top-K20 and refinement unchanged.
Freeze all src Python and runner SHA-256 before any safety/held-out observation.
No calibration fitting, no pilot benchmark tuning; tests use disjoint seeds.

## Safety gate, before held-out
Each of4 independent seeds per condition at40GHz/8000 samples (200ns), SNR40dB.
Stationary f=.075,.5,3,5.8GHz; fast chirp3GHz plus +/-4e16Hz/s during75–125ns,
constant continuation outside; two tones3GHz and+150/+300MHz, amplitudes1/.8;
edge tone3GHz switches on at100ns. Both original STFT profiles. All complete
frames retained (including recording edges); additionally report interior.
Stationary absolute signed bias increase<=0.1MHz for EACH condition/profile;
fast-chirp RMSE<=1.05*raw+1kHz numerical floor, on75–125ns frames, each sign/profile.
Two-component distinct-candidate recall (tolerance min50MHz,sep/4) drop<=1pp.
No new >-30dB relative narrowband candidate farther than2/T from all present tones
in stationary/two cases; compare count against raw, each condition/profile.
Analytic envelope abs(hilbert), first crossings10/50/90% within +/-5ns of onset:
50% timing shift<=0.2ns, 10–90 width increase<=0.5ns in EACH edge waveform.
Fast-chirp waveform RMS ratio inside75–125ns in[.99,1.01].
Stationary complex projection phase difference<=.01rad after discarding only
the declared64-sample filter support in this evaluator (never from output).
Source/time hashes unchanged for every case; all gate conditions required.
Fail -> R1 NOT SUPPORTED (safety), stop filter experiments immediately after
the prespecified battery; core/stress/real tables carry explicit skipped reasons.

## Fresh held-out if safety passes
CORE: original generate_case, all8 families, instances8..11,32 independent seeds.
Distribution unchanged; only seed/id/split. Does not replace core with stress.
OBVIOUS: O1..O8 x4 seeds,16000 samples (400ns), fs40GHz, target3GHz,
noise sd=.15V, random phase. Event160–200ns. O1 target absent before160ns;
O2 local2.5V nuisance at4.3GHz with random phase walk increments sd.15rad;
O3 added broadband Gaussian noise sd12V in event plus20V impulses every80samples;
O4 target amplitude .03 in event; O5 wrong4.3GHz coherent component amplitude2;
O6 true drop4.5->1.5GHz over20ns from160ns, remains low; O7 clean;
O8 persistent equal-amplitude3/4.3GHz, both target labels evaluated on SAME output.
Truth comes only from waveform generation and evaluator. All methods receive
same original waveform. No frequency/ROI/truth enters preprocessing or backend.
O8 counts once in aggregate (labelA); labelB diagnostic saved separately, no
confidence/target-identity claim. All finite outputs HYPOTHESIS_UNCALIBRATED.
No E1 or automatic informative interval. No claim to solve O1 by filtering.

## Metrics and performance gate
200MHz branch tolerance (1550nm ->155m/s). Internal frequency Hz/time seconds;
velocity relation v_app=1550e-9*f/2, no corrected velocity or LiF calculations.
RMSE on finite target/output, missing counts wrong; truth coverage and all-record
coverage separate. Candidate Recall within200MHz; minimum amplitude rank within
tolerance; absent rank NaN with misses counted. New candidates retain provenance.
Report interventions vs raw strongest AND vs P3. Exact frequency changes saved;
material intervention threshold1MHz because filtering changes sub-bin estimates
without switching branch. Correction/harm = absolute error decrease/increase>1MHz;
all exact-sign changes also saved. Precision=corrected/material interventions;
harm=harmed/material interventions; missing output always harmed.
Normal preservation: strongest initially truth-near and slow (<5e15Hz/s), output
still truth-near AND differs from P3 by<=1MHz; O7 separately. Fast preservation:
O6 changing frames with initially correct P3 remain truth-near. Also exact equality.
Obvious jump correction: O2–O5 focus, raw strongest wrong>200MHz and has adjacent
jump>450MHz, final becomes truth-near. Additionally all focus wrong-frame recovery.
No-information false track: finite frequency on wholly target-absent STFT support
(mixed onset/dropout windows excluded from this denominator only). Finite fallback
counts false even if marked uncertain; credible-track rate not inferred.
Pooled counts and waveform-macro metrics (pool both profiles within waveform)
reported separately; frames/profiles are not independent experiments.
SUPPORTED requires on CORE AND OBVIOUS independently: >=10% RMSE reduction OR
>=10% relative wrong reduction vs P3, other metric<=1% relative degradation;
truth and overall coverage>=P3; harmed/valid and harm/interventions vs strongest
<=P3 (zero-intervention harm=0 only for gate, N/A in report); normal>=99%,
fast>=99%; no-info false<=P3. Also obvious jump correction improves>=10pp
vs P3 with nonzero denominator. Each profile also meets coverage/normal/fast.
No benefits only on extremes. Partial gains failing any requirement=MIXED;
no >=10% accuracy improvement in either dataset=NOT SUPPORTED. Stop, no tuning.
Safety/performance pass required before any new real34/ch3 evaluation; if eligible
freeze a real behavioral protocol before loading real observations. No real GT.
Known result-named.dat excluded. Manual focus not needed for this inexpensive FIR.
Full pytest/ruff/mypy --strict/diff check; inherited launcher failures separate.
Boundary hashes before/after; no Production/main/raw/git mutation.
'''


def register(output: Path) -> None:
    if not (output / 'boundary_before.json').exists():
        raise RuntimeError('Boundary snapshot must finish first')
    for name in ('waveforms', 'streams', 'tests', 'figures'):
        (output / name).mkdir(exist_ok=False)
    for name, content in [('phase_a_route_review.md', REVIEW), ('protocol.md', PROTOCOL)]:
        with (output / name).open('x', encoding='utf-8') as handle:
            handle.write(content)
    rows: list[dict[str, Any]] = []
    safety = ['stationary_0.075', 'stationary_0.5', 'stationary_3', 'stationary_5.8',
              'chirp_-1', 'chirp_1', 'two_0.15', 'two_0.3', 'edge']
    for j, family in enumerate(safety):
        rows.extend(dict(dataset='SAFETY', family=family, instance=i, seed=27010000+j*100+i)
                    for i in range(4))
    for j, family in enumerate(FAMILIES):
        rows.extend(dict(dataset='CORE', family=family, instance=i, seed=27020000+j*100+i)
                    for i in range(8, 12))
    for j in range(1, 9):
        rows.extend(dict(dataset='OBVIOUS', family=f'O{j}', instance=i, seed=27030000+j*100+i)
                    for i in range(4))
    write_json(output / 'seed_registration.json', rows)
    write_json(output / 'baseline_definition.json', read_json(FROOT / 'frozen_activation.json'))
    write_json(output / 'method_configs.json', dict(filter=asdict(m.FilterConfig()),
        profiles=[asdict(p) for p in PROFILES], top_k=20, tuning=False,
        methods=['strongest', 'P3', 'FIR_P3'], quality='HYPOTHESIS_UNCALIBRATED'))
    files = [*sorted((ROOT / 'src').rglob('*.py')), Path(__file__).resolve(),
             ROOT / 'scripts/evaluate_task027.py']
    files += [output / n for n in ('protocol.md', 'seed_registration.json',
                                   'baseline_definition.json', 'method_configs.json')]
    write_json(output / 'frozen_manifest.json', {p.relative_to(ROOT).as_posix(): digest(p)
                                                for p in files})
    print('REGISTERED before observation', flush=True)


def verify_freeze(output: Path) -> None:
    for name, expected in read_json(output / 'frozen_manifest.json').items():
        if digest(ROOT / name) != expected:
            raise RuntimeError('Frozen file changed: ' + name)


def case_for(row: dict[str, Any]) -> WaveformCase:
    family, seed, i = row['family'], row['seed'], row['instance']
    identifier = f'T27_{row["dataset"]}_{family}_{i}'
    if row['dataset'] == 'CORE':
        return replace(generate_case(family, i, seed), case_id=identifier,
                       observation_group=identifier, split='HELD_OUT')
    rng = np.random.default_rng(seed)
    safety = row['dataset'] == 'SAFETY'
    n = 8000 if safety else 16000
    t = np.arange(n) / SAMPLE_RATE_HZ
    target = np.full(n, 3e9)
    nuisance = np.full(n, np.nan)
    amplitude = np.ones(n)
    focus = (t >= (75e-9 if safety else 160e-9)) & (t < (125e-9 if safety else 200e-9))
    noise = rng.normal(0, np.sqrt(.5)*.01 if safety else .15, n)
    extra = np.zeros(n)
    phase = rng.uniform(-np.pi, np.pi, 2)
    if family.startswith('stationary_'):
        target[:] = float(family.split('_')[1])*1e9
    elif family.startswith('chirp_'):
        target += int(family.split('_')[1])*4e16*np.clip(t-100e-9, -25e-9, 25e-9)
    elif family.startswith('two_') or family == 'O8':
        nuisance[:] = target + (float(family.split('_')[1])*1e9 if safety else 1.3e9)
        extra = (.8 if safety else 1)*np.cos(oscillator_phase(nuisance, phase0=phase[1]))
    elif family in ('edge', 'O1'):
        amplitude[t < (100e-9 if safety else 160e-9)] = 0
    elif family in ('O2', 'O5'):
        nuisance[focus] = 4.3e9
        modulation = np.cumsum(rng.normal(0, .15, n)) if family == 'O2' else np.zeros(n)
        extra[focus] = (2.5 if family == 'O2' else 2)*np.cos(
            2*np.pi*4.3e9*t[focus]+phase[1]+modulation[focus])
    elif family == 'O3':
        noise[focus] += rng.normal(0, 12, int(focus.sum()))
        extra[np.flatnonzero(focus)[::80]] = 20
    elif family == 'O4':
        amplitude[focus] = .03
    elif family == 'O6':
        target = 4.5e9-3e9*np.clip((t-160e-9)/20e-9, 0, 1)
    voltage = amplitude*np.cos(oscillator_phase(target, phase0=phase[0]))+extra+noise
    truth = target.copy()
    truth[amplitude == 0] = np.nan
    return WaveformCase(identifier, family, i, 'SAFETY' if safety else 'HELD_OUT', seed,
        SignalRecord(t, voltage), truth, nuisance, focus, dict(row), identifier)


def safety(output: Path) -> None:
    verify_freeze(output)
    write_json(output / 'safety_started.json', {'unix_time': time.time()})
    rows = []
    for row in read_json(output / 'seed_registration.json'):
        if row['dataset'] != 'SAFETY':
            continue
        case = case_for(row)
        raw = case.record
        before = (array_hash(raw.time_s), array_hash(raw.voltage_v))
        filtered = m.preprocess(raw)
        unchanged = before == (array_hash(raw.time_s), array_hash(raw.voltage_v))
        unchanged &= np.array_equal(raw.time_s, filtered.time_s)
        common = dict(**row, time_and_source_unchanged=unchanged)
        family = row['family']
        phase_delta = 0.
        amplitude_ratio = 1.
        timing_shift = width_increase = 0.
        if family.startswith('stationary'):
            phase = oscillator_phase(case.truth_hz)[64:-64]
            projections = [np.sum(r.voltage_v[64:-64]*np.exp(-1j*phase))
                           for r in (raw, filtered)]
            phase_delta = float(abs(np.angle(projections[1]/projections[0])))
        if family.startswith('chirp'):
            amplitude_ratio = float(np.sqrt(np.mean(filtered.voltage_v[case.focus]**2)
                                              /np.mean(raw.voltage_v[case.focus]**2)))
        if family == 'edge':
            indices = np.flatnonzero(abs(raw.time_s-100e-9) <= 5e-9)
            crossings = []
            for record in (raw, filtered):
                envelope = abs(hilbert(record.voltage_v))
                crossings.append([float(record.time_s[indices[np.flatnonzero(
                    envelope[indices] >= level)[0]]]) for level in (.1, .5, .9)])
            timing_shift = abs(crossings[1][1]-crossings[0][1])
            width_increase = (crossings[1][2]-crossings[1][0])-(crossings[0][2]-crossings[0][0])
        arrays: dict[str, Any] = dict(time_s=raw.time_s, voltage_v=raw.voltage_v,
            filtered_v=filtered.voltage_v, truth_hz=case.truth_hz)
        for profile in PROFILES:
            observations = [m.frontend(record, profile) for record in (raw, filtered)]
            stft, _ = observations[0]
            ix = np.rint(stft.time_s*SAMPLE_RATE_HZ).astype(int)
            truth = case.truth_hz[ix]
            valid = np.isfinite(truth)
            if family.startswith('chirp'):
                valid &= case.focus[ix]
            metrics = []
            for method, (_, peaks) in zip(('raw', 'fir'), observations, strict=True):
                path = m.strongest(peaks)
                err = path[valid]-truth[valid]
                resolution = []
                ghosts = 0
                for k, frame in enumerate(peaks.candidates_by_frame):
                    physical = [truth[k], case.nuisance_hz[ix[k]]]
                    present = [v for v in physical if np.isfinite(v)]
                    if family.startswith('two'):
                        tol = min(50e6, abs(present[1]-present[0])/4)
                        hits = [[j for j, p in enumerate(frame)
                                 if abs(p.transition_frequency_hz-v) <= tol] for v in present]
                        resolution.append(any(a != b for a in hits[0] for b in hits[1]))
                    if frame and present:
                        ghosts += sum(p.peak_amplitude > frame[0].peak_amplitude*10**(-30/20)
                            and all(abs(p.transition_frequency_hz-v) >
                                    2*SAMPLE_RATE_HZ/profile.window_length_samples for v in present)
                            for p in frame)
                metrics.append(dict(rmse_hz=float(np.sqrt(np.mean(err**2))),
                    bias_hz=float(np.mean(err)), resolution=float(np.mean(resolution))
                    if resolution else 1., ghosts=ghosts))
                arrays[profile.profile_id.value+'_'+method] = path
            a, b = metrics
            checks = dict(time=bool(unchanged), phase=phase_delta <= .01,
                amplitude=.99 <= amplitude_ratio <= 1.01,
                edge=timing_shift <= .2e-9 and width_increase <= .5e-9,
                bias=not family.startswith('stationary') or abs(b['bias_hz']) <= abs(a['bias_hz'])+1e5,
                chirp=not family.startswith('chirp') or b['rmse_hz'] <= 1.05*a['rmse_hz']+1e3,
                resolution=b['resolution'] >= a['resolution']-.01,
                ghosts=not family.startswith(('stationary', 'two')) or b['ghosts'] <= a['ghosts'])
            rows.append(dict(**common, profile=profile.profile_id.value,
                **{'raw_'+k: v for k, v in a.items()}, **{'fir_'+k: v for k, v in b.items()},
                phase_delta_rad=phase_delta, amplitude_ratio=amplitude_ratio,
                edge_shift_s=timing_shift, edge_width_increase_s=width_increase,
                **{'pass_'+k: v for k, v in checks.items()}, passed=all(checks.values())))
        with (output / 'waveforms' / (case.case_id+'.npz')).open('xb') as handle:
            np.savez_compressed(handle, **arrays)
        print('SAFETY', case.case_id, flush=True)
    write_csv(output / 'safety_audit.csv', rows)
    checks = {key: all(bool(r[key]) for r in rows) for key in rows[0] if key.startswith('pass_')}
    write_json(output / 'safety_gate.json', checks)
    if not all(checks.values()):
        reason = 'SAFETY_GATE_FAILED: ' + ','.join(k for k, v in checks.items() if not v)
        for name in ('synthetic_results.csv', 'obvious_error_benchmark.csv', 'real_data_behavior.csv'):
            write_csv(output / name, [dict(status='SKIPPED', reason=reason)])
        write_json(output / 'skipped_stages.json', dict(core=reason, obvious=reason,
                                                       real=reason, ch3=reason))
    print(json.dumps(checks), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['register', 'safety'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().parent != ROOT / 'artifacts/task027_non_ai_open_exploration':
        raise ValueError('Output must be a new TASK-027 artifact')
    {'register': register, 'safety': safety}[args.stage](args.output.resolve())


if __name__ == '__main__':
    main()
