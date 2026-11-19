"""Compare frame decisions, group interesting frames and expose local waveform fits."""
from __future__ import annotations

from math import isfinite
from pathlib import Path
from threading import Event
from time import perf_counter

import numpy as np
from numpy.typing import ArrayLike

from dps_studio.core.models import SignalRecord

from ._evidence import RawEvaluator
from .engine import Progress, _b1, _channel, _m4, _matched_stft
from .models import (
    CATEGORY_ZH, REASON_ZH, DiffCategory, Estimate, InterestingRegion, LocalComparisonWaveform,
    PointEvidence, StftM4ComparisonBundle, readonly,
)
from .waveform import FMAX, FMIN, Float, Int, chirp_phase, complete, detrend, offsets, quadrature, samples_for_ns


def classify_differences(b1: Estimate, m4: Estimate) -> tuple[DiffCategory, ...]:
    if not np.array_equal(b1.sample_index, m4.sample_index):
        raise ValueError("B1 and M4 must share the same sample centers")
    left = np.isfinite(b1.accepted_hz)
    right = np.isfinite(m4.accepted_hz)
    both, added, dropped = left & right, right & ~left, left & ~right
    delta = abs(b1.accepted_hz - m4.accepted_hz)
    raw = m4.raw
    supported = ~m4.persistent_cw_overlap & (
        (raw.raw_chirp_r2_64ns >= .15)
        | ((raw.raw_chirp_r2_256ns >= .04) & (raw.split_half_coherence_256ns >= .58))
    )
    risk = b1.raw.raw_chirp_r2_64ns >= .15
    masks = (
        both & (delta <= 50e6), added & supported, added & ~supported,
        both & (delta > 50e6) & (delta <= 250e6), both & (delta > 250e6),
        dropped & ~risk, dropped & risk, ~(left | right),
    )
    if not np.all(np.sum(masks, axis=0) == 1):
        raise AssertionError("Difference classification must cover each frame exactly once")
    values = np.select(masks, [item.value for item in DiffCategory], default="")
    return tuple(DiffCategory(value) for value in values)


def _regions(
    frame_time: Float, categories: tuple[DiffCategory, ...], m4: Estimate,
    edge_time: Float,
) -> tuple[InterestingRegion, ...]:
    labels = np.asarray(categories, dtype="U40")
    diff = (labels != DiffCategory.BOTH_AGREE) & (labels != DiffCategory.BOTH_REJECTED)
    onset = np.zeros(len(frame_time), dtype=np.bool_)
    # Include the nearest center to each measured boundary and the first
    # published frames following a common OFF stretch.
    if len(frame_time):
        right = np.clip(np.searchsorted(frame_time, edge_time), 0, len(frame_time)-1)
        left = np.maximum(right-1, 0)
        nearest = np.where(abs(frame_time[left]-edge_time) <= abs(frame_time[right]-edge_time),
                           left, right)
        onset[nearest] = True
        active = np.isfinite(m4.accepted_hz)
        initial = active & ~np.r_[False, active[:-1]]
        quiet = np.r_[True, True, True, ~active[:-3]][:len(active)] if len(active) >= 3 else initial
        onset |= initial & quiet
    ambiguous = labels == DiffCategory.M4_ADDED_AMBIGUOUS
    cw = m4.persistent_cw_overlap
    pre_edge = np.asarray(m4.diagnostics["near_support_edge"], dtype=np.bool_) & ~np.asarray(
        m4.diagnostics["post_support_edge"], dtype=np.bool_)
    masks = (
        ("all_diff", "全部差异", diff),
        ("m4_added_supported", "M4 新增 · 波形支持",
         labels == DiffCategory.M4_ADDED_SUPPORTED),
        ("branch_diff_major", "大频差分歧 >250 MHz", labels == DiffCategory.BRANCH_DIFF_MAJOR),
        ("m4_dropped_strong_risk", "疑似误伤 · B1 强短窗被拒",
         labels == DiffCategory.M4_DROPPED_STRONG_RISK),
        ("precursor_or_ambiguous", "起跳前侧或归属争议", ambiguous | cw | (pre_edge & diff)),
        ("onset_or_step", "起跳、DC 阶跃与触轨退出", onset),
        ("rapid_chirp", "高调频率 ≥ 10¹⁶ Hz/s",
         np.isfinite(m4.accepted_hz) & (abs(m4.chirp_hz_s) >= 1e16)),
    )
    regions = []
    for kind, title, mask in masks:
        frames = np.flatnonzero(mask)
        for group in np.split(frames, np.flatnonzero(np.diff(frames) != 1)+1):
            if len(group):
                regions.append(InterestingRegion(
                    kind, title, tuple(map(int, group)), float(frame_time[group[0]]),
                    float(frame_time[group[-1]]), f"{len(group)} 帧 · 每 128 个原始采样点",
                ))
    return tuple(regions)


