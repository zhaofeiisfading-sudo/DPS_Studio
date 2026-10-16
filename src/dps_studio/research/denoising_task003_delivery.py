"""TASK003 delivery from immutable numeric tables; no estimator selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from dps_studio.research.denoising_task003_statistics import aggregate, read_csv
from dps_studio.research.denoising_task003_study import write_csv, write_json


def identity_control() -> dict[str, Any]:
    """Reproduce the independently executed observation-preserving label control."""
    from dps_studio.core.models import SignalRecord
    from dps_studio.research import denoising_task001 as m2
    from dps_studio.research import denoising_task003 as risk
    from dps_studio.research import task028_consolidation as frozen
    from dps_studio.research.denoising_task003_study import PROFILES, hash_array
    from dps_studio.research.task023e_waveform_benchmark import oscillator_phase

    rng = np.random.default_rng(43088001)
    t = np.arange(32000)/40e9
    upper = np.full(len(t), 3e9)
    event = (t >= 300e-9) & (t < 410e-9)
    lower = upper.copy()
    lower[event] = 1.8e9
    transition = np.clip((t-300e-9)/110e-9, 0, 1)
    a = 1.15-.98*transition
    a[event] = 1.05
    b = .08+1.02*transition
    b[event] = .86
    u = a*np.cos(oscillator_phase(lower, phase0=float(rng.uniform(-np.pi, np.pi))))
    v = b*np.cos(oscillator_phase(upper, phase0=float(rng.uniform(-np.pi, np.pi))))
    noise = rng.normal(0, .18, len(t))
    x, y = u+v+noise, v+u+noise
    assert np.array_equal(x, y)
    scores = []
    for profile in PROFILES:
        stfts = []
        outputs = []
        for obs in (x, y):
            stft, peaks = frozen.frontend(SignalRecord(t, obs), profile)
            base = frozen.consolidate(stft, peaks).trajectories['M2'].frequency_hz
            proposals = m2.propose_repairs(stft, peaks, base)
            out, _ = m2.apply_repairs(peaks, base, proposals)
            r3, _, _ = risk.risk_repair(peaks, base, proposals)
            stfts.append(stft)
            outputs.append((base, out, r3))
        assert np.array_equal(stfts[0].spectrum, stfts[1].spectrum)
        ix = np.rint(stfts[0].time_s*40e9).astype(int)
        trutha, truthb = lower[ix], upper[ix]
        contradictory = abs(trutha-truthb) > 400e6
        for k, name in enumerate(('M1', 'M2', 'R2_B3')):
            path = outputs[0][k]
            assert np.array_equal(path, outputs[1][k])
            both = (abs(path-trutha) <= 200e6) & (abs(path-truthb) <= 200e6)
            assert not np.any(both & contradictory)
            scores.append(dict(profile=profile.profile_id.value, method=name,
                path_sha256=hash_array(path),
                target_A_wrong=int((abs(path-trutha) > 200e6).sum()),
                target_B_wrong=int((abs(path-truthb) > 200e6).sum()),
                contradictory_frames=int(contradictory.sum()),
                both_correct_on_conflict=int((both & contradictory).sum()),
                complex_stft_sha256=hash_array(stfts[0].spectrum)))
    return dict(voltage_A_sha256=hash_array(x), voltage_B_sha256=hash_array(y), scores=scores)


def _pct(value: Any) -> str:
    return 'NA' if value is None or value == '' else f'{100*float(value):.3f}%'


def deliver(out: Path) -> None:
    frozen = json.loads((out/'calibration_freeze.json').read_text())
    chosen = frozen['M3']
    rows = read_csv(out/'held_out_metrics.csv')
    primary = [r for r in rows if r['reference'] == 'M1']
    names = ['M0', 'M1', 'M2', chosen, 'R1']
    values = {m: aggregate([r for r in primary if r['method'] == m]) for m in names}
    decision = json.loads((out/'held_out_readiness.json').read_text())[chosen]
    readiness = bool(frozen['calibration_passed'] and decision['passed'])
    # This delivery is intentionally conditional, not a fabricated real-data run.
    if readiness:
        raise RuntimeError('Real-data gate passed: perform authorized read-only evaluation first')
    write_json(out/'real_data_decision.json', dict(status='SKIPPED',
        reason='Complete calibration and held-out trajectory requirements not both passed',
        actual_new_real_STFT_runs=0, accuracy='UNKNOWN', ch3_tuning=False))
    baseline = read_csv(out/'held_out_comparison.csv')
    for row in baseline:
        if row['method'] == chosen:
            row['method'] = 'M3'
    write_csv(out/'baseline_comparison.csv', baseline)
    proposals = read_csv(out/'held_out_proposals.csv')
    for row in proposals:
        if row['method'] == chosen:
            row['method'] = 'M3'
            row['flag'] = ('AMBIGUOUS_INTERVENTION' if row['rejected'] == 'True'
                           else 'IDENTITY_UNVALIDATED')
    write_csv(out/'accepted_rejected_proposals.csv', proposals)
    diagnostics = read_csv(out/'held_out_risk_diagnostics.csv')
    for row in diagnostics:
        if row['method'] == chosen:
            row['method'] = 'M3'
    write_csv(out/'risk_diagnostics.csv', diagnostics)
    risk_row = next(r for r in diagnostics if r['method'] == 'M3')
    frames = read_csv(out/'held_out_frames.csv')
    harms = []
    for row in frames:
        if row['harmed'] == 'True':
            harms.append(dict(**row, M3_rejected=row[chosen+'_rejected'],
                              retained_M3_harm=row[chosen+'_rejected'] == 'False'))
    write_csv(out/'harm_audit.csv', harms)
    profile_rows = []
    for profile in sorted({r['profile'] for r in rows}):
        for ref in ('M0', 'M1'):
            for method in names:
                profile_rows.append(dict(profile=profile, reference=ref,
                    method='M3' if method == chosen else method,
                    **aggregate([r for r in rows if r['profile'] == profile
                                 and r['method'] == method and r['reference'] == ref])))
    write_csv(out/'profile_comparison.csv', profile_rows)

    # Post-evaluation descriptive intervals, not used to select or gate the method.
    cases = sorted({r['case_id'] for r in primary})
    cluster = []
    selected_proposals = [r for r in proposals if r['method'] == 'M3']
    for case in cases:
        a = aggregate([r for r in primary if r['case_id'] == case and r['method'] == chosen])
        b = aggregate([r for r in primary if r['case_id'] == case and r['method'] == 'M2'])
        ps = [r for r in selected_proposals if r['case_id'] == case]
        hp = [r for r in ps if int(r['harmed']) > 0]
        np_ = [r for r in ps if int(r['harmed']) == 0]
        cluster.append([a['harmed_frames'], b['harmed_frames'],
                        a['corrected_frames'], b['corrected_frames'],
                        sum(r['rejected'] == 'True' for r in hp), len(hp),
                        sum(r['rejected'] == 'True' for r in np_), len(np_)])
    arr = np.asarray(cluster)
    rng = np.random.default_rng(43099004)
    draws = arr[rng.integers(len(arr), size=(4000, len(arr)))].sum(axis=1)
    intervals = {}
    for name, numerator, denominator, complement in (
            ('harm_reduction', 0, 1, True), ('benefit_retention', 2, 3, False),
            ('risk_recall', 4, 5, False), ('false_positive_rate', 6, 7, False)):
        valid = draws[:, denominator] > 0
        v = draws[valid, numerator]/draws[valid, denominator]
        if complement:
            v = 1-v
        intervals[name] = dict(lower=float(np.quantile(v, .025)),
                               upper=float(np.quantile(v, .975)),
                               estimable_resamples=int(valid.sum()))
    write_json(out/'risk_waveform_uncertainty.json', dict(
        units=len(cases), resamples=4000, seed=43099004,
        role='Post-evaluation descriptive; never used for method selection', intervals=intervals))
    timing = read_csv(out/'held_out_provenance.csv')
    costs = {}
    for name in ('frontend_s', 'p3_s', 'm2_increment_s', chosen+'_increment_s'):
        x = np.array([float(r[name]) for r in timing])
        costs[name] = dict(median_s=float(np.median(x)), p95_s=float(np.quantile(x, .95)),
                          total_s=float(x.sum()))
    write_json(out/'runtime_summary.json', costs)

    family_rows = read_csv(out/'held_out_family_comparison.csv')
    family_table = []
    for family in sorted({r['family'] for r in primary}):
        family_values = {m: aggregate([r for r in primary if r['family'] == family and r['method'] == m])
             for m in ('M0', 'M1', 'M2', chosen)}
        family_table.append('| '+family+' | '+ ' | '.join(
            f"{family_values[m]['rmse_hz']/1e6:.3f}" for m in ('M0', 'M1', 'M2', chosen))
            + f" | {family_values['M2']['corrected_frames']:.0f}/{family_values[chosen]['corrected_frames']:.0f}"
            + f" | {family_values['M2']['harmed_frames']:.0f}/{family_values[chosen]['harmed_frames']:.0f} |")
    main_table = []
    for m in names:
        a = values[m]
        main_table.append(f"| {'M3' if m == chosen else m} | {a['rmse_hz']/1e6:.3f}"
            f" | {_pct(a['wrong_branch_fraction'])} | {a['corrected_frames']:.0f}"
            f" | {a['harmed_frames']:.0f} | {_pct(a['intervention_precision'])}"
            f" | {_pct(a['harm_per_intervention'])} |")
    a, b = values[chosen], values['M2']
    full = aggregate([r for r in rows if r['method'] == chosen and r['reference'] == 'M0'])
    p3_full = aggregate([r for r in rows if r['method'] == 'M1' and r['reference'] == 'M0'])
    macro = read_csv(out/'held_out_paired_uncertainty.csv')
    ci_lines = []
    for ref in ('M0', 'M1', 'M2'):
        r = next(r for r in macro if r['method'] == chosen and r['reference'] == ref)
        ci_lines.append(f"- M3−{ref}: {float(r['mean_hz'])/1e6:.3f} MHz, "
                        f"95% CI [{float(r['lower_hz'])/1e6:.3f}, "
                        f"{float(r['upper_hz'])/1e6:.3f}] MHz; "
                        f"{r['improved']}改善/{r['worsened']}恶化/{r['unchanged']}不变。")
    gate_table = '\n'.join(f"| {k} | {'PASS' if v else 'FAIL'} |"
                           for k, v in decision['gates'].items())
    validation = json.loads((out/'validation_summary.json').read_text())
    report = f"""# TASK-003：局部候选误修风险与保守拒绝审计

