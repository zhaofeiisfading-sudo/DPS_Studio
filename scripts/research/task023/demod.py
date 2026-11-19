"""Bidirectional real I-Q phase-state demodulation from verified anchors."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from scripts.research.task023.coherent import hypotheses, off_threshold
from scripts.research.task023.common import Channel, Estimate, RawEvaluator
from scripts.research.task023.waveform import (
    FMAX, FMIN, Bool, Float, Int, Quiet, chirp_phase, quadrature_stats, samples_for_ns,
)


@dataclass(frozen=True)
class Anchor:
    frame: int
    hz: float
    rate: float
    phase: float
    quality: float
    scale_ns: float


def _anchors(ch: Channel, ev: RawEvaluator) -> list[Anchor]:
    h = hypotheses(ch, (6.4, 25.6))
    threshold = off_threshold() + .70
    anchors: list[Anchor] = []
    # Test several spectral hypotheses so a bright spurious peak does not
    # suppress a coherent island at a neighboring frequency.
    for scale in (6.4, 25.6):
        frame, rank = np.nonzero(
            (h.score[:, :6] >= (off_threshold() if scale == 25.6 else threshold))
            & (h.scale_ns[:, :6] == scale)
        )
        hz, rate = h.hz[frame, rank], h.rate[frame, rank]
        short = ev.matched(frame, hz, rate, 6.4)
        fit = short if scale == 6.4 else ev.matched(frame, hz, rate, scale)
        strong = ((h.score[frame, rank] >= threshold) & (fit.r2 >= .40)
                  & (fit.rho >= .65) & (fit.half_snr_db >= 4.5))
        weak = ((scale == 25.6) & (fit.r2 >= .16) & (fit.rho >= .75)
                & (fit.snr_db >= 15.) & (fit.half_snr_db >= 8.))
        ok = (short.center_supported & (strong | weak)
              & ev.low_frequency_supported(frame, hz, rate))
        for i in np.flatnonzero(ok):
            anchors.append(Anchor(int(frame[i]), float(hz[i]), float(rate[i]),
                                  float(np.angle(fit.phasor[i])),
                                  float(h.score[frame[i], rank[i]] + fit.r2[i] + fit.rho[i]
                                        + 2.*strong[i]),
                                  scale))
    return sorted(anchors, key=lambda a: -a.quality)


@dataclass(frozen=True)
class PhaseState:
    sample: int
    phase: float
    hz: float
    rate: float
    integration_ns: float = 0.

    def predict(self, index: int, fs: float) -> PhaseState:
        dt = (index - self.sample)/fs
        hz = self.hz + self.rate*dt
        phase = self.phase + 2*np.pi*(self.hz*dt + .5*self.rate*dt**2)
        return PhaseState(index, float((phase+np.pi) % (2*np.pi)-np.pi), hz, self.rate)


@dataclass(frozen=True)
class Demodulator:
    y: Float
    fs: float
    steps: Int
    noise_v: float
    quiet: Quiet | None = None

    def update(self, state: PhaseState, index: int) -> PhaseState | None:
        dt = (index - state.sample)/self.fs
        predicted = state.predict(index, self.fs)
        hz, phase = predicted.hz, predicted.phase
        if not FMIN <= hz <= FMAX:
            return None
        order = np.searchsorted(self.steps, index, side="right")
        left = int(self.steps[order-1]) if order else 0
        right = int(self.steps[order]) if order < len(self.steps) else len(self.y)
        # State updates have a sub-ns cadence. Integration can be longer,
        # especially when fewer than 1.3 cycles fit in one update block.
        duration = min(6.4, max(.85, 1.3e9/hz))
        integrations = sorted({duration, min(6.4, 2*duration), 6.4, 12.8, 25.6, 38.4})
        bed = (self.noise_v**2 if self.quiet is None else
               float(np.interp(hz, self.quiet.frequency_hz, self.quiet.floor_v2)))
        for integration in integrations:
            width = samples_for_ns(integration, self.fs)
            lo, hi = max(left, index-width//2), min(right, index+width//2)
            if hi-lo < .70*width:
                continue
            tau = (np.arange(lo, hi, dtype=np.float64)-index)/self.fs
            phi = chirp_phase(tau, hz, state.rate) + phase
            degree = 2 if integration >= 25.6 else 1
            z, r2, power = quadrature_stats(self.y[lo:hi], phi, degree=degree)
            innovation = float(np.angle(z))
            # A large innovation on an observable block is a slip. Extending
            # the window is only a recovery for poor quadrature SNR.
            if r2 < .08 or power < 2*bed*10**.8:
                continue
            if abs(innovation) > 1.15:
                return None
            confidence = float(np.clip(r2, .15, .7))
            # PLL feedback with gains tapered for noisy, overlapping blocks.
            # A longer I-Q fit cannot resolve instantaneous innovation on the
            # microstep cadence. Reduce feedback when the measurements overlap.
            feedback_dt = float(np.copysign(max(abs(dt), .25e-9*integration), dt))
            hz_error = innovation/(2*np.pi*feedback_dt)
            hz += float(np.clip(.23*confidence*hz_error, -55e6, 55e6))
            rate = float(np.clip(state.rate+.025*confidence*hz_error/feedback_dt, -4e16, 4e16))
            if not FMIN <= hz <= FMAX:
                return None
            phase = float((phase+.65*confidence*innovation+np.pi) % (2*np.pi)-np.pi)
            return PhaseState(index, phase, hz, rate, integration)
        return None


def _propagate(
    ch: Channel, ev: RawEvaluator, demod: Demodulator, anchor: Anchor,
    hz: Float, rate: Float, lost: Bool,
    integrations: Float, predictions: Int, direction: int,
) -> None:
    state = PhaseState(int(ch.q[anchor.frame]), anchor.phase, anchor.hz, anchor.rate)
    micro = max(1, round(.8e-9*ch.fs))
    end = len(ch.q) if direction > 0 else -1
    fade = 0
    for frame in range(anchor.frame+direction, end, direction):
        if np.isfinite(hz[frame]):
            return
        center = int(ch.q[frame])
        # A detected voltage discontinuity terminates this lock in either direction.
        limits = np.searchsorted(demod.steps, (state.sample, center), side="right")
        if limits[0] != limits[1]:
            lost[frame] = True
            return
        max_integration, predicted_count = 0., 0
        for index in (*range(state.sample+direction*micro, center, direction*micro), center):
            updated = demod.update(state, index)
            if updated is None:
                fade += 1
                predicted = state.predict(index, ch.fs)
                if fade > 2 or not FMIN <= predicted.hz <= FMAX:
                    lost[frame] = True
                    return
                updated = predicted
                predicted_count += 1
            else:
                fade = 0
            state = updated
            max_integration = max(max_integration, state.integration_ns)
        row = np.array([frame], dtype=np.int64)
        frequency, slope = np.array([state.hz]), np.array([state.rate])
        short = ev.matched(row, frequency, slope, 6.4)
        if not short.center_supported[0] or not ev.low_frequency_supported(row, frequency, slope)[0]:
            lost[frame] = True
            return
        if short.r2[0] < .13:
            long = ev.matched(row, frequency, slope, 25.6)
            if not (long.r2[0] >= .10 and long.rho[0] >= .55 and long.snr_db[0] >= 8.
                    and long.half_snr_db[0] >= 4.5):
                lost[frame] = True
                return
        hz[frame], rate[frame] = state.hz, state.rate
        integrations[frame], predictions[frame] = max_integration, predicted_count


def m3_ss_demod(channel: Channel) -> Estimate:
    ch = channel
    ev = RawEvaluator(ch)
    hz, rate = np.full(len(ch.q), np.nan), np.full(len(ch.q), np.nan)
    seeded, lost = np.zeros(len(ch.q), dtype=np.bool_), np.zeros(len(ch.q), dtype=np.bool_)
    integrations = np.zeros(len(ch.q))
    predictions = np.zeros(len(ch.q), dtype=np.int64)
    demod = Demodulator(ch.y, ch.fs, ch.quiet.steps.index, ch.quiet.noise_power_v2**.5, ch.quiet)
    anchors = _anchors(ch, ev)
    for anchor in anchors:
        if np.isfinite(hz[anchor.frame]):
            continue
        hz[anchor.frame], rate[anchor.frame] = anchor.hz, anchor.rate
        integrations[anchor.frame] = anchor.scale_ns
        seeded[anchor.frame] = True
        lost[anchor.frame] = False
        for direction in (1, -1):
            _propagate(ch, ev, demod, anchor, hz, rate, lost, integrations, predictions, direction)
    raw = ev.evaluate(hz, rate)
    frames = np.arange(len(ch.q), dtype=np.int64)
    short = ev.matched(frames, hz, rate, 6.4)
    long = ev.matched(frames, hz, rate, 25.6)
    verified = (raw.raw_chirp_r2_64ns >= .13) | (
        (raw.raw_chirp_r2_256ns >= .10) & (raw.split_half_coherence_256ns >= .55)
        & (long.snr_db >= 8.) & (long.half_snr_db >= 4.5)
    )
    supported = short.center_supported
    supported[integrations == 25.6] &= long.half_snr_db[integrations == 25.6] >= 4.5
    for duration in (12.8, 38.4):
        rows = np.flatnonzero(supported & (integrations == duration))
        fit = ev.matched(rows, hz[rows], rate[rows], duration)
        supported[rows] &= fit.half_snr_db >= 4.5
    accepted = np.where(supported & verified, hz, np.nan)
    return Estimate(ch.q, hz, accepted, rate, raw, {
        "anchor": seeded,
        "loss_of_lock": lost & ~np.isfinite(accepted),
        "integration_ns": integrations,
        "predicted_microsteps": predictions,
        "center_narrowband_snr_db": short.snr_db,
        "center_half_min_snr_db": short.half_snr_db,
        "narrowband_snr_25_6ns_db": long.snr_db,
    })
