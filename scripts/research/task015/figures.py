"""Publication-size figures from retained outputs; no new synthetic draws."""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import NullLocator

from dps_studio.research.task009_data import inventory, read_raw
from dps_studio.core.models import SignalRecord
from dps_studio.core.time_frequency import compute_stft

OUT=(Path(__file__).resolve().parents[3] / "artifacts/TASK-015")
FIG=OUT/'figures'
COLORS=['#0072B2','#777777','#E69F00','#009E73','#CC79A7']
MAPS=['M1_balanced','M2_task014_gui','M3_parameters','M4_specialized']
LABELS=['Balanced','TASK-014 GUI','Parameters','Specialized']
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
    'font.size':8,'axes.titlesize':9,'axes.labelsize':8,'legend.fontsize':7,
    'axes.spines.top':True,'axes.spines.right':True,'xtick.direction':'in','ytick.direction':'in',
    'xtick.top':True,'ytick.right':True,'axes.linewidth':.7,'svg.fonttype':'none','pdf.fonttype':42,
    'legend.frameon':False,'lines.linewidth':1.3,'savefig.facecolor':'white'})


def save(fig,name):
    for suffix in ('png','svg','pdf'):
        fig.savefig(FIG/f'{name}.{suffix}',dpi=300)
    plt.close(fig)


def panels(axes,titles):
    for i,(ax,title) in enumerate(zip(axes.flat,titles)):
        ax.set_title(f'{chr(97+i)}  {title}',loc='left',fontweight='bold',pad=8)


def case(family,index=5):
    return np.load(OUT/f'data/heldout/cases/heldout_{family}_{index:02d}_b0_m0.npz')


