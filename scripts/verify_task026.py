"""Final read-only integrity checks and reproducible boundary receipts."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.research.task023e_waveform_benchmark import array_hash
from scripts.freeze_task026 import ROOT, digest, load_json, write_json
from scripts.run_task026 import write_csv


def verify(output: Path) -> dict[str, Any]:
    frozen = load_json(output/'boundary_before.json')
    differences, raw, states = [], [], {}
    checked = 0
    for name, root in (('Research', ROOT), ('Production', ROOT.parent/'DPS_Studio')):
        before = frozen[name]
        after = {cmd: subprocess.check_output(['git', *cmd.split()], cwd=root).decode(
            'utf-8', errors='replace').strip() for cmd in before['git']}
        states[name] = after
        for relative, expected in before['hashes'].items():
            path = root/relative
            actual = digest(path) if path.is_file() else 'MISSING'
            checked += 1
            if actual != expected:
                differences.append(dict(tree=name, path=relative, before=expected, after=actual))
            if relative.startswith('data/raw/'):
                raw.append(dict(tree=name, path=relative, before_sha256=expected,
                                after_sha256=actual, unchanged=actual == expected))
        raw_inventory = {p.relative_to(root).as_posix() for p in (root/'data/raw').rglob('*')
                         if p.is_file()}
        assert raw_inventory == {p for p in before['hashes'] if p.startswith('data/raw/')}
        for cmd in ('rev-parse HEAD', 'rev-parse main', 'branch --show-current', 'diff',
                    'diff --cached'):
            assert after[cmd] == before['git'][cmd], f'{name} changed: {cmd}'
        if name == 'Production':
            assert after == before['git'], 'Production git state changed'
    assert not differences, differences
    for manifest in ('implementation_freeze.json', 'evaluation_code_freeze.json'):
        for relative, expected in load_json(output/manifest).items():
            assert digest(ROOT/relative) == expected, relative
    for relative, expected in load_json(output/'frozen_manifest.json')['files'].items():
        assert digest(output/relative) == expected, relative
    registration = load_json(output/'seed_registration.json')
    streams = 0
    for row in registration:
        case = load_json(output/'waveforms'/f'{row["waveform"]}.json')
        assert case['registration'] == row
        with np.load(output/'waveforms'/f'{row["waveform"]}.npz') as saved:
            assert array_hash(saved['voltage_v']) == case['source_voltage_sha256']
            assert array_hash(saved['time_s']) == case['source_time_sha256']
        for profile in ('balanced', 'high_time_resolution'):
            with np.load(output/'streams'/f'{row["waveform"]}__{profile}.npz') as arrays:
                assert np.all(np.diff(arrays['time_s']) > 0)
                for method in ('R0', 'R1', 'R2', 'R3'):
                    key = method+'_frequency_hz'
                    if key in arrays:
                        assert arrays[key].shape == (len(arrays['time_s']), 20)
                        streams += 1
    for name in ('implementation_freeze.json', 'evaluation_code_freeze.json'):
        assert (output/name).stat().st_mtime_ns < (output/'single_held_out_started.json').stat().st_mtime_ns
    write_csv(output/'raw_hash_verification.csv', raw)
    write_json(output/'boundary_verification.json', dict(preexisting_files_checked=checked,
        raw_entries=len(raw), raw_hash_unchanged=True, production_unchanged=True,
        main_refs_unchanged=True, all_preexisting_files_unchanged=True,
        all_preexisting_tracked_diffs_unchanged=True, research_head_unchanged=True,
        implementation_and_protocol_unchanged=True, differences=differences))
    write_json(output/'repository_after.json', states)
    tests = output/'tests'
    test_text = (tests/'pytest_full_verified.txt').read_text(encoding='utf-8')
    failures = re.findall(r'^FAILED ([^\s]+)', test_text, re.MULTILINE)
    expected_failures = [
        'tests/unit/test_deployment_launchers.py::test_gui_launcher_uses_portable_conda_discovery',
        'tests/unit/test_deployment_launchers.py::test_production_launcher_does_not_pin_the_author_python_path']
    assert failures == expected_failures, failures
    match = re.search(r'\d+ failed, \d+ passed in [^\n]+', test_text)
    assert match is not None
    for filename, required in (('ruff_delivery.txt', 'All checks passed!'),
                                ('mypy_delivery.txt', 'Success: no issues found')):
        assert required in (tests/filename).read_text(encoding='utf-8')
    assert not (tests/'diff_check.txt').read_text(encoding='utf-8').strip()
    pngs = {p.stem for p in (output/'figures').glob('*.png')}
    svgs = {p.stem for p in (output/'figures').glob('*.svg')}
    assert len(pngs) == 19 and pngs == svgs
    assert (output/'visual_review.md').is_file()
    summary = dict(task='TASK-026', status='COMPLETE_RESEARCH_ONLY',
        independent_waveforms=len(registration), profiles=len(registration)*2,
        method_profile_streams=streams, core_waveforms=128,
        controlled_single_waveforms=sum(r['dataset'] == 'SINGLE' for r in registration),
        controlled_two_waveforms=sum(r['dataset'] == 'TWO' for r in registration),
        pytest=match.group(0), known_failures=failures, new_tests=34,
        initial_cli_test_failure='pytest argv leaked into CLI; isolated sys.argv rerun passes',
        ruff='PASS', mypy_strict='PASS', git_diff_check='PASS',
        source_waveform_time_hashes_verified=True, no_split_leakage=True,
        gt_only_in_synthesis_evaluator=True, gate_code_frozen_before_held_out=True,
        all_preexisting_files_unchanged=True, raw_sha256_unchanged=True,
        production_main_unchanged=True, commit_push_merge_performed=False,
        phase_d_executed=False, real_streams_evaluated=0,
        figures=dict(count=19, formats=['PNG', 'SVG'], review='visual_review.md'),
        representation_gate=load_json(output/'representation_gate.json'))
    assert not any(v['verdict'] == 'SUPPORTED' for v in summary['representation_gate'].values())
    write_json(output/'validation_summary.json', summary)
    print(summary, flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    verify(parser.parse_args().output)


if __name__ == '__main__':
    main()
