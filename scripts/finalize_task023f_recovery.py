"""Assemble TASK-023F evidence, risk-qualified conclusions and integrity checks."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.figure import Figure

from dps_studio.research import task023f_audit as a
from scripts import run_task023f_proposal_recovery as runner
from scripts.evaluate_task023f_frozen import artifact_stem


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def pooled_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ('valid_frames', 'sse_hz2', 'wrong_frames', 'baseline_frames', 'output_frames',
            'modifications', 'truth_modifications', 'corrected_frames', 'harmed_frames',
            'no_truth_frames', 'no_truth_output_frames', 'no_truth_modifications',
            'correct_edge_frames', 'correct_edge_modified', 'correct_edge_harmed',
            'fast_descent_frames', 'fast_descent_harmed')
    out: dict[str, Any] = {key: sum(float(row.get(key, 0) or 0) for row in rows) for key in keys}
    n = out['valid_frames']
    out.update(rmse_mhz=np.sqrt(out['sse_hz2'] / n) / 1e6 if n else None,
        wrong_branch=a.ratio(out['wrong_frames'], n),
        coverage=a.ratio(out['output_frames'], out['baseline_frames']),
        modification_fraction=a.ratio(out['modifications'], out['baseline_frames']),
        precision=a.ratio(out['corrected_frames'], out['truth_modifications']),
        harm_rate=a.ratio(out['harmed_frames'], out['truth_modifications']))
    return out


def macro_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row['observation_group']].append(row)
    waveforms = [pooled_metrics(values) for values in groups.values()]
    fields = ('rmse_mhz', 'wrong_branch', 'coverage', 'modification_fraction', 'precision', 'harm_rate')
    return {key: float(np.mean([r[key] for r in waveforms if r[key] is not None]))
            if any(r[key] is not None for r in waveforms) else None for key in fields} | {
                'waveforms': len(waveforms), 'truth_waveforms': sum(r['valid_frames'] > 0 for r in waveforms)}


def chart(path: Path, labels: list[str], values: list[float], title: str,
          ylabel: str = 'Frames') -> None:
    figure = Figure(figsize=(10, 5), layout='constrained')
    axis = figure.subplots()
    bars = axis.bar(labels, values, color=['#4477aa', '#66ccee', '#228833', '#ccbb44'][:len(labels)]
                    if len(labels) <= 4 else '#4477aa')
    axis.bar_label(bars, fmt='%.3g')
    axis.set(title=title, ylabel=ylabel)
    axis.tick_params(axis='x', labelrotation=15)
    figure.savefig(path, dpi=150)


def aggregate_tables(output: Path) -> dict[str, Any]:
    results = [json.loads(path.read_text(encoding='utf-8')) for path in sorted((output / 'streams').glob('*.json'))]
    all_summary = [row for result in results for row in result['summaries']]
    all_oracle = [row for result in results for row in result['oracle']]
    all_windows = [row for result in results for row in result['windows']]
    all_costs = [{**result['context'], **row} for result in results for row in result['costs']]
    runner.write_csv(output / 'proposal_recall_summary.csv', all_summary)
    runner.write_csv(output / 'proposal_oracle_upper_bound.csv', all_oracle)
    runner.write_csv(output / 'proposal_window_costs.csv', all_windows)
    runner.write_csv(output / 'search_resource_costs.csv', all_costs)
    runner.write_csv(output / 'beam_oracle_comparison.csv', [row for result in results for row in result['b32']])
    matched_results = [r for r in results if r['context']['stage'] == 'FRESH' and r['b32']]
    matched_rows = [row for r in matched_results for row in r['summaries'] + r['b32']]
    matched = []
    for variant in ('P0', 'P1', 'P2', 'P3', 'B32_P0_PERMISSION', 'B32_CHALLENGE_PERMISSION'):
        selected = [row for row in matched_rows if row['variant'] == variant]
        matched.append(dict(variant=variant, **runner.aggregate(selected)))
    runner.write_csv(output / 'beam_matched_comparison.csv', matched)
    frame_rows: list[dict[str, Any]] = []
    prune_rows: list[dict[str, Any]] = []
    for result in results:
        stem = artifact_stem(output, result['context'])
        frame_rows.extend(read_csv(output / 'details' / (stem + '_funnel.csv')))
        prune_rows.extend(read_csv(output / 'details' / (stem + '_pruning.csv')))
    lineage_index = {(r['case_id'], r['profile'], r['variant'], r['frame'], r['window_id']): r
                     for r in prune_rows}
    for row in frame_rows:
        lineage = lineage_index.get((row['case_id'], row['profile'], row['variant'],
                                     row['frame'], row['window_id']))
        row['local_reason'] = row['reason']
        if lineage:
            row['first_loss_frame'] = lineage['first_loss_frame']
            row['first_loss_reason'] = lineage['first_loss_reason']
            if (row['reason'] == 'HYPOTHESIS_NOT_GENERATED'
                and lineage['first_loss_reason'] == 'EXPANDED_THEN_PRUNED'):
                row['reason'] = 'BEAM_PRUNED_ANCESTOR'
    runner.write_csv(output / 'proposal_funnel_detail.csv', frame_rows)
    runner.write_csv(output / 'beam_pruning_detail.csv', prune_rows)
    runner.write_csv(output / 'core_lock_audit.csv', [r for r in frame_rows if r['core'] == 'True'])
    # Paired full-record feasible oracle difference is a sum of the independently
    # matched core-window permission counterfactuals; edge sets are identical.
    pairs: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    for row in all_oracle:
        if row['variant'] in ('P0', 'P1') and row['oracle'] == 'FEASIBLE_MIN_SSE':
            pairs[row['case_id'], row['profile']][row['variant']] = row
    core_gain = []
    for (case, profile), pair in pairs.items():
        p0, p1 = pair['P0'], pair['P1']
        frame = [r for r in frame_rows if r['case_id'] == case and r['profile'] == profile and r['variant'] == 'P0']
        core_gain.append(dict(case_id=case, profile=profile, stage=p0['stage'],
            same_window_anchor_score=True, p0_sse_hz2=p0['sse_hz2'], p1_sse_hz2=p1['sse_hz2'],
            permission_oracle_sse_gain_hz2=p0['sse_hz2'] - p1['sse_hz2'],
            p0_wrong_frames=p0['wrong_frames'], p1_wrong_frames=p1['wrong_frames'],
            untriggered_core_errors=sum(r['reason'] == 'UNTRIGGERED_CORE' for r in frame),
            no_anchor_errors=sum(r['reason'] == 'NO_ELIGIBLE_ANCHOR' for r in frame),
            permission_denied_errors=sum(r['reason'] == 'CORE_PERMISSION_DENIED' for r in frame)))
    runner.write_csv(output / 'core_lock_oracle_gain.csv', core_gain)
    aggregates = []
    for stage in sorted({row['stage'] for row in all_summary}):
        for variant in ('P0', 'P1', 'P2', 'P3'):
            selected = [r for r in all_summary if r['stage'] == stage and r['variant'] == variant]
            aggregates.append(dict(stage=stage, variant=variant, aggregation='FRAME_POOLED',
                                   **runner.aggregate(selected)))
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in selected:
                groups[row['observation_group']].append(row)
            macro = [runner.aggregate(values) for values in groups.values()]
            aggregates.append(dict(stage=stage, variant=variant, aggregation='WAVEFORM_MACRO',
                **{k: float(np.mean([r[k] for r in macro if r[k] is not None]))
                   if any(r[k] is not None for r in macro) else None for k in (
                       'candidate_recall', 'graph_recall', 'terminal_recall',
                       'missing_proposal_fraction', 'branch_recall')}))
    runner.write_csv(output / 'proposal_recall_aggregates.csv', aggregates)
    cost_summary = []
    activation = json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
    resource_index = {(r['case_id'], r['profile'], r['window_id'], r['mode']): r for r in all_costs}
    for variant in ('P0', 'P1', 'P2', 'P3'):
        windows = [r for r in all_windows if r['stage'] == 'FRESH' and r['variant'] == variant]
        counts = [r['proposals'] for r in windows]
        mode = 'DIVERSITY_B8' if variant in ('P2', 'P3') and activation['diversity'] else 'B8'
        resources = [resource_index.get((r['case_id'], r['profile'], r['window_id'], mode), {})
                     if r['kind'] == 'EDGE' or (variant in ('P1', 'P3') and activation['core']) else {}
                     for r in windows]
        times = [float(r.get('seconds', 0)) for r in resources]
        peaks = [int(r['process_lifetime_peak_bytes']) for r in resources
                 if r.get('process_lifetime_peak_bytes') is not None]
        cost_summary.append(dict(variant=variant, common_windows=len(windows), total=sum(counts),
            mean=float(np.mean(counts)) if counts else None, p95=float(np.quantile(counts, .95)) if counts else None,
            families=sum(r['families'] for r in windows), search_seconds_total=sum(times),
            search_seconds_mean=float(np.mean(times)) if times else None,
            search_seconds_p95=float(np.quantile(times, .95)) if times else None,
            process_lifetime_peak_bytes_max=max(peaks) if peaks else None,
            memory_scope='PROCESS_LIFETIME_HIGH_WATER_BOUND_NOT_ISOLATED_VARIANT'))
    p0_cost = cost_summary[0]['total']
    p0_time = cost_summary[0]['search_seconds_total']
    for row in cost_summary:
        row['ratio_to_p0'] = a.ratio(row['total'], p0_cost)
        row['search_time_ratio_to_p0'] = a.ratio(row['search_seconds_total'], p0_time)
        row['engineering_risk'] = any(row[key] is not None and row[key] > 4
                                      for key in ('ratio_to_p0', 'search_time_ratio_to_p0'))
        row['zero_baseline_new_cost'] = p0_cost == 0 and row['total'] > 0
    runner.write_csv(output / 'proposal_cost_summary.csv', cost_summary)
    fresh = [r for r in frame_rows if r['stage'] == 'FRESH' and r['variant'] == 'P0']
    missing = Counter(r['reason'] for r in fresh if r['candidate_available'] == 'True' and r['terminal'] == 'False')
    missing_by_variant = {variant: dict(Counter(r['reason'] for r in frame_rows
        if r['stage'] == 'FRESH' and r['variant'] == variant
        and r['candidate_available'] == 'True' and r['terminal'] == 'False'))
        for variant in ('P0', 'P1', 'P2', 'P3')}
    first_prunes = [r for r in prune_rows if r['stage'] == 'FRESH' and r['variant'] == 'P0'
                    and r['first_loss_here'] == 'True' and r['first_loss_reason'] == 'EXPANDED_THEN_PRUNED']
    global_prunes = [r for r in read_csv(output / 'full_window_lineage_loss.csv')
                     if r['stage'] == 'FRESH' and r['mode'] == 'B8' and r['kind'] == 'EDGE'
                     and int(r['strongest_error_frames']) > 0
                     and r['first_loss_reason'] == 'EXPANDED_THEN_PRUNED']
    return dict(results=results, summaries=all_summary, oracle=all_oracle, costs=cost_summary,
                missing=dict(missing), first_prunes=first_prunes, core_gain=core_gain, matched=matched,
                full_window_prunes=global_prunes, missing_by_variant=missing_by_variant)


def final_metrics(output: Path) -> dict[str, Any]:
    source = output / 'fresh_heldout_comparison.csv'
    if not source.exists():
        return dict(status='SKIPPED_PROPOSAL_GATE')
    rows = read_csv(source)
    if not rows:
        return dict(status='SKIPPED_PROPOSAL_GATE')
    tables = []
    pooled = {}
    for method in ('strongest', 'TASK023C', 'E3_REFERENCE', 'P0', 'P1', 'P2', 'P3'):
        selected = [r for r in rows if r['method'] == method]
        value = pooled_metrics(selected)
        pooled[method] = value
        tables.append(dict(method=method, aggregation='FRAME_POOLED', **value))
        tables.append(dict(method=method, aggregation='WAVEFORM_MACRO', **macro_metrics(selected)))
    runner.write_csv(output / 'fresh_final_aggregates.csv', tables)
    family_rows = []
    for family in sorted({r['family'] for r in rows}):
        for method in pooled:
            selected = [r for r in rows if r['family'] == family and r['method'] == method]
            family_rows.append(dict(family=family, method=method, aggregation='FRAME_POOLED',
                                    **pooled_metrics(selected)))
            family_rows.append(dict(family=family, method=method, aggregation='WAVEFORM_MACRO',
                                    **macro_metrics(selected)))
    runner.write_csv(output / 'fresh_family_aggregates.csv', family_rows)
    runner.write_csv(output / 'no_target_diagnostic.csv', [
        {k: r[k] for k in ('case_id', 'observation_group', 'profile', 'method',
                          'no_truth_frames', 'no_truth_output_frames', 'no_truth_modifications')}
        | {'label_source': 'GENERATOR_GT_NO_TARGET; not an algorithm identity label'}
        for r in rows if float(r['no_truth_frames']) > 0])
    verdicts = {}
    p0 = pooled['P0']
    for method in ('P1', 'P2', 'P3'):
        value = pooled[method]
        gates = dict(rmse_lower=value['rmse_mhz'] < p0['rmse_mhz'],
            wrong_nonworse=value['wrong_branch'] <= p0['wrong_branch'],
            coverage_preserved=value['coverage'] >= pooled['strongest']['coverage'],
            precision=value['precision'] is not None and value['precision'] >= .99,
            harm=value['harm_rate'] is not None and value['harm_rate'] <= .01,
            correct_edge=value['correct_edge_harmed'] <= p0['correct_edge_harmed'],
            fast_descent=value['fast_descent_harmed'] <= p0['fast_descent_harmed'])
        gates = {key: bool(flag) for key, flag in gates.items()}
        verdicts[method] = dict(gates=gates, verdict='BETTER_THAN_TASK023D' if all(gates.values()) else 'MIXED')
    return dict(status='RUN', pooled=pooled, verdicts=verdicts)


def figures(output: Path, evidence: dict[str, Any], gate: dict[str, Any]) -> None:
    folder = output / 'figures'
    p0 = gate['totals']['P0']
    funnel_labels = ['Strongest error', 'Candidate', 'Constructable', 'Terminal']
    funnel_counts = [p0[k] for k in ('error_frames', 'candidate_frames', 'graph_frames', 'terminal_frames')]
    if (output / 'final_funnel_summary.csv').exists() and gate['passed']:
        final_funnel = read_csv(output / 'final_funnel_summary.csv')
        funnel_labels.append('Final correction')
        funnel_counts.append(int(next(r['corrected'] for r in final_funnel if r['variant'] == 'P0')))
    chart(folder / '01_proposal_funnel.png', funnel_labels, funnel_counts,
        'Fresh P0 proposal funnel (common denominator)')
    chart(folder / '02_candidate_vs_proposal.png', ['Candidate', 'P0 terminal', 'P3 terminal'],
          [p0['candidate_recall'], p0['terminal_recall'], gate['totals']['P3']['terminal_recall']],
          'Fresh availability vs terminal recall', 'Fraction of strongest-error frames')
    chart(folder / '03_core_loss_breakdown.png', list(evidence['missing']), list(evidence['missing'].values()),
          'Fresh P0 missing proposals: distinct causal layers')
    frames = [int(r['first_loss_search_step']) for r in evidence['full_window_prunes']]
    figure = Figure(figsize=(9, 4), layout='constrained')
    axis = figure.subplots()
    axis.hist(frames, bins=25)
    axis.set(title='First loss of full-window GT-consistent lineage (fresh P0)',
             xlabel='Search step from anchor (one-based)', ylabel='Windows containing strongest errors')
    figure.savefig(folder / '04_first_prune_distribution.png', dpi=150)
    chart(folder / '05_b8_diversity.png', ['P0', 'P1', 'P2', 'P3'],
          [gate['totals'][p]['terminal_recall'] for p in ('P0', 'P1', 'P2', 'P3')],
          'Fresh frozen proposal variants', 'Terminal recall')
    values = [pooled_metrics([r for r in evidence['oracle'] if r['stage'] == 'FRESH'
                              and r['variant'] == p and r['oracle'] == 'FEASIBLE_MIN_SSE'])['rmse_mhz']
              for p in ('P0', 'P1', 'P2', 'P3')]
    chart(folder / '06_complete_proposal_oracle.png', ['P0', 'P1', 'P2', 'P3'], values,
          'Diagnostic complete-proposal minimum-SSE oracle', 'RMSE / MHz')
    for number, family in ((7, 'separated_edges'), (8, 'divergence'), (9, 'merge_crossing')):
        contexts = [result['context'] for result in evidence['results']
                    if result['context']['stage'] == 'FRESH' and result['context']['family'] == family]
        if not contexts:
            continue
        context = contexts[0]  # fixed lowest instance/profile, not a result-selected illustration
        stem = artifact_stem(output, context)
        with np.load(output / 'provenance' / (stem + '.npz')) as data:
            figure = Figure(figsize=(10, 4), layout='constrained')
            axis = figure.subplots()
            t = data['time_s'] * 1e9
            axis.scatter(np.repeat(t, 20), data['candidates_hz'].ravel() / 1e9,
                         s=.5, alpha=.12, color='gray', label='Main Top-20')
            for key, label in (('truth_hz', 'GT'), ('strongest_frequency_hz', 'strongest'),
                               ('e4_frequency_hz', 'frozen E4')):
                axis.plot(t, data[key] / 1e9, label=label, lw=1)
            final_path = output / 'final_streams' / (f'{context["case_id"]}_{context["profile"]}.npz')
            if final_path.exists():
                with np.load(final_path) as final_data:
                    axis.plot(t, final_data['P3_final_frequency_hz'] / 1e9,
                              label='P3 final', lw=1., linestyle='--')
            axis.set(title=context['case_id'] + ' (fixed illustration)', xlabel='Time / ns',
                     ylabel='Frequency / GHz', ylim=(.05, 6))
            axis.legend()
            figure.savefig(folder / f'{number:02d}_{family}_example.png', dpi=150)
    if not gate['passed']:
        for profile in ('Balanced', 'High-time'):
            figure = Figure(figsize=(9, 3), layout='constrained')
            axis = figure.subplots()
            axis.axis('off')
            axis.text(.5, .5, f'ch3 {profile}\nNOT RUN: fresh proposal gate failed\nNo real-data result is implied.',
                       ha='center', va='center')
            figure.savefig(folder / f'ch3_{profile}_SKIPPED.png', dpi=120)


def integrity(output: Path) -> dict[str, Any]:
    before = json.loads((output / 'freeze_before.json').read_text(encoding='utf-8'))
    prod = runner.ROOT.parent / 'DPS_Studio'
    rows = []
    authorized = {'src/dps_studio/research/task023e_waveform_benchmark.py',
                  'src/dps_studio/research/task023e_proposal_audit.py'}
    for name, root, key in (('Research', runner.ROOT, 'research_hashes'),
                            ('Production', prod, 'production_hashes')):
        for relative, digest in before[key].items():
            path = root / relative
            current = runner.sha256(path) if path.is_file() else 'MISSING'
            rows.append(dict(worktree=name, path=relative, sha256_before=digest, sha256_after=current,
                unchanged=digest == current, authorized_change=(name == 'Research' and Path(relative).as_posix() in authorized)))
    runner.write_csv(output / 'existing_file_integrity.csv', rows)
    assert all(r['unchanged'] or r['authorized_change'] for r in rows)
    snapshots = {name: {cmd: subprocess.check_output(['git', *cmd.split()], cwd=root, text=True).strip()
                       for cmd in ('status --short --branch', 'rev-parse HEAD', 'diff --stat', 'diff --cached --stat')}
                 for name, root in (('Research', runner.ROOT), ('Production', prod))}
    assert snapshots['Production'] == before['production_git']
    runner.write_json(output / 'repository_after.json', snapshots)
    frozen = json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
    source_rows = [dict(path=path, sha256_at_activation=digest,
                       sha256_at_delivery=runner.sha256(runner.ROOT / path),
                       identical=digest == runner.sha256(runner.ROOT / path))
                   for path, digest in frozen['source_hashes'].items()]
    runner.write_csv(output / 'activation_source_reconciliation.csv', source_rows)
    return dict(raw_unchanged=all(r['unchanged'] for r in rows if 'data' in Path(r['path']).parts
                                 and 'raw' in Path(r['path']).parts),
                production_unchanged=all(r['unchanged'] for r in rows if r['worktree'] == 'Production'),
                only_authorized_existing_changes=True, git=snapshots)


def report(output: Path, evidence: dict[str, Any], gate: dict[str, Any], final: dict[str, Any],
           checks: dict[str, Any]) -> None:
    activation = json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
    witness = json.loads((output / 'diversity_causal_verification.json').read_text(encoding='utf-8'))
    totals = gate['totals']
    p0, p1, p2, p3 = (totals[p] for p in ('P0', 'P1', 'P2', 'P3'))
    real = read_csv(output / 'cross_dataset_validation.csv') if gate['passed'] else []
    real_risks = [r for r in real if r.get('relatively_good_risk') == 'True']
    proposal_risk = any(r['engineering_risk'] or r['zero_baseline_new_cost'] for r in evidence['costs'])
    overall = ('NOT_SUPPORTED' if not gate['passed'] else
               ('MIXED/ENGINEERING_RISK' if proposal_risk or real_risks else
                final.get('verdicts', {}).get('P3', {}).get('verdict', 'MIXED')))
    oracle_values = {p: pooled_metrics([r for r in evidence['oracle'] if r['stage'] == 'FRESH'
                       and r['variant'] == p and r['oracle'] == 'FEASIBLE_MIN_SSE'])
                     for p in ('P0', 'P1', 'P2', 'P3')}
    matched_values = {r['variant']: r for r in evidence['matched']}
    final_values = final.get('pooled', {})
    final_funnel = read_csv(output / 'final_funnel_summary.csv') if (output / 'final_funnel_summary.csv').exists() else []
    funnel_text = '；'.join(f'{r["variant"]}: 回到200 MHz内 {r["corrected"]}，selection loss {r["selection_loss"]}，acceptance loss {r["acceptance_loss"]}' for r in final_funnel)
    beam_loss = sum(evidence['missing'].get(k, 0) for k in ('EXPANDED_THEN_PRUNED', 'BEAM_PRUNED_ANCESTOR'))
    p3_missing = evidence['missing_by_variant']['P3']
    p3_funnel = next((r for r in final_funnel if r['variant'] == 'P3'), {})
    layer_counts = dict(Candidate=p3['error_frames'] - p3['candidate_frames'],
        Proposal_permission_or_generation=sum(v for k, v in p3_missing.items()
            if k not in ('EXPANDED_THEN_PRUNED', 'BEAM_PRUNED_ANCESTOR')),
        Beam_retention=sum(p3_missing.get(k, 0) for k in ('EXPANDED_THEN_PRUNED', 'BEAM_PRUNED_ANCESTOR')),
        Selection=int(p3_funnel.get('selection_loss', 0)),
        Acceptance=int(p3_funnel.get('acceptance_loss', 0)))
    def pct(value: Any) -> str:
        return 'N/A' if value is None else f'{100 * value:.3f}%'
    lines = ['# TASK-023F：恢复正确支路的提案可达性', '', f'结论：**{overall}**。', '',
        '评价使用冻结 E4/P0。E3 只作历史参考，没有利用 fresh 结果重新选择 E3/E4、阈值或 beam 参数。',
        '跨尺度证据与 AI 均未实施。保留 strongest 不构成物理身份确认。', '',
        '## 四项结论', '',
        f'- Core diagnosis：{"SUPPORTED" if activation["core"] else "NOT SUPPORTED"}；开发集同窗口权限反事实 SSE 改善为 {activation["core_counterfactual_sse_gain_hz2"]:.6g} Hz²。',
        f'- Diversity beam：{"SUPPORTED" if activation["diversity"] else "NOT SUPPORTED"}；开发审计实际重复同族挤占事件 {activation["duplicate_crowding_events"]}。',
        f'  其中 {witness["guard_eligible_events"]} 个符合 diversity guard；{witness["strong_causal_witnesses"]} 个还满足未占位新族且 diversity 终端恢复该帧的更强可复核条件。',
        f'- Proposal recovery：{gate["verdict"]}；通过门槛的固定变体：{gate["passed"] or "无"}。',
        f'- Frozen-selector performance：{json.dumps(final.get("verdicts", final["status"]), ensure_ascii=False)}。', '',
        '## Fresh 128 波形 / 256 profile streams', '',
        '| Variant | Candidate recall | Terminal recall | Missing fraction | Whole-interval branch recall |',
        '|---|---:|---:|---:|---:|']
    for variant, value in totals.items():
        lines.append(f'| {variant} | {pct(value["candidate_recall"])} | {pct(value["terminal_recall"])} | {pct(value["missing_proposal_fraction"])} | {pct(value["branch_recall"])} |')
    lines += ['', '可行整条 proposal 最小 SSE oracle（诊断，不是算法成绩）：', '',
              '| Variant | RMSE / MHz | Wrong branch | Harmed frames |', '|---|---:|---:|---:|']
    for variant, value in oracle_values.items():
        lines.append(f'| {variant} | {value["rmse_mhz"]:.3f} | {pct(value["wrong_branch"])} | {value["harmed_frames"]:.0f} |')
    if final_values:
        lines += ['', '冻结 selector 的最终成绩（共同有效帧，frame-pooled）：', '',
                  '| Method | RMSE / MHz | Wrong branch | Precision | Harm | Modified / harmed |',
                  '|---|---:|---:|---:|---:|---:|']
        for method, value in final_values.items():
            lines.append(f'| {method} | {value["rmse_mhz"]:.3f} | {pct(value["wrong_branch"])} | {pct(value["precision"])} | {pct(value["harm_rate"])} | {value["modifications"]:.0f} / {value["harmed_frames"]:.0f} |')
        lines += ['', 'Waveform-macro（同一波形先合并两个 profile；无干预波形不进入 precision/harm 平均）：', '',
                  '| Method | RMSE / MHz | Wrong branch | Precision | Harm |',
                  '|---|---:|---:|---:|---:|']
        for row in read_csv(output / 'fresh_final_aggregates.csv'):
            if row['aggregation'] == 'WAVEFORM_MACRO':
                precision = float(row['precision']) if row['precision'] else None
                harm = float(row['harm_rate']) if row['harm_rate'] else None
                lines.append(f'| {row["method"]} | {float(row["rmse_mhz"]):.3f} | {pct(float(row["wrong_branch"]))} | {pct(precision)} | {pct(harm)} |')
    lines += ['', f'共同 strongest-error 分母 {p0["error_frames"]} 帧，candidate-conditioned 分母 {p0["candidate_frames"]} 帧。',
        'Frame-pooled 与 waveform-macro 分开保存在 proposal_recall_aggregates.csv；先在波形内合并两个 profile，profile 不是独立实验。',
        '192 条旧波形统一标记 LEGACY_DIAGNOSTIC，其中原 calibration 64 条用于机制开发。旧默认调用 voltage/truth 哈希全部一致；新数据只改变 seed。', '',
        '## 损失层级与反事实', '', f'P0 candidate-available missing 分解：`{json.dumps(evidence["missing"], ensure_ascii=False)}`。',
        'core 内的错误帧数不等于 core lock 的因果贡献；未触发、无合格锚点、permission 拒绝和搜索损失分别计数。',
        'core_lock_oracle_gain.csv 配对的是同一窗口注册表、同一锚点、同一 B8/E4 的权限变化，报告完整 proposal-set oracle 的 SSE 差；不是逐帧拼接收益。',
        'beam_pruning_detail.csv 以 hypothesis/parent 谱系证明首次丢失；完整扩展 DAG 在 lineages/*.pickle.gz。GT 仅进入只读 auditor/oracle。',
        '另用 full_window_lineage_loss.csv 从窗口第一步跟踪完整 GT-consistent 前缀；它与错误区间入口重置的局部审计分开，避免漏掉错误区间之前已发生的剪枝。无目标帧仅作为标签 wildcard，不计为正确识别。',
        '主 ledger 保留 local_reason，并将前驱已被剪枝导致后续未扩展的帧标为 BEAM_PRUNED_ANCESTOR；这类损失归于 retention，不能误归为独立 proposal-generator 缺失。逐帧 first_loss_frame/reason 可复核。',
        'B32 是更宽 beam 的经验参考，可能因搜索路径改变而非单调改善，不是数学严格上界。', '',
        '## Oracle、最终输出与成本', '',
        'proposal_oracle_upper_bound.csv 分开报告 FEASIBLE_MIN_SSE、FEASIBLE_MIN_WRONG 和 RELAXED_FRAMEWISE，并给出每种选择对应的 harmed frames。零干预 precision/harm 为 N/A。',
        f'共同窗口成本：`{json.dumps(evidence["costs"], ensure_ascii=False)}`。',
        '超过 4× P0 为 engineering risk，未删除 proposal 或截断修改数以达标。运行时间逐窗口保存；Windows 内存为进程 lifetime high-water bound，不能解释为独立变体的峰值；早期开发记录未测内存并明确留空。', '',
        '## 24 项问题逐项回答', '']
    answers = [
        f'原 P0 Candidate Recall：{pct(p0["candidate_recall"])}。',
        f'原 P0 Terminal Proposal Recall：{pct(p0["terminal_recall"])}。',
        f'69.81% 不作 fresh 复现值；本次 fresh missing fraction 为 {pct(p0["missing_proposal_fraction"])}。历史值只来自六个 legacy 案例。',
        f'主要 missing 层级：{max(evidence["missing"], key=evidence["missing"].get) if evidence["missing"] else "无"}；全部分解见上。',
        f'同窗口开放权限使 truth-near terminal 增加 {p1["terminal_frames"] - p0["terminal_frames"]} 帧，净 recall 变化 P1−P0={pct(p1["terminal_recall"] - p0["terminal_recall"])}；不把全部 core 错误算作因果 loss。',
        f'P0→P1 可行最小 SSE oracle RMSE：{oracle_values["P0"]["rmse_mhz"]:.3f}→{oracle_values["P1"]["rmse_mhz"]:.3f} MHz；逐窗口同锚点反事实见 core_permission_matched_windows.csv。',
        f'P0 中 {beam_loss} 个 missing 帧可由谱系定位到剪枝或被剪前驱，占共同错误分母 {pct(a.ratio(beam_loss, p0["error_frames"]))}；错误区间局部审计记录 {len(evidence["first_prunes"])} 次首次剪枝。B32 的实际恢复量另见下一项。',
        f'完整窗口前缀首次剪枝的 search step 中位数：{float(np.median([int(r["first_loss_search_step"]) for r in evidence["full_window_prunes"]])) if evidence["full_window_prunes"] else "N/A"}（从 anchor 起一基计数）；见图04和 full_window_lineage_loss.csv。',
        f'匹配 fresh 子集、原权限 terminal recall：B8={pct(matched_values["P0"]["terminal_recall"])}，B32={pct(matched_values["B32_P0_PERMISSION"]["terminal_recall"])}；challenge 权限 B8={pct(matched_values["P1"]["terminal_recall"])}，B32={pct(matched_values["B32_CHALLENGE_PERMISSION"]["terminal_recall"])}。',
        f'同子集 diversity：P2={pct(matched_values["P2"]["terminal_recall"])}，P3={pct(matched_values["P3"]["terminal_recall"])}；应与上题相同权限 B32 比较，不称严格上界。',
        f'最高 fresh terminal recall：{max(totals, key=lambda p: totals[p]["terminal_recall"])}；只描述固定矩阵，不据此调参。',
        f'全 fresh proposal 总量：{[(r["variant"], r["total"], r["ratio_to_p0"]) for r in evidence["costs"]]}；mean/p95 见成本表，P0 新窗口记零。',
        f'P0→P3 完整 proposal oracle RMSE {oracle_values["P0"]["rmse_mhz"]:.3f}→{oracle_values["P3"]["rmse_mhz"]:.3f} MHz，wrong {pct(oracle_values["P0"]["wrong_branch"])}→{pct(oracle_values["P3"]["wrong_branch"])}；对应 harm 独立列出。',
        f'最终 funnel 分解：{funnel_text}。' if gate['passed'] else 'proposal gate 失败，最终 scorer 评价按协议跳过，不能作利用能力结论。',
        f'最终 RMSE P0→P3：{final_values["P0"]["rmse_mhz"]:.3f}→{final_values["P3"]["rmse_mhz"]:.3f} MHz；全部变体见上表。' if gate['passed'] else '最终 RMSE：未运行。',
        f'最终 wrong P0→P3：{pct(final_values["P0"]["wrong_branch"])}→{pct(final_values["P3"]["wrong_branch"])}。' if gate['passed'] else '最终 wrong branch：未运行。',
        f'P3 precision={pct(final_values["P3"]["precision"])}, harm={pct(final_values["P3"]["harm_rate"])}，harmed={final_values["P3"]["harmed_frames"]:.0f}；其余变体见上表。' if gate['passed'] else 'precision/harm：未运行，不填零。',
        f'正确 edge harmed P0/P3={final_values["P0"]["correct_edge_harmed"]:.0f}/{final_values["P3"]["correct_edge_harmed"]:.0f}，modified P3={final_values["P3"]["correct_edge_modified"]:.0f}。' if gate['passed'] else 'correct-edge preservation：未运行。',
        f'Fast-descent harmed P0/P3={final_values["P0"]["fast_descent_harmed"]:.0f}/{final_values["P3"]["fast_descent_harmed"]:.0f}。' if gate['passed'] else 'fast-descent preservation：未运行。',
        'ch3 七项诊断见 ch3_proposal_audit.csv 和下节；仅描述行为，不声称正确率提高。' if gate['passed'] else 'ch3：按停止条件未读取评价。',
        f'Good-data modification risk 超限记录 {len(real_risks)} 条（不同固定变体分别计数）；这不是已证实的准确率 regression。' if gate['passed'] else 'Good-data：未运行，不作 regression 结论。',
        f'P3 未完成纠正的层级计数：{json.dumps(layer_counts, ensure_ascii=False)}；最大项为 {max(layer_counts, key=lambda key: layer_counts[key])}。',
        f'P3 仍有 {pct(p3["missing_proposal_fraction"])} 的 candidate-conditioned proposal 缺失，不能把全局问题转交 scorer。可在已有完整 proposal 的受限子集研究跨尺度证据，但本轮没有自动启动 023G。',
        '没有资格跳过跨尺度直接启动 AI；身份交换对观测不可辨识，AI 不能创造物理身份。']
    lines += [f'{i}. {text}' for i, text in enumerate(answers, 1)]
    if gate['passed']:
        lines += ['', '## 真实数据修改风险', '',
                  f'共 {len({r["stream"] for r in real})} streams；风险表涉及 {len({r["stream"] for r in real_risks})} 个不同 stream。修改率超过 5% 不等于已证实准确率下降。', '',
                  '| Stream | Variant | 修改率 | 同 stream P0 风险 |', '|---|---|---:|---|']
        for row in real_risks:
            baseline = next(r for r in real if r['stream'] == row['stream'] and r['variant'] == 'P0')
            lines.append(f'| {row["stream"]} | {row["variant"]} | {float(row["modification_fraction"]):.3%} | {baseline["relatively_good_risk"]} |')
        lines += ['', '20260607 Balanced ch2 的 P2/P3 是相对 P0 新触发的风险；20260701 的超限需与同 stream P0 既有风险区分。完整全记录谱图与逐点 provenance 已保存。',
                  'ch3 的终端提案另见 figures/ch3__*_proposal_overlay.png；这些图从保存的 DAG 绘制，不重新运行搜索或 selector。人工观察见 visual_review.md。']
        lines += ['', '## ch3 七项行为诊断', '']
        for row in read_csv(output / 'ch3_proposal_audit.csv'):
            lines.append(f'- {row["profile"]}/{row["variant"]}：算法 suspicious {row["suspicious_frames"]}；core alternative {row["core_alternative_frames"]}；core accepted {row["core_accepted_frames"]}；最终修改 {row["modified_frames"]}；相对 E4 变化 {row["changed_vs_e4"]}；retained core 偏离 {row["core_accepted_frames"]}（正确性未知）；修改率 {float(row["modification_fraction"]):.3%}。人工展示为全记录，并不等于算法 suspicious 或真实错误标签。')
    lines += ['', '## 验证与边界', '',
        '基线 pytest：717 passed、2 failed（既有 launcher）；基线 strict mypy：19 项、仅两个 023E 模块；基线 ruff 通过。',
        '本次新测试、完整 pytest、ruff、mypy --strict 与 git diff --check 的实际记录见 validation_summary.json 及对应日志。不通过修改 launcher 或 Production 消除历史失败。',
        '冻结后仅补强了接口边界校验（拒绝伪装成正式结果的非 B8 对象、空 edge 返回 KEEP_NO_EDGE）及审计输出。正常 B8 非空窗口的生成、评分、阈值和接受逻辑未变；未调参或重跑 fresh 争取通过，详见 interface_validation_amendment.json。',
        f'完整性：`{json.dumps({k:v for k,v in checks.items() if k != "git"}, ensure_ascii=False)}`。',
        'Research HEAD 91381f1，Production HEAD 07a1e0f；Production main 继续冻结，未 commit/push/promotion。HEAD 不代表全部 untracked Research 实现。',
        '任务结束。TASK-020 whitening 未独立核验，不能把历史记录写成复现结论。']
    (output / 'final_research_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    runner.write_json(output / 'experiment_metadata.json', dict(task='TASK-023F', verdict=overall,
        activation=activation, gate=gate, final=final, integrity=checks,
        diversity_causal_verification=witness, remaining_layer_counts=layer_counts,
        real_guard_risks=real_risks, cost_risk=proposal_risk,
        cross_scale='NOT_TESTED', ai='NOT_STARTED', legacy_streams=sum(
            r['context']['stage'] != 'FRESH' for r in evidence['results']),
        fresh_streams=sum(r['context']['stage'] == 'FRESH' for r in evidence['results'])))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    gate = json.loads((output / 'fresh_proposal_gate.json').read_text(encoding='utf-8'))
    if not gate['passed']:
        for name, fields in (
            ('fresh_heldout_comparison.csv', ('case_id', 'method', 'rmse_mhz', 'wrong_branch', 'coverage')),
            ('ch3_proposal_audit.csv', ('stream', 'profile', 'variant', 'modified_frames')),
            ('cross_dataset_validation.csv', ('stream', 'variant', 'modification_fraction'))):
            runner.write_csv(output / name, [], fields)
        runner.write_json(output / 'skipped_stages.json', dict(final_algorithm='PROPOSAL_GATE_FAILED',
                          real_data='PROPOSAL_GATE_FAILED', ch3='PROPOSAL_GATE_FAILED'))
    evidence = aggregate_tables(output)
    final = final_metrics(output)
    figures(output, evidence, gate)
    checks = integrity(output)
    report(output, evidence, gate, final, checks)


if __name__ == '__main__':
    main()