def main():
    FIG.mkdir(exist_ok=True)
    fam=pd.read_csv(OUT/'data/families.csv')
    gated=fam[fam.kind=='gated']
    summary=pd.read_csv(OUT/'data/summary.csv')
    fig,axes=plt.subplots(2,2,figsize=(7.15,5.1),layout='constrained')
    panels(axes,['Low tone beneath a stronger spur','Low-tone precision at equal coverage',
                 'Unobservable inputs: accepted output','Incorrect stationary label'])
    z=case('low_spur')
    t=z['time_s'][z['centers']]*1e9
    for method,label,color in [('M1_balanced','Balanced',COLORS[0]),('low_prior','Low prior (no accepted points)',COLORS[2]),
                                ('low_glrt','GLRT',COLORS[3])]:
        axes[0,0].plot(t,z[method+'__accepted']/1e6,'o-',ms=2,color=color,label=label)
    axes[0,0].plot(t,z['truth_hz'][z['centers']]/1e6,'k--',lw=.8,label='Synthetic target')
    axes[0,0].set(yscale='log',xlabel='Time (ns)',ylabel='Beat frequency (MHz)',ylim=(20,3000))
    axes[0,0].legend(loc='center right')
    subset=gated[(gated.family=='low_tone')&gated.method.isin(['stft_low','low_glrt'])].set_index('method')
    axes[0,1].bar([0,1],[subset.loc[k,'rmse_m_s'] for k in ['stft_low','low_glrt']],color=[COLORS[2],COLORS[3]],width=.55)
    axes[0,1].set(xticks=[0,1],xticklabels=['Band STFT','GLRT'],ylabel='Supported RMSE (m/s)')
    axes[0,1].text(.95,.95,'Both: 75% coverage\n16 held-out records',ha='right',va='top',transform=axes[0,1].transAxes)
    for j,method in enumerate(['M1_balanced','low_prior','low_glrt']):
        vals=[gated[(gated.family==f)&(gated.method==method)].iloc[0].coverage_pct for f in ['drift_spur','subcycle_ac']]
        axes[1,0].bar(np.arange(2)+(j-1)*.24,vals,width=.22,color=[COLORS[0],COLORS[2],COLORS[3]][j],label=['Balanced','Low prior','GLRT'][j])
    axes[1,0].set(xticks=[0,1],xticklabels=['Drift + spur','Sub-cycle + AC'],ylabel='Accepted output (%)',ylim=(0,115))
    axes[1,0].legend(loc='upper right')
    methods=['M1_balanced','low_prior','low_glrt']
    vals=[gated[(gated.family=='stationary_mislabel')&(gated.method==k)].iloc[0].coverage_pct for k in methods]
    axes[1,1].bar(range(3),vals,color=[COLORS[0],COLORS[2],COLORS[3]],width=.6)
    axes[1,1].set(xticks=range(3),xticklabels=['Balanced','Low prior','GLRT'],ylabel='Coverage (%)',ylim=(0,115))
    axes[1,1].text(.96,.94,'True beat: 1.8 GHz\nGLRT rejects the target',ha='right',va='top',transform=axes[1,1].transAxes)
    save(fig,'fig01_low_frequency')

    fig,axes=plt.subplots(2,2,figsize=(7.15,5.3),layout='constrained')
    panels(axes,['Missing-inclusive failure','Coverage and supported error',
                 'Operator boundary sensitivity','Pulse-width resolution on a 3.2 ns grid'])
    tab=summary[(summary.region=='all')&(summary.kind=='gated')].set_index('method')
    axes[0,0].bar(range(4),[tab.loc[m,'failure_pct'] for m in MAPS],color=COLORS[:4],width=.65)
    axes[0,0].set(xticks=range(4),xticklabels=LABELS,ylabel='Failure (%)',ylim=(0,100))
    for k in MAPS:
        row=tab.loc[k]
        i=MAPS.index(k)
        axes[0,1].scatter(row.coverage_pct,row.rmse_m_s,color=COLORS[i],s=35)
        axes[0,1].annotate(LABELS[i],(row.coverage_pct,row.rmse_m_s),xytext=(3,6),textcoords='offset points',fontsize=7)
    axes[0,1].set(xlabel='Coverage (%)',ylabel='Supported RMSE (m/s)',xlim=(35,100),ylim=(0,820))
    sens=pd.read_csv(OUT/'data/sensitivity_v02/metrics.csv')
    for i,k in enumerate(MAPS):
        part=sens[(sens.kind=='gated')&(sens.family=='onset_step')&~sens.mislabel&(sens.method==k)]
        grouped=part.groupby('boundary_ns').onset_error_ns.agg(lambda x:x.abs().mean())
        axes[1,0].plot(grouped.index,grouped.values,'o-',color=COLORS[i],label=LABELS[i],ms=3)
    axes[1,0].set(xlabel='Boundary error (ns)',ylabel='Onset MAE (ns)')
    axes[1,0].legend(loc='upper center',fontsize=6)
    axes[1,0].set_ylim(bottom=0)
    pulse=pd.read_csv(OUT/'data/resolution/metrics.csv')
    for k,label,color in [('M1_balanced','Balanced',COLORS[0]),('full_512','Short, full context',COLORS[2]),
                           ('clip_512','Short, clipped',COLORS[3]),('clip_2048','Long, clipped',COLORS[4])]:
        grouped=pulse[pulse.method==k].groupby('duration_ns').resolved.mean()*100
        axes[1,1].plot(grouped.index,grouped.values,'o-',label=label,color=color,ms=3)
    axes[1,1].set(xscale='log',xticks=[2,4,8,16,32],xticklabels=['2','4','8','16','32'],
                  xlabel='True pulse width (ns)',ylabel='Resolved records (%)',ylim=(-5,105))
    axes[1,1].legend(loc='lower right',fontsize=6)
    axes[1,1].xaxis.set_minor_locator(NullLocator())
    save(fig,'fig02_validation')

    fig,axes=plt.subplots(2,2,figsize=(7.15,5.1),layout='constrained')
    panels(axes,['Fixed clutter: conditional recovery','Drifting clutter: retained failure',
                 'Wrong branch and rejection','Target already in background prefix'])
    for ax,family in zip(axes[0],['weak_fixed','weak_drift']):
        z=case(family)
        t=z['time_s'][z['centers']]*1e9
        ax.plot(t,z['truth_hz'][z['centers']]/1e9,'k--',label='Synthetic target')
        for k,label,color in [('M1_balanced','Balanced',COLORS[0]),('clutter_varpro','Clutter VarPro',COLORS[3])]:
            ax.plot(t,z[k+'__accepted']/1e9,'o-',ms=2,label=label,color=color)
        ax.set(xlabel='Time (ns)',ylabel='Beat frequency (GHz)')
    axes[0,0].legend(fontsize=6)
    for i,family in enumerate(['weak_fixed','weak_drift','crossing']):
        r=gated[(gated.family==family)&(gated.method=='clutter_varpro')].iloc[0]
        axes[1,0].bar(i,r.wrong_branch_pct,color=COLORS[3],label='Wrong branch' if i==0 else None)
        axes[1,0].bar(i,r.branch_missing_pct,bottom=r.wrong_branch_pct,color='#BBBBBB',label='Missing' if i==0 else None)
    axes[1,0].set(xticks=range(3),xticklabels=['Fixed','Drifting','Crossing'],ylabel='Eligible frames (%)',ylim=(0,110))
    axes[1,0].legend(fontsize=6)
    names=['M1_balanced','background_stft','clutter_varpro']
    axes[1,1].bar(range(3),[gated[(gated.family=='prefix_target')&(gated.method==k)].iloc[0].coverage_pct for k in names],
                  color=[COLORS[0],COLORS[2],COLORS[3]])
    axes[1,1].set(xticks=range(3),xticklabels=['Balanced','Background\nSTFT','Clutter\nVarPro'],ylabel='Coverage (%)',ylim=(0,110))
    save(fig,'fig03_interference')

    real=pd.read_csv(OUT/'data/real_v02/diagnostics.csv')
    fig,axes=plt.subplots(1,2,figsize=(7.15,3.0),layout='constrained',gridspec_kw={'width_ratios':[1.25,1]})
    panels(np.array([axes]),['Measured voltage spectrum; identity unknown','All 17 streams: frequency agreement'])
    item=next(i for i in inventory() if i['kind']=='RAW' and i['local_path'].endswith('20260607.csv'))
    signal=read_raw(item)[0]
    stft=compute_stft(SignalRecord(signal.time_s,signal.voltage_v),window_length_samples=1024,
                     overlap_samples=896,nfft=4096,window_name='hann')
    z=np.load(OUT/'data/real_v02'/f'{signal.name}.npz')
    band=(stft.frequency_hz>=0)&(stft.frequency_hz<=3e9)
    power=abs(stft.spectrum[band])**2
    db=10*np.log10(np.maximum(power/max(float(power.max()),1e-30),1e-12))
    axes[0].pcolormesh(stft.time_s*1e6,stft.frequency_hz[band]/1e9,db,vmin=-60,vmax=0,cmap='Greys',shading='auto',rasterized=True)
    for k,label,color in [('M1_balanced','Balanced',COLORS[0]),('stft_long','Long STFT',COLORS[2]),('low_glrt','Low GLRT (hypothesis)',COLORS[3])]:
        axes[0].plot(z['time_s']*1e6,z[k+'__accepted']/1e9,'.',ms=2,color=color,label=label)
    axes[0].set(xlabel='Absolute time (µs)',ylabel='Beat frequency (GHz)',ylim=(0,3))
    axes[0].legend(loc='upper left',fontsize=6,facecolor='white',frameon=True,framealpha=.9)
    for j,(k,label) in enumerate([('stft_short','Short'),('stft_long','Long'),('low_glrt','Low GLRT'),('tone_refine','Tone'),('clutter_varpro','Clutter')]):
        part=real[real.method==k]
        cov=100*part.finite_n.sum()/part.centers.sum()
        diff=100*part.disagreement_100MHz_n.sum()/part.paired_n.sum()
        axes[1].scatter(cov,diff,color=[COLORS[0],COLORS[2],COLORS[3],COLORS[4],COLORS[1]][j],s=35,label=label)
    axes[1].set(xlabel='Finite output (%)',ylabel='Difference >100 MHz / paired (%)',xlim=(0,65),ylim=(-.4,7))
    axes[1].legend(loc='upper right')
    save(fig,'fig04_real_observations')


if __name__=='__main__':
    main()
