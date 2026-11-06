"""Write Chinese Research conclusions directly from the locked experiment tables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from artifacts.research_clean_task10.audit import OUT, ROOT
from artifacts.research_clean_task10.experiment import Spec
from artifacts.research_clean_task10.plot import values


def table(columns: list[str], rows: list[list[Any]]) -> str:
    return "\n".join(["| " + " | ".join(columns) + " |",
                       "| " + " | ".join("---" for _ in columns) + " |"] +
                      ["| " + " | ".join(str(v) for v in row) + " |" for row in rows])


def number(value: Any, precision: int = 2) -> str:
    return f"{value:.{precision}f}" if value is not None and np.isfinite(value) else "缺失"


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("summary","run","cost","figures","transient"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--output",type=Path,default=OUT)
    args=parser.parse_args()
    for name in ("summary", "run", "cost", "figures", "transient"):
        setattr(args, name, getattr(args, name).resolve())
    output=args.output.resolve()
    if not output.is_relative_to(OUT):
        parser.error("Reports must stay in TASK-010")
    output.mkdir(parents=True,exist_ok=True)
    summary=pd.read_csv(args.summary/"summary.csv")
    frozen=pd.read_csv(args.summary/"frozen_summary.csv")
    paired=pd.read_csv(args.summary/"paired_bootstrap.csv")
    onset=pd.read_csv(args.summary/"onset.csv")
    family=pd.read_csv(args.summary/"family_summary.csv")
    data=pd.read_csv(args.run/"tables/synthetic_metrics.csv")
    costs=pd.read_csv(args.summary/"cost_summary.csv")
    mixing=pd.read_csv(args.transient/"spectral_mixing_metrics.csv")
    corr=pd.read_csv(args.summary/"correlation.csv")
    real=pd.read_csv(args.run/"tables/real_metrics.csv")
    names=[Spec(512,128).name,Spec(768,128).name,Spec(1024,32).name,Spec(1536,32).name,
           Spec(2048,32).name,"wide_demean_w512_h32_n4096","wide_demean_w2048_h32_n4096",
           "adaptive512_2048_w2048_h32_n4096"]
    main_rows=[]
    key=[]
    for name in names:
        c=values(summary,"fresh",name,"motion","candidate")
        s=values(summary,"fresh",name,"motion","supported")
        main_rows.append([name,number(c.rmse_pooled_m_s),number(s.rmse_pooled_m_s),
                          number(s.coverage_macro*100),number(s.failure_macro*100)])
        key.append(dict(stage="fresh",name=name,candidate_rmse_m_s=c.rmse_pooled_m_s,
                        supported_rmse_m_s=s.rmse_pooled_m_s,
                        coverage_macro=s.coverage_macro,failure_macro=s.failure_macro))
    low_rows=[]
    for name in names:
        c=values(summary,"phase_stress",name,"motion","candidate")
        s=values(summary,"phase_stress",name,"motion","supported")
        low_rows.append([name,number(c.rmse_pooled_m_s),number(s.rmse_pooled_m_s),
                         number(s.coverage_macro*100),number(s.failure_macro*100)])
        key.append(dict(stage="phase_stress",name=name,candidate_rmse_m_s=c.rmse_pooled_m_s,
                        supported_rmse_m_s=s.rmse_pooled_m_s,
                        coverage_macro=s.coverage_macro,failure_macro=s.failure_macro))
    tables=output/"tables"
    tables.mkdir(exist_ok=True)
    key_path=tables/"key_results.csv"
    if key_path.exists():
        pd.testing.assert_frame_equal(pd.read_csv(key_path),pd.DataFrame(key),check_dtype=False)
    else:
        pd.DataFrame(key).to_csv(key_path,index=False,mode="x",encoding="utf-8-sig")
    delta_rows=[]
    for stage in ("fresh","phase_stress","confirmation"):
        for row in paired[(paired.stage==stage)&(paired.state=="supported")&
                           (paired.region=="motion")&(paired.outcome=="failure_fraction")].itertuples():
            delta_rows.append([stage,row.baseline,row.candidate,number(row.mean_delta*100),
                               f"[{row.ci95_lower*100:.2f}, {row.ci95_upper*100:.2f}]",row.paired_waveforms])
    costs_raw=costs[(costs.dataset=="raw80000")&
                    (costs.backend=="research_chunked_fft_peak_support")]
    cost_rows=[]
    for name in [Spec(512,128).name,Spec(768,64).name,Spec(1024,64).name,
                 Spec(1024,32).name,Spec(2048,128).name,Spec(2048,32).name,Spec(2048,1).name]:
        r=costs_raw[costs_raw.name==name].iloc[0]
        cost_rows.append([name,number(r.median_runtime_s*1000),number(r.allocated_peak_mib),
                          number(r.process_peak_rss_mib),number(r.dense_complex_mib)])
    ratio=costs_raw[costs_raw.name==Spec(2048,1).name].iloc[0].median_runtime_s / \
          costs_raw[costs_raw.name==Spec(2048,128).name].iloc[0].median_runtime_s
    onset_rows=[]
    for name in [Spec(w,h).name for w in (512,2048) for h in (128,32,1)]:
        r=onset[(onset.stage=="fresh")&(onset.name==name)&(onset.method=="spectral")].iloc[0]
        onset_rows.append([name,number(r.mean_abs_error_ns,3),int(r.missed_n),int(r.false_event_n)])
    raw_event=onset[(onset.stage=="fresh")&(onset.method=="raw_energy")].iloc[0]
    mix_rows=[]
    for width in (512,768,1024,1536,2048):
        cells=[]
        for hop in (128,32,1):
            group=mixing[(mixing.window==width)&(mixing.hop==hop)].mixing_10_90_width_ns
            cells.append(f"{group.mean():.3f} ± {group.std():.3f}")
        mix_rows.append([width,*cells])
    corr_rows=[]
    for width in (512,2048):
        for hop in (128,32,1):
            g=corr[(corr.window==width)&(corr.hop==hop)]
            corr_rows.append([width,hop,number(g.lag1_residual_correlation.mean(),6),
                              number(g.lag_128samples_residual_correlation.mean(),6)])
    frozen_rows=[]
    for method in ("stft512","stft768","legacy_m0_512","legacy_m0_768","gated_stft256",
                   "gated_stft512","dechirp","varpro","clutter_varpro","acmd","matrix_pencil",
                   "time_domain","baseband","stft512_wide"):
        r=values(frozen,"fresh","frozen::"+method,"motion","supported")
        frozen_rows.append([method,number(r.rmse_pooled_m_s),number(r.coverage_macro*100),
                            number(r.failure_macro*100)])
    confirm_rows=[]
    for width in (512,1024,2048):
        r=values(summary,"confirmation",Spec(width,32).name,"motion","supported")
        confirm_rows.append([width,number(r.rmse_pooled_m_s),number(r.coverage_macro*100),
                             number(r.failure_macro*100)])
    family_rows=[]
    for f in ("step","low_ramp","fast_accel","fast_decel","two_shock","weak_chirp",
              "dropout","stationary_spur","two_component","phase_jump","colored_noise"):
        row=[f]
        for width in (512,1024,2048):
            g=family[(family.family==f)&(family.name==Spec(width,32).name)&
                (family.grid=="common")&(family.state=="supported")&(family.region=="motion")].iloc[0]
            row.append(f"{g.failure_macro*100:.2f}")
        family_rows.append(row)
    fft_rows=[]
    for width in (512,2048):
        for nfft in (2048,4096,8192):
            name=Spec(width,32).name if nfft==4096 else Spec(width,32,nfft,label="fft_control").name
            r=values(summary,"phase_stress",name,"motion","supported")
            fft_rows.append([width,nfft,number(40e9/nfft/1e6,3),number(r.rmse_pooled_m_s,3),
                             number(r.coverage_macro*100),number(r.failure_macro*100)])
    comparison=f'''# TASK-010｜长窗口与高重叠 STFT 比较

日期：2026-11-05。分支：`codex/research_2/global-path-ridge-v2`。本研究已实际运行，未修改 Production，也不进行 promotion、commit 或 push。

## 结论与进入 PDV Studio 的判断

**值得增加带适用条件的可选窗口/步长预设；不支持把“2048点＋H1”作为通用升级替换现有默认算法。** 固定窗口时，高重叠在相同中心的候选频率、支持频率、RMSE、覆盖和失败数完全相同；它增加输出密度，可能减小阈值越过的采样量化，但本轮并未改善整体起跳误差。长窗在平稳低速、弱谱峰条件下有实际收益，在快变和复杂支路中存在代价。是否更好必须同时检查有限点RMSE、覆盖、含缺失失败及门控定义。

建议保留原512/128、768/128基准；通用可选探索用768或1024点、H64或H32。需要快速变化时优先512点、H64/H32；平稳低速研究可用1536/2048点、H128/H64，并显式选择频带/DC处理及质量门槛。H8/H1限于小ROI的离线诊断，不作为常规默认。以上是参数工程建议，不是新的 Production 准入结论。

## 范围、评分与公平性

完整5×6矩阵：W=512/768/1024/1536/2048，H=128/64/32/16/8/1，周期Hann、FFT4096、50 MHz–6 GHz、无去直流、无边界扩展或末端补帧。146条既有波形含96条主分布及50条初相低速压力；另24条新种子确认波形运行预注册3×2矩阵。共6714条合成配置结果。146条既有波形曾用于TASK-008，不能再称从未见过的盲测；本轮先冻结协议再运行，不根据结果调参。

所有估计器只接收时间和电压。主网格为原始样本索引1024+128k≤N−1024，12,800点记录共有85个中心；长窗边界外的时刻不计入共同评分，原生帧数、支撑范围另报。88条主运动波形共有6512个共同运动目标点；纯噪声不计算运动RMSE。消光仍在运动分母内。矩阵以H1准确结果作整数子集视图，绝不插值；视图没有独立耗时，成本另用逐配置独立执行的3次串行测量。

候选RMSE只统计有限候选；支持RMSE只统计有限支持。失败率的完整目标分母包括NaN或|误差|>77.5 m/s；另保存38.75/155 m/s阈值的失败数。77.5 m/s对15 m/s目标较宽，不能据此称极低速已稳定准确恢复，须看误差幅度及严格阈值。覆盖/失败表为逐波形宏平均，RMSE为全部有限点的pooled值，彼此不是同一统计量。置信区间按配对波形bootstrap4000次，探索性、未做多重比较校正；重叠帧不是独立重复。

新支持门控为本窗谱峰对比≥10 dB，以及统一256样本sin/cos/DC的R²≥0.2和条件数≤10⁵，原能量事件后截掉事件前验证片段。它不是经过物理标定的置信度，也不同于TASK-008统一512去直流对比的门控。候选与原严格STFT逐点核验，**新支持列不能冒充旧门控的严格复现**。真实记录都没有速度GT或核验波长，只输出1550 nm假设下等效表观速度；校正速度独立为NaN。

## 主分布结果

{table(["配置", "候选RMSE m/s", "支持RMSE m/s", "支持覆盖 %", "含缺失失败 %"],main_rows)}

严格频带下，从512加长到1024降低了全分母失败，但2048没有继续改善，且1024的候选RMSE高于512，不能据支持后的数字宣称整体候选精度提高。Hann短窗的DC主瓣可进入原频带，长窗缩窄DC泄漏也是收益来源，不能仅归于单音频率分辨能力。支持RMSE的变化还受接受点集合影响，不能把某配置拒绝困难点后的较小RMSE直接解释为整体精度更好。去直流宽频带短窗与长窗必须作为匹配控制比较；预注册双尺度选择在主分布未超过该短窗控制，负结果保留。

{table(["族（每族8条）", "W512失败 %", "W1024失败 %", "W2048失败 %"],family_rows)}

## 配对区间与新种子确认

下表差值为候选配置减基准，单位为百分点，负值表示含缺失失败减少。原频带512→1024的收益不等于高重叠收益，因为512/H32相对512/H128的差值严格为0。宽带DC策略在主分布的长窗/自适应差值是负结果。

{table(["分布", "基准", "配置", "失败差 pp", "配对95%区间 pp", "波形n"],delta_rows)}

新种子确认包含6族×4条，不包括额外杂散/双分量等压力族；没有对这些结果再调参。不同覆盖集合的条件RMSE仍须谨慎。

{table(["W（H32）", "支持RMSE m/s", "覆盖 %", "含缺失失败 %"],confirm_rows)}

## 高重叠、起跳和伪重复

730个既有波形×窗口组合的6种H共同评分完全一致；292条原严格512/768候选轨迹与冻结结果的NaN模式一致，最大差小于0.001 Hz。原生网格的RMSE可能随H变化，因为评价时刻、分母和缺失位置变化；这不构成同一时刻估计改善。相邻误差相关显著增加，固定128原始样本间隔的相关基本保持。

{table(["W", "H", "相邻残差相关", "相隔128样本相关"],corr_rows)}

相关性取固定阶跃族8条、起跳60 ns后稳态段的波形内Pearson相关，再跨波形平均，不将它换算为经过校准的有效样本量。

{table(["配置", "检测成功者MAE ns", "漏检/88", "假事件/8纯噪声"],onset_rows)}

同一W的功率阈值由H128参考前10%帧固定，不随H重新估计。H1更早看到窗前缘能量，会加重某些提前越过，平均绝对误差并未随帧间隔下降。独立原电压能量检测MAE={raw_event.mean_abs_error_ns:.3f} ns，漏检{int(raw_event.missed_n)}/88；它对W/H完全不变，且假设首段安静，不能归为高重叠收益，也不能仅据成功者误差宣布优越。

## 长窗瞬态混合与后续策略

{table(["W", "H128 混合宽度 ns", "H32 混合宽度 ns", "H1 混合宽度 ns"],mix_rows)}

数值为8条独立双冲击波形的双频功率占比10–90%过渡宽度均值±标准差。在同一个长窗内加密H不改变混合核。最强峰可能突然换支，外观陡峭不代表该窗的时间支撑变短。本诊断在生成器已知240/1150 m/s对应频率查询傅里叶投影，使用GT仅作外部解释，不是盲解混性能。

预注册的512/2048直接选择会在短窗快速变化或原能量事件邻域使用短窗，其余用长窗；不平滑、不混合、不填NaN，来源写入逐点flag。它可避免部分长窗瞬态污染，但在主分布相对同处理短窗失败率更高。既有Dechirp/VarPro结果继续保留，说明下游模型研究必须单独评估；本轮不能声称所有联合时频/相位算法都不可能受益于密集STFT，更不能把高重叠本身视为消除了模糊。

## 低速、去直流与FFT网格

{table(["配置", "候选RMSE m/s", "支持RMSE m/s", "支持覆盖 %", "含缺失失败 %"],low_rows)}

50条压力波形按速度15/30/50/100/200 m/s各10条，SNR和AC截止沿既有联合压力分配，不是每个交互单元10次独立重复。原50 MHz下限对应38.75 m/s，15/30 m/s在频带外；长窗无法修复频带排除。扩展到5 MHz与显式局部去均值明显改变结果，所以不能把整个收益归于W/H。仅扩频带不去直流也保留，弱低频镜像/DC与不足周期可辨识性没有被软件参数普遍解决。

{table(["W / H32", "NFFT", "FFT网格 MHz", "支持RMSE m/s", "覆盖 %", "含缺失失败 %"],fft_rows)}

改变NFFT影响网格、三点拟合偏差与频带边界失败/接受点集合，结果并不单调。更低的有限点RMSE可能伴随更多缺失；零填充不增加观测时长或新物理信息。

## 工程成本与合理折中

{table(["配置（80,000点）", "耗时中位数 ms", "跟踪分配峰值 MiB", "绝对进程峰值 MiB", "完整复谱存储 MiB"],cost_rows)}

同一Windows工作站、单线程、配置间独立子进程、串行，3次计时不含导入/读盘/保存，另有一次不计时的tracemalloc探针。W2048/H1相对同窗H128约耗时{ratio:.1f}倍。峰值工作集为含解释器/导入的进程生命周期绝对值，不能与每次运算的跟踪分配峰值相减后冒充精确内存增量；本机FFT原生分配可能不全受tracemalloc跟踪。最后一列仅为完整complex128谱矩阵的精确存储需求，绝非实测总峰值。分批实现限制瞬时谱矩阵，但仍需执行更多FFT，不能消除H1的算力成本。

研究实现计时包含FFT、细化与支持检查；core_dense对照只计算变换，不能据不同算子的耗时宣称算法加速。80,000点实测记录为80 GS/s；合成主分布为40 GS/s，速度效果不能自动外推到任意采样率/采集链。

## 原14方法及真实记录

下表读取原冻结轨迹，在本轮共同中心重新评分；并保留原始统计表，未重写既有曲线或结论。原支持门控与新门控不同，本表用于避免选择弱基准，不能把横向差值直接归为单一窗长效应。

{table(["冻结方法", "支持RMSE m/s", "支持覆盖 %", "含缺失失败 %"],frozen_rows)}

真实原始文件13个、17个电压流，每流10种代表配置/策略，共170条，无运行异常。data/raw的全部10个真正原始文件全部包含，另3个来自TASK-009原样归档；图像/占位/result不作输入。所有记录都保存候选、支持、quality flags、频率、假设表观速度及独立NaN校正速度。真实图只评价运行完成、支持、密度和资源，**没有真实准确率、速度RMSE或物理起跳误差排名**。ch3等问题记录也保留。

## 时频量、机制及适用边界

令窗长L、步长H、采样率f_s，窗口时长T=L/f_s，帧间隔Δt=H/f_s，FFT网格Δf_grid=f_s/NFFT。周期Hann的等效噪声带宽ENBW=1.5 f_s/L，主瓣第一零点偏移±2 f_s/L。它们是不同量，不能直接互换为参数估计误差或两信号可分辨能力。40 GS/s时，W512/1024/2048分别为12.8/25.6/51.2 ns；H128/32/1分别为3.2/0.8/0.025 ns；固定4096的网格始终为9.765625 MHz。80 GS/s时各时长减半、频率网格加倍。同一H对应的重叠率1−H/L随L变化，研究以W/H而非单一重叠百分比归因。

物理解释：平稳单音加白噪声时，更长Hann降低等效噪声带宽，增加可用周期，可能提高单频参数估计；这是模型解释，实测收益以上述GT结果为依据。对频率随时间变化的信号，窗内扫频范围约|df/dt|T；PDV表观关系df/dt=2a/λ。40×10⁹ m/s²加速在12.8/51.2 ns内扫过约512/2048 m/s，长窗会混合明显不同的状态。但理想无限线性chirp的中心估计不必总偏，转折、饱和、实值镜像、AC传递和多支路使实际失败依信号而变。

本轮只验证实值单通道峰值及已定义的启发式选择，没有校准仪器光学传递函数、参考频移、目标身份、正负速度或LiF。次周期低速下初相/DC/振幅耦合及AC信息损失是可辨识性问题，不能靠输出帧密度消除。

数值API语义核验依据：[SciPy原始STFT实现](https://github.com/scipy/scipy/blob/main/scipy/signal/_spectral_py.py)与[官方信号处理教程源文档](https://github.com/scipy/scipy/blob/main/doc/source/tutorial/signal.rst)。实验环境、参数及运行本地版本独立记录，不把在线main分支当作本机源码版本。

## 验证与下一步

相关pytest、Ruff、mypy、分母/真值隔离/图件校验和raw/Git/Production SHA审计见[VALIDATION.md](VALIDATION.md)。不通过修改旧基准、旧结果、原始数据或生产默认值制造通过。可选预设进入Research界面前应明确窗口时长、帧间隔和内存预估；后续需带参考真值的实测验证、物理采集链标定和多事件检测，另设新数据验证下游chirp/相位模型。没有足够证据把H1或预注册双尺度选择提升为Production默认。
'''
    readme='''# TASK-010｜长窗口与高重叠 STFT 性能研究

2026-11-05，状态：实验完成，Research only。**推荐可选768/1024点＋H64/H32；保留原基准，不把2048＋H1作为通用默认。** 固定窗口下加密步长没有改善共同中心的频率/速度估计，只增加密度和相关性。长窗对平稳低速有条件收益，瞬态代价不能靠高重叠消除。

- [完整比较、结论与适用边界](COMPARISON.md)
- [论文图件、中文图注、PNG预览](FIGURE_INDEX.md)
- [注册协议](PROTOCOL.md)与[配置](config.json)
- [关键结果表](tables/key_results.csv)、[完整汇总](summary/v02/summary.csv)、[配对区间](summary/v02/paired_bootstrap.csv)、[原14方法重评分](summary/v02/frozen_summary.csv)
- [验证记录](VALIDATION.md)与[边界核验](checks/boundary_verification.json)

170条GT波形（96原主分布、50低速初相压力、24新种子确认），6714条合成配置结果；13真实原始文件、17电压流、170条实测配置；原14方法2044条冻结轨迹保留并在共同中心重评分。没有因NaN、消光、坏记录或负结果排除案例。原生与共同网格分开评价，支持RMSE/覆盖/含缺失失败同时报告。真实记录没有GT，1550 nm速度是假设等效表观速度，校正速度独立为NaN。

关键负结果：H1没有改善整体谱阈值起跳MAE；W512由3.512 ns变为4.042 ns，W2048由10.317 ns变为11.319 ns（成功检测者均值，漏检另报）。H1下W512/W2048的双频混合10–90%宽度约3.416/13.572 ns。主分布中，匹配宽带去均值W2048及双尺度选择相对W512的含缺失失败分别增加约3.22/0.91个百分点。

本地完整数据与源码以本目录为准。逐案例表、数据及轨迹在`runs/v01/`，完整合成指标为`runs/v01/tables/synthetic_metrics.csv`，实测指标为`runs/v01/tables/real_metrics.csv`。H>1主矩阵通过`trajectory`列指向同窗H1结果，按`(sample_indices−W/2) % H == 0`还原准确视图，不需插值；视图耗时留空。成本在`cost/v01/measurements.csv`独立计时，不能使用复用耗时。

## 复现

使用现有环境，不安装新依赖；PowerShell7，仓库根目录运行。所有输出目录必须不存在，重复运行请换名字。原基准仍可由TASK-009入口单独重放。

```powershell
$task10Py = 'D:\\miniconda3\\envs\\dps-studio\\python.exe'
$env:PYTHONPATH = "$PWD\\src;$PWD"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
& $task10Py -B -m artifacts.research_clean_task10.run --output artifacts/research_clean_task10/runs/new_run
& $task10Py -B -m artifacts.research_clean_task10.benchmark --output artifacts/research_clean_task10/cost/new_cost
& $task10Py -B -m artifacts.research_clean_task10.transient --output artifacts/research_clean_task10/transient/new_transient
& $task10Py -B -m artifacts.research_clean_task10.summarize --run artifacts/research_clean_task10/runs/new_run --cost artifacts/research_clean_task10/cost/new_cost --output artifacts/research_clean_task10/summary/new_summary
& $task10Py -B -m artifacts.research_clean_task10.plot --run artifacts/research_clean_task10/runs/new_run --summary artifacts/research_clean_task10/summary/new_summary --transient artifacts/research_clean_task10/transient/new_transient --output artifacts/research_clean_task10/figures/new_figures
```

`plot.py`同时生成Origin原生伴随工程的数据规范；`scripts/render_origin.ps1`使用私有隐藏COM、ASCII导入与逐点读回，`publish_native.py`嵌入PDF字体并导出SVG/600dpi PNG。复杂矩阵用Matplotlib矢量单元格，全部主图保留可编辑SVG文字；两张Origin伴随图保留可编辑OPJU，SVG字形为路径。PDF先解析为JSON，再渲染与人工视觉检查。

## 文件、边界与云端

源码都在`artifacts/research_clean_task10/`，新增测试在`tests/unit/test_research_task010.py`；不改`src`、生产配置、旧Research实现或TASK-008/009结果。全部raw前后SHA-256、Git HEAD/index及Production代码/raw审计另附。未commit/push/promotion。

G盘路径在开始时确认可访问。手机成果副本位于`G:\\我的云端硬盘\\codex\\pdv_studio_research\\research_clean_task10`；复制关键文档、图件和表格，保留本地完整NPZ与源码。实际复制清单及逐文件SHA回读见`checks/cloud_sync.json`。不移动或删除本地文件，不覆盖云端不同版本。

`summary/v01`是成本测量前的完整速度汇总；`summary/v02`为加入独立成本表的最终汇总。失败和已弃用渲染版本若存在均保留，以FIGURE_INDEX列出的成品为准。
'''
    figure_manifest=json.loads((args.figures/"figure_manifest.json").read_text(encoding="utf-8"))
    figure_lines=["# TASK-010 图件索引", "", "主图统一Times New Roman、四边框、向内刻度，183 mm宽；PDF/SVG矢量，PNG600 dpi。SVG文字可编辑。图注逐一说明n、分母、门控和真实GT限制。", ""]
    for figure in figure_manifest:
        identifier=figure["id"]
        base=args.figures.relative_to(OUT).as_posix()+"/"+identifier
        figure_lines += [f"## {identifier}", "",
            f"[PNG]({base}.png) · [PDF]({base}.pdf) · [SVG]({base}.svg) · [中文图注]({base}_caption_zh.md)", "",
            f"![{identifier}]({base}.png)", ""]
    figure_lines += ["## Origin可编辑伴随工程", "",
        "两张原生线图保留数据工作簿、曲线和文字，ASCII导入后逐点读回核验。复杂矩阵/统计主图以Matplotlib成品为准，不伪造OPJU。", ""]
    for identifier in ("Origin01_WindowTradeoff","Origin02_WindowMixing"):
        base=f"origin/v01/{identifier}/{identifier}"
        figure_lines += [f"- {identifier}：[OPJU]({base}.opju) · [PDF]({base}_embedded.pdf) · [PNG]({base}.png) · [SVG]({base}.svg)"]
    failed_rows=[]
    for f in ("weak_chirp","dropout","stationary_spur","two_component","phase_jump"):
        for width in (512,2048):
            g=family[(family.family==f)&(family.name==Spec(width,32).name)&
                     (family.grid=="common")&(family.region=="motion")&(family.state=="supported")].iloc[0]
            failed_rows.append([f,width,number(g.rmse_pooled_m_s),number(g.coverage_macro*100),
                                number(g.failure_macro*100)])
    failures="# TASK-010 失败与负结果\n\n没有运行异常不等于算法成功。下列是完整预注册压力族（每族8条）的支持结果，NaN包含在失败率分母。\n\n"+table(
        ["族","W / H32","有限支持RMSE m/s","覆盖 %","含缺失失败 %"],failed_rows)+"\n\n完整事后最差案例表为`summary/v02/worst_cases_posthoc.csv`，明确标为事后诊断，不能替换预先固定第0条代表图。低速、弱信号、消光、静止杂散、近邻双分量和目标身份歧义均未普遍解决。H1起跳MAE未获益、W2048主分布不如W1024、宽带去均值长窗/自适应不如匹配短窗，都作为负结果保留。\n"
    methods="""# TASK-010 指标与源码入口

