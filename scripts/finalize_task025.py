"""Complete delivery receipts and the explicitly requested lightweight Obsidian log."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.research.task025_informative_interval import calibration_threshold
from scripts.report_task025 import main as report_main
from scripts.run_task025 import DETECTORS, load_json
from scripts.run_task023f_proposal_recovery import ROOT, sha256, write_csv, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    boundary = load_json(output / 'boundary_verification.json')
    assert boundary['all_preexisting_files_unchanged'] and boundary['raw_hash_unchanged']
    assert boundary['production_unchanged']
    assert not load_json(output / 'phase_b_decision.json')['passed']
    for relative, expected in load_json(output / 'evaluation_code_freeze.json').items():
        assert sha256(ROOT / relative) == expected
    registration = load_json(output / 'seed_registration.json')
    cases = load_json(output / 'calibration_manifest.json')+load_json(output / 'held_out_manifest.json')
    assert len(cases) == len({case['waveform'] for case in cases}) == 272
    assert {(r['waveform'], r['split']) for r in registration} == {
        (r['waveform'], r['split']) for r in cases}
    assert all(len(row['streams']) == 2 for row in cases)
    # Reconstruct only the already frozen calibration order statistic as an integrity check.
    calibration = [case for case in cases if case['split'] == 'CALIBRATION']
    thresholds = load_json(output / 'frozen_thresholds.json')
    for name in DETECTORS:
        scores, labels = [], []
        for case in calibration:
            for stream in case['streams']:
                with np.load(output / 'streams' / (stream['stream']+'.npz')) as arrays:
                    scores.append(arrays[name])
                    labels.append(arrays['mask_target_present'])
        expected = calibration_threshold(np.concatenate(scores), np.concatenate(labels),
                                         split='CALIBRATION')
        assert expected == thresholds[name]['threshold']
    assert (output / 'frozen_thresholds.json').stat().st_mtime_ns < (
        output / 'held_out_started.json').stat().st_mtime_ns
    tests = output / 'tests'
    pytest_text = (tests / 'pytest_full_short_path.txt').read_text(encoding='utf-8')
    summary = re.search(r'\d+ failed, \d+ passed in [^\n]+', pytest_text)
    assert summary is not None
    failures = re.findall(r'^FAILED ([^\s]+)', pytest_text, re.MULTILINE)
    assert failures == [
        'tests/unit/test_deployment_launchers.py::test_gui_launcher_uses_portable_conda_discovery',
        'tests/unit/test_deployment_launchers.py::test_production_launcher_does_not_pin_the_author_python_path',
    ]
    assert 'All checks passed!' in (tests / 'ruff_delivery.txt').read_text()
    assert 'Success: no issues found' in (tests / 'mypy_delivery.txt').read_text()
    assert not (tests / 'git_diff_check.txt').read_text().strip()
    validation = dict(task='TASK-025', status='COMPLETE_PHASE_B_EARLY_STOP',
        pytest_summary=summary.group(0).strip(), new_tests=29, new_test_failures=0,
        pytest_log='tests/pytest_full_short_path.txt', known_launcher_failures=failures,
        initial_test_failure=dict(log='tests/pytest_full.txt', passed=820, failed=3,
            extra_failure='Windows MAX_PATH exceeded by deeply nested pytest temporary output',
            resolution='Re-ran unchanged tests with a new short Research-local .t25_full directory'),
        ruff='PASS', ruff_log='tests/ruff_delivery.txt',
        mypy='PASS (strict, src + all TASK-025 scripts and tests)',
        mypy_log='tests/mypy_delivery.txt', git_diff_check='PASS',
        independent_waveforms=272, calibration_waveforms=94, held_out_waveforms=178,
        profile_streams=544, held_out_generation_runs=1, held_out_evaluation_runs=1,
        split_leakage=False, thresholds_reconstructed_from_calibration_exactly=True,
        frozen_evaluation_code_unchanged=True, real_streams_evaluated=0,
        phase_c_run=False, complete_strongest_coverage=1.,
        outside_interval_helper_exact_equality_tested=True,
        actual_g1_equality='NOT TESTED: Phase C skipped', integrity=boundary,
        figures=dict(measured=4, skipped_not_measured=4, formats=['PNG', 'SVG'],
                     visual_review='visual_review.md'),
        verdicts=load_json(output / 'phase_b_decision.json')['verdicts'])
    write_json(output / 'validation_summary.json', validation)
    report_main()
    with (output / 'visual_review.md').open('x', encoding='utf-8') as handle:
        handle.write('# Visual review\n\n'
            'Inspected PNGs 01–04 and representative SKIPPED ch3 panel07. '
            'Axes, labels, split separation and frozen-threshold markings readable. '
            'The histogram full scale emphasizes the large coherent/noise separation; '
            'the operating-point table is necessary for the weak-signal tail. '
            'Curve plots are descriptive only and never feed threshold selection. '
            'Segment plot distinguishes any overlap from 99% and complete coverage. '
            'Panels05–08 explicitly show SKIPPED and contain no fabricated measurements.\n')
    changed = sorted([*ROOT.glob('scripts/*task025*.py'),
                      *ROOT.glob('src/dps_studio/research/task025*.py'),
                      ROOT / 'tests/unit/test_task025_informative_interval.py'])
    write_csv(output / 'source_delivery_manifest.csv', [dict(path=str(p.relative_to(ROOT)),
        sha256=sha256(p), lines=len(p.read_text(encoding='utf-8').splitlines())) for p in changed])
    frame = pd.read_csv(output / 'frame_detection_aggregates.csv')

    def metric(stratum: str, mask: str, reject: bool = False) -> float:
        row = frame[(frame.split == 'HELD_OUT') & (frame.detector == 'E1') &
            (frame['mask'] == mask) & (frame.stratum == stratum) & (frame.dataset == 'ALL') &
            (frame.family == 'ALL') & (frame.profile == 'ALL') &
            (frame.aggregation == 'waveform_macro')].iloc[0]
        value = float(row.recall_or_activation)
        return 100*(1-value if reject else value)

    obsidian = Path('D:/Research/Notes/05项目/dps/2026-09-14_TASK-025_informative-interval.md')
    with obsidian.open('x', encoding='utf-8') as handle:
        handle.write(f'''---
task: TASK-025
date: 2026-09-14
branch: codex/research_2/global-path-ridge
status: COMPLETE_PHASE_B_EARLY_STOP
verdict: signal_MIXED; hard_negative_MIXED; interval_NOT_SUPPORTED; engineering_NOT_TESTED; preservation_NOT_TESTED; production_RESEARCH_ONLY
artifact: {output.as_posix()}
---

预注册后完成128原分布fresh core、64困难负样本、80困难正样本；272波形/544 profiles。
94 calibration、178 held-out按波形分组；所有历史task023h作为TASK-024/LEGACY_DIAGNOSTIC。
只新增task025 detector/stress模块、6个脚本、29项测试和artifact；既有源码未改。
Core Candidate Recall=100%（148596/148596有效帧）；held-out positive stress=99.7455%，未改Top-K。
Threshold规则：最高实际calibration值满足target recall≥99.5%；E1={thresholds['E1']['threshold']:.12g}，两个profile共用。
Held-out E1 waveform-macro：supported target recall={metric('target_present', 'SUPPORTED_FRAME'):.4f}%；active={metric('target_present', 'SEARCH_ACTIVE'):.4f}%。
LOW_INFORMATION rejection：supported={metric('low_information', 'SUPPORTED_FRAME', True):.4f}%；active={metric('low_information', 'SEARCH_ACTIVE', True):.4f}%。
临时衰落active recall={metric('temporary_fading', 'SEARCH_ACTIVE'):.4f}%<98%；pure-noise/dropout active rejection={metric('pure_noise_dropout', 'SEARCH_ACTIVE', True):.4f}%<80%。
相干非目标仍高激活，所有H标签保持TARGET_ABSENT；E1检测相干结构，不能确认物理目标身份。
任意重叠segment recall=100%；不代表完整覆盖，逐段coverage/fragmentation/boundary见artifact。
Phase B失败：G0/G1 proposal/runtime、RMSE/wrong/precision/harm、ch3双profile及34真实streams全部SKIPPED/NOT TESTED。
无新真实数据风险结论，无准确率声明；≥5%修改风险检查未执行。
pytest={summary.group(0).strip()}；仅2既有launcher失败。首轮MAX_PATH额外失败已用短临时路径复核。
Ruff/strict mypy/diff check PASS。git status仅新增Research文件和测试临时目录，tracked/staged diff为空。
48 raw SHA-256及14758既有文件不变；Research HEAD7864f1a、Production/main07a1e0f不变；无commit/push/promotion。
未解决：弱信号高召回与噪声排除不兼容，固定context放大active区域；当前gate缺乏工程化依据。
建议人工审计后优先弱信号representation/局部统计量适用边界，保留identifiability约束；未启动TASK-026。

[最终报告]({(output / 'final_research_report.md').as_posix()})。本日志仅索引，源码/git/tests/artifact优先。
''')
    git = {name: subprocess.check_output(['git', *command], cwd=ROOT, text=True).strip()
           for name, command in (('status', ['status', '--short']), ('diff', ['diff']),
               ('staged_diff', ['diff', '--cached']), ('head', ['rev-parse', 'HEAD']))}
    write_json(output / 'delivery_receipt.json', dict(obsidian=str(obsidian),
        obsidian_sha256=sha256(obsidian), report_sha256=sha256(output / 'final_research_report.md'),
        git=git, stopped_after_task025=True))
    with (output / 'README.md').open('x', encoding='utf-8') as handle:
        handle.write('# TASK-025\n\nPhase B EARLY_STOP; Research only.\n\n'
            '[Final report](final_research_report.md) · [Validation](validation_summary.json) · '
            '[Gate checks](phase_b_success_gates.csv) · [Raw integrity](raw_hash_verification.csv)\n\n'
            'protocol/seed/threshold files were preregistered. waveforms/ preserves all raw synthetic '
            'inputs and truth; streams/ preserves frozen scores and baseline trajectories. '
            'Four phase-C/real tables have headers only; reasons in skipped_stages.json. '
            'Temporary full-test output also remains in Research .t25_full; nothing was deleted.\n')
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