日期2026-10-15（Asia/Shanghai）。状态 **COMPLETE / RESEARCH_ONLY / MIXED**。
安全与收益联合目标 **NOT SUPPORTED**；真实数据评价 **SKIPPED**；AI **NOT JUSTIFIED / NOT RUN**。
branch={validation['branch']}；HEAD={validation['head']}。
本报告中的“正确/错误”均是合成频率真值下200MHz阈值，不是已验证的真实目标身份。

## 结论与代价

冻结M3={chosen}，CALIBRATION独立冻结3dB门槛；没有根据留出改规则。
留出M2→M3新增伤害 {b['harmed_frames']:.0f}→{a['harmed_frames']:.0f}，
减少{_pct(decision['harm_reduction'])}；纠正{b['corrected_frames']:.0f}→{a['corrected_frames']:.0f}，
保留{_pct(decision['benefit_retention'])}。损失{b['corrected_frames']-a['corrected_frames']:.0f}帧有益修复，
避免{b['harmed_frames']-a['harmed_frames']:.0f}帧新增伤害。
这未同时达到“减伤至少75%、保留至少70%纠正”等完整预注册门槛。
R1将全部提案拒绝、回到P3；其零新增伤害不构成算法成功。

预登记4dB对照在留出有1606纠正/76伤害，减伤85.900%、收益保留71.825%，
达到了两个主要比例目标，但仍未通过快变原正确保持和最差家族门槛。
它在校准阶段仅保留758/1329=57.035%收益，未被选中。
不得利用已查看的留出将4dB改称最终M3；这也说明操作点的分布稳定性不足。

