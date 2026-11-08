"""TASK-015 paired experiment. Only score() sees truth; all inputs/results retained."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from scipy.signal import butter, sosfilt

from scripts.research.task013 import stage as old
from scripts.research.task014.study import route as route14
from dps_studio.algorithms.waveform.common import Signal
from dps_studio.algorithms.waveform.clutter_varpro.implementation import prefix_tone
from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation.models import EstimatorRequest, Segment
from dps_studio.core.segmentation.pool import default_pool
from dps_studio.core.segmentation.strategies import Strategy, STRATEGIES, estimate_strategy

OUT = Path(__file__).resolve().parents[3] / "artifacts/TASK-015"
ROOT = Path(__file__).resolve().parents[3]
V = 1550e-9/2
FAMILIES = ('low_tone','low_spur','drift_spur','subcycle_ac','stationary_mislabel',
            'onset_step','gradual_onset','fast_accel','fast_decel','turnaround','plateau',
            'weak_fixed','weak_drift','crossing','dropout','colored','noise_only','prefix_target')


@dataclass
class Case:
    signal: Signal
    truth: np.ndarray
    other: np.ndarray
    plan: tuple[Segment, ...]
    metadata: dict


@dataclass
class Trace:
    candidate: np.ndarray
    accepted: np.ndarray
    flags: np.ndarray
    runtime_s: float
    details: list


def make_case(family, index, split, boundary_ns=0., mislabel=False):
    seed = (150000000 if split == 'development' else 151000000)+FAMILIES.index(family)*1000+index
    rng = np.random.default_rng(seed)
    fs, n = 40e9, 12800
    t = np.arange(n)/fs
    t0 = (80+rng.uniform(-2,2))*1e-9
    active = t >= t0
    f = np.full(n, (500+100*(index%4))*1e6)
    amp = np.full(n, .05)
    other = np.full(n, np.nan)
    snr = (0.,8.,16.,-4.)[index%4] if split == 'development' else (-8.,4.,12.,20.)[(index//4)%4]
    events = [(0.,'stationary'), (t0,'onset'), (t0+15e-9,'plateau')]
    cutoff = 0.
    onset = t0
    if family in ('low_tone','low_spur','drift_spur','subcycle_ac','stationary_mislabel'):
        active[:] = True
        onset = None
        f[:] = (20,40,80,120)[index%4]*1e6
        events = [(0., 'stationary')]
        if family == 'drift_spur':
            f[:] = 0.
            amp[:] = 0.
        if family == 'subcycle_ac':
            f[:] = 1.5/V
            cutoff = 50e6
        if family == 'stationary_mislabel':
            f[:] = 1.8e9
    elif family == 'plateau':
        f[:] = (100,400,1200,2400)[index%4]*1e6
    elif family == 'fast_accel':
        f = np.minimum(2.2e9, 150e6+np.maximum(t-t0,0)*4e16)
        events = [(0.,'stationary'),(t0,'acceleration'),(t0+52e-9,'plateau')]
    elif family == 'fast_decel':
        f = 2.2e9-np.clip((t-140e-9)*4e16,0,2e9)
        events += [(140e-9,'decline'),(190e-9,'plateau')]
    elif family == 'turnaround':
        f = 1.8e9-np.clip((t-120e-9)*2.5e16,0,1.5e9)+np.clip((t-180e-9)*3e16,0,1.6e9)
        events += [(120e-9,'decline'),(175e-9,'rebound'),(235e-9,'plateau')]
    elif family in ('weak_fixed','weak_drift','colored','dropout','crossing'):
        f = 600e6+np.maximum(t-t0,0)*2e15
        events = [(0.,'stationary'),(t0,'noise' if family != 'dropout' else 'acceleration')]
        if family == 'dropout':
            amp[(t >= 145e-9) & (t < 175e-9)] = 0.
    elif family == 'prefix_target':
        active[:] = True
        f[:] = 700e6
        onset = None
        events = [(0.,'plateau')]
    elif family == 'noise_only':
        amp[:] = 0.
        active[:] = False
        onset = None
        events = [(0.,'noise')]
    if family == 'gradual_onset':
        amp *= np.clip((t-t0)/20e-9,0,1)
    f = np.where(active,f,0.)
    phase0 = rng.uniform(0,2*np.pi)
    phase = phase0+2*np.pi*np.r_[0,np.cumsum((f[1:]+f[:-1])/(2*fs))]
    clean = amp*np.cos(phase)
    if cutoff:
        clean = sosfilt(butter(1,cutoff,fs=fs,btype='highpass',output='sos'), clean-clean[0])
    if family in ('low_spur','drift_spur','weak_fixed','weak_drift'):
        other[:] = 2e9 if family.startswith(('low','drift')) else 450e6
        if family == 'weak_drift':
            other += (t-t0)*1.5e15
        phase2 = rng.uniform(0,2*np.pi)+2*np.pi*np.cumsum(other)/fs
        clean += .15*np.cos(phase2)
    if family == 'crossing':
        other = 1.2e9-np.maximum(t-t0,0)*2e15
        clean += .055*np.cos(rng.uniform(0,2*np.pi)+2*np.pi*np.cumsum(other)/fs)*active
    sigma = .05/np.sqrt(2*10**(snr/10))
    y = clean+rng.normal(0,sigma,n)+.03+.02*(t/t[-1])**2
    if family == 'drift_spur':
        y += .12*np.exp(-t/(35e-9))
    if family == 'colored':
        colored = sosfilt(butter(1,200e6,fs=fs,output='sos'),rng.normal(size=n))
        y += sigma*colored/np.std(colored)
    truth = f.copy()
    truth[~active] = np.nan
    starts = [0.]+[float(e[0]+boundary_ns*1e-9) for e in events[1:]]
    ends = starts[1:]+[float(t[-1])]
    plan = tuple(Segment(str(i),a,b,'stationary' if mislabel and stage != 'stationary' else stage,
                         observation_quality='interference' if family in
                         ('low_spur','drift_spur','weak_fixed','weak_drift','crossing') else 'unspecified')
                 for i,(a,b,(_,stage)) in enumerate(zip(starts,ends,events)))
    return Case(Signal(t,np.asarray(y),f'{split}_{family}_{index:02d}_b{boundary_ns:g}_m{int(mislabel)}'),
                truth,other,plan,dict(seed=seed,split=split,family=family,index=index,snr_db=snr,
                    phase0_rad=phase0,cutoff_hz=cutoff,onset_s=onset,boundary_ns=boundary_ns,
                    mislabel=mislabel,wavelength_m=2*V))


def request(signal, fmin=5e6):
    return EstimatorRequest(SignalRecord(signal.time_s,signal.voltage_v),
        float(signal.time_s[0]),float(signal.time_s[-1]),2*V,
        dict(window_length_samples=1024,overlap_samples=960,nfft=4096,window_name='hann',
             minimum_frequency_hz=fmin,maximum_frequency_hz=6e9))


def common_grid(signal):
    return np.arange(1024,len(signal.time_s)-1024+1,128)


def extract(estimate, signal):
    q = signal.time_s[common_grid(signal)]
    idx = np.searchsorted(estimate.time_s,q)
    if np.any(idx >= len(estimate.time_s)) or not np.allclose(estimate.time_s[idx],q,rtol=0,atol=5e-15):
        raise AssertionError('Unequal physical centers; interpolation forbidden')
    return Trace(estimate.candidate_frequency_hz[idx],estimate.frequency_hz[idx],
                 np.array(estimate.quality)[idx],0.,[dict(estimate.details)])


def local(signal, plan, spec, name):
    started = perf_counter()
    q = signal.time_s[common_grid(signal)]
    candidate = np.full(len(q),np.nan)
    accepted = candidate.copy()
    flags = np.full(len(q),'UNOBSERVABLE_NOT_ZERO',dtype='U256')
    details=[]
    req = request(signal)
    for j,segment in enumerate(plan):
        result = estimate_strategy(replace(req,segment=segment),name,replace(spec,hop=128))
        selection = (q >= segment.start_s) & (q <= segment.end_s if j == len(plan)-1 else q < segment.end_s)
        idx = np.searchsorted(result.time_s,q[selection])
        if not np.allclose(result.time_s[idx],q[selection],rtol=0,atol=5e-15):
            raise AssertionError('No exact centers')
        candidate[selection]=result.candidate_frequency_hz[idx]
        accepted[selection]=result.frequency_hz[idx]
        flags[selection]=np.array(result.quality)[idx]
        details.append(dict(result.details))
    return Trace(candidate,accepted,flags,perf_counter()-started,details)


def run(signal, plan, family, *, ablations=True):
    cache={}
    def formal(name):
        if name not in cache:
            start=perf_counter()
            cache[name]=extract(default_pool().estimate(name,request(signal,50e6)),signal)
            cache[name].runtime_s=perf_counter()-start
        return cache[name]
    base=formal('stft')
    result={'M1_balanced':base}
    def strategy(name, spec=None):
        if name not in cache:
            cache[name]=local(signal,plan,STRATEGIES[name] if spec is None else spec,name)
        return cache[name]
    def routed(names, name):
        q=signal.time_s[common_grid(signal)]
        trace=Trace(np.full(len(q),np.nan),np.full(len(q),np.nan),
                    np.full(len(q),'UNOBSERVABLE_NOT_ZERO',dtype='U256'),0.,[])
        used=set()
        for j,seg in enumerate(plan):
            chosen=names.get(seg.stage,'stft')
            if chosen == 'unobservable':
                continue
            tr=formal(chosen) if chosen in ('stft','dechirp','clutter_varpro') else strategy(chosen)
            mask=(q >= seg.start_s)&(q <= seg.end_s if j == len(plan)-1 else q < seg.end_s)
            trace.candidate[mask]=tr.candidate[mask]
            trace.accepted[mask]=tr.accepted[mask]
            trace.flags[mask]=tr.flags[mask]
            used.add(chosen)
        trace.runtime_s=sum(cache[key].runtime_s for key in used)
        trace.details=[dict(component=key,details=cache[key].details) for key in sorted(used)]
        result[name]=trace
    routed({'acceleration':'dechirp','noise':'unobservable'},'M2_task014_gui')
    simple={'stationary':'stft_low','onset':'stft_short','rebound':'stft_short',
            'acceleration':'stft_short','decline':'stft_short','plateau':'stft_long',
            'noise':'stft_long','weak_signal':'stft_long'}
    routed(simple,'M3_parameters')
    special={**simple,'stationary':'low_glrt','plateau':'tone_refine',
             'acceleration':'signed_dechirp','decline':'signed_dechirp',
             'noise':'clutter_varpro'}
    routed(special,'M4_specialized')
    if ablations:
        if family in FAMILIES[:5]:
            for name in ('stft_low','low_prior','low_glrt'):
                result[name]=strategy(name)
            result['band_linear']=strategy('band_linear',replace(STRATEGIES['stft_low'],degree=1))
            result['glrt_no_nuisance']=strategy('glrt_no_nuisance',replace(STRATEGIES['low_glrt'],project_nuisance=False))
        if family in ('onset_step','gradual_onset','fast_accel','fast_decel','turnaround','plateau'):
            for width in (256,512,1024,2048):
                name=f'clip_{width}'
                result[name]=strategy(name,Strategy(width=width))
            for boundary in ('full','one_sided'):
                name=f'{boundary}_512'
                result[name]=strategy(name,Strategy(width=512,boundary=boundary))
            result['unsigned_dechirp']=strategy('unsigned_dechirp',Strategy(width=512,mode='chirp'))
            result['signed_dechirp']=strategy('signed_dechirp')
            result['tone_refine']=strategy('tone_refine')
        if family in ('weak_fixed','weak_drift','crossing','dropout','colored','noise_only','prefix_target'):
            result['clutter_varpro']=formal('clutter_varpro')
            result['stft_long']=strategy('stft_long')
            begin=perf_counter()
            prediction,meta=prefix_tone(signal)
            residual=Signal(signal.time_s.copy(),signal.voltage_v-prediction)
            result['background_stft']=local(residual,plan,Strategy(width=1024),'background_stft')
            result['background_stft'].runtime_s=perf_counter()-begin
            result['background_stft'].details.append(meta)
    # Additional exact TASK-014 research parameter-map replay.
    oldplan=tuple(old.Annotation(p.start_s,p.end_s,'low_frequency' if family in ('low_tone','low_spur')
                    else p.stage,persistent_clutter=family=='weak_fixed') for p in plan)
    begin=perf_counter()
    replay=route14(signal,oldplan,{},False)
    result['TASK014_research_simple']=Trace(replay.candidate_hz,replay.accepted_hz,replay.quality,
                                           perf_counter()-begin,[])
    return result


def score(case,traces):
    idx=common_grid(case.signal)
    t=case.signal.time_s[idx]
    truth,other=case.truth[idx],case.other[idx]
    target=np.isfinite(truth)
    branch=target & np.isfinite(other) & (abs(truth-other)>20e6)
    rows=[]
    for name,tr in traces.items():
        for kind,values in (('candidate',tr.candidate),('gated',tr.accepted)):
            finite=target & np.isfinite(values)
            error=(values[finite]-truth[finite])*V
            n,m=int(target.sum()),int(finite.sum())
            record=dict(case=case.signal.name,**case.metadata,method=name,kind=kind,
                target_n=n,finite_n=m,sse=float(error@error),rmse_m_s=float(np.sqrt(np.mean(error**2))) if m else np.nan,
                coverage=m/n if n else np.nan,failure_n=n-m+int((abs(error)>77.5).sum()),
                failure30_n=n-m+int((abs(error)>30).sum()),error50_n=int((abs(error)>50).sum()),
                branch_n=int(branch.sum()),wrong_branch_n=int((branch & np.isfinite(values) &
                    (abs(values-other)<abs(values-truth))).sum()),
                branch_missing_n=int((branch & ~np.isfinite(values)).sum()),
                absent_n=int((~target).sum()),absent_output_n=int((~target & np.isfinite(values)).sum()),
                runtime_s=tr.runtime_s,onset_error_ns=np.nan,onset_missed=0,onset_eligible=0,
                step_error_m_s=np.nan,valley_bias_m_s=np.nan)
            if case.metadata['onset_s'] is not None:
                cross=np.isfinite(values)&(values*V>=100.)
                found=np.flatnonzero(cross[:-1]&cross[1:])
                truth_cross=np.flatnonzero(np.isfinite(case.truth)&(case.truth*V>=100.))
                if len(truth_cross):
                    record['onset_eligible']=1
                    record['onset_missed']=int(not len(found))
                    if len(found):
                        record['onset_error_ns']=(t[found[0]]-case.signal.time_s[truth_cross[0]])*1e9
                near=(t>=case.metadata['onset_s'])&(t<case.metadata['onset_s']+15e-9)&finite
                if near.any():
                    record['step_error_m_s']=float(np.mean(abs(values[near]-truth[near]))*V)
            if case.metadata['family']=='turnaround':
                near=(t>=170e-9)&(t<=190e-9)&finite
                if near.any():
                    record['valley_bias_m_s']=float((np.min(values[near])-np.min(truth[(t>=170e-9)&(t<=190e-9)]))*V)
            rows.append(record)
    return rows


def run_case(payload):
    destination,split,spec,sensitivity=payload
    family,index,boundary,mislabel=spec
    case=make_case(family,index,split,boundary,mislabel)
    before=hashlib.sha256(case.signal.voltage_v.tobytes()).hexdigest()
    traces=run(case.signal,case.plan,family,ablations=not sensitivity)
    assert before==hashlib.sha256(case.signal.voltage_v.tobytes()).hexdigest()
    arrays=dict(time_s=case.signal.time_s,voltage_v=case.signal.voltage_v,truth_hz=case.truth,
                other_hz=case.other,centers=common_grid(case.signal))
    for name,tr in traces.items():
        arrays[name+'__candidate']=tr.candidate
        arrays[name+'__accepted']=tr.accepted
        arrays[name+'__flags']=tr.flags
    np.savez_compressed(destination/'cases'/f'{case.signal.name}.npz',**arrays)
    details=dict(metadata=case.metadata,plan=[asdict(p) for p in case.plan],input_sha256=before,
                 algorithms={name:tr.details for name,tr in traces.items()})
    import gzip
    with gzip.open(destination/'cases'/f'{case.signal.name}.json.gz','wt',encoding='utf-8') as stream:
        json.dump(details,stream,allow_nan=True)
    return case.signal.name,score(case,traces)


def execute(destination, split, count, sensitivity=False, workers=4):
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'cases').mkdir()
    sources=[Path(__file__),ROOT/"docs/tasks/TASK-015/PROTOCOL.md",*sorted((ROOT/'src/dps_studio/core/segmentation').glob('*.py'))]
    freeze=dict(sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                split=split,count=count,strategies={k:asdict(v) for k,v in STRATEGIES.items()},
                no_truth_in_estimators=True,common_centers='1024+128k <= N-1024',
                workers=workers,cost='parallel wall time; dedicated serial timing reported separately',
                argv=__import__('sys').argv)
    (destination/'freeze.json').write_text(json.dumps(freeze,indent=2),encoding='utf-8')
    rows=[]
    specs=[(f,i,0.,False) for f in FAMILIES for i in range(count)]
    if sensitivity:
        specs=[(f,i,b,m) for f in ('onset_step','fast_accel','turnaround') for i in range(count)
               for b,m in [(-30.,False),(-15.,False),(-5.,False),(5.,False),(15.,False),(30.,False),(0.,True)]]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for number,(name,case_rows) in enumerate(executor.map(run_case,
                [(destination,split,spec,sensitivity) for spec in specs]),1):
            rows.extend(case_rows)
            pd.DataFrame(rows).to_csv(destination/'metrics.csv',index=False)
            print(f'{number}/{len(specs)} {name}',flush=True)
    (destination/'complete.json').write_text(json.dumps(dict(cases=len(specs),rows=len(rows))),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('split',choices=['development','heldout'])
    p.add_argument('--count',type=int,default=4)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--sensitivity',action='store_true')
    p.add_argument('--workers',type=int,default=4)
    args=p.parse_args()
    if not args.output.resolve().is_relative_to(OUT):
        p.error('Output must remain inside TASK-015')
    execute(args.output,args.split,args.count,args.sensitivity,args.workers)
