"""GT-only evaluator and conditional fresh experiment; no fitting."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research import task027_denoising as m
from dps_studio.research.task023e_waveform_benchmark import PROFILES, SAMPLE_RATE_HZ, array_hash
from scripts.run_task027 import case_for, read_json, verify_freeze, write_csv, write_json


def counts(path: m.FloatArray, reference: m.FloatArray, truth: m.FloatArray,
           normal: Any, fast: Any, no_info: Any, jump: Any,
           candidates: Any) -> dict[str, Any]:
    valid = np.isfinite(truth)
    finite = np.isfinite(path)
    comparable = valid & finite
    error, old = abs(path-truth), abs(reference-truth)
    changed = (abs(path-reference) > 1e6) | (finite != np.isfinite(reference))
    corrected = valid & changed & finite & (error < old-1e6)
    harmed = valid & ((changed & (error > old+1e6)) | ~finite)
    ranks = [min((p.candidate_rank for p in frame if abs(p.transition_frequency_hz-truth[i])
                  <= 200e6), default=np.nan) for i, frame in enumerate(candidates.candidates_by_frame)]
    rank = np.asarray(ranks)
    return dict(frames=len(path), truth_frames=int(valid.sum()),
        selected=int(finite.sum()), truth_selected=int(comparable.sum()),
        sse_hz2=float(np.sum(error[comparable]**2)),
        wrong=int((valid & ((error > 200e6) | ~finite)).sum()),
        candidate_hits=int((valid & np.isfinite(rank)).sum()),
        truth_near_rank_sum=float(np.nansum(rank[valid])),
        interventions=int((valid & changed).sum()),
        exact_modifications=int(np.sum(~np.isclose(path, reference, rtol=0, atol=0, equal_nan=True))),
        corrected_frames=int(corrected.sum()), harmed_frames=int(harmed.sum()),
        exact_error_improved=int((comparable & (error < old)).sum()),
        exact_error_worsened=int((comparable & (error > old)).sum()),
        normal_frames=int(normal.sum()),
        normal_preserved=int((normal & finite & (error <= 200e6)
                              & (abs(path-reference) <= 1e6)).sum()),
        fast_frames=int(fast.sum()), fast_preserved=int((fast & finite & (error <= 200e6)).sum()),
        no_info_frames=int(no_info.sum()), false_tracks=int((no_info & finite).sum()),
        obvious_jump_frames=int(jump.sum()), jump_corrected=int((jump & finite & (error <= 200e6)).sum()))


def rates(c: dict[str, Any]) -> dict[str, float | None]:
    def ratio(a: str, b: str) -> float | None:
        return float(c[a]/c[b]) if c[b] else None
    return dict(rmse_hz=float(np.sqrt(c['sse_hz2']/c['truth_selected']))
                if c['truth_selected'] else None,
        wrong_branch=ratio('wrong', 'truth_frames'), coverage=ratio('selected', 'frames'),
        truth_coverage=ratio('truth_selected', 'truth_frames'),
        candidate_recall=ratio('candidate_hits', 'truth_frames'),
        truth_near_rank=ratio('truth_near_rank_sum', 'candidate_hits'),
        intervention_precision=ratio('corrected_frames', 'interventions'),
        harm_rate=ratio('harmed_frames', 'interventions'),
        harmed_fraction=ratio('harmed_frames', 'truth_frames'),
        normal_preservation=ratio('normal_preserved', 'normal_frames'),
        fast_preservation=ratio('fast_preserved', 'fast_frames'),
        no_information_false_track_rate=ratio('false_tracks', 'no_info_frames'),
        obvious_jump_correction_rate=ratio('jump_corrected', 'obvious_jump_frames'))


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [k for k in rows[0] if k not in ('dataset', 'family', 'instance', 'seed', 'method',
                                         'profile', 'reference', 'elapsed_s', 'case_id')]
    out = []
    for dataset in ('CORE', 'OBVIOUS'):
        for method in ('strongest', 'P3', 'FIR_P3'):
            selected = [r for r in rows if r['dataset'] == dataset and r['method'] == method
                        and r['reference'] == 'P3']
            pooled = {k: sum(r[k] for r in selected) for k in keys}
            out.append(dict(dataset=dataset, method=method, aggregation='POOLED',
                            **pooled, **rates(pooled)))
            waveforms = []
            for identifier in sorted({r['case_id'] for r in selected}):
                group = [r for r in selected if r['case_id'] == identifier]
                waveforms.append(rates({k: sum(r[k] for r in group) for k in keys}))
            macro = {k: float(np.mean([w[k] for w in waveforms if w[k] is not None]))
                     if any(w[k] is not None for w in waveforms) else None for k in rates(pooled)}
            out.append(dict(dataset=dataset, method=method, aggregation='WAVEFORM_MACRO', **macro))
    return out


def performance_gate(rows: list[dict[str, Any]]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    summaries = aggregate(rows)
    for dataset in ('CORE', 'OBVIOUS'):
        for aggregation in ('POOLED', 'WAVEFORM_MACRO'):
            base, new = [next(r for r in summaries if r['dataset'] == dataset
                and r['aggregation'] == aggregation and r['method'] == name)
                for name in ('P3', 'FIR_P3')]
            key = dataset+'_'+aggregation
            rmse_gain = new['rmse_hz'] <= .9*base['rmse_hz']
            wrong_gain = base['wrong_branch'] > 0 and new['wrong_branch'] <= .9*base['wrong_branch']
            checks[key+'_accuracy'] = bool((rmse_gain and new['wrong_branch'] <=
                1.01*base['wrong_branch']) or (wrong_gain and new['rmse_hz'] <= 1.01*base['rmse_hz']))
            checks[key+'_coverage'] = all(new[k] >= base[k] for k in ('coverage', 'truth_coverage'))
            checks[key+'_normal'] = new['normal_preservation'] is not None and new['normal_preservation'] >= .99
            checks[key+'_fast'] = new['fast_preservation'] is None or new['fast_preservation'] >= .99
            checks[key+'_no_info'] = (new['no_information_false_track_rate'] is None or
                new['no_information_false_track_rate'] <= base['no_information_false_track_rate'])
            if dataset == 'OBVIOUS':
                checks[key+'_jump'] = (new['obvious_jump_correction_rate'] is not None and
                    new['obvious_jump_correction_rate'] >= base['obvious_jump_correction_rate']+.10)
        # Harm rates have the SAME strongest reference for both methods.
        for name in ('P3', 'FIR_P3'):
            chosen = [r for r in rows if r['dataset'] == dataset and r['method'] == name
                      and r['reference'] == 'strongest']
            values = [sum(r[k] for r in chosen) for k in ('harmed_frames', 'interventions', 'truth_frames')]
            if name == 'P3':
                old_harm = values
            else:
                checks[dataset+'_harm_fraction'] = values[0]/values[2] <= old_harm[0]/old_harm[2]
                checks[dataset+'_harm_rate'] = values[0]/max(values[1], 1) <= old_harm[0]/max(old_harm[1], 1)
        for profile in {r['profile'] for r in rows}:
            chosen = [r for r in rows if r['dataset'] == dataset and r['profile'] == profile
                      and r['reference'] == 'P3']
            for name in ('P3', 'FIR_P3'):
                part = [r for r in chosen if r['method'] == name]
                cs = {k: sum(r[k] for r in part) for k in ('frames', 'truth_frames', 'selected',
                      'truth_selected', 'normal_frames', 'normal_preserved', 'fast_frames', 'fast_preserved')}
                if name == 'P3':
                    old_counts = cs
                else:
                    checks[dataset+'_'+profile+'_coverage'] = (cs['selected'] >= old_counts['selected']
                                              and cs['truth_selected'] >= old_counts['truth_selected'])
                    checks[dataset+'_'+profile+'_normal'] = cs['normal_preserved'] >= .99*cs['normal_frames']
                    checks[dataset+'_'+profile+'_fast'] = cs['fast_preserved'] >= .99*cs['fast_frames']
    return checks


def held_out(output: Path) -> None:
    verify_freeze(output)
    m.require_gate(read_json(output / 'safety_gate.json'))
    write_json(output / 'held_out_started.json', {'unix_time': time.time()})
    activation = read_json(output / 'baseline_definition.json')
    rows = []
    for row in read_json(output / 'seed_registration.json'):
        if row['dataset'] == 'SAFETY':
            continue
        case = case_for(row)
        raw = case.record
        original_hash = (array_hash(raw.time_s), array_hash(raw.voltage_v))
        filtered = m.preprocess(raw)
        with (output / 'waveforms' / (case.case_id+'.npz')).open('xb') as handle:
            np.savez_compressed(handle, time_s=raw.time_s, voltage_v=raw.voltage_v,
                filtered_v=filtered.voltage_v, truth_hz=case.truth_hz, nuisance_hz=case.nuisance_hz)
        for profile in PROFILES:
            start = time.perf_counter()
            stft, peaks = m.frontend(raw, profile)
            fstft, fpeaks = m.frontend(filtered, profile)
            assert np.array_equal(stft.time_s, fstft.time_s)
            s = m.strongest(peaks)
            p3 = m.frozen_p3(stft, peaks, activation)
            new = m.frozen_p3(fstft, fpeaks, activation)
            elapsed = time.perf_counter()-start
            ix = np.rint(stft.time_s*SAMPLE_RATE_HZ).astype(int)
            truth = case.truth_hz[ix]
            valid = np.isfinite(truth)
            slope = abs(np.gradient(truth, stft.time_s))
            normal = valid & (abs(s-truth) <= 200e6) & (slope < 5e15)
            fast = valid & (slope >= 5e15) & (abs(p3-truth) <= 200e6)
            no_info = np.asarray([np.all(~np.isfinite(case.truth_hz[max(0, j-
                profile.window_length_samples//2):j+profile.window_length_samples//2])) for j in ix])
            large = abs(np.diff(s)) > 450e6
            jump = valid & (abs(s-truth) > 200e6) & (np.r_[False, large] | np.r_[large, False])
            jump &= case.focus[ix] & (case.family in ('O2', 'O3', 'O4', 'O5'))
            arrays: dict[str, Any] = dict(time_s=stft.time_s, truth_hz=truth, strongest=s,
                P3=p3, FIR_P3=new, normal=normal, fast=fast, no_info=no_info, obvious_jump=jump,
                quality=np.full(len(s), 'HYPOTHESIS_UNCALIBRATED'))
            for name, path, provenance in [('strongest', s, peaks), ('P3', p3, peaks),
                                            ('FIR_P3', new, fpeaks)]:
                for ref_name, reference in [('strongest', s), ('P3', p3)]:
                    rows.append(dict(**row, case_id=case.case_id, profile=profile.profile_id.value,
                        method=name, reference=ref_name, elapsed_s=elapsed,
                        **counts(path, reference, truth, normal, fast, no_info, jump, provenance)))
                arrays[name+'_candidates_hz'] = np.asarray([[p.transition_frequency_hz for p in frame]
                    + [np.nan]*(20-len(frame)) for frame in provenance.candidates_by_frame])
            if case.family == 'O8':
                arrays['swapped_truth_hz'] = case.nuisance_hz[ix]
                arrays['identity_claim'] = np.asarray(False)
            with (output / 'streams' / (case.case_id+'_'+profile.profile_id.value+'.npz')).open('xb') as h:
                np.savez_compressed(h, **arrays)
        assert original_hash == (array_hash(raw.time_s), array_hash(raw.voltage_v))
        print('HELD_OUT', case.case_id, flush=True)
    write_csv(output / 'synthetic_results.csv', [r for r in rows if r['dataset'] == 'CORE'])
    write_csv(output / 'obvious_error_benchmark.csv', [r for r in rows if r['dataset'] == 'OBVIOUS'])
    write_csv(output / 'aggregate_metrics.csv', aggregate(rows))
    gate = performance_gate(rows)
    write_json(output / 'performance_gate.json', gate)
    if not all(gate.values()):
        reason = 'PERFORMANCE_GATE_FAILED; no retuning, real/ch3 forbidden'
        write_csv(output / 'real_data_behavior.csv', [dict(status='SKIPPED', reason=reason)])
        write_json(output / 'skipped_stages.json', dict(real=reason, ch3=reason))
    write_json(output / 'held_out_completed.json', {'unix_time': time.time(), 'rows': len(rows)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    held_out(parser.parse_args().output.resolve())
