"""Exclusive-output TASK003 research runner and historical diagnostic replay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.core.analysis_profiles import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.research import denoising_task001 as m2
from dps_studio.research import denoising_task001_benchmark as old1
from dps_studio.research import denoising_task002 as old2
from dps_studio.research import denoising_task003 as risk
from dps_studio.research import denoising_task003_benchmark as bench
from dps_studio.research import task028_consolidation as frozen

ROOT = Path(__file__).resolve().parents[3]
OLD1 = Path('D:/Research/DPS_Denoising_Runs/TASK-001/20261014T115200Z')
OLD2 = Path('D:/Research/DPS_Denoising_Runs/TASK-002/20261015T060621Z')
PROFILES = (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)

PROTOCOL = """# TASK-003 protocol, registered before fresh outcomes

H1: continuous original spectral support plus similar competing amplitudes can flag
unsafe bridging. H2: a single-channel superposition has a label-permutation symmetry
without an external target-identity constraint. Classifier failure is not proof of H2.
Historical TASK001/002 outcomes are development evidence ONLY, including their held-out.

Fresh: 12 contexts x 2 polarities x (2 TRAIN + 2 CALIBRATION + 4 HELD_OUT) =192
independent voltage waveforms,384 paired profile streams. Each context has repair
opportunity and true-change counterexample variants. Normal segments occur in all;
normal family is a normal-context short probe, not an all-clean control. Long-error
and no-target families include a separate short probe so safety cannot win by doing
nothing. No-target intervals have no frequency GT and are excluded only from GT
metrics, never from candidate coverage. Each waveform is wholly assigned one split.
Seeds43010000/43020000/43040000 +100*family+10*variant+instance. Check historical
registrations for collisions; record all voltage hashes. Actual voltage -> frozen
STFT -> frozen Top20 -> frozen P3. No ideal spectral inputs or altered P3/M2 defaults.

Models: M0 Strongest; M1 frozen P3; M2 frozen TASK001 repair. R1 vetoes whole proposals
with original background>=12dB for >=80% of interval and a continuous supported
frame-center run>=12.8ns with adjacent steps<=200MHz. R2 additionally requires median
absolute original/proposed amplitude ratio in dB <=b. Only b=3 or4 dB considered;
these bracket the historical harm cluster, explicitly a development-derived prior.
No further tuning. TRAIN diagnoses mechanics; CALIBRATION selects R2 b maximizing
corrected-harmed, among gates below if feasible, otherwise best diagnostic point.
Ties prefer smaller b (retain more proposals). R1 is deliberately broad safety
ablation, not a claim that persistent spectra prove correct physical identity.
M3 is the single calibration-frozen R2. R1 and both thresholds reported without
post-held-out selection. All-veto is a negative-control behavior, not success.

Primary engineering gates (all required): reduce new harm vs M2 by>=75%, retain
>=70% of M2 correct repairs, >=20 corrections; candidate coverage1; pooled RMSE
<=1.02*M2 and <=Strongest; normal accuracy no lower than M2; fast accuracy no
lower than M2 and already-correct P3 fast preservation>=.995; no family's wrong
fraction exceeds M2 by>.005; paired waveform macro RMSE M3-M0 bootstrap95% upper<=0.
If M2 harm=0, safety is NOT ESTIMABLE and cannot pass. If M2 corrected=0, retention
is NOT ESTIMABLE. Report family and waveform bootstrap intervals and denominators.
Calibration failure does not cancel the once-only held-out diagnostic, but blocks
real-data entry. No held-out threshold changes. Real evaluation only if both
calibration and held-out satisfy complete gates, otherwise SKIPPED.

Wrong=abs(error)>200MHz or nonfinite. Every present center including weak/transition
windows contributes. Fast=STFT support touches true rate>5e15Hz/s. Precision=corrected/
all changed present frames, including wrong-to-wrong; harm rate=harmed/same denominator.
Compare against both P3 and Strongest. Report rejected beneficial (corrected>0) and
harmful (harmed>0) proposals, including mixed proposals in both counts, and frame
benefits lost/harms avoided. Risk recall=harmful rejected/harmful; false positive
rate=nonharmful rejected/nonharmful, no identity probability claim.
Bootstrap4000 paired waveform resamples, seed43099003, combine two profiles SSE/count
before waveform RMSE. Fixed mixture of contexts is not real-world prevalence.

