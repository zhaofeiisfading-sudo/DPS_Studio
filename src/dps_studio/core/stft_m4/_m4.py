"""Phase 2 raw-voltage verification and competing-path reconstruction."""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from functools import cached_property

import numpy as np

from ._coherent import Hypotheses, hypotheses, kinematic_path, off_threshold
from ._evidence import Channel, RawEvaluator
from .models import Estimate, MatchedEvidence, RejectionReason
from ._pursuit import _pursue
from .waveform import (
    FLOOR, Bool, Float, Int, Steps, chirp_phase, complete, detrend, impulse_weights,
    offsets, quadrature, same_side_weights, samples_for_ns,
)

CW_RATE_HZ_S = 3e15
CW_TOLERANCE_HZ = 25e6
CW_LATE_FRACTION = .30
SHORT_NS = 6.4
LONG_NS = 25.6
LONGEST_NS = 38.4
BACKGROUND_HZ = np.linspace(.30e9, 5.60e9, 107)
LOW_FLOOR_HZ = np.linspace(50e6, 250e6, 41)


def _tone_basis(sample_s: Float, hz: Float) -> Float:
    """Orthonormalize each pair of quadratures after quadratic detrending."""
    phase = chirp_phase(sample_s, hz[:, None], 0.)
    cosine = detrend(np.cos(phase), degree=2)
    cosine /= np.sqrt(np.maximum(np.sum(cosine**2, axis=1, keepdims=True), FLOOR))
    sine = detrend(np.sin(phase), degree=2)
    sine -= np.sum(sine*cosine, axis=1, keepdims=True)*cosine
    sine /= np.sqrt(np.maximum(np.sum(sine**2, axis=1, keepdims=True), FLOOR))
    return np.ascontiguousarray(np.concatenate((cosine, sine)).T)


