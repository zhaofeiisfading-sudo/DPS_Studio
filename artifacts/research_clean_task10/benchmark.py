"""Serial, isolated-process timings and measured Windows memory; no GUI edits."""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import subprocess
import sys
import time
import tracemalloc
from ctypes import wintypes
from pathlib import Path
from typing import Any

import numpy as np

from artifacts.research_clean_task8.common import Signal, event_detector
from artifacts.research_clean_task10.audit import OUT, ROOT, write_json
from artifacts.research_clean_task10.experiment import HOPS, WINDOWS, Spec, estimate
from artifacts.research_clean_task10.run import frozen_case, write_csv


class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def process_memory() -> dict[str, int]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return dict(working_set_bytes=int(counters.WorkingSetSize),
                process_peak_working_set_bytes=int(counters.PeakWorkingSetSize),
                private_bytes=int(counters.PrivateUsage))


def worker(args: argparse.Namespace) -> None:
    spec = Spec(args.window, args.hop)
    signals = [("synthetic12800", frozen_case("fresh", "step", 0).signal)]
    if not args.core:
        raw = np.loadtxt(ROOT / "data/raw/20231019-ch1.dat", delimiter=",")
        signals.append(("raw80000", Signal(raw[:, 0].copy(), raw[:, 1].copy())))
    rows = []
    for dataset, signal in signals:
        onset, _ = event_detector(signal)
        if args.core:
            from dps_studio.core.models import SignalRecord
            from dps_studio.core.time_frequency import compute_stft
            record = SignalRecord(signal.time_s, signal.voltage_v)

            def operation() -> Any:
                return compute_stft(record, window_length_samples=spec.window,
                                    overlap_samples=spec.window-spec.hop, nfft=spec.nfft)
        else:
            def operation() -> Any:
                return estimate(signal, spec, batch_frames=256, onset=onset)

        gc.collect()
        before = process_memory()
        tracemalloc.start()
        probe = operation()
        _, allocated_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        after = process_memory()
        del probe
        gc.collect()
        for repeat in range(3):
            clock = time.perf_counter()
            result = operation()
            elapsed = time.perf_counter() - clock
            after_repeat = process_memory()
            rows.append(dict(dataset=dataset, **spec.parameters(signal.fs), repeat=repeat,
                backend="core_dense_transform_only" if args.core else "research_chunked_fft_peak_support",
                runtime_s=elapsed, tracemalloc_peak_bytes=allocated_peak,
                baseline_working_set_bytes=before["working_set_bytes"],
                measured_process_peak_working_set_bytes=max(after["process_peak_working_set_bytes"],
                    after_repeat["process_peak_working_set_bytes"]),
                measured_final_working_set_bytes=after_repeat["working_set_bytes"],
                measured_private_bytes=after_repeat["private_bytes"],
                retained_dense_complex_bytes=(spec.nfft//2+1) * (
                    (len(signal.time_s)-spec.window)//spec.hop+1) * 16,
                samples=len(signal.time_s), process_id=os.getpid()))
            del result
            gc.collect()
    write_json(args.worker_output, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument("--window", type=int)
    parser.add_argument("--hop", type=int)
    parser.add_argument("--core", action="store_true")
    args = parser.parse_args()
    if args.worker_output:
        worker(args)
        return
    if args.output is None:
        parser.error("--output required")
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(OUT):
        parser.error("Output must be a new TASK-010 subdirectory")
    output.mkdir(parents=True, exist_ok=False)
    jobs = [(w, h, False) for w in WINDOWS for h in HOPS]
    np.random.default_rng(1010).shuffle(jobs)
    jobs += [(512, 128, True), (512, 1, True), (2048, 1, True)]
    rows = []
    for window, hop, core in jobs:
        target = output / f"{'core' if core else 'chunk'}_w{window}_h{hop}.json"
        cmd = [sys.executable, "-B", "-m", "artifacts.research_clean_task10.benchmark",
               "--worker-output", str(target), "--window", str(window), "--hop", str(hop)]
        if core:
            cmd.append("--core")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode:
            write_json(output / f"failure_w{window}_h{hop}_{core}.json", dict(
                command=cmd, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
            raise RuntimeError(result.stderr)
        values = json.loads(target.read_text(encoding="utf-8"))
        rows.extend(values)
        print(json.dumps(dict(window=window, hop=hop, core=core, done=len(rows))), flush=True)
    write_csv(output / "measurements.csv", rows)
    write_json(output / "methodology.json", dict(repeats=3, threads=1,
        serial_isolated_process_per_configuration=True, io_imports_serialization_excluded=True,
        traced_probe_excluded_from_timing=True, order="seed1010 shuffled chunk jobs; core last",
        memory="OS peak working set is lifetime absolute RSS including imports; raw80000 follows synthetic in each child. tracemalloc is per-operation allocation peak; native allocator/workspaces may not be fully tracked.",
        comparison="core_dense is transform-only; chunk timings also include peak refinement and quality support. No direct algorithm speedup claim from these unlike operations."))


if __name__ == "__main__":
    main()
