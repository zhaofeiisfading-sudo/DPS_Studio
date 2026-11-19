"""Whitened split-half chirp hypotheses and second-order path selection."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.fft import fft  # type: ignore[import-untyped]
from scipy.ndimage import maximum_filter  # type: ignore[import-untyped]

from ._evidence import Channel
from .waveform import (
    FLOOR, WINDOW_NS, Bool, Float, Int, complete, offsets, project_steps,
    same_side_weights, samples_for_ns,
)

RATES = np.linspace(-4e16, 4e16, 17)
PEAKS = 16
BATCH = 24
NULL_SCORE = 2.95


@dataclass(frozen=True)
class Hypotheses:
    hz: Float
    rate: Float
    score: Float
    rho: Float
    scale_ns: Float


def _scale_peaks(channel: Channel, duration: float, coherent: Float | None) -> Hypotheses:
    ch = channel
    width = samples_for_ns(duration, ch.fs)
    half = width//2
    sample = offsets(width)
    tau = sample/ch.fs
    nfft, k, frequency = ch.coherent_grid(width)
    bed = np.interp(frequency, ch.quiet.frequency_hz, ch.quiet.floor_v2)
    dechirp = np.exp(-1j*np.pi*RATES[:, None]*tau**2).astype(np.complex64)
    rotate = np.exp(2j*np.pi*k*half/nfft).astype(np.complex64)
    taper = np.hanning(half+2)[1:-1]
    shape = (len(ch.q), PEAKS)
    out = Hypotheses(np.full(shape, np.nan), np.full(shape, np.nan),
                     np.full(shape, -np.inf), np.full(shape, np.nan),
                     np.full(shape, duration))
    if not len(k):
        return out
    frames = np.flatnonzero(complete(ch.q, len(ch.y), width))
    min_rho = {6.4: .25, 12.8: .40, 25.6: .55, 38.4: .65}[duration]
    positive = frequency[None, :] > abs(RATES[:, None])*half/ch.fs
    for i in range(0, len(frames), BATCH):
        ch.check()
        idx = frames[i:i+BATCH]
        degree = 2 if duration >= 25.6 else 1
        residual, _ = project_steps(ch.y, ch.q[idx], width, ch.quiet.steps, degree)
        own = same_side_weights(ch.q[idx], width, ch.quiet.steps, len(ch.y))
        tapered = own * np.tile(taper, 2)
        x = (residual*tapered).astype(np.float32)
        size = np.sum(tapered.reshape(-1, 2, half)**2, axis=-1)
        zl = fft(x[:, None, :half]*dechirp[:, :half], nfft, axis=-1)[..., k]*rotate
        zr = fft(x[:, None, half:]*dechirp[:, half:], nfft, axis=-1)[..., k]
        # Compare half amplitudes after correcting for unequal taper masses.
        mass = np.maximum(tapered.reshape(-1, 2, half).sum(axis=-1), FLOOR)
        al = zl / mass[:, 0, None, None]
        ar = zr / mass[:, 1, None, None]
        cross = 2*np.real(al*ar.conj())
        rho = cross / (abs(al)**2 + abs(ar)**2 + FLOOR)
        # For whitened independent complex noise, the common-phase direction
        # has unit variance. Profile an added variance along that direction.
        inverse_size = 1./np.maximum(size, FLOOR)
        gain = mass*inverse_size
        coherent_power = abs(zl*gain[:, 0, None, None] + zr*gain[:, 1, None, None])**2
        noise = np.sum(mass*gain, axis=1)[:, None, None]*bed
        normalized = np.maximum(coherent_power / np.maximum(noise, FLOOR), 1.)
        log_likelihood = normalized - 1. - np.log(normalized)
        score = np.log1p(log_likelihood)
        enough = np.min(size, axis=1) >= .25*(taper @ taper)
        admissible = (rho >= min_rho) & enough[:, None, None] & positive
        if duration >= 12.8:
            half_power = np.minimum(abs(zl)**2*inverse_size[:, 0, None, None],
                                    abs(zr)**2*inverse_size[:, 1, None, None])
            admissible &= half_power >= 10**(.45)*bed
        if coherent is not None:
            # Capture the maximum whitened response over admissible chirp rates.
            power = np.max(np.where(admissible, normalized, 0.), axis=1)
            axis = ch.coherent_frequency
            if np.array_equal(axis, frequency):
                np.maximum(coherent[idx], power, out=power)
                coherent[idx] = power
            else:
                upper = np.clip(np.searchsorted(axis, frequency), 0, len(axis)-1)
                lower = np.maximum(upper-1, 0)
                nearest = np.where(frequency - axis[lower] <= axis[upper] - frequency,
                                   lower, upper)
                np.maximum.at(coherent, (idx[:, None], nearest), power)
        score = np.where(admissible, score, -np.inf)
        peaks = score == maximum_filter(score, size=(1, 3, 5), mode="nearest")
        surface = np.where(peaks, score, -np.inf).reshape(len(idx), -1)
        count = min(PEAKS, surface.shape[1])
        flat = np.argpartition(surface, -count, axis=-1)[:, -count:]
        rank, bin_ = np.divmod(flat, len(k))
        row = np.arange(len(idx))[:, None]
        selected = surface[row, flat]
        # Local interpolation of the cross-power peak at the selected rate.
        safe = np.clip(bin_, 1, max(1, len(k)-2))
        left, middle, right = (
            np.log(np.maximum(cross[row, rank, np.minimum(safe+j, len(k)-1)], FLOOR)) for j in (-1, 0, 1)
        )
        hessian = left - 2*middle + right
        delta = np.divide(.5*(left-right), hessian, out=np.zeros_like(left),
                          where=(len(k) >= 3) & (safe == bin_) & (hessian < -1e-8))
        hz = frequency[bin_] + np.clip(delta, -.5, .5)*(ch.fs/nfft)
        ok = np.isfinite(selected)
        out.score[idx, :count] = selected
        out.hz[idx, :count] = np.where(ok, np.clip(hz, ch.fmin, ch.fmax), np.nan)
        out.rho[idx, :count] = np.where(ok, rho[row, rank, bin_], np.nan)
        out.rate[idx, :count] = np.where(ok, RATES[rank], np.nan)
    return out


def hypotheses(channel: Channel, coherent: Float | None) -> Hypotheses:
    durations = WINDOW_NS
    banks = []
    for i, duration in enumerate(durations):
        channel.update(24 + 6*i, f"M4 相干候选 · {duration:g} ns")
        banks.append(_scale_peaks(channel, duration, coherent))
    hz = np.concatenate([bank.hz for bank in banks], axis=1)
    rate = np.concatenate([bank.rate for bank in banks], axis=1)
    score = np.concatenate([bank.score for bank in banks], axis=1)
    rho = np.concatenate([bank.rho for bank in banks], axis=1)
    scale = np.concatenate([bank.scale_ns for bank in banks], axis=1)
    order = np.argsort(-score, axis=1, kind="stable")
    # Suppress the same state appearing in several scales. Retain alternatives
    # at the same frequency when they describe different kinematics.
    kept = np.full((len(channel.q), PEAKS), -1, dtype=np.int64)
    for i, ranked in enumerate(order):
        if i % 32 == 0:
            channel.check()
        chosen: list[int] = []
        for j in ranked:
            if not np.isfinite(score[i, j]):
                break
            if any(abs(hz[i, j]-hz[i, m]) < 40e6 and abs(rate[i, j]-rate[i, m]) <= 5e15
                   for m in chosen):
                continue
            chosen.append(int(j))
            if len(chosen) == PEAKS:
                break
        kept[i, :len(chosen)] = chosen
    row = np.arange(len(channel.q))[:, None]
    return Hypotheses(*(np.where(kept >= 0, array[row, kept], fill) for array, fill in
                        ((hz, np.nan), (rate, np.nan), (score, -np.inf), (rho, np.nan),
                         (scale, np.nan))))


def off_threshold() -> float:
    """Fixed null extreme-value cutoff, checked on independent Gaussian records.

    Under the ideal exponential null this requires normalized power above 21.
    The split-half coherence gate further constrains the searched templates.
    """
    return NULL_SCORE


def kinematic_path(h: Hypotheses, time_s: Float, enabled: Bool,
                   threshold: float, *, entry_penalty: float = .35,
                   persistent_cw: Bool | None = None, jump_cost: float = 1.25,
                   check: Callable[[], None] = lambda: None) -> tuple[Int, Bool]:
    """Viterbi recurrence over dense proposals, an OFF state and JUMP edges."""
    n, count = h.hz.shape
    if not n:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.bool_)
    back = np.zeros((n, count+1), dtype=np.int64)
    jump = np.zeros((n, count+1), dtype=np.bool_)
    valid = enabled[:, None] & (h.score >= threshold)
    emit = np.where(valid, h.score-threshold+.20, -np.inf)
    value = np.r_[emit[0]-entry_penalty, 0.]
    transitions = np.zeros((count+1, count+1))
    transitions[-1, :-1] = -entry_penalty
    transitions[:-1, -1] = -.25
    for i in range(1, n):
        if i % 32 == 0:
            check()
        dt = time_s[i]-time_s[i-1]
        predicted = h.hz[i-1] + h.rate[i-1]*dt
        error = abs(h.hz[i][None, :]-predicted[:, None])
        curvature = abs(h.rate[i][None, :]-h.rate[i-1][:, None])
        cost = np.nan_to_num(.65*(error/65e6)**2 + .18*curvature/5e15, nan=np.inf)
        transitions[:-1, :-1] = -np.minimum(cost, jump_cost)
        if persistent_cw is not None:
            previous_cw, next_cw = persistent_cw[i-1], persistent_cw[i]
            # A continuous non-CW state takes priority over switching onto
            # a late recurrent line. A switch remains possible when it fades.
            continues = np.any(valid[i][None, :] & ~next_cw[None, :] & (cost < .90), axis=1)
            switching = (~previous_cw & continues)[:, None] & next_cw[None, :]
            transitions[:-1, :-1][switching] -= 2.0
        options = value[:, None] + transitions
        previous = np.argmax(options, axis=0)
        back[i] = previous
        jump[i, :-1] = ((previous[:-1] < count)
                        & (cost[np.minimum(previous[:-1], count-1), np.arange(count)] > jump_cost))
        value = options[previous, np.arange(count+1)] + np.r_[emit[i], 0.]
    path = np.full(n, count, dtype=np.int64)
    path[-1] = np.argmax(value)
    for i in range(n-1, 0, -1):
        path[i-1] = back[i, path[i]]
    return np.where(path < count, path, -1), jump[np.arange(n), path]
