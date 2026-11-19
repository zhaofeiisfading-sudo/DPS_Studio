"""Natural dual-gain agreement on exact acquisition-center intersections."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from scripts.research.task023.common import Channel
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.phase2_run import PHASE2_METHODS
from scripts.research.task023.pursuit import rail_mask
from scripts.research.task023.waveform import Bool, Float, Int, samples_for_ns

PAIR_SHOTS = ("20260607", "20260630-1", "20260630-2", "20260701")
CLIP_WINDOW_NS = 6.4
LAG_RADIUS_S = .5e-9


def align_centers(time1: Float, time2: Float) -> tuple[Float, Int, Int]:
    """Join exact physical times, rejecting duplicated or unordered coordinates."""
    for times in (time1, time2):
        if not np.isfinite(times).all() or np.any(np.diff(times) <= 0.):
            raise ValueError("Center times must be finite and strictly increasing")
    times, left, right = np.intersect1d(time1, time2, assume_unique=True, return_indices=True)
    return times, left, right


@dataclass(frozen=True)
class RawLag:
    samples: int
    seconds: float
    correlation: float
    peak_margin: float
    search_radius_samples: int


def raw_sample_lag(ch1: Float, ch2: Float, fs: float) -> RawLag:
    """Maximize Pearson correlation of ch1[i + lag] and ch2[i] within ±0.5 ns."""
    radius = round(LAG_RADIUS_S * fs)
    if ch1.shape != ch2.shape or radius < 1 or len(ch1) <= 2*radius + 1:
        raise ValueError("The raw lag needs a shared sample grid with enough overlap")
    stop = len(ch2)-radius
    reference = ch2[radius:stop] - ch2[radius:stop].mean()
    reference_norm = np.linalg.norm(reference)
    scores = np.empty(2*radius+1)
    for j, lag in enumerate(range(-radius, radius+1)):
        signal = ch1[radius+lag:stop+lag]
        signal = signal - signal.mean()
        norm = np.linalg.norm(signal) * reference_norm
        scores[j] = (signal @ reference)/norm if norm else -np.inf
    best = int(np.argmax(scores))
    if not np.isfinite(scores[best]):
        raise ValueError("The raw lag is undefined for these voltages")
    lag = best-radius
    runner_up = np.partition(scores, -2)[-2]
    return RawLag(lag, lag/fs, float(scores[best]), float(scores[best]-runner_up), radius)


def _clipped_centers(ch: Channel) -> Bool:
    half = samples_for_ns(CLIP_WINDOW_NS, ch.fs)//2
    cumulative = np.r_[0, np.cumsum(rail_mask(ch.y))]
    lo, hi = np.clip(ch.q-half, 0, len(ch.y)), np.clip(ch.q+half, 0, len(ch.y))
    return np.asarray(cumulative[hi] > cumulative[lo], dtype=np.bool_)


@dataclass(frozen=True)
class PairComparison:
    shot: str
    time_s: Float
    stage: NDArray[np.str_]
    clipped_ch1: Bool
    clipped_ch2: Bool
    accepted_ch1: dict[str, Float]
    accepted_ch2: dict[str, Float]
    lag: RawLag
    unmatched_ch1_centers: int
    unmatched_ch2_centers: int


def compare_pair(shot: str, first: Screening, second: Screening) -> PairComparison:
    ch1, ch2 = first.channel, second.channel
    if (ch1.id, ch2.id) != (f"{shot}_ch1", f"{shot}_ch2"):
        raise ValueError(f"Unexpected channels for shot {shot}")
    if ch1.fs != ch2.fs or not np.array_equal(ch1.t, ch2.t):
        raise ValueError(f"Raw channels for {shot} require an identical sample clock")
    p1, p2 = (np.flatnonzero(ch.primary) for ch in (ch1, ch2))
    times, i1, i2 = align_centers(ch1.t[ch1.q[p1]], ch2.t[ch2.q[p2]])
    left, right = p1[i1], p2[i2]
    s1, s2 = first.stages[left], second.stages[right]
    stage = np.where(s1 == s2, s1, "visual_stage_mismatch")
    return PairComparison(
        shot, times, stage, _clipped_centers(ch1)[left], _clipped_centers(ch2)[right],
        {key: value.accepted_hz[left] for key, value in first.results.items()},
        {key: value.accepted_hz[right] for key, value in second.results.items()},
        raw_sample_lag(ch1.y, ch2.y, ch1.fs), len(p1)-len(times), len(p2)-len(times),
    )


def agreement_metrics(ch1: Float, ch2: Float) -> dict[str, object]:
    if ch1.shape != ch2.shape:
        raise ValueError("Agreement requires the same number of paired centers")
    a, b = np.isfinite(ch1), np.isfinite(ch2)
    both = a & b
    delta = np.abs(ch1[both] - ch2[both])
    return dict(
        paired_centers=len(ch1), both_accepted_n=len(delta),
        only_ch1_n=int(np.count_nonzero(a & ~b)), only_ch2_n=int(np.count_nonzero(b & ~a)),
        both_rejected_n=int(np.count_nonzero(~(a | b))),
        median_abs_diff_mhz=float(np.median(delta)/1e6) if len(delta) else float("nan"),
        mean_abs_diff_mhz=float(np.mean(delta)/1e6) if len(delta) else float("nan"),
        agree_30mhz_frac=float(np.mean(delta <= 30e6)) if len(delta) else float("nan"),
        agree_100mhz_frac=float(np.mean(delta <= 100e6)) if len(delta) else float("nan"),
        disagree_250mhz_n=int(np.count_nonzero(delta > 250e6)),
    )


def pair_rows(pair: PairComparison) -> list[dict[str, object]]:
    clipped = pair.clipped_ch1 | pair.clipped_ch2
    all_centers = np.ones(len(pair.time_s), dtype=np.bool_)
    stages = ("all", *dict.fromkeys(pair.stage))
    rows: list[dict[str, object]] = []
    for stage in stages:
        stage_mask = all_centers if stage == "all" else pair.stage == stage
        for clip_label, clip_mask in (
            ("all", all_centers), ("clipped", clipped), ("unclipped", ~clipped),
        ):
            mask = stage_mask & clip_mask
            for method in PHASE2_METHODS:
                rows.append(dict(
                    shot=pair.shot, visual_stage=stage, clipping=clip_label, method=method,
                    clip_window_ns=CLIP_WINDOW_NS,
                    clipped_ch1_n=int(np.count_nonzero(mask & pair.clipped_ch1)),
                    clipped_ch2_n=int(np.count_nonzero(mask & pair.clipped_ch2)),
                    unmatched_ch1_centers=pair.unmatched_ch1_centers,
                    unmatched_ch2_centers=pair.unmatched_ch2_centers,
                    raw_lag_samples=pair.lag.samples, raw_lag_s=pair.lag.seconds,
                    raw_lag_correlation=pair.lag.correlation,
                    raw_lag_peak_margin=pair.lag.peak_margin,
                    raw_lag_search_radius_samples=pair.lag.search_radius_samples,
                    **agreement_metrics(pair.accepted_ch1[method][mask],
                                        pair.accepted_ch2[method][mask]),
                ))
    return rows
