"""Frozen aggregation, paired waveform bootstrap, calibration and readiness."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research import denoising_task002 as scoring
from dps_studio.research.denoising_task003_study import write_csv, write_json

COUNT_KEYS = ('frames', 'truth_frames', 'finite_frames', 'sse_hz2', 'squared_error_frames',
              'wrong_frames', 'interventions', 'truth_interventions', 'corrected_frames',
              'harmed_frames', 'normal_all', 'normal_wrong', 'normal_frames',
              'normal_preserved', 'fast_all', 'fast_wrong', 'fast_frames', 'fast_preserved',
              'candidate_recalled')


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = {k: sum(float(r[k]) for r in rows) for k in COUNT_KEYS}
    return {**values, **scoring.ratios(values),
            'independent_waveforms': len({r['case_id'] for r in rows})}


def paired_uncertainty(rows: list[dict[str, Any]], method: str,
                       reference: str) -> dict[str, Any]:
    cases = sorted({r['case_id'] for r in rows})
    differences = []
    for case in cases:
        a = aggregate([r for r in rows if r['case_id'] == case and r['method'] == method])
        b = aggregate([r for r in rows if r['case_id'] == case and r['method'] == reference])
        if a['rmse_hz'] is not None and b['rmse_hz'] is not None:
            differences.append(a['rmse_hz']-b['rmse_hz'])
    if not differences:
        return dict(method=method, reference=reference, waveforms=0, mean_hz=None,
                    lower_hz=None, upper_hz=None)
    d = np.asarray(differences)
    rng = np.random.default_rng(43099003)
    means = d[rng.integers(len(d), size=(4000, len(d)))].mean(axis=1)
    return dict(method=method, reference=reference, waveforms=len(d),
                mean_hz=float(d.mean()), lower_hz=float(np.quantile(means, .025)),
                upper_hz=float(np.quantile(means, .975)),
                improved=int((d < -1).sum()), worsened=int((d > 1).sum()),
                unchanged=int((abs(d) <= 1).sum()))


def assess(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    by = {m: aggregate([r for r in rows if r['method'] == m])
          for m in ('M0', 'M1', 'M2', method)}
    a, b, strongest = by[method], by['M2'], by['M0']
    reduction = 1-a['harmed_frames']/b['harmed_frames'] if b['harmed_frames'] else None
    retention = a['corrected_frames']/b['corrected_frames'] if b['corrected_frames'] else None
    family_differences = []
    for family in sorted({r['family'] for r in rows}):
        c = aggregate([r for r in rows if r['family'] == family and r['method'] == method])
        d = aggregate([r for r in rows if r['family'] == family and r['method'] == 'M2'])
        family_differences.append(c['wrong_branch_fraction']-d['wrong_branch_fraction'])
    uncertainty = paired_uncertainty(rows, method, 'M0')
    gates = dict(harm_reduction_75pct=reduction is not None and reduction >= .75,
        benefit_retention_70pct=retention is not None and retention >= .7,
        nontrivial_corrections=a['corrected_frames'] >= 20, coverage=a['coverage'] == 1,
        rmse_vs_m2=a['rmse_hz'] <= 1.02*b['rmse_hz'],
        rmse_vs_strongest=a['rmse_hz'] <= strongest['rmse_hz'],
        normal_accuracy=a['normal_truth_accuracy'] >= b['normal_truth_accuracy'],
        fast_accuracy=a['fast_truth_accuracy'] >= b['fast_truth_accuracy'],
        correct_fast_preservation=a['fast_preservation'] >= .995,
        worst_family_wrong_increase=max(family_differences) <= .005,
        macro_rmse_vs_strongest=uncertainty['upper_hz'] <= 0)
    return dict(method=method, harm_reduction=reduction, benefit_retention=retention,
                gates=gates, passed=all(gates.values()), uncertainty=uncertainty)


def summarize(out: Path, split: str) -> dict[str, Any]:
    key = split.lower()
    raw = read_csv(out/f'{key}_metrics.csv')
    primary = [r for r in raw if r['reference'] == 'M1']
    methods = sorted({r['method'] for r in raw})
    summaries = []
    for reference in ('M0', 'M1'):
        for method in methods:
            summaries.append(dict(split=split, method=method, reference=reference,
                **aggregate([r for r in raw if r['method'] == method and r['reference'] == reference])))
    write_csv(out/f'{key}_comparison.csv', summaries)
    families = []
    for family in sorted({r['family'] for r in primary}):
        subset = [r for r in primary if r['family'] == family]
        for method in methods:
            families.append(dict(family=family, method=method,
                **aggregate([r for r in subset if r['method'] == method]),
                **{f'paired_vs_M2_{k}': v for k, v in
                   paired_uncertainty(subset, method, 'M2').items()
                   if k not in ('method', 'reference')}))
    write_csv(out/f'{key}_family_comparison.csv', families)
    diagnostics = []
    proposals = read_csv(out/f'{key}_proposals.csv')
    for method in ('R1', 'R2_B3', 'R2_B4'):
        p = [r for r in proposals if r['method'] == method]
        rejected = [r for r in p if r['rejected'] == 'True']
        harmful = [r for r in p if int(r['harmed']) > 0]
        rejected_harmful = [r for r in rejected if int(r['harmed']) > 0]
        nonharmful = [r for r in p if int(r['harmed']) == 0]
        rejected_nonharmful = [r for r in rejected if int(r['harmed']) == 0]
        diagnostics.append(dict(method=method, proposals=len(p), rejected=len(rejected),
            rejection_rate=len(rejected)/len(p) if p else None,
            harmful_proposals=len(harmful), rejected_harmful_proposals=len(rejected_harmful),
            accepted_harmful_proposals=len(harmful)-len(rejected_harmful),
            beneficial_proposals=sum(int(r['corrected']) > 0 for r in p),
            rejected_beneficial_proposals=sum(int(r['corrected']) > 0 for r in rejected),
            harmful_waveforms=len({r['case_id'] for r in harmful}),
            risk_recall=len(rejected_harmful)/len(harmful) if harmful else None,
            false_positive_rate=len(rejected_nonharmful)/len(nonharmful) if nonharmful else None,
            correct_frames_lost=sum(int(r['corrected']) for r in rejected),
            harm_frames_avoided=sum(int(r['harmed']) for r in rejected)))
    write_csv(out/f'{key}_risk_diagnostics.csv', diagnostics)
    decisions = {m: assess(primary, m) for m in ('R1', 'R2_B3', 'R2_B4')}
    write_json(out/f'{key}_readiness.json', decisions)
    uncertainty = [paired_uncertainty(primary, m, ref) for m in methods
                   for ref in ('M0', 'M1', 'M2') if m != ref]
    write_csv(out/f'{key}_paired_uncertainty.csv', uncertainty)
    return decisions


def freeze(out: Path) -> None:
    decisions = json.loads((out/'calibration_readiness.json').read_text())
    rows = read_csv(out/'calibration_comparison.csv')
    candidates = [m for m in ('R2_B3', 'R2_B4') if decisions[m]['passed']]
    feasible = bool(candidates)
    if not candidates:
        candidates = ['R2_B3', 'R2_B4']
    def score(m: str) -> tuple[float, int]:
        r = next(r for r in rows if r['method'] == m and r['reference'] == 'M1')
        return float(r['corrected_frames'])-float(r['harmed_frames']), int(m == 'R2_B3')
    chosen = max(candidates, key=score)
    write_json(out/'calibration_freeze.json', dict(M3=chosen, calibration_passed=feasible,
        maximum_balance_db=3. if chosen == 'R2_B3' else 4.,
        utc=datetime.now(timezone.utc).isoformat(), ai='NOT JUSTIFIED / NOT RUN',
        selection='pre-registered corrected-harmed, smaller threshold on tie',
        no_held_out_viewed=not (out/'held_out_started.json').exists()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('summarize', 'freeze'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', default='HELD_OUT')
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.output)
    else:
        summarize(args.output, args.split)


if __name__ == '__main__':
    main()
