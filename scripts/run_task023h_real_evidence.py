"""Descriptive diagnostics of the original 34 streams, with no target labels."""
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
from dps_studio.research import task023h_pair_audit as a
from dps_studio.research import task023h_raw_evidence as e
from dps_studio.research.global_path_calibration import candidate_set_for_top_k
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH, formal_read_input, prepare_streams,
)
from scripts import run_task023f_proposal_recovery as r
from scripts.run_task023h_raw_audit import PRIOR, freeze_evidence


def evaluate(output: Path) -> None:
    freeze_evidence(output)
    workflow = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=r.ROOT)
    raw = r.ROOT/'data/raw'
    expected = {p.name.removesuffix('_lineages.pickle.gz') for p in (PRIOR/'real_streams').glob('*_lineages.pickle.gz')}
    rows: list[dict[str, Any]] = []
    inventory = []
    for path in sorted(raw.rglob('*')):
        if not path.is_file():
            continue
        before = r.sha256(path)
        if not r.eligible_raw(path, raw):
            inventory.append(dict(path=str(path), before=before, after=r.sha256(path),
                                  status='EXCLUDED_BEFORE_READER'))
            continue
        formal = formal_read_input(path, workflow)
        streams, failures = prepare_streams(raw_root=raw, configuration=workflow, accepted_inputs={path:formal})
        if failures:
            raise RuntimeError(str(failures))
        for stream in streams:
            assert stream.stream_id in expected
            target = output/'real_streams'/(stream.stream_id+'.json')
            if target.exists():
                rows.extend(json.loads(target.read_text()))
                continue
            print('REAL '+stream.stream_id, flush=True)
            record = formal.loaded.records[stream.channel_name]
            z = e.analytic_signal(record.time_s, record.voltage_v)
            profile = next(p for p in workflow.analysis.profiles if p.profile_id.value == stream.profile_id)
            duration = profile.window_length_samples * float(np.median(np.diff(record.time_s)))
            candidates = candidate_set_for_top_k(stream.candidate_set_maximum, config=GlobalPathConfig(top_k=20))
            stft = stream.analysis.stft_result
            strongest = np.asarray([frame[0].transition_frequency_hz for frame in candidates.candidates_by_frame])
            with gzip.open(PRIOR/'real_streams'/(stream.stream_id+'_lineages.pickle.gz'), 'rb') as handle:
                saved = pickle.load(handle)
            searches = tuple(s for (_, mode), s in saved['searches'].items() if mode == 'DIVERSITY_B8')
            frozen = a.fingerprint((candidates, searches, stft.spectrum, record.voltage_v))
            stream_rows = []
            common = dict(stream=stream.stream_id, profile=stream.profile_id, channel=stream.channel_name,
                source_path=str(path), source_sha256=before, scope='BEHAVIORAL_DIAGNOSTIC',
                physical_correctness='UNKNOWN', no_new_interval=True)
            for i, (center, freq) in enumerate(zip(candidates.time_s, strongest, strict=True)):
                mask = (record.time_s >= center-duration/2) & (record.time_s < center+duration/2)
                value = e.demodulated_evidence(record.time_s[mask], z[mask],
                    np.full(int(mask.sum()), freq), duration)
                node = candidates.candidates_by_frame[i][0]
                stream_rows.append(dict(**common, kind='STRONGEST_LOCAL_CONSTANT', frame=i,
                    time_s=float(center), frequency_hz=float(freq),
                    spectral_support_db=node.peak_to_background_db, **value.row()))
            for search in searches:
                frames = list(search.window.indices)
                times = candidates.time_s[frames]
                baseline = e.evidence_for_proposal(record.time_s, z, times, strongest[frames], duration)
                for proposal in search.proposals:
                    value = e.evidence_for_proposal(record.time_s, z, times,
                        np.asarray(proposal.state.frequencies_hz), duration)
                    row = dict(**common, kind='EXISTING_TERMINAL_PROPOSAL',
                        window=search.window.window_id, proposal_id=proposal.hypothesis_id,
                        time_start_s=float(min(times)), time_end_s=float(max(times)),
                        frames=frames, frequency_history_hz=list(proposal.state.frequencies_hz),
                        existing_e4_cost=proposal.state.total_cost, **value.row())
                    for feature in e.FEATURES:
                        row[feature+'_minus_strongest'] = getattr(value, feature)-getattr(baseline, feature)
                    stream_rows.append(row)
            assert a.fingerprint((candidates, searches, stft.spectrum, record.voltage_v)) == frozen
            r.write_json(target, stream_rows)
            rows.extend(stream_rows)
        after = r.sha256(path)
        assert before == after
        inventory.append(dict(path=str(path), before=before, after=after, status='READ_ONLY'))
    assert {row['stream'] for row in rows} == expected and len(expected) == 34
    r.write_csv(output/'real_data_raw_evidence.csv', rows)
    r.write_csv(output/'real_reader_inventory.csv', inventory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    evaluate(parser.parse_args().output.resolve())


if __name__ == '__main__':
    main()
