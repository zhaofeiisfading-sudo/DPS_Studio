"""Render a source-grounded report from immutable TASK-025 tables."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from scripts.run_task025 import load_json


def percentage(value: float) -> str:
    return f'{100*value:.4f}%'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    frame = pd.read_csv(output / 'frame_detection_aggregates.csv')
    segment = pd.read_csv(output / 'segment_detection_aggregates.csv')
    candidate = pd.read_csv(output / 'candidate_recall_aggregates.csv')
    decision = load_json(output / 'phase_b_decision.json')
    thresholds = load_json(output / 'frozen_thresholds.json')
    validation = load_json(output / 'validation_summary.json')
    boundary = load_json(output / 'boundary_verification.json')
    if decision['passed']:
        raise RuntimeError('Phase C report required; early-stop template cannot claim completion')

    def row(stratum: str = 'target_present', detector: str = 'E1',
            mask: str = 'SUPPORTED_FRAME', dataset: str = 'ALL', family: str = 'ALL',
            aggregation: str = 'frame_pooled') -> Any:
        selected = frame[(frame.split == 'HELD_OUT') & (frame.detector == detector) &
            (frame['mask'] == mask) & (frame.stratum == stratum) & (frame.dataset == dataset) &
            (frame.family == family) & (frame.profile == 'ALL') & (frame.aggregation == aggregation)]
        return selected.iloc[0]

    def pair(stratum: str = 'target_present', detector: str = 'E1',
             mask: str = 'SUPPORTED_FRAME', dataset: str = 'ALL', family: str = 'ALL',
             reject: bool = False) -> str:
        result = []
        for aggregation in ('frame_pooled', 'waveform_macro'):
            entry = row(stratum, detector, mask, dataset, family, aggregation)
            value = float(entry.recall_or_activation)
            result.append(percentage(1-value if reject else value))
        return ' / '.join(result)

    def candidate_pair(split: str, dataset: str = 'CORE') -> str:
        selected = candidate[(candidate.split == split) & (candidate.dataset == dataset) &
                             (candidate.scope == 'all_target')].iloc[0]
        return (f'{percentage(selected.frame_pooled)} / {percentage(selected.waveform_macro)} '
                f'({int(selected.numerator)}/{int(selected.denominator)} frames)')

    def seg(metric: str, detector: str = 'E1') -> str:
        selected = segment[(segment.split == 'HELD_OUT') & (segment.detector == detector) &
            (segment.dataset == 'ALL') & (segment.family == 'ALL') &
            (segment.metric == metric)].iloc[0]
        if metric in ('detected', 'coverage_99', 'fully_covered'):
            return percentage(selected.segment_pooled)+' / '+percentage(selected.waveform_macro)
        return f'{selected.segment_pooled:.6g} / {selected.waveform_macro:.6g}'

    lines = [
        '# TASK-025 有效信息区间鲁棒性审计与门控可行性验证',
        '',
        '**状态：Phase B 未通过，按预注册 early-stop。没有运行 Phase C G0/G1，'
        '没有开展新的真实 34 streams / ch3 评价，没有调整冻结阈值。等待人工审计。**',
        '',
        '## 分层 verdict', '',
        '| 层级 | Verdict |', '|---|---|',
    ]
    names = ('Signal-support separability', 'Hard-negative robustness',
             'Informative interval detection', 'Engineering cost reduction',
             'Frozen-P3 performance preservation', 'Potential Production value')
    for label, value in zip(names, decision['verdicts'].values(), strict=True):
        lines.append(f'| {label} | {value} |')
    lines += [
        '', '## 事实边界与预注册', '',
        '开始前只读检查 Research：工作树 clean，branch=`codex/research_2/global-path-ridge`，'
        'HEAD=`7864f1a52711410fa029469e273b9359ae903c29`。Production/main '
        '`07a1e0f85f156225518b671a48d687bea94908e9` clean。frozen_manifest 的 status '
        '采集在创建本任务 protocol/seed 文件之后，因此其中列出的 task025 untracked 文件不是原有改动。',
        'TASK-024 实际 artifact 为 `task023h_raw_domain_evidence/20260913T132656Z`。'
        '已读其报告、验证摘要和最新 Obsidian 日志；该日志中的旧 Research HEAD 不替代当前 git。'
        '所有旧数据保持 LEGACY_DIAGNOSTIC，没有重命名、移动、覆盖或参与阈值选择。',
        'protocol.md、seed_registration.json、threshold_protocol.json 先于 benchmark；'
        'implementation_freeze.json 先于 calibration；frozen_thresholds.json 先于 held-out。'
        'evaluation_code_freeze.json 在 held-out 正式评价前记录汇总程序哈希。'
        '正式 held-out 只生成和评价一次；后续绘图、汇总仅消费已保存数组/计数。',
        '', '## 数据与独立单位', '',
        '128 fresh core 波形：原 generate_case 的 8 families × instances 8…23，只换 seed/ID/split。'
        '64 H0…H7 独立困难负样本、80 条10类困难正样本，均未替代或改变 core 分布。'
        '共272波形/544 profile streams：94波形 calibration、178波形 held-out。'
        '两 profile 为同一波形的重复测量，不当作独立实验。',
        '本文帧指标以 **frame-pooled / waveform-macro** 成对报告；macro 先在波形内合并两个 '
        'profile 的分子分母，再对有定义的波形取等权均值。分段指标为 segment-pooled / '
        'waveform-macro。完整分母、profile、dataset、family 及弱信号 focus 分层见 CSV。'
        '小压力集用于可行性筛查，不估计真实数据发生率；没有据此声称泛化到全部实验条件。',
        '', '## 数学、阈值与输出规则', '',
        r'直接复用 TASK-024：$z=\mathrm{hilbert}(V)$；局部原采样点上 '
        r'$E1=|\sum_n z_n e^{-i\phi_n}|^2/(N\sum_n|z_n|^2)$，'
        r'$\Delta\phi_n=\pi(f_n+f_{n-1})\Delta t_n$。'
        '本次逐帧模板频率恒为 strongest candidate 频率，使用原STFT物理窗。'
        '没有用 GT/正确 proposal/final corrected path/manual ch3 区间选择频率模板。',
        '完整 raw Hilbert、normalization、phase integration、bandwidth 和四分段定义完全未变。'
        'B0 为同次函数返回的 analytic RMS（V），B1 为已有 strongest peak_to_background_db（dB）。'
        '仅比较各自阈值，不叠加特征；本实验没有单独优化或测量 B0/B1 的实现成本。',
        '| Detector | 冻结阈值 | calibration target recall |', '|---|---:|---:|',
    ]
    for detector, info in thresholds.items():
        lines.append(f'| {detector} | {info["threshold"]:.12g} | '
                     f'{percentage(info["target_recall"])} |')
    lines += [
        '最高实际 calibration 观测值满足 pooled target recall≥99.5%；非有限值计漏检。'
        '共享阈值覆盖所有 dataset/profile。没有使用 held-out 或 ch3 调参。',
        '连续至少4个 SUPPORTED_FRAME 才生成区间，两侧只扩展原16 ns context；'
        '不新增 padding search。SEARCH_ACTIVE 是将来搜索许可掩码，**不是已经运行的搜索比例**。'
        '审计输出保留完整 strongest，100%有限覆盖；complete_output 边界函数经测试区间外逐点严格相等。'
        '这不代表已经验证实际G1执行结果，Phase C尚未运行。'
        'E1 质量标记/未定义证据与输出频率分开存储；未将质量诊断替代频率输出。',
        '冻结 STFT：Balanced 768/640/4096，High-time 512/384/4096；40 GHz原始采样。'
        'Top-K=20，200 MHz truth-near 判定。未运行或修改 P3/E4/acceptance、未计算新的 '
        'velocity correction 或 LiF 公式。内部单位为SI。',
        '', '## Candidate sufficiency', '',
        f'- Fresh core calibration：{candidate_pair("CALIBRATION")}',
        f'- Fresh core held-out：{candidate_pair("HELD_OUT")}',
        f'- Positive stress held-out：{candidate_pair("HELD_OUT", "POSITIVE_STRESS")}',
        '完整 target 和 strongest-error 子集见 candidate_recall_aggregates.csv。'
        '困难压力集若下降，说明在该压力分布下 CANDIDATE REPRESENTATION MAY STILL BE A BOTTLENECK；'
        '不据此改变 Top-K，也不把200 MHz recall 当作近频分量独立分辨率证明。',
        '', '## Primary held-out 指标与 baseline', '',
        '| Detector / mask | Target recall | LOW_INFORMATION rejection | Search-active fraction |',
        '|---|---:|---:|---:|',
    ]
    for detector in thresholds:
        for mask in ('SUPPORTED_FRAME', 'SEARCH_ACTIVE'):
            lines.append(f'| {detector} / {mask} | {pair(detector=detector, mask=mask)} | '
                f'{pair("low_information", detector, mask, reject=True)} | '
                f'{pair("all", detector, "SEARCH_ACTIVE")} |')
    lines += ['', '在各自99.5% calibration约束的冻结工作点，E1与谱支持的总体召回和排噪率接近：'
              f'E1 low-information rejection={pair("low_information", reject=True)}，'
              f'B1={pair("low_information", detector="B1_SPECTRAL", reject=True)}。'
              '这点排噪差别不足以支持E1的工程增益；RMS排噪较多，但held-out目标及衰落召回更差。'
              '不能只根据平均E1值或噪声分布分离判断工程可用性，也没有证明任一单统计量在所有工作点占优。',
              '模型解释（不是新实验结论）：E1归一化消除了绝对幅度信息，而strongest频率本身经过'
              '最大峰选择；噪声主导的窗口也能产生非零局部投影。为了保留极弱目标而降低阈值，'
              '会同时放行这些噪声窗口。固定context可补回漏检，也会扩大低信息区的搜索许可。'
              '本次选择的压力集只测试这种适用边界，不代表所有真实波形都处于这种噪声水平。',
              '', '## 困难正样本与边界', '',
              '| Stratum | E1 supported recall | E1 active recall | supported FNR |',
              '|---|---:|---:|---:|']
    for stratum in ('low_snr', 'temporary_fading', 'amplitude_fading', 'fast_descent',
                    'leading_edge', 'trailing_edge', 'branch_crossing', 'branch_merge',
                    'broadband_target', 'short_segment'):
        lines.append(f'| {stratum} | {pair(stratum)} | {pair(stratum, mask="SEARCH_ACTIVE")} | '
                     f'{pair(stratum, reject=True)} |')
    lines += [
        'fast-descent 仅算实际下降 ramp；temporary fading仅算 .05 V focus，'
        'amplitude fading为既有 amplitude_exchange focus及新持续幅度衰落区；'
        '这些分母不被容易的完整波形区域稀释。弱目标仍按合成真值 TARGET_PRESENT 标记。',
        f'独立 low_snr stress (-10/-5/0 dB) supported FNR：'
        f'{pair("target_present", dataset="POSITIVE_STRESS", family="low_snr", reject=True)}；'
        f'amplitude_fading 独立 focus FNR：'
        f'{pair("amplitude_fading", dataset="POSITIVE_STRESS", family="amplitude_fading", reject=True)}。',
        '', '## 分段检测', '',
        f'- 任意重叠 target-segment recall：{seg("detected")}',
        f'- ≥99%段内覆盖的真区段比例：{seg("coverage_99")}',
        f'- 完全覆盖真区段比例：{seg("fully_covered")}',
        f'- 每真区段 fragments：{seg("fragments")}',
        f'- 额外 fragments：{seg("excess_fragments")}',
        f'- 连续 leading/trailing boundary miss（s）：{seg("leading_missed_s")} / '
        f'{seg("trailing_missed_s")}',
        '分段有至少一帧被覆盖不是全段召回保证；完整段表保存逐段覆盖、碎裂及两端漏帧。'
        '短段的leading/trailing四帧可能重叠，boundary_missed_frames 为两个方向的计数和。',
        '', '## 困难负样本：结构与身份分开', '',
        '| Family | target-absent activation (all frames) | known-structure recall / low-info rejection |',
        '|---|---:|---:|',
    ]
    for i in range(8):
        family = f'H{i}'
        structure = (pair('low_information', dataset='HARD_NEGATIVE', family=family, reject=True)
                     if i < 2 else pair('structured', dataset='HARD_NEGATIVE', family=family))
        lines.append(f'| {family} | {pair("all", dataset="HARD_NEGATIVE", family=family)} | '
                     f'{structure} |')
    lines += [
        'H0/H1分别为纯噪声/宽带瞬态-only。H2…H7为stationary/chirped/intermittent/'
        'two-component/contaminated/pickup相干非目标。H4只在合成on-time评结构召回，off-time保持低信息。'
        '**E1 detects coherent structure, not target identity. E1检测的是相干结构，不是物理目标身份。** '
        'coherent non-target高分不自动判定结构检测失败；全部H标签仍TARGET_ABSENT。',
        '', '## Phase B stop 与未执行阶段', '',
        f'预注册共{len(pd.read_csv(output / "phase_b_success_gates.csv"))}项检查，'
        f'{len(decision["failed_checks"])}项未通过。每个profile和合并结果，'
        '同时检查pooled/macro和supported/active，完整失败列表见 phase_b_success_gates.csv。',
        '| Profile | Mask | Stratum | Aggregation | Observed | Required |',
        '|---|---|---|---|---:|---:|',
    ]
    for fail in decision['failed_checks']:
        lines.append(f'| {fail["profile"]} | {fail["mask"]} | {fail["stratum"]} | '
                     f'{fail["aggregation"]} | {percentage(fail["observed"])} | '
                     f'{percentage(fail["required"])} |')
    lines += [
        '没有进入G0/G1，proposal count、runtime reduction、RMSE/wrong保持、precision/harm、'
        'harmed frames状态分布全部NOT TESTED。不能从许可掩码推算实际成本收益，'
        '不能预设旧P3 harm主要来自低信息区。四个对应CSV保留表头，skipped_stages.json记录原因。',
        '真实34 streams、relatively-good风险和ch3双profile专项按early-stop跳过。'
        '图07/08是明确SKIPPED说明图，**没有伪造full spectrogram/overlay**；'
        '旧ch3结果不替代新阈值评价。用户“中间小段明显”的描述仅是无数值边界的人工参考，'
        '没有生成或使用人为ROI。没有真实准确率、target recall或branch correctness声明。',
        '', '## 最终18问逐项回答', '',
        f'1. Fresh Candidate Recall：core held-out {candidate_pair("HELD_OUT")}；'
        '与stress分开，不继续扩大K。',
        '2. 是否优于RMS/谱支持：见三detector冻结工作点表。E1没有通过完整可行性门槛，'
        '不能因噪声高低分差就宣称适合门控或有独立工程优势。',
        '3. 检测对象：coherent structure；target identity无观测标签依据。',
        f'4. 纯噪声H0 rejection：{pair("low_information", dataset="HARD_NEGATIVE", family="H0", reject=True)}。',
        f'5. Broadband-only H1 rejection：{pair("low_information", dataset="HARD_NEGATIVE", family="H1", reject=True)}。',
        '6. Coherent non-target：结构存在时可以高E1并激活；这是结构检测而非确认目标。',
        f'7. 独立low-SNR target FNR：{pair("target_present", dataset="POSITIVE_STRESS", family="low_snr", reject=True)}。',
        f'8. 独立amplitude-fading focus FNR：{pair("amplitude_fading", dataset="POSITIVE_STRESS", family="amplitude_fading", reject=True)}。',
        f'9. Fast-descent recall {pair("fast_descent")}；leading {pair("leading_edge")}，'
        f'trailing {pair("trailing_edge")}；是否超限按预注册失败表判定。',
        '10. Automatic interval的完整鲁棒性门槛未满足，NOT SUPPORTED。',
        '11. Proposal count降低：NOT TESTED，Phase C被禁止进入。',
        '12. Runtime降低：NOT TESTED，不能用active fraction代替计时。',
        '13. G0/G1 RMSE/wrong保持：NOT TESTED。',
        '14. Harm是否降低：NOT TESTED，没有测量新的G0 harm分布。',
        '15. ch3中间区域保留：NOT TESTED，真实评价被early-stop跳过。',
        '16. ch3首尾搜索减少：NOT TESTED。',
        '17. 本结果没有资格支持Production promotion experiment；RESEARCH_ONLY。',
        '18. 不优先工程化当前gate。下一轮人工审计后应优先研究弱信号/快速变化的'
        'representation与局部统计量适用边界，同时保留target identifiability约束；'
        '本轮没有依据支持新scorer或waveform denoising。未启动下一TASK。',
        '', '## 验证与不可变性', '',
        f'pytest：{validation["pytest_summary"]}；既有两个launcher失败单列，未修改launcher。'
        f'Ruff：{validation["ruff"]}；mypy --strict：{validation["mypy"]}；'
        f'git diff --check：{validation["git_diff_check"]}。',
        f'前后核对{boundary["preexisting_files_checked"]}个既有文件，'
        f'{boundary["raw_entries"]}条raw SHA-256全部一致；Production/main和Research HEAD不变。'
        '仅新增本TASK Research模块、脚本、测试、artifact及用户明确要求的轻量Obsidian日志。'
        '没有commit/push/merge/promotion。详见validation_summary.json与boundary_verification.json。',
        '本任务没有修改原始waveform、滤波、小波/Wiener降噪、平滑、插值、重采样或删点。'
        '**Informative gate只是决定何时运行复杂推断，不是waveform denoising。**',
        '', '## 可复现入口与交付物', '',
        '`scripts/freeze_task025.py`只创建新的预注册目录；`scripts/run_task025.py`按'
        '`calibration → held-out → evaluate`分阶段排他写入，拒绝覆盖一次性stage marker。'
        '`scripts/summarize_task025.py`汇总固定计数/绘图，`scripts/verify_task025.py`检查边界。'
        '复现必须使用新artifact目录，不得重跑或覆盖本次正式评价。',
        'waveforms/保留272条实际time-voltage/truth及参数，streams/保存544套最强轨迹、'
        'E1/RMS/谱支持、质量、标签和候选可用性；所有自动区间见automatic_intervals.csv。'
        'figures/提供4幅实测诊断图和4幅明确跳过说明图的PNG/SVG。',
    ]
    with (output / 'final_research_report.md').open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(lines)+'\n')
    print(output / 'final_research_report.md')


if __name__ == '__main__':
    main()
