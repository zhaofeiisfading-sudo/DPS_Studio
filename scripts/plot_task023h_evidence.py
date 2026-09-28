"""Reproducible figures from saved audit tables; no model fitting or new feature."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from dps_studio.research import task023h_raw_evidence as e
from scripts import run_task023f_proposal_recovery as r
from scripts.finalize_task023f_recovery import read_csv
from scripts.run_task023h_raw_audit import fresh_case

COLORS = ['#332288', '#0077bb', '#ee7733', '#009988', '#cc3311']


def save(figure: Figure, output: Path, name: str) -> None:
    figure.savefig(output/'figures'/(name+'.png'), dpi=300)
    figure.savefig(output/'figures'/(name+'.pdf'))


def ranking(output: Path) -> None:
    rows = read_csv(output/'pairwise_separability_by_family.csv')
    selected = [v for v in rows if v['role']=='FRESH' and v['scope']=='STRICT_WHOLE_HISTORY'
                and v['aggregation']=='WAVEFORM_MACRO']
    figure = Figure(figsize=(12, 5), layout='constrained')
    axis = figure.subplots()
    groups = ['ALL','PERSISTENT_SCORE_INFERIOR','SELECTION_LOSS','CORRECT_SELECTION_CONTROL']
    labels = ['All strict pairs','Persistent score inferior','Selection loss','Correct controls']
    x = np.arange(4)
    for j, feature in enumerate(['Frozen E4', *e.FEATURES]):
        data = [next(v for v in selected if v['stratum']==tag and v['feature']==
                     ('E1' if j==0 else feature)) for tag in groups]
        values = [100*float(v['baseline_accuracy' if j==0 else 'raw_accuracy']) for v in data]
        axis.bar(x+(j-2)*.15, values, width=.145, color=COLORS[j], label=feature)
    axis.set_xticks(x, [label+'\nn='+next(v['pairs'] for v in selected if v['stratum']==tag)
                       for label, tag in zip(labels,groups,strict=True)])
    axis.set(ylabel='Pairwise ranking accuracy (%)', ylim=(0,105))
    axis.legend(ncol=5, loc='upper center', bbox_to_anchor=(.5,1.15))
    axis.grid(axis='y', alpha=.15)
    figure.suptitle('Fresh 128 waveforms: waveform-macro; profiles grouped within waveform', fontsize=11)
    save(figure, output, '01_pairwise_ranking')
    pair_rows = [v for v in read_csv(output/'raw_domain_pairwise_scores.csv')
        if v['role']=='FRESH' and v['scope']!='LOCAL_SUBPATH' and v['taxonomy']!='NO_VALID_DESCENDANT']
    figure = Figure(figsize=(12,7), layout='constrained')
    axes = figure.subplots(2,3).ravel()
    for j, feature in enumerate(['Frozen E4', *e.FEATURES]):
        data = [v for v in pair_rows if v['feature']==('E1' if j==0 else feature)]
        differences = np.array([float(v['baseline_difference' if j==0 else 'difference']) for v in data])
        differences = differences[np.isfinite(differences)]
        axes[j].hist(differences, bins=50, color=COLORS[j])
        axes[j].axvline(0,color='black',linewidth=.8)
        axes[j].set(xlabel='Correct minus wrong '+('(-cost)' if j==0 else 'evidence'),
                    ylabel='Pairs', title=feature)
        axes[j].set_yscale('symlog', linthresh=1)
    axes[-1].axis('off')
    axes[-1].text(.03,.7,'Strict fresh pairs only\nPositive favors truth-near\n'
        'Count axes use symlog\nDifferent statistics have different units\nNo feature selection / rescaling',fontsize=11)
    save(figure, output, '02_score_difference_histogram')


def persistent_example(output: Path) -> None:
    rows = read_csv(output/'proposal_pair_manifest.csv')
    choices = [v for v in rows if v['taxonomy']=='PERSISTENT_SCORE_INFERIOR']
    choices.sort(key=lambda v:(v['role']!='FRESH',v['scope']=='LOCAL_SUBPATH',v['pair_id']))
    figure = Figure(figsize=(12,9), layout='constrained')
    if not choices:
        axis = figure.subplots()
        axis.axis('off')
        axis.text(.1,.5,'NO AVAILABLE PERSISTENT_SCORE_INFERIOR PAIR\nNo demodulation example fabricated.')
        save(figure, output, '03_persistent_demodulation_UNAVAILABLE')
        return
    pair = choices[0]
    case = (fresh_case(pair['family'], int(pair['instance'])) if pair['role']=='FRESH'
            else r.fresh_case(pair['family'], int(pair['instance'])))
    assert r.sha256(output/'waveforms'/(case.case_id+'.npz')) if pair['role']=='FRESH' else True
    frames = json.loads(pair['full_frames'])
    chosen_frames = json.loads(pair['evidence_frames'])
    frequencies = json.loads(pair['frequency_history'])
    # Existing STFT centers are exactly window/2 + j*128 raw samples.
    window_samples = 768 if pair['profile']=='balanced' else 512
    knot_time = (window_samples/2+np.asarray(chosen_frames)*128)/40e9
    raw = case.record.time_s
    z = e.analytic_signal(raw, case.record.voltage_v)
    axes = figure.subplots(3,1)
    for side in range(2):
        kf = np.array([frequencies[side][frames.index(frame)] for frame in chosen_frames])
        mask, sample_freq = e.proposal_model(raw,knot_time,kf)
        phase = e.integrate_phase(raw[mask],sample_freq)
        demod = z[mask]*np.exp(-1j*phase)
        color = COLORS[1 if side==0 else 2]
        label = 'truth-near' if side==0 else 'wrong competitor'
        axes[0].plot(knot_time*1e9,kf/1e9,'.-',color=color,label=label)
        axes[1].plot(raw[mask]*1e9,np.real(demod),color=color,alpha=.65,label=label+' Re')
        spectrum = abs(np.fft.fftshift(np.fft.fft(demod)))**2
        rf = np.fft.fftshift(np.fft.fftfreq(len(demod),1/40e9))
        axes[2].plot(rf/1e6,spectrum/spectrum.sum(),color=color,label=label)
    axes[0].set(ylabel='Frequency (GHz)')
    axes[1].set(xlabel='Raw sample time (ns)',ylabel='Demodulated real part (V)')
    axes[2].set(xlabel='Residual frequency (MHz)',ylabel='Energy fraction / FFT bin',xlim=(-600,600))
    for axis in axes:
        axis.legend(fontsize=9)
    figure.suptitle(pair['waveform']+' / '+pair['profile']+' / '+pair['scope']+
        '\nFirst deterministic eligible example; does not establish physical identity',fontsize=11)
    save(figure,output,'03_persistent_demodulation')
    r.write_json(output/'demodulation_example_manifest.json',pair)


def maps(output: Path) -> None:
    rows = read_csv(output/'identifiability_sweep.csv')
    for name, yfield, fixed, ylabel in (
        ('04_separation_snr_map','snr_db',{'chirp_difference_hz_per_s':0.},'SNR (dB)'),
        ('05_chirp_separation_map','chirp_difference_hz_per_s',{'snr_db':0.},'Chirp difference (10^15 Hz/s)')):
        selected = [v for v in rows if v['profile']=='balanced' and float(v['amplitude_ratio'])==1.
            and float(v['fade_depth'])==0. and all(float(v[k])==x for k,x in fixed.items())]
        xs=sorted({float(v['separation_mhz']) for v in selected})
        ys=sorted({float(v[yfield]) for v in selected})
        figure=Figure(figsize=(13,7),layout='constrained')
        axes=figure.subplots(2,3).ravel()
        for j,feature in enumerate(['candidate_separable','proposal_separable',*e.FEATURES]):
            matrix=np.full((len(ys),len(xs)),np.nan)
            for row in selected:
                value=(float(row[feature]=='True') if j<2 else float(row[feature+'_difference']))
                matrix[ys.index(float(row[yfield])),xs.index(float(row['separation_mhz']))]=value
            plot=axes[j].imshow(matrix,origin='lower',aspect='auto',
                cmap='Blues' if j<2 else 'PuOr',vmin=0 if j<2 else -1,vmax=1)
            axes[j].set_xticks(range(len(xs)),[str(int(x)) for x in xs])
            axes[j].set_yticks(range(len(ys)),[f'{y/1e15:g}' if 'chirp' in yfield else f'{y:g}' for y in ys])
            axes[j].set(xlabel='Separation at center (MHz)',ylabel=ylabel,title=feature)
            figure.colorbar(plot,ax=axes[j],shrink=.75,label='Exists' if j<2 else 'Target - nuisance')
        figure.suptitle('Controlled grid / Balanced / ratio=1 / no fade\n'
            'Known-template evidence is separate from generated-proposal existence; one shared noise realization',fontsize=11)
        save(figure,output,name)


def identity(output: Path) -> None:
    example=json.loads((output/'identity_swap_example.json').read_text())[0]
    figure=Figure(figsize=(11,6),layout='constrained')
    axes=figure.subplots(2,1)
    axes[0].plot(np.array(example['time_s'])*1e9,example['voltage_v'],color=COLORS[1])
    axes[0].set(xlabel='Time (ns)',ylabel='Same voltage (V)')
    x=np.arange(4)
    for j in range(2):
        axes[1].bar(x+(j-.5)*.3,[example['scores'][0][j][feature] for feature in e.FEATURES],
            width=.3,color=COLORS[j+1],label=f'Fixed proposal {j}: same evidence under both labels')
    axes[1].set_xticks(x,list(e.FEATURES))
    axes[1].set(ylabel='Evidence',ylim=(0,1))
    axes[1].legend(fontsize=9)
    figure.suptitle('OBSERVATIONALLY NON-IDENTIFIABLE: target label swaps, observation and evidence do not',fontsize=11)
    save(figure,output,'06_identity_swap')


def real_overlays(output: Path) -> None:
    for profile,label in [('balanced','07_ch3_balanced'),('high_time_resolution','08_ch3_high_time')]:
        value=json.loads((output/'real_streams'/f'ch3__{profile}__pdv_channel_1.json').read_text())
        strongest=[v for v in value if v['kind']=='STRONGEST_LOCAL_CONSTANT']
        times=np.array([v['time_s'] for v in strongest])
        figure=Figure(figsize=(12,9),layout='constrained')
        axes=figure.subplots(3,1,sharex=True)
        axes[0].plot(times*1e9,[v['frequency_hz']/1e9 for v in strongest],color=COLORS[0],label='strongest')
        for proposal in [v for v in value if v['kind']=='EXISTING_TERMINAL_PROPOSAL']:
            axes[0].plot(times[proposal['frames']]*1e9,np.array(proposal['frequency_history_hz'])/1e9,
                         color='#888888',alpha=.35,linewidth=.8)
        axes[0].set(ylabel='Frequency (GHz)')
        axes[0].legend()
        for j,feature in enumerate(e.FEATURES):
            axes[1].plot(times*1e9,[v[feature] for v in strongest],color=COLORS[j+1],label=feature,linewidth=.9)
        axes[1].set(ylabel='Local strongest evidence',ylim=(0,1))
        axes[1].legend(ncol=4)
        axes[2].plot(times*1e9,[v['amplitude_rms_v'] for v in strongest],color=COLORS[1],label='analytic RMS')
        other=axes[2].twinx()
        other.plot(times*1e9,[v['spectral_support_db'] for v in strongest],color=COLORS[2],alpha=.7)
        other.set_ylabel('Peak/background (dB)',color=COLORS[2])
        axes[2].set(xlabel='Time (ns)',ylabel='Local analytic RMS (V)')
        figure.suptitle(f'ch3 / {profile}: behavioral diagnostic, physical correctness UNKNOWN\n'
            'Grey = saved alternatives; low-support valleys shown without threshold or new interval',fontsize=11)
        save(figure,output,label)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args().output.resolve()
    ranking(output)
    persistent_example(output)
    maps(output)
    identity(output)
    real_overlays(output)


if __name__=='__main__':
    main()