## 数据、冻结与独立性

192条新time-voltage波形：48 TRAIN、48 CALIBRATION、96 HELD_OUT；
两profile成组，共384streams。12场景，每场景两种极性，每种4条留出，
每家族独立N=8。新seed与TASK001/002已登记seed无交集，电压hash逐流保存。
TASK001/002所有旧样本（包括旧held-out）只用于机制开发，未计入本轮独立N。
正常场景保留长正常区并置入短探针；持续错误及无目标场景另有短探针。
因此“每类同时包含机会与反例”是设计，不保证每类M2都能提出修复。
幅度比区间故意交叠，避免将历史有益/有害样本的幅度差直接编码为新标签。
简化包络、相干分量及噪声不是经过仪器校准的散斑/噪声统计。

actual voltage→原STFT→原Top20→冻结P3→冻结M2→R1/R2否决。
原源码/配置和统计程序在新数据前hash冻结，split末核验；
正式门槛、校准选择规则在留出前冻结。没有重训、扩大候选或全局动态规划。
R2_B4是预注册的第二门槛诊断，不得在看完留出后替换M3。
候选假设coverage=100%；经验证频率仍NaN。拒绝时保留P3作为假设，
并输出AMBIGUOUS_INTERVENTION，不能解释为P3已正确。

## Phase A：可观测风险是否存在

