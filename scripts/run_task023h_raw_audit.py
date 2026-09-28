"""Run frozen raw-domain evidence audits; resume only completed immutable streams."""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023g_retention_audit as g
from dps_studio.research import task023h_pair_audit as a
from dps_studio.research import task023h_raw_evidence as e
from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, PROFILES, SAMPLE_RATE_HZ, WaveformCase, array_hash, generate_case, profile_input,
)
from scripts import run_task023f_proposal_recovery as r
from scripts.finalize_task023f_recovery import read_csv

PRIOR = r.ROOT / 'artifacts/task023f_proposal_recall_recovery/20260912T100142Z'
G_PRIOR = r.ROOT / 'artifacts/task023g_beam_retention_interval_gate/20260913T082646Z'


def fresh_case(family: str, instance: int) -> WaveformCase:
    case = generate_case(family, instance, seed=2408000 + 100*FAMILIES.index(family) + instance)
    identifier = f'H23_{family}_{instance:02d}'
    return replace(case, case_id=identifier, observation_group=identifier, split='FRESH_HELD_OUT')


def configs() -> tuple[d.BranchAmbiguityConfig, d.BranchCompetitionConfig]:
    frozen = r.frozen_configs()
    return (d.BranchAmbiguityConfig(**frozen['ambiguity_config']),
            f.effective_e4(d.BranchCompetitionConfig(**frozen['branch_config'])))


def context_for(case: WaveformCase, profile: str, role: str) -> dict[str, Any]:
    return dict(waveform=case.case_id, observation_group=case.observation_group,
        family=case.family, variant=case.parameters['variant'], instance=case.instance,
        seed=case.seed, profile=profile, role=role, voltage_sha256=array_hash(case.record.voltage_v),
        noise_sd_v=case.parameters['noise_sd_v'],
        unfaded_target_snr_db=float(10*np.log10(.5/case.parameters['noise_sd_v']**2)),
        amplitude_ratio=case.parameters['amplitude_ratio'])


def support_rows(case: WaveformCase, time: e.FloatArray, strongest: e.FloatArray,
                 analytic: e.ComplexArray, window_s: float, context: dict[str, Any],
                 ) -> list[dict[str, Any]]:
    rows = []
    raw = case.record.time_s
    for i, (center, freq) in enumerate(zip(time, strongest, strict=True)):
        mask = (raw >= center-window_s/2) & (raw < center+window_s/2)
        score = e.demodulated_evidence(raw[mask], analytic[mask],
            np.full(int(mask.sum()), freq), window_s)
        raw_index = int(np.argmin(abs(raw-center)))
        rows.append(dict(**context, frame=i, time_s=float(center), frequency_hz=float(freq),
            target_present=bool(np.isfinite(case.truth_hz[raw_index])), **score.row()))
    return rows


def fresh_stream(output: Path, family: str, instance: int) -> dict[str, Any]:
    case = fresh_case(family, instance)
    target = output / 'streams' / (case.case_id + '.json')
    if target.exists():
        return dict(json.loads(target.read_text(encoding='utf-8')))
    waveform_path = output / 'waveforms' / (case.case_id + '.npz')
    if not waveform_path.exists():
        with waveform_path.open('xb') as handle:
            np.savez_compressed(handle, time_s=case.record.time_s, voltage_v=case.record.voltage_v,
                truth_hz=case.truth_hz, nuisance_hz=case.nuisance_hz, focus=case.focus)
    before = array_hash(case.record.voltage_v)
    analytic = e.analytic_signal(case.record.time_s, case.record.voltage_v)
    ambiguity, config = configs()
    rows, pairs, ledger, support = [], [], [], []
    for profile in PROFILES:
        stft, candidates, truth, _ = profile_input(case, profile)
        original = r.original_e4(candidates, stft)
        strongest = original.task023c.strongest.frequency_hz
        frozen_before = a.fingerprint((candidates, stft.spectrum, original))
        broadband = f.broadband_evidence(stft)
        registry = f.windows(original, f.ProposalConfig(), ambiguity)
        searches = tuple(f.generate_proposals(window, original, candidates, ambiguity,
            config, broadband, diversity=True) for window in registry
            if window.indices and window.anchor is not None)
        graph_file = output / 'lineages' / (case.case_id+'_'+profile.profile_id.value+'.pickle.gz')
        if not graph_file.exists():
            with gzip.open(graph_file, 'xb', compresslevel=1) as handle:
                pickle.dump(dict(searches=searches, registry=registry), handle, protocol=5)
        context = context_for(case, profile.profile_id.value, 'FRESH')
        context['candidate_sha256'] = a.fingerprint(candidates)
        context['proposal_sha256'] = a.fingerprint(searches)
        context['stft_sha256'] = array_hash(stft.spectrum)
        valid = np.isfinite(truth)
        available = a.candidate_availability(candidates, truth)
        wrong = valid & (abs(strongest-truth) > 200e6)
        rows.append(dict(**context, truth_frames=int(valid.sum()),
            available_truth_frames=int((valid & available).sum()),
            strongest_error_frames=int(wrong.sum()),
            available_error_frames=int((wrong & available).sum()),
            recall_all=float(available[valid].mean()) if valid.any() else None,
            recall_error=float(available[wrong].mean()) if wrong.any() else None,
            top_k=20, window_samples=profile.window_length_samples,
            overlap=profile.overlap_samples, hop=128, nfft=profile.nfft,
            terminal_proposals=sum(len(s.proposals) for s in searches)))
        replays = {s.window.window_id: g.Replay(s, original, candidates, ambiguity, config, broadband)
                   for s in searches}
        found, events = a.audit_searches(searches, candidates, truth, strongest,
            case.record.time_s, analytic, profile.window_length_samples/SAMPLE_RATE_HZ,
            context, replays)
        pairs.extend(found)
        ledger.extend(events)
        support.extend(support_rows(case, candidates.time_s, strongest, analytic,
            profile.window_length_samples/SAMPLE_RATE_HZ, context))
        assert a.fingerprint((candidates, stft.spectrum, original)) == frozen_before
    assert before == array_hash(case.record.voltage_v)
    result = dict(recall=rows, pairs=pairs, ledger=ledger, support=support)
    r.write_json(target, result)
    return result


