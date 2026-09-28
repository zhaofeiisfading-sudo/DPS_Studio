"""Split-ordered TASK-026 execution, immutable inputs/outputs and implementation."""
from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research.task023e_waveform_benchmark import PROFILES, array_hash
from dps_studio.research.task026_benchmark import metrics, physical_truth, synthesize
from dps_studio.research.task026_representation import METHODS, Method, estimate
from scripts.freeze_task026 import ROOT, digest, load_json, write_json


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def frozen_code(output: Path) -> None:
    files = [*ROOT.glob('src/dps_studio/research/task026*.py'),
             ROOT/'scripts/run_task026.py', ROOT/'scripts/freeze_task026.py']
    observed = {str(p.relative_to(ROOT)): digest(p) for p in files}
    path = output/'implementation_freeze.json'
    if path.exists():
        assert observed == load_json(path), 'Implementation changed after observation'
    else:
        write_json(path, observed)
    for name, expected in load_json(output/'frozen_manifest.json')['files'].items():
        assert digest(output/name) == expected, name


def process_waveform(row: dict[str, Any], output: Path,
                     methods: tuple[Method, ...]) -> list[dict[str, Any]]:
    case = synthesize(row)
    before = array_hash(case.record.voltage_v), array_hash(case.record.time_s)
    with (output/'waveforms'/f'{case.case_id}.npz').open('xb') as handle:
        np.savez_compressed(handle, time_s=case.record.time_s, voltage_v=case.record.voltage_v,
                            truth_hz=case.truth_hz, nuisance_latent_hz=case.nuisance_hz,
                            focus=case.focus)
    results: list[dict[str, Any]] = []
    for profile in PROFILES:
        stream = case.case_id+'__'+profile.profile_id.value
        saved: dict[str, Any] = {}
        frame_time = None
        ordered = methods[row['seed'] % len(methods):]+methods[:row['seed'] % len(methods)]
        for method in ordered:
            start = time.perf_counter()
            observation = estimate(case.record, profile, method)
            elapsed = time.perf_counter()-start
            if frame_time is None:
                frame_time = observation.time_s
            assert np.array_equal(frame_time, observation.time_s)
            assert before == (array_hash(case.record.voltage_v), array_hash(case.record.time_s))
            first, second, focus = physical_truth(case, row['dataset'], observation.time_s)
            context = dict(**row, profile=profile.profile_id.value, method=method,
                           stream=stream, elapsed_s=elapsed, source_voltage_sha256=before[0],
                           source_time_sha256=before[1])
            regions = dict(ALL=focus)
            if row['dataset'] == 'TWO':
                regions.update(CLOSE=focus & (np.abs(first-second) <= 150e6),
                    LOW_SNR=focus & (row['snr_db'] <= 0), FADE=focus & (row['fade_depth'] < 1),
                    CROSSING=focus & (row['family'] in ('crossing', 'merging', 'diverging')))
            if row['dataset'] == 'CORE':
                regions['NOISE'] = focus & ~np.isfinite(first) & ~np.isfinite(second)
                regions['FOCUS'] = focus & case.focus[np.rint(
                    observation.time_s*40e9).astype(int)]
            for region, mask in regions.items():
                if mask.any():
                    results.append(dict(**context, region=region,
                                        **metrics(observation, first, second, mask)))
            for name in ('frequency_hz', 'discrete_hz', 'chirp_rate_hz_per_s', 'evidence',
                         'quality_flags', 'residual_fraction'):
                saved[method+'_'+name] = getattr(observation, name)
            saved.update(time_s=frame_time, truth_hz=first, nuisance_hz=second, focus=focus)
            representative = (row['dataset'] != 'CORE' and row['instance'] == 1 and
                row['carrier_hz'] == 3e9 and row['amplitude_v'] == 1 and
                row['snr_db'] in (-20., 10.) and (
                    row['family'] == 'stationary' or
                    (row['family'] == 'fast_chirp' and row['chirp_hz_per_s'] == 4e16) or
                    (row['family'] == 'crossing' and row['separation_hz'] == 150e6)))
            if representative:
                saved[method+'_representation'] = observation.representation
                saved['frequency_axis_hz'] = observation.frequency_axis_hz
        with (output/'streams'/f'{stream}.npz').open('xb') as handle:
            np.savez_compressed(handle, **saved)
    write_json(output/'waveforms'/f'{case.case_id}.json', dict(registration=row,
               source_voltage_sha256=before[0], source_time_sha256=before[1],
               parameters=case.parameters, metrics=results))
    return results


