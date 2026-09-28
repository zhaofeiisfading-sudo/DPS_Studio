"""Aggregate immutable paired observations; never select new feature definitions."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research.task023h_pair_audit import ranking_credit
from dps_studio.research.task023h_raw_evidence import FEATURES
from scripts import run_task023f_proposal_recovery as r


def mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else float('nan')


def metric(rows: list[dict[str, Any]], feature: str, macro: bool) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row['waveform'] if macro else 'pooled'].append(row)
    estimates = []
    deltas: list[float] = []
    for values in groups.values():
        baseline = [ranking_credit(v['baseline_difference'], 1e-9) for v in values]
        delta = [float(v['scores'][0][feature]-v['scores'][1][feature]) for v in values]
        raw = [ranking_credit(v) for v in delta]
        error = [j for j, b in enumerate(baseline) if b == 0]
        correct = [j for j, b in enumerate(baseline) if b == 1]
        rescued = sum(raw[j] == 1 for j in error)
        harmed = sum(raw[j] != 1 for j in correct)
        estimates.append(dict(baseline_accuracy=mean(baseline), raw_accuracy=mean(raw),
            improvement=mean(raw)-mean(baseline), finite_coverage=mean([float(np.isfinite(v)) for v in delta]),
            rescue_rate=rescued/len(error) if error else float('nan'),
            preservation_rate=1-harmed/len(correct) if correct else float('nan'),
            net_pairwise_gain=(rescued-harmed)/len(values)))
        deltas.extend(d for d in delta if np.isfinite(d))
    out: dict[str, Any] = dict(feature=feature, pairs=len(rows), waveforms=len({v['waveform'] for v in rows}),
        aggregation='WAVEFORM_MACRO' if macro else 'PAIR_POOLED')
    fields = ('baseline_accuracy', 'raw_accuracy', 'improvement', 'finite_coverage',
              'rescue_rate', 'preservation_rate', 'net_pairwise_gain')
    for field in fields:
        out[field] = mean([v[field] for v in estimates if np.isfinite(v[field])])
    for q in (.05, .25, .5, .75, .95):
        out[f'difference_q{int(q*100):02d}'] = float(np.quantile(deltas, q)) if deltas else float('nan')
    if macro and estimates:
        gains = np.array([v['improvement'] for v in estimates])
        draws = np.random.default_rng(2408999).choice(gains, size=(2000, len(gains)), replace=True).mean(axis=1)
        out['gain_ci95_low'], out['gain_ci95_high'] = map(float, np.quantile(draws, [.025, .975]))
    else:
        out['gain_ci95_low'] = out['gain_ci95_high'] = float('nan')
    return out


def strata(pair: dict[str, Any]) -> set[str]:
    tags = {'ALL', pair['taxonomy'], pair['family']}
    variant = pair['variant']
    aliases = {'crossing':'branch_crossing', 'merge':'branch_merge',
        'internal_wrong_core':'smooth_wrong_branch', 'amplitude_exchange':'amplitude_fading',
        'dropout':'temporary_fading', 'transient_leakage':'broadband_contamination',
        'fast_descent':'fast_descent'}
    if variant in aliases:
        tags.add(aliases[variant])
    if pair['noise_sd_v'] >= .3:
        tags.add('low_SNR')
    else:
        tags.add('higher_SNR')
    tags.add('nuisance_stronger' if pair['amplitude_ratio'] > 1 else 'nuisance_weaker_or_equal')
    return tags


def summarize(output: Path) -> None:
    fresh_files = sorted((output/'streams').glob('H23_*.json'))
    assert len(fresh_files) == 128, f'Incomplete fresh: {len(fresh_files)}/128'
    recalls, pairs, ledger, support = [], [], [], []
    for path in sorted((output/'streams').glob('*.json')):
        value = json.loads(path.read_text(encoding='utf-8'))
        recalls.extend(value.get('recall', []))
        pairs.extend(value['pairs'])
        ledger.extend(value['ledger'])
        support.extend(value.get('support', []))
    assert len(recalls) == 256
    r.write_csv(output/'fresh_candidate_recall.csv', recalls)
    manifest, scores = [], []
    pairs.sort(key=lambda v: v['pair_id'])
    assert len({v['pair_id'] for v in pairs}) == len(pairs)
    for pair in pairs:
        manifest.append({key: json.dumps(value, allow_nan=True) if isinstance(value, (list, dict)) else value
                         for key, value in pair.items() if key != 'scores'})
        for feature in FEATURES:
            delta = float(pair['scores'][0][feature]-pair['scores'][1][feature])
            scores.append(dict(pair_id=pair['pair_id'], waveform=pair['waveform'], profile=pair['profile'],
                role=pair['role'], family=pair['family'], variant=pair['variant'], taxonomy=pair['taxonomy'],
                scope=pair['scope'], feature=feature, correct_score=pair['scores'][0][feature],
                wrong_score=pair['scores'][1][feature], difference=delta,
                raw_credit=ranking_credit(delta), baseline_difference=pair['baseline_difference'],
                baseline_credit=ranking_credit(pair['baseline_difference'], 1e-9),
                correct_quality=pair['scores'][0]['quality'], wrong_quality=pair['scores'][1]['quality'],
                samples=pair['scores'][0]['samples'], phase_valid_fraction=pair['scores'][0]['phase_valid_fraction'],
                amplitude_rms_v=pair['scores'][0]['amplitude_rms_v']))
    r.write_csv(output/'proposal_pair_manifest.csv', manifest)
    r.write_csv(output/'raw_domain_pairwise_scores.csv', scores)
    r.write_csv(output/'pair_construction_ledger.csv', ledger)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        scope = 'LOCAL_SUBPATH' if pair['scope'] == 'LOCAL_SUBPATH' else 'STRICT_WHOLE_HISTORY'
        for tag in strata(pair):
            if pair['taxonomy'] != 'NO_VALID_DESCENDANT' or tag == 'NO_VALID_DESCENDANT':
                grouped[pair['role'], scope, tag].append(pair)
        if pair['scope'] == 'TERMINAL':
            grouped[pair['role'], 'TERMINAL_ONLY', 'ALL'].append(pair)
    required = ('ALL', 'PERSISTENT_SCORE_INFERIOR', 'SELECTION_LOSS', 'CORRECT_SELECTION_CONTROL',
                'branch_crossing', 'branch_merge', 'smooth_wrong_branch', 'amplitude_exchange',
                'amplitude_fading', 'temporary_fading', 'broadband_contamination', 'fast_descent', 'low_SNR')
    for tag in required:
        grouped.setdefault(('FRESH', 'STRICT_WHOLE_HISTORY', tag), [])
    aggregates = [dict(role=role, scope=scope, stratum=tag, **metric(values, feature, macro))
        for (role, scope, tag), values in sorted(grouped.items())
        for feature in FEATURES for macro in (False, True)]
    r.write_csv(output/'pairwise_separability_by_family.csv', aggregates)
    r.write_csv(output/'correct_pair_preservation.csv', [v for v in aggregates
        if v['stratum'] in ('ALL', 'CORRECT_SELECTION_CONTROL', 'SELECTION_LOSS', 'PERSISTENT_SCORE_INFERIOR')])
    def get(feature: str, tag: str) -> dict[str, Any]:
        return next(v for v in aggregates if v['role']=='FRESH' and v['scope']=='STRICT_WHOLE_HISTORY'
                    and v['stratum']==tag and v['aggregation']=='WAVEFORM_MACRO' and v['feature']==feature)
    gates = {}
    for feature in FEATURES:
        overall, persistent, selection = (get(feature, tag) for tag in ('ALL','PERSISTENT_SCORE_INFERIOR','SELECTION_LOSS'))
        major = max((v['improvement'] for v in (persistent, selection) if np.isfinite(v['improvement'])), default=0.)
        strata_ok = all(get(feature, tag)['improvement'] > 0 for tag in
                        ('low_SNR','amplitude_fading','smooth_wrong_branch'))
        signal = overall['improvement'] >= .10 and major >= .15
        preservation = overall['preservation_rate'] >= .99
        # Observational identity equality is separately validated before counterfactual.
        verdict = 'SUPPORTED' if signal and preservation and strata_ok else ('MIXED' if signal else 'NOT SUPPORTED')
        gates[feature] = dict(verdict=verdict, overall=overall, persistent=persistent, selection=selection,
            gain_threshold=signal, preservation_threshold=preservation, difficult_strata=strata_ok,
            major_improvement=major,
            counterfactual_eligible=bool(signal and overall['preservation_rate'] >= .95))
    error_count = sum(v['strongest_error_frames'] for v in recalls)
    available_count = sum(v['available_error_frames'] for v in recalls)
    truth_count = sum(v['truth_frames'] for v in recalls)
    truth_available = sum(v['available_truth_frames'] for v in recalls)
    candidate_recall = available_count/error_count
    waveform_recalls = []
    for waveform in sorted({v['waveform'] for v in recalls}):
        values = [v for v in recalls if v['waveform'] == waveform]
        denominator = sum(v['strongest_error_frames'] for v in values)
        if denominator:
            waveform_recalls.append(sum(v['available_error_frames'] for v in values)/denominator)
    summary = dict(waveforms=128, streams=256, strongest_error_frames=error_count,
        candidate_available_error_frames=available_count, candidate_recall=candidate_recall,
        candidate_recall_waveform_macro=mean(waveform_recalls), truth_frames=truth_count,
        candidate_available_truth_frames=truth_available, recall_all_truth=truth_available/truth_count,
        candidate_verdict='SUPPORTED' if candidate_recall >= .99 else 'MIXED',
        representation_warning=candidate_recall < .99, feature_gates=gates,
        raw_verdict=('SUPPORTED' if any(v['verdict']=='SUPPORTED' for v in gates.values()) else
                     'MIXED' if any(v['verdict']=='MIXED' for v in gates.values()) else 'NOT SUPPORTED'),
        counterfactual_allowed=any(v['counterfactual_eligible'] for v in gates.values()),
        scope='Audit only; no new final trajectory or algorithm performance')
    r.write_json(output/'phase_c_gate.json', summary)
    if not summary['counterfactual_allowed']:
        r.write_csv(output/'offline_counterfactual_ranking.csv', [],
            ('waveform','profile','window','feature','original_selection','counterfactual_selection',
             'corrected_selection_loss','scope','skipped_reason'))
        r.write_json(output/'offline_counterfactual_skipped.json', dict(
            reason='PHASE_C_GATE_FAILED: no feature met SUPPORTED or MIXED-with-strong-signal; preservation >=95% required',
            no_terminal_reranking=True, no_new_output=True))
    else:
        print('COUNTERFACTUAL REQUIRED: do not claim task complete before implementing saved-set diagnostic', flush=True)
    # Same four features, along strongest; no new threshold or informative interval.
    support_summary = []
    for profile in ('balanced', 'high_time_resolution'):
        for present in (False, True):
            chosen = [v for v in support if v['profile']==profile and v['target_present']==present]
            for feature in FEATURES:
                values = [v[feature] for v in chosen if np.isfinite(v[feature])]
                support_summary.append(dict(profile=profile, target_present=present, feature=feature,
                    frames=len(chosen), finite_frames=len(values),
                    q05=float(np.quantile(values,.05)), median=float(np.median(values)),
                    q95=float(np.quantile(values,.95)), scope='GT_LABEL_ONLY; STRONGEST_TEMPLATE; NO_THRESHOLD'))
    r.write_csv(output/'synthetic_target_support_distribution.csv', support_summary)
    r.write_json(output/'summary_counts.json', dict(pairs=len(pairs),
        fresh_pairs=sum(v['role']=='FRESH' for v in pairs),
        strict_fresh_pairs=len(grouped['FRESH','STRICT_WHOLE_HISTORY','ALL']),
        legacy_pairs=sum(v['role']=='LEGACY_DIAGNOSTIC' for v in pairs),
        ledger_rows=len(ledger), support_frames=len(support)))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    summarize(parser.parse_args().output.resolve())
