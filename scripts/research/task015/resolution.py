"""Predeclared pulse separation supplement; exact-grid estimates, no GT routing."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

from scripts.research.task015.experiment import common_grid, extract, local, request
from dps_studio.algorithms.waveform.common import Signal
from dps_studio.core.segmentation import Segment, default_pool
from dps_studio.core.segmentation.strategies import Strategy

OUT=(Path(__file__).resolve().parents[3] / "artifacts/TASK-015")/'data/resolution'


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    rows=[]
    for duration_ns in (2,4,8,16,32):
        for index in range(4):
            rng=np.random.default_rng(152000000+duration_ns*100+index)
            t=np.arange(12800)/40e9
            begin=(120+rng.uniform(-1.6,1.6))*1e-9
            end=begin+duration_ns*1e-9
            pulse=(t>=begin)&(t<end)
            truth=np.where(pulse,1.8e9,600e6)
            phase=rng.uniform(0,2*np.pi)+2*np.pi*np.cumsum(truth)/40e9
            snr=(6,18)[index%2]
            y=.05*np.cos(phase)+rng.normal(0,.05/np.sqrt(2*10**(snr/10)),len(t))
            signal=Signal(t,y)
            plan=(Segment('a',t[0],begin,'plateau'),Segment('b',begin,end,'onset'),
                  Segment('c',end,t[-1],'plateau'))
            methods={'M1_balanced':extract(default_pool().estimate('stft',request(signal,50e6)),signal)}
            for width in (256,512,1024,2048):
                for boundary in ('full','clip'):
                    name=f'{boundary}_{width}'
                    methods[name]=local(signal,plan,Strategy(width=width,boundary=boundary),name)
            q=t[common_grid(signal)]
            arrays=dict(time_s=q,truth_hz=truth[common_grid(signal)])
            for name,tr in methods.items():
                high=np.isfinite(tr.accepted)&(tr.accepted>1.2e9)
                region=(q>=begin-50e-9)&(q<=end+50e-9)
                inside=(q>=begin)&(q<end)
                resolved=bool(np.any(high&inside))
                detected_width=float(high[region].sum()*128/40e9*1e9)
                rows.append(dict(duration_ns=duration_ns,index=index,snr_db=snr,method=name,
                    grid_centers_inside=int(inside.sum()),resolved=resolved,
                    detected_width_ns=detected_width,width_error_ns=detected_width-duration_ns,
                    false_high_centers=int((high&~inside&region).sum()),
                    accepted_inside=int((np.isfinite(tr.accepted)&inside).sum()),
                    annotation='exact operator boundaries; no automatic timing claim',hop_ns=3.2))
                arrays[name]=tr.accepted
            np.savez_compressed(OUT/f'pulse_{duration_ns}_{index}.npz',**arrays)
        print(f'pulse {duration_ns} ns complete',flush=True)
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    (OUT/'complete.json').write_text(json.dumps(dict(records=20,rows=len(rows),tuned_on_results=False)),encoding='utf-8')


if __name__=='__main__':
    main()
