"""Frozen B1 and M4 comparison algorithms on an imported SignalRecord."""
from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from threading import Event

import numpy as np

from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation.models import EstimatorRequest
from dps_studio.core.segmentation.strategies import Strategy, estimate_strategy

from ._evidence import Channel, RawEvaluator
from ._m4 import _support_edges, track_m4
from ._pursuit import rail_mask
from .models import ComparisonCancelledError, Estimate, SpectrogramMap
from .waveform import FMAX, FMIN, FLOOR, Bool, Float, Int, complete, offsets, samples_for_ns

Progress = Callable[[int, str], None]
_B1 = Strategy(width=512, hop=128, nfft=4096, boundary="full", degree=0)
_MATCHED_NAME = "STFT_25p6ns_quad"


def _channel(
    record: SignalRecord, fmin: float, fmax: float, cancel: Event | None,
    callback: Progress | None,
) -> Channel:
    def check() -> None:
        if cancel is not None and cancel.is_set():
            raise ComparisonCancelledError("对比计算已取消")

    def update(percent: int, stage: str) -> None:
        check()
        if callback is not None:
            callback(percent, stage)
        check()

    check()
    if not record.is_uniformly_sampled:
        raise ValueError("STFT / M4 需要均匀采样的时间轴")
    if not isfinite(fmin) or not isfinite(fmax) or fmin < 1. or fmax <= fmin:
        raise ValueError("搜索频带须为递增的有限频率，且下限至少为 1 Hz")
    fmax = min(fmax, .49 * record.sample_rate_hz)
    if fmax <= fmin:
        raise ValueError("频带下限须低于采样率的 49%")
    return Channel(record, fmin, fmax, check, update)


def _estimate_stft(ch: Channel, ev: RawEvaluator, name: str, spec: Strategy) -> Estimate:
    candidate = np.full(len(ch.q), np.nan)
    accepted = candidate.copy()
    flags = ["INSUFFICIENT_FULL_WINDOW"] * len(ch.q)
    use = np.flatnonzero(complete(ch.q, len(ch.y), spec.width))
    if len(use):
        request = EstimatorRequest(
            ch.record, ch.record.start_time_s, ch.record.end_time_s, 1.,
            {"minimum_frequency_hz": ch.fmin, "maximum_frequency_hz": ch.fmax},
        )
        native = estimate_strategy(request, name, spec, sample_centers=ch.q[use], check=ch.check)
        for dest, values in ((candidate, native.candidate_frequency_hz),
                             (accepted, native.frequency_hz)):
            dest[use] = np.where((values >= ch.fmin) & (values <= ch.fmax), values, np.nan)
        for i, quality in zip(use, native.quality, strict=True):
            flags[i] = quality
    rate = np.zeros(len(ch.q))
    raw = ev.evaluate(candidate, rate)
    return Estimate(ch.q, candidate, accepted, rate, raw, {}, tuple(flags))


def _b1_map(ch: Channel) -> SpectrogramMap:
    sample = offsets(_B1.width)
    taper = .5 - .5*np.cos(2*np.pi*np.arange(_B1.width)/_B1.width)
    axis = np.fft.rfftfreq(_B1.nfft, 1/ch.fs)
    band = (axis >= ch.fmin) & (axis <= ch.fmax)
    power = np.empty((len(ch.q), np.count_nonzero(band)))
    for start in range(0, len(ch.q), 32):
        ch.check()
        q = ch.q[start:start+32]
        y = ch.y[q[:, None] + sample]
        spectrum = np.fft.rfft((y-y.mean(axis=1, keepdims=True))*taper, n=_B1.nfft)
        power[start:start+len(q)] = 10*np.log10(np.maximum(abs(spectrum[:, band])**2, FLOOR))
    return SpectrogramMap(ch.t[ch.q], ch.b1_frequency, power)


def _b1(ch: Channel, ev: RawEvaluator) -> tuple[Estimate, SpectrogramMap]:
    ch.update(4, "B1 峰值与原生门控")
    result = _estimate_stft(ch, ev, "B1", _B1)
    ch.update(17, "生成共用 B1 时频底图")
    return result, _b1_map(ch)


def _matched_stft(ch: Channel, ev: RawEvaluator) -> Estimate:
    ch.update(92, "等时长 STFT · 25.6 ns")
    width = samples_for_ns(25.6, ch.fs)
    spec = Strategy(width=width, hop=128, nfft=max(4096, 1 << (2*width-1).bit_length()),
                    boundary="full", degree=2)
    return _estimate_stft(ch, ev, _MATCHED_NAME, spec)


def _m4(
    ch: Channel, ev: RawEvaluator, capture_map: bool,
) -> tuple[Estimate, SpectrogramMap | None, Int, Bool]:
    rail = rail_mask(ch.y)
    edges, rail_exit = _support_edges(ch, rail)
    power: Float | None = (
        np.zeros((len(ch.q), len(ch.coherent_frequency)))
        if capture_map and len(ch.coherent_frequency)
        else None
    )
    estimate = track_m4(ch, ev, rail, edges, rail_exit, power)
    raster = None
    if power is not None:
        measured = power > 0.
        np.log10(power, out=power, where=measured)
        power *= 10.
        power[~measured] = np.nan
        raster = SpectrogramMap(ch.t[ch.q], ch.coherent_frequency, power)
    return estimate, raster, rail_exit, rail


def compute_b1_stft(
    record: SignalRecord, *, fmin_hz: float = FMIN, fmax_hz: float = FMAX,
    cancel_event: Event | None = None, progress_callback: Progress | None = None,
) -> tuple[Estimate, SpectrogramMap]:
    """Return B1's native peak/gate result and the common Hann power raster."""
    ch = _channel(record, fmin_hz, fmax_hz, cancel_event, progress_callback)
    ch.update(0, "准备 B1")
    result = _b1(ch, RawEvaluator(ch))
    ch.update(100, "B1 完成")
    return result


def compute_matched_stft_25p6ns(
    record: SignalRecord, *, fmin_hz: float = FMIN, fmax_hz: float = FMAX,
    cancel_event: Event | None = None, progress_callback: Progress | None = None,
) -> Estimate:
    ch = _channel(record, fmin_hz, fmax_hz, cancel_event, progress_callback)
    ch.update(0, "准备等时长 STFT")
    result = _matched_stft(ch, RawEvaluator(ch))
    ch.update(100, "等时长 STFT 完成")
    return result


def compute_m4_phase_coherent(
    record: SignalRecord, *, fmin_hz: float = FMIN, fmax_hz: float = FMAX,
    cancel_event: Event | None = None, progress_callback: Progress | None = None,
) -> Estimate:
    ch = _channel(record, fmin_hz, fmax_hz, cancel_event, progress_callback)
    ch.update(0, "准备 M4")
    ch.update(21, "估计静默频谱与电压边界")
    result, _, _, _ = _m4(ch, RawEvaluator(ch), False)
    ch.update(100, "M4 完成")
    return result