def run_stage(output: Path, stage: str, workers: int) -> None:
    frozen_code(output)
    all_rows = load_json(output/'seed_registration.json')
    if stage == 'single_calibration':
        rows = [r for r in all_rows if r['dataset'] == 'SINGLE' and r['split'] == 'CALIBRATION']
        methods = METHODS
    elif stage == 'single_held_out':
        assert (output/'phase_a_sanity.json').exists()
        rows = [r for r in all_rows if r['dataset'] == 'SINGLE' and r['split'] == 'HELD_OUT']
        methods = METHODS
    else:
        split = 'CALIBRATION' if stage == 'two_core_calibration' else 'HELD_OUT'
        assert (output/'single_held_out_completed.json').exists()
        rows = [r for r in all_rows if r['dataset'] != 'SINGLE' and r['split'] == split]
        methods = tuple(m for m in METHODS if load_json(output/'phase_a_sanity.json')[m]['passed'])
        assert 'R0' in methods
    write_json(output/f'{stage}_started.json', dict(time=time.time(), waveforms=len(rows),
                                                  methods=methods))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(process_waveform, row, output, methods) for row in rows]
        for i, future in enumerate(as_completed(futures), 1):
            results.extend(future.result())
            if i % 25 == 0 or i == len(rows):
                print(f'{stage}: {i}/{len(rows)}', flush=True)
    write_csv(output/f'{stage}.csv', sorted(results, key=lambda r: (r['waveform'],
                                                    r['profile'], r['method'], r['region'])))
    write_json(output/f'{stage}_completed.json', dict(time=time.time(), waveforms=len(rows)))


def sanity(output: Path) -> None:
    frozen_code(output)
    with (output/'single_calibration.csv').open(encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    decision = {}
    for method in METHODS:
        selected = [r for r in rows if r['method'] == method and float(r['snr_db']) == 30]
        stationary = [r for r in selected if r['family'] == 'stationary']
        medium = [r for r in selected if r['family'] == 'medium_chirp']
        s = float(np.mean([float(r['rmse_hz']) for r in stationary]))
        c = float(np.mean([float(r['rmse_hz']) for r in medium]))
        valid = min(float(r['valid_estimate_fraction']) for r in stationary)
        decision[method] = dict(stationary_rmse_hz=s, medium_chirp_rmse_hz=c,
                                valid=valid, passed=s <= 5e6 and c <= 20e6 and valid >= .99)
    write_json(output/'phase_a_sanity.json', decision)
    print(decision, flush=True)


def isolated_runtime(output: Path) -> None:
    frozen_code(output)
    rows = load_json(output/'seed_registration.json')
    selected: dict[str, Any] = {}
    for row in rows:
        if row['split'] != 'HELD_OUT':
            continue
        key = row['family'] if row['dataset'] == 'CORE' else (
            row['family'] if row['family'] in ('stationary', 'fast_chirp', 'crossing') else '')
        if row['dataset'] == 'SINGLE' and row['snr_db'] == -20:
            selected.setdefault('single_low_snr', row)
        if key:
            selected.setdefault(row['dataset']+'_'+key, row)
    results = []
    # Explicit warm-up excluded, timed measurements are sequential without a process pool.
    first = synthesize(next(iter(selected.values())))
    for method in METHODS:
        estimate(first.record, PROFILES[0], method)
    for i, row in enumerate(selected.values()):
        case = synthesize(row)
        for p, profile in enumerate(PROFILES):
            for repeat in range(3):
                shift = (i+p+repeat) % 4
                for method in METHODS[shift:]+METHODS[:shift]:
                    start = time.perf_counter()
                    estimate(case.record, profile, method)
                    elapsed = time.perf_counter()-start
                    results.append(dict(waveform=row['waveform'], dataset=row['dataset'],
                        family=row['family'], profile=profile.profile_id.value, method=method,
                        repeat=repeat, elapsed_s=elapsed, timing='ISOLATED_SEQUENTIAL'))
        print(f'isolated runtime {i+1}/{len(selected)}', flush=True)
    write_csv(output/'runtime_isolated.csv', results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('single_calibration', 'sanity', 'single_held_out',
        'two_core_calibration', 'two_core_held_out', 'runtime'), required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.stage == 'sanity':
        sanity(args.output)
    elif args.stage == 'runtime':
        isolated_runtime(args.output)
    else:
        run_stage(args.output, args.stage, args.workers)


if __name__ == '__main__':
    main()