def legacy_stream(output: Path, identifier: str, events: list[dict[str, Any]],
                   sources: list[dict[str, Any]]) -> dict[str, Any]:
    target = output / 'streams' / (identifier + '_legacy.json')
    if target.exists():
        return dict(json.loads(target.read_text(encoding='utf-8')))
    context_old = json.loads((PRIOR/'streams'/(identifier+'.json')).read_text())['context']
    case = r.fresh_case(context_old['family'], context_old['instance'])
    profile = next(p for p in PROFILES if p.profile_id.value == context_old['profile'])
    stft, candidates, truth, _ = profile_input(case, profile)
    original = r.original_e4(candidates, stft)
    ambiguity, config = configs()
    broadband = f.broadband_evidence(stft)
    with gzip.open(PRIOR/'lineages'/(identifier+'.pickle.gz'), 'rb') as handle:
        saved = pickle.load(handle)
    searches = tuple(s for (window, mode), s in saved['searches'].items() if mode == 'DIVERSITY_B8')
    replays = {s.window.window_id: g.Replay(s, original, candidates, ambiguity, config, broadband)
               for s in searches}
    for event in events:
        event['source_frames'] = [int(row['frame']) for row in sources
            if row['window'] == event['window'] and row['first_loss_frame'] == event['first_loss_frame']
            and row['lineage_id'] == event['lineage_id']]
    context = context_for(case, profile.profile_id.value, 'LEGACY_DIAGNOSTIC')
    context['candidate_sha256'] = a.fingerprint(candidates)
    context['proposal_sha256'] = a.fingerprint(searches)
    # G CSV rows repeat stream metadata; the H auditor adds its own explicit
    # scope/role. Strip duplicate serialization fields, leaving taxonomy/IDs intact.
    events = [{key: value for key, value in event.items()
               if key not in context and key not in ('scope', 'stage', 'pair_available',
                                                     'exclusion_reason')}
              for event in events]
    pairs, ledger = a.audit_searches(searches, candidates, truth,
        original.task023c.strongest.frequency_hz, case.record.time_s,
        e.analytic_signal(case.record.time_s, case.record.voltage_v),
        profile.window_length_samples/SAMPLE_RATE_HZ, context, replays, events)
    value = dict(pairs=pairs, ledger=ledger)
    r.write_json(target, value)
    return value


def freeze_evidence(output: Path) -> None:
    target = output / 'evidence_code_freeze.json'
    paths = [r.ROOT/'src/dps_studio/research'/name for name in (
        'task023h_raw_evidence.py', 'task023h_pair_audit.py', 'task023e_waveform_benchmark.py',
        'task023f_proposals.py', 'task023g_retention_audit.py')]
    hashes = {str(p.relative_to(r.ROOT)): r.sha256(p) for p in paths}
    if target.exists():
        assert json.loads(target.read_text())['hashes'] == hashes, 'Frozen computation changed'
    else:
        r.write_json(target, dict(hashes=hashes, before_fresh_observation=True,
            four_features=list(e.FEATURES), no_real_tuning=True))
        with (output/'protocol_clarification_before_observation.md').open('x', encoding='utf-8') as h:
            h.write('The I1 formula to use is the explicitly labelled latter expression in protocol.md: '
                'sigma_f=sqrt(2 sigma_noise^2 / (A^2 (2 pi)^2 sum((t-mean(t))^2))). '
                'The preceding draft expression is a transcription error and is not used. '
                'This clarification precedes fresh/sweep/real generation and score inspection.\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=['fresh', 'legacy'], default='fresh')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    freeze_evidence(output)
    jobs = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        if args.phase == 'fresh':
            jobs = [pool.submit(fresh_stream, output, family, i)
                    for family in FAMILIES for i in range(8, 24)]
        else:
            events = [v for v in read_csv(G_PRIOR/'beam_lineage_audit.csv')
                      if v['role'] == 'LEGACY_DIAGNOSTIC']
            frames = [v for v in read_csv(G_PRIOR/'retention_failure_taxonomy.csv')
                      if v['role'] == 'LEGACY_DIAGNOSTIC']
            keys = sorted({(v['waveform'], v['profile']) for v in events})
            jobs = [pool.submit(legacy_stream, output, waveform+'_'+profile,
                [v for v in events if (v['waveform'], v['profile']) == (waveform, profile)],
                [v for v in frames if (v['waveform'], v['profile']) == (waveform, profile)])
                for waveform, profile in keys]
        failures = []
        for i, future in enumerate(as_completed(jobs), 1):
            try:
                value = future.result()
                print(f'{args.phase} {i}/{len(jobs)} pairs={len(value["pairs"])}', flush=True)
            except Exception as error:
                failures.append(repr(error))
                print(f'FAILED {error!r}', flush=True)
        if failures:
            raise RuntimeError(str(failures))


if __name__ == '__main__':
    main()
