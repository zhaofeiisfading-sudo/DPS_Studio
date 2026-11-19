"""Time-domain projections and empirical quiet-voltage statistics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import percentile_filter, uniform_filter1d  # type: ignore[import-untyped]
from scipy.signal import find_peaks  # type: ignore[import-untyped]

Float: TypeAlias = NDArray[np.float64]
Int: TypeAlias = NDArray[np.int64]
Bool: TypeAlias = NDArray[np.bool_]
Complex: TypeAlias = NDArray[np.complex128]

FMIN, FMAX = 50e6, 6e9
FLOOR = 1e-30
WINDOW_NS = (6.4, 12.8, 25.6, 38.4)


def samples_for_ns(duration_ns: float, fs: float) -> int:
    """Nearest even number of samples for the requested physical duration."""
    return max(2, 2 * round(duration_ns * 1e-9 * fs / 2))


def centers(n: int) -> Int:
    return np.arange(384, n - 383, 128, dtype=np.int64)


def offsets(width: int) -> Int:
    return np.arange(-width // 2, width // 2, dtype=np.int64)


def complete(q: Int, n: int, width: int) -> Bool:
    return (q >= width // 2) & (q + width // 2 <= n)


def detrend(y: Float, weights: Float | None = None, degree: int = 1) -> Float:
    """Project each row off a linear or quadratic baseline on the sample grid."""
    t = np.linspace(-1., 1., y.shape[-1])
    if weights is None:
        residual = y - y.mean(axis=-1, keepdims=True) - (
            (y @ t)[..., None] * (t / (t @ t))
        )
        if degree == 2:
            v = t**2 - np.mean(t**2)
            residual -= (y @ v)[..., None] * (v / max(float(v @ v), FLOOR))
        return residual
    mass = np.maximum(weights.sum(axis=-1, keepdims=True), FLOOR)
    u = t - (weights @ t)[..., None] / mass
    variance = np.maximum(np.sum(weights * u**2, axis=-1, keepdims=True), FLOOR)
    slope = np.sum(weights * u * y, axis=-1, keepdims=True) / variance
    residual = y - np.sum(weights * y, axis=-1, keepdims=True) / mass - slope * u
    if degree == 2:
        square = u**2
        v = (square - np.sum(weights * square, axis=-1, keepdims=True) / mass
             - u * np.sum(weights * u * square, axis=-1, keepdims=True) / variance)
        curvature = np.sum(weights * v * residual, axis=-1, keepdims=True) / np.maximum(
            np.sum(weights * v**2, axis=-1, keepdims=True), FLOOR
        )
        residual -= curvature * v
    return residual


def quadrature_stats(
    y: Float, phase: Float, weights: Float | None = None, degree: int = 1,
) -> tuple[Complex, Float, Float]:
    """Return the real chirp fit's phasor, explained fraction and explained energy.

    Data and both quadratures are projected off the same polynomial.
    The phasor is a - ib for a*cos(phase) + b*sin(phase).
    """
    c = detrend(np.cos(phase), weights, degree)
    s = detrend(np.sin(phase), weights, degree)
    v = detrend(y, weights, degree)
    w = 1. if weights is None else weights
    cc, ss, cs = (np.sum(p * w, axis=-1) for p in (c*c, s*s, c*s))
    yc, ys = (np.sum(v * a * w, axis=-1) for a in (c, s))
    det = cc * ss - cs**2
    usable = det > np.maximum(1e-14 * (cc + ss)**2, FLOOR)
    a = np.divide(ss*yc - cs*ys, det, out=np.zeros_like(det), where=usable)
    b = np.divide(cc*ys - cs*yc, det, out=np.zeros_like(det), where=usable)
    explained = np.maximum(a*yc + b*ys, 0.)
    fraction = explained / np.maximum(np.sum(v**2 * w, axis=-1), FLOOR)
    return np.asarray(a - 1j*b), np.clip(fraction, 0., 1.), np.asarray(explained)


def quadrature(
    y: Float, phase: Float, weights: Float | None = None, degree: int = 1,
) -> tuple[Complex, Float]:
    z, fraction, _ = quadrature_stats(y, phase, weights, degree)
    return z, fraction


def chirp_phase(tau: Float, hz: Float | float, rate: Float | float) -> Float:
    return np.asarray(2*np.pi * (hz*tau + .5*rate*tau**2))


def split_half_coherence(y: Float, phase: Float, degree: int = 1) -> Float:
    half = y.shape[-1] // 2
    left, _ = quadrature(y[..., :half], phase[..., :half], degree=degree)
    right, _ = quadrature(y[..., half:], phase[..., half:], degree=degree)
    return coherence(left, right)


def coherence(left: Complex, right: Complex) -> Float:
    return np.asarray(np.clip(
        2*np.real(left * right.conj()) / (abs(left)**2 + abs(right)**2 + FLOOR), -1., 1.
    ))


@dataclass(frozen=True)
class Steps:
    index: Int
    strength_v: Float


def detect_steps(y: Float, fs: float, noise_v: float) -> Steps:
    """Find persistent low-pass jumps with three flank lengths.

    Require consistent contrasts as the flanks grow. A jump must also stand
    above the within-flank variance to distinguish it from a bright tone.
    """
    span = max(4, round(.8e-9 * fs))
    i = np.arange(4*span, len(y) - 4*span, dtype=np.int64)
    prefix = np.r_[0., np.cumsum(y)]
    short = (prefix[i+span] + prefix[i-span] - 2*prefix[i]) / span
    long = (prefix[i+2*span] + prefix[i-2*span] - 2*prefix[i]) / (2*span)
    wide = (prefix[i+4*span] + prefix[i-4*span] - 2*prefix[i]) / (4*span)
    aligned = ((short*long > 0.) & (short*wide > 0.) & (abs(long-short) < .55*abs(short))
               & (abs(wide-short) < .55*abs(short)))
    contrast = np.minimum(np.minimum(abs(short), abs(long)), abs(wide))
    sum_square = np.r_[0., np.cumsum(y**2)]
    left_mean = (prefix[i]-prefix[i-4*span]) / (4*span)
    right_mean = (prefix[i+4*span]-prefix[i]) / (4*span)
    left_var = (sum_square[i]-sum_square[i-4*span]) / (4*span) - left_mean**2
    right_var = (sum_square[i+4*span]-sum_square[i]) / (4*span) - right_mean**2
    stable = contrast**2 > 6.25*np.maximum(left_var, right_var)
    contrast = np.where(aligned & stable, contrast, 0.)
    peaks, _ = find_peaks(contrast, height=max(7.*noise_v, 1e-12), distance=span)
    return Steps(i[peaks], contrast[peaks])


def project_steps(
    y: Float, q: Int, width: int, steps: Steps, degree: int = 1,
) -> tuple[Float, Int]:
    """Select the strongest jump within each window and fit its two flanks."""
    slab = y[q[:, None] + offsets(width)]
    residual = detrend(slab, degree=degree)
    split = np.full(len(q), -1, dtype=np.int64)
    best = np.zeros(len(q))
    for index, strength in zip(steps.index, steps.strength_v, strict=True):
        left = index - q + width // 2
        eligible = (left >= 4) & (left <= width-4) & (strength > best)
        split[eligible] = left[eligible]
        best[eligible] = strength
    # Most windows have no detected step. Group the remaining windows so the
    # polynomial projection is vectorized even when the selected split differs.
    for point in np.unique(split[split >= 0]):
        own = split == point
        residual[own, :point] = detrend(slab[own, :point], degree=degree)
        residual[own, point:] = detrend(slab[own, point:], degree=degree)
    return residual, split


def same_side_weights(q: Int, width: int, steps: Steps, n: int) -> Float:
    index = q[:, None] + offsets(width)
    order = np.searchsorted(steps.index, q, side="right")
    bounds = np.concatenate(([-n], steps.index, [2*n]))
    own = (index >= bounds[order, None]) & (index < bounds[order+1, None])
    return own.astype(np.float64)


def center_power(y: Float, q: Int, width: int, steps: Steps) -> Float:
    """Local detrended voltage power on the same side of a jump as the center."""
    power = np.full(len(q), np.nan)
    valid = complete(q, len(y), width)
    slab = y[q[valid, None] + offsets(width)]
    w = same_side_weights(q[valid], width, steps, len(y))
    remaining = w.sum(axis=-1)
    energy = np.sum(w * detrend(slab, w)**2, axis=-1)
    power[valid] = np.where(remaining >= width // 2, energy / np.maximum(remaining, 1), 0.)
    return power


@dataclass(frozen=True)
class Quiet:
    noise_power_v2: float
    frequency_hz: Float
    floor_v2: Float
    quiet_centers: Int
    center_threshold_db: float
    steps: Steps


def quiet_model(y: Float, fs: float, q: Int, *, fmax: float = FMAX) -> Quiet:
    width = samples_for_ns(6.4, fs)
    valid_q = q[complete(q, len(y), width)]
    if not len(valid_q):
        return Quiet(FLOOR, np.array([0., fs/2]), np.full(2, FLOOR), valid_q, 3.,
                     Steps(np.empty(0, dtype=np.int64), np.empty(0)))
    raw = detrend(y[valid_q[:, None] + offsets(width)])
    energy = np.mean(raw**2, axis=-1)
    # The lowest-energy decile is selected from voltage alone. Frozen visual
    # stages and nominal onsets play no role in the novel methods.
    order = np.argsort(energy, kind="stable")[:max(1, len(energy)//10)]
    noise = max(float(np.median(energy[order])), FLOOR)
    threshold_db = max(1.5, float(10*np.log10(
        max(float(np.quantile(energy[order], .95)), FLOOR) / noise
    )) + 1.25)
    taper = np.hanning(width)
    nfft = max(2048, width*4)
    f = np.fft.rfftfreq(nfft, 1/fs)
    spectra = abs(np.fft.rfft(raw[order]*taper, n=nfft))**2 / (taper @ taper)
    median = np.median(spectra, axis=0) / np.log(2.)
    band = (f >= FMIN) & (f <= fmax)
    bins = max(3, 2*round(.25e9 / (fs/nfft)) + 1)
    floor = percentile_filter(median[band], 40., size=bins, mode="nearest")
    # Short-window detrending attenuates the lowest spectral bins even for
    # white noise. Avoid treating that loss as improved low-frequency sensitivity.
    reference = (f[band] >= 250e6) & (f[band] <= 500e6)
    low = f[band] < 250e6
    floor[low] = np.maximum(floor[low], np.median(floor[reference]))
    floor = np.maximum(floor, max(float(np.median(floor))*1e-3, FLOOR))
    return Quiet(noise, f[band], floor, valid_q[order], threshold_db,
                 detect_steps(y, fs, noise**.5))


def impulse_weights(y: Float, fs: float, noise_v: float) -> Float:
    """Flag isolated outliers using the two neighbors and local scale."""
    difference = y[1:-1] - .5*(y[:-2] + y[2:])
    local = uniform_filter1d(abs(difference), size=max(5, round(1.6e-9*fs)))
    threshold = np.maximum(7.*local, 6.*noise_v)
    return np.concatenate(([1.], (abs(difference) <= threshold).astype(np.float64), [1.]))
