"""Rail-censored orthogonal matching pursuit on morphological residuals."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.fft import fft, next_fast_len  # type: ignore[import-untyped]

from scripts.research.task023.common import Channel, Estimate, RawEvaluator
from scripts.research.task023.waveform import (
    FMAX, FMIN, FLOOR, Bool, Float, Int, chirp_phase, complete, detrend,
    impulse_weights, offsets, project_steps, same_side_weights, samples_for_ns,
)


def rail_mask(y: Float) -> Bool:
    """Identify repeated flat hits at either acquisition extremum."""
    lo, hi = float(y.min()), float(y.max())
    tol = max((hi-lo)*1e-8, 1e-15)
    clipped = np.zeros(len(y), dtype=np.bool_)
    if hi-lo <= 2*tol:
        return clipped
    for at_rail in (y <= lo+tol, y >= hi-tol):
        count = np.count_nonzero(at_rail)
        if 4 <= count < .65*len(y) and np.count_nonzero(at_rail[1:] & at_rail[:-1]) >= 2:
            clipped |= at_rail
    return clipped


def _project(y: Float, w: Float, split: Int, degree: int) -> Float:
    """Weighted projection for frame, atom, sample arrays."""
    residual = detrend(y, w, degree)
    for point in np.unique(split[split >= 0]):
        own = split == point
        residual[own, ..., :point] = detrend(y[own, ..., :point], w[own, ..., :point], degree)
        residual[own, ..., point:] = detrend(y[own, ..., point:], w[own, ..., point:], degree)
    return residual


def joint_fit(y: Float, tau: Float, hz: Float, rate: Float, weights: Float,
              split: Int, degree: int = 1) -> tuple[Float, Float]:
    """Joint weighted real chirp fit with a polynomial nuisance on each flank."""
    phase = chirp_phase(tau, hz[..., None], rate[..., None])
    basis = np.concatenate((np.cos(phase), np.sin(phase)), axis=1)
    basis = _project(basis, weights[:, None, :], split, degree)
    raw = _project(y, weights, split, degree)
    weighted = basis * weights[:, None, :]
    gram = weighted @ basis.swapaxes(1, 2)
    rhs = weighted @ raw[..., None]
    # A rejected/duplicate atom can leave an exactly singular column. The
    # diagonal term stabilizes the normal equations at machine precision.
    ridge = np.maximum(np.max(abs(gram), axis=(1, 2)), 1.)*1e-10
    coeff = np.linalg.solve(gram + ridge[:, None, None]*np.eye(gram.shape[-1]), rhs)
    residual = raw - (basis.swapaxes(1, 2) @ coeff)[..., 0]
    return coeff[..., 0], residual


def _nominate(
    residual: Float, gate: Float, phase_factor: NDArray[np.complex64], rate: Float, nfft: int, df: float,
    band: Int, positive: Bool, previous: Float,
    *, fmax: float = FMAX,
) -> tuple[Float, Float]:
    """Select and refine a dechirped residual peak for each frame."""
    bank = fft((residual*gate).astype(np.float32)[:, None, :]*phase_factor, nfft, axis=-1)
    power = np.where(positive, abs(bank[..., band])**2, 0.).astype(np.float64)
    f = band*df
    if previous.shape[1]:
        clear = (abs(f[None, :, None]-previous[:, None, :]) >= 100e6).all(axis=2)
        power = np.where(clear[:, None, :], power, 0.)
    speed = np.argmax(power.reshape(len(power), -1), axis=1)
    ri, fi = np.divmod(speed, len(band))
    row = np.arange(len(power))
    inside = np.clip(fi, 1, len(band)-2)
    left, middle, right = (
        np.log(np.maximum(power[row, ri, inside+j], FLOOR)) for j in (-1, 0, 1)
    )
    denom = left - 2*middle + right
    delta = np.divide(.5*(left-right), denom, out=np.zeros_like(left),
                      where=(inside == fi) & (denom < -1e-8))
    hz = np.clip(f[fi] + np.clip(delta, -.5, .5)*df, FMIN, fmax)
    return hz, rate[ri]


def _harmonics(hz: Float, rate: Float, strong: Bool) -> Bool:
    ratio = hz[:, :, None] / hz[:, None, :]
    order = np.rint(ratio)
    fits = abs(hz[:, :, None] - order*hz[:, None, :]) <= np.maximum(45e6, .02*hz[:, :, None])
    follows = abs(rate[:, :, None] - order*rate[:, None, :]) <= 1.5e16
    return np.any((order >= 2.) & (order <= 6.) & fits & follows & strong[:, None, :], axis=-1)


@dataclass(frozen=True)
class PursuitFit:
    hz: Float
    rate: Float
    secondary_hz: Float
    secondary_rate: Float
    clipped: Bool
    censored: Bool
    harmonic: Bool


def _pursue(
    ch: Channel, duration: float, rail: Bool, impulse: Float, *,
    selected: Bool | None = None, atom_count: int = 3, secondary_gain: float = .075,
    reject_harmonics: bool = True,
) -> PursuitFit:
    width = samples_for_ns(duration, ch.fs)
    degree = 2 if duration >= 25.6 else 1
    ii = offsets(width)
    tau = ii/ch.fs
    rates = np.linspace(-4e16, 4e16, 9)
    phase_factor = np.exp(-1j*np.pi*rates[:, None]*tau**2).astype(np.complex64)
    nfft = next_fast_len(max(width, round(ch.fs/19.5e6)))
    df = ch.fs/nfft
    band = np.arange(int(np.ceil(FMIN/df)), int(np.floor(ch.fmax/df))+1, dtype=np.int64)
    positive = band[None, :]*df > abs(rates[:, None])*width/(2*ch.fs)
    taper = np.hanning(width)
    q = ch.q
    hz, rate, second, second_rate = (np.full(len(q), np.nan) for _ in range(4))
    clipped, censored, has_harmonic = (np.zeros(len(q), dtype=np.bool_) for _ in range(3))
    available = complete(q, len(ch.y), width)
    if selected is not None:
        available &= selected
    if duration >= 25.6:
        steps = ch.quiet.steps.index
        available &= (np.searchsorted(steps, q - width//2, side="right")
                      == np.searchsorted(steps, q + width//2, side="left"))
    frames = np.flatnonzero(available)
    for i in range(0, len(frames), 32):
        rows = frames[i:i+32]
        samples = q[rows, None]+ii
        y = ch.y[samples]
        # Morphological separation uses the low-pass flank contrast to find
        # steps, then a robust polynomial projection, then impulse rejection.
        morphological, split = project_steps(ch.y, q[rows], width, ch.quiet.steps, degree)
        impulse_gate = impulse[samples]
        w = impulse_gate * (~rail[samples])
        clipped[rows] = rail[samples].any(axis=1)
        w *= same_side_weights(q[rows], width, ch.quiet.steps, len(ch.y))
        left, right = w[:, :width//2].sum(axis=1), w[:, width//2:].sum(axis=1)
        usable = (w.sum(axis=1) >= .20*width) & (np.maximum(left, right) >= .12*width)
        censored[rows] = clipped[rows] & usable
        residual = _project(y, w, split, degree)
        # A Huber pass limits remaining trend leverage without classifying
        # sustained oscillation as an impulse. Rail weights stay identically zero.
        scale = np.maximum(np.median(abs(morphological), axis=1), ch.quiet.noise_power_v2**.5)
        robust = np.minimum(1., (6*scale[:, None])/np.maximum(abs(residual), FLOOR))
        w *= robust
        residual = _project(y, w, split, degree)
        rss0 = np.sum(w*residual**2, axis=1)
        atom_hz, atom_rate, gain = (np.empty((len(rows), atom_count)) for _ in range(3))
        prior_rss = rss0
        for m in range(atom_count):
            atom_hz[:, m], atom_rate[:, m] = _nominate(
                residual, w*taper, phase_factor, rates, nfft, df, band, positive, atom_hz[:, :m],
                fmax=ch.fmax,
            )
            _, residual = joint_fit(y, tau, atom_hz[:, :m+1], atom_rate[:, :m+1], w, split, degree)
            rss = np.sum(w*residual**2, axis=1)
            gain[:, m] = (prior_rss-rss)/np.maximum(rss0, FLOOR)
            prior_rss = rss
        strong = gain >= .075
        harmonic = _harmonics(atom_hz, atom_rate, strong)
        has_harmonic[rows] = (strong & harmonic).any(axis=1)
        # Rank independent components by their incremental explained voltage.
        keep = ~harmonic if reject_harmonics else np.ones_like(harmonic)
        rank = np.argsort(-np.where(keep, gain, -np.inf), axis=1, kind="stable")
        row = np.arange(len(rows))
        primary, runner_up = rank[:, 0], rank[:, 1]
        hz[rows] = np.where(usable, atom_hz[row, primary], np.nan)
        rate[rows] = np.where(usable, atom_rate[row, primary], np.nan)
        rival = (usable & strong[row, primary] & (gain[row, runner_up] >= secondary_gain)
                 & keep[row, runner_up])
        second[rows] = np.where(rival, atom_hz[row, runner_up], np.nan)
        second_rate[rows] = np.where(rival, atom_rate[row, runner_up], np.nan)
    return PursuitFit(hz, rate, second, second_rate, clipped, censored, has_harmonic)


def m2_mc_decomp(channel: Channel) -> Estimate:
    ch = channel
    ev = RawEvaluator(ch)
    rail = rail_mask(ch.y)
    impulse = impulse_weights(ch.y, ch.fs, ch.quiet.noise_power_v2**.5)
    q = ch.q
    frames = np.arange(len(q), dtype=np.int64)
    short = _pursue(ch, 12.8, rail, impulse)
    long = _pursue(ch, 25.6, rail, impulse)
    short_center = ev.matched(frames, short.hz, short.rate, 6.4)
    long_center = ev.matched(frames, long.hz, long.rate, 6.4)
    short_fit = ev.matched(frames, short.hz, short.rate, 12.8)
    long_fit = ev.matched(frames, long.hz, long.rate, 25.6)
    short_on_long = ev.matched(frames, short.hz, short.rate, 25.6)
    short_ok = (short_center.center_supported & (short_fit.snr_db >= 8.)
                & (short_fit.r2 >= .12) & (short_fit.half_snr_db >= 4.5)
                & (short_fit.rho >= .40))
    long_ok = (long_center.center_supported & (long_fit.snr_db >= 8.)
               & (long_fit.r2 >= .10) & (long_fit.half_snr_db >= 4.5) & (long_fit.rho >= .50))
    short_ok &= ev.low_frequency_supported(frames, short.hz, short.rate)
    long_ok &= ev.low_frequency_supported(frames, long.hz, long.rate)
    use_long = long_ok & (~short_ok | (long_fit.r2 > short_on_long.r2 + .005))
    hz = np.where(use_long, long.hz, short.hz)
    rate = np.where(use_long, long.rate, short.rate)
    scale = np.where(use_long, 25.6, 12.8)
    second = np.where(use_long, long.secondary_hz, short.secondary_hz)
    second_rate = np.where(use_long, long.secondary_rate, short.secondary_rate)
    second_center = ev.matched(frames, second, second_rate, 6.4)
    rival = second_center.center_supported & ev.low_frequency_supported(frames, second, second_rate)
    for duration in (12.8, 25.6):
        use = np.flatnonzero(rival & (scale == duration))
        fit = ev.matched(use, second[use], second_rate[use], duration)
        rival[use] &= ((fit.snr_db >= 8.) & (fit.half_snr_db >= 4.5)
                       & (fit.rho >= (.50 if duration >= 25.6 else .40)))

    raw = ev.evaluate(hz, rate)
    supported = ((raw.raw_chirp_r2_64ns >= .15)
                 | ((raw.raw_chirp_r2_256ns >= .12) & (raw.split_half_coherence_256ns >= .5)))
    accepted = np.where((short_ok | use_long) & supported, hz, np.nan)
    competing = rival & np.isfinite(accepted)
    return Estimate(q, hz, accepted, rate, raw, {
        "secondary_hz": np.where(competing, second, np.nan),
        "is_competing_multibranch": competing,
        "is_clipped_window": np.where(use_long, long.clipped, short.clipped),
        "rail_censored_fit": np.where(use_long, long.censored, short.censored),
        "has_harmonic": np.where(use_long, long.harmonic, short.harmonic),
        "selected_scale_ns": scale,
        "whitened_narrowband_snr_db": np.where(use_long, long_fit.snr_db, short_fit.snr_db),
        "center_narrowband_snr_db": np.where(use_long, long_center.snr_db, short_center.snr_db),
        "center_half_min_snr_db": np.where(
            use_long, long_center.half_snr_db, short_center.half_snr_db,
        ),
    })
