"""One-time, split-ordered TASK-025 experiment; exclusive artifact creation."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research import task025_informative_interval as gate
from dps_studio.research.task023e_waveform_benchmark import (
    PROFILES, SAMPLE_RATE_HZ, array_hash, profile_input,
)
from dps_studio.research.task023h_pair_audit import fingerprint
from dps_studio.research.task025_stress_benchmark import evaluation_masks, registered_case
from scripts.run_task023f_proposal_recovery import (
    ROOT, process_peak_bytes, sha256, write_csv, write_json,
)

DETECTORS = ('E1', 'B0_RMS', 'B1_SPECTRAL')


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def generate_waveform(row: dict[str, Any], output: Path) -> dict[str, Any]:
    start = time.perf_counter()
    case = registered_case(row)
    with (output / 'waveforms' / (case.case_id+'.npz')).open('xb') as handle:
        np.savez_compressed(handle, time_s=case.record.time_s, voltage_v=case.record.voltage_v,
                            truth_hz=case.truth_hz, nuisance_hz=case.nuisance_hz, focus=case.focus)
    streams = []
    for profile in PROFILES:
        stft, candidates, truth, _ = profile_input(case, profile)
        strongest = np.asarray([frame[0].transition_frequency_hz
                                for frame in candidates.candidates_by_frame])
        assert np.all(np.isfinite(strongest))
        original_hash = fingerprint((stft.spectrum, candidates, case.record.voltage_v))
        before = time.perf_counter()
        support = gate.strongest_support(case.record.time_s, case.record.voltage_v,
            stft.time_s, strongest, profile.window_length_samples/SAMPLE_RATE_HZ)
        support_seconds = time.perf_counter()-before
        assert original_hash == fingerprint((stft.spectrum, candidates, case.record.voltage_v))
        available = np.asarray([any(abs(c.transition_frequency_hz-truth[i]) <= 200e6
                                    for c in frame)
                                for i, frame in enumerate(candidates.candidates_by_frame)])
        masks = evaluation_masks(case, row['dataset'], stft.time_s, truth)
        spectral = np.asarray([frame[0].peak_to_background_db
                               for frame in candidates.candidates_by_frame])
        name = f'{case.case_id}_{profile.profile_id.value}'
        saved_arrays: dict[str, Any] = dict(time_s=stft.time_s, strongest_hz=strongest,
            truth_hz=truth, E1=support.e1, B0_RMS=support.analytic_rms_v,
            B1_SPECTRAL=spectral, quality=np.asarray(support.quality),
            candidate_available=available, **{'mask_'+k: v for k, v in masks.items()})
        with (output / 'streams' / (name+'.npz')).open('xb') as handle:
            np.savez_compressed(handle, **saved_arrays)
        valid = np.isfinite(truth)
        error = valid & (abs(strongest-truth) > 200e6)
        streams.append(dict(**row, stream=name, profile=profile.profile_id.value,
            frames=len(truth), target_frames=int(valid.sum()),
            candidate_hits=int((available & valid).sum()), error_frames=int(error.sum()),
            error_candidate_hits=int((available & error).sum()),
            E1_nonfinite=int((~np.isfinite(support.e1)).sum()),
            strongest_coverage=float(np.isfinite(strongest).mean()),
            source_and_candidates_unchanged=True, source_stft_candidate_fingerprint=original_hash,
            stft_sha256=array_hash(stft.spectrum), strongest_sha256=array_hash(strongest),
            support_seconds=support_seconds, process_high_water_bytes=process_peak_bytes()))
    result = dict(**row, voltage_sha256=array_hash(case.record.voltage_v),
                  parameters=case.parameters, streams=streams, elapsed_seconds=time.perf_counter()-start)
    write_json(output / 'waveforms' / (case.case_id+'.json'), result)
    return result


def freeze_code(output: Path) -> None:
    path = output / 'implementation_freeze.json'
    if path.exists():
        for name, digest in load_json(path).items():
            if sha256(ROOT / name) != digest:
                raise RuntimeError('Implementation changed after calibration: '+name)
        return
    names = ['scripts/run_task025.py', 'scripts/freeze_task025.py',
             'src/dps_studio/research/task025_informative_interval.py',
             'src/dps_studio/research/task025_stress_benchmark.py']
    write_json(path, {name: sha256(ROOT / name) for name in names})


def generate(output: Path, split: str, workers: int) -> None:
    freeze_code(output)
    frozen = load_json(output / 'frozen_manifest.json')
    for name, field in (('protocol.md', 'protocol_sha256'),
                        ('seed_registration.json', 'seed_sha256'),
                        ('threshold_protocol.json', 'threshold_protocol_sha256')):
        assert sha256(output / name) == frozen[field]
    if split == 'HELD_OUT':
        assert (output / 'frozen_thresholds.json').exists()
        assert load_json(output / 'frozen_thresholds.json')['E1']['status'] == 'CALIBRATED'
    write_json(output / (split.lower()+'_started.json'), dict(split=split, time=time.time()))
    selected = [r for r in load_json(output / 'seed_registration.json') if r['split'] == split]
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(generate_waveform, row, output): row for row in selected}
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            print(f'{split} {len(results)}/{len(selected)} {result["waveform"]}', flush=True)
    ordered = sorted(results, key=lambda row: row['waveform'])
    write_json(output / (split.lower()+'_manifest.json'), ordered)


def calibrate(output: Path) -> None:
    freeze_code(output)
    rows = load_json(output / 'calibration_manifest.json')
    frames: dict[str, list[np.ndarray[Any, Any]]] = {name: [] for name in DETECTORS}
    target = []
    provenance = []
    for row in rows:
        assert row['split'] == 'CALIBRATION'
        for stream in row['streams']:
            path = output / 'streams' / (stream['stream']+'.npz')
            with np.load(path) as arrays:
                for name in DETECTORS:
                    frames[name].append(arrays[name])
                target.append(arrays['mask_target_present'])
            provenance.append(dict(stream=stream['stream'], split='CALIBRATION',
                                   sha256=sha256(path)))
    present = np.concatenate(target)
    thresholds, metrics = {}, []
    for name in DETECTORS:
        values = np.concatenate(frames[name])
        try:
            threshold = gate.calibration_threshold(values, present, split='CALIBRATION')
            info = dict(status='CALIBRATED', threshold=threshold,
                target_recall=float(np.mean(values[present] >= threshold)),
                target_frames=int(present.sum()))
        except ValueError as error:
            info = dict(status='NOT SUPPORTED', reason=str(error), threshold=None)
        thresholds[name] = info
        metrics.append(dict(detector=name, **info))
    write_csv(output / 'threshold_calibration.csv', metrics)
    write_json(output / 'frozen_thresholds.json', thresholds)
    write_json(output / 'threshold_provenance.json', provenance)
    print(json.dumps(thresholds, indent=2), flush=True)


def count_rows(context: dict[str, Any], arrays: Any, thresholds: dict[str, Any],
               ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frames, segments = [], []
    time_s = arrays['time_s']
    target = arrays['mask_target_present']
    for detector in DETECTORS:
        threshold = thresholds[detector]['threshold']
        if threshold is None:
            continue
        supported, active = gate.informative_mask(time_s, arrays[detector], threshold)
        output = gate.complete_output(arrays['strongest_hz'], arrays['strongest_hz'], active)
        assert np.array_equal(output, arrays['strongest_hz'])
        assert np.all(np.isfinite(output))
        for mask_name, selected in (('SUPPORTED_FRAME', supported), ('SEARCH_ACTIVE', active)):
            for name in arrays.files:
                if not name.startswith('mask_'):
                    continue
                stratum = name.removeprefix('mask_')
                mask = arrays[name]
                denominator = int(mask.sum())
                if not denominator:
                    continue
                hits = int((selected & mask).sum())
                frames.append(dict(**context, detector=detector, mask=mask_name,
                    stratum=stratum, numerator=hits, denominator=denominator,
                    recall_or_activation=hits/denominator, rejection_or_fnr=1-hits/denominator,
                    search_active_fraction=float(active.mean()), coverage=1.0))
        for index, (a, b) in enumerate(gate.runs(target)):
            local = active[a:b]
            hits = int(local.sum())
            fragments = len(gate.runs(local))
            leading = int(np.flatnonzero(local)[0]) if hits else b-a
            trailing = int(np.flatnonzero(local[::-1])[0]) if hits else b-a
            dt = float(np.median(np.diff(time_s)))
            segments.append(dict(**context, detector=detector, segment=index, frames=b-a,
                start_s=float(time_s[a]), end_s=float(time_s[b-1]), active_frames=hits,
                detected=int(hits > 0), coverage=hits/(b-a),
                coverage_99=int(hits/(b-a) >= .99), fully_covered=int(hits == b-a),
                fragments=fragments, excess_fragments=max(fragments-1, 0),
                leading_missed_frames=leading, trailing_missed_frames=trailing,
                leading_missed_s=leading*dt, trailing_missed_s=trailing*dt,
                boundary_missed_frames=int((~local[:4]).sum()+(~local[-4:]).sum())))
    return frames, segments


def evaluate(output: Path) -> None:
    """Consume the frozen scores once; no new synthesis or fitting here."""
    freeze_code(output)
    write_json(output / 'evaluation_started.json', dict(time=time.time(), runs=1))
    thresholds = load_json(output / 'frozen_thresholds.json')
    frames, segments, streams, manifest = [], [], [], []
    for split in ('calibration', 'held_out'):
        for row in load_json(output / (split+'_manifest.json')):
            manifest.append({k: v for k, v in row.items() if k not in ('streams', 'parameters')})
            for stream in row['streams']:
                streams.append(stream)
                context = {key: stream[key] for key in ('waveform', 'dataset', 'family',
                                                        'split', 'profile', 'stream')}
                with np.load(output / 'streams' / (stream['stream']+'.npz')) as arrays:
                    frows, srows = count_rows(context, arrays, thresholds)
                frames.extend(frows)
                segments.extend(srows)
    write_csv(output / 'fresh_split.csv', manifest)
    write_csv(output / 'hard_negative_manifest.csv', [v for v in manifest
                                                     if v['dataset'] == 'HARD_NEGATIVE'])
    write_csv(output / 'candidate_recall.csv', streams)
    write_csv(output / 'frame_detection_metrics.csv', frames)
    write_csv(output / 'segment_detection_metrics.csv', segments)
    write_csv(output / 'hard_negative_results.csv', [v for v in frames
                                                    if v['dataset'] == 'HARD_NEGATIVE'])
    write_json(output / 'evaluation_completed.json', dict(time=time.time(), runs=1,
        waveform_count=len(manifest), stream_count=len(streams)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stage', choices=('calibration', 'held-out', 'evaluate'), required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.stage == 'calibration':
        generate(output, 'CALIBRATION', args.workers)
        calibrate(output)
    elif args.stage == 'held-out':
        generate(output, 'HELD_OUT', args.workers)
    else:
        evaluate(output)


if __name__ == '__main__':
    main()
