"""Post-gate frozen-selector evaluation; labels only reach metrics, never proposals."""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.figure import Figure

from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_audit as a
from dps_studio.research import task023f_proposals as f
from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, PROFILES, SAMPLE_RATE_HZ, ambiguous_pair, profile_input,
)
from scripts import run_task023f_proposal_recovery as runner


def searches_for_variant(cache: dict[tuple[str, str], f.SearchResult], variant: str,
                         activation: dict[str, Any]) -> tuple[f.SearchResult, ...]:
    core = variant in ('P1', 'P3') and activation['core']
    mode = 'DIVERSITY_B8' if variant in ('P2', 'P3') and activation['diversity'] else 'B8'
    return tuple(search for (_, method), search in cache.items()
                 if method == mode and (core or search.window.kind == 'EDGE'))


def artifact_stem(output: Path, context: dict[str, Any]) -> str:
    base = f'{context["case_id"]}_{context["profile"]}'
    paths = sorted((output / 'lineages').glob(base + '*.pickle.gz'))
    return paths[-1].name.removesuffix('.pickle.gz')


def load_searches(output: Path, context: dict[str, Any]) -> dict[tuple[str, str], f.SearchResult]:
    with gzip.open(output / 'lineages' / (artifact_stem(output, context) + '.pickle.gz'), 'rb') as handle:
        value: dict[str, Any] = pickle.load(handle)
    return dict(value['searches'])


def final_synthetic(output: Path, activation: dict[str, Any]) -> None:
    target = output / 'final_streams'
    target.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        for instance in range(8, 24):
            case = runner.fresh_case(family, instance)
            for profile in PROFILES:
                context = dict(case_id=case.case_id, observation_group=case.observation_group,
                               family=family, profile=profile.profile_id.value, stage='FRESH')
                identifier = f'{case.case_id}_{profile.profile_id.value}'
                saved = target / (identifier + '.json')
                if saved.exists():
                    rows.extend(json.loads(saved.read_text(encoding='utf-8')))
                    continue
                stft, candidates, truth, focus = profile_input(case, profile)
                original = runner.original_e4(candidates, stft)
                e3 = runner.original_e4(candidates, stft, d.SmoothBranchMethod.E3_CORE_TRIM_BRANCH)
                ambiguity = d.BranchAmbiguityConfig(**activation['config']['ambiguity_config'])
                config = d.BranchCompetitionConfig(**activation['effective_e4'])
                broadband = f.broadband_evidence(stft)
                cache = load_searches(output, context)
                strongest = original.task023c.strongest.frequency_hz
                methods: dict[str, np.ndarray] = dict(strongest=strongest,
                    TASK023C=original.task023c.final_frequency_hz, E3_REFERENCE=e3.final_frequency_hz)
                details: dict[str, Any] = dict(strongest_frequency_hz=strongest, time_s=stft.time_s)
                nuisance = case.nuisance_hz[np.rint(stft.time_s * SAMPLE_RATE_HZ).astype(int)]
                funnel: dict[str, Any] = {}
                for variant in ('P0', 'P1', 'P2', 'P3'):
                    searches = searches_for_variant(cache, variant, activation)
                    result = f.apply_searches(searches, original, candidates, ambiguity, config, broadband)
                    methods[variant] = result.final_frequency_hz
                    for key in ('final_frequency_hz', 'final_rank', 'permission_mask', 'accepted_mask'):
                        details[variant + '_' + key] = getattr(result, key)
                    funnel[variant] = a.audit(candidates, truth, nuisance, original, searches,
                        f.windows(original, f.ProposalConfig(), ambiguity),
                        4 * SAMPLE_RATE_HZ / profile.window_length_samples, result).summary
                    runner.write_csv(target / (identifier + '_' + variant + '_selection.csv'), [
                        dict(window_id=search.window.window_id, selected_proposal=selection.selected_proposal,
                             status=selection.status, margin=selection.margin,
                             accepted_frames=sum(selection.accepted))
                        for search, selection in zip(searches, result.selections, strict=True)])
                per_stream = []
                # Fixed physical regions; edge: first/last 150 ns and strongest truth-near.
                correct = np.isfinite(truth) & (np.abs(strongest - truth) <= a.TOLERANCE_HZ)
                edge = correct & ((stft.time_s <= 150e-9) | (stft.time_s >= 2e-6 - 150e-9))
                fast = correct & (np.abs(np.gradient(truth, stft.time_s)) >= 5e15)
                for method, path in methods.items():
                    old, error = np.abs(strongest - truth), np.abs(path - truth)
                    row = {**context, 'method': method, **a.metrics(strongest, path, truth),
                        'correct_edge_frames': int(np.sum(edge)),
                        'correct_edge_modified': int(np.sum(edge & (path != strongest))),
                        'correct_edge_harmed': int(np.sum(edge & (error > old))),
                        'fast_descent_frames': int(np.sum(fast)),
                        'fast_descent_harmed': int(np.sum(fast & (error > old)))}
                    if method in funnel:
                        row.update(funnel[method])
                    per_stream.append(row)
                with (target / (identifier + '.npz')).open('xb') as handle:
                    np.savez_compressed(handle, **details)
                runner.write_json(saved, per_stream)
                rows.extend(per_stream)
                print('FINAL ' + identifier, flush=True)
    runner.write_csv(output / 'fresh_heldout_comparison.csv', rows)