精确重放TASK002全部5条误修波形、7提案、151帧；M1/M2路径hash与旧CSV一致。
配对时长/实例成功对照及TASK001代表成功共16个有益提案、592帧纠正。
原支路在23个提案中均有持续谱支持，因此R1不能区分有益与有害替换。
历史有害提案幅度对比0.847–3.289dB，抽查成功4.455–6.937dB；
3dB在旧例截获101/151伤害且不损失抽查收益，仅构成开发线索。
新数据故意检验幅度对比重叠后是否仍有效。详见failure_mechanism_audit.md。

R1：原候选背景≥12dB占比≥80%，频率相邻步长≤200MHz的连续支持段中心跨度≥12.8ns。
R2：再要求原支路/提议支路幅度比绝对dB的中位数≤b，校准仅选3或4dB。
全提案否决，不逐帧挖洞；观察量不接受truth、component_id、family或harmed标签。
该证据可以提示“有另一个可信解释”，不能确定哪一条属于目标。

## 留出整体结果

以下纠正/伤害/precision以P3为参照。precision=corrected/全部有真值干预，
包含wrong→wrong；harm rate=harmed/相同分母。RMSE包含所有目标存在帧，
保留弱信号与混合快变窗，没有靠删帧提高准确率。

| 方法 | pooled RMSE/MHz | wrong fraction | corrected | harmed | precision | harm rate |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(main_table)}

全流程M3相对Strongest纠正{full['corrected_frames']:.0f}、伤害{full['harmed_frames']:.0f}；
P3自身相对Strongest伤害{p3_full['harmed_frames']:.0f}。仅拦截M2不能自动修复P3继承错误。
不能把相对P3的新增伤害当成全流程总伤害。两个参照均见baseline_comparison.csv。

96独立波形、两profile先合并SSE/帧数后计算波形RMSE，4000次paired bootstrap：
{chr(10).join(ci_lines)}
这些区间针对固定合成分布，不是仪器误差或真实场景风险率。

## 拒绝、漏检与收益损失

M3拒绝{risk_row['rejected']}/{risk_row['proposals']}提案
（{_pct(risk_row['rejection_rate'])}）。
有害提案{risk_row['harmful_proposals']}，涉及{risk_row['harmful_waveforms']}独立波形；
截获{risk_row['rejected_harmful_proposals']}，仍接受{risk_row['accepted_harmful_proposals']}。
有益提案{risk_row['beneficial_proposals']}，拒绝{risk_row['rejected_beneficial_proposals']}。
风险召回{_pct(risk_row['risk_recall'])}，非有害提案误报率{_pct(risk_row['false_positive_rate'])}。
混合提案可同时归入有益和有害，两profile提案不是独立样本。
所有提案及特征、拒绝状态见accepted_rejected_proposals.csv；所有M2新增受损帧
及M3是否阻断见harm_audit.csv。风险比率的波形cluster区间另存
risk_waveform_uncertainty.json，属事后描述性分析，不用于选择或gate。

## 正常、快变与家族

M3正常区绝对准确率{_pct(a['normal_truth_accuracy'])}，
P3原正确正常帧保持{_pct(a['normal_preservation'])}；
快变绝对准确率M2/M3={_pct(b['fast_truth_accuracy'])}/{_pct(a['fast_truth_accuracy'])}，
P3原正确快变保持M3={_pct(a['fast_preservation'])}。
保留错误基线不等于保护真值。profile_comparison.csv同时给出两个profile及两个参照。

| family（每类8波形） | M0 MHz | P3 MHz | M2 MHz | M3 MHz | corrected M2/M3 | harmed M2/M3 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(family_table)}

家族配对bootstrap区间在held_out_family_comparison.csv，每类仅8波形，分组结果
为描述性、未作多重比较发现声明。某类没有提案时不能声称该类风险已解决。

## 预注册门槛与真实数据

