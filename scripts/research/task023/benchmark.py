"""Two-channel Phase 1A timing and frozen-baseline parity. No figures are written."""
from __future__ import annotations

from dataclasses import replace
from time import perf_counter

import numpy as np

from scripts.research.task023.common import load_channel, run_baselines, verify_baselines
from scripts.research.task023.methods import m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod


def main() -> None:
    for channel in ("20201211m_ch1", "20260630-1_ch2"):
        ch = load_channel(channel)
        print(f"{channel} | {ch.fs/1e9:.1f} GS/s | {len(ch.q)} centers", flush=True)
        start = perf_counter()
        baselines = run_baselines(ch)
        verify_baselines(ch, baselines)
        print(f"  B0/B1/B+S + frozen parity: {perf_counter()-start:.3f} s", flush=True)
        for method in (m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod):
            cold = replace(ch)
            started = perf_counter()
            result = method(cold)
            elapsed = perf_counter()-started
            accepted = np.count_nonzero(np.isfinite(result.accepted_hz))
            print(f"  {method.__name__}: {elapsed:.3f} s, {accepted} accepted", flush=True)
            if elapsed >= 15.:
                raise RuntimeError(f"{method.__name__} exceeded the 15 s budget on {channel}")


if __name__ == "__main__":
    main()
