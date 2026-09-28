"""Post hoc verification of development crowding witnesses, without parameter selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dps_studio.research import task023f_proposals as f
from dps_studio.research.task023e_waveform_benchmark import PROFILES, generate_case, profile_input
from scripts import run_task023f_proposal_recovery as runner
from scripts.evaluate_task023f_frozen import artifact_stem, load_searches
from scripts.finalize_task023f_recovery import read_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    rows = []
    for path in sorted((output / 'streams').glob('E23*.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        context = result['context']
        if context['stage'] != 'DEVELOPMENT':
            continue
        stem = artifact_stem(output, context)
        events = [r for r in read_csv(output / 'details' / (stem + '_pruning.csv'))
                  if r['variant'] == 'P1' and r['first_loss_here'] == 'True'
                  and r['truth_prefix_displaced_by_duplicates'] == 'True']
        if not events:
            continue
        cache = load_searches(output, context)
        case = generate_case(context['family'], context['instance'])
        profile = next(p for p in PROFILES if p.profile_id.value == context['profile'])
        stft, _, truth, _ = profile_input(case, profile)
        broadband = f.broadband_evidence(stft)
        for event in events:
            frame = int(event['frame'])
            search = cache[event['window_id'], 'B8']
            rank = int(event['best_expansion_rank'])
            nodes = [n for n in search.lineage if n.frame == frame]
            node = next(n for n in nodes if n.expansion_rank == rank)
            best = min(n.score for n in nodes)
            eligible = (node.identity >= .62 and node.local_support >= .65
                        and (broadband[frame] < 3. or node.local_support >= .75)
                        and node.score - best <= 8.)
            diverse = cache[event['window_id'], 'DIVERSITY_B8']
            offset = diverse.window.indices.index(frame)
            baseline_near = any(abs(p.state.frequencies_hz[offset] - truth[frame]) <= 200e6
                                for p in search.proposals)
            diverse_near = any(abs(p.state.frequencies_hz[offset] - truth[frame]) <= 200e6
                               for p in diverse.proposals)
            rows.append({**context, 'window_id': event['window_id'], 'frame': frame,
                'truth_consistent_expansion_id': node.hypothesis_id, 'parent_id': node.parent_id,
                'expansion_rank': node.expansion_rank, 'cutoff': node.cutoff_score,
                'score_gap_to_best': node.score - best, 'identity': node.identity,
                'local_support': node.local_support, 'broadband_z': float(broadband[frame]),
                'family': node.family, 'family_occupancy': node.family_occupancy,
                'other_retained_duplicates': any(n.retained and n.family_occupancy > 1 for n in nodes),
                'diversity_guard_eligible': eligible,
                'b8_terminal_truth_near': baseline_near, 'diversity_terminal_truth_near': diverse_near,
                'strong_causal_witness': eligible and node.family_occupancy == 0 and not baseline_near and diverse_near})
        del cache
    runner.write_csv(output / 'diversity_causal_witnesses.csv', rows)
    runner.write_json(output / 'diversity_causal_verification.json', dict(
        original_crowding_events=len(rows), guard_eligible_events=sum(r['diversity_guard_eligible'] for r in rows),
        strong_causal_witnesses=sum(r['strong_causal_witness'] for r in rows),
        role='Verification only: activation and parameters remain frozen'))


if __name__ == '__main__':
    main()
