"""Fixed controlled oscillator grid, reference bound and identity-swap controls."""
from __future__ import annotations

import argparse
import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.core.models import SignalRecord
from dps_studio.research import task023f_proposals as f
from dps_studio.research import task023h_raw_evidence as e
from dps_studio.research.task023e_waveform_benchmark import (
    PROFILES, SAMPLE_COUNT, SAMPLE_RATE_HZ, WaveformCase, ambiguous_pair, array_hash,
    oscillator_phase, profile_input,
)
from scripts import run_task023f_proposal_recovery as r
from scripts.run_task023h_raw_audit import configs, freeze_evidence


def controlled_case(separation_mhz: float, snr_db: float, ratio: float,
                    chirp: float, fade: float) -> WaveformCase:
    """Same sampled oscillator/Gaussian observation model; controlled I2 only.

    No change to generate_case or the fresh benchmark distribution.
    """
    t = np.arange(SAMPLE_COUNT)/SAMPLE_RATE_HZ
    target = np.full(SAMPLE_COUNT, 2.4e9)
    nuisance = target + separation_mhz*1e6 + chirp*np.clip(t-1e-6, -32e-9, 32e-9)
    amplitude = np.ones(SAMPLE_COUNT)
    focus = abs(t-1e-6) <= 32e-9
    amplitude[focus] = 1-fade
    noise_sd = float(np.sqrt(.5 / 10**(snr_db/10)))
    voltage = amplitude*np.cos(oscillator_phase(target))
    voltage += ratio*np.cos(oscillator_phase(nuisance, phase0=.7))
    voltage += noise_sd*np.random.default_rng(24081000).normal(size=SAMPLE_COUNT)
    identifier = f'I2_d{separation_mhz}_s{snr_db}_a{ratio}_c{chirp}_f{fade}'
    return WaveformCase(identifier, 'CONTROLLED_TWO_COMPONENT', 0, 'CONTROLLED_DIAGNOSTIC',
        24081000, SignalRecord(t, voltage, source_path='synthetic/'+identifier+'.npz'),
        target, nuisance, focus, dict(separation_mhz=separation_mhz, snr_db=snr_db,
        amplitude_ratio=ratio, chirp_difference_hz_per_s=chirp, fade_depth=fade,
        noise_sd_v=noise_sd, target_amplitude_v=1-fade), identifier)


def sweep_case(output: Path, values: tuple[float, ...]) -> list[dict[str, Any]]:
    case = controlled_case(*values)
    target_file = output/'sweep'/(case.case_id+'.json')
    if target_file.exists():
        import json
        return list(json.loads(target_file.read_text()))
    analytic = e.analytic_signal(case.record.time_s, case.record.voltage_v)
    ambiguity, config = configs()
    rows = []
    for profile in PROFILES:
        stft, candidates, truth, _ = profile_input(case, profile)
        frame = int(np.argmin(abs(candidates.time_s-1e-6)))
        raw_frame = int(np.rint(candidates.time_s[frame]*SAMPLE_RATE_HZ))
        target_f, other_f = float(truth[frame]), float(case.nuisance_hz[raw_frame])
        sep = abs(target_f-other_f)
        tolerance = min(200e6, sep/2)
        near = [[c.candidate_rank for c in candidates.candidates_by_frame[frame]
                 if abs(c.transition_frequency_hz-freq) < tolerance] for freq in (target_f, other_f)]
        candidate_separable = any(i != j for i in near[0] for j in near[1])
        duration = profile.window_length_samples/SAMPLE_RATE_HZ
        mask = abs(case.record.time_s-1e-6) <= duration/2
        scores = [e.demodulated_evidence(case.record.time_s[mask], analytic[mask], freq[mask],
            duration).row() for freq in (case.truth_hz, case.nuisance_hz)]
        original = r.original_e4(candidates, stft)
        broadband = f.broadband_evidence(stft)
        registry = f.windows(original, f.ProposalConfig(), ambiguity)
        # Only query frozen registered windows touching the central analysis window.
        windows = [w for w in registry if w.anchor is not None and frame in w.indices]
        proposal_matches: list[list[tuple[str, int, tuple[float, ...]]]] = [[], []]
        offered = 0
        for window in windows:
            search = f.generate_proposals(window, original, candidates, ambiguity,
                config, broadband, diversity=True)
            offered += len(search.proposals)
            for proposal in search.proposals:
                ix = list(window.indices)
                raw_ix = np.rint(candidates.time_s[ix]*SAMPLE_RATE_HZ).astype(int)
                for j, freq in enumerate((case.truth_hz[raw_ix], case.nuisance_hz[raw_ix])):
                    if np.all(abs(np.asarray(proposal.state.frequencies_hz)-freq) <= 200e6):
                        proposal_matches[j].append((window.window_id, proposal.hypothesis_id,
                                                    proposal.state.frequencies_hz))
        distinct_proposals = any(i[:2] != j[:2] and i[2] != j[2]
            for i in proposal_matches[0] for j in proposal_matches[1])
        row = dict(**case.parameters, waveform=case.case_id, profile=profile.profile_id.value,
            raw_sha256=array_hash(case.record.voltage_v), central_frame=frame,
            actual_separation_hz=sep, candidate_tolerance_hz=tolerance,
            candidate_separable=candidate_separable, candidate_ranks=near,
            registered_windows=len(windows), generated_proposals=offered,
            proposal_separable=distinct_proposals,
            proposal_scope='DISTINCT_FULL_GENERATED_HISTORIES_200MHZ; tolerance overlaps at small separation',
            target_proposal_matches=len(proposal_matches[0]), nuisance_proposal_matches=len(proposal_matches[1]),
            supplied_template_scope='KNOWN_PHYSICAL_FREQUENCY_TEMPLATES; NOT_GENERATED_PROPOSALS',
            reference_sigma_f_hz=e.single_component_reference(case.record.time_s[mask],
                float(case.parameters['target_amplitude_v']), float(case.parameters['noise_sd_v'])),
            reference_status='REFERENCE_ONLY_SINGLE_COMPONENT_LOCAL_STATIONARY',
            identity_status='TARGET_LABEL_NOT_IDENTIFIED_BY_COMPONENT_SUPPORT')
        for feature in e.FEATURES:
            delta = float(scores[0][feature]-scores[1][feature])
            row.update({feature+'_target': scores[0][feature], feature+'_nuisance': scores[1][feature],
                feature+'_difference': delta, feature+'_near_tie': abs(delta) <= .01,
                feature+'_prefers_target': delta > 1e-12})
        rows.append(row)
    r.write_json(target_file, rows)
    return rows


