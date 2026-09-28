"""Frozen, resumable TASK-023F experiments. Existing stream artifacts are never overwritten."""
from __future__ import annotations

import argparse
import ctypes
import csv
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
import pickle
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_audit as auditor
from dps_studio.research import task023f_proposals as f
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import EdgeRescueConfig, TrustedCoreConfig
from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, PROFILES, SAMPLE_RATE_HZ, WaveformCase, array_hash,
    generate_case, profile_input,
)

ROOT = Path(__file__).resolve().parents[1]
D_METADATA = ROOT / 'artifacts/task023d_smooth_branch_rescue/20260904T092908Z/experiment_metadata.json'
E_ROOT = ROOT / 'artifacts/task023e_cross_scale_evidence/20260911T151301Z'


def process_peak_bytes() -> int:
    """Windows process lifetime working-set peak, not a per-variant allocation claim."""
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(counters),
                                                   ctypes.sizeof(counters)):
        raise OSError('GetProcessMemoryInfo failed')
    return int(counters.PeakWorkingSetSize)


def write_json(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, allow_nan=True, default=lambda x: x.item())


def write_csv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...] = ()) -> None:
    names = list(dict.fromkeys([*fields, *(key for row in rows for key in row)]))
    with path.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible_raw(path: Path, raw_root: Path) -> bool:
    return (path.resolve().is_relative_to(raw_root.resolve())
            and path.suffix.lower() in {'.dat', '.csv'}
            and not (path.suffix.lower() == '.dat' and 'result' in path.name.lower()))


def frozen_configs() -> dict[str, Any]:
    metadata = json.loads(D_METADATA.read_text(encoding='utf-8'))
    return {key: metadata[key] for key in ('core_config', 'edge_config', 'internal_config',
                                         'ambiguity_config', 'trim_config', 'branch_config')}


def original_e4(candidates: Any, stft: Any, method: d.SmoothBranchMethod =
                d.SmoothBranchMethod.E4_CONSERVATIVE_BRANCH) -> d.SmoothBranchOptimizationResult:
    configs = frozen_configs()
    return d.optimize_smooth_wrong_branches(candidates, method=method,
        core_config=TrustedCoreConfig(**configs['core_config']),
        edge_config=EdgeRescueConfig(**configs['edge_config']),
        internal_config=SegmentRescueConfig(**configs['internal_config']),
        ambiguity_config=d.BranchAmbiguityConfig(**configs['ambiguity_config']),
        trim_config=d.CoreTrimConfig(**configs['trim_config']),
        branch_config=d.BranchCompetitionConfig(**configs['branch_config']), stft_result=stft)


def fresh_case(family: str, instance: int) -> WaveformCase:
    seed = 2306000 + FAMILIES.index(family) * 100 + instance
    case = generate_case(family, instance, seed=seed)
    identifier = f'F23_{family}_{instance:02d}'
    return replace(case, case_id=identifier, observation_group=identifier, split='FRESH_HELD_OUT')


def manifest(output: Path) -> None:
    legacy = list(csv.DictReader((E_ROOT / 'fresh_waveform_manifest.csv').open(encoding='utf-8')))
    verified = []
    for row in legacy:
        case = generate_case(row['family'], int(row['instance']))
        if (array_hash(case.record.voltage_v) != row['voltage_sha256']
            or array_hash(case.truth_hz) != row['truth_sha256']):
            raise AssertionError('Default generator differs from original TASK-023E')
        verified.append({**row, 'original_split': row['split'], 'split': 'LEGACY_DIAGNOSTIC',
                         'development': case.instance < 8, 'default_hash_compatible': True})
    write_csv(output / 'benchmark_manifest.csv', verified)
    fresh = []
    waveform_dir = output / 'waveforms'
    waveform_dir.mkdir(exist_ok=False)
    for family in FAMILIES:
        for instance in range(8, 24):
            case = fresh_case(family, instance)
            path = waveform_dir / (case.case_id + '.npz')
            with path.open('xb') as handle:
                np.savez_compressed(handle, time_s=case.record.time_s,
                    voltage_v=case.record.voltage_v, truth_hz=case.truth_hz,
                    nuisance_hz=case.nuisance_hz, focus=case.focus)
            fresh.append(dict(case_id=case.case_id, observation_group=case.observation_group,
                family=family, instance=instance, seed=case.seed, split=case.split,
                voltage_sha256=array_hash(case.record.voltage_v), truth_sha256=array_hash(case.truth_hz),
                parameters_json=json.dumps(case.parameters, sort_keys=True),
                b32_diagnostic=instance in (8, 12, 16, 20), profiles='Balanced;High-time'))
    assert not set(r['voltage_sha256'] for r in verified) & set(r['voltage_sha256'] for r in fresh)
    write_csv(output / 'fresh_split.csv', fresh)