def ambiguity_pairs(output: Path, activation: dict[str, Any], final_allowed: bool) -> None:
    rows = []
    for index in range(16):
        first, second = ambiguous_pair(index)
        assert np.array_equal(first.record.voltage_v, second.record.voltage_v)
        for profile in PROFILES:
            stft, candidates, _, _ = profile_input(first, profile)
            original = runner.original_e4(candidates, stft)
            ambiguity = d.BranchAmbiguityConfig(**activation['config']['ambiguity_config'])
            config = d.BranchCompetitionConfig(**activation['effective_e4'])
            broadband = f.broadband_evidence(stft)
            cache = {}
            for window in f.windows(original, f.ProposalConfig(), ambiguity):
                if window.kind == 'CORE' and not activation['core']:
                    continue
                for mode in (('B8', 'DIVERSITY_B8') if activation['diversity'] else ('B8',)):
                    cache[window.window_id, mode] = f.generate_proposals(window, original, candidates,
                        ambiguity, config, broadband, diversity=mode == 'DIVERSITY_B8')
            for variant in ('P0', 'P1', 'P2', 'P3'):
                searches = searches_for_variant(cache, variant, activation)
                final = (f.apply_searches(searches, original, candidates, ambiguity, config, broadband)
                         if final_allowed else None)
                # Both labels share this exact GT-free call. No classification of target
                # identity is emitted: strongest remains a fallback, not a label.
                rows.append(dict(observation_group=first.observation_group, profile=profile.profile_id.value,
                    variant=variant, labels='A;B', observation_equal=True,
                    proposal_behavior_equal=True, final_behavior_equal=True if final else None,
                    final_status='RUN_IDENTICAL_INPUT' if final else 'SKIPPED_PROPOSAL_GATE',
                    proposals=sum(len(s.proposals) for s in searches),
                    modifications=int(np.sum(final.final_frequency_hz != final.strongest_frequency_hz))
                                  if final else None,
                    identity_status='UNIDENTIFIABLE_FROM_OBSERVATION',
                    output_identity_claim=False))
    runner.write_csv(output / 'ambiguity_pair_summary.csv', rows)


def plot_overlay(path: Path, stft: Any, original: np.ndarray,
                 methods: dict[str, np.ndarray], title: str) -> None:
    figure = Figure(figsize=(12, 5), layout='constrained')
    axis = figure.subplots()
    magnitude = np.abs(stft.spectrum)
    db = 20 * np.log10(np.maximum(magnitude, np.finfo(float).tiny) / max(float(magnitude.max()), 1e-300))
    axis.pcolormesh(stft.time_s * 1e9, stft.frequency_hz / 1e9, db, vmin=-55, vmax=0,
                    cmap='magma', shading='auto', rasterized=True)
    axis.plot(stft.time_s * 1e9, original / 1e9, color='white', lw=.7, label='strongest')
    for name, values in methods.items():
        axis.plot(stft.time_s * 1e9, values / 1e9, lw=.8, label=name)
    axis.set(xlabel='Time / ns', ylabel='Frequency / GHz', ylim=(.05, 6), title=title)
    axis.legend()
    figure.savefig(path, dpi=150)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ambiguity-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    activation = json.loads((output / 'frozen_activation.json').read_text(encoding='utf-8'))
    gate = json.loads((output / 'fresh_proposal_gate.json').read_text(encoding='utf-8'))
    if args.ambiguity_only:
        ambiguity_pairs(output, activation, bool(gate['passed']))
    elif not gate['passed']:
        raise RuntimeError('Final algorithm evaluation forbidden: proposal gate failed')
    else:
        final_synthetic(output, activation)


if __name__ == '__main__':
    main()
