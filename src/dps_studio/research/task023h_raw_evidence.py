"""Four preregistered, GT-blind raw-domain statistics. No tracker imports.

These are coherence statistics, not probabilities or likelihoods. Hilbert phase
belongs to the observed mixture and does not identify a physical component.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import hilbert  # type: ignore[import-untyped]

FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]
FEATURES = ('E1', 'E2', 'E3', 'E4raw')


@dataclass(frozen=True)
class Evidence:
    E1: float = float('nan')
    E2: float = float('nan')
    E3: float = float('nan')
    E4raw: float = float('nan')
    samples: int = 0
    phase_valid_fraction: float = 0.0
    amplitude_rms_v: float = float('nan')
    bandwidth_hz: float = float('nan')
    residual_if_median_abs_hz: float = float('nan')
    quality: str = 'UNCOMPUTED'

    def row(self) -> dict[str, Any]:
        return asdict(self)


def analytic_signal(time_s: FloatArray, voltage_v: FloatArray) -> ComplexArray:
    """Full-record Hilbert transform; fail explicitly, never fill missing data."""
    t, v = np.asarray(time_s, dtype=float), np.asarray(voltage_v, dtype=float)
    if t.ndim != 1 or v.shape != t.shape or len(t) < 2:
        raise ValueError('Expected equally sized 1D time/voltage arrays')
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)):
        raise ValueError('NONFINITE_RAW_INPUT; no interpolation or deletion')
    dt = np.diff(t)
    if np.any(dt <= 0) or not np.allclose(dt, np.median(dt), rtol=1e-5, atol=0):
        raise ValueError('NONUNIFORM_ACQUISITION; no resampling')
    return np.asarray(hilbert(v), dtype=np.complex128)


def integrate_phase(time_s: FloatArray, frequency_hz: FloatArray) -> FloatArray:
    """Trapezoidal integral on the actual raw times, including irregular grids."""
    t, f = np.asarray(time_s, dtype=float), np.asarray(frequency_hz, dtype=float)
    if t.ndim != 1 or f.shape != t.shape or len(t) < 2:
        raise ValueError('Expected equally sized sample-grid time/frequency arrays')
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(f)) or np.any(np.diff(t) <= 0):
        raise ValueError('Undefined phase/time; no interpolation')
    return np.asarray(np.r_[0., np.cumsum(np.pi * (f[1:] + f[:-1]) * np.diff(t))])


def proposal_model(raw_time_s: FloatArray, knot_time_s: FloatArray,
                   knot_frequency_hz: FloatArray) -> tuple[NDArray[np.bool_], FloatArray]:
    """Declared linear frequency model between existing knots; not raw interpolation."""
    kt = np.asarray(knot_time_s, dtype=float)
    kf = np.asarray(knot_frequency_hz, dtype=float)
    if kt.ndim != 1 or kf.shape != kt.shape or len(kt) < 2:
        raise ValueError('INSUFFICIENT_PROPOSAL_HISTORY')
    if not np.all(np.isfinite(kt)) or not np.all(np.isfinite(kf)):
        raise ValueError('NONFINITE_PROPOSAL; no interpolation across NaN')
    order = np.argsort(kt)
    kt, kf = kt[order], kf[order]
    if np.any(np.diff(kt) <= 0):
        raise ValueError('DUPLICATE_PROPOSAL_TIMES')
    mask = (raw_time_s >= kt[0]) & (raw_time_s <= kt[-1])
    return mask, np.asarray(np.interp(raw_time_s[mask], kt, kf), dtype=float)


def demodulated_evidence(time_s: FloatArray, analytic: ComplexArray,
                         sample_frequency_hz: FloatArray, stft_window_s: float) -> Evidence:
    """Compute exactly four statistics with fixed physical bandwidth and segments."""
    t, z = np.asarray(time_s, dtype=float), np.asarray(analytic, dtype=np.complex128)
    if t.ndim != 1 or z.shape != t.shape or sample_frequency_hz.shape != t.shape:
        raise ValueError('Sample arrays must have matching shapes')
    if not np.isfinite(stft_window_s) or stft_window_s <= 0:
        raise ValueError('STFT physical duration must be positive')
    n, bandwidth = len(t), 1. / stft_window_s
    if n < 16:
        return Evidence(samples=n, bandwidth_hz=bandwidth, quality='INSUFFICIENT_SAMPLES')
    if not np.all(np.isfinite(z)) or not np.all(np.isfinite(sample_frequency_hz)):
        return Evidence(samples=n, bandwidth_hz=bandwidth, quality='NONFINITE_PHASE_OR_SIGNAL')
    phase = integrate_phase(t, sample_frequency_hz)
    if not np.allclose(np.diff(t), np.median(np.diff(t)), rtol=1e-5, atol=0):
        return Evidence(samples=n, bandwidth_hz=bandwidth, quality='NONUNIFORM_FFT_GRID')
    power = float(np.vdot(z, z).real)
    if power <= np.finfo(float).tiny:
        return Evidence(samples=n, bandwidth_hz=bandwidth, quality='ZERO_AMPLITUDE_PHASE_UNDEFINED')
    demod = z * np.exp(-1j * phase)
    e1 = float(abs(np.sum(demod)) ** 2 / (n * power))
    spectrum = np.fft.fft(demod)
    frequency = np.fft.fftfreq(n, d=float(np.median(np.diff(t))))
    e2 = float(np.sum(abs(spectrum[abs(frequency) <= bandwidth]) ** 2) / (n * power))
    rms = float(np.sqrt(power / n))
    amplitude_ok = abs(z) >= .1 * rms
    increments = np.angle(demod[1:] * demod[:-1].conj())
    valid = amplitude_ok[1:] & amplitude_ok[:-1] & (abs(increments) < .9 * np.pi)
    fraction = float(np.mean(valid))
    residual = np.full(n - 1, np.nan)
    residual[valid] = increments[valid] / (2 * np.pi * np.diff(t)[valid])
    median = float(np.median(abs(residual[valid]))) if fraction >= .5 else float('nan')
    e3 = float(1 / (1 + median / bandwidth)) if np.isfinite(median) else float('nan')
    e4 = float(sum(abs(np.sum(segment)) ** 2 / len(segment)
                   for segment in np.array_split(demod, 4)) / power)
    quality = 'OK' if np.all(valid) else ('MASKED_PHASE' if fraction >= .5 else 'LOW_PHASE_COVERAGE')
    return Evidence(e1, e2, e3, e4, n, fraction, rms, bandwidth, median, quality)


def evidence_for_proposal(raw_time_s: FloatArray, analytic: ComplexArray,
                          knot_time_s: FloatArray, knot_frequency_hz: FloatArray,
                          stft_window_s: float) -> Evidence:
    try:
        mask, frequency = proposal_model(raw_time_s, knot_time_s, knot_frequency_hz)
    except ValueError as error:
        return Evidence(quality=str(error))
    return demodulated_evidence(raw_time_s[mask], analytic[mask], frequency, stft_window_s)


def single_component_reference(time_s: FloatArray, amplitude_v: float,
                               noise_sd_v: float) -> float:
    """REFERENCE ONLY: phase-cycle-averaged iid real Gaussian sinusoid Fisher bound.

    y=A cos(2 pi f t + phi)+iid N(0,sigma^2), constant A,f, unknown phase.
    Var(f)>=2 sigma^2/[A^2 (2 pi)^2 sum(t-tbar)^2]. Local approximation only.
    Not a multicomponent bound or an impossibility proof.
    """
    if amplitude_v <= 0 or noise_sd_v < 0 or len(time_s) < 3:
        return float('nan')
    spread = float(np.sum((time_s - np.mean(time_s)) ** 2))
    return float(np.sqrt(2 * noise_sd_v ** 2 / (amplitude_v ** 2 * (2*np.pi)**2 * spread)))
