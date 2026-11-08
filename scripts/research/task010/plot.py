"""Publication figures from recorded measurements; no fitting or truth feedback."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from matplotlib.ticker import AutoMinorLocator

from scripts.research.task010.audit import OUT, sha, write_json
from scripts.research.task010.experiment import HOPS, VELOCITY, WINDOWS, Spec

COLORS = {512: "#0072B2", 768: "#56B4E9", 1024: "#009E73", 1536: "#CC79A7", 2048: "#D55E00"}
ADAPT = "#6A51A3"


def style() -> None:
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman"],
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "axes.linewidth": .7, "lines.linewidth": 1., "mathtext.fontset": "stix",
        "axes.spines.top": True, "axes.spines.right": True,
        "xtick.direction": "in", "ytick.direction": "in",
        "xtick.top": True, "ytick.right": True, "legend.frameon": False,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "savefig.facecolor": "white", "axes.unicode_minus": True})


def decorate(ax: Any, letter: str, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(f"{letter}   {title}", loc="left", pad=7)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if ax.get_xscale() == "linear":
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    if ax.get_yscale() == "linear":
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which="major", length=3, width=.7, direction="in", top=True, right=True)
    ax.tick_params(which="minor", length=1.8, width=.5, direction="in", top=True, right=True)


def save(fig: Any, output: Path, name: str, caption: str,
         sources: list[str], manifest: list[dict[str, Any]]) -> None:
    for ext in ("svg", "pdf", "png"):
        path = output / f"{name}.{ext}"
        if path.exists():
            raise FileExistsError(path)
        fig.savefig(path, dpi=600)
    with (output / f"{name}_caption_zh.md").open("x", encoding="utf-8") as stream:
        stream.write(caption + "\n")
    manifest.append(dict(id=name, backend="Matplotlib", width_mm=float(fig.get_figwidth()*25.4),
                         height_mm=float(fig.get_figheight()*25.4), dpi=600,
                         svg_text_editable=True, pdf_fonttype=42, sources=sources,
                         data_hashes={source: sha(output/source) for source in sources
                                      if (output/source).is_file()}))
    plt.close(fig)


def values(summary: Any, stage: str, name: str, region: str, state: str,
           grid: str = "common") -> Any:
    rows = summary[(summary.stage == stage) & (summary.name == name) &
                   (summary.region == region) & (summary.state == state) & (summary.grid == grid)]
    if len(rows) != 1:
        raise ValueError((stage, name, region, state, grid, len(rows)))
    return rows.iloc[0]


def trajectory(run: Path, stage: str, case: str, spec: Spec) -> dict[str, Any]:
    folder = run / "trajectories" / stage / case
    exact = folder / (spec.name + ".npz")
    stored = exact if exact.exists() else folder / (Spec(spec.window, 1).name + ".npz")
    with np.load(stored) as z:
        data = {key: z[key] for key in z.files}
    mask = (data["sample_indices"] - spec.window//2) % spec.hop == 0
    return {key: val[mask] for key, val in data.items()}


def make_matrices(summary: Any, output: Path, manifest: list[dict[str, Any]]) -> None:
    panels = [("fresh", "motion", "candidate", "rmse_pooled_m_s", 1., "Motion RMSE (m s$^{-1}$)"),
              ("fresh", "motion", "supported", "failure_macro", 100., "Motion failure (%)"),
              ("fresh", "motion", "supported", "coverage_macro", 100., "Motion coverage (%)"),
              ("phase_stress", "low", "candidate", "rmse_pooled_m_s", 1., "Low-speed RMSE (m s$^{-1}$)"),
              ("fresh", "fast", "candidate", "rmse_pooled_m_s", 1., "Fast-region RMSE (m s$^{-1}$)"),
              ("phase_stress", "low", "supported", "failure_macro", 100., "Low-speed failure (%)")]
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 4.55), layout="constrained")
    exported = []
    for pi, (ax, panel) in enumerate(zip(axes.flat, panels, strict=True)):
        stage, region, state, field, scale, title = panel
        matrix = np.array([[values(summary, stage, Spec(w, h).name, region, state)[field]*scale
                            for h in HOPS] for w in WINDOWS], dtype=float)
        im = ax.pcolormesh(np.arange(7)-.5, np.arange(6)-.5, matrix,
                          cmap="cividis", shading="flat", rasterized=False,
                          vmin=0 if scale == 100 else None, vmax=100 if scale == 100 else None)
        ax.set_ylim(4.5, -.5)
        ax.set_xticks(range(len(HOPS)), [str(h) for h in HOPS])
        ax.set_yticks(range(len(WINDOWS)), [str(w) for w in WINDOWS])
        ax.set_title(f"{chr(97+pi)}   {title}", loc="left", pad=6)
        ax.set_xlabel("Hop (samples)")
        ax.set_ylabel("Window (samples)")
        ax.tick_params(direction="in", top=True, right=True, length=2)
        for row in range(5):
            for col in range(6):
                norm = im.norm(matrix[row, col])
                ax.text(col, row, f"{matrix[row,col]:.1f}", ha="center", va="center", fontsize=6.3,
                        color="white" if norm < .48 else "black")
                exported.append(dict(panel=chr(97+pi), stage=stage, region=region, state=state,
                    window=WINDOWS[row], hop=HOPS[col], metric=field, value=float(matrix[row,col])))
        colorbar = fig.colorbar(im, ax=ax, shrink=.86, pad=.02)
        if colorbar.solids is not None:
            colorbar.solids.set_rasterized(False)
    pd.DataFrame(exported).to_csv(output/"source_data/matrix_values.csv", index=False, mode="x")
    save(fig, output, "Fig01_ParameterMatrix",
         "主矩阵。全部面板在共同原始样本中心评分，FFT=4096、50 MHz–6 GHz、无去直流。主分布96条，88条有运动真值；低速压力50条，d/f仅评价GT<200 m/s的中心，200 m/s档不进入此区域分母。RMSE仅在有限候选点计算；失败率把NaN和|速度误差|>77.5 m/s计入完整区域分母，覆盖率单列。失败/覆盖为逐波形宏平均；RMSE为pooled。相同行内数字随H不变是共同中心估计相同的实测结果，并非精度被四舍五入隐藏。", ["source_data/matrix_values.csv"], manifest)


def make_hop(summary: Any, data: Any, onset: Any, output: Path,
             manifest: list[dict[str, Any]]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.7), layout="constrained")
    export = []
    for width in (512, 2048):
        color = COLORS[width]
        common, native, count, corr1, corr128, time = [], [], [], [], [], []
        for hop in HOPS:
            name = Spec(width, hop).name
            common.append(values(summary, "fresh", name, "motion", "candidate").rmse_pooled_m_s)
            native.append(values(summary, "fresh", name, "motion", "candidate", "native").rmse_pooled_m_s)
            group = data[(data.stage == "fresh") & (data.family == "step") & (data.name == name)]
            count.append(group.frames.mean())
            corr1.append(group.lag1_residual_correlation.mean())
            corr128.append(group.lag_128samples_residual_correlation.mean())
            time.append(onset[(onset.stage == "fresh") & (onset.name == name) &
                              (onset.method == "spectral")].mean_abs_error_ns.iloc[0])
            export.append(dict(window=width, hop=hop, common_rmse=common[-1], native_rmse=native[-1],
                native_frames=count[-1], lag1_correlation=corr1[-1], fixed128_correlation=corr128[-1],
                spectral_onset_mae_ns=time[-1]))
        axes[0,0].plot(HOPS, common, "o-", color=color, label=f"W{width}, common")
        axes[0,0].plot(HOPS, native, "s--", color=color, mfc="white", label=f"W{width}, native")
        axes[0,1].plot(HOPS, count, "o-", color=color, label=f"W{width}")
        axes[1,0].plot(HOPS, corr1, "o-", color=color, label=f"W{width}, adjacent")
        axes[1,0].plot(HOPS, corr128, "s--", mfc="white", color=color, label=f"W{width}, 128 samples")
        axes[1,1].plot(HOPS, time, "o-", color=color, label=f"W{width}, spectral")
    raw = onset[(onset.stage == "fresh") & (onset.name == Spec(512,128).name) &
                (onset.method == "raw_energy")].mean_abs_error_ns.iloc[0]
    axes[1,1].axhline(raw, color=".35", ls=":", label="Raw energy (independent)")
    for ax in axes.flat:
        ax.set_xscale("log", base=2)
        ax.set_xticks([1,8,16,32,64,128], ["1","8","16","32","64","128"])
        ax.legend(loc="best", handlelength=1.8, fontsize=6.3)
    axes[0,1].set_yscale("log")
    axes[0,0].legend(loc="center",bbox_to_anchor=(.5,.39),ncol=2,fontsize=6.1)
    axes[1,0].set_ylim(-.05, 1.04)
    decorate(axes[0,0], "a", "Same-center versus native-grid RMSE", "Hop (samples)", "RMSE (m s$^{-1}$)")
    decorate(axes[0,1], "b", "Output density", "Hop (samples)", "Frames per waveform")
    decorate(axes[1,0], "c", "Residual correlation on stationary plateaus", "Hop (samples)", "Pearson correlation")
    decorate(axes[1,1], "d", "Onset error includes misses separately", "Hop (samples)", "Detected-event MAE (ns)")
    pd.DataFrame(export).to_csv(output/"source_data/hop_effects.csv", index=False, mode="x")
    save(fig, output, "Fig02_HopAndInformation",
         "步长控制。(a)共同中心和原生中心的有限候选RMSE，分母不同必须区分。(b)输出帧数。(c)固定阶跃族8条独立波形、起跳60 ns后稳态段的残差相关系数均值；实线为相邻输出，虚线为相隔128原始样本，不能把高相关帧当独立重复。(d)88条运动波形中检测成功者的起跳绝对误差均值；漏检数和纯噪声假事件在onset.csv，原电压能量检测不依赖W/H。", ["source_data/hop_effects.csv", "source_data/onset.csv"], manifest)


def make_examples(run: Path, output: Path, manifest: list[dict[str, Any]]) -> None:
    families = [("step", "Sudden onset"), ("low_ramp", "Low-speed ramp"),
                ("fast_accel", "Rapid acceleration"), ("fast_decel", "Rapid deceleration"),
                ("two_shock", "Two shocks"), ("weak_chirp", "Weak chirp (-5 dB)")]
    fig, axes = plt.subplots(3, 2, figsize=(7.2, 6.2), layout="constrained")
    sources = []
    for pi, (ax, (family, title)) in enumerate(zip(axes.flat, families, strict=True)):
        case = f"fresh_{family}_00"
        with np.load(run/"datasets/fresh"/(case+".npz")) as z:
            time, truth = z["time_s"], z["truth_hz"]*VELOCITY
        ax.plot(time*1e9, truth, color=".15", lw=1.2, label="Ground truth", zorder=4)
        visible_values = [truth[(time*1e9 >= 35) & (time*1e9 <= 310)]]
        for width in (512,2048):
            trace = trajectory(run,"fresh",case,Spec(width,32))
            ax.plot(trace["time_s"]*1e9, trace["frequency_hz"]*VELOCITY,
                    color=COLORS[width], label=f"Strict W{width}, H32", alpha=.9)
            visible = (trace["time_s"]*1e9 >= 35) & (trace["time_s"]*1e9 <= 310)
            visible_values.append(trace["frequency_hz"][visible]*VELOCITY)
        if family == "low_ramp":
            spec = Spec(2048,32,minimum_hz=5e6,maximum_hz=8e9,demean=True,label="wide_demean")
            trace = trajectory(run,"fresh",case,spec)
            ax.plot(trace["time_s"]*1e9,trace["frequency_hz"]*VELOCITY,color=ADAPT,ls="--",
                    label="Wide + DC, W2048")
            visible = (trace["time_s"]*1e9 >= 35) & (trace["time_s"]*1e9 <= 310)
            visible_values.append(trace["frequency_hz"][visible]*VELOCITY)
        ax.set_xlim(35,310)
        if family == "low_ramp":
            ax.set_ylim(-10,350)
        elif family in ("step","weak_chirp","two_shock"):
            ax.set_ylim(0,1700)
        else:
            ax.set_ylim(0,2050)
        finite_values = np.concatenate(visible_values)
        finite_values = finite_values[np.isfinite(finite_values)]
        lower, upper = ax.get_ylim()
        ax.set_ylim(min(lower, float(finite_values.min())-10),
                    max(upper, float(finite_values.max())*1.04))
        decorate(ax,chr(97+pi),title,"Time (ns)","Apparent velocity (m s$^{-1}$)")
        if family == "low_ramp":
            zoom = ax.inset_axes([.38, .24, .57, .36])
            zoom.plot(time*1e9, truth, color=".15", lw=.9)
            for width in (512,2048):
                item=trajectory(run,"fresh",case,Spec(width,32))
                zoom.plot(item["time_s"]*1e9,item["frequency_hz"]*VELOCITY,
                          color=COLORS[width],lw=.8)
            item=trajectory(run,"fresh",case,Spec(2048,32,minimum_hz=5e6,maximum_hz=8e9,
                                                 demean=True,label="wide_demean"))
            zoom.plot(item["time_s"]*1e9,item["frequency_hz"]*VELOCITY,color=ADAPT,ls="--",lw=.8)
            zoom.set_xlim(60,200)
            zoom.set_ylim(0,240)
            zoom.set_title("Motion-region zoom",fontsize=6,pad=2)
            zoom.tick_params(labelsize=5.5,direction="in",top=True,right=True,length=2)
        if pi in (0,1):
            ax.legend(loc="upper right",fontsize=6.1)
        sources.append(f"source_data/{case}_ground_truth.csv")
        pd.DataFrame(dict(time_ns=time*1e9,truth_velocity_m_s=truth)).to_csv(
            output/sources[-1],index=False,mode="x")
    save(fig,output,"Fig03_FixedSyntheticExamples",
         "六类预先固定的第0条代表波形，展示候选轨迹及GT；不是最佳案例筛选。W512/W2048均使用H32、FFT4096和原频带，候选NaN保留缺口。低速面板额外显示宽频带去均值控制，收益不能归给单独窗长或重叠。曲线连线只辅助读图，不对原电压重采样、平滑或补NaN。候选图必须与全体失败/覆盖及逐案例表配合阅读。",sources+["source_data/synthetic_metrics.csv"],manifest)


def make_transient(run: Path, transient: Path, output: Path,
                   manifest: list[dict[str, Any]]) -> None:
    curves=pd.read_csv(transient/"spectral_mixing_curves.csv")
    metrics=pd.read_csv(transient/"spectral_mixing_metrics.csv")
    fig,axes=plt.subplots(2,2,figsize=(7.2,4.7),layout="constrained")
    with np.load(run/"datasets/fresh/fresh_two_shock_00.npz") as z:
        axes[0,0].plot(z["time_s"]*1e9,z["truth_hz"]*VELOCITY,color=".15",lw=1.4,label="GT")
    for width in (512,2048):
        for hop,ls in ((128,"--"),(1,"-")):
            tr=trajectory(run,"fresh","fresh_two_shock_00",Spec(width,hop))
            axes[0,0].plot(tr["time_s"]*1e9,tr["frequency_hz"]*VELOCITY,
                color=COLORS[width],ls=ls,label=f"W{width}, H{hop}",alpha=.85)
            c=curves[(curves.window==width)&(curves.hop==hop)]
            axes[0,1].plot(c.time_ns,c.high_component_power_fraction,color=COLORS[width],
                          ls=ls,label=f"W{width}, H{hop}")
    axes[0,0].set_xlim(80,130)
    axes[0,0].set_ylim(100,1350)
    axes[0,0].legend(loc="upper left",fontsize=6)
    axes[0,1].set_xlim(80,130)
    axes[0,1].set_ylim(-.03,1.03)
    for level in (.1,.9):
        axes[0,1].axhline(level,color=".6",lw=.5,ls=":")
    for hop,marker in ((128,"s"),(32,"^"),(1,"o")):
        means=metrics[metrics.hop==hop].groupby("window").mixing_10_90_width_ns.agg(["mean","std"])
        axes[1,0].errorbar(means.index,means["mean"],yerr=means["std"],marker=marker,
            capsize=2,label=f"H{hop}",ls="--" if hop!=1 else "-",color={128:".45",32:"#009E73",1:ADAPT}[hop])
    shock=pd.read_csv(run/"tables/shock_response.csv")
    for width in (512,2048):
        group=shock[(shock.stage=="fresh")&(shock.label=="strict")&(shock.window==width)]
        grouped=group.groupby("hop").candidate_t50_error_ns.agg(["mean","std"])
        axes[1,1].errorbar(grouped.index,grouped["mean"],yerr=grouped["std"],marker="o",
                            color=COLORS[width],capsize=2,label=f"W{width}")
    axes[1,1].set_xscale("log",base=2)
    axes[1,1].set_xticks([1,8,16,32,64,128],["1","8","16","32","64","128"])
    axes[1,1].axhline(0,color=".5",lw=.6)
    axes[1,0].legend()
    axes[1,1].legend()
    decorate(axes[0,0],"a","Strongest-peak branch switching","Time (ns)","Velocity (m s$^{-1}$)")
    decorate(axes[0,1],"b","Window mixing persists at H1","Time (ns)","High-component power fraction")
    decorate(axes[1,0],"c","Spectral mixing width, mean ± SD","Window (samples)","10–90% width (ns)")
    decorate(axes[1,1],"d","Second-shock 50% timing, mean ± SD","Hop (samples)","Timing error (ns)")
    for name in ("spectral_mixing_curves.csv","spectral_mixing_metrics.csv"):
        with (output/"source_data"/name).open("xb") as stream:
            stream.write((transient/name).read_bytes())
    save(fig,output,"Fig04_TransientAndWindowMixing",
         "双冲击瞬态。(a)固定第0条的最强峰轨迹可能突然换支，不能由其外观推断窗口混合已经消失。(b,c)在8条波形上，用生成器标记的两个频率作局部Hann傅里叶投影，计算高频功率占两频率总功率的比例；这是使用GT的外部诊断，绝不反馈估计器，也不是未知频率解混的成功率。(c,d)误差棒为8条独立波形的标准差，点为均值。H1缩小输出量化间隔，不改变W决定的混合支撑。(d)第二跳速度50%第一次越过误差；非单调和缺失在原表保留。",["source_data/spectral_mixing_curves.csv","source_data/spectral_mixing_metrics.csv","source_data/shock_response.csv"],manifest)


def make_low_adaptive(data: Any, family: Any, output: Path,
                      manifest: list[dict[str, Any]]) -> None:
    fig,axes=plt.subplots(2,2,figsize=(7.2,4.8),layout="constrained")
    names=[("strict_w512_h32_n4096","Strict W512",COLORS[512],"--"),
           ("strict_w2048_h32_n4096","Strict W2048",COLORS[2048],"--"),
           ("wide_demean_w512_h32_n4096","Wide + DC W512",COLORS[512],"-"),
           ("wide_demean_w2048_h32_n4096","Wide + DC W2048",COLORS[2048],"-")]
    export=[]
    for name,label,color,ls in names:
        group=data[(data.stage=="phase_stress")&(data.name==name)].copy()
        group["nominal_velocity_m_s"]=[(15,30,50,100,200)[int(v.rsplit("_",1)[1])%5] for v in group.case_id]
        x,rmse,coverage=[],[],[]
        for speed,g in group.groupby("nominal_velocity_m_s"):
            finite=g.common_candidate_motion_finite_n.sum()
            pooled=np.sqrt(g.common_candidate_motion_sse_m2_s2.sum()/finite) if finite else np.nan
            cov=g.common_supported_motion_coverage.mean()*100
            x.append(speed)
            rmse.append(pooled)
            coverage.append(cov)
            export.append(dict(name=name,speed_m_s=speed,candidate_rmse_m_s=pooled,
                               supported_coverage_percent=cov,waveforms=len(g)))
        axes[0,0].plot(x,rmse,marker="o",color=color,ls=ls,label=label)
        axes[0,1].plot(x,coverage,marker="o",color=color,ls=ls,label=label)
    axes[0,0].set_yscale("log")
    axes[0,0].legend(fontsize=6.1)
    axes[0,1].set_ylim(-3,103)
    for ax in axes[0]:
        ax.set_xticks([15,30,50,100,200])
    selected=[("wide_demean_w512_h32_n4096","W512",COLORS[512]),
              ("wide_demean_w2048_h32_n4096","W2048",COLORS[2048]),
              ("adaptive512_2048_w2048_h32_n4096","Adaptive",ADAPT)]
    families=["step","low_ramp","fast_accel","fast_decel","two_shock","weak_chirp"]
    labels=["Step","Low ramp","Accel.","Decel.","Two shocks","Weak"]
    for name,label,color in selected:
        rows=[]
        for f in families:
            g=family[(family.family==f)&(family.name==name)&(family.state=="supported")&
                     (family.region=="motion")&(family.grid=="common")]
            rows.append(g.iloc[0])
        axes[1,0].plot(range(6),[r.failure_macro*100 for r in rows],"o-",color=color,label=label)
        axes[1,1].plot(range(6),[r.coverage_macro*100 for r in rows],"o-",color=color,label=label)
    for ax in axes[1]:
        ax.set_xticks(range(6),labels,rotation=25,ha="right")
        ax.set_ylim(-3,103)
        ax.legend(fontsize=6.3)
    decorate(axes[0,0],"a","Low-speed phase stress","Nominal velocity (m s$^{-1}$)","Finite-candidate RMSE (m s$^{-1}$)")
    decorate(axes[0,1],"b","Missingness accompanies low-speed error","Nominal velocity (m s$^{-1}$)","Supported coverage (%)")
    decorate(axes[1,0],"c","Registered two-scale selector","Waveform family","Failure including NaN (%)")
    decorate(axes[1,1],"d","Matched wide-band/DC controls","Waveform family","Supported coverage (%)")
    pd.DataFrame(export).to_csv(output/"source_data/phase_stress_by_speed.csv",index=False,mode="x")
    save(fig,output,"Fig05_LowSpeedAndAdaptive",
         "低速与双尺度选择。(a,b)各速度10条独立波形，初相/SNR/AC截止沿用联合压力分布，不能解释为每个交互条件均有10次重复。候选RMSE和支持覆盖分开呈现，失效并非删除。原频带下15/30 m/s低于50 MHz门槛；宽带+去直流的变化不能归于窗长或H。(c,d)每族8条，在相同H32、宽频带和去均值条件下比较W512、W2048及预注册的直接双尺度选择。无混合、平滑、补NaN；仍是Research启发式，不是Production准入证据。",["source_data/phase_stress_by_speed.csv","source_data/family_summary.csv"],manifest)


def make_cost(cost: Any, output: Path, manifest: list[dict[str, Any]]) -> None:
    fig,axes=plt.subplots(2,2,figsize=(7.2,4.7),layout="constrained")
    subset=cost[(cost.dataset=="raw80000")&(cost.backend=="research_chunked_fft_peak_support")]
    for width in WINDOWS:
        g=subset[subset.window==width].sort_values("hop")
        axes[0,0].plot(g.hop,g.median_runtime_s*1000,"o-",color=COLORS[width],label=f"W{width}")
        axes[0,1].plot(g.hop,g.allocated_peak_mib,"o-",color=COLORS[width],label=f"W{width}")
        axes[1,0].plot(g.hop,g.dense_complex_mib,"o-",color=COLORS[width],label=f"W{width}")
    for ax in (axes[0,0],axes[0,1],axes[1,0]):
        ax.set_xscale("log",base=2)
        ax.set_xticks([1,8,16,32,64,128],["1","8","16","32","64","128"])
    axes[0,0].set_yscale("log")
    axes[1,0].set_yscale("log")
    axes[0,0].legend(ncol=2,fontsize=6.2)
    names=[Spec(512,128).name,Spec(512,1).name,Spec(2048,1).name]
    for backend,label,color,shift in [("core_dense_transform_only","Core dense, FFT only",".5",-.16),
        ("research_chunked_fft_peak_support","Research chunks + support",ADAPT,.16)]:
        vals=[]
        for name in names:
            r=cost[(cost.dataset=="synthetic12800")&(cost.backend==backend)&(cost.name==name)]
            vals.append(r.allocated_peak_mib.iloc[0])
        axes[1,1].bar(np.arange(3)+shift,vals,width=.3,label=label,color=color)
    axes[1,1].set_xticks(range(3),["512 / 128","512 / 1","2048 / 1"])
    axes[1,1].legend(fontsize=6.1)
    decorate(axes[0,0],"a","Independent serial execution: 80,000 samples","Hop (samples)","Runtime (ms), median of 3")
    decorate(axes[0,1],"b","Measured per-operation tracked allocation","Hop (samples)","Allocation peak (MiB)")
    decorate(axes[1,0],"c","Full complex128 spectrum storage only","Hop (samples)","Spectrum size (MiB)")
    decorate(axes[1,1],"d","Measured allocation: 12,800 samples","Window / hop (samples)","Allocation peak (MiB)")
    save(fig,output,"Fig06_EngineeringCost",
         "工程成本。每配置独立子进程，单线程、串行，计时3次取中位数，导入/读盘/保存不计；先做一次独立内存探针，其耗时不进入计时。(a,b)同一80,000点真实记录；研究实现分批256帧，含FFT、细化与支持验证。(b,d)tracemalloc实测跟踪分配峰值，不保证覆盖所有本机分配；绝对进程峰值工作集另在cost_summary.csv。(c)保存全部complex128谱矩阵的精确字节数，属于存储需求计算，不是实测峰值总内存。(d)两实现算子不同，不能用其耗时宣布算法加速；这里只展示实测分配代价。",["source_data/cost_summary.csv"],manifest)


def make_real(run: Path, output: Path, manifest: list[dict[str, Any]]) -> None:
    real=pd.read_csv(run/"tables/real_metrics.csv")
    streams=pd.read_csv(run/"tables/raw_streams.csv")
    configs=[Spec(512,128).name,Spec(768,128).name,Spec(512,32).name,Spec(1024,32).name,
             Spec(2048,128).name,Spec(2048,32).name,Spec(2048,1).name,
             "wide_demean_w512_h32_n4096","wide_demean_w2048_h32_n4096",
             "adaptive512_2048_w2048_h32_n4096"]
    labels=["512/128","768/128","512/32","1024/32","2048/128","2048/32","2048/1",
            "Wide512","Wide2048","Adaptive"]
    matrix=np.array([[real[(real.case_id==case)&(real.name==name)].native_supported_fraction.iloc[0]*100
                       for name in configs] for case in streams.case_id])
    fig=plt.figure(figsize=(7.2,6.4),layout="constrained")
    grid=fig.add_gridspec(2,2,height_ratios=[1.55,1.])
    ax=fig.add_subplot(grid[0,:])
    im=ax.pcolormesh(np.arange(11)-.5,np.arange(len(streams)+1)-.5,matrix,
                     cmap="cividis",vmin=0,vmax=100,shading="flat",rasterized=False)
    ax.set_ylim(len(streams)-.5,-.5)
    ax.set_yticks(range(len(streams)),[f"{i:02d}  {c.split('_',1)[1]}" for i,c in enumerate(streams.case_id)])
    ax.set_xticks(range(10),labels,rotation=30,ha="right")
    ax.set_title("a   All 17 raw streams: heuristic support, no accuracy ground truth",loc="left",pad=8)
    ax.set_xlabel("Window / hop or explicit research control")
    ax.tick_params(length=2,direction="in",top=True,right=True)
    colorbar=fig.colorbar(im,ax=ax,label="Native-grid supported fraction (%)",shrink=.9,pad=.02)
    if colorbar.solids is not None:
        colorbar.solids.set_rasterized(False)
    for i in range(len(streams)):
        for j in range(10):
            ax.text(j,i,f"{matrix[i,j]:.0f}",ha="center",va="center",fontsize=5.5,
                    color="white" if matrix[i,j]<48 else "black")
    representatives=[streams.case_id.iloc[0],next(c for c in streams.case_id if "_ch3_" in c)]
    for pi,case in enumerate(representatives):
        axis=fig.add_subplot(grid[1,pi])
        for name,color,label in [(Spec(512,128).name,COLORS[512],"Strict 512/128"),
                                (Spec(2048,32).name,COLORS[2048],"Strict 2048/32"),
                                ("adaptive512_2048_w2048_h32_n4096",ADAPT,"Adaptive")]:
            r=real[(real.case_id==case)&(real.name==name)].iloc[0]
            with np.load(run/r.trajectory) as z:
                raw_start = z["time_s"][0]-z["sample_indices"][0]/r.sample_rate_hz
                t=(z["time_s"]-raw_start)*1e9
                axis.plot(t,z["apparent_velocity_m_s"],lw=.65,color=color,label=label)
        axis.legend(fontsize=5.9,loc="best")
        decorate(axis,chr(98+pi),case.split("_",1)[1],"Time from record start (ns)",
                 "Equivalent apparent velocity (m s$^{-1}$)")
    pd.DataFrame(matrix,index=streams.case_id,columns=configs).to_csv(
        output/"source_data/real_support_matrix.csv",mode="x")
    save(fig,output,"Fig07_AllRealStreams",
         "全部13个原始文件、17个电压流，包括data/raw内全部10个真正原始文件及TASK-009的3个补充归档。(a)原生网格启发式支持比例，不是准确率，不同W丢失的边界支撑不能由此隐藏；总输出帧数和窗口时长另表。(b,c)预先选定首记录与已知问题ch3记录的有限候选假设曲线，仅用于运行/支路诊断。所有速度使用未经核验的1550 nm等效表观速度，corrected velocity始终独立为NaN。没有真实GT，不能作真实精度排名。",["source_data/real_support_matrix.csv","source_data/real_metrics.csv","source_data/raw_streams.csv"],manifest)


def native_spec(output: Path, summary: Any, run: Path, transient: Path) -> None:
    root=output/"origin_source"
    root.mkdir()
    figures=[]
    # Origin companion projects use exact numeric source points and native line
    # objects. Complex matrices/interval logic remain in the Matplotlib figures.
    specs: list[dict[str, Any]]=[]
    panels: list[dict[str, Any]]=[]
    for state,field,ylabel in [("candidate","rmse_pooled_m_s","Velocity RMSE (m/s)"),
                               ("supported","failure_macro","Failure including NaN (%)")]:
        series: list[dict[str, Any]]=[]
        for region,color,label in [("motion",COLORS[512],"All motion"),
                                   ("low",COLORS[2048],"Low speed"),
                                   ("fast",ADAPT,"Fast regions")]:
            y=[float(values(summary,"fresh",Spec(w,32).name,region,state)[field]) *
               (100 if field=="failure_macro" else 1) for w in WINDOWS]
            series.append(dict(x=list(WINDOWS),y=y,color=color,label=label,width=1.3,
                               symbols=True,dash=False,kind="line",data_csv="summary.csv"))
        maximum=max(v for s in series for v in s["y"])
        panels.append(dict(rect=[12+len(panels)*48,16,35,63],series=series,xlabel="Window (samples)",
            ylabel=ylabel,xlim=[400,2200],ylim=[0,maximum*1.18],xlog=False,ylog=False,
            legend_position=[3,5]))
    specs.append(dict(id="Origin01_WindowTradeoff",width_mm=183,height_mm=95,panels=panels))
    curves=pd.read_csv(transient/"spectral_mixing_curves.csv")
    series=[]
    for width in (512,2048):
        c=curves[(curves.window==width)&(curves.hop==1)]
        series.append(dict(x=c.time_ns.tolist(),y=c.high_component_power_fraction.tolist(),
            color=COLORS[width],label=f"W{width}, H1",width=1.3,symbols=False,dash=False,
            kind="line",data_csv="spectral_mixing_curves.csv"))
    specs.append(dict(id="Origin02_WindowMixing",width_mm=183,height_mm=100,panels=[dict(
        rect=[14,15,78,70],series=series,xlabel="Time (ns)",ylabel="High component power fraction",
        xlim=[80,130],ylim=[0,1.05],xlog=False,ylog=False,legend_position=[5,5])]))
    for spec in specs:
        directory=root/spec["id"]
        directory.mkdir()
        write_json(directory/"figure.json",spec)
        figures.append(spec["id"])
    write_json(root/"manifest.json",dict(figures=figures,source="TASK010 recorded tables",
                                       companion_native_lines=True))


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--summary",type=Path,required=True)
    parser.add_argument("--transient",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if output.exists() or not output.is_relative_to(OUT):
        parser.error("Use a new TASK-010 output directory")
    output.mkdir(parents=True,exist_ok=False)
    (output/"source_data").mkdir()
    for source in [args.summary/name for name in ("summary.csv","family_summary.csv","onset.csv","cost_summary.csv")]+[
            args.run/"tables"/name for name in ("synthetic_metrics.csv","shock_response.csv","real_metrics.csv","raw_streams.csv")]:
        with (output/"source_data"/source.name).open("xb") as stream:
            stream.write(source.read_bytes())
    style()
    summary=pd.read_csv(args.summary/"summary.csv")
    data=pd.read_csv(args.run/"tables/synthetic_metrics.csv")
    onset=pd.read_csv(args.summary/"onset.csv")
    family=pd.read_csv(args.summary/"family_summary.csv")
    cost=pd.read_csv(args.summary/"cost_summary.csv")
    manifest: list[dict[str,Any]]=[]
    make_matrices(summary,output,manifest)
    make_hop(summary,data,onset,output,manifest)
    make_examples(args.run,output,manifest)
    make_transient(args.run,args.transient,output,manifest)
    make_low_adaptive(data,family,output,manifest)
    make_cost(cost,output,manifest)
    make_real(args.run,output,manifest)
    native_spec(output,summary,args.run,args.transient)
    write_json(output/"figure_manifest.json",manifest)
    print(json.dumps(dict(figures=len(manifest),output=str(output))))


if __name__ == "__main__":
    main()
