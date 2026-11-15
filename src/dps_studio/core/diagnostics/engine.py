"""Pure diagnostic engine, ported from TASK-017 compare / TASK-018 inputs and fuse.

No artifact lookup or GUI dependency. Evidence uses symmetric ``np.hanning``;
display/estimator STFT uses the periodic Hann, as in the reference scripts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from time import perf_counter

import numpy as np
from numpy.typing import ArrayLike

from dps_studio.algorithms.waveform.clutter_varpro.implementation import run as run_clutter
from dps_studio.algorithms.waveform.common import Context, Estimate, Signal
from dps_studio.algorithms.waveform.dechirp.implementation import run as run_dechirp
from dps_studio.algorithms.waveform.matrix_pencil.implementation import run as run_pencil
from dps_studio.algorithms.waveform.varpro.implementation import run as run_varpro
from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation.models import EstimatorRequest
from dps_studio.core.segmentation.pool import default_pool
from dps_studio.core.segmentation.strategies import (
    Strategy,
    baseline,
    estimate_strategy,
    fit_tone,
    project_out,
)

from .explanations import explain_candidate
from .models import (
    CLUSTER_WIDTH_HZ,
    COMPARED_CURVE_METHODS,
    DIAGNOSTIC_FMAX_HZ,
    DIAGNOSTIC_FMIN_HZ,
    ESTIMATOR_DISPLAY,
    FAMILY,
    METHODS,
    CandidateEntry,
    ClusterSummary,
    DiagnosticBundle,
    DiagnosticComputeMode,
    FloatArray,
    FrameTags,
    IntArray,
    LocalFrameEvidence,
    MethodCurve,
    SpectrogramLayer,
    StageSegment,
)

_PRIORITY = {m: i for i, m in enumerate(METHODS)}
_NATIVE: dict[str, tuple[Callable[[Context], Estimate], int]] = {
    "dechirp": (run_dechirp, 512),
    "varpro": (run_varpro, 384),
    "clutter_varpro": (run_clutter, 384),
    "matrix_pencil": (run_pencil, 96),
}
_STRATEGIES = {
    "B1": Strategy(width=512, hop=128, nfft=4096, boundary="full", degree=0),
    "B2": Strategy(width=2048, hop=128, nfft=4096, boundary="full", degree=0),
    "low_glrt": Strategy(width=4096, hop=128, boundary="full", degree=2, mode="glrt"),
}


class DiagnosticCancelledError(RuntimeError):
    """The caller cancelled computation; no partial bundle is published."""


def _check(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DiagnosticCancelledError("Diagnostic computation cancelled")


def _record(time_s: ArrayLike | SignalRecord, voltage_v: ArrayLike | None) -> SignalRecord:
    if isinstance(time_s, SignalRecord):
        if voltage_v is not None:
            raise ValueError("Supply either a SignalRecord or time and voltage")
        record = time_s
    else:
        if voltage_v is None:
            raise ValueError("voltage_v is required with time_s")
        record = SignalRecord(time_s, voltage_v, uniformity_relative_tolerance=1e-5)
    if (
        record.sample_count < 1024
        or not record.is_uniformly_sampled
        or record.maximum_relative_interval_deviation > 1e-5
    ):
        raise ValueError("Diagnostics require >=1024 continuous uniform samples; no resampling")
    return record


def _band(fs: float, low: float, high: float) -> None:
    if not np.isfinite([low, high]).all() or not 0 < low < min(high, fs * 0.49):
        raise ValueError("Invalid finite diagnostic frequency band")


def background_stop_for_stages(t: FloatArray, stages: Sequence[StageSegment]) -> int:
    """TASK-017 cutoff: min(4096, onset lower bound - 2 ns).

    Without visual onset, use TASK-018's fixed-prefix control (N//20, cap 2048).
    This explicit assumption is recorded in bundle provenance, never a measured quiet state.
    """
    onset = next((s for s in stages if s.stage == "onset"), None)
    if onset is None:
        return min(len(t) // 20, 2048)
    start = onset.start_range_s[0] if onset.start_range_s is not None else onset.start_s
    return min(4096, int(np.searchsorted(t, start - 2e-9)))


@dataclass(frozen=True, slots=True)
class _Evidence:
    spectra: FloatArray
    background: FloatArray
    frequency: FloatArray
    tau: tuple[FloatArray, ...]
    voltage: tuple[FloatArray, ...]
    width: int


def _background(y: FloatArray, fs: float, stop_index: int, width: int) -> FloatArray:
    nfft = max(4096, width * 2)
    last = min(max(4096, width * 4), stop_index)
    stop = last - width // 2 + (1 if width > 256 else 0)
    frames = [
        abs(np.fft.rfft((yy - yy.mean()) * np.hanning(width), n=nfft)) ** 2
        for c in range(width // 2, max(width // 2, stop), 128)
        for yy in (y[c - width // 2 : c + width // 2],)
    ]
    return (
        np.asarray(np.median(frames, axis=0), dtype=np.float64)
        if frames
        else np.full(nfft // 2 + 1, np.nan)
    )


def _evidence(
    record: SignalRecord,
    q: IntArray,
    stop: int,
    width: int = 256,
    cancel_event: Event | None = None,
) -> _Evidence:
    fs, t, y = record.sample_rate_hz, record.time_s, record.voltage_v
    spectra: list[FloatArray] = []
    taus: list[FloatArray] = []
    raw: list[FloatArray] = []
    for i, c in enumerate(q):
        if i % 32 == 0:
            _check(cancel_event)
        left, right = max(0, int(c) - width // 2), min(len(t), int(c) + width // 2)
        tau = (np.arange(left, right) - c) / fs
        yy = y[left:right]
        null = baseline(tau, 1)
        residual = project_out(null, yy)
        spectra.append(
            np.asarray(
                abs(np.fft.rfft(residual * np.hanning(len(yy)), n=max(4096, width * 2))) ** 2,
                dtype=np.float64,
            )
        )
        taus.append(tau)
        raw.append(yy)
    return _Evidence(
        np.asarray(spectra),
        _background(y, fs, stop, width),
        np.fft.rfftfreq(max(4096, width * 2), 1 / fs),
        tuple(taus),
        tuple(raw),
        width,
    )


@dataclass(frozen=True, slots=True)
class _Metrics:
    spectral_contrast_db: float = np.nan
    background_gain_db: float = np.nan
    relative_strongest_db: float = np.nan
    competitor_advantage_db: float = np.nan
    raw_tone_r2: float = np.nan
    raw_chirp_r2: float = np.nan
    raw_tone_residual_rms_v: float = np.nan
    raw_chirp_residual_rms_v: float = np.nan
    cycles_256: float = np.nan
    s_supported: bool = False


def _diagnose(ev: _Evidence, i: int, hz: float, rate: float, fs: float) -> _Metrics:
    if not np.isfinite(hz):
        return _Metrics()
    p, grid = ev.spectra[i], ev.frequency
    band = (grid >= 50e6) & (grid <= 8e9)  # Reference evidence band, not evaluation band.
    near = abs(grid - hz) <= fs / ev.width * 0.5
    if not np.any(near) or not np.any(band):
        return _Metrics()
    selected = max(float(p[near].max()), 1e-30)
    noise = max(float(np.median(p[band])), 1e-30)
    bg = max(float(ev.background[near].max()), 1e-30)
    strongest = max(float(p[band].max()), 1e-30)
    other = band & (abs(grid - hz) >= 2 * fs / ev.width)
    competitor = max(float(p[other].max()), 1e-30) if np.any(other) else 1e-30
    contrast, gain = float(10 * np.log10(selected / noise)), float(10 * np.log10(selected / bg))
    tau, yy = ev.tau[i], ev.voltage[i]
    null = baseline(tau, 1)
    rate = rate if np.isfinite(rate) else 0.0
    r2tone, _, _, etone = fit_tone(tau, yy, hz, null, 0.0)
    r2chirp, _, _, echirp = fit_tone(tau, yy, hz, null, rate)
    cycles = hz * float(np.ptp(tau))
    return _Metrics(
        contrast,
        gain,
        float(10 * np.log10(selected / strongest)),
        float(10 * np.log10(competitor / selected)),
        r2tone,
        r2chirp,
        float(np.sqrt(np.mean(etone**2))),
        float(np.sqrt(np.mean(echirp**2))),
        cycles,
        bool(contrast >= 10 and gain >= 6 and cycles >= 1 and max(r2tone, r2chirp) >= 0.20),
    )


def inspect_frame(
    time_s: ArrayLike,
    voltage_v: ArrayLike,
    sample_index: int,
    background_stop_index: int,
    *,
    focus_frequency_hz: float,
    focus_chirp_hz_s: float = 0.0,
    focus_label: str = "",
    fmin_hz: float = DIAGNOSTIC_FMIN_HZ,
    fmax_hz: float = DIAGNOSTIC_FMAX_HZ,
    window_width: int = 256,
) -> LocalFrameEvidence:
    """The actual projected least-squares model, including baseline in raw-space fits.

    ``*_psd_db`` retains the historical unnormalized FFT power (dB re 1 V²),
    not a per-Hz density. ``cycles_256`` uses the inspected window's actual span
    even when window_width=512; S at 512 is a separate diagnostic, not frozen S.
    """
    record = _record(time_s, voltage_v)
    _band(record.sample_rate_hz, fmin_hz, fmax_hz)
    if not 0 <= sample_index < record.sample_count:
        raise IndexError(sample_index)
    if not 0 <= background_stop_index <= record.sample_count:
        raise ValueError("Background cutoff outside samples")
    if window_width < 16 or window_width % 2:
        raise ValueError("Evidence window must have an even width >=16")
    ev = _evidence(
        record, np.array([sample_index], dtype=np.int64), background_stop_index, window_width
    )
    fs = record.sample_rate_hz
    tau, yy = ev.tau[0], ev.voltage[0]
    null = baseline(tau, 1)
    base = null @ np.linalg.lstsq(null, yy, rcond=1e-10)[0]
    residual = yy - base
    rate = focus_chirp_hz_s if np.isfinite(focus_chirp_hz_s) else 0.0
    metrics = _diagnose(ev, 0, focus_frequency_hz, rate, fs)
    fits: list[FloatArray] = []
    for chirp in (0.0, rate):
        if np.isfinite(focus_frequency_hz):
            _, _, _, error = fit_tone(tau, yy, focus_frequency_hz, null, chirp)
            fits.append(residual - error)
        else:
            fits.append(np.full(len(yy), np.nan))
    band = (ev.frequency >= 50e6) & (ev.frequency <= 8e9)
    other = band & (abs(ev.frequency - focus_frequency_hz) >= 2 * fs / window_width)

    def peak(mask: np.ndarray[tuple[int, ...], np.dtype[np.bool_]]) -> float:
        bins = np.flatnonzero(mask)
        return float(ev.frequency[bins[np.argmax(ev.spectra[0, bins])]]) if len(bins) else np.nan

    return LocalFrameEvidence(
        sample_index,
        float(record.time_s[sample_index]),
        window_width,
        background_stop_index,
        tau,
        yy,
        base,
        residual,
        float(np.mean(yy)),
        float(np.ptp(base)),
        ev.frequency,
        10 * np.log10(np.maximum(ev.spectra[0], 1e-30)),
        10 * np.log10(np.maximum(ev.background, 1e-30)),
        focus_frequency_hz,
        focus_chirp_hz_s,
        focus_label,
        fits[0],
        fits[1],
        base + fits[0],
        base + fits[1],
        metrics.spectral_contrast_db,
        metrics.background_gain_db,
        metrics.relative_strongest_db,
        metrics.competitor_advantage_db,
        metrics.raw_tone_r2,
        metrics.raw_chirp_r2,
        metrics.raw_tone_residual_rms_v,
        metrics.raw_chirp_residual_rms_v,
        metrics.cycles_256,
        metrics.s_supported,
        peak(band),
        peak(other),
    )


def _spectrogram(
    record: SignalRecord,
    q: IntArray,
    width: int,
    degree: int | None,
    high: float,
    cancel_event: Event | None,
) -> SpectrogramLayer:
    grid = np.fft.rfftfreq(4096, 1 / record.sample_rate_hz)
    keep = grid <= high
    power = np.full((int(keep.sum()), len(q)), np.nan)
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(width) / width)
    windows = np.lib.stride_tricks.sliding_window_view(record.voltage_v, width)
    valid = np.flatnonzero((q >= width // 2) & (q <= record.sample_count - width // 2))
    for start in range(0, len(valid), 64):
        _check(cancel_event)
        indices = valid[start : start + 64]
        yy = windows[q[indices] - width // 2]
        if degree == 0:
            yy = yy - yy.mean(axis=1, keepdims=True)
        spectrum = abs(np.fft.rfft(yy * hann, n=4096, axis=1) / hann.sum()) ** 2
        power[:, indices] = (10 * np.log10(np.maximum(spectrum[:, keep], 1e-30))).T
    return SpectrogramLayer(
        record.time_s[q],
        grid[keep],
        power,
        f"Hann W{width} H128 NFFT4096 degree={degree}; dB re 1 V²",
    )


@dataclass(frozen=True, slots=True)
class _Trace:
    time: FloatArray
    raw: FloatArray
    gated: FloatArray
    flags: tuple[str, ...]
    rate: FloatArray
    width: int
    fmin: float
    fmax: float
    source: str


def _request(record: SignalRecord, width: int, low: float, high: float) -> EstimatorRequest:
    return EstimatorRequest(
        record,
        record.start_time_s,
        record.end_time_s,
        1.55e-6,
        {
            "window_length_samples": width,
            "overlap_samples": width - 64,
            "nfft": max(4096, width),
            "window_name": "hann",
            "minimum_frequency_hz": low,
            "maximum_frequency_hz": high,
        },
    )


def _trace(
    record: SignalRecord, name: str, context: Context, low: float, high: float
) -> tuple[_Trace, _Trace | None]:
    if name in _NATIVE:
        runner, width = _NATIVE[name]
        result = runner(context)
        source = f"dps_studio.algorithms.waveform.{name}.implementation.run"
        trace = _Trace(
            context.time_s,
            result.frequency_hz,
            result.accepted_hz,
            tuple(str(s) for s in result.flags),
            result.extra.get("chirp_hz_per_s", np.zeros(len(context.time_s))),
            width,
            5e6,
            8e9,
            source,
        )
        second = None
        if name == "matrix_pencil":
            f = result.extra["secondary_frequency_hz"]
            second = replace(
                trace,
                raw=f,
                gated=np.full_like(f, np.nan),
                flags=tuple(
                    "SECONDARY_NO_NATIVE_GATE" if np.isfinite(hz) else flag
                    for hz, flag in zip(f, trace.flags, strict=True)
                ),
                source=source + " / secondary_frequency_hz",
            )
        return trace, second
    if name == "B0":
        width = 1024
        estimate = default_pool().estimate("stft", _request(record, width, low, high))
        source = "core.segmentation.pool._stft / formal workflow (original gate)"
    else:
        spec = _STRATEGIES[name]
        width = spec.width
        estimate = estimate_strategy(_request(record, width, low, high), name, spec)
        source = f"core.segmentation.strategies.estimate_strategy / {spec}"
    return _Trace(
        estimate.time_s,
        estimate.candidate_frequency_hz,
        estimate.frequency_hz,
        estimate.quality,
        np.zeros(len(estimate.time_s)),
        width,
        low,
        250e6 if name == "low_glrt" else high,
        source,
    ), None


def _candidate_rows(
    record: SignalRecord,
    q: IntArray,
    tr: _Trace,
    name: str,
    ev: _Evidence,
    rank: int,
    low: float,
    high: float,
    cancel_event: Event | None,
) -> list[CandidateEntry]:
    fs, t = record.sample_rate_hz, record.time_s
    centers = np.rint((tr.time - t[0]) * fs).astype(np.int64)
    if len(np.unique(centers)) != len(centers) or np.any(centers < 0) or np.any(centers >= len(t)):
        raise ValueError("Invalid or duplicate native sample centers")
    if np.max(abs(tr.time - t[centers]), initial=0.0) > 5e-15:
        raise ValueError("Physical center mismatch beyond recorded rounding")
    positions = np.searchsorted(centers, q)
    aligned = positions < len(centers)
    aligned[aligned] &= centers[positions[aligned]] == q[aligned]
    raw, gate, rates = (np.full(len(q), np.nan) for _ in range(3))
    flags = ["NO_NATIVE_CENTER"] * len(q)
    raw[aligned], gate[aligned], rates[aligned] = (
        v[positions[aligned]] for v in (tr.raw, tr.gated, tr.rate)
    )
    # normalize() first enforces the estimator's native band on gated output.
    gate[~(np.isfinite(gate) & (gate >= tr.fmin) & (gate <= tr.fmax))] = np.nan
    if rank > 1:
        gate[:] = np.nan
    for native_i in np.flatnonzero(aligned):
        flags[native_i] = tr.flags[positions[native_i]]
    rows: list[CandidateEntry] = []
    cap = min(high, tr.fmax)
    for i, center in enumerate(q):
        if i % 32 == 0:
            _check(cancel_event)
        flag, status = flags[i], "RAN"
        for token, label in (
            ("NO_NATIVE_CENTER", "NO_NATIVE_CENTER"),
            ("NO_EVENT", "NO_EVENT"),
            ("PRE_EVENT", "PRE_EVENT"),
            ("INSUFFICIENT", "INSUFFICIENT_WINDOW"),
            ("NOT_RUN_MANUAL_SCOPE", "NOT_RUN_MANUAL_SCOPE"),
        ):
            if token in flag:
                status = label
        if name == "low_glrt" and (center < tr.width // 2 or center > len(t) - tr.width // 2):
            status = "NO_COMPLETE_GLRT_WINDOW"
        applicable = status == "RAN"
        c = bool(np.isfinite(raw[i]) and low <= raw[i] <= cap and applicable)
        g = bool(c and np.isfinite(gate[i]) and low <= gate[i] <= cap)
        hz = float(raw[i]) if c else np.nan
        m = _diagnose(ev, i, hz, float(rates[i]), fs)
        rows.append(
            CandidateEntry(
                source_row=0,
                sample_index=int(center),
                time_s=float(t[center]),
                estimator=name,
                family=FAMILY[name],
                native_rank=rank,
                source_label=tr.source,
                raw_frequency_hz=float(raw[i]),
                frequency_hz=hz,
                native_gated_hz=float(gate[i]),
                chirp_hz_s=float(rates[i]),
                native_quality=flag,
                applicable=applicable,
                run_status=status,
                c_present=c,
                g_accepted=g,
                s_supported=m.s_supported,
                spectral_contrast_db=m.spectral_contrast_db,
                background_gain_db=m.background_gain_db,
                relative_strongest_db=m.relative_strongest_db,
                competitor_advantage_db=m.competitor_advantage_db,
                raw_tone_r2=m.raw_tone_r2,
                raw_chirp_r2=m.raw_chirp_r2,
                raw_tone_residual_rms_v=m.raw_tone_residual_rms_v,
                raw_chirp_residual_rms_v=m.raw_chirp_residual_rms_v,
                cycles_256=m.cycles_256,
                evaluation_max_hz=cap,
            )
        )
    return rows


@dataclass(frozen=True, slots=True)
class _Vote:
    cluster: int
    score: float
    voters: int
    eligible: int
    representative: CandidateEntry
    supporters: tuple[str, ...]


def _priority(c: CandidateEntry) -> tuple[int, int]:
    return c.native_rank, _PRIORITY[c.estimator]


def _clusters(rows: Sequence[CandidateEntry]) -> list[list[CandidateEntry]]:
    groups: list[list[CandidateEntry]] = []
    for c in sorted(
        (c for c in rows if c.c_present), key=lambda c: (c.frequency_hz, _priority(c), c.source_row)
    ):
        if not groups or c.frequency_hz - groups[-1][0].frequency_hz > CLUSTER_WIDTH_HZ:
            groups.append([])
        groups[-1].append(c)
    return groups


def _vote(
    groups: Sequence[Sequence[CandidateEntry]],
    caps: dict[str, float],
    *,
    family: bool,
    require_support: bool = False,
) -> list[_Vote]:
    by_voter: dict[str, set[int]] = defaultdict(set)
    presence: list[set[str]] = []
    supported: list[set[str]] = []
    for k, group in enumerate(groups):
        units, evidence = set(), set()
        for c in group:
            unit = c.family if family else c.estimator
            if unit not in caps or c.frequency_hz > caps[unit]:
                raise ValueError("Candidate outside voter eligibility")
            units.add(unit)
            if c.s_supported:
                evidence.add(unit)
            by_voter[unit].add(k)
        presence.append(units)
        supported.append(evidence)
    budgets = Counter({key: len(ks) for key, ks in by_voter.items()})
    peaks: list[_Vote] = []
    for k, group in enumerate(groups):
        voters = supported[k] if require_support else presence[k]
        selection = [c for c in group if not require_support or c.s_supported]
        if not selection:
            continue
        representative = min(selection, key=lambda c: (_priority(c), c.frequency_hz, c.source_row))
        mass = sum(1 / budgets[v] for v in sorted(voters))
        denominator = sum(cap >= group[0].frequency_hz for cap in caps.values())
        peaks.append(
            _Vote(
                k,
                mass / denominator,
                len(voters),
                denominator,
                representative,
                tuple(sorted(voters)),
            )
        )
    return sorted(
        peaks,
        key=lambda p: (
            -p.score,
            -p.voters,
            _priority(p.representative),
            p.representative.frequency_hz,
            p.cluster,
        ),
    )


def _fuse_frame(
    rows: Sequence[CandidateEntry],
    *,
    full: bool,
) -> tuple[tuple[CandidateEntry, ...], tuple[ClusterSummary, ...], _Vote | None, _Vote | None]:
    ecaps: dict[str, float] = {}
    fcaps: dict[str, float] = {}
    for c in rows:
        if c.applicable:
            ecaps[c.estimator] = c.evaluation_max_hz
            fcaps[c.family] = max(fcaps.get(c.family, 0.0), c.evaluation_max_hz)
    groups = _clusters(rows)
    s0 = _vote(groups, ecaps, family=False)
    s1 = _vote(groups, fcaps, family=True)
    s2 = _vote(groups, fcaps, family=True, require_support=True)
    a, b, d = ({v.cluster: v for v in seq} for seq in (s0, s1, s2))
    members: dict[int, CandidateEntry] = {}
    summaries: list[ClusterSummary] = []
    for k, group in enumerate(groups):
        x, y, z = a[k], b[k], d.get(k)
        f = y.representative.frequency_hz
        other = [c.frequency_hz for idx, g in enumerate(groups) if idx != k for c in g]
        harmonic = any(
            abs(f - r * h) <= CLUSTER_WIDTH_HZ or abs(h - r * f) <= CLUSTER_WIDTH_HZ
            for h in other
            for r in (2, 3)
        )
        hi = y.score >= 0.6 and y.voters >= 3
        summaries.append(
            ClusterSummary(
                group[0].sample_index,
                group[0].time_s,
                k,
                group[0].frequency_hz,
                group[-1].frequency_hz,
                f,
                len(group),
                len(groups),
                len(s2),
                len(groups) > 1,
                hi,
                hi and z is None,
                harmonic,
                f <= 100e6,
                y.representative.background_gain_db < 6,
                x.score,
                y.score,
                z.score if z else 0.0,
                z.voters if z else 0,
                z.eligible if z else y.eligible,
                bool(z and z.representative.g_accepted),
                bool(z and z.representative.s_supported),
                bool(full and z and z == s2[0]),
                z.supporters if z else (),
            )
        )
        for c in group:
            members[c.source_row] = replace(
                c,
                cluster_id=k,
                s0_score=x.score,
                s1_score=y.score,
                s2_score=z.score if z else 0.0,
                family_votes=y.voters,
                supported_family_votes=z.voters if z else 0,
                competing_clusters=len(groups) - 1,
                s0_selected=c.source_row == s0[0].representative.source_row,
                s1_selected=c.source_row == s1[0].representative.source_row,
                s2_selected=bool(full and s2 and c.source_row == s2[0].representative.source_row),
            )
    return (
        tuple(members.get(c.source_row, c) for c in rows),
        tuple(summaries),
        s2[0] if s2 and full else None,
        s1[0] if s1 else None,
    )


def _curve(
    method: str,
    q: IntArray,
    times: FloatArray,
    representatives: Sequence[CandidateEntry | None],
    proposals: Sequence[CandidateEntry | None],
    clusters: Sequence[int],
    *,
    conflicts: Sequence[bool] | None = None,
    voters: Sequence[int] | None = None,
) -> MethodCurve:
    quality: list[str] = []
    for i, (r, pre) in enumerate(zip(representatives, proposals, strict=True)):
        quality.append(
            "NO_S"
            if pre and not r
            else "NO_C"
            if not r
            else "SUPPORTED_COMPETING"
            if r.s_supported and conflicts and conflicts[i]
            else "SUPPORTED_CROSS_FAMILY"
            if r.s_supported and voters and voters[i] >= 2 and method == "S2"
            else "SUPPORTED"
            if r.s_supported
            else "UNSUPPORTED"
        )
    return MethodCurve(
        method,
        q,
        times,
        np.array([p is not None for p in proposals]),
        np.array([bool(r and r.g_accepted) for r in representatives]),
        np.array([bool(r and r.s_supported) for r in representatives]),
        np.array([r is not None for r in representatives]),
        np.array([r.frequency_hz if r else np.nan for r in representatives]),
        np.array(
            [
                (r or p).frequency_hz if p and (r or p) else np.nan
                for r, p in zip(representatives, proposals, strict=True)
            ]
        ),
        tuple(r.estimator if r else "" for r in representatives),
        tuple(quality),
        np.asarray(clusters, dtype=np.int64),
    )


def curves_from_candidates(
    q: IntArray, times: FloatArray, frames: Sequence[Sequence[CandidateEntry]]
) -> dict[str, MethodCurve]:
    """TASK-018 C curves plus TASK-020 B+S; native names map only at display boundary."""
    curves: dict[str, MethodCurve] = {}
    for estimator in ("B0", "B1", "dechirp", "varpro"):
        reps = [
            next(
                (c for c in row if c.estimator == estimator and c.native_rank == 1 and c.c_present),
                None,
            )
            for row in frames
        ]
        name = ESTIMATOR_DISPLAY.get(estimator, estimator)
        curves[name] = _curve(name, q, times, reps, reps, [-1] * len(q))
    b1 = [next((c for c in row if c.estimator == "B1" and c.c_present), None) for row in frames]
    chosen = [c if c and c.s_supported else None for c in b1]
    curves["B+S"] = _curve("B+S", q, times, chosen, b1, [-1] * len(q))
    return curves


def _tags(
    times: FloatArray,
    stages: Sequence[StageSegment],
    curves: dict[str, MethodCurve],
    candidates: Sequence[Sequence[CandidateEntry]],
    clusters: Sequence[Sequence[ClusterSummary]],
) -> FrameTags:
    n = len(times)
    stage = ["unknown"] * n
    for j, seg in enumerate(stages):
        if not np.isfinite([seg.start_s, seg.end_s]).all() or seg.start_s >= seg.end_s:
            raise ValueError("Invalid stage interval")
        if j and seg.start_s < stages[j - 1].end_s:
            raise ValueError("Overlapping or unordered stage intervals")
        mask = (times >= seg.start_s) & (
            (times <= seg.end_s) if j == len(stages) - 1 else (times < seg.end_s)
        )
        for stage_i in np.flatnonzero(mask):
            stage[stage_i] = seg.stage
    disagreement, gs, rescued, competing, high = (np.zeros(n, dtype=bool) for _ in range(5))
    compared = [curves[k] for k in COMPARED_CURVE_METHODS if k in curves]
    for i in range(n):
        fs = [
            float(c.frequency_hz[i])
            for c in compared
            if c.selected[i] and np.isfinite(c.frequency_hz[i])
        ]
        disagreement[i] = bool(fs and max(fs) - min(fs) > CLUSTER_WIDTH_HZ)
        gs[i] = any(c.g_accepted[i] and not c.s_supported[i] for c in compared) or any(
            c.g_accepted and not c.s_supported for c in candidates[i]
        )
        c2 = curves.get("S2")
        rescued[i] = any(
            c.s_supported and c.raw_chirp_r2 >= 0.20 and c.raw_tone_r2 < 0.20 for c in candidates[i]
        )
        if c2 is not None and c2.selected[i] and c2.s_supported[i]:
            rescued[i] |= any(
                k in curves
                and (
                    not curves[k].selected[i]
                    or not curves[k].g_accepted[i]
                    or not curves[k].s_supported[i]
                    or abs(curves[k].frequency_hz[i] - c2.frequency_hz[i]) > CLUSTER_WIDTH_HZ
                )
                for k in ("B0", "B1")
            )
        competing[i] = any(c.s_clusters_at_center > 1 for c in clusters[i])
        high[i] = any(c.high_without_s for c in clusters[i])
    return FrameTags(tuple(stage), disagreement, gs, rescued, competing, high)


def assemble_bundle(
    record: SignalRecord,
    *,
    channel_name: str,
    source_path: Path | None,
    stop: int,
    low: float,
    high: float,
    stages: tuple[StageSegment, ...],
    curves: dict[str, MethodCurve],
    candidates: tuple[tuple[CandidateEntry, ...], ...],
    clusters: tuple[tuple[ClusterSummary, ...], ...],
    mode: DiagnosticComputeMode,
    provenance: str,
    display_fmax_hz: float = 10e9,
    cancel_event: Event | None = None,
    metrics: dict[str, int | float | str] | None = None,
) -> DiagnosticBundle:
    """Shared live/frozen construction; never runs estimators for frozen inputs."""
    q = np.arange(0, record.sample_count, 128, dtype=np.int64)
    display_high = min(0.5 * record.sample_rate_hz, display_fmax_hz)
    if not np.isfinite(display_high) or display_high <= 0:
        raise ValueError("Display frequency limit must be positive and finite")
    raw = _spectrogram(record, q, 1024, None, display_high, cancel_event)
    demeaned = _spectrogram(record, q, 512, 0, display_high, cancel_event)
    tags = _tags(record.time_s[q], stages, curves, candidates, clusters)
    explained: list[tuple[CandidateEntry, ...]] = []
    for i, row in enumerate(candidates):
        if i % 32 == 0:
            _check(cancel_event)
        lookup = {c.cluster_id: c for c in clusters[i]}
        b0 = curves.get("B0")
        dc = bool(
            b0 is not None
            and b0.selected[i]
            and b0.frequency_hz[i] < 250e6
            and not b0.s_supported[i]
            and any(
                k in curves
                and curves[k].selected[i]
                and curves[k].s_supported[i]
                and curves[k].frequency_hz[i] >= 250e6
                for k in ("B1", "S2")
            )
        )
        entries: list[CandidateEntry] = []
        for c in row:
            code, yes, no = explain_candidate(
                c,
                cluster=lookup.get(c.cluster_id),
                dc_leak_hint=dc and c.estimator == "B0",
                fmin_hz=low,
            )
            entries.append(c.with_explanation(code, yes, no))
        explained.append(tuple(entries))
    summary: dict[str, int | float | str] = dict(metrics or {})
    summary.update(
        centers=len(q),
        primary_centers=int(((q >= 1024) & (q <= len(record.time_s) - 1024)).sum()),
        background_available=int(
            np.isfinite(_background(record.voltage_v, record.sample_rate_hz, stop, 256)).any()
        ),
        s2_status="NOT_RUN" if "S2" not in curves else "COMPUTED_OR_LOADED",
    )
    for name, curve in curves.items():
        summary[f"{name}_C_n"] = int(curve.c_present.sum())
        summary[f"{name}_G_n"] = int(curve.g_accepted.sum())
        summary[f"{name}_S_n"] = int(curve.s_supported.sum())
    return DiagnosticBundle(
        channel_name,
        source_path,
        record.sample_rate_hz,
        stop,
        low,
        high,
        record.time_s,
        record.voltage_v,
        q,
        record.time_s[q],
        raw,
        demeaned,
        curves,
        tuple(explained),
        clusters,
        stages,
        tags,
        summary,
        mode.value,
        provenance,
    )


def compute_diagnostic_bundle(
    time_s: ArrayLike | SignalRecord,
    voltage_v: ArrayLike | None = None,
    *,
    channel_name: str,
    source_path: Path | None = None,
    mode: DiagnosticComputeMode = DiagnosticComputeMode.FAST_CORE,
    fmin_hz: float = DIAGNOSTIC_FMIN_HZ,
    fmax_hz: float = DIAGNOSTIC_FMAX_HZ,
    stages: tuple[StageSegment, ...] = (),
    progress_callback: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
    display_fmax_hz: float = 10e9,
    background_stop_index: int | None = None,
) -> DiagnosticBundle:
    started = perf_counter()
    mode = DiagnosticComputeMode(mode)
    if mode == DiagnosticComputeMode.PRECOMPUTED_STACK:
        raise ValueError("Use load_precomputed_bundle for precomputed_stack")

    def step(label: str) -> None:
        _check(cancel_event)
        if progress_callback is not None:
            progress_callback(label)
        _check(cancel_event)

    step("validate")
    record = _record(time_s, voltage_v)
    _band(record.sample_rate_hz, fmin_hz, fmax_hz)
    q = np.arange(0, record.sample_count, 128, dtype=np.int64)
    stop = (
        background_stop_for_stages(record.time_s, stages)
        if background_stop_index is None
        else background_stop_index
    )
    if not 0 <= stop <= record.sample_count:
        raise ValueError("Background cutoff outside samples")
    step("shared_evidence")
    evidence = _evidence(record, q, stop, cancel_event=cancel_event)
    step("waveform_context")
    context = Context(Signal(np.array(record.time_s), np.array(record.voltage_v), channel_name))
    methods = (
        METHODS if mode == DiagnosticComputeMode.FULL_S2 else ("B1", "B0", "dechirp", "varpro")
    )
    blocks: list[list[CandidateEntry]] = []
    timings: dict[str, int | float | str] = {}
    source_offset = 0
    for name in methods:
        step(name)
        t0 = perf_counter()
        tr, second = _trace(record, name, context, fmin_hz, fmax_hz)
        _check(cancel_event)
        for rank, trace in enumerate((tr,) if second is None else (tr, second), 1):
            block = _candidate_rows(
                record, q, trace, name, evidence, rank, fmin_hz, fmax_hz, cancel_event
            )
            blocks.append([replace(c, source_row=source_offset + i) for i, c in enumerate(block)])
            source_offset += len(q)
        timings[name + "_estimate_and_audit_s"] = perf_counter() - t0
    step("fusion")
    frames: list[tuple[CandidateEntry, ...]] = []
    cluster_frames: list[tuple[ClusterSummary, ...]] = []
    winners: list[_Vote | None] = []
    proposals: list[_Vote | None] = []
    for i in range(len(q)):
        if i % 32 == 0:
            _check(cancel_event)
        row, clusters, winner, proposal = _fuse_frame(
            [b[i] for b in blocks], full=mode == DiagnosticComputeMode.FULL_S2
        )
        frames.append(row)
        cluster_frames.append(clusters)
        winners.append(winner)
        proposals.append(proposal)
    curves = curves_from_candidates(q, record.time_s[q], frames)
    if mode == DiagnosticComputeMode.FULL_S2:
        curves["S2"] = _curve(
            "S2",
            q,
            record.time_s[q],
            [w.representative if w else None for w in winners],
            [p.representative if p else None for p in proposals],
            [w.cluster if w else -1 for w in winners],
            conflicts=[bool(c and c[0].s_clusters_at_center > 1) for c in cluster_frames],
            voters=[w.voters if w else 0 for w in winners],
        )
    step("spectrograms_and_explanations")
    background_policy = (
        "explicit cutoff"
        if background_stop_index is not None
        else "TASK-017 visual onset lower bound minus 2 ns, cap 4096"
        if any(s.stage == "onset" for s in stages)
        else "TASK-018 fixed-prefix control min(N//20,2048); quietness unverified"
    )
    bundle = assemble_bundle(
        record,
        channel_name=channel_name,
        source_path=source_path or record.source_path,
        stop=stop,
        low=fmin_hz,
        high=fmax_hz,
        stages=stages,
        curves=curves,
        candidates=tuple(frames),
        clusters=tuple(cluster_frames),
        mode=mode,
        provenance=f"TASK-017/018/020 numerical port; background: {background_policy}; "
        "C/G/S distinct; no physical branch identification; no artifact dependency.",
        display_fmax_hz=display_fmax_hz,
        cancel_event=cancel_event,
        metrics=timings,
    )
    step("complete")
    bundle.summary_metrics["wall_s"] = perf_counter() - started
    return bundle
