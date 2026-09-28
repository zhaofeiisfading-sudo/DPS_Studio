"""Additional descriptive accounting and end-of-task boundary verification."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research import task023h_raw_evidence as e
from scripts import run_task023f_proposal_recovery as r
from scripts.finalize_task023f_recovery import read_csv


def diagnostics(output: Path) -> None:
    legacy_rows = []
    raw_model_rows = []
    for path in sorted((output/'streams').glob('*.json')):
        stream = json.loads(path.read_text())
        pairs = stream['pairs']
        if path.name.endswith('_legacy.json'):
            counters: dict[tuple[str,str],int] = defaultdict(int)
            for event in stream['ledger']:
                if event['stage'] != 'pruning':
                    continue
                scope,window = event['scope'],event['window']
                index=counters[window,scope]
                counters[window,scope]+=1
                pair=next((p for p in pairs if p['window']==window and p['scope']==scope
                           and p['event_id']==str(index)),None)
                row=dict(waveform=event['waveform'],profile=event['profile'],window=window,
                    event_id=index,scope=scope,taxonomy=event['taxonomy'],
                    affected_legacy_frames=int(event['affected_error_frames']),
                    strict_pair_available=pair is not None,
                    meaning='PAIRWISE_DIAGNOSTIC_ONLY; NOT_RECOVERABLE_RETENTION_COUNT')
                for feature in e.FEATURES:
                    row[feature+'_prefers_correct']=(pair['scores'][0][feature]-pair['scores'][1][feature] > 1e-12
                                                    if pair else False)
                legacy_rows.append(row)
        # GT-only error accounting already stored at frozen knots. No new feature.
        for pair in pairs:
            if pair['role']=='FRESH' and pair['scope']!='LOCAL_SUBPATH':
                for side,label in enumerate(('truth_near','wrong')):
                    raw_model_rows.append(dict(waveform=pair['waveform'],pair_id=pair['pair_id'],side=label,
                        knot_rmse_hz=float(np.sqrt(pair['truth_mse_hz2'][side])),
                        knot_max_error_hz=pair['truth_max_error_hz'][side],
                        evidence_duration_s=pair['time_end_s']-pair['time_start_s'],
                        E1=pair['scores'][side]['E1'],E2=pair['scores'][side]['E2'],
                        error_scope='GT_AT_FROZEN_KNOTS; raw sample frequency error not measured'))
    strict=[v for v in legacy_rows if v['scope']=='PRUNING_PREFIX']
    assert sum(v['affected_legacy_frames'] for v in strict)==1699
    r.write_csv(output/'legacy_retention_evidence_accounting.csv',legacy_rows)
    r.write_csv(output/'proposal_frequency_error_diagnostic.csv',raw_model_rows)
    summary=[]
    for scope in ('PRUNING_PREFIX','LOCAL_SUBPATH'):
        for taxonomy in sorted({v['taxonomy'] for v in legacy_rows}):
            values=[v for v in legacy_rows if v['scope']==scope and v['taxonomy']==taxonomy]
            row=dict(scope=scope,taxonomy=taxonomy,events=len(values),
                frames=sum(v['affected_legacy_frames'] for v in values),
                paired_events=sum(v['strict_pair_available'] for v in values),
                paired_frames=sum(v['affected_legacy_frames'] for v in values if v['strict_pair_available']))
            for feature in e.FEATURES:
                row[feature+'_preference_frames']=sum(v['affected_legacy_frames'] for v in values
                                                       if v[feature+'_prefers_correct'])
            summary.append(row)
    r.write_csv(output/'legacy_retention_evidence_summary.csv',summary)
    real=read_csv(output/'real_data_raw_evidence.csv')
    real_summary=[]
    for stream_id in sorted({v['stream'] for v in real}):
        rows=[v for v in real if v['stream']==stream_id and v['kind']=='STRONGEST_LOCAL_CONSTANT']
        alt=[v for v in real if v['stream']==stream_id and v['kind']=='EXISTING_TERMINAL_PROPOSAL']
        for feature in e.FEATURES:
            score_values=np.array([float(v[feature]) for v in rows])
            finite=score_values[np.isfinite(score_values)]
            real_summary.append(dict(stream=stream_id,feature=feature,frames=len(rows),
                finite_frames=len(finite),q05=float(np.quantile(finite,.05)),
                median=float(np.median(finite)),q95=float(np.quantile(finite,.95)),
                alternative_proposals=len(alt),
                alternatives_above_strongest=sum(float(v[feature+'_minus_strongest'])>0 for v in alt),
                scope='DESCRIPTIVE_ONLY; no correctness, threshold or interval'))
    r.write_csv(output/'real_behavior_summary.csv',real_summary)
    sweep=read_csv(output/'identifiability_sweep.csv')
    summary_sweep=[]
    for profile in ('balanced','high_time_resolution'):
        values=[v for v in sweep if v['profile']==profile]
        for feature in e.FEATURES:
            summary_sweep.append(dict(profile=profile,feature=feature,grid_points=len(values),
                candidate_separable=sum(v['candidate_separable']=='True' for v in values),
                proposal_separable=sum(v['proposal_separable']=='True' for v in values),
                no_registered_window=sum(int(v['registered_windows'])==0 for v in values),
                near_evidence_ties=sum(v[feature+'_near_tie']=='True' for v in values),
                prefers_target=sum(v[feature+'_prefers_target']=='True' for v in values),
                warning='Grid fractions depend on declared grid, not prevalence estimates or impossibility proof'))
    r.write_csv(output/'identifiability_summary.csv',summary_sweep)
    r.write_json(output/'diagnostic_completion.json',dict(legacy_frames=1699,
        real_streams=len({v['stream'] for v in real}),sweep_profile_streams=len(sweep)))


def integrity(output: Path) -> dict[str, Any]:
    frozen=json.loads((output/'frozen_manifest.json').read_text())
    rows=[]
    for name,root in (('Research',r.ROOT),('Production',r.ROOT.parent/'DPS_Studio')):
        for relative,digest in frozen['hashes'][name].items():
            current=r.sha256(root/relative)
            rows.append(dict(worktree=name,path=relative,sha256_before=digest,
                sha256_after=current,unchanged=current==digest,raw=relative.startswith('data/raw/')))
    table=output/('integrity_check_verified.csv' if (output/'integrity_check.csv').exists()
                  else 'integrity_check.csv')
    r.write_csv(table,rows)
    assert all(v['unchanged'] for v in rows),'Frozen file modified'
    snapshots={name:{cmd:subprocess.check_output(['git',*cmd.split()],cwd=root,text=True).strip()
        for cmd in ('status --short --branch','rev-parse HEAD','branch --show-current',
                    'rev-parse main','diff','diff --cached')}
        for name,root in (('Research',r.ROOT),('Production',r.ROOT.parent/'DPS_Studio'))}
    assert snapshots['Production']==frozen['git']['Production']
    for cmd in ('rev-parse HEAD','branch --show-current','rev-parse main','diff','diff --cached'):
        assert snapshots['Research'][cmd]==frozen['git']['Research'][cmd]
    # Include untracked new task files in whitespace validation without git index writes.
    checks=[]
    for path in sorted([*(r.ROOT/'scripts').glob('*task023h*.py'),
                        *(r.ROOT/'src/dps_studio/research').glob('task023h*.py'),
                        *(r.ROOT/'tests/unit').glob('test_task023h*.py')]):
        result=subprocess.run(['git','-c','core.autocrlf=false','diff','--no-index','--check',
                               '--','NUL',str(path)],
            cwd=r.ROOT,text=True,capture_output=True)
        checks.append(dict(path=str(path.relative_to(r.ROOT)),exit_code=result.returncode,
                           output=result.stdout+result.stderr))
    subprocess.run(['git','diff','--check'],cwd=r.ROOT,check=True)
    # --no-index implies --exit-code: 1 means the new file differs from NUL.
    # Whitespace errors are reported in output; code 2+ is an actual check failure.
    assert all(v['exit_code'] in (0,1) and not v['output'] for v in checks),checks
    r.write_json(output/'git_diff_check.json',checks)
    r.write_json(output/'repository_after.json',snapshots)
    return dict(all_preexisting_files_unchanged=True,raw_entries=sum(v['raw'] for v in rows),
        raw_sha256_unchanged=True,production_unchanged=True,main_refs_unchanged=True,
        no_commit_push_merge_rebase_cherry_pick_promotion=True,
        frozen_files=len(rows),new_files_only=True)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--phase',choices=['diagnostics','integrity'],required=True)
    args=parser.parse_args()
    if args.phase=='diagnostics':
        diagnostics(args.output.resolve())
    else:
        r.write_json(args.output/'integrity_summary.json',integrity(args.output.resolve()))


if __name__=='__main__':
    main()