def run_stream(case: WaveformCase, profile: AnalysisProfile, output: Path,
               stage: str, activation: dict[str, Any]) -> dict[str, Any]:
    identifier = f'{case.case_id}_{profile.profile_id.value}'
    target = output / 'streams' / (identifier + '.json')
    if target.exists():
        return dict(json.loads(target.read_text(encoding='utf-8')))
    attempt = 1
    base_identifier = identifier
    while (output / 'lineages' / (identifier + '.pickle.gz')).exists():
        attempt += 1
        identifier = f'{base_identifier}_attempt{attempt:02d}'
    start = time.perf_counter()
    stft, candidates, truth, focus = profile_input(case, profile)
    candidate_hash = hashlib.sha256(pickle.dumps(candidates.candidates_by_frame)).hexdigest()
    stft_hash = array_hash(stft.spectrum)
    original = original_e4(candidates, stft)
    configs = frozen_configs()
    ambiguity_config = d.BranchAmbiguityConfig(**configs['ambiguity_config'])
    branch_config = f.effective_e4(d.BranchCompetitionConfig(**configs['branch_config']))
    registry = f.windows(original, f.ProposalConfig(), ambiguity_config)
    broadband = f.broadband_evidence(stft)
    search_cache: dict[tuple[str, str], f.SearchResult] = {}
    costs: list[dict[str, Any]] = []
    use_b32 = stage == 'DEVELOPMENT' or (stage == 'FRESH' and case.instance in (8, 12, 16, 20))
    for window in registry:
        if window.anchor is None or not window.indices:
            continue
        modes = ['B8']
        if stage == 'DEVELOPMENT' or activation['diversity']:
            modes.append('DIVERSITY_B8')
        if use_b32:
            modes.append('B32_DIAGNOSTIC')
        # Fresh core permission follows activation; denied windows are still in registry.
        if window.kind == 'CORE' and stage != 'DEVELOPMENT' and not activation['core']:
            continue
        for mode in modes:
            t0 = time.perf_counter()
            search = (f.diagnostic_b32(window, original, candidates, ambiguity_config,
                                      branch_config, broadband) if mode == 'B32_DIAGNOSTIC'
                      else f.generate_proposals(window, original, candidates, ambiguity_config,
                          branch_config, broadband, diversity=mode == 'DIVERSITY_B8'))
            search_cache[window.window_id, mode] = search
            costs.append(dict(window_id=window.window_id, kind=window.kind, mode=mode,
                seconds=time.perf_counter() - t0, process_lifetime_peak_bytes=process_peak_bytes(),
                proposals=len(search.proposals),
                expansions=len(search.lineage), families=len(set(f.family_ids(
                    tuple(p.state for p in search.proposals)))), window_frames=len(window.indices)))
    variants: dict[str, tuple[f.SearchResult, ...]] = {}
    for variant, core, diversity in (('P0', False, False), ('P1', True, False),
                                   ('P2', False, True), ('P3', True, True)):
        enabled_core = core and (stage == 'DEVELOPMENT' or activation['core'])
        enabled_diversity = diversity and (stage == 'DEVELOPMENT' or activation['diversity'])
        mode = 'DIVERSITY_B8' if enabled_diversity else 'B8'
        variants[variant] = tuple(search_cache[window.window_id, mode] for window in registry
            if (window.kind == 'EDGE' or enabled_core) and (window.window_id, mode) in search_cache)
    # Always verify P0, including its terminal best and literal rejection reason.
    p0 = f.apply_searches(variants['P0'], original, candidates, ambiguity_config, branch_config, broadband)
    assert np.array_equal(p0.final_frequency_hz, original.final_frequency_hz)
    assert np.array_equal(p0.final_rank, original.final_rank)
    for search, selection in zip(p0.searches, p0.selections, strict=True):
        assert search.window.anchor is not None
        expected = d._search_branch(search.window.indices, search.window.anchor, search.window.slope,
            original.task023c, candidates, original.ambiguity, ambiguity_config, branch_config, broadband)
        assert search.proposals[0].state == expected
        decision = (original.leading_branch_decision if search.window.window_id == 'edge_left'
                    else original.trailing_branch_decision)
        assert decision is not None and selection.status == decision.status.value
        assert selection.accepted == tuple(step.modified for step in decision.steps)
    nuisance = case.nuisance_hz[np.rint(stft.time_s * SAMPLE_RATE_HZ).astype(int)]
    context = dict(case_id=case.case_id, observation_group=case.observation_group, family=case.family,
                   profile=profile.profile_id.value, stage=stage, instance=case.instance)
    summaries: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    prune_rows: list[dict[str, Any]] = []
    oracle_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    for variant, searches in variants.items():
        audited = auditor.audit(candidates, truth, nuisance, original, searches, registry,
                                 4 * SAMPLE_RATE_HZ / profile.window_length_samples)
        summaries.append({**context, 'variant': variant, **audited.summary})
        frame_rows.extend({**context, 'variant': variant, **row} for row in audited.frames)
        prune_rows.extend({**context, 'variant': variant, **row} for row in audited.pruning)
        for name, value in auditor.oracle(original.task023c.strongest.frequency_hz, truth, searches,
                                         auditor.internal_fallback(original)).items():
            oracle_rows.append({**context, 'variant': variant, 'oracle': name, **value})
        by_window = {search.window.window_id: search for search in searches}
        for window in registry:
            offered = by_window.get(window.window_id)
            window_rows.append({**context, 'variant': variant, 'window_id': window.window_id,
                'kind': window.kind, 'status': window.status, 'frames': len(window.indices),
                'proposals': len(offered.proposals) if offered else 0,
                'families': len(set(f.family_ids(tuple(p.state for p in offered.proposals))))
                            if offered else 0})
    b32_rows = []
    if use_b32:
        for variant, core in (('B32_P0_PERMISSION', False), ('B32_CHALLENGE_PERMISSION', True)):
            searches = tuple(search_cache[window.window_id, 'B32_DIAGNOSTIC'] for window in registry
                if (window.kind == 'EDGE' or core)
                and (window.window_id, 'B32_DIAGNOSTIC') in search_cache)
            audited = auditor.audit(candidates, truth, nuisance, original, searches, registry,
                                     4 * SAMPLE_RATE_HZ / profile.window_length_samples)
            b32_rows.append({**context, 'variant': variant, **audited.summary})
            for name, value in auditor.oracle(original.task023c.strongest.frequency_hz, truth, searches,
                                             auditor.internal_fallback(original)).items():
                oracle_rows.append({**context, 'variant': variant, 'oracle': name, **value})
    # The full expansion DAG is kept once per actual search, not duplicated for aliases.
    with gzip.open(output / 'lineages' / (identifier + '.pickle.gz'), 'xb', compresslevel=1) as handle:
        pickle.dump(dict(searches=search_cache, registry=registry), handle, protocol=5)
    write_csv(output / 'details' / (identifier + '_funnel.csv'), frame_rows)
    write_csv(output / 'details' / (identifier + '_pruning.csv'), prune_rows,
              ('case_id', 'variant', 'frame', 'first_loss_frame', 'first_loss_reason'))
    # Save enough provenance to audit the unchanged graph and baseline without rereading raw.
    with (output / 'provenance' / (identifier + '.npz')).open('xb') as handle:
        np.savez_compressed(handle, time_s=stft.time_s, truth_hz=truth, nuisance_hz=nuisance,
            strongest_frequency_hz=original.task023c.strongest.frequency_hz,
            task023c_frequency_hz=original.task023c.final_frequency_hz, e4_frequency_hz=original.final_frequency_hz,
            e4_rank=original.final_rank, retained_core=original.trimmed_core_mask,
            focus=focus, candidates_hz=np.array([[c.transition_frequency_hz for c in frame] + [np.nan] * (20 - len(frame))
                                               for frame in candidates.candidates_by_frame]))
    assert candidate_hash == hashlib.sha256(pickle.dumps(candidates.candidates_by_frame)).hexdigest()
    assert stft_hash == array_hash(stft.spectrum)
    value = dict(context=context, artifact_stem=identifier, summaries=summaries, b32=b32_rows, oracle=oracle_rows,
                 costs=costs, windows=window_rows, candidate_sha256=candidate_hash,
                 stft_sha256=stft_hash, p0_exact=True, seconds=time.perf_counter() - start,
                 crowding_events=sum(bool(row['truth_prefix_displaced_by_duplicates'])
                                     for row in prune_rows if row['variant'] == 'P1'),
                 baseline_metrics=auditor.metrics(original.task023c.strongest.frequency_hz,
                                                   original.final_frequency_hz, truth))
    write_json(target, value)
    print(f'{stage} {identifier}: {value["seconds"]:.1f}s, '
          f'P0/P1 terminal {summaries[0]["terminal_frames"]}/{summaries[1]["terminal_frames"]}', flush=True)
    return value


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ('error_frames', 'candidate_frames', 'graph_frames', 'terminal_frames', 'missing_frames',
            'error_intervals', 'recovered_intervals', 'resolved_error_frames', 'resolved_terminal_frames',
            'unresolved_error_frames', 'unresolved_terminal_frames')
    total: dict[str, Any] = {key: sum(row[key] for row in rows) for key in keys}
    total.update(candidate_recall=auditor.ratio(total['candidate_frames'], total['error_frames']),
                 terminal_recall=auditor.ratio(total['terminal_frames'], total['error_frames']),
                 graph_recall=auditor.ratio(total['graph_frames'], total['error_frames']),
                 missing_proposal_fraction=auditor.ratio(total['missing_frames'], total['candidate_frames']),
                 branch_recall=auditor.ratio(total['recovered_intervals'], total['error_intervals']))
    return total


