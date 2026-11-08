"""Record-level summaries and paired bootstrap; no estimator parameter changes."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

OUT=(Path(__file__).resolve().parents[3] / "artifacts/TASK-015")
ROOT=OUT.parents[1]
METHODS=['M1_balanced','M2_task014_gui','M3_parameters','M4_specialized','TASK014_research_simple']


def aggregate(frame):
    n,m=frame.target_n.sum(),frame.finite_n.sum()
    return dict(records=len(frame),target_n=n,finite_n=m,
        rmse_m_s=np.sqrt(frame.sse.sum()/m) if m else np.nan,
        coverage_pct=100*m/n if n else np.nan,
        failure_pct=100*frame.failure_n.sum()/n if n else np.nan,
        failure30_pct=100*frame.failure30_n.sum()/n if n else np.nan,
        error50_pct=100*frame.error50_n.sum()/n if n else np.nan,
        wrong_branch_pct=100*frame.wrong_branch_n.sum()/frame.branch_n.sum() if frame.branch_n.sum() else np.nan,
        branch_missing_pct=100*frame.branch_missing_n.sum()/frame.branch_n.sum() if frame.branch_n.sum() else np.nan,
        absent_output_pct=100*frame.absent_output_n.sum()/frame.absent_n.sum() if frame.absent_n.sum() else np.nan,
        onset_mae_ns=frame.onset_error_ns.abs().mean(),onset_missed=frame.onset_missed.sum(),
        onset_eligible=frame.onset_eligible.sum(),step_error_m_s=frame.step_error_m_s.mean(),
        valley_bias_m_s=frame.valley_bias_m_s.mean(),runtime_ms=1000*frame.runtime_s.mean())


def table(frame,columns):
    def fmt(value):
        if isinstance(value,(float,np.floating)):
            return '—' if not np.isfinite(value) else f'{value:.3f}'
        return str(value)
    return '\n'.join(['| '+' | '.join(columns)+' |','|'+'|'.join(['---']*len(columns))+'|']+
        ['| '+' | '.join(fmt(row[c]) for c in columns)+' |' for _,row in frame.iterrows()])


def main():
    data=pd.read_csv(OUT/'data/heldout/metrics.csv')
    freeze=json.loads((OUT/'data/heldout/freeze.json').read_text(encoding='utf-8'))
    checks={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in freeze['sources'].items()}
    # Plot/report scripts are intentionally outside the estimator freeze.
    assert all(checks.values()),checks
    (OUT/'data/heldout_source_check.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    rows=[]
    for region in ('all','observable_motion'):
        subset=data if region=='all' else data[~data.family.isin(['drift_spur','subcycle_ac','noise_only'])]
        for (method,kind),group in subset.groupby(['method','kind']):
            rows.append(dict(region=region,method=method,kind=kind,**aggregate(group)))
    summary=pd.DataFrame(rows)
    summary.to_csv(OUT/'data/summary.csv',index=False)
    families=pd.DataFrame([dict(family=family,method=method,kind=kind,**aggregate(group))
        for (family,method,kind),group in data.groupby(['family','method','kind'])])
    families.to_csv(OUT/'data/families.csv',index=False)
    rng=np.random.default_rng(153000015)
    contrasts=[('low_spur','stft_low','low_glrt'),('low_tone','stft_low','low_glrt'),
        ('plateau','clip_2048','tone_refine'),('fast_accel','unsigned_dechirp','signed_dechirp'),
        ('fast_decel','unsigned_dechirp','signed_dechirp'),('weak_fixed','M1_balanced','clutter_varpro'),
        ('weak_drift','M1_balanced','clutter_varpro'),('crossing','M1_balanced','clutter_varpro'),
        ('prefix_target','M1_balanced','background_stft'),('all','M3_parameters','M4_specialized')]
    paired=[]
    for family,a,b in contrasts:
        group=data[(data.kind=='gated') & ((data.family==family) if family!='all' else True)]
        left=group[group.method==a].set_index('case')
        right=group[group.method==b].set_index('case')
        keys=left.index.intersection(right.index)
        left,right=left.loc[keys],right.loc[keys]
        nonzero=left.target_n>0
        left,right=left[nonzero],right[nonzero]
        delta=(right.failure_n/right.target_n-left.failure_n/left.target_n).to_numpy()*100
        boot=np.mean(delta[rng.integers(0,len(delta),(5000,len(delta)))],axis=1)
        paired.append(dict(family=family,baseline=a,candidate=b,records=len(delta),
            failure_difference_pp=float(delta.mean()),ci_low=float(np.quantile(boot,.025)),
            ci_high=float(np.quantile(boot,.975)),bootstrap_unit='waveform',multiplicity='exploratory_uncorrected'))
    pairs=pd.DataFrame(paired)
    pairs.to_csv(OUT/'data/paired_bootstrap.csv',index=False)
    sensitivity=pd.read_csv(OUT/'data/sensitivity_v02/metrics.csv')
    sens=pd.DataFrame([dict(family=family,boundary_ns=b,mislabel=m,method=method,**aggregate(group))
        for (family,b,m,method),group in sensitivity[sensitivity.kind=='gated'].groupby(
            ['family','boundary_ns','mislabel','method'])])
    sens.to_csv(OUT/'data/boundary_summary.csv',index=False)
    overall=summary[(summary.region=='all')&(summary.kind=='gated')&summary.method.isin(METHODS)]
    candidate=summary[(summary.region=='all')&(summary.kind=='candidate')&summary.method.isin(METHODS)]
    cols=['method','rmse_m_s','coverage_pct','failure_pct','failure30_pct','wrong_branch_pct','branch_missing_pct']
    lines=['# TASK-015 对照与失败记录','',
      '任务开始 2026-11-07；分析及验收跨至 2026-11-08。所有性能数字来自本任务合成实验，真实数据只报告 Hz 观测。',
      '', '## 设计与有效性边界','',
      '开发集 72 条；独立 held-out 288 条（18 场景 × 16 条），开发/测试使用互不相交 RNG 块。独立低频测试覆盖 20/40/80/120 MHz × −8/4/12/20 dB，各组合一个随机初相；每场景 n=16，不能代表装置外泛化。另有 336 条配对边界/误标扰动与 20 条脉冲分辨实验。首轮 84 条扰动仅覆盖 −8 dB，已原样保留并扩展至四个 SNR 层，见 SENSITIVITY_NOTE.md；重复波形不作为独立重复。开发 v01 的“无杂散投影”消融曾误用全频单峰，v02 已修正为同频带、同门控仅关闭杂散投影；v01 仅作过程留档。独立测试未用于重新调参。',
      '', '每条 40 GHz、12,800 点，共同中心 1024+128k≤N−1024，共 85 点、3.2 ns 间隔。不同方法的支撑窗不同，但比较中心严格相同；没有插值、逐帧真值选优、平滑或填洞。短窗/长窗等 GUI 策略默认 H64，研究比较 H128；更密采样不能当作独立证据。',
      '', 'M1 是当前正式 Balanced STFT 1024/64/NFFT4096（50 MHz–6 GHz）。M2 是 TASK-014 GUI 映射：加速 Dechirp、噪声排除、其他 STFT。M3 仅用阶段窗长/边界/频带参数；M4 在相同路由中增加低频 GLRT、长窗正弦精修、斜率先验 Dechirp，并探索噪声→Clutter VarPro。另列 TASK-014 研究版 simple mapping，避免把 GUI 默认与研究基准混为一谈。M3/M4 是消融候选，不等于最终 GUI 默认。',
      '', '## 完整分母指标','',
      '历史失败 = 缺失或 |误差|>77.5 m/s；历史错支路 = 两真值支路相距>20 MHz 时更接近干扰支路。新增 failure30 与 error50 是误差阈值指标，不能冒称物理支路身份。RMSE 只在有限目标点计算，必须同时读覆盖/含缺失失败；candidate 仍可能有缺失。静止漂移的潜在零频和 AC 耦合不可观测低速保留在目标分母，故诚实拒绝仍计失败；另附 observable_motion 汇总以便分离可观测性。',
      '', '**门控后：**','',table(overall,cols),'','**门控前候选：**','',table(candidate,cols),
      '', '完整误差阈值、无目标输出、阶跃误差、谷底偏差和分母见 data/summary.csv、data/families.csv；每条波形的所有失败保留于 data/heldout/metrics.csv 和 cases。',
      '', '## 数学模型与诊断','',
      '局部模型 y(τ)=P₂(τ)c+a_c cos(2πf_cτ)+b_c sin(2πf_cτ)+a cos(2πfτ)+b sin(2πfτ)+ε。低频 GLRT 对背景子空间同时投影 y 和正余弦基，逐频优化残差；f_c 来自本窗高频谱峰并经局部拟合，绝不来自真值。f_c 项可消融关闭。低频范围受用户频带与 250 MHz 上限共同限制；分析窗 4096 点，最少 1.25 周期、设计条件数≤10⁴、部分 R²≥0.20、谱对比度≥10 dB、残差改善统计量≥12。该搜索后统计量不是校准 CFAR、置信区间或物理身份检验。',
      '', '原始实值模型显式拟合随机相位和基线；GLRT 保留原谱候选、残差谱候选、所选频率、杂散频率、R²、条件数、周期数及支撑区间。单位为 V、s、Hz，合成表观速度用 λf/2、λ=1550 nm；物理修正仅在既有链中执行。',
      '', '低频评分用 log(1+谱功率/中位功率) 减去有上限的频率惩罚。强杂散仍可压过先验；静止误标时硬低频带又会拒绝真实高频。这是信息不可辨识与先验错误的代价，不能用“未检出=0”掩盖。静止先验零单独记录，测量频率/速度不填零。',
      '', '## 配对消融','',table(pairs,['family','baseline','candidate','records','failure_difference_pp','ci_low','ci_high']),
      '', '差值 = 候选 − 基准，百分点；5000 次以整条波形重抽样的百分位区间，探索性、未校正多重比较。相邻重叠帧不是独立重复。零差值不证明统计等价。',
      '', '## 边界、转折与时间分辨','',
      'data/boundary_summary.csv 保留 ±5/±15/±30 ns 全部结果，并单列把运动误标为静止。起跳是连续两个有限中心超过 100 m/s 的首中心，与真值首次过阈值比较；同时报漏检，不把条件 MAE 当全样本精度。阶跃失真为起跳后 15 ns 内有限点平均绝对误差；谷底偏差为 170–190 ns 窗内最小值差，须与覆盖共同判断。',
      '', 'data/resolution/metrics.csv 检验 2/4/8/16/32 ns 的 600 MHz→1.8 GHz→600 MHz 脉冲；每宽度四个随机相位/位置实例，6/18 dB。resolved 仅表示脉冲内部至少一个有效中心超过 1.2 GHz，并同时报告外部错误高频点与宽度误差；真实边界作为额外人工输入，不能解释为自动定位能力。采样网格 3.2 ns，最短脉冲可能根本没有内部中心，不作亚纳秒能力宣称。',
      '', '## 噪声干扰与历史负结果','',
      '固定杂散下相干前缀背景有条件收益；漂移杂散/交叉支路/消光仍失败。前缀已有目标时背景扣除会删除真实目标，这是不能默认应用的明确反例。完整候选及独立质量诊断保留；本任务不桥接，不把预测冒充测量。',
      '', '历史根目录 COMPARISON.md（TASK-008）及 TASK-013 COMPARISON.md 已指出：PSD Whitening、Global Path/多假设追踪不能创造新的波形信息；ACMD 单模态变体无综合净优势，低信号下损失覆盖。此次未重新调这些复杂路径模型；首先测试简单背景与现有 Clutter VarPro，避免把复杂度当进步。',
      '', '## 最终推荐与手动覆盖','',
      '| 阶段 | 自动推荐 | 可手动研究选项及边界 |','|---|---|---|',
      '| 静止 | STFT，显式人工静止先验 | 低频带 STFT / GLRT；须核验频带、周期数、杂散与误标 |',
      '| 起跳 | STFT | 边界短窗；准确边界不保证弱信号收益 |',
      '| 加速 | 既有 Dechirp | 研究脚本含边界/斜率消融，未把符号先验增益当既定事实 |',
      '| 平台 | STFT | 长窗 STFT / 正弦精修；长稳定段才满足局部定频模型 |',
      '| 下降、回升 | STFT | 短窗和已有 VarPro；转折处长窗可削平极值 |',
      '| 弱信号 | STFT | 观察候选与质量，不自动填补 |',
      '| 噪声干扰 | STFT，取消直接 NaN 映射 | Clutter VarPro 仍为手选；固定/漂移杂散身份须复核 |',
      '| 未知 | STFT | 由实验员选策略；不自动猜阶段 |',
      '', '新增专项方法的收益具有输入假设；误标/干扰反例阻止无条件默认升级。每次阶段编辑即时采用上述映射，随后手选受到保护；无关刷新不重置。内部 observation_quality 与运动阶段独立；九个入口为向后兼容仍保留弱信号/噪声入口，不宣称已经实现完整正交分类 GUI。',
      '', '## 真实观测、成本与复现','',
      '真实输入固定为 TASK-009 索引的全部 13 文件/17 流、完整记录。所有非人工标注均为 unknown，故 M2/M3/M4 默认路由等于 M1；另外显式运行各研究策略作 Hz 级敏感性诊断，绝不凭外观设真值。data/real_v02/diagnostics.csv 提供覆盖、共同中心频差、质量与候选；不能报告真实速度/RMSE/准确率或确认物理支路。',
      '', '首轮 real/ 保留失败：两个历史时间戳由正式 STFT 重建后与 CSV 有浮点舍入差，直接 searchsorted 可能偏一帧。real_v02 使用整数原采样中心匹配，17 流逐一验证，最大时间差与候选哈希见 data/grid_check.json；未做轨迹插值。',
      '', '并行研究运行时长只供执行追踪，不用于定量加速比；data/cost.csv 另列无并行任务干扰时的单线程重复测量。阶段映射的成本按使用到的整轨组件相加，含保守重复支撑成本，并非 GUI 按段优化后的延迟。',
      '', '复现命令和验收见 README.md、VALIDATION.md。所有原始输入只读；删除清单、前后完整 Production/raw 摘要、Git 状态及磁盘清单在 disk_governance/。文献仅作为方法背景：Dolan (2010), DOI [10.1063/1.3429257](https://doi.org/10.1063/1.3429257)；时域 Bayesian 线索见 [arXiv:2508.13695](https://arxiv.org/abs/2508.13695)。附件性能预测未经本任务独立证实的部分均为 unverified，本任务方法不声称完整复现文献算法。']
    cost=pd.read_csv(OUT/'data/cost.csv')
    costs=cost[cost.method.isin(METHODS)].groupby('method').runtime_ms.agg(
        median_ms='median',minimum_ms='min',maximum_ms='max').reset_index()
    costs.to_csv(OUT/'data/cost_summary.csv',index=False)
    lines += ['', '## 独立串行成本测量', '',
              '6 个代表场景 × 3 次重复，单线程数值库，无同时进行的研究或构建任务；下表为每条完整记录的组件成本，映射相加，包含初始化。最小/最大不是置信区间。机器与版本见 data/environment.json。', '',
              table(costs,['method','median_ms','minimum_ms','maximum_ms'])]
    (OUT/'COMPARISON.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(table(overall,cols))
    print(table(pairs,['family','baseline','candidate','failure_difference_pp','ci_low','ci_high']))


if __name__=='__main__':
    main()
