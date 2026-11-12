"""Local positive-frequency chirp estimation from real PDV voltage in SI units."""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray
from scipy.fft import fft, rfft  # type: ignore[import-untyped]
from scipy.optimize import minimize  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class DechirpSettings:
    window_samples: int = 512
    max_rate_hz_s: float = 1.0e17
    minimum_r2: float = 0.50

    def __post_init__(self) -> None:
        if type(self.window_samples) is not int or not 64 <= self.window_samples <= 2048:
            raise ValueError("Dechirp window must contain 64 to 2048 samples.")
        if not math.isfinite(self.max_rate_hz_s) or self.max_rate_hz_s <= 0:
            raise ValueError("Dechirp slope limit must be positive and finite.")
        if not 0 < self.minimum_r2 < 1:
            raise ValueError("Dechirp minimum R² must be between zero and one.")


@dataclass(frozen=True, slots=True, eq=False)
class DechirpResult:
    settings: DechirpSettings
    vacuum_wavelength_m: float
    time_s: FloatArray
    frequency_hz: FloatArray
    rate_hz_s: FloatArray
    apparent_velocity_m_s: FloatArray
    apparent_acceleration_m_s2: FloatArray
    r2: FloatArray
    flags: tuple[str, ...]
    boundaries_s: tuple[float, ...]


class _LocalFit(NamedTuple):
    frequency: float
    rate: float
    r2: float
    flag: str