def identity_audit(output: Path) -> None:
    rows = []
    examples = []
    for index in range(16):
        first, second = ambiguous_pair(index)
        for profile in PROFILES:
            scores = []
            for case in (first, second):
                z = e.analytic_signal(case.record.time_s, case.record.voltage_v)
                mask = abs(case.record.time_s-1e-6) <= profile.window_length_samples/SAMPLE_RATE_HZ/2
                scores.append([e.demodulated_evidence(case.record.time_s[mask], z[mask], freq[mask],
                    profile.window_length_samples/SAMPLE_RATE_HZ).row()
                    for freq in (first.truth_hz, second.truth_hz)])
            assert scores[0] == scores[1]
            for proposal in range(2):
                row = dict(observation_group=first.observation_group, profile=profile.profile_id.value,
                    proposal_id=proposal, observation_identical=True, evidence_identical=True,
                    target_identity_A=0, target_identity_B=1,
                    status='OBSERVATIONALLY_NON_IDENTIFIABLE',
                    voltage_sha256=array_hash(first.record.voltage_v))
                for feature in e.FEATURES:
                    row[feature+'_label_A'] = scores[0][proposal][feature]
                    row[feature+'_label_B'] = scores[1][proposal][feature]
                rows.append(row)
            if index == 0:
                examples.append(dict(profile=profile.profile_id.value,
                    time_s=first.record.time_s[mask].tolist(),
                    voltage_v=first.record.voltage_v[mask].tolist(),
                    template_frequencies_hz=[float(first.truth_hz[0]), float(second.truth_hz[0])],
                    scores=scores))
    r.write_csv(output/'identity_swap_audit.csv', rows)
    r.write_json(output/'identity_swap_example.json', examples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    output = args.output.resolve()
    freeze_evidence(output)
    (output/'sweep').mkdir(exist_ok=True)
    grid = list(itertools.product([0.,25.,50.,100.,200.,400.], [-10.,0.,10.,20.],
        [.5,1.,2.], [-2e15,0.,2e15], [0.,.8]))
    if not (output/'identifiability_grid_registration.json').exists():
        r.write_json(output/'identifiability_grid_registration.json', grid)
    if not (output/'identity_swap_audit.csv').exists():
        identity_audit(output)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(sweep_case, output, values) for values in grid]
        for i, future in enumerate(as_completed(jobs), 1):
            rows.extend(future.result())
            print(f'SWEEP {i}/{len(jobs)}', flush=True)
    rows.sort(key=lambda v: (v['waveform'], v['profile']))
    r.write_csv(output/'identifiability_sweep.csv', rows)


if __name__ == '__main__':
    main()