def freeze_activation(output: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [row for result in results for row in result['summaries']]
    oracle_rows = [row for result in results for row in result['oracle']]
    scores = {variant: sum(row['sse_hz2'] for row in oracle_rows
                          if row['variant'] == variant and row['oracle'] == 'FEASIBLE_MIN_SSE')
              for variant in ('P0', 'P1', 'P2', 'P3')}
    gain = scores['P0'] - scores['P1']
    crowding = sum(result['crowding_events'] for result in results)
    terminal = {variant: sum(row['terminal_frames'] for row in summaries if row['variant'] == variant)
                for variant in ('P0', 'P1', 'P2', 'P3')}
    activation = dict(core=gain > 0, diversity=crowding > 0 and (
        terminal['P2'] > terminal['P0'] or terminal['P3'] > terminal['P1']),
        core_counterfactual_sse_gain_hz2=gain, duplicate_crowding_events=crowding,
        development_terminal_frames=terminal, config=frozen_configs(),
        effective_e4=asdict(f.effective_e4(d.BranchCompetitionConfig(**frozen_configs()['branch_config']))),
        proposal_config=asdict(f.ProposalConfig()),
        source_hashes={str(p.relative_to(ROOT)): sha256(p) for folder in ('src','scripts','tests')
                       for p in (ROOT / folder).rglob('*task023f*.py')},
        selection_rule='core: positive same-window permission oracle gain; diversity: crowding plus recovered terminal evidence',
        fresh_used_for_activation=False)
    write_json(output / 'frozen_activation.json', activation)
    return activation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--stage', choices=('prepare', 'development', 'fresh', 'legacy'), required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'artifacts/task023f_proposal_recall_recovery'):
        raise ValueError('Research-only output required')
    if args.stage == 'prepare':
        for name in ('streams', 'lineages', 'details', 'provenance', 'figures'):
            (output / name).mkdir(exist_ok=False)
        manifest(output)
        return
    activation = (json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
                  if args.stage in ('fresh', 'legacy') else dict(core=True, diversity=True))
    jobs = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for family in FAMILIES:
            for instance in (range(8) if args.stage == 'development' else range(8, 24)):
                case = (generate_case(family, instance) if args.stage in ('development', 'legacy')
                        else fresh_case(family, instance))
                for profile in PROFILES:
                    jobs.append(pool.submit(run_stream, case, profile, output,
                        'DEVELOPMENT' if args.stage == 'development' else (
                            'LEGACY_DIAGNOSTIC' if args.stage == 'legacy' else 'FRESH'), activation))
        results = [job.result() for job in jobs]
    if args.stage == 'development':
        freeze_activation(output, results)
    elif args.stage == 'fresh':
        values = [row for result in results for row in result['summaries']]
        totals = {variant: aggregate([r for r in values if r['variant'] == variant])
                  for variant in ('P0', 'P1', 'P2', 'P3')}
        p0 = totals['P0']
        passed = []
        for variant in ('P1', 'P2', 'P3'):
            value = totals[variant]
            recall_gain = (value['terminal_recall'] - p0['terminal_recall']
                           if p0['terminal_recall'] is not None else None)
            missing_gain = ((p0['missing_proposal_fraction'] - value['missing_proposal_fraction'])
                            / p0['missing_proposal_fraction'] if p0['missing_proposal_fraction'] else None)
            if (recall_gain is not None and recall_gain >= .15) or (
                missing_gain is not None and missing_gain >= .30):
                passed.append(variant)
        write_json(output / 'fresh_proposal_gate.json', dict(totals=totals, passed=passed,
            verdict='PROPOSAL_GATE_PASSED' if passed else 'NOT_SUPPORTED',
            final_evaluation_authorized=bool(passed), real_evaluation_authorized=bool(passed)))


if __name__ == '__main__':
    main()