`config.json`和`PROTOCOL.md`为注册参数与方法。`experiment.py`不接收真值；`run.py`负责外部评分、原始数据核验、数据/轨迹保存、原冻结结果重评分。`summarize.py`按波形计算宏平均与配对bootstrap。`benchmark.py`逐参数独立子进程串行计时3次并探测Windows工作集及tracemalloc峰值。`transient.py`只做GT标记频率上的外部窗口混合诊断，不是重建算法。`plot.py`只读结果画图，`qa_pdf.py`先解析PDF到JSON再渲染。

候选、支持和校正速度分别存储；校正速度全NaN。原生帧数为floor((N−L)/H)+1，共同中心按整数索引选择，边界不补。全运动失败包含消光与缺失。静止/纯噪声不填零、不加入运动RMSE；假事件与假支持单列。低速RMSE、快变、起跳后40ns和全运动分别评价。主阈值77.5m/s，另有38.75/155m/s敏感性失败数。

源数据与物理原始数据全部保留。完整数值表在runs/v01/tables，逐案例表在runs/v01/cases。每个主矩阵H>1是所指H1轨迹的整数子集；读取它的runtime_s空值表示复用，不代表零耗时。成本看cost/v01和summary/v02/cost_summary.csv。原14方法保留frozen_tables原表及frozen_common_rescored的共同中心评分；新支持门控与旧门控不同，禁止把两者差异归为窗长。

未改变Production、core、默认参数或LiF公式；没有promotion、commit或push。任何将研究预设正式加入GUI/Production的实现是独立后续任务。
"""
    for name,text in (("README.md",readme),("COMPARISON.md",comparison),("FIGURE_INDEX.md","\n".join(figure_lines)),
                      ("FAILURES.md",failures),("METHODS.md",methods)):
        with (output/name).open("x",encoding="utf-8") as stream:
            stream.write(text)
    print(json.dumps(dict(reports=5,real_records=len(real),synthetic_records=len(data),root=str(ROOT))))


if __name__=="__main__":
    main()