def _fit_window(
    t: FloatArray, y: FloatArray, center: float, seed: float, fs: float, cfg: DechirpSettings,
) -> _LocalFit:
    # Dimensionless coordinates: carrier cycles per half-window, quadratic term
    # cycles per half-window squared. Keep the actual raw time samples in the fit.
    half = (t[-1] - t[0]) / 2
    u = (t - center) / half
    weight = np.hanning(t.size)
    y = y - np.average(y, weights=weight)
    energy = float(np.dot(weight, y**2))
    invalid = _LocalFit(math.nan, math.nan, math.nan, "fit_failed")
    if not math.isfinite(energy) or energy <= np.finfo(float).tiny:
        return invalid._replace(flag="weak_model")

    # Positive frequency projection is only a coarse initializer. Its leakage
    # near DC/Nyquist is avoided by requiring >= 2 cycles of edge clearance.
    nfft = 4 * 2 ** (t.size - 1).bit_length()
    frequencies = np.arange(nfft // 2 + 1) * fs / nfft
    clearance = 1 / half
    low, high = max(seed - clearance, clearance), min(seed + clearance, fs / 2 - clearance)
    if low >= high:
        return invalid._replace(flag="candidate_missing")
    span = high - low
    ilo, ihi = np.searchsorted(frequencies, [low, high], side="left")
    if ihi <= ilo:
        return invalid._replace(flag="candidate_missing")
    qmax = min(cfg.max_rate_hz_s * half**2, 32.0)
    rates = np.linspace(-qmax, qmax, 2 * max(1, math.ceil(2 * qmax)) + 1)
    phases = np.pi * u**2
    projection = fft(
        (weight * y)[None, :] * np.exp(-1j * rates[:, None] * phases),
        n=nfft, axis=1,
    )
    power = np.abs(projection[:, ilo:ihi])**2
    rate_bin, freq_bin = np.unravel_index(int(np.argmax(power)), power.shape)
    start = np.array([frequencies[ilo + freq_bin] * half, rates[rate_bin]])

    def evaluate(x: FloatArray) -> tuple[float, FloatArray, FloatArray]:
        phase = (2 * np.pi * x[0]) * u + x[1] * phases
        cos, sin = np.cos(phase), np.sin(phase)
        basis = np.array([cos, sin, np.ones_like(u)])
        weighted = basis * weight
        amplitudes = np.linalg.solve(weighted @ basis.T, weighted @ y)
        residual = y - amplitudes @ basis
        error = float(np.dot(weight, residual**2) / energy)
        phase_gradient = -2 * weight * residual * (-amplitudes[0] * sin + amplitudes[1] * cos)
        gradient = np.array([np.dot(phase_gradient, 2 * np.pi * u),
                             np.dot(phase_gradient, phases)]) / energy
        return error, gradient, residual

    def objective(x: FloatArray) -> tuple[float, FloatArray]:
        error, gradient, _ = evaluate(x)
        return error, gradient

    try:
        optimized = minimize(
            objective, start, jac=True, method="L-BFGS-B",
            bounds=((low * half, high * half), (-qmax, qmax)),
            options={"maxiter": 50, "ftol": 1e-11, "gtol": 1e-7},
        )
        if not optimized.success or not np.isfinite(optimized.x).all():
            return invalid
        error, _, residual = evaluate(optimized.x)
    except (ValueError, np.linalg.LinAlgError, FloatingPointError):
        return invalid

    carrier, rate = optimized.x / np.array([half, half**2])
    r2 = 1 - error
    model = invalid._replace(r2=r2)
    if r2 < cfg.minimum_r2:
        return model._replace(flag="weak_model")
    if (abs(optimized.x[1]) >= 0.995 * qmax
            or min(carrier - low, high - carrier) <= 0.01 * span):
        return model._replace(flag="search_limit")
    edges = carrier + rate * (t[[0, -1]] - center)
    if min(edges) < clearance or max(edges) > fs / 2 - clearance:
        return model._replace(flag="band_limit")

    # Reject a resolved competing component in the residual, including clutter
    # outside the seed band. This is a relative amplitude diagnostic, not a p-value.
    main_amp = math.sqrt(2 * r2 * energy / float(weight.sum()))
    residual_spectrum = np.abs(rfft(weight * residual, n=nfft))
    if 2 * float(residual_spectrum[1:].max()) > 0.55 * main_amp * float(weight.sum()):
        return model._replace(flag="competing_component")

    # A good whole-window score can hide a burst/step in one half. Do not report
    # one slope when either half is poorly explained by the same phase model.
    for part in (slice(None, t.size // 2), slice(t.size // 2, None)):
        y_part, w_part = y[part], weight[part]
        total = float(np.dot(w_part, (y_part - np.average(y_part, weights=w_part))**2))
        if total <= 0 or float(np.dot(w_part, residual[part]**2)) > 0.70 * total:
            return model._replace(flag="inconsistent_window")
    return _LocalFit(float(carrier), float(rate), r2, "accepted")


def estimate_dechirp(
    record: SignalRecord,
    time_s: FloatArray,
    seed_hz: FloatArray,
    *,
    vacuum_wavelength_m: float,
    settings: DechirpSettings = DechirpSettings(),
    boundaries_s: tuple[float, ...] = (),
    analysis_range_s: tuple[float, float] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> DechirpResult:
    """Use STFT only for frame centers and frequency search; fit slope from voltage."""
    if not record.is_uniformly_sampled:
        raise ValueError("The Dechirp search requires approximately uniform samples.")
    if not math.isfinite(vacuum_wavelength_m) or vacuum_wavelength_m <= 0:
        raise ValueError("The vacuum wavelength must be positive and finite.")
    time_s = np.array(time_s, dtype=np.float64, copy=True)
    seed_hz = np.asarray(seed_hz, dtype=np.float64)
    if (time_s.ndim != 1 or seed_hz.shape != time_s.shape or not np.isfinite(time_s).all()
            or np.any(np.diff(time_s) <= 0)):
        raise ValueError("Frame centers must be increasing and match the frequency seeds.")
    if not all(math.isfinite(x) for x in boundaries_s):
        raise ValueError("Fit boundaries must be finite times.")
    dt = np.diff(time_s)
    jump = np.abs(np.diff(seed_hz)) > (
        settings.max_rate_hz_s * dt + 2 * record.sample_rate_hz / settings.window_samples
    )
    boundaries = tuple(sorted(set(boundaries_s) | set(time_s[:-1][jump] + dt[jump] / 2)))
    frequency = np.full(time_s.size, np.nan)
    rate = np.full(time_s.size, np.nan)
    scores = np.full(time_s.size, np.nan)
    flags: list[str] = []
    n = settings.window_samples
    starts = np.searchsorted(record.time_s, time_s) - n // 2
    for i, (center, seed, first) in enumerate(zip(time_s, seed_hz, starts, strict=True)):
        if cancelled is not None and cancelled():
            raise CancelledError
        last = first + n
        if first < 0 or last > record.sample_count:
            flags.append("window_edge")
            continue
        t = record.time_s[first:last]
        if analysis_range_s is not None and (t[0] < analysis_range_s[0]
                                             or t[-1] > analysis_range_s[1]):
            flags.append("window_edge")
            continue
        boundary_idx = np.searchsorted(boundaries, t[0], side="right")
        if boundary_idx < len(boundaries) and boundaries[boundary_idx] <= t[-1]:
            flags.append("crosses_boundary")
            continue
        if not math.isfinite(seed) or not 0 < seed < record.nyquist_frequency_hz:
            flags.append("candidate_missing")
            continue
        fit = _fit_window(t, record.voltage_v[first:last], center, seed,
                          record.sample_rate_hz, settings)
        frequency[i], rate[i], scores[i], flag = fit
        flags.append(flag)
    velocity = frequency * (vacuum_wavelength_m / 2)
    acceleration = rate * (vacuum_wavelength_m / 2)
    for array in (time_s, frequency, rate, velocity, acceleration, scores):
        array.setflags(write=False)
    return DechirpResult(settings, vacuum_wavelength_m, time_s, frequency, rate,
                         velocity, acceleration, scores, tuple(flags), boundaries)
