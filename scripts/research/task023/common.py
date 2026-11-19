"""Frozen input, STFT baselines and original-voltage evidence for Phase 1."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cached_property
from time import perf_counter
from typing import Any, TypedDict, cast

import numpy as np

from scripts.research.task017.compare import diagnose, evidence, formal, frozen_plans, normalize
from scripts.research.task017.prepare import ROOT, load, records
from scripts.research.task018.inputs import strategy_trace
from scripts.research.task023.waveform import (
    FMAX, FMIN, FLOOR, Bool, Complex, Float, Int, Quiet, Steps, center_power, centers, chirp_phase,
    coherence, complete, offsets, quadrature, quadrature_stats, quiet_model, same_side_weights,
    samples_for_ns,
    split_half_coherence,
)


class Segment(TypedDict):
    id: str
    start_s: float
    end_s: float
    stage: str
    start_range_s: list[float]
    end_range_s: list[float]
    visual_evidence: str
    confidence: str
    physical_branch: str
    stationary_zero_is_measurement: bool


@dataclass(frozen=True)
class Channel:
    id: str
    t: Float
    y: Float
    fs: float
    segments: tuple[Segment, ...] = ()
    fmax: float = FMAX

    @cached_property
    def q(self) -> Int:
        return centers(len(self.y))

    @cached_property
    def primary(self) -> Bool:
        """Frozen TASK-020 mask on the requested center grid."""
        return (self.q >= 1024) & (self.q <= len(self.y)-1024)

    @cached_property
    def quiet(self) -> Quiet:
        return quiet_model(self.y, self.fs, self.q, fmax=self.fmax)


def load_channel(channel_id: str) -> Channel:
    plans = frozen_plans()
    for item in records():
        if item["id"] == channel_id:
            t, y, fs = load(item)
            t, y = np.asarray(t, dtype=np.float64), np.asarray(y, dtype=np.float64)
            t.flags.writeable = y.flags.writeable = False
            return Channel(channel_id, t, y, fs, tuple(cast(list[Segment], plans[channel_id])))
    raise KeyError(f"Unknown TASK-017 channel: {channel_id}")


@dataclass(frozen=True)
class RawEvidence:
    raw_tone_r2_256: Float
    raw_chirp_r2_256: Float
    S_256: Bool
    raw_tone_r2_64ns: Float
    raw_chirp_r2_64ns: Float
    raw_chirp_r2_256ns: Float
    split_half_coherence_256ns: Float
    local_center_snr_32ns: Float  # wideband dB, +/-3.2 ns diagnostic


@dataclass(frozen=True)
class MatchedEvidence:
    phasor: Complex
    r2: Float
    snr_db: Float
    half_snr_db: Float
    rho: Float
    snr_left_db: Float
    snr_right_db: Float

    @property
    def center_supported(self) -> Bool:
        """Require both sides of the short window to contribute to the chirp fit."""
        return (self.snr_db >= 7.) & (self.half_snr_db >= 3.) & (self.rho >= .25)


class RawEvaluator:
    """Evaluate center-aligned hypotheses on the original measured voltage.

    Column suffixes 64ns and 256ns denote 6.4 and 25.6 ns, respectively.
    The legacy 256-sample support retains its original 8 GHz diagnostic
    reference band and background stop, while candidates use the 6 GHz band.
    """

    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    @cached_property
    def legacy(self) -> dict[str, Any]:
        ch = self.channel
        onset = next((seg for seg in ch.segments if seg["stage"] == "onset"), None)
        stop = onset["start_range_s"][0]-2e-9 if onset else float(ch.t[len(ch.t)//4])
        return evidence(ch.t, ch.y, ch.fs, ch.q, stop)

    @cached_property
    def local_snr_db(self) -> Float:
        ch = self.channel
        power = center_power(ch.y, ch.q, samples_for_ns(6.4, ch.fs), ch.quiet.steps)
        return np.asarray(10*np.log10(np.maximum(power, FLOOR) / ch.quiet.noise_power_v2))

    @cached_property
    def center_supported(self) -> Bool:
        """Legacy wideband diagnostic flag for comparison with Phase 1A."""
        return self.local_snr_db >= self.channel.quiet.center_threshold_db

    def matched(
        self, frames: Int, hz: Float, rate: Float, duration_ns: float, *,
        steps: Steps | None = None, usable_samples: Bool | None = None,
    ) -> MatchedEvidence:
        """Fit raw voltage on the center's side of every detected step.

        Explained energy divided by twice the spectral floor has expectation
        one for a fixed two-quadrature fit under locally white Gaussian noise.
        The half-window statistic is the smaller of the two fitted powers.
        """
        ch = self.channel
        width = samples_for_ns(duration_ns, ch.fs)
        half = width // 2
        degree = 2 if duration_ns >= 25.6 else 1
        q = ch.q[frames]
        valid = np.flatnonzero(complete(q, len(ch.y), width) & np.isfinite(hz) & np.isfinite(rate))
        phasor = np.full(len(frames), np.nan + 1j*np.nan)
        r2, snr_db, half_snr_db, rho, left_db, right_db = (
            np.full(len(frames), np.nan) for _ in range(6)
        )
        sample = offsets(width)
        steps = ch.quiet.steps if steps is None else steps
        for start in range(0, len(valid), 128):
            ok = valid[start:start+128]
            indices = q[ok, None] + sample
            w = same_side_weights(q[ok], width, steps, len(ch.y))
            if usable_samples is not None:
                w *= usable_samples[indices]
            y = ch.y[indices]
            phase = chirp_phase(sample/ch.fs, hz[ok, None], rate[ok, None])
            bed = 2*np.interp(hz[ok], ch.quiet.frequency_hz, ch.quiet.floor_v2)
            phasor[ok], r2[ok], power = quadrature_stats(y, phase, w, degree)
            zl, _, pl = quadrature_stats(y[:, :half], phase[:, :half], w[:, :half], degree)
            zr, _, pr = quadrature_stats(y[:, half:], phase[:, half:], w[:, half:], degree)
            enough = (w[:, :half].sum(axis=1) >= half//4) & (w[:, half:].sum(axis=1) >= half//4)
            snr_db[ok] = 10*np.log10(np.maximum(power/bed, FLOOR))
            left_db[ok] = np.where(w[:, :half].sum(axis=1) >= half//4,
                                   10*np.log10(np.maximum(pl/bed, FLOOR)), -np.inf)
            right_db[ok] = np.where(w[:, half:].sum(axis=1) >= half//4,
                                    10*np.log10(np.maximum(pr/bed, FLOOR)), -np.inf)
            half_snr_db[ok] = np.where(
                enough, 10*np.log10(np.maximum(np.minimum(pl, pr)/bed, FLOOR)), -np.inf,
            )
            rho[ok] = np.where(enough, coherence(zl, zr), np.nan)
        return MatchedEvidence(phasor, r2, snr_db, half_snr_db, rho, left_db, right_db)

    def low_frequency_supported(self, frames: Int, hz: Float, rate: Float) -> Bool:
        """Demand sustained oscillation when a short fit spans fewer than 1.6 cycles."""
        verified = np.ones(len(frames), dtype=np.bool_)
        low = np.flatnonzero(hz < 250e6)
        # A slow baseline can fit subcycle quadratures with a large amplitude.
        # Test the hypothesis on a long quadratic residual with two-sided support.
        fit = self.matched(frames[low], hz[low], rate[low], 38.4)
        center = self.matched(frames[low], hz[low], rate[low], 6.4)
        amplitude_consistent = abs(center.phasor) <= 3.*abs(fit.phasor)
        positive = hz[low] > abs(rate[low])*19.2e-9
        verified[low] = (positive & amplitude_consistent & (fit.r2 >= .10) & (fit.rho >= .55)
                         & (fit.snr_db >= 8.) & (fit.half_snr_db >= 4.5))
        return verified

    def post_step_r2(self, hz: Float, rate: Float) -> Float:
        """Supplementary same-side raw fit just after a detected jump."""
        ch = self.channel
        width = samples_for_ns(6.4, ch.fs)
        steps = ch.quiet.steps
        last = np.r_[-len(ch.y), steps.index][np.searchsorted(steps.index, ch.q, side="right")]
        ok = (ch.q-last < width//2) & np.isfinite(hz)
        w = same_side_weights(ch.q[ok], width, steps, len(ch.y))
        sample = offsets(width)
        y = ch.y[ch.q[ok, None]+sample]
        _, fraction = quadrature(y, chirp_phase(sample/ch.fs, hz[ok, None], rate[ok, None]), w)
        result = np.full(len(ch.q), np.nan)
        result[ok] = np.where(w.sum(axis=1) >= width//2, fraction, np.nan)
        return result

    def evaluate(self, hz: Float, rate: Float) -> RawEvidence:
        ch = self.channel
        if hz.shape != ch.q.shape or rate.shape != ch.q.shape:
            raise ValueError("Hypotheses must match the TASK-023 center grid")
        legal = np.isfinite(hz) & (hz >= FMIN) & (hz <= ch.fmax)
        rate = np.where(np.isfinite(rate), rate, 0.)
        legacy = diagnose(dict(time_s=ch.t[ch.q], frequency_hz=np.where(legal, hz, np.nan),
                               chirp_hz_s=rate), self.legacy, ch.fs)
        short_tone = np.full(len(hz), np.nan)
        short_chirp, long_chirp, rho = (short_tone.copy() for _ in range(3))
        short = samples_for_ns(6.4, ch.fs)
        if short == 256:
            short_tone[:] = legacy["raw_tone_r2"]
            short_chirp[:] = legacy["raw_chirp_r2"]
        else:
            ok = legal & complete(ch.q, len(ch.y), short)
            tau = offsets(short) / ch.fs
            y = ch.y[ch.q[ok, None] + offsets(short)]
            _, short_tone[ok] = quadrature(y, chirp_phase(tau, hz[ok, None], 0.))
            _, short_chirp[ok] = quadrature(y, chirp_phase(tau, hz[ok, None], rate[ok, None]))
        long = samples_for_ns(25.6, ch.fs)
        ok = legal & complete(ch.q, len(ch.y), long)
        tau = offsets(long) / ch.fs
        y = ch.y[ch.q[ok, None] + offsets(long)]
        phase = chirp_phase(tau, hz[ok, None], rate[ok, None])
        _, long_chirp[ok] = quadrature(y, phase, degree=2)
        rho[ok] = split_half_coherence(y, phase, degree=2)
        return RawEvidence(np.asarray(legacy["raw_tone_r2"]), np.asarray(legacy["raw_chirp_r2"]),
                           np.asarray(legacy["spectrally_supported"]), short_tone, short_chirp,
                           long_chirp, rho, self.local_snr_db)


@dataclass(frozen=True)
class Estimate:
    sample_index: Int
    candidate_hz: Float
    accepted_hz: Float
    chirp_hz_s: Float
    raw: RawEvidence
    diagnostics: dict[str, Float | Int | Bool]


def run_baselines(channel: Channel, timing: dict[str, float] | None = None) -> dict[str, Estimate]:
    """B0 and B1 use their frozen native outputs. B+S gates B1 candidates."""
    ch = channel
    ev = RawEvaluator(ch)
    out: dict[str, Estimate] = {}
    for name in ("B0", "B1"):
        started = perf_counter()
        trace = formal(ch.t, ch.y) if name == "B0" else strategy_trace(ch.t, ch.y, "B1", FMAX)
        values = normalize(trace, ch.t, ch.fs)
        grid = ch.q//128
        candidate, accepted, rate = (np.asarray(values[key][grid], dtype=np.float64) for key in
                                      ("frequency_hz", "gated_frequency_hz", "chirp_hz_s"))
        raw = ev.evaluate(candidate, rate)
        out[name] = Estimate(ch.q, candidate, accepted, rate, raw, {})
        if timing is not None:
            timing[name] = perf_counter()-started
    started = perf_counter()
    b1 = out["B1"]
    out["B+S"] = Estimate(ch.q, b1.candidate_hz, np.where(b1.raw.S_256, b1.candidate_hz, np.nan),
                          b1.chirp_hz_s, b1.raw, {})
    if timing is not None:
        timing["B+S"] = perf_counter()-started
    return out


def verify_baselines(channel: Channel, results: dict[str, Estimate]) -> None:
    """Compare frequency, masks and native gates at every requested center."""
    archive = ROOT / "artifacts/TASK-020/data/centers" / f"{channel.id}.csv"
    with archive.open(encoding="utf-8", newline="") as stream:
        by_center = {int(row["sample_index"]): row for row in csv.DictReader(stream)}
    rows = [by_center[int(q)] for q in channel.q]
    np.testing.assert_array_equal(channel.primary, [row["primary"] == "True" for row in rows])
    for name, label in (("B0", "A"), ("B1", "B"), ("B+S", "BS")):
        result = results[name]
        comparisons = {f"{label}_output_hz": result.accepted_hz}
        if name != "B+S":
            comparisons[f"{label}_frequency_hz"] = result.candidate_hz
            np.testing.assert_array_equal(result.raw.S_256,
                                          [row[f"{label}_S"] == "True" for row in rows])
        for key, hz in comparisons.items():
            np.testing.assert_array_equal(hz, [float(row[key] or "nan") for row in rows],
                                          err_msg=f"{channel.id}: {key}")