H2 control uses one independently seeded voltage under two target label assignments;
identical voltage and all processing inputs, different GT separated>400MHz. Assert
identical outputs and show deterministic output cannot be within200MHz of both.
No extra independent N from relabeling. AI NOT JUSTIFIED: only five historical
harm waveforms and no independent identity observable established. No AI fit.
Validated frequencies remain NaN; ambiguous flags invite manual review. Veto retains
P3 as a hypothesis, not a certified measurement. No new true velocity exports.
No Production/OLD/raw edits, commit/push/merge/promotion, dependencies, or Junction
writes. Outputs created exclusively. Stop after report, tests, boundary and log.
"""


def source_hashes() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('src', 'configs') for p in (ROOT/folder).rglob('*')
            if p.is_file() and '__pycache__' not in str(p)}


def prepare(out: Path) -> None:
    cfg = configs()
    cfg['risk'] = asdict(risk.RiskConfig())
    cfg['balance_candidates_db'] = [3., 4.]
    write_json(out/'method_configs.json', cfg)
    records = bench.registration()
    seeds = {r['seed'] for r in records}
    historical_seeds: set[int] = set()
    for folder in (OLD1, OLD2):
        for name in ('seed_registration.json', 'seed_registration_addendum.json'):
            if (folder/name).exists():
                historical_seeds.update(r['seed'] for r in json.loads((folder/name).read_text()))
    assert len(seeds) == len(records) and not seeds & historical_seeds
    write_json(out/'seed_registration.json', records)
    write_json(out/'seed_collision_audit.json', dict(fresh=len(seeds), collisions=[],
        historical_count=len(historical_seeds), historical_role='development only'))
    with (out/'protocol.md').open('x', encoding='utf-8') as f:
        f.write(PROTOCOL)
    write_json(out/'source_freeze.json', source_hashes())
    write_json(out/'prepared.json', dict(utc=datetime.now(timezone.utc).isoformat(),
                                        profiles=[asdict(p) for p in PROFILES]))


def run_split(out: Path, split: str) -> None:
    manifest = json.loads((out/'source_freeze.json').read_text())
    assert source_hashes() == manifest, 'Source drift after registration'
    if split == 'CALIBRATION':
        assert (out/'train_completed.json').exists()
    if split == 'HELD_OUT':
        assert (out/'calibration_freeze.json').exists()
    key = split.lower()
    write_json(out/f'{key}_started.json', dict(utc=datetime.now(timezone.utc).isoformat()))
    cfg = configs()
    records = [r for r in bench.registration() if r['split'] == split]
    metrics_rows: list[dict[str, Any]] = []
    proposals_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    started = time.perf_counter()
    for n, r in enumerate(records):
        case = bench.generate(r['family'], r['variant'], r['instance'], split)
        for profile in PROFILES:
            meta = dict(**r, profile=profile.profile_id.value)
            tick = time.perf_counter()
            stft, peaks = frozen.frontend(case.record, profile)
            frontend_s = time.perf_counter()-tick
            tick = time.perf_counter()
            result = frozen.consolidate(stft, peaks,
                                       frozen.FinalMethodConfig.from_dict(cfg['frozen_p3']))
            p3_s = time.perf_counter()-tick
            paths = {'M0': result.trajectories['M0'].frequency_hz,
                     'M1': result.trajectories['M2'].frequency_hz}
            tick = time.perf_counter()
            proposals = m2.propose_repairs(stft, peaks, paths['M1'], m2.RepairConfig(**cfg['repair']))
            paths['M2'], _ = m2.apply_repairs(peaks, paths['M1'], proposals)
            repair_s = time.perf_counter()-tick
            risks = {}
            cost = {}
            for name, rule, balance in (('R1', 'R1', 3.), ('R2_B3', 'R2', 3.),
                                        ('R2_B4', 'R2', 4.)):
                tick = time.perf_counter()
                paths[name], _, risks[name] = risk.risk_repair(peaks, paths['M1'], proposals,
                    rule=rule, config=risk.RiskConfig(maximum_balance_db=balance))
                cost[name] = time.perf_counter()-tick
            labels = old2.frame_labels(case, stft.time_s, stft.window_length_samples)
            truth = labels['truth']
            valid = np.isfinite(truth)
            recall = np.array([any(abs(c.transition_frequency_hz-truth[i]) <= 200e6
                                   for c in frame) for i, frame in enumerate(peaks.candidates_by_frame)])
            for name, path in paths.items():
                for reference in ('M0', 'M1'):
                    counts = old2.metrics(path, paths[reference], labels)
                    metrics_rows.append(dict(**meta, method=name, reference=reference, **counts,
                        **old2.ratios(counts), candidate_recalled=int((valid & recall).sum()),
                        path_sha256=hash_array(path)))
            for p_id, p in enumerate(proposals):
                ix = p.frame_indices
                a = abs(paths['M1'][ix]-truth[ix]) > 200e6
                b = abs(paths['M2'][ix]-truth[ix]) > 200e6
                corrected = valid[ix] & a & ~b
                harmed = valid[ix] & ~a & b
                for name in risks:
                    proposals_rows.append(dict(**meta, method=name, **risks[name][p_id],
                        proposed_frames=len(ix), corrected=int(corrected.sum()),
                        harmed=int(harmed.sum())))
                for k, i in enumerate(ix):
                    frame_rows.append(dict(**meta, proposal_id=p_id, frame=int(i),
                        time_s=float(stft.time_s[i]), truth_hz=float(truth[i]) if valid[i] else None,
                        original_hz=float(paths['M1'][i]), proposed_hz=float(paths['M2'][i]),
                        corrected=bool(corrected[k]), harmed=bool(harmed[k]),
                        fast=bool(labels['fast'][i]), normal=bool(labels['normal'][i]),
                        **{name+'_rejected': risks[name][p_id]['rejected'] for name in risks}))
            provenance.append(dict(**meta, voltage_sha256=hash_array(case.record.voltage_v),
                parameters=json.dumps(case.parameters), frontend_s=frontend_s, p3_s=p3_s,
                m2_increment_s=repair_s, **{k+'_increment_s': v for k, v in cost.items()},
                proposals=len(proposals), validated_frequency_state='ALL_NAN_IDENTITY_UNVALIDATED'))
            # Compact preselected contexts: first held-out instance only, no waveform archive.
            if split == 'HELD_OUT' and r['instance'] == 0 and r['family'] in (
                    'anchor_exchange', 'obvious_jump', 'nonlinear_valley'):
                band = (stft.frequency_hz >= .05e9) & (stft.frequency_hz <= 6e9)
                with (out/f"example_{case.case_id}_{profile.profile_id.value}.npz").open('xb') as f:
                    np.savez_compressed(f, time_s=stft.time_s, frequency_hz=stft.frequency_hz[band],
                        magnitude=np.abs(stft.spectrum[band]).astype(np.float32), truth_hz=truth,
                        M0=paths['M0'], M1=paths['M1'], M2=paths['M2'], R1=paths['R1'],
                        R2_B3=paths['R2_B3'], R2_B4=paths['R2_B4'])
        print(f'{split} {n+1}/{len(records)} {case.case_id}', flush=True)
    write_csv(out/f'{key}_metrics.csv', metrics_rows)
    write_csv(out/f'{key}_proposals.csv', proposals_rows)
    write_csv(out/f'{key}_frames.csv', frame_rows)
    write_csv(out/f'{key}_provenance.csv', provenance)
    assert source_hashes() == manifest
    write_json(out/f'{key}_completed.json', dict(seconds=time.perf_counter()-started,
        independent_waveforms=len(records), streams=len(provenance),
        utc=datetime.now(timezone.utc).isoformat()))


def write_json(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open('x', encoding='utf-8', newline='') as f:
        names = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def hash_array(value: Any) -> str:
    return hashlib.sha256(value.tobytes()).hexdigest()


def configs() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads((OLD1/'method_configs.json').read_text())
    assert cfg['repair'] == asdict(m2.RepairConfig())
    assert cfg['frozen_p3'] == frozen.FinalMethodConfig().to_dict()
    return cfg


def historical(out: Path) -> None:
    """All seven held-out harmful proposals, nearby successful families, D001 successes."""
    cfg = configs()
    with (OLD2/'held_out_proposals.csv').open() as f:
        original = list(csv.DictReader(f))
    harmed = [r for r in original if r['kind'] == 'M2' and int(r['harmed']) > 0]
    selection = {(r['family'], int(r['instance'])) for r in harmed}
    # Matched duration/instance successes across the same frozen historical split.
    selection |= {(family, i) for family in ('wrong_burst', 'asymmetric_envelope')
                  for i in (1, 3, 7)}
    rows: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    replays: list[dict[str, Any]] = []
    jobs = [('TASK002', f, i) for f, i in sorted(selection)]
    jobs += [('TASK001', 'jump', i) for i in (0, 1, 2)]
    for source, family, instance in jobs:
        case: Any = (old2.generate(family, instance, 'HELD_OUT') if source == 'TASK002'
                     else old1.generate(family, instance, 'HELD_OUT'))
        for profile in PROFILES:
            stft, peaks = frozen.frontend(case.record, profile)
            result = frozen.consolidate(stft, peaks,
                                        frozen.FinalMethodConfig.from_dict(cfg['frozen_p3']))
            baseline = result.trajectories['M2'].frequency_hz
            proposals = m2.propose_repairs(stft, peaks, baseline, m2.RepairConfig(**cfg['repair']))
            path, _ = m2.apply_repairs(peaks, baseline, proposals)
            truth = case.truth_hz[np.rint(stft.time_s * old2.FS_HZ).astype(int)]
            replays.append(dict(source=source, case_id=case.case_id,
                                profile=profile.profile_id.value,
                                voltage_sha256=hash_array(case.record.voltage_v),
                                M1_sha256=hash_array(baseline), M2_sha256=hash_array(path)))
            for n, p in enumerate(proposals):
                ix = p.frame_indices
                valid = np.isfinite(truth[ix])
                a = abs(baseline[ix] - truth[ix]) > 200e6
                b = abs(path[ix] - truth[ix]) > 200e6
                meta = dict(source=source, case_id=case.case_id, family=family, seed=case.seed,
                            profile=profile.profile_id.value, proposal_id=n,
                            first=p.first, stop=p.stop)
                rows.append(dict(**meta, **risk.diagnostics(peaks, baseline, p),
                                 corrected=int((valid & a & ~b).sum()),
                                 harmed=int((valid & ~a & b).sum())))
                for k, i in enumerate(ix):
                    before = min(peaks.candidates_by_frame[i],
                                 key=lambda c: abs(c.transition_frequency_hz-baseline[i]))
                    after = peaks.candidates_by_frame[i][p.candidate_indices[k]]
                    frames.append(dict(**meta, frame=int(i), time_s=float(stft.time_s[i]),
                        original_hz=float(baseline[i]), proposed_hz=float(path[i]),
                        truth_hz=float(truth[i]), original_db=before.peak_to_background_db,
                        proposed_db=after.peak_to_background_db,
                        original_amplitude_v=before.peak_amplitude,
                        proposed_amplitude_v=after.peak_amplitude,
                        harmed=bool(valid[k] and not a[k] and b[k]),
                        corrected=bool(valid[k] and a[k] and not b[k])))
        print(f'historical {source} {family} {instance}', flush=True)
    expected = {(r['case_id'], r['profile'], int(r['proposal_id'])): int(r['harmed'])
                for r in harmed}
    actual = {(r['case_id'], r['profile'], r['proposal_id']): r['harmed'] for r in rows
              if r['source'] == 'TASK002' and r['harmed']}
    assert expected == actual and sum(actual.values()) == 151
    write_csv(out/'historical_proposal_features.csv', rows)
    write_csv(out/'historical_frame_audit.csv', frames)
    write_json(out/'historical_replay.json', dict(replays=replays, matched_harm_proposals=7,
        matched_harm_frames=151, independent_harm_waveforms=5,
        role='Historical mechanism development only; no new validation N'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('historical', 'prepare', 'run'))
    parser.add_argument('--split', choices=tuple(bench.SPLITS))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'historical':
        historical(args.output)
    elif args.action == 'prepare':
        prepare(args.output)
    else:
        run_split(args.output, args.split)


if __name__ == '__main__':
    main()