def compute_comparison_bundle(
    record: SignalRecord, *, channel_name: str = "", source_path: Path | None = None,
    fmin_hz: float = FMIN, fmax_hz: float = FMAX, include_matched_stft: bool = False,
    include_coherent_map: bool = True, cancel_event: Event | None = None,
    progress_callback: Progress | None = None,
) -> StftM4ComparisonBundle:
    """Compute both methods and publish a complete, immutable comparison."""
    started = perf_counter()
    ch = _channel(record, fmin_hz, fmax_hz, cancel_event, progress_callback)
    ch.update(0, "准备原始波形")
    ch.update(1, "估计静默频谱与 DC 阶跃")
    _ = ch.quiet
    ev = RawEvaluator(ch)
    t0 = perf_counter()
    b1, raster = _b1(ch, ev)
    t1 = perf_counter()
    ch.update(21, "识别触轨与支持边界")
    m4, coherent, rail_exit, rail = _m4(ch, ev, include_coherent_map)
    t2 = perf_counter()
    matched = _matched_stft(ch, ev) if include_matched_stft else None
    matched_wall = perf_counter()-t2 if matched is not None else None
    ch.update(98, "汇总逐帧差异与关注区域")
    categories = classify_differences(b1, m4)
    steps = ch.quiet.steps.index
    frame_time = ch.t[ch.q]
    regions = _regions(frame_time, categories, m4, ch.t[np.r_[steps, rail_exit]])
    bundle = StftM4ComparisonBundle(
        record, channel_name, source_path or record.source_path, ch.fs, ch.q, frame_time,
        ch.fmin, ch.fmax, t1-t0, t2-t1, matched_wall, perf_counter()-started,
        raster, coherent, steps, rail_exit, rail, b1, m4, matched, categories, regions,
    )
    ch.update(100, "对比计算完成")
    return bundle


def convert_frequency_for_display(
    frequency_hz: ArrayLike, *, confirmed_wavelength_m: float | None = None,
) -> tuple[Float, str, bool]:
    frequency = np.asarray(frequency_hz, dtype=np.float64)
    if confirmed_wavelength_m is None:
        return np.asarray(frequency/1e9), "GHz", False
    if (isinstance(confirmed_wavelength_m, (bool, np.bool_))
            or not isfinite(confirmed_wavelength_m) or confirmed_wavelength_m <= 0.):
        raise ValueError("真空波长必须为正有限值（m）")
    if np.isinf(frequency).any() or np.any(frequency < 0.):
        raise ValueError("频率必须为非负有限值，缺测用 NaN 表示")
    with np.errstate(over="ignore"):
        speed = (confirmed_wavelength_m / 2.) * frequency
    if np.isinf(speed).any():
        raise ValueError("表观速度超出有限数值范围")
    return np.asarray(speed), "m/s", True


def _point(estimate: Estimate, i: int) -> PointEvidence:
    fields = estimate.diagnostics

    def diag(key: str) -> float:
        return float(fields[key][i]) if key in fields else float("nan")

    raw = estimate.raw
    return PointEvidence(
        float(estimate.accepted_hz[i]), float(estimate.candidate_hz[i]),
        float(estimate.chirp_hz_s[i]), float(raw.raw_tone_r2_64ns[i]),
        float(raw.raw_chirp_r2_64ns[i]), float(raw.raw_chirp_r2_256ns[i]),
        float(raw.split_half_coherence_256ns[i]), float(raw.local_center_snr_32ns[i]),
        diag("verification_window_ns"), diag("snr_full_db"), diag("secondary_hz"),
        "persistent_cw_overlap" in fields and bool(fields["persistent_cw_overlap"][i]),
        estimate.quality_flags[i],
    )


def inspect_frame_waveform(bundle: StftM4ComparisonBundle, frame_index: int) -> LocalComparisonWaveform:
    if not 0 <= frame_index < len(bundle.q):
        raise IndexError("Frame lies outside the comparison grid")
    q = int(bundle.q[frame_index])
    fs = bundle.sample_rate_hz
    t, y = bundle.record.time_s, bundle.record.voltage_v
    center = float(t[q])
    left = int(np.searchsorted(t, center-16e-9))
    right = int(np.searchsorted(t, center+16e-9, side="right"))
    local = slice(left, right)
    residual = detrend(y[local])
    width = samples_for_ns(6.4, fs)
    sample = offsets(width)
    full = bool(complete(np.array([q]), len(y), width)[0])
    fit_samples = q + sample
    clip = (fit_samples >= 0) & (fit_samples < len(t))
    fit_time = t[fit_samples[clip]]
    local_baseline = y[local]-residual

    def fit(point: PointEvidence, rate: float) -> Float:
        if not full or not isfinite(point.candidate_hz) or not isfinite(rate):
            return np.full(len(fit_time), np.nan)
        phase = chirp_phase(sample/fs, point.candidate_hz, rate)
        phasor, _ = quadrature(y[fit_samples], phase)
        fitted = detrend(np.asarray(np.real(phasor*np.exp(1j*phase))))
        # Render the short-window fit in the same voltage coordinates as the
        # surrounding residual, accounting for the two different trend fits.
        short_trend = y[fit_samples]-detrend(y[fit_samples])
        return fitted + (short_trend-local_baseline[fit_samples-left])

    def event_times(indices: Int) -> Float:
        return t[indices[(indices >= left) & (indices < right)]]

    b1, m4 = _point(bundle.b1, frame_index), _point(bundle.m4, frame_index)
    category, reason = bundle.diff_categories[frame_index], bundle.m4.rejection_reasons[frame_index]
    rail = bundle.rail_mask[local]
    return LocalComparisonWaveform(
        frame_index, center, t[local], y[local], readonly(local_baseline), readonly(residual),
        readonly(event_times(bundle.dc_step_indices)), readonly(t[local][rail]),
        readonly(y[local][rail]), readonly(event_times(bundle.rail_exit_indices)),
        readonly(fit_time), (center-width/(2*fs), center+width/(2*fs)),
        readonly(fit(b1, 0.)), readonly(fit(m4, m4.chirp_hz_s)), b1, m4, category, reason,
        f"{CATEGORY_ZH[category]} · {REASON_ZH[reason]}",
    )
