"""Descriptive aggregation of the once-evaluated, immutable TASK-025 results."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from matplotlib.figure import Figure

from dps_studio.research.task025_informative_interval import informative_mask, runs
from scripts.run_task025 import DETECTORS, load_json
from scripts.run_task023f_proposal_recovery import write_csv, write_json


def ratios(frame: Any) -> dict[str, float]:
    if frame.empty:
        return dict(frame_pooled=float('nan'), waveform_macro=float('nan'))
    by_wave = frame.groupby('waveform')[['numerator', 'denominator']].sum()
    return dict(frame_pooled=float(frame.numerator.sum()/frame.denominator.sum()),
                waveform_macro=float((by_wave.numerator/by_wave.denominator).mean()))


def filtered(frame: Any, *, split: str = 'HELD_OUT', detector: str = 'E1',
             mask: str = 'SEARCH_ACTIVE', stratum: str = 'target_present',
             profile: str = 'ALL', dataset: str = 'ALL', family: str = 'ALL') -> Any:
    result = frame[(frame.split == split) & (frame.detector == detector) &
                   (frame['mask'] == mask) & (frame.stratum == stratum)]
    for column, value in (('profile', profile), ('dataset', dataset), ('family', family)):
        if value != 'ALL':
            result = result[result[column] == value]
    return result


def frame_aggregates(frame: Any) -> list[dict[str, Any]]:
    rows = []
    for (split, detector, mask, stratum), group in frame.groupby(
            ['split', 'detector', 'mask', 'stratum']):
        scopes = [('ALL', 'ALL', 'ALL', group)]
        scopes += [(profile, 'ALL', 'ALL', sub) for profile, sub in group.groupby('profile')]
        scopes += [('ALL', dataset, 'ALL', sub) for dataset, sub in group.groupby('dataset')]
        scopes += [('ALL', dataset, family, sub) for (dataset, family), sub in group.groupby(
            ['dataset', 'family'])]
        for profile, dataset, family, subset in scopes:
            for aggregation, value in ratios(subset).items():
                rows.append(dict(split=split, detector=detector, mask=mask, stratum=stratum,
                    profile=profile, dataset=dataset, family=family, aggregation=aggregation,
                    recall_or_activation=value, rejection_or_fnr=1-value,
                    waveforms=int(subset.waveform.nunique()),
                    numerator=int(subset.numerator.sum()), denominator=int(subset.denominator.sum())))
    return rows


def phase_b(frame: Any, candidate: Any) -> list[dict[str, Any]]:
    result = []
    for profile in ('ALL', 'balanced', 'high_time_resolution'):
        for mask in ('SUPPORTED_FRAME', 'SEARCH_ACTIVE'):
            for stratum, minimum, reject in (
                ('target_present', .99, False), ('fast_descent', .99, False),
                ('temporary_fading', .98, False), ('leading_edge', .98, False),
                ('trailing_edge', .98, False), ('pure_noise_dropout', .80, True),
            ):
                for aggregation, value in ratios(filtered(frame, profile=profile, mask=mask,
                                                         stratum=stratum)).items():
                    observed = 1-value if reject else value
                    result.append(dict(profile=profile, mask=mask, stratum=stratum,
                        aggregation=aggregation, metric='rejection' if reject else 'recall',
                        observed=observed, required=minimum,
                        passed=bool(np.isfinite(observed) and observed >= minimum)))
    coverage = float(candidate[candidate.split == 'HELD_OUT'].strongest_coverage.min())
    result.append(dict(profile='ALL', mask='COMPLETE_OUTPUT', stratum='all',
        aggregation='minimum_stream', metric='coverage', observed=coverage,
        required=1., passed=coverage == 1.))
    return result


def descriptive_verdicts(frame: Any, passed: bool) -> dict[str, str]:
    def meets(stratum: str, minimum: float, reject: bool = False,
              dataset: str = 'ALL', family: str = 'ALL') -> bool:
        values = ratios(filtered(frame, stratum=stratum, mask='SUPPORTED_FRAME',
                                  dataset=dataset, family=family))
        return all(np.isfinite(v) and (1-v if reject else v) >= minimum for v in values.values())

    signal = [meets('structured', .99), meets('low_information', .80, True)]
    hard = [meets('low_information', .80, True, 'HARD_NEGATIVE', name)
            for name in ('H0', 'H1')]
    hard += [meets('structured', .99, False, 'HARD_NEGATIVE', f'H{i}') for i in range(2, 8)]

    def label(values: list[bool]) -> str:
        return 'SUPPORTED' if all(values) else 'MIXED' if any(values) else 'NOT SUPPORTED'

    return dict(signal_support_separability=label(signal), hard_negative_robustness=label(hard),
        informative_interval_detection='SUPPORTED' if passed else 'NOT SUPPORTED',
        engineering_cost_reduction='NOT TESTED', frozen_p3_performance_preservation='NOT TESTED',
        potential_production_value='RESEARCH_ONLY')


def segment_aggregates(segments: Any) -> list[dict[str, Any]]:
    result = []
    metrics = ('detected', 'coverage_99', 'fully_covered', 'coverage', 'fragments',
               'excess_fragments', 'leading_missed_s', 'trailing_missed_s')
    for (split, detector), group in segments.groupby(['split', 'detector']):
        scopes = [('ALL', 'ALL', group)] + [(dataset, family, sub)
            for (dataset, family), sub in group.groupby(['dataset', 'family'])]
        for dataset, family, sub in scopes:
            for metric in metrics:
                result.append(dict(split=split, detector=detector, dataset=dataset, family=family,
                    metric=metric, segment_pooled=float(sub[metric].mean()),
                    waveform_macro=float(sub.groupby('waveform')[metric].mean().mean()),
                    segments=len(sub), waveforms=int(sub.waveform.nunique())))
    return result


def candidate_aggregates(candidate: Any) -> list[dict[str, Any]]:
    result = []
    for (split, dataset), group in candidate.groupby(['split', 'dataset']):
        for denominator, numerator, scope in (
            ('target_frames', 'candidate_hits', 'all_target'),
            ('error_frames', 'error_candidate_hits', 'strongest_error'),
        ):
            by_wave = group.groupby('waveform')[[numerator, denominator]].sum()
            positive = by_wave[by_wave[denominator] > 0]
            total = int(group[denominator].sum())
            result.append(dict(split=split, dataset=dataset, scope=scope, denominator=total,
                numerator=int(group[numerator].sum()),
                frame_pooled=float(group[numerator].sum()/total) if total else None,
                waveform_macro=float((positive[numerator]/positive[denominator]).mean())
                if len(positive) else None, waveforms=len(positive)))
    return result


def save_figure(figure: Figure, output: Path, name: str) -> None:
    for suffix in ('png', 'svg'):
        path = output / 'figures' / (name+'.'+suffix)
        if path.exists():
            raise FileExistsError(path)
        figure.savefig(path, dpi=180, bbox_inches='tight')


def skipped(output: Path, reason: str) -> None:
    fields = {
        'gating_performance.csv': ('dataset', 'waveform', 'profile', 'method', 'candidate_recall',
            'terminal_proposal_recall', 'final_correction_recall', 'rmse_hz', 'wrong_branch',
            'coverage', 'precision', 'harm', 'corrected_frames', 'harmed_frames', 'status', 'reason'),
        'engineering_cost.csv': ('dataset', 'waveform', 'profile', 'method', 'proposal_count',
            'windows_searched', 'search_active_fraction', 'search_seconds', 'mean_search_seconds',
            'p95_search_seconds', 'process_high_water_bytes', 'status', 'reason'),
        'real_data_interval_behavior.csv': ('stream', 'profile', 'intervals', 'search_active_fraction',
            'proposal_count', 'runtime', 'final_modifications', 'rank_changes', 'spectral_support',
            'raw_E1', 'quality_diagnostics', 'risk_over_5_percent', 'status', 'reason'),
        'ch3_interval_audit.csv': ('profile', 'middle_retained', 'edge_search_reduction',
            'proposal_reduction', 'outside_equals_strongest', 'manual_reference', 'status', 'reason'),
    }
    for name, header in fields.items():
        write_csv(output / name, [], header)
    write_json(output / 'skipped_stages.json', {name: dict(status='SKIPPED', reason=reason)
                                               for name in fields})
    for name, title in (
        ('05_g0_g1_cost_SKIPPED', 'G0 / G1 proposal and runtime comparison'),
        ('06_g0_g1_performance_SKIPPED', 'G0 / G1 RMSE, wrong branch and harm'),
        ('07_ch3_balanced_SKIPPED', 'ch3 Balanced full-record interval audit'),
        ('08_ch3_high_time_SKIPPED', 'ch3 High-time full-record interval audit'),
    ):
        fig = Figure(figsize=(9, 3))
        axis = fig.subplots()
        axis.axis('off')
        axis.text(.5, .72, title, ha='center', fontsize=15)
        axis.text(.5, .46, 'SKIPPED: preregistered Phase B gate failed', ha='center', fontsize=13)
        axis.text(.5, .20, 'No G0/G1 or real-data result measured; no legacy substitution.',
                  ha='center', fontsize=10)
        save_figure(fig, output, name)


def plots(output: Path, aggregate: Any) -> None:
    streams: dict[str, list[dict[str, np.ndarray[Any, Any]]]] = {'CALIBRATION': [], 'HELD_OUT': []}
    interval_rows = []
    thresholds = load_json(output / 'frozen_thresholds.json')
    for split in ('calibration', 'held_out'):
        for row in load_json(output / (split+'_manifest.json')):
            for stream in row['streams']:
                with np.load(output / 'streams' / (stream['stream']+'.npz')) as arrays:
                    values = {key: arrays[key] for key in (*DETECTORS, 'mask_target_present',
                        'mask_low_information', 'mask_structured', 'time_s')}
                    values['coherent_negative'] = (arrays['mask_structured'] &
                        (row['dataset'] == 'HARD_NEGATIVE'))
                    _, active = informative_mask(arrays['time_s'], arrays['E1'],
                                                  thresholds['E1']['threshold'])
                    for first, stop in runs(active):
                        interval_rows.append(dict(waveform=row['waveform'], split=row['split'],
                            profile=stream['profile'], start_frame=first, end_frame=stop-1,
                            start_s=float(arrays['time_s'][first]),
                            end_s=float(arrays['time_s'][stop-1])))
                streams[row['split']].append(values)
    write_csv(output / 'automatic_intervals.csv', interval_rows)
    pooled = {split: {key: np.concatenate([v[key] for v in values]) for key in values[0]}
              for split, values in streams.items()}
    for name, groups, title in (
        ('01_e1_target_low_information', ('mask_target_present', 'mask_low_information'),
         'E1: target-present vs low information (stress included)'),
        ('02_e1_coherent_nontarget', ('coherent_negative', 'mask_low_information'),
         'E1: coherent non-target remains TARGET_ABSENT'),
    ):
        fig = Figure(figsize=(12, 4))
        for axis, (split, values) in zip(fig.subplots(1, 2), pooled.items(), strict=True):
            for group, color in zip(groups, ('#0072B2', '#D55E00'), strict=True):
                axis.hist(values['E1'][values[group]], bins=np.linspace(0, 1, 61), density=True,
                          histtype='step', linewidth=1.8, label=group.removeprefix('mask_'), color=color)
            axis.axvline(thresholds['E1']['threshold'], color='black', linestyle='--',
                         label='frozen threshold')
            axis.set(title=split, xlabel='E1 (dimensionless)', ylabel='Frame-pooled density')
            axis.legend(fontsize=8)
        fig.suptitle(title)
        fig.tight_layout()
        save_figure(fig, output, name)
    curves = []
    fig = Figure(figsize=(12, 4.5))
    for axis, (split, values) in zip(fig.subplots(1, 2), pooled.items(), strict=True):
        for detector, color in zip(DETECTORS, ('#0072B2', '#D55E00', '#009E73'), strict=True):
            scores = values[detector]
            finite = scores[np.isfinite(scores)]
            grid = np.unique(np.r_[np.quantile(finite, np.linspace(0, 1, 201)),
                                   thresholds[detector]['threshold']])
            pos = np.sort(scores[values['mask_target_present']])
            neg = np.sort(scores[values['mask_low_information']])
            recall = (len(pos)-np.searchsorted(pos, grid, side='left'))/len(pos)
            rejection = np.searchsorted(neg, grid, side='left')/len(neg)
            axis.plot(rejection, recall, label=detector, color=color)
            frozen_index = int(np.flatnonzero(grid == thresholds[detector]['threshold'])[0])
            axis.scatter([rejection[frozen_index]], [recall[frozen_index]], color=color, s=32)
            for threshold, rec, rej in zip(grid, recall, rejection, strict=True):
                curves.append(dict(split=split, detector=detector, threshold=float(threshold),
                    target_recall=float(rec), low_information_rejection=float(rej),
                    purpose='DESCRIPTIVE_ONLY_NO_THRESHOLD_SELECTION'))
        axis.set(title=split, xlabel='Low-information rejection', ylabel='Target-present recall',
                 xlim=(0, 1), ylim=(0, 1.01))
        axis.axhline(.99, color='gray', linestyle=':')
        axis.legend()
    fig.suptitle('Recall-rejection curves; dots = calibration-frozen operating points')
    fig.tight_layout()
    save_figure(fig, output, '03_recall_rejection_curves')
    write_csv(output / 'recall_rejection_curves.csv', curves)
    fig = Figure(figsize=(10, 4.5))
    axis = fig.subplots()
    for j, metric in enumerate(('detected', 'coverage_99', 'fully_covered')):
        fractions = []
        for detector in DETECTORS:
            subset = aggregate[(aggregate.split == 'HELD_OUT') &
                (aggregate.detector == detector) & (aggregate.metric == metric) &
                (aggregate.dataset == 'ALL') & (aggregate.family == 'ALL')]
            fractions.append(float(subset.iloc[0].waveform_macro))
        axis.bar(np.arange(3)+.23*(j-1), fractions, .23, label=metric)
    axis.set(xticks=np.arange(3), xticklabels=DETECTORS, ylim=(0, 1.05),
             ylabel='Waveform-macro fraction', title='Held-out target segments: overlap vs coverage')
    axis.legend()
    fig.tight_layout()
    save_figure(fig, output, '04_segment_recall')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    frame = pd.read_csv(output / 'frame_detection_metrics.csv')
    segments = pd.read_csv(output / 'segment_detection_metrics.csv')
    candidate = pd.read_csv(output / 'candidate_recall.csv')
    write_csv(output / 'frame_detection_aggregates.csv', frame_aggregates(frame))
    segment_rows = segment_aggregates(segments)
    write_csv(output / 'segment_detection_aggregates.csv', segment_rows)
    write_csv(output / 'candidate_recall_aggregates.csv', candidate_aggregates(candidate))
    gates = phase_b(frame, candidate)
    write_csv(output / 'phase_b_success_gates.csv', gates)
    passed = all(row['passed'] for row in gates)
    verdicts = descriptive_verdicts(frame, passed)
    write_json(output / 'phase_b_decision.json', dict(passed=passed, verdicts=verdicts,
        failed_checks=[row for row in gates if not row['passed']],
        next_phase='PHASE_C_PERMITTED' if passed else 'EARLY_STOP'))
    plots(output, pd.DataFrame(segment_rows))
    if not passed:
        skipped(output, 'Frozen Phase B failed; see phase_b_success_gates.csv. No threshold retuning.')
    print(verdicts, flush=True)


if __name__ == '__main__':
    main()
