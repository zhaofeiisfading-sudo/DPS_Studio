"""All indexed raw streams, complete time records, Hz diagnostics only."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import gzip
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from scripts.research.task015.experiment import Trace, common_grid, local, request
from dps_studio.algorithms.waveform.common import Signal
from dps_studio.core.segmentation import Segment, default_pool
from dps_studio.core.segmentation.strategies import STRATEGIES
from dps_studio.research.task009_data import inventory, read_raw

OUT=(Path(__file__).resolve().parents[3] / "artifacts/TASK-015")/'data/real_v02'


def extract(estimate, signal):
    # Formal STFT constructs ideal timestamps; measured CSV timestamps can
    # differ by rounding. Match original integer sample centers, never curves.
    native=np.rint((estimate.time_s-signal.time_s[0])*signal.fs).astype(np.int64)
    q=common_grid(signal)
    idx=np.searchsorted(native,q)
    if np.any(idx >= len(native)) or not np.array_equal(native[idx],q):
        raise AssertionError('Integer physical sample centers differ')
    if not np.allclose(estimate.time_s[idx],signal.time_s[q],rtol=0,atol=5e-15):
        raise AssertionError('Physical time differs beyond timestamp rounding')
    return Trace(estimate.candidate_frequency_hz[idx],estimate.frequency_hz[idx],
                 np.array(estimate.quality)[idx],0.,[dict(estimate.details)])


def execute(item):
    rows=[]
    for original in read_raw(item):
        signal=Signal(original.time_s,original.voltage_v,original.name)
        plan=(Segment('whole',float(signal.time_s[0]),float(signal.time_s[-1])),)
        started=perf_counter()
        base=extract(default_pool().estimate('stft',request(signal,50e6)),signal)
        base.runtime_s=perf_counter()-started
        methods={'M1_balanced':base}
        for name in ('stft_short','stft_long','low_glrt','tone_refine'):
            # Low-frequency option is a hypothesis, never a claimed real stationary label.
            methods[name]=local(signal,plan,replace(STRATEGIES[name],hop=128),name)
        started=perf_counter()
        methods['clutter_varpro']=extract(default_pool().estimate('clutter_varpro',request(signal)),signal)
        methods['clutter_varpro'].runtime_s=perf_counter()-started
        arrays=dict(time_s=signal.time_s[common_grid(signal)])
        details={}
        for name,tr in methods.items():
            valid=np.isfinite(tr.accepted)
            paired=valid & np.isfinite(base.accepted)
            diff=abs(tr.accepted[paired]-base.accepted[paired])
            rows.append(dict(file=item['local_path'],channel=original.name,method=name,
                raw_samples=len(signal.time_s),centers=len(valid),finite_n=int(valid.sum()),
                paired_n=int(paired.sum()),disagreement_100MHz_n=int((diff>1e8).sum()),
                median_abs_difference_hz=float(np.median(diff)) if len(diff) else None,
                runtime_s=tr.runtime_s,identity='UNVALIDATED',prior_zero_n=0,bridge_n=0,
                no_physical_velocity_calibration=True))
            arrays[name+'__candidate']=tr.candidate
            arrays[name+'__accepted']=tr.accepted
            arrays[name+'__flags']=tr.flags
            details[name]=tr.details
        np.savez_compressed(OUT/(original.name+'.npz'),**arrays)
        with gzip.open(OUT/(original.name+'.json.gz'),'wt',encoding='utf-8') as f:
            json.dump(details,f,allow_nan=True)
        print(original.name,flush=True)
    return rows


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=False)
    items=[item for item in inventory() if item['kind']=='RAW']
    rows=[]
    with ProcessPoolExecutor(max_workers=3) as executor:
        for result in executor.map(execute,items):
            rows.extend(result)
            pd.DataFrame(rows).to_csv(OUT/'diagnostics.csv',index=False)
    (OUT/'complete.json').write_text(json.dumps(dict(files=len(items),streams=len(rows)//6,
        rows=len(rows),real_truth=False,routing='unknown: M2/M3/M4 equal M1 by definition; optional strategy diagnostics listed separately')),
        encoding='utf-8')
