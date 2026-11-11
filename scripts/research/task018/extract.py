"""Candidate-only execution. No fusion is evaluated in this entry point."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import ctypes
from pathlib import Path
import platform
import sys
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task017.compare import digest
from scripts.research.task017.prepare import OUT as OLD
from scripts.research.task018.inputs import OUT, PROTOCOL, extract, head, inventory, json_write


def peak_working_set() -> int | None:
    if sys.platform != 'win32':
        return None

    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('peak_ws', 'ws', 'peak_paged', 'paged',
                                                 'peak_nonpaged', 'nonpaged', 'page', 'peak_page')]

    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = ctypes.c_void_p
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(process()),
                                                   ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return int(counters.peak_ws)


def worker(item: dict[str, Any], plan: list[dict[str, Any]], dest: Path) -> dict[str, Any]:
    value = extract(item, plan, dest)
    value['worker_peak_working_set_bytes'] = peak_working_set()
    print(item['id'], value['evaluated'], 'centers', value['onset'], 'onset',
          round(value['channel_wall_s'], 2), 's', flush=True)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='inputs_v1')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    started = perf_counter()
    dest = (OUT / 'data' / args.output).resolve()
    assert dest.parent == (OUT / 'data').resolve()
    items, plans = inventory()
    dest.mkdir(exist_ok=False)
    old = pd.read_csv(OLD / 'data/analysis_v03/segment_metrics.csv')
    assert old.method.nunique() == 28 and old.channel.nunique() == 14
    assert set(old.channel) == set(plans)
    old.groupby(['method', 'stage'], sort=False)[[
        'centers', 'candidate_n', 'gated_n', 'supported_n', 'supported_common50_6_n',
    ]].sum().to_csv(dest / 'task017_review.csv', mode='x')
    json_write(dest / 'preflight.json', dict(protocol_sha256=digest(PROTOCOL), head=head(),
        branch='codex/research_2/global-path-ridge-v2', inventory=items,
        visual_freeze_sha256=digest(OLD / 'data/visual_freeze.json'),
        visual_annotations_sha256=digest(OLD / 'data/visual_annotations.json'),
        old_metrics_sha256=digest(OLD / 'data/analysis_v03/segment_metrics.csv'),
        python=sys.version, platform=platform.platform(), numpy=np.__version__, pandas=pd.__version__))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        values = list(pool.map(worker, items, [plans[r['id']] for r in items], [dest]*len(items)))
    assert sum(row['onset'] for row in values) == 69
    json_write(dest / 'complete.json', dict(channels=values, workers=args.workers,
                                          wall_s=perf_counter()-started, files=10))


if __name__ == '__main__':
    main()
