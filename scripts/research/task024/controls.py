"""Frozen B1/B+S and duration-matched Hann STFT controls."""
from __future__ import annotations

import csv
from dataclasses import replace

import numpy as np

from dps_studio.core.segmentation.strategies import Strategy, estimate_strategy
from scripts.research.task017.compare import Trace, normalize, request
from scripts.research.task017.prepare import ROOT
from scripts.research.task023.common import Channel, Estimate, RawEvaluator
from scripts.research.task023.waveform import FMIN, samples_for_ns

B1 = "B1"
BS = "B+S"
QUAD = "STFT_25p6ns_quad"
LONG_QUAD = "STFT_38p4ns_quad"
MATCHED = {
    "STFT_12p8ns": (12.8, 0, 4096),
    "STFT_25p6ns": (25.6, 0, 4096),
    QUAD: (25.6, 2, 4096),
    LONG_QUAD: (38.4, 2, 8192),
}
CONTROLS = (B1, BS, *MATCHED)


def strategy(name: str, fs: float) -> Strategy:
    if name in (B1, BS):
        return Strategy(width=512, hop=128, nfft=4096, boundary="full", degree=0)
    duration, degree, minimum_fft = MATCHED[name]
    width = samples_for_ns(duration, fs)
    nfft = max(minimum_fft, 1 << (2*width-1).bit_length())
    return Strategy(width=width, hop=128, nfft=nfft, boundary="full", degree=degree)


def estimate(ch: Channel, ev: RawEvaluator, name: str) -> Estimate:
    spec = strategy(name, ch.fs)
    result = estimate_strategy(replace(request(ch.t, ch.y, spec.width, ch.fmax), segment=None),
                               name, spec)
    trace = Trace(result.time_s, result.candidate_frequency_hz, result.frequency_hz,
                  np.asarray(result.quality), np.zeros(len(result.time_s)), spec.width,
                  FMIN, ch.fmax, 0., {}, name)
    values = normalize(trace, ch.t, ch.fs)
    grid = ch.q//128
    candidate, accepted, rate = (
        np.asarray(values[key][grid], dtype=np.float64)
        for key in ("frequency_hz", "gated_frequency_hz", "chirp_hz_s")
    )
    support = np.zeros(len(ch.q), dtype=np.int64)
    quality = result.details["frames"]
    for frame in quality:
        center = frame["center_sample"]
        if 384 <= center <= ch.q[-1]:
            support[(center-384)//128] = frame["support_samples"]
    return Estimate(ch.q, candidate, accepted, rate, ev.evaluate(candidate, rate),
                    {"support_samples": support})


def run_controls(ch: Channel, ev: RawEvaluator) -> dict[str, Estimate]:
    baseline = estimate(ch, ev, B1)
    return {
        B1: baseline,
        BS: replace(baseline, accepted_hz=np.where(baseline.raw.S_256, baseline.candidate_hz,
                                                  np.nan)),
        **{name: estimate(ch, ev, name) for name in MATCHED},
    }


def verify_task020(ch: Channel, results: dict[str, Estimate]) -> int:
    archive = ROOT / "artifacts/TASK-020/data/centers" / f"{ch.id}.csv"
    with archive.open(encoding="utf-8", newline="") as stream:
        by_center = {int(row["sample_index"]): row for row in csv.DictReader(stream)}
    rows = [by_center[int(q)] for q in ch.q]
    b1, bs = results[B1], results[BS]
    for key, data in (("B_frequency_hz", b1.candidate_hz), ("B_output_hz", b1.accepted_hz),
                      ("BS_output_hz", bs.accepted_hz)):
        np.testing.assert_array_equal(data, [float(row[key] or "nan") for row in rows],
                                      err_msg=f"{ch.id}: {key}")
    for key, values in (("primary", ch.primary), ("B_S", b1.raw.S_256)):
        np.testing.assert_array_equal(values, [row[key] == "True" for row in rows],
                                      err_msg=f"{ch.id}: {key}")
    return len(rows)