| 条件 | 留出结果 |
|---|---|
{gate_table}

校准本身未通过完整要求；无论留出个别指标改善，均不能进入真实行为评价。
本轮未运行真实STFT/修复，不使用ch3调参。真实准确率UNKNOWN，
不覆盖原速度、正式导出或GUI默认结果。

## H2：独立身份可辨识性对照

独立seed43088001生成单份电压；交换两分量的目标标签，电压及复数STFT逐字节相同。
两profile各35冲突帧，真值相差1.2GHz，任何确定性预测在两解释下完全相同，
不可能同时落入两个互不相交的±200MHz正确区间。结果已实际核验，
见identity_indistinguishability.json。重标记不增加独立样本N。

这是观测模型无外部身份约束时的标签置换对称性。局部相位或完整单通道波形
亦随观测保持不变；额外实验先验、已知反射界面或独立测量可打破对称性。
不是“R2分类失败所以物理不可辨识”，也不宣称真实PDV所有歧义均不可解决。

## 最终十问

1. 旧危险误修有可观察的内部支持和竞争支路；它们也出现在正确修复，非唯一标志。
2. 可识别的是竞争解释风险，不能仅由这些频谱/幅度特征认证目标身份；H2仅在明确模型成立。
3. M3确实减少部分新增伤害，幅度和保留收益已同时报告，完整安全目标未获支持。
4. 代价是拒绝正确修复，导致部分家族和整体RMSE相对M2退化，不能只报precision提高。
5. 相对P3及Strongest的平均表现见完整表和波形区间，不能以平均优势代替安全gate。
6. 部分真实下降/返回更受保护，但仍有接受的有害提案与P3继承错误，不能称已安全。
7. AI未运行。少量历史独立负例及缺少独立身份特征不支持现在训练灵活分类器。
8. 有。持续、相干、幅度近似的目标与非目标均能满足保护条件，安全与纠正收益冲突。
9. 不进入真实数据评价，SKIPPED。
10. 当前应停止将此风险规则用于自动激活；保留候选、风险标记和人工审查，
    并寻求外部身份依据。人工仅看同一观测也不保证解决真正的标签歧义。

## 测试、边界和复现

pytest=959 passed/12 failed，与TASK002失败名单完全一致；新增20项均通过。
Ruff通过；整个src strict mypy通过。扩大到全部历史scripts的额外strict检查因
pandas类型桩缺失及重复模块名失败，具体命令/日志见validation_summary.json。
没有安装依赖或为全绿恢复旧raw/artifact。git diff --check和新文件空白检查通过。
Production、旧Research、data/raw及既有源码/配置hash不变；没有commit/push/merge/promotion。
新增模块仅位于独立research目录，测试位于tests/unit。输出没有经过artifacts Junction。

主运行时间与增量成本见runtime_summary.json及各split_completed.json。
P3入口含共享诊断，计时有测试并行影响，不能解释成隔离microbenchmark；
风险增量不含已运行的P3/M2，须与前端及基线开销相加。峰值内存未测。

