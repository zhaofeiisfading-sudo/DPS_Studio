"""Conditional Research-raw evaluation of frozen TASK-023F; no accuracy labels."""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.core.ridge import GlobalPathConfig
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f
from dps_studio.research.global_path_calibration import candidate_set_for_top_k
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH, formal_read_input, prepare_streams,
)
from scripts import run_task023f_proposal_recovery as runner
from scripts.evaluate_task023f_frozen import plot_overlay, searches_for_variant


def evaluate(output: Path) -> None:
    gate = json.loads((output / 'fresh_proposal_gate.json').read_text(encoding='utf-8'))
    if not gate['passed'] or not (output / 'evaluation_source_manifest.json').exists():
        raise RuntimeError('Real evaluation requires passed proposal gate and frozen evaluation configuration')
    activation = json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
    ambiguity = d.BranchAmbiguityConfig(**activation['config']['ambiguity_config'])
    config = d.BranchCompetitionConfig(**activation['effective_e4'])
    raw = runner.ROOT / 'data/raw'
    before = {str(p.relative_to(raw)): runner.sha256(p) for p in raw.rglob('*') if p.is_file()}
    workflow = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=runner.ROOT)
    folder = output / 'real_streams'
    folder.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for path in sorted(raw.rglob('*')):
        if not path.is_file():
            continue
        eligible = runner.eligible_raw(path, raw)
        inventory.append(dict(path=str(path.resolve()), sha256_before=runner.sha256(path),
                              reader_called=eligible,
                              status='NUMERICAL_RAW' if eligible else 'EXCLUDED_BEFORE_READER'))
        if not eligible:
            continue
        formal = formal_read_input(path, workflow)
        streams, failures = prepare_streams(raw_root=raw, configuration=workflow,
                                            accepted_inputs={path: formal})
        if failures:
            raise RuntimeError(str(failures))
        for stream in streams:
            summary_file = folder / (stream.stream_id + '.json')
            if summary_file.exists():
                rows.extend(json.loads(summary_file.read_text(encoding='utf-8')))
                continue
            print('REAL ' + stream.stream_id, flush=True)
            candidates = candidate_set_for_top_k(stream.candidate_set_maximum,
                                                  config=GlobalPathConfig(top_k=20))
            stft = stream.analysis.stft_result
            original = runner.original_e4(candidates, stft)
            broadband = f.broadband_evidence(stft)
            registry = f.windows(original, f.ProposalConfig(), ambiguity)
            cache = {}
            for window in registry:
                if not window.indices or window.anchor is None:
                    continue
                if window.kind == 'CORE' and not activation['core']:
                    continue
                for mode in (('B8', 'DIVERSITY_B8') if activation['diversity'] else ('B8',)):
                    cache[window.window_id, mode] = f.generate_proposals(window, original, candidates,
                        ambiguity, config, broadband, diversity=mode == 'DIVERSITY_B8')
            paths: dict[str, np.ndarray] = {}
            stream_rows, details, branches = [], [], []
            strongest = original.task023c.strongest.frequency_hz
            p0_offered: dict[int, set[float]] = {}
            for search in searches_for_variant(cache, 'P0', activation):
                for proposal in search.proposals:
                    for frame, frequency in zip(search.window.indices, proposal.state.frequencies_hz, strict=True):
                        p0_offered.setdefault(frame, set()).add(frequency)
            suspicious = original.ambiguity.branch_ambiguity >= .36
            for window in registry:
                if window.kind == 'CORE':
                    suspicious[list(window.indices)] = True
            for variant in ('P0', 'P1', 'P2', 'P3'):
                searches = searches_for_variant(cache, variant, activation)
                result = f.apply_searches(searches, original, candidates, ambiguity, config, broadband)
                paths[variant] = result.final_frequency_hz
                if variant == 'P0':
                    assert np.array_equal(result.final_frequency_hz, original.final_frequency_hz)
                    assert np.array_equal(result.final_rank, original.final_rank)
                proposed = np.zeros(len(strongest), dtype=bool)
                additional = np.zeros(len(strongest), dtype=bool)
                for search, selection in zip(searches, result.selections, strict=True):
                    ix = list(search.window.indices)
                    for proposal in search.proposals:
                        proposed[ix] |= np.asarray(proposal.state.frequencies_hz) != strongest[ix]
                        for frame, frequency in zip(ix, proposal.state.frequencies_hz, strict=True):
                            if frequency != strongest[frame] and frequency not in p0_offered.get(frame, set()):
                                additional[frame] = True
                    branches.append(dict(stream=stream.stream_id, variant=variant,
                        window_id=search.window.window_id, kind=search.window.kind,
                        anchor=search.window.anchor, frames=len(ix),
                        duration_s=float(np.ptp(candidates.time_s[ix])) if ix else 0.,
                        proposals=len(search.proposals), selected_proposal=selection.selected_proposal,
                        acceptance=selection.status, margin=selection.margin,
                        accepted_frames=sum(selection.accepted)))
                changed = result.final_frequency_hz != strongest
                core_changed = changed & original.trimmed_core_mask
                fraction = float(np.mean(changed))
                stream_rows.append(dict(stream=stream.stream_id, source_path=str(path.resolve()),
                    source_sha256=runner.sha256(path), quality_group=stream.quality_group,
                    profile=stream.profile_id, channel=stream.channel_name, variant=variant,
                    frames=len(strongest), output_frames=int(np.sum(np.isfinite(result.final_frequency_hz))),
                    modified_frames=int(np.sum(changed)), modification_fraction=fraction,
                    suspicious_frames=int(np.sum(suspicious)),
                    human_visual_region='FULL_RECORD_DISPLAY_ONLY; no truth labels',
                    core_frames=int(np.sum(original.trimmed_core_mask)),
                    core_alternative_frames=int(np.sum(original.trimmed_core_mask & proposed)),
                    core_accepted_frames=int(np.sum(core_changed)),
                    core_challenge_windows=sum(s.window.kind == 'CORE' for s in searches),
                    proposals=sum(len(s.proposals) for s in searches),
                    additional_terminal_frames_vs_p0=int(np.sum(additional)),
                    additional_edge_terminal_frames_vs_p0=int(np.sum(additional & ~original.trimmed_core_mask)),
                    beam_rescue_interpretation='additional retention evidence; correctness unknown',
                    changed_vs_e4=int(np.sum(result.final_frequency_hz != original.final_frequency_hz)),
                    median_step_hz=float(np.median(np.abs(np.diff(result.final_frequency_hz)))),
                    maximum_jump_hz=float(np.max(np.abs(np.diff(result.final_frequency_hz)))),
                    relatively_good_risk=('good' in stream.quality_group.lower() and fraction > .05),
                    physical_correctness='UNKNOWN'))
                for i, frequency in enumerate(result.final_frequency_hz):
                    candidate = next(c for c in candidates.candidates_by_frame[i]
                                     if c.transition_frequency_hz == frequency)
                    details.append(dict(stream=stream.stream_id, variant=variant, frame=i,
                        time_s=float(candidates.time_s[i]), strongest_frequency_hz=float(strongest[i]),
                        final_frequency_hz=float(frequency), rank=int(result.final_rank[i]),
                        permission=bool(result.permission_mask[i]), accepted=bool(result.accepted_mask[i]),
                        core=bool(original.trimmed_core_mask[i]), suspicious=bool(suspicious[i]),
                        candidate_peak_to_background_db=candidate.peak_to_background_db,
                        candidate_peak_to_competitor_db=candidate.peak_to_competitor_db,
                        ambiguity=float(original.ambiguity.branch_ambiguity[i]),
                        modification_interval=next((j for j, run in enumerate(f.runs(changed)) if i in run), None)))
            runner.write_csv(folder / (stream.stream_id + '_provenance.csv'), details)
            runner.write_csv(folder / (stream.stream_id + '_branches.csv'), branches)
            with gzip.open(folder / (stream.stream_id + '_lineages.pickle.gz'), 'xb', compresslevel=1) as handle:
                pickle.dump(dict(searches=cache, registry=registry), handle, protocol=5)
            plot_overlay(output / 'figures' / (stream.stream_id + '_overlay.png'), stft, strongest,
                         paths, stream.stream_id + ' (physical target unknown)')
            runner.write_json(summary_file, stream_rows)
            rows.extend(stream_rows)
    after = {str(p.relative_to(raw)): runner.sha256(p) for p in raw.rglob('*') if p.is_file()}
    assert before == after
    assert len({row['stream'] for row in rows}) == 34
    for row in inventory:
        row['sha256_after'] = runner.sha256(Path(row['path']))
        row['unchanged'] = row['sha256_before'] == row['sha256_after']
    runner.write_csv(output / 'raw_reader_inventory.csv', inventory)
    runner.write_csv(output / 'cross_dataset_validation.csv', rows)
    runner.write_csv(output / 'ch3_proposal_audit.csv', [r for r in rows if Path(r['source_path']).stem == 'ch3'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.output.resolve())


if __name__ == '__main__':
    main()
