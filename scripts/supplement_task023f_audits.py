"""Derive additional audit tables from saved frozen proposals; never run a selector."""
from __future__ import annotations

import argparse
import json
from itertools import groupby
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research import task023f_audit as a
from scripts import run_task023f_proposal_recovery as runner
from scripts.evaluate_task023f_frozen import artifact_stem, load_searches
from scripts.finalize_task023f_recovery import read_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    results = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((output / 'streams').glob('*.json'))]
    core_rows, final_frames, full_lineage_rows = [], [], []
    for result in results:
        context = result['context']
        stem = artifact_stem(output, context)
        # Development is the causal activation dataset. Fresh matched-window
        # results are reported too; neither is used to alter the frozen method.
        if context['stage'] in ('DEVELOPMENT', 'FRESH'):
            cache = load_searches(output, context)
            with np.load(output / 'provenance' / (stem + '.npz')) as values:
                strongest, truth = values['strongest_frequency_hz'], values['truth_hz']
                for (window_id, mode), search in cache.items():
                    alive = {0}
                    first: dict[str, Any] = {}
                    for offset, group in groupby(search.lineage, key=lambda node: node.offset):
                        nodes = list(group)
                        frame = nodes[0].frame
                        expanded = [node for node in nodes if node.parent_id in alive and (
                            not np.isfinite(truth[frame]) or abs(node.frequency_hz - truth[frame]) <= 200e6)]
                        retained = [node for node in expanded if node.retained]
                        if not retained and not first:
                            first = dict(first_loss_frame=frame, first_loss_search_step=offset + 1,
                                first_loss_reason='EXPANDED_THEN_PRUNED' if expanded else 'HYPOTHESIS_NOT_GENERATED',
                                best_truth_consistent_expansion_rank=min(
                                    (node.expansion_rank for node in expanded), default=None),
                                first_loss_cutoff=nodes[0].cutoff_score)
                        alive = {node.hypothesis_id for node in retained}
                    ix = np.asarray(search.window.indices, dtype=int)
                    target_frames = int(np.sum(np.isfinite(truth[ix])))
                    full_lineage_rows.append({**context, 'window_id': window_id, 'kind': search.window.kind,
                        'mode': mode, 'beam_width': search.beam_width,
                        'truth_valid_frames': target_frames,
                        'strongest_error_frames': int(np.sum(np.isfinite(truth[ix]) & (
                            np.abs(strongest[ix] - truth[ix]) > 200e6))),
                        'whole_window_truth_consistent_terminal_count': len(alive) if target_frames else None,
                        'anchor_truth_near': bool(abs(strongest[search.window.anchor] - truth[search.window.anchor])
                                                 <= 200e6) if search.window.anchor is not None else None,
                        'scope': 'FULL_WINDOW_PREFIX; no-target frames are label wildcards', **first})
                for (window_id, mode), search in cache.items():
                    if mode != 'B8' or search.window.kind != 'CORE':
                        continue
                    ix = np.asarray(search.window.indices, dtype=int)
                    valid = np.isfinite(truth[ix]) & np.isfinite(strongest[ix])
                    options = [strongest[ix], *(np.asarray(p.state.frequencies_hz) for p in search.proposals)]
                    errors = [np.abs(path - truth[ix]) for path in options]
                    sse = [float(np.sum(e[valid] ** 2)) for e in errors]
                    best = min(range(len(options)), key=lambda j: (sse[j], j))
                    core_rows.append({**context, 'window_id': window_id, 'anchor': search.window.anchor,
                        'window_frames': len(ix), 'permission_off_proposals': 0,
                        'permission_on_proposals': len(search.proposals),
                        'permission_off_sse_hz2': sse[0], 'permission_on_sse_hz2': sse[best],
                        'sse_gain_hz2': sse[0] - sse[best],
                        'selected_oracle_proposal_id': search.proposals[best - 1].hypothesis_id if best else None,
                        'permission_off_wrong': int(np.sum(errors[0][valid] > a.TOLERANCE_HZ)),
                        'permission_on_wrong': int(np.sum(errors[best][valid] > a.TOLERANCE_HZ)),
                        'oracle_harmed_frames': int(np.sum((errors[best] > errors[0]) & valid)),
                        'scope': 'SAME_WINDOW_ANCHOR_B8_SCORE_PERMISSION_ONLY'})
            del cache
        if context['stage'] != 'FRESH':
            continue
        final_path = output / 'final_streams' / (f'{context["case_id"]}_{context["profile"]}.npz')
        if not final_path.exists():
            continue
        frame_rows = read_csv(output / 'details' / (stem + '_funnel.csv'))
        prune_rows = read_csv(output / 'details' / (stem + '_pruning.csv'))
        lineage = {(r['variant'], r['frame'], r['window_id']): r for r in prune_rows}
        with np.load(final_path) as values:
            for row in frame_rows:
                variant, frame = row['variant'], int(row['frame'])
                frequency = float(values[variant + '_final_frequency_hz'][frame])
                corrected = abs(frequency - float(row['truth_hz'])) <= a.TOLERANCE_HZ
                reason = row['reason']
                ancestor = lineage.get((variant, row['frame'], row['window_id']))
                if (ancestor and reason == 'HYPOTHESIS_NOT_GENERATED'
                    and ancestor['first_loss_reason'] == 'EXPANDED_THEN_PRUNED'):
                    reason = 'BEAM_PRUNED_ANCESTOR'
                if corrected:
                    reason = 'FINAL_CORRECTION'
                elif row['terminal'] == 'True':
                    reason = 'ACCEPTANCE_REJECTED' if row['selected'] == 'True' else 'SELECTOR_NOT_SELECTED'
                final_frames.append({**row, 'final_frequency_hz': frequency,
                    'final_rank': int(values[variant + '_final_rank'][frame]),
                    'accepted': bool(values[variant + '_accepted_mask'][frame]),
                    'final_correction': corrected, 'reason': reason})
    runner.write_csv(output / 'core_permission_matched_windows.csv', core_rows)
    runner.write_csv(output / 'full_window_lineage_loss.csv', full_lineage_rows)
    runner.write_csv(output / 'final_proposal_funnel_detail.csv', final_frames,
                      ('case_id', 'profile', 'variant', 'frame', 'reason', 'accepted'))
    by_variant: list[dict[str, Any]] = []
    for variant in ('P0', 'P1', 'P2', 'P3'):
        rows = [r for r in final_frames if r['variant'] == variant]
        by_variant.append(dict(variant=variant, error_frames=len(rows),
            corrected=sum(r['final_correction'] for r in rows),
            selection_loss=sum(r['reason'] == 'SELECTOR_NOT_SELECTED' for r in rows),
            acceptance_loss=sum(r['reason'] == 'ACCEPTANCE_REJECTED' for r in rows),
            missing_proposal=sum(r['terminal'] == 'False' for r in rows),
            final_correction_recall=a.ratio(sum(r['final_correction'] for r in rows), len(rows))))
    runner.write_csv(output / 'final_funnel_summary.csv', by_variant)


if __name__ == '__main__':
    main()
