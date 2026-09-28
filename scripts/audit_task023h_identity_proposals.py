"""Supplement I3 with actual frozen candidate/proposal invariance under label swap."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023h_pair_audit as a
from dps_studio.research import task023h_raw_evidence as e
from dps_studio.research.task023e_waveform_benchmark import (
    PROFILES, SAMPLE_RATE_HZ, ambiguous_pair, profile_input,
)
from scripts import run_task023f_proposal_recovery as r
from scripts.run_task023h_raw_audit import configs, freeze_evidence


def audit_one(index: int) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    first,second=ambiguous_pair(index)
    ambiguity,config=configs()
    rows,pairs=[],[]
    for profile in PROFILES:
        hashes=[]
        snapshots=[]
        for case in (first,second):
            stft,candidates,truth,_=profile_input(case,profile)
            original=r.original_e4(candidates,stft)
            broadband=f.broadband_evidence(stft)
            searches=tuple(f.generate_proposals(w,original,candidates,ambiguity,config,broadband,
                diversity=True) for w in f.windows(original,f.ProposalConfig(),ambiguity)
                if w.indices and w.anchor is not None)
            hashes.append(a.fingerprint((stft.spectrum,candidates,original,searches)))
            snapshots.append((candidates,truth,searches))
        assert hashes[0]==hashes[1]
        candidates,truth,searches=snapshots[0]
        z=e.analytic_signal(first.record.time_s,first.record.voltage_v)
        pair_count=0
        for search in searches:
            nodes={n.hypothesis_id:n for n in search.lineage}
            views=[a.prefix_view(search,p.hypothesis_id,nodes) for p in search.proposals]
            pair=a.pick_pair(views,truth)
            if pair is None:
                continue
            context=dict(waveform=first.observation_group,observation_group=first.observation_group,
                profile=profile.profile_id.value,role='IDENTITY_SWAP_CONTROL',family='ambiguity_label_swap',
                candidate_sha256=a.fingerprint(candidates),proposal_sha256=a.fingerprint(searches),
                target_identity='A; identical observation also labelled B')
            value=a.score_pair(pair,context,candidates,first.record.time_s,z,
                profile.window_length_samples/SAMPLE_RATE_HZ,truth,'IDENTITY_SWAP_AMBIGUITY',
                'TERMINAL',search.window.window_id)
            # Same fixed proposals under changed truth labels: score values must match exactly.
            other=a.score_pair(pair,context,candidates,second.record.time_s,
                e.analytic_signal(second.record.time_s,second.record.voltage_v),
                profile.window_length_samples/SAMPLE_RATE_HZ,snapshots[1][1],
                'IDENTITY_SWAP_AMBIGUITY','TERMINAL',search.window.window_id)
            assert value['scores']==other['scores']
            value['truth_max_error_under_identity_B_hz']=other['truth_max_error_hz']
            value['observation_evidence_identical']=True
            pairs.append(value)
            pair_count+=1
        rows.append(dict(observation_group=first.observation_group,profile=profile.profile_id.value,
            frozen_graph_hash_A=hashes[0],frozen_graph_hash_B=hashes[1],identical=True,
            generated_windows=len(searches),terminal_proposals=sum(len(s.proposals) for s in searches),
            strict_identity_comparison_pairs=pair_count,
            status='OBSERVATIONALLY_NON_IDENTIFIABLE',
            pair_status='AVAILABLE' if pair_count else 'NO_TWO_STRICT_FROZEN_TERMINAL_PROPOSALS'))
    return rows,pairs


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args().output.resolve()
    freeze_evidence(output)
    rows,pairs=[],[]
    with ProcessPoolExecutor(max_workers=4) as pool:
        for current,comparisons in pool.map(audit_one,range(16)):
            rows.extend(current)
            pairs.extend(comparisons)
    r.write_csv(output/'identity_swap_frozen_graph_audit.csv',rows)
    r.write_json(output/'ambiguity_proposal_pair_manifest.json',pairs)
    print(f'32 profile checks; {len(pairs)} strict frozen identity pairs',flush=True)


if __name__=='__main__':
    main()