class _VerificationNoise:
    """Phase 2B noise references on full, quadratically detrended windows."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel
        self._background_basis: dict[float, Float] = {}
        self._probe_hz = BACKGROUND_HZ[BACKGROUND_HZ <= .49*channel.fs]

    def quiet_floor(self, hz: Float) -> Float:
        quiet = self.channel.quiet
        return np.interp(hz, quiet.frequency_hz, quiet.floor_v2)

    @cached_property
    def _low_floor(self) -> Float:
        ch = self.channel
        width = samples_for_ns(LONGEST_NS, ch.fs)
        q = ch.quiet.quiet_centers
        crosses_step, _, _ = _edge_at(q, ch.quiet.steps.index, width//2)
        q = q[complete(q, len(ch.y), width) & ~crosses_step]
        if not len(q):
            return np.zeros_like(LOW_FLOOR_HZ)
        sample = offsets(width)
        residual = detrend(ch.y[q[:, None] + sample], degree=2)
        energy = np.sum(residual**2, axis=1)
        quiet = np.argsort(energy, kind="stable")[:max(1, len(q)//2)]
        projection = residual[quiet] @ _tone_basis(sample/ch.fs, LOW_FLOOR_HZ)
        c, s = np.split(projection, 2, axis=1)
        # Each fit has two quadratures, so divide the exponential mean by two.
        return np.asarray(np.median(c**2 + s**2, axis=0) / (2*np.log(2.)))

    def low_frequency_loss(self, hz: Float) -> Float:
        loss = np.zeros_like(hz)
        low = hz < 250e6
        if low.any():
            floor = self.quiet_floor(hz[low])
            empirical = np.interp(hz[low], LOW_FLOOR_HZ, self._low_floor)
            loss[low] = 10*np.log10(np.maximum(floor, empirical) / floor)
        return loss

    def background_loss(self, frames: Int, hz: Float, duration_ns: float) -> Float:
        """Estimate the local noise bed with a 250 MHz guard around each fit."""
        if not len(frames):
            return np.empty(0)
        if len(self._probe_hz) < 2:
            return np.zeros(len(frames))
        ch = self.channel
        width = samples_for_ns(duration_ns, ch.fs)
        sample = offsets(width)
        if duration_ns not in self._background_basis:
            self._background_basis[duration_ns] = _tone_basis(sample/ch.fs, self._probe_hz)
        basis = self._background_basis[duration_ns]
        q, inverse = np.unique(ch.q[frames], return_inverse=True)
        normalized = np.empty((len(q), len(self._probe_hz)))
        probe_floor = self.quiet_floor(self._probe_hz)
        for start in range(0, len(q), 128):
            ch.check()
            batch = q[start:start+128]
            residual = detrend(ch.y[batch[:, None] + sample], degree=2)
            c, s = np.split(residual @ basis, 2, axis=1)
            normalized[start:start+len(batch)] = (c**2 + s**2) / probe_floor
        guarded = abs(self._probe_hz - hz[:, None]) >= 250e6
        # Scaling each probe by the candidate's quiet floor and dividing by the
        # reference bed cancels that floor, leaving the factor of two here.
        ranked = np.sort(np.where(guarded, normalized[inverse], np.inf), axis=1)
        enough = guarded.sum(axis=1) >= 2
        rank = .35*(guarded[enough].sum(axis=1) - 1)
        lower = rank.astype(np.int64)
        row = np.flatnonzero(enough)
        left, right = ranked[row, lower], ranked[row, lower+1]
        p35 = left + (rank - lower)*(right - left)
        relative_bed = np.maximum(1., p35 / (-2*np.log(.65)))
        result = np.zeros(len(hz))
        result[row] = 10*np.log10(relative_bed)
        return result


def _runs(mask: Bool) -> tuple[Int, Int]:
    changes = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return changes[::2], changes[1::2]


def _support_edges(ch: Channel, rail: Bool) -> tuple[Steps, Int]:
    """Include the first rail exit after a quiet interval as a support boundary."""
    starts, stops = _runs(rail)
    gap = starts - np.r_[-len(ch.y), stops][:len(starts)]
    minimum = round(.15e-9 * ch.fs)
    first_exit = stops[(stops - starts >= minimum) & (gap >= round(12.8e-9 * ch.fs))]
    first_exit = first_exit[first_exit < len(ch.y)]
    measured = ch.quiet.steps
    if len(measured.index) and len(first_exit):
        close = abs(first_exit[:, None] - measured.index[None, :]) < round(1e-9 * ch.fs)
        first_exit = first_exit[~close.any(axis=1)]
    index = np.r_[measured.index, first_exit]
    strength = np.r_[measured.strength_v, np.zeros(len(first_exit))]
    order = np.argsort(index)
    return Steps(index[order], strength[order]), first_exit


def _edge_at(q: Int, index: Int, half: int) -> tuple[Bool, Bool, Int]:
    boundaries = np.r_[np.iinfo(np.int64).min // 2, index, np.iinfo(np.int64).max // 2]
    order = np.searchsorted(index, q, side="right")
    before, after = boundaries[order], boundaries[order+1]
    nearest = np.where(q - before <= after - q, before, after)
    return abs(q - nearest) < half, q >= nearest, nearest


def _score(snr_db: Float) -> Float:
    power = np.maximum(10**(snr_db / 10), 1.)
    return np.log1p(power - 1. - np.log(power))


def _propose(ch: Channel, ev: RawEvaluator, rail: Bool, near: Bool,
             coherent: Float | None) -> tuple[Hypotheses, Bool]:
    bank = hypotheses(ch, coherent)
    rows = np.arange(len(ch.q), dtype=np.int64)
    impulse = impulse_weights(ch.y, ch.fs, ch.quiet.noise_power_v2**.5)
    active = bank.score[:, 0] >= off_threshold()
    hz, rate, score, rho, scale = ([column] for column in (
        bank.hz, bank.rate, bank.score, bank.rho, bank.scale_ns,
    ))
    residual = [np.zeros_like(bank.hz, dtype=np.bool_)]
    for duration, selected in ((6.4, near), (12.8, active), (25.6, active)):
        ch.update({6.4: 48, 12.8: 51, 25.6: 54}[duration], f"M4 残差候选 · {duration:g} ns")
        fit = _pursue(ch, duration, rail, impulse, selected=selected,
                      atom_count=2, secondary_gain=.025, reject_harmonics=False)
        for atom, (frequency, chirp) in enumerate(((fit.hz, fit.rate),
                                                   (fit.secondary_hz, fit.secondary_rate))):
            matched = ev.matched(rows, frequency, chirp, duration)
            hz.append(frequency[:, None])
            rate.append(chirp[:, None])
            score.append(_score(matched.snr_db)[:, None])
            rho.append(matched.rho[:, None])
            scale.append(np.full((len(rows), 1), duration))
            residual.append(np.full((len(rows), 1), atom == 1, dtype=np.bool_))
    return Hypotheses(*(np.concatenate(x, axis=1) for x in (hz, rate, score, rho, scale))), (
        np.concatenate(residual, axis=1)
    )


def _raw_r2(ch: Channel, frame: Int, hz: Float, rate: Float, duration: float) -> Float:
    width = samples_for_ns(duration, ch.fs)
    result = np.full(len(frame), np.nan)
    valid = np.flatnonzero(complete(ch.q[frame], len(ch.y), width))
    sample = offsets(width)
    for start in range(0, len(valid), 128):
        ch.check()
        use = valid[start:start+128]
        phase = chirp_phase(sample/ch.fs, hz[use, None], rate[use, None])
        _, result[use] = quadrature(ch.y[ch.q[frame[use], None] + sample], phase,
                                    degree=2 if duration >= LONG_NS else 1)
    return result


def _short_cycles(ch: Channel, hz: Float, rate: Float, width: int) -> tuple[Float, Bool]:
    start, stop = -width/2/ch.fs, width/2/ch.fs
    cycles = hz*(stop - start) + .5*rate*(stop**2 - start**2)
    return cycles, (hz + rate*start > 0.) & (hz + rate*stop > 0.)


def _step_cycles(
    ch: Channel, q: Int, hz: Float, rate: Float, width: int, edges: Steps, usable: Bool,
) -> Float:
    sample = offsets(width)
    indices = q[:, None] + sample
    valid = (indices >= 0) & (indices < len(ch.y))
    w = same_side_weights(q, width, edges, len(ch.y))
    kept = valid & usable[np.clip(indices, 0, len(ch.y)-1)] & (w > 0.)
    # Integrate instantaneous frequency over the usable sample cells.
    frequency = hz[:, None] + rate[:, None]*(sample + .5)/ch.fs
    return np.sum(np.where(kept, frequency, 0.), axis=1)/ch.fs


def _long_supported(
    fit: MatchedEvidence, raw_r2: Float, cycles: Float, positive: Bool, loss_db: Float,
) -> Bool:
    return (positive & (cycles >= 1.5) & (raw_r2 >= .04)
            & (fit.snr_db - loss_db >= 11.5) & (fit.half_snr_db - loss_db >= 5.)
            & (fit.rho >= .58))


@dataclass(frozen=True)
class Verification:
    valid: Bool
    short_r2: Float
    duration_ns: Float
    snr_full_db: Float
    snr_L_db: Float
    snr_R_db: Float
    rho: Float
    cycles: Float
    post_step_r2: Float
    lowfreq_failed: Bool


def _verify(
    ch: Channel, ev: RawEvaluator, h: Hypotheses, frame: Int, col: Int,
    edges: Steps, rail: Bool, noise: _VerificationNoise, *, initial: bool = False,
) -> Verification:
    hz, rate = h.hz[frame, col], h.rate[frame, col]
    score = h.score[frame, col]
    low_loss = noise.low_frequency_loss(hz)
    width = samples_for_ns(SHORT_NS, ch.fs)
    near, post, _ = _edge_at(ch.q[frame], edges.index, width//2)
    short = ev.matched(frame, hz, rate, SHORT_NS, progress=(58, 64) if initial else None)
    short_r2 = short.r2.copy()
    dc_short, _, _ = _edge_at(ch.q[frame], ch.quiet.steps.index, width//2)
    use = np.flatnonzero(dc_short)
    if len(use):
        short_r2[use] = _raw_r2(ch, frame[use], hz[use], rate[use], SHORT_NS)
    cycles, positive = _short_cycles(ch, hz, rate, width)
    short_fit = (positive & (short_r2 >= .15) & (short.snr_db - low_loss >= 9.)
                 & (short.half_snr_db - low_loss >= 3.) & (short.rho >= .25)
                 & (score >= off_threshold()))
    short_anchor = short_fit & (cycles >= 1.)
    valid = short_anchor & (hz >= 250e6)
    duration = np.full(len(frame), SHORT_NS)
    full, left, right = (value - low_loss for value in
                         (short.snr_db, short.snr_left_db, short.snr_right_db))
    rho = short.rho.copy()
    selected_cycles = cycles.copy()
    # Use the shortest verification support that passes, then the longer bank.
    pending = np.flatnonzero(~valid & ~near)
    for duration_ns in (LONG_NS, LONGEST_NS):
        if not len(pending):
            break
        f, hertz, chirps = frame[pending], hz[pending], rate[pending]
        progress = None
        if initial:
            a, b = (65, 69) if duration_ns == LONG_NS else (70, 73)
            ch.update(a, f"M4 原波形门控 · {duration_ns:g} ns")
            progress = (a, b)
        longer = ev.matched(f, hertz, chirps, duration_ns, progress=progress)
        long_width = samples_for_ns(duration_ns, ch.fs)
        long_r2 = longer.r2.copy()
        dc_long, _, _ = _edge_at(ch.q[f], ch.quiet.steps.index, long_width//2)
        use = np.flatnonzero(dc_long)
        if len(use):
            long_r2[use] = _raw_r2(ch, f[use], hertz[use], chirps[use], duration_ns)
        count, positive_long = _short_cycles(ch, hertz, chirps, long_width)
        loss = low_loss[pending]
        # The nonnegative CA-CFAR penalty can only remove candidates that
        # already meet the long gate. Share probe powers across candidates.
        eligible = _long_supported(longer, long_r2, count, positive_long, loss)
        recheck = eligible & ~short_fit[pending]
        loss[recheck] = np.maximum(
            loss[recheck], noise.background_loss(f[recheck], hertz[recheck], duration_ns),
        )
        ok = _long_supported(longer, long_r2, count, positive_long, loss)
        use = pending[ok]
        duration[use], selected_cycles[use] = duration_ns, count[ok]
        full[use], left[use], right[use], rho[use] = (
            longer.snr_db[ok] - loss[ok], longer.snr_left_db[ok] - loss[ok],
            longer.snr_right_db[ok] - loss[ok], longer.rho[ok],
        )
        valid[use] = True
        if duration_ns == LONG_NS:
            pending = pending[~ok & ((long_r2 >= .04) | (score[pending] >= off_threshold()))]
    # A subcycle short fit can inflate amplitude when it follows curvature.
    # Require sustained two-sided oscillation in the 38.4 ns raw voltage.
    if initial:
        ch.update(74, "M4 持续低频与边界验证")
    low = np.flatnonzero(valid & (hz < 250e6))
    low_fit = ev.matched(frame[low], hz[low], rate[low], LONGEST_NS)
    min_r2 = np.where((hz[low] < 200e6) & ~short_anchor[low], .15, .10)
    _, low_positive = _short_cycles(ch, hz[low], rate[low], samples_for_ns(LONGEST_NS, ch.fs))
    sustained = (low_positive & (abs(short.phasor[low]) <= 3.*abs(low_fit.phasor))
                   & (low_fit.r2 >= min_r2) & (low_fit.rho >= .55)
                   & (low_fit.snr_db - low_loss[low] >= 8.)
                   & (low_fit.half_snr_db - low_loss[low] >= 4.5))
    lowfreq_failed = np.zeros(len(frame), dtype=np.bool_)
    lowfreq_failed[low] = ~sustained
    valid[low] &= sustained
    # Permit a <1-cycle short continuation only adjacent to a verified
    # multi-cycle state, with a compatible predicted frequency.
    for i in np.flatnonzero(short_fit & ~valid & ~near & (cycles >= .8) & (cycles < 1.)):
        adjacent = np.flatnonzero(valid & ~near & (selected_cycles >= 1.5)
                                  & (abs(frame-frame[i]) == 1))
        dt = (ch.q[frame[i]] - ch.q[frame[adjacent]])/ch.fs
        valid[i] = np.any(abs(hz[i] - hz[adjacent] - rate[adjacent]*dt) < 60e6)
    post_r2 = np.full(len(frame), np.nan)
    use = np.flatnonzero(near)
    step = ev.matched(frame[use], hz[use], rate[use], SHORT_NS, steps=edges, usable_samples=~rail)
    usable_cycles = _step_cycles(ch, ch.q[frame[use]], hz[use], rate[use], width, edges, ~rail)
    post_r2[use] = np.where(post[use], step.r2, np.nan)
    valid[use] = (post[use] & positive[use] & (step.r2 >= .25)
                  & (step.snr_db >= 10.) & (usable_cycles >= 1.))
    duration[use], selected_cycles[use] = SHORT_NS, usable_cycles
    full[use], left[use], right[use], rho[use] = (
        step.snr_db, step.snr_left_db, step.snr_right_db, step.rho,
    )
    return Verification(valid, short_r2, duration, full, left, right, rho, selected_cycles, post_r2,
                        lowfreq_failed)


def _persistent_cw(h: Hypotheses, valid: Bool, *, fmin: float, fmax: float) -> tuple[Bool, Float]:
    """Find narrow near-zero-rate lines recurring across the final 30% of the trace."""
    tail = max(1, int(np.ceil(CW_LATE_FRACTION*len(h.hz))))
    flat = valid & (abs(h.rate) <= CW_RATE_HZ_S)
    tail_score = np.where(valid[-tail:], h.score[-tail:], -np.inf)
    best_rank = np.argmax(tail_score, axis=1)
    last = np.arange(len(tail_score))
    tail_hz = h.hz[-tail:][last, best_rank]
    remaining = flat[-tail:][last, best_rank]
    lines: list[float] = []
    # Search a physical-frequency neighborhood and count frames, even when
    # several templates for the same line are present in one frame.
    grid = np.arange(fmin, fmax + 10e6, 10e6)
    while remaining.any():
        counts = np.array([np.count_nonzero(remaining & (
            abs(tail_hz - center) <= CW_TOLERANCE_HZ)) for center in grid])
        best = int(np.argmax(counts))
        if counts[best] < max(4, np.ceil(CW_LATE_FRACTION * tail)):
            break
        close = abs(tail_hz - grid[best]) <= CW_TOLERANCE_HZ
        lines.append(float(np.median(tail_hz[close & remaining])))
        remaining &= abs(tail_hz - lines[-1]) > 2*CW_TOLERANCE_HZ
    near = np.zeros_like(valid)
    for hz in lines:
        near |= (abs(h.hz - hz) <= CW_TOLERANCE_HZ) & (abs(h.rate) <= CW_RATE_HZ_S)
    return near & valid, np.array(lines, dtype=np.float64)


def _isolated(
    valid: Bool, score: Float, r2: Float, duration: Float, hz: Float, rate: Float, dt: float,
) -> Bool:
    removed = np.zeros_like(valid)
    starts, stops = _runs(valid)
    previous_off = starts - np.r_[-3, stops][:len(starts)]
    next_off = np.r_[starts, len(valid)+3][1:] - stops
    isolated = (stops - starts <= 2) & (previous_off >= 3) & (next_off >= 3)
    for start, stop in zip(starts[isolated], stops[isolated], strict=True):
        if not ((score[start:stop] >= 4.5) & (r2[start:stop] >= .30)).any():
            removed[start:stop] = True
    # Adjacent long windows overlap heavily. A narrowband-only branch
    # needs a short-window anchor or a full 25.6 ns of recurring evidence.
    # Small gaps can connect a branch but remain unpublished.
    rows = np.flatnonzero(valid & ~removed)
    steps = np.diff(rows)
    gap_time = steps*dt
    departure = hz[rows[1:]] - hz[rows[:-1]] - rate[rows[:-1]]*gap_time
    joins = (abs(departure) <= 60e6) & (gap_time <= 9.6e-9 + 1e-15)
    for branch in np.split(rows, np.flatnonzero(~joins)+1):
        anchored = np.any((duration[branch] == SHORT_NS)
                          & (score[branch] >= 4.5) & (r2[branch] >= .24))
        if len(branch)*dt < 25.6e-9 - 1e-15 and not anchored:
            removed[branch] = True
    return removed


def _select(ch: Channel, h: Hypotheses, valid: Bool) -> tuple[Int, Bool, Bool]:
    null = off_threshold()
    cw, lines = _persistent_cw(h, valid, fmin=ch.fmin, fmax=ch.fmax)
    score = np.where(valid, np.maximum(h.score, null), -np.inf)
    if len(lines):
        moving = valid & ~cw
        cw_neighborhood = np.zeros_like(cw)
        for hz in lines:
            moving &= abs(h.hz - hz) >= 100e6
            cw_neighborhood |= abs(h.hz - hz) <= 65e6
        # Clipping harmonics can pass the raw-voltage gate and share a frame
        # with a fundamental inside the CW neighborhood.
        cand_hz = np.where(valid, h.hz, np.nan)
        cand_score = np.where(valid, score, -np.inf)
        is_harmonic = np.zeros_like(moving)
        tol = np.minimum(120e6, 0.06 * h.hz[:, :, None] + 35e6)
        for k in range(2, 9):
            ch.check()
            harmonic_diff = np.abs(h.hz[:, :, None] - k * cand_hz[:, None, :])
            compatible = (harmonic_diff <= tol) & (cand_score[:, None, :] >= score[:, :, None] - 2.0)
            is_harmonic |= np.any(compatible, axis=2)
        moving &= ~is_harmonic
        rival_score = np.max(np.where(moving, score, -np.inf), axis=1)
        has_rival = np.isfinite(rival_score)
        limit = np.maximum(rival_score - .55, null)
        score = np.where(cw_neighborhood & has_rival[:, None],
                         np.minimum(score, limit[:, None]), score)
    path, jump = kinematic_path(replace(h, score=score), ch.t[ch.q],
                                np.ones(len(ch.q), dtype=np.bool_), null,
                                entry_penalty=.95, persistent_cw=cw, jump_cost=3.0, check=ch.check)
    return path, jump, cw


def _path_values(
    h: Hypotheses, path: Int, frame: Int, col: Int, fit: Verification,
) -> tuple[Int, Int, Float, Float, Float, Float]:
    row = np.arange(len(path))
    best = np.argmax(np.where(np.isfinite(h.score), h.score, -np.inf), axis=1)
    rank = np.where(path >= 0, path, best)
    index = np.full(h.hz.shape, len(frame), dtype=np.int64)
    index[frame, col] = np.arange(len(frame))
    selected = index[row, rank]
    return (
        rank, selected, h.hz[row, rank], h.rate[row, rank],
        np.concatenate((fit.short_r2, [np.nan]))[selected],
        np.concatenate((fit.duration_ns, [np.nan]))[selected],
    )


def _around_gaps(ch: Channel, h: Hypotheses, path: Int, near: Bool) -> Hypotheses:
    """Nominate bounded frequency/rate offsets from nearby verified states."""
    observed = np.flatnonzero(path >= 0)
    shape = (len(path), 18)
    hz, rate, scale = (np.full(shape, np.nan) for _ in range(3))
    score = np.full(shape, -np.inf)
    if not len(observed):
        return Hypotheses(hz, rate, score, np.full(shape, np.nan), scale)
    missing = np.flatnonzero((path < 0) & ~near)
    insertion = np.searchsorted(observed, missing)
    for side in (0, 1):
        proximal = observed[np.clip(insertion-side, 0, len(observed)-1)]
        dt = (ch.q[missing] - ch.q[proximal])/ch.fs
        keep = abs(dt) <= 6.4e-9 + 1e-15
        rows, origin = missing[keep], proximal[keep]
        cols = path[origin]
        candidate_sz = slice(side*9, (side+1)*9)
        origin_rate = h.rate[origin, cols]
        predicted = h.hz[origin, cols] + origin_rate*dt[keep]
        hz[rows, candidate_sz] = predicted[:, None] + np.tile([-10e6, 0., 10e6], 3)
        rate[rows, candidate_sz] = origin_rate[:, None] + np.repeat([-2.5e15, 0., 2.5e15], 3)
        # The phase match at the new center determines the emission score.
        score[rows, candidate_sz] = off_threshold()
        scale[rows, candidate_sz] = LONG_NS
    index = (hz >= ch.fmin) & (hz <= ch.fmax)
    return Hypotheses(hz, rate, np.where(index, score, -np.inf), np.full(shape, np.nan), scale)


def track_m4(ch: Channel, ev: RawEvaluator, rail: Bool, edges: Steps,
             rail_exit: Int, coherent: Float | None) -> Estimate:
    """Track verified narrowband states with label-free step and CW evidence."""
    noise = _VerificationNoise(ch)
    near, post, _ = _edge_at(ch.q, edges.index, samples_for_ns(SHORT_NS, ch.fs)//2)
    h, residual = _propose(ch, ev, rail, near, coherent)
    null = off_threshold()
    frame, col = np.nonzero(np.isfinite(h.score) & (h.score >= null - .75))
    ch.update(58, "M4 原波形门控")
    fit = _verify(ch, ev, h, frame, col, edges, rail, noise, initial=True)
    valid = np.zeros_like(h.hz, dtype=np.bool_)
    valid[frame, col] = fit.valid
    path, jump, cw = _select(ch, h, valid)
    row = np.arange(len(path))
    rank, chosen, hz, rate, short_r2, duration = _path_values(h, path, frame, col, fit)
    island = _isolated(path >= 0, h.score[row, rank], short_r2, duration, hz, rate, 128/ch.fs)
    # A rejected short island cannot seed neighboring frames and manufacture
    # the persistence that it lacked on the initial path.
    seed_path = np.where(island, -1, path)
    ch.update(80, "M4 缺口复验")
    search = _around_gaps(ch, h, seed_path, near)
    rows, ranks = np.nonzero(np.isfinite(search.score))
    added = _verify(ch, ev, search, rows, ranks, edges, rail, noise)
    if added.valid.any():
        # Refined hypotheses still pass the same untouched original-voltage
        # thresholds. Re-run the path with those measured alternatives.
        added_valid = np.zeros_like(search.hz, dtype=np.bool_)
        added_valid[rows, ranks] = added.valid
        search.score[rows, ranks] = np.where(added.valid, _score(added.snr_full_db), -np.inf)
        residual = np.concatenate((residual, np.zeros_like(added_valid)), axis=1)
        valid = np.concatenate((valid, added_valid), axis=1)
        col = np.concatenate((col, h.hz.shape[1] + ranks))
        frame = np.concatenate((frame, rows))
        h = Hypotheses(*(np.concatenate((getattr(h, f.name), getattr(search, f.name)), axis=1)
                         for f in fields(Hypotheses)))
        fit = Verification(*(
            np.concatenate((getattr(fit, f.name), getattr(added, f.name)))
            for f in fields(Verification)
        ))
        path, jump, cw = _select(ch, h, valid)
        rank, chosen, hz, rate, short_r2, duration = _path_values(h, path, frame, col, fit)
        island = _isolated(path >= 0, h.score[row, rank], short_r2, duration, hz, rate, 128/ch.fs)

    def read(values: Float) -> Float:
        return np.concatenate((values, [np.nan]))[chosen]

    accepted = (path >= 0) & ~island
    secondary = valid & (abs(h.hz - hz[:, None]) >= 100e6)
    # Secondary publication requires explicit orthogonal nomination or an
    # independently recurring CW line. Near-step alternatives are ambiguous.
    secondary &= (residual | cw) & ~near[:, None] & accepted[:, None]
    competing_cw = (secondary & cw).any(axis=1)
    preferred = secondary & (cw | ~competing_cw[:, None])
    rival = np.argmax(np.where(preferred, h.score, -np.inf), axis=1)
    half = samples_for_ns(SHORT_NS, ch.fs)//2
    samples = ch.q[:, None] + offsets(2*half)
    rail_clipped = rail[np.clip(samples, 0, max(0, len(rail)-1))].any(axis=1)
    rail_edge, _, _ = _edge_at(ch.q, rail_exit, half)
    dc_edge, _, _ = _edge_at(ch.q, ch.quiet.steps.index, half)
    ch.update(88, "汇总 M4 原波形证据")
    raw = ev.evaluate(hz, rate)
    proposed = np.bincount(frame, minlength=len(path)) > 0
    suppressed_low = np.bincount(frame[fit.lowfreq_failed], minlength=len(path)) > 0
    verified = valid.any(axis=1)
    reason = np.full(len(path), RejectionReason.NO_PROPOSAL.value, dtype="U48")
    reason[proposed] = RejectionReason.RAW_GATE.value
    reason[suppressed_low & proposed] = RejectionReason.LOW_FREQ.value
    reason[verified] = RejectionReason.PATH_OFF.value
    reason[near & ~post] = RejectionReason.PRE_EDGE.value
    reason[island] = RejectionReason.ISLAND.value
    reason[accepted] = RejectionReason.ACCEPTED.value
    reasons = tuple(RejectionReason(value) for value in reason)
    return Estimate(ch.q, hz, np.where(accepted, hz, np.nan), rate, raw, {
        "whitened_score": h.score[row, rank],
        "selected_scale_ns": h.scale_ns[row, rank],
        "verification_window_ns": read(fit.duration_ns),
        "snr_full_db": read(fit.snr_full_db),
        "snr_L_db": read(fit.snr_L_db),
        "snr_R_db": read(fit.snr_R_db),
        "split_half_coherence": read(fit.rho),
        "verification_cycles": read(fit.cycles),
        "post_step_r2": read(fit.post_step_r2),
        "near_support_edge": near,
        "post_support_edge": near & post,
        "detected_dc_step": dc_edge,
        "rail_entry_edge": rail_edge,
        "rail_clipped": rail_clipped,
        "path_off": ~accepted,
        "path_jump": accepted & jump,
        "island_removed": island,
        "verified_hypothesis_count": valid.sum(axis=1, dtype=np.int64),
        "residual_nomination": residual[row, rank],
        "secondary_hz": np.where(secondary.any(axis=1), h.hz[row, rival], np.nan),
        "competing_cw_present": competing_cw,
        "persistent_cw_overlap": accepted & cw[row, rank],
    }, tuple(item.value for item in reasons), reasons)
