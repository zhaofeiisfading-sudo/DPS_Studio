"""Close a negative Phase A honestly; never fabricate unexecuted G1-G3 results."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from matplotlib.figure import Figure

from scripts import run_task023f_proposal_recovery as r
from scripts.evaluate_task023f_frozen import load_searches
from scripts.finalize_task023f_recovery import read_csv
from scripts.run_task023g_retention_audit import PRIOR


def save_plots(output: Path, events: list[dict[str, Any]], frames: list[dict[str, Any]]) -> None:
    folder = output / 'figures'
    legacy = [row for row in frames if row['role'] == 'LEGACY_DIAGNOSTIC']
    counts = Counter(row['taxonomy'] for row in legacy)
    figure = Figure(figsize=(11, 5), layout='constrained')
    axis = figure.subplots()
    bars = axis.barh(list(counts), list(counts.values()), color='#4477aa')
    axis.bar_label(bars)
    axis.set(title='Prior F P3: all 1699 retention-loss frames; G audit only', xlabel='Affected frames')
    figure.savefig(folder / 'retention_taxonomy.png', dpi=150)
    selected = [row for row in events if row['role'] == 'LEGACY_DIAGNOSTIC']
    figure = Figure(figsize=(9, 4), layout='constrained')
    axis = figure.subplots()
    axis.hist([int(row['previous_survival_length']) + 1 for row in selected], bins=25, color='#228833')
    axis.set(title='Source-frame-correct cohort first loss (prior F P3)',
             xlabel='Search step from original anchor (one-based)', ylabel='Cohort extinction events')
    figure.savefig(folder / 'lineage_first_loss.png', dpi=150)
    example = sorted(selected, key=lambda row: (row['waveform'], row['profile'], int(row['first_loss_frame'])))[0]
    context = json.loads((PRIOR / 'streams' / (example['waveform'] + '_' + example['profile'] + '.json')).read_text())['context']
    search = load_searches(PRIOR, context)[example['window'], 'DIVERSITY_B8']
    lookup = {node.hypothesis_id: node for node in search.lineage}
    chain = []
    cursor = int(example['lineage_id'])
    while cursor:
        node = lookup[cursor]
        chain.append(dict(waveform=example['waveform'], profile=example['profile'], window=example['window'],
            lineage_id=node.hypothesis_id, parent_id=node.parent_id, frame=node.frame,
            search_step=node.offset + 1, score_rank=node.expansion_rank, score=node.score,
            cutoff=node.cutoff_score, family=node.family, retained=node.retained))
        cursor = node.parent_id
    chain.reverse()
    r.write_csv(output / 'beam_rank_trajectory_example.csv', chain)
    figure = Figure(figsize=(10, 4), layout='constrained')
    axis = figure.subplots()
    axis.plot([row['search_step'] for row in chain], [row['score_rank'] for row in chain], color='#4477aa')
    axis.axhline(8, color='#cc3311', linestyle='--', label='Raw cost rank 8; diversity can retain lower ranks')
    axis.set(title=f'{example["waveform"]}: fixed first audit example', xlabel='Search step', ylabel='Cumulative cost rank')
    axis.legend()
    figure.savefig(folder / 'beam_rank_trajectory.png', dpi=150)
    for filename, title in [('g0_g3_recall', 'G0-G3 fresh recall'), ('proposal_cost', 'G0-G3 proposal/runtime cost'),
                            ('automatic_interval_overlay', 'Automatic informative interval'),
                            ('ch3_balanced_full_record', 'ch3 Balanced interval evaluation'),
                            ('ch3_high_time_full_record', 'ch3 High-time interval evaluation')]:
        figure = Figure(figsize=(9, 3), layout='constrained')
        axis = figure.subplots()
        axis.axis('off')
        axis.text(.5, .65, title, ha='center', fontsize=16)
        axis.text(.5, .35, 'NOT RUN: Phase A early-stop\nNo G algorithm / fresh / real result is claimed.',
                  ha='center', fontsize=12)
        figure.savefig(folder / (filename + '_SKIPPED.png'), dpi=120)


def integrity(output: Path) -> dict[str, Any]:
    frozen = json.loads((output / 'frozen_manifest.json').read_text(encoding='utf-8'))
    rows = []
    for name, root in [('Research', r.ROOT), ('Production', r.ROOT.parent / 'DPS_Studio')]:
        for relative, digest in frozen['hashes'][name].items():
            current = r.sha256(root / relative)
            rows.append(dict(worktree=name, path=relative, sha256_before=digest, sha256_after=current,
                             unchanged=current == digest))
    r.write_csv(output / 'integrity_check.csv', rows)
    assert all(row['unchanged'] for row in rows), 'Existing Research/Production file changed'
    snapshot = {name: {command: subprocess.check_output(['git', *command.split()], cwd=root, text=True).strip()
                      for command in ('status --short --branch', 'rev-parse HEAD', 'diff --stat', 'diff --cached --stat')}
                for name, root in [('Research', r.ROOT), ('Production', r.ROOT.parent / 'DPS_Studio')]}
    assert snapshot['Production'] == frozen['git']['Production']
    assert snapshot['Research']['rev-parse HEAD'] == frozen['git']['Research']['rev-parse HEAD']
    assert snapshot['Research']['diff --stat'] == snapshot['Research']['diff --cached --stat'] == ''
    subprocess.run(['git', 'diff', '--check'], cwd=r.ROOT, check=True)
    r.write_json(output / 'repository_after.json', snapshot)
    return dict(all_preexisting_files_unchanged=True, research_raw_unchanged=True, production_unchanged=True,
                git_write_operations=False, raw_entries=sum('raw' in Path(row['path']).parts for row in rows))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    activation = json.loads((output / 'retention_activation.json').read_text(encoding='utf-8'))
    if activation['lookahead_enabled']:
        raise RuntimeError('Positive Phase A requires the next experimental phases, not this early-stop finalizer')
    frames, events = read_csv(output / 'retention_failure_taxonomy.csv'), read_csv(output / 'beam_lineage_audit.csv')
    dev, legacy = (activation['summaries'][key] for key in ('DEVELOPMENT', 'LEGACY_DIAGNOSTIC'))
    assert legacy['loss_frames'] == 1699
    skips = {name: 'PHASE_A_EARLY_STOP; no G method implemented/evaluated' for name in (
        'fresh_waveforms', 'G0_G1_G2_G3', 'informative_gate', 'final_selector', 'engineering_comparison',
        'real_34_streams', 'ch3', 'cross_scale', 'ai')}
    for filename, fields in [
        ('interval_gate_metrics.csv', ('waveform', 'profile', 'method', 'target_present_recall', 'noise_exclusion_rate')),
        ('proposal_recall_aggregates.csv', ('method', 'aggregation', 'candidate_recall', 'terminal_recall')),
        ('final_performance.csv', ('method', 'rmse_mhz', 'wrong_branch', 'coverage', 'precision', 'harm')),
        ('engineering_cost.csv', ('method', 'proposals', 'mean', 'p95', 'search_seconds', 'memory_high_water', 'search_active_fraction')),
        ('real_data_behavior.csv', ('stream', 'method', 'modification_fraction', 'search_active_fraction')),
        ('ch3_interval_audit.csv', ('profile', 'automatic_interval', 'manual_reference', 'modifications', 'status'))]:
        r.write_csv(output / filename, [], fields)
    r.write_json(output / 'skipped_stages.json', skips)
    save_plots(output, events, frames)
    checks = integrity(output)
    prior = json.loads((PRIOR / 'experiment_metadata.json').read_text(encoding='utf-8'))
    legacy_frames = [row for row in frames if row['role'] == 'LEGACY_DIAGNOSTIC']
    late = sum(row['pruned_after_source_frame'] == 'True' for row in legacy_frames)
    blank = sum(not row['original_first_loss_frame'] for row in legacy_frames)
    lines = ['# TASK-023G：Beam retention 审计与 early-stop', '',
        '**结论：单步前瞻的开发启用条件 NOT SUPPORTED；按 Phase 6 提前停止。**', '',
        '完成 Phase A、测试和原有文件完整性复核。没有实现新 beam/gate，没有生成 G fresh 波形，没有运行 G0–G3 或真实数据评价。F 的已看过数据全部只作开发或 legacy 诊断。', '',
        '## 分层结论', '',
        '| 层级 | 结论 | 解释 |', '|---|---|---|',
        '| Retention diagnosis | SUPPORTED | 已逐帧追踪既有 1699 个 terminal-missing 帧的 parent-ID 后代 |',
        '| One-Step Lookahead | NOT SUPPORTED（启用证据） | 开发集单步恢复比例未达预声明门槛；算法未实现，不声称实测算法性能失败 |',
        '| Informative Interval Gate | NOT EVALUATED | Phase A early-stop；不能声称 gate 有效或无效 |',
        '| Engineering cost | NOT EVALUATED | 审计探针耗时不是 G 算法搜索成本 |',
        '| Frozen selector | NOT EVALUATED | 没有新 G 最终轨迹，不能判断新 selector performance |', '',
        '## 单步恢复证据', '',
        '| 数据角色 | 首次丢失 cohort 事件 | 受影响错误帧 | 合格单步恢复事件 | 对应帧 | 事件比例 | 帧比例 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for label, value in [('开发：旧 E23 instances 0–7', dev), ('Legacy：原 F23 fresh', legacy)]:
        lines.append(f'| {label} | {value["events"]} | {value["loss_frames"]} | {value["one_step_recovery_events"]} | {value["one_step_recovery_frames"]} | {value["event_fraction"]:.3%} | {value["loss_frame_fraction"]:.3%} |')
    lines += ['', f'其中原 cost rank>8 且下一步恢复≤8的严格 score-dip 证据：开发 {dev["raw_cost_dip_events"]} 事件/{dev["raw_cost_dip_frames"]} 帧，legacy {legacy["raw_cost_dip_events"]} 事件/{legacy["raw_cost_dip_frames"]} 帧。其余单步可恢复事件可能原已在 raw score 前8，却被 diversity retention 拒绝，不能全部称为短暂评分下降。',
        '“大量”在审计前操作化为开发事件和受影响帧比例均≥20%；这不是用户指定的数值，未用于调参或最终频率选择。见 phase_a_protocol.md。新 G seeds 已登记，但 waveform 未生成。',
        '恢复探针允许一条被剪路径强制多走一帧，与保存的下一步 B8 累计 cost cutoff 比较；下一步需 truth-near 且满足冻结 E4 evidence。探针不进入 beam/terminal/output，也不是严格上界。', '',
        '## 1699 帧损失分类（原 F23，仅 legacy）', '',
        '| 分类 | 帧数 | 比例 |', '|---|---:|---:|']
    for key, count in legacy['frame_taxonomy'].items():
        lines.append(f'| {key} | {count} | {count / 1699:.3%} |')
    lines += ['', f'其中 {late} 帧的携带正确 source-frame 选择的后代在搜索顺序中晚于源帧才完全丢失；{blank} 帧在旧局部表没有 first_loss_frame。不能把旧的 1699 帧都解释成“在对应错误帧当场发生剪枝”。',
        'G 改为沿完整窗口追踪 source-frame-correct cohort。后续帧不施加新的标签条件，以对应原 frame-level terminal recall；它不等同于完整正确物理支路。各布尔机制字段、互斥 taxonomy、未决情况均保留，详见 cohort_audit_amendment.md。',
        'NO_VALID_DESCENDANT 表示无 truth-near 后继通过冻结 identity/local-support/broadband evidence；F 的扩展函数仍可能生成这些候选，不能称候选不存在或 beam 实现 bug。',
        'FAMILY_COLLISION 使用冻结 guard 下的单独分族反事实；DUPLICATE_OCCUPANCY 是 guard-eligible 路径与重复占位共存的证据，不能自动等同于净算法收益。PERSISTENT_SCORE_INFERIOR 仅为四步贪心强制标签探针持续落后，不能外推无限未来。', '',
        '## 结束时十项回答', '',
        f'1. 1699 帧主要分类为 {max(legacy["frame_taxonomy"], key=lambda key: legacy["frame_taxonomy"][key])}；完整拆分见上表。',
        '2. 只证明少数单步探针可恢复竞争力，未达到启动 lookahead 的开发门槛；没有正式算法恢复成绩。',
        '3. 原保存搜索为 P3 live B8，未使用更宽 beam 生成任何新输出。临时探针仅存在于 GT auditor。',
        '4. 自动有效信息区间尚未实现或验证，可靠性未知。',
        '5. 没有新 G proposal/runtime 比较，不能宣称成本改善。',
        '6. ch3 本轮未作 G 评价；没有自动中间区间或 manual reference 参与算法。对应图为明确标记的 skipped 页。',
        '7. G Terminal Proposal Recall 未测。历史 F P3=38.226%、Candidate=100% 是 legacy 指标，不能重标为 G fresh 成绩。',
        '8. 本轮定位旧 retention 损失，并未生成新 G remaining-missing 分解；F 的旧分解仅作上下文。',
        '9. 不能凭未通过的单步启用实验宣称 retention 已解决或 scorer 已成为唯一主要瓶颈；尚未证明完整正确 proposal 足够。',
        '10. 本轮不支持自动进入 TASK-023H；不启动跨尺度或 AI，等待人工审计。', '',
        '## 既有性能与边界', '',
        '旧 F P3（仅 legacy 背景）：RMSE 110.484 MHz，wrong 1.579%，precision 94.957%，harm 5.043%；proposal 约66×P0、search约6.28×P0。这些不是本次 G 性能。',
        f'前一任务总体结论为 {prior["verdict"]}，仍保留。原 F 对 ch3 的修改和 relatively-good 风险不因本轮审计而撤销。',
        '无目标帧不进入频率 RMSE 分母；本次无新的频率指标。测试仅覆盖已实现审计与冻结边界，未实现的 interval/coverage/lookahead 正式算法条目明确标记未测试。', '',
        '## 验证和完整性', '',
        '基线 pytest 738 passed、2 项既有 launcher failed；本次实际最终结果见 validation_summary.json。未修改 launcher 消除失败。',
        f'完整性：{json.dumps(checks, ensure_ascii=False)}。Research HEAD 91381f1，Production/main HEAD 07a1e0f；tracked/cached diff 空。新 Research 文件未跟踪，HEAD 不能代表全部实现。',
        '初次局部谱系假设失败日志保留；最终采用 cohort_audits，不删除或混入旧尝试。任务结束，不 commit/push/promotion，不启动 023H。']
    with (output / 'final_research_report.md').open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    r.write_json(output / 'metadata.json', dict(task='TASK-023G',status='COMPLETED_PROTOCOL_EARLY_STOP',
        verdict='LOOKAHEAD_ACTIVATION_NOT_SUPPORTED', activation=activation, integrity=checks,
        stages=skips, original_1699_audited=True, late_suffix_loss_frames=late,
        original_local_first_loss_missing_frames=blank, newly_generated_waveforms=0,
        fresh_seed_rule='2307000 + family_index*100 + instance', existing_f_reference=str(PRIOR)))


if __name__ == '__main__':
    main()
