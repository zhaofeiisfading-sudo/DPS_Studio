"""Chinese audit report and explicitly requested lightweight Obsidian task note."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.freeze_task026 import ROOT, digest, load_json, write_json
from scripts.summarize_task026 import macro, save


def table(frame: Any, columns: list[str]) -> str:
    lines = ['| '+' | '.join(columns)+' |', '| '+' | '.join('---' for _ in columns)+' |']
    for _, row in frame.iterrows():
        values = []
        for column in columns:
            value = row[column]
            values.append(f'{value:.5g}' if isinstance(value, (float, np.floating)) else str(value))
        lines.append('| '+' | '.join(values)+' |')
    return '\n'.join(lines)


def report(output: Path) -> None:
    output = output.resolve()
    all_rows = pd.read_csv(output/'candidate_recall.csv')
    held = all_rows[(all_rows.split == 'HELD_OUT') & (all_rows.region == 'ALL')]
    single = held[held.dataset == 'SINGLE']
    core = held[held.dataset == 'CORE']
    two = held[held.dataset == 'TWO']
    low_rmse = {m: macro(single[(single.method == m) & (single.snr_db <= 0)], 'rmse_hz')
                for m in ('R0', 'R1', 'R2', 'R3')}
    best_low = min(low_rmse, key=lambda m: low_rmse[m])
    close = all_rows[(all_rows.dataset == 'TWO') & (all_rows.split == 'HELD_OUT') &
                     (all_rows.region == 'CLOSE')]
    close_rates = {m: macro(close[close.method == m], 'resolution_rate')
                   for m in ('R0', 'R1', 'R2', 'R3')}
    best_close = max(close_rates, key=lambda m: close_rates[m])
    gate = load_json(output/'representation_gate.json')
    validation = load_json(output/'validation_summary.json')
    boundary = load_json(output/'boundary_verification.json')
    registration = load_json(output/'seed_registration.json')
    rows = []
    for family in ('stationary', 'fast_chirp', 'amplitude_ramp', 'nonlinear_chirp',
                   'temporary_fading'):
        for method in ('R0', 'R1', 'R2', 'R3'):
            selected = single[(single.family == family) & (single.method == method) &
                              (single.snr_db == 30)]
            rows.append(dict(family=family, method=method,
                RMSE_MHz=macro(selected, 'rmse_hz')/1e6, bias_MHz=macro(selected, 'bias_hz')/1e6,
                mean_absolute_waveform_bias_MHz=float(selected.groupby('waveform').bias_hz.mean()
                                                       .abs().mean()/1e6),
                discrete_RMSE_MHz=macro(selected, 'discrete_rmse_hz')/1e6,
                discrete_bias_MHz=macro(selected, 'discrete_bias_hz')/1e6,
                p95_MHz=macro(selected, 'p95_absolute_error_hz')/1e6,
                failure_fraction=macro(selected, 'failure_rate')))
    high_snr = pd.DataFrame(rows)
    save(high_snr, output/'high_snr_chirp_bias_summary.csv')
    gate_rows = []
    for method, result in gate.items():
        gate_rows.append(dict(method=method, verdict=result['verdict'],
            overall_RMSE_gain_percent=100*result['overall_rmse_improvement'],
            fast_RMSE_gain_percent=100*result['fast_rmse_improvement'],
            best_resolution_gain_pp=100*max(result['resolution_gains'].values()),
            runtime_ratio=result['isolated_runtime_ratio'], **result['checks']))
    gates = pd.DataFrame(gate_rows)
    core_rows = []
    for method in ('R0', 'R1', 'R2', 'R3'):
        selected = core[core.method == method]
        core_rows.append(dict(method=method, recall_percent=100*macro(selected, 'candidate_recall'),
            hits=int(selected.candidate_hits.sum()), truth_frames=int(selected.truth_frames.sum()),
            strongest_RMSE_MHz=macro(selected, 'rmse_hz')/1e6,
            nearest_RMSE_MHz=macro(selected, 'nearest_candidate_rmse_hz')/1e6,
            resolution_percent=100*macro(selected, 'resolution_rate'),
            resolved_frames=int(selected.resolved_frames.sum()),
            two_component_frames=int(selected.two_component_frames.sum()),
            truth_near_rank=macro(selected, 'truth_near_rank'),
            candidate_count=macro(selected, 'candidate_multiplicity')))
    core_table = pd.DataFrame(core_rows)
    snr_rows = []
    for snr in (-20, -10, 0, 10, 30):
        for method in ('R0', 'R1', 'R2', 'R3'):
            selected = single[(single.method == method) & (single.snr_db == snr)]
            snr_rows.append(dict(SNR_dB=snr, method=method, RMSE_MHz=macro(selected, 'rmse_hz')/1e6,
                failure_percent=100*macro(selected, 'failure_rate'),
                recall_percent=100*macro(selected, 'candidate_recall'),
                false_candidate_percent=100*macro(selected, 'false_candidate_rate')))
    snr_table = pd.DataFrame(snr_rows)
    save(snr_table, output/'snr_summary.csv')
    evidence = pd.read_csv(output/'denoising_matched_conditions.csv')
    fit = pd.read_csv(output/'local_chirp_fit_diagnostics.csv')
    fit_summary = fit[fit.snr_db.isin((-20, 30))].groupby(['snr_db', 'family'])[
        ['chirp_rate_rmse_hz_per_s', 'weighted_residual_fraction', 'bank_boundary_fraction']
    ].mean().reset_index()
    key = ['family', 'profile', 'carrier_hz', 'chirp_hz_per_s', 'amplitude_v']
    matched = evidence.groupby(key).matched_low_fail_high_success.all()
    denoise = bool(matched.any())
    assert not any(v['verdict'] == 'SUPPORTED' for v in gate.values())
    # User's scientific taxonomy distinguishes partial precision benefit from
    # the stricter preregistered quantitative gate. Never change that gate file.
    chirp_interpretation = ('MIXED' if gate['R3']['overall_rmse_improvement'] > 0 and
        macro(two[two.method == 'R3'], 'resolution_rate') <= macro(
            two[two.method == 'R0'], 'resolution_rate') else gate['R3']['verdict'])
    verdicts = dict(current_stft_adequacy='MIXED', reassignment=gate['R1']['verdict'],
        sst_equivalent=gate['R2']['verdict'], local_chirp_estimator=chirp_interpretation,
        low_snr_bottleneck='MIXED', two_component_bottleneck='MIXED',
        candidate_framework='KEEP', waveform_denoising='YES' if denoise else 'NOT YET')
    write_json(output/'verdicts.json', verdicts)
    actual_two = []
    for (family, method), group in two.groupby(['family', 'method']):
        actual_two.append(dict(family=family, method=method,
            resolution_percent=100*macro(group, 'resolution_rate'),
            recall_percent=100*macro(group, 'candidate_recall')))
    two_table = pd.DataFrame(actual_two)
    baseline = load_json(output/'boundary_before.json')
    cal = sum(r['split'] == 'CALIBRATION' for r in registration)
    body = f'''# TASK-026 原始波形到频率估计的表示层基准审计

## 结论

**没有方法通过完整 REPRESENTATION_GATE；保留当前 STFT Candidate frontend 和 Candidate + trajectory 架构。**
R3 在高 SNR 的快 chirp、幅度斜坡和暂时衰落中有明确局部精度收益，但收益不足以支持直接替换。
R1/R2 的本次具体实现未建立整体优势。Phase D、真实数据和 ch3 新评价均未执行。
后续独立 Waveform Denoising Safety Audit：**{verdicts['waveform_denoising']}**；本任务没有实施降噪。

| 审计项 | 科学解释 Verdict |
|---|---|
| Current STFT adequacy | {verdicts['current_stft_adequacy']} |
| Reassignment R1 | {verdicts['reassignment']} |
| SST/equivalent R2 | {verdicts['sst_equivalent']} |
| Local chirp estimator R3 | {verdicts['local_chirp_estimator']} |
| Low-SNR bottleneck | MIXED（噪声主导的大误差 + 方法差异） |
| Two-component bottleneck | MIXED（冻结提取限制 + 信号重叠/噪声 + 表示差异） |
| Candidate framework | KEEP |
| Need for waveform denoising | {verdicts['waveform_denoising']} |

按任务“频率精度改善、但双分量不改善”的解释分类，R3 为 **MIXED**。
另一个独立标签是预注册的定量 REPRESENTATION_GATE：R3 的 6.383% 整体/17.135% fast-chirp
改善未达10%/20%，因此该 gate 仍为 **NOT SUPPORTED**。这不是修改门限或重新判为可启用；
representation_gate.json 保持原计算结果，三个方法都没有进入 Phase D。

## 冻结与事实来源

Research branch=`{baseline['Research']['git']['branch --show-current']}`，HEAD=`{baseline['Research']['git']['rev-parse HEAD']}`。
Production/main HEAD=`{baseline['Production']['git']['rev-parse HEAD']}`。
开始时 Research 已有 5215 个 tracked 删除，Production 已有 349 个 tracked 删除，主要为旧测试临时文件。
这些是继承状态；本任务没有恢复、删除或改写它们。TASK-025 日志的旧 HEAD/clean 状态已过时。
本报告按当前源码/git/tests > artifact > Obsidian；TASK-024 对应 task023h 的 20260913T132656Z，
TASK-025 对应 20260914T100937Z。旧数据全部 LEGACY_DIAGNOSTIC，未混入本次样本。

预注册共 {len(registration)} 个波形：128 core + 765 SINGLE + 1890 TWO；{cal} calibration、
{len(registration)-cal} held-out，两个 profile 共 {2*len(registration)} streams。
core 调用原 generate_case，仅改 seed/ID/split；受控扫描单独统计。
controlled 用已知解析相位积分；core 保留原左端点离散相位积分及原 truth 定义。
快变频下由这种定义/离散化引入的采样级差异不得全部归因于表示算法；未为新方法修正 core truth。
controlled 每格 3 个随机相位/噪声实现，其中 1 calibration、2 held-out；这是稀疏重复的受控实验，
不是现实数据分布发生率估计。profile 与 frame 不是独立统计样本。
协议、参数、seed 和 estimator/evaluator hash 在 held-out 之前冻结。

## 方法与公平比较边界

R0 完全调用原 Hann STFT、Top-20 和三点 log-magnitude 精修。
R1 是时间与频率重分配的能量栅格；R2 是仅频率能量压缩，**不是可逆 complex SST**。
这次 R2 的结论只约束该等价重分配实现，不排除严谨 SST/CWT 的未来独立研究。
R3 在原窗口内最大化局部二次相位模板投影，c 从 -2e17 到 2e17 Hz/s，步长 1e16 Hz/s。
输出 f_est、chirp_rate_est、频谱 evidence、最强分量加权残差和 bank-boundary flag。
没有 truth 初始化、后续轨迹信息、残差减分量或原波形重构。
三点精修用于 bank-envelope 峰频率；chirp rate 保持离散网格，半格 5e15 Hz/s 是量化尺度，
**不是误差置信区间**。weighted SSE/energy 衡量局部拟合残差，不代表多分量物理模型成立。

内部 f 用 Hz、c 用 Hz/s、t 用 s、V 用 V。40 GHz 下窗口 19.2/12.8 ns，frame spacing 均为 3.2 ns，
FFT bin spacing 9.765625 MHz；1/T=52.083/78.125 MHz。frame spacing 不等于时间分辨率，
FFT spacing 不等于真实频率分辨率，补零不增加信息，精修不自动消除模型 bias。
基础 PDV 映射仍是 v_app=λ0 f_b/2，λ0=1550 nm；本任务没有生成新速度或校正输出。

**冻结候选提取本身施加 2/T 的峰间距抑制：104.167/156.25 MHz。**
所有方法同样受到该限制。低于它的分辨失败不能单独归因于物理不可辨识；本实验是“固定提取器条件下的表示”审计。
R1 的 time deposition 还可能汇集邻窗，最大原始支持约达两倍源窗；其收益不能被解释为完全等支持长度的纯频率优势。
重分配采用最近栅格能量投放，不平滑；有限频率栅格也限制 delta-like 峰定位。
每方法每 stream 的 retained-energy 比例保留在 CSV，边界/数值 guard 丢弃的表示能量未伪称守恒。
raw waveform 和采样时刻全程不变；没有过滤、插值、重采样、相位修复或 denoising。

## 评价定义

主频误差使用最强候选与目标 truth；不以最近 truth 的候选代替 estimator 输出。
Candidate Recall 仍为 200 MHz 容差，并另外报告 truth-near rank、nearest-candidate error 和候选数量。
nearest-candidate error 是 evaluator 的乐观诊断，不能声称实际自动选中。
双分量要求不同候选分别匹配两个真实存在分量，容差 min(50 MHz, separation/4)，一一分配。
重合频率计 UNRESOLVED；一个峰不能匹配两次。该定义检验两个频率，不能证明物理目标身份可识别。
原 generator 的 nuisance_hz 含 off-time 潜在值；本 evaluator 按原振幅规则限定实际存在性。

下表以 waveform-macro 为主：先合并同波形 profile，再平均波形；同时保存 pooled 分子分母。
RMSE 是每波形/profile 条件 RMSE 的平均，p95 是每波形/profile p95 的平均，不是全帧 pooled p95。
NaN 作为 failure/recall miss，不能从 coverage 分母删除；有限输出只是未校准频率假设，
valid-estimate fraction 不等于可靠检测率。没有训练 noise-support 阈值。

## Phase A：30 dB 高信息条件下的 bias audit

四方法均通过预注册 calibration sanity check：stationary RMSE≤5 MHz、medium-chirp RMSE≤20 MHz、
有效估计比例≥99%。具体数值见 phase_a_sanity.json；通过 sanity 不等于通过 representation gate。

{table(high_snr, ['family', 'method', 'RMSE_MHz', 'bias_MHz', 'mean_absolute_waveform_bias_MHz', 'discrete_RMSE_MHz', 'discrete_bias_MHz'])}

恒幅、对称局部线性 chirp 的展宽不必产生大系统偏差，不能从谱更宽直接推出 bias。
本次高 SNR 的 R0 fast-chirp signed bias 远小于其 RMSE；幅度斜坡产生约 10 MHz 的有方向偏差，
对应窗内振幅加权有效时刻偏离 frame center。R3 在正确二次相位模型下减少这种局部误差。
机制参考：对远离零频/Nyquist、可单独表示为 A(t)exp(iφ(t)) 的分量，局部谱能量质心满足
f_centroid=∫h²A²f(t)dt/∫h²A²dt；线性 f=f0+cτ 时，偏移为 c∫τh²A²dt/∫h²A²dt。
恒幅对称窗的奇矩为零，AM 则可能非零。谱峰不等于质心，这个关系解释偏移机制，
不是本任务用来修正峰值的公式，也不能直接套到不可分的双分量或混合噪声峰。
非线性 chirp 仍有模型失配；R3 不是任意相位函数的真值恢复器。
mean absolute waveform bias 同时提供，避免正负 chirp/curvature 平均抵消后误称无 bias。

R3 局部模型诊断（全量逐波形/profile 在 local_chirp_fit_diagnostics.csv）：

{table(fit_summary, ['snr_db', 'family', 'chirp_rate_rmse_hz_per_s', 'weighted_residual_fraction', 'bank_boundary_fraction'])}

chirp-rate error 仅在 evaluator 计算；它从未进入估计器。恒幅线性模型较好时残差主要来自加性噪声；
AM 模型不包含振幅包络，因此即使频率正确也可能有较大振幅残差。低 SNR 下选择 bank 极端值的比例
和 rate error 用于揭示过拟合噪声风险，不据此重新选择 bank 或阈值。

![bias audit]({output.as_posix()}/figures/bias_vs_chirp_rate.png)

## Phase A：噪声与衰落

{table(snr_table, ['SNR_dB', 'method', 'RMSE_MHz', 'failure_percent', 'recall_percent', 'false_candidate_percent'])}

![error vs SNR]({output.as_posix()}/figures/frequency_error_vs_snr.png)

SNR 是衰落前单目标 A²/(2σ²)，不是衰落后的局部 SNR，也不是双分量总功率 SNR。
temporary fading 同时改变局部 SNR 和有限窗内的振幅权重；高 SNR 有 R3 收益、低 SNR 全部受限，
因此不能只归结为一种原因。候选级 false fraction 通常很高，因为 Top-20 是弱门控的假设集合；
它衡量候选污染，不能直接解读为正式检测器误报概率。

## Phase B：双分量分辨

{table(two_table, ['family', 'method', 'resolution_percent', 'recall_percent'])}

![resolution]({output.as_posix()}/figures/resolution_vs_separation.png)
![SNR separation]({output.as_posix()}/figures/snr_separation_map.png)
![slope separation]({output.as_posix()}/figures/separation_chirp_difference_map.png)

完整四类物理失效图见 figures：SNR×separation、SNR×chirp、separation×amplitude ratio、
separation×chirp difference，统一色标，两个 profile 单独显示；其他预注册轴等权边缘平均。
crossing/merge/diverge 图使用单独命名案例；不把 crossing 的名义 span 冒充中心频差。
coincident intervals 的频率分辨定义自然失败；跨时间/额外 chirp-rate 信息是否能区分成分不在此证明范围。

## Fresh core：100% Recall 的信息边界

{table(core_table, ['method', 'recall_percent', 'hits', 'truth_frames', 'strongest_RMSE_MHz', 'nearest_RMSE_MHz', 'resolution_percent', 'resolved_frames', 'two_component_frames', 'truth_near_rank', 'candidate_count'])}

该表只含 fresh held-out core，与 controlled 结果分开。candidate_recall.csv 另含 calibration、focus、
noise 分层。旧“Recall=100%”不能说明最强频率正确、误差小，也不能说明两个近频分量独立可分。
最近候选的低误差和最强候选的大误差之间的差距说明候选集合与选择是不同问题，
本任务未据此继续修改 Top-K/Beam/scorer。

## Representation Gate 与 runtime

{table(gates, ['method', 'verdict', 'overall_RMSE_gain_percent', 'fast_RMSE_gain_percent', 'best_resolution_gain_pp', 'runtime_ratio', 'accuracy', 'recall', 'resolution', 'false_candidates', 'runtime', 'hard_gain'])}

每项门限见 protocol.md；所有条件必须同时满足。representation_gate.json 保存每数据集/profile 的
Recall 比较、每个预定义困难区域的 resolution gain、低 SNR 污染变化及纯噪声候选数量变化。
runtime.csv 为无其他 benchmark/test 并发的顺序独立计时，每预注册计时角色/profile/method 重复3次并轮换顺序；
包含表示计算和候选提取，不含生成/评估/I/O。批处理 elapsed_s 只作为并行吞吐诊断。
首个 stationary 与首个 -20 dB 角色选中同一波形；12个角色对应11个唯一波形，该波形计时6次。
按原选取规则保留角色权重，未根据计时结果重加权；runtime_design_note.json 在计时前记录此重合。
没有通过完整 gate，所以 optional_backend_comparison.csv 明确 SKIPPED，未运行 frozen P3 compatibility。
也未运行34真实 streams、ch3，不能声称真实频率/速度更正确或恢复真实支路。

## 可辨识性解释与下一阶段

匹配物理参数后，-20 dB 四方法均达到预注册失败标准、30 dB 四方法均成功的条件组：
**{int(matched.sum())}/{len(matched)}**（含 profile 分层，不能当独立重复数）。
对应明细 denoising_matched_conditions.csv。它支持噪声是当前大误差的重要来源。
低 SNR 且近分量区域可谨慎标记 **LIKELY OBSERVATION-LIMITED**，但没有严格 identifiability proof，
尤其不能忽略共同的 2/T 提取限制。所有方法失败并不证明不存在更优估计器。

建议独立 denoising safety audit：{verdicts['waveform_denoising']}。如获后续授权，优先固定、可复现的
deterministic band-limited filtering；只有已知窄带干扰才加入 notch。先建立滤波器相位/群延迟、
frequency bias、chirp attenuation、edge smearing 和 false spectral structure 的注入-恢复审计。
不把“谱更干净”或“零相位”当作物理无损证明，也不优先引入自适应复杂分解。
当前 Candidate 已限定分析频带；预滤波不会凭空增加信息，也不保证改善带内噪声造成的可辨识性。
下一审计应同时保留“不改善但引入边缘/相位影响”这一可能结果。
本任务没有启动 TASK-027、AI、denoising、新 scorer 或 Beam 变体。

## 14 个核心问题的逐项回答

1. **Stationary STFT 是否接近最优？** 在本次高 SNR stationary 上 R0 与 R3 相同且优于 R1/R2，
   支持当前方法在此区间足够有效；没有比较严格 CRB/所有估计器，不能证明全局最优。
2. **Fast chirp 是否有明显系统 bias？** 恒幅线性情形没有普遍的大 signed bias；AM ramp/fading 与非线性
   情形出现更大的局部偏差/误差，必须按物理条件报告。
3. **精修是否真正降低 bias？** 精修显著减小频点量化误差，但不是消除 chirp/AM 窗内权重偏差的机制；
   离散与精修列直接可比，AM 条件可以更精确地定位仍有偏差的峰。
4. **R1/R2 是否只是更锐？** 锐度不是指标；本次实际提取候选后的误差和 gate 未支持替换。
   这约束本次能量重分配实现，不等价于否定所有 SST。
5. **哪种方法低 SNR 最有效？** 按本次 SINGLE SNR≤0 的 waveform-macro RMSE，{best_low} 最低，
   {low_rmse[best_low]/1e6:.3f} MHz（R0={low_rmse['R0']/1e6:.3f} MHz）。这不是跨家族的稳定胜者；
   极低 SNR 下四方法均有 noise-driven 大误差，不能宣称普遍鲁棒。
6. **哪种方法 fast chirp 最有效？** R3 在高 SNR 正确局部二次相位条件最强；overall/low-SNR 提升
   和完整 gate 单独评判，不能外推到非线性/多分量/实测。
7. **哪种方法最能分开近频双支路？** 预注册 CLOSE（瞬时频差≤150 MHz）区域内，{best_close} 的
   waveform-macro resolution 最高，为{100*close_rates[best_close]:.3f}%（R0={100*close_rates['R0']:.3f}%）。
   没有同时保持 Recall、精度、污染和 runtime 的全面替换方案；所有方法受到固定最小候选间距限制。
8. **Crossing 是否表示层不可分？** 精确重合在本次频率-only 一一匹配定义下不可分；
   相邻帧、不同 slope 或全波形信息是否能辨别不是本次不可辨识证明。
9. **Fading 是表示还是 SNR？** MIXED：AM 改变窗内加权，衰落也降低局部 SNR；高低 SNR 对照分别支持两者。
10. **100% Recall 是否掩盖 bias/unresolved？** 是；宽200MHz附近有候选，与两个独立分量和精确频率完全不同。
11. **是否值得替换 STFT frontend？** 当前没有方法通过 REPRESENTATION_GATE，不能支持替换。
12. **是否保留 Candidate + trajectory？** KEEP。此次只审计观测层，未证明整个架构需替换。
13. **是否有证据进入 waveform denoising？** {verdicts['waveform_denoising']}，依据匹配 low/high-SNR 条件，
    仅建议单独安全性审计，不宣称滤波一定改善物理频率。
14. **下一任务优先什么滤波？** 固定带限；有已知干扰再考虑 notch，同时检验相位、chirp、边界和伪结构。

## 验证、限制与交付

- 新增34项测试全部通过；完整 pytest：{validation['pytest']}。
- 仅两个历史 launcher 失败；初轮 CLI 参数污染复核后消失。保存所有日志，未改 unrelated launcher。
- Ruff、strict mypy、git diff --check：PASS。完整命令范围见 tests/ 和 validation_summary.json。
- 核对 {boundary['preexisting_files_checked']} 个既有文件、{boundary['raw_entries']} 条 raw SHA-256：全部不变。
- Production/main、Research HEAD、两边 main ref、已有 tracked/staged diff 全部不变。无 commit/push。
- 本轮首次 snapshot 因 GBK 解码大 diff 失败，改为保存原始 diff bytes + UTF-8 replacement 展示。
  哈希遍历在新增源码前启动，boundary JSON 写完于13:53:07，比首个新增模块13:52:48晚19秒，
  但在任何 benchmark 观测之前；既有 tracked/raw 清单在遍历启动时固定，新增文件不在原清单内。
  因而 protocol 的“snapshot before source creation”措辞应理解为启动顺序，不能宣称 JSON 已先写完。
  首次 registration serializer 使用不存在的 to_metadata 失败，
  改为 dataclass asdict；已写 protocol/seeds 完全一致核验后补齐 manifest，发生在任何 benchmark 之前。
- R2 非完整 SST、R1 的支持长度差、固定峰间距、R3 网格和模型范围、controlled 每格2个 held-out 重复
  都是结论适用边界。未以新的 waveform distribution 或 held-out 调参支持新方法。

关键 artifact：protocol.md、seed_registration.json、frozen_manifest.json、method_configs.json、
single_component_benchmark.csv、chirp_bias.csv、two_component_benchmark.csv、resolution_rate.csv、
candidate_recall.csv、failure_maps.csv、runtime.csv、optional_backend_comparison.csv、validation_summary.json。
waveforms/ 保留原始合成数据与 truth，streams/ 保留完整估计数组与质量 flags。
代表图按预注册 ID 选取，stationary、fast-chirp、crossing 各含 10 dB 与 -20 dB，不只展示成功案例。

## 核验来源

重分配坐标的 derivative-window 定义核对自
[librosa 官方源码文档](https://librosa.org/doc/0.11.0/_modules/librosa/core/spectrum.html)。
解析 chirp 的相位积分与瞬时频率约定核对自
[SciPy 官方 chirp 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.chirp.html)。
其余定量结论是本次实验结果/模型解释，不伪装为文献事实；未编造 DOI 或元数据。

**TASK-026 完成后停止，等待人工审计。**
'''
    with (output/'final_research_report.md').open('x', encoding='utf-8') as handle:
        handle.write(body)
    note = Path('D:/Research/Notes/05项目/dps/2026-09-15_TASK-026_frequency-representation.md')
    short = f'''---
task: TASK-026
date: 2026-09-15
branch: {baseline['Research']['git']['branch --show-current']}
status: COMPLETE_RESEARCH_ONLY
verdict: STFT_MIXED; R1_{gate['R1']['verdict']}; R2_{gate['R2']['verdict']}; R3_{chirp_interpretation}; KEEP
artifact: {output.as_posix()}
---

新增 Research task026 表示/benchmark 模块、freeze/run/summarize/plot/verify/report 脚本、34项测试。
2783 fresh波形：128原分布core、765单分量、1890双分量；所有方法同一raw、frame centers、K20。
R0原STFT精修；R1时频能量重分配；R2频率能量压缩（非可逆SST）；R3固定局部chirplet bank。
高SNR stationary/fast-chirp RMSE与bias（MHz）：
{table(high_snr[high_snr.family.isin(('stationary', 'fast_chirp'))], ['family','method','RMSE_MHz','bias_MHz'])}

低SNR无稳定胜者；匹配-20/30dB条件四法低SNR失败/高SNR成功 {int(matched.sum())}/{len(matched)}。
双分量采用min(50MHz,sep/4)一一匹配；2/T既有候选间距限制须与物理不可辨识分开。
{table(core_table, ['method','recall_percent','resolution_percent'])}

科学解释R3=MIXED（精度改善、双分量下降）；预注册Gate R0对照外三法均NOT SUPPORTED，原门限/结果不变。
Phase D、34真实streams、ch3全部SKIPPED；backend冻结。
pytest={validation['pytest']}，仅两项既有launcher失败；新增34通过。Ruff/strict mypy/diff check PASS。
git继承Research5215/Production349测试文件删除；既有tracked/staged diff未变。
{boundary['raw_entries']} raw SHA-256及{boundary['preexisting_files_checked']}既有文件不变。
Production/main={baseline['Production']['git']['rev-parse HEAD'][:8]}、Research HEAD={baseline['Research']['git']['rev-parse HEAD'][:8]}不变；无commit/push。
建议独立waveform denoising safety audit={verdicts['waveform_denoising']}：固定带限优先，已知干扰再notch；审计phase/frequency/chirp/edge/伪结构。
未启动TASK-027。完整数据/失败门限见[报告]({output.as_posix()}/final_research_report.md)。本日志仅索引。
'''
    with note.open('x', encoding='utf-8') as handle:
        handle.write(short)
    with (output/'README.md').open('x', encoding='utf-8') as handle:
        handle.write('# TASK-026\n\nSee final_research_report.md and protocol.md.\n\n'
            'Reproduce in a NEW artifact directory: snapshot_task026, freeze_task026; '
            'run_task026 stages single_calibration, sanity, single_held_out, '
            'two_core_calibration, two_core_held_out, runtime; summarize_task026, '
            'plot_task026, tests, verify_task026, report_task026. '
            'Existing outputs use exclusive creation and are never replaced.\n')
    write_json(output/'delivery_receipt.json', dict(obsidian=str(note),
        obsidian_sha256=digest(note), report_sha256=digest(output/'final_research_report.md'),
        verdicts=verdicts, source_files=[str(p.relative_to(ROOT)) for p in (
            *ROOT.glob('src/dps_studio/research/task026*.py'), *ROOT.glob('scripts/*task026.py'),
            *ROOT.glob('tests/unit/test_task026*.py'))]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    report(parser.parse_args().output)


if __name__ == '__main__':
    main()
