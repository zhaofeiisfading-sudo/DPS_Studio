"""Phase A only: replay prior DAGs and audit one-step recovery before algorithms."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023g_retention_audit as g
from dps_studio.research.task023e_waveform_benchmark import PROFILES, generate_case, profile_input
from scripts import run_task023f_proposal_recovery as r
from scripts.evaluate_task023f_frozen import load_searches
from scripts.finalize_task023f_recovery import read_csv

PRIOR = r.ROOT / 'artifacts/task023f_proposal_recall_recovery/20260912T100142Z'


def restore_source_context(frames: list[dict[str, Any]], prunes: list[dict[str, Any]]) -> None:
    """Cohorts may span error intervals; original metadata belongs to each source frame."""
    lookup = {(row['case_id'], row['profile'], row['window_id'], row['frame']): row for row in prunes}
    for row in frames:
        original = lookup[row['waveform'], row['profile'], row['window'], str(row['frame'])]
        row['original_first_loss_frame'] = original['first_loss_frame']
        row['error_start'], row['error_end'] = int(original['error_start']), int(original['error_end'])


def audit_stream(output: Path, losses: list[dict[str, Any]], prunes: list[dict[str, Any]]) -> dict[str, Any]:
    first = losses[0]
    identifier = first['case_id'] + '_' + first['profile']
    verified = output / 'recovery_recheck/cohort_audits' / (identifier + '.json')
    if verified.exists():
        return dict(json.loads(verified.read_text(encoding='utf-8')))
    target = output / 'cohort_audits' / (identifier + '.json')
    if target.exists():
        return dict(json.loads(target.read_text(encoding='utf-8')))
    context = json.loads((PRIOR / 'streams' / (identifier + '.json')).read_text(encoding='utf-8'))['context']
    case = (r.fresh_case(context['family'], context['instance']) if context['stage'] == 'FRESH'
            else generate_case(context['family'], context['instance']))
    profile = next(p for p in PROFILES if p.profile_id.value == context['profile'])
    stft, candidates, truth, _ = profile_input(case, profile)
    original = r.original_e4(candidates, stft)
    configs = r.frozen_configs()
    ambiguity = d.BranchAmbiguityConfig(**configs['ambiguity_config'])
    config = f.effective_e4(d.BranchCompetitionConfig(**configs['branch_config']))
    broadband = f.broadband_evidence(stft)
    searches = load_searches(PRIOR, context)
    prune_index = {(row['window_id'], row['frame']): row for row in prunes}
    grouped: dict[tuple[str, int, tuple[int, ...]], list[dict[str, Any]]] = defaultdict(list)
    replay_cache: dict[str, g.Replay] = {}
    for loss in losses:
        window = loss['window_id']
        if window not in replay_cache:
            replay_cache[window] = g.Replay(searches[window, 'DIVERSITY_B8'], original,
                                           candidates, ambiguity, config, broadband)
        first_loss, identifiers = replay_cache[window].cohort_loss(int(loss['frame']), truth)
        grouped[window, first_loss, identifiers].append(loss)
    events, frames = [], []
    for key, affected in grouped.items():
        window = key[0]
        original_event = prune_index[window, affected[0]['frame']]
        event = dict(original_event, first_loss_frame=key[1], cohort_ids=key[2])
        value = g.audit_event(replay_cache[window], event, truth)
        common = dict(waveform=context['case_id'], observation_group=context['observation_group'],
            profile=context['profile'], family=context['family'], original_stage=context['stage'],
            role='DEVELOPMENT' if context['stage'] == 'DEVELOPMENT' else 'LEGACY_DIAGNOSTIC',
            error_start=int(original_event['error_start']), error_end=int(original_event['error_end']),
            scope='SOURCE_FRAME_CORRECT_COHORT; later descendants unrestricted',
            original_first_loss_frame=original_event['first_loss_frame'])
        events.append({**common, **value, 'affected_error_frames': len(affected)})
        for loss in affected:
            frames.append({**common, **value, 'frame': int(loss['frame']),
                           'original_reason': loss['reason'],
                           'pruned_after_source_frame': key[1] != int(loss['frame'])})
    result = dict(context=context, events=events, frames=frames)
    r.write_json(target, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    (output / 'cohort_audits').mkdir(exist_ok=True)
    frames = [row for row in read_csv(PRIOR / 'proposal_funnel_detail.csv')
              if row['variant'] == 'P3' and row['stage'] in ('DEVELOPMENT', 'FRESH')
              and row['reason'] in ('EXPANDED_THEN_PRUNED', 'BEAM_PRUNED_ANCESTOR')]
    assert sum(row['stage'] == 'FRESH' for row in frames) == 1699
    prunes = [row for row in read_csv(PRIOR / 'beam_pruning_detail.csv')
              if row['variant'] == 'P3' and row['stage'] in ('DEVELOPMENT', 'FRESH')]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in frames:
        grouped[row['case_id'], row['profile']].append(row)
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(audit_stream, output, values,
            [row for row in prunes if (row['case_id'], row['profile']) == key]): key
            for key, values in grouped.items()}
        failures = []
        for future in as_completed(pending):
            try:
                value = future.result()
            except Exception as error:
                failures.append((pending[future], repr(error)))
                print(f'AUDIT_ERROR {pending[future]} {error!r}', flush=True)
                continue
            results.append(value)
            print(f'AUDIT {len(results)}/{len(pending)} {pending[future]}', flush=True)
    if failures:
        raise RuntimeError(f'Audit incomplete: {failures}')
    frame_rows = sorted((row for result in results for row in result['frames']),
                         key=lambda row: (row['waveform'], row['profile'], row['frame']))
    restore_source_context(frame_rows, prunes)
    events = sorted((row for result in results for row in result['events']),
                    key=lambda row: (row['waveform'], row['profile'], row['first_loss_frame']))
    for row in [*frame_rows, *events]:
        row.setdefault('raw_cost_dip_recovery', False)
    r.write_csv(output / 'retention_failure_taxonomy.csv', frame_rows)
    r.write_csv(output / 'beam_lineage_audit.csv', events)
    summaries = {}
    for role in ('DEVELOPMENT', 'LEGACY_DIAGNOSTIC'):
        selected = [row for row in events if row['role'] == role]
        selected_frames = [row for row in frame_rows if row['role'] == role]
        recovery = sum(row['future_recovery_existence'] for row in selected)
        recovery_frames = sum(row['future_recovery_existence'] for row in selected_frames)
        summaries[role] = dict(events=len(selected), loss_frames=len(selected_frames),
            one_step_recovery_events=recovery, one_step_recovery_frames=recovery_frames,
            raw_cost_dip_events=sum(row['raw_cost_dip_recovery'] for row in selected),
            raw_cost_dip_frames=sum(row['raw_cost_dip_recovery'] for row in selected_frames),
            event_fraction=recovery / len(selected) if selected else None,
            loss_frame_fraction=recovery_frames / len(selected_frames) if selected_frames else None,
            event_taxonomy=dict(Counter(row['taxonomy'] for row in selected)),
            frame_taxonomy=dict(Counter(row['taxonomy'] for row in selected_frames)))
    dev = summaries['DEVELOPMENT']
    supported = (dev['event_fraction'] is not None and dev['event_fraction'] >= .20
                 and dev['loss_frame_fraction'] is not None and dev['loss_frame_fraction'] >= .20)
    r.write_json(output / 'retention_activation.json', dict(lookahead_enabled=bool(supported),
        criterion='Predeclared operational meaning of many: >=20% development events AND affected loss frames recover at next-step raw-score B8 cutoff with frozen evidence. No fresh G data inspected.',
        summaries=summaries, verdict='SUPPORTED' if supported else 'NOT_SUPPORTED'))


if __name__ == '__main__':
    main()