复现命令见REPRODUCIBILITY.md；主要数值均来自不可覆盖CSV与冻结配置。
报告与图是结果后渲染，不回写评估数据或阈值。完成后停止，不启动TASK004。
"""
    with (out/'final_research_report.md').open('x', encoding='utf-8') as f:
        f.write(report)
    # Figure contract: quantitative grid, show benefits lost and harms retained together.
    contract = dict(backend='Python/matplotlib', archetype='quantitative grid',
        claim='Risk veto trades fewer harmful interventions for lost beneficial repairs.',
        panels=['Corrected and harmed frame counts vs P3', 'Complete pooled RMSE',
                'Historical vs fresh amplitude overlap'],
        width_mm=183, formats=['PNG300dpi', 'PDF editable text', 'SVG editable text'],
        source_data=['baseline_comparison.csv', 'accepted_rejected_proposals.csv'],
        n='96 independent held-out waveforms; paired profiles not independent',
        uncertainty='Pooled counts/RMSE have no error bars; paired CIs are in report/CSV',
        journal_submission_claim=False, image_adjustment='No raw-image manipulation')
    write_json(out/'figure_contract.json', contract)
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Arial', 'DejaVu Sans'],
        'font.size': 8, 'pdf.fonttype': 42, 'svg.fonttype': 'none',
        'axes.spines.top': False, 'axes.spines.right': False, 'legend.frameon': False})
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), layout='constrained')
    labels = ['M2', 'M3', 'R1']
    xx = np.arange(3)
    axes[0].bar(xx-.17, [values[m]['corrected_frames'] for m in ('M2', chosen, 'R1')],
                .34, color='#4C78A8', label='Corrected')
    axes[0].bar(xx+.17, [values[m]['harmed_frames'] for m in ('M2', chosen, 'R1')],
                .34, color='#D17C59', label='Harmed')
    axes[0].set(xticks=xx, xticklabels=labels, ylabel='Frames relative to P3',
                title='a  Benefits and harms')
    axes[0].legend(fontsize=7)
    rmse = [values[m]['rmse_hz']/1e6 for m in ('M0', 'M1', 'M2', chosen)]
    axes[1].bar(['M0', 'P3', 'M2', 'M3'], rmse,
                color=['#A9AFB6', '#79828D', '#4C78A8', '#72A5AD'])
    for i, v in enumerate(rmse):
        axes[1].text(i, v+3, f'{v:.1f}', ha='center', fontsize=7)
    axes[1].set(ylabel='Pooled RMSE (MHz)', title='b  Complete trajectory')
    axes[1].set_ylim(0, max(rmse)*1.18)
    fig.suptitle('Independent held-out: 96 waveforms, two paired profiles', fontsize=9)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(out/f'01_safety_benefit.{ext}', dpi=300)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7.2, 3.3), layout='constrained')
    for harmed, y, label, color in ((False, 0, 'Beneficial; no harm', '#4C78A8'),
                                    (True, 1, 'Harmful proposal', '#D17C59')):
        ps = [r for r in selected_proposals if (int(r['harmed']) > 0) == harmed
              and (harmed or int(r['corrected']) > 0)]
        x = np.array([float(r['median_absolute_balance_db']) for r in ps])
        offsets = .13*np.sin(np.arange(len(ps))*2.4)
        ax.scatter(x, y+offsets, s=18, alpha=.7, color=color, label=f'{label} (n={len(ps)})')
    ax.axvline(frozen['maximum_balance_db'], color='#444444', ls='--', lw=1)
    ax.set(xlabel='Median absolute original/proposed amplitude contrast (dB)',
           yticks=[0, 1], yticklabels=['Beneficial', 'Harmful'],
           ylim=(-.45, 1.55), title='Proposal-level overlap: stronger support does not certify identity')
    ax.legend(loc='upper right', fontsize=7)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(out/f'02_risk_overlap.{ext}', dpi=300)
    plt.close(fig)
    # Paired visual counterexamples, selected before outcomes by context/instance.
    files = sorted(out.glob('example_*anchor_exchange*balanced.npz'))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.5), layout='constrained', sharey=True)
    for ax, path in zip(axes, files, strict=True):
        z = np.load(path)
        mag = z['magnitude']
        db = 20*np.log10(np.maximum(mag, 1e-12)/mag.max())
        ax.pcolormesh(z['time_s']*1e9, z['frequency_hz']/1e9, db,
                      shading='auto', cmap='Greys', vmin=-40, vmax=0, rasterized=True)
        ax.plot(z['time_s']*1e9, z['truth_hz']/1e9, color='#202020', lw=1.2, ls='--', label='Truth')
        ax.plot(z['time_s']*1e9, z['M2']/1e9, color='#D17C59', lw=1, label='M2')
        ax.plot(z['time_s']*1e9, z[chosen]/1e9, color='#4C78A8', lw=1, label='M3')
        ax.set(xlim=(210, 450), ylim=(1, 3.7), xlabel='Time (ns)',
               title='Counterexample' if 'harm_counterexample' in path.name else 'Repair opportunity')
    axes[0].set_ylabel('Frequency (GHz)')
    axes[0].legend(fontsize=7, loc='lower left')
    fig.suptitle('Anchor-exchange context: preselected held-out instance 0 / Balanced', fontsize=9)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(out/f'03_paired_examples.{ext}', dpi=300)
    plt.close(fig)
    write_json(out/'figure_data_notes.json', dict(
        figure3='Same -40 to0dB per-panel relative spectral display; no interpolation or local edits; x crop210–450ns; only preselected instance0, not performance evidence.',
        figure2='Deterministic display jitter only on categorical y, no feature modification.',
        source_family_table_rows=len(family_rows)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    deliver(args.output)


if __name__ == '__main__':
    main()
