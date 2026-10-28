"""TASK007 local waveform estimators: no trajectory prior or GUI dependency.

Frequencies describe the sampled waveform. Physical anti-alias/identity evidence
is deliberately separate. A finite candidate is not a validated velocity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize, minimize_scalar  # type: ignore[import-untyped]

FloatArray = NDArray[np.float64]
Model = Literal["tone", "chirp"]


@dataclass(frozen=True)
class FitConfig:
    sample_rate_hz: float
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    model: Model
    detection_threshold: float
    maximum_chirp_cycles: float = 4.0
    residual_peak_threshold: float = 14.0
    residual_correlation_limit: float = 0.3

    def __post_init__(self) -> None:
        values = (self.sample_rate_hz, self.minimum_frequency_hz,
                  self.maximum_frequency_hz, self.detection_threshold,
                  self.maximum_chirp_cycles, self.residual_peak_threshold,
                  self.residual_correlation_limit)
        if not all(np.isfinite(values)):
            raise ValueError("All configuration values must be finite")
        if not 0 < self.minimum_frequency_hz < self.maximum_frequency_hz < self.sample_rate_hz / 2:
            raise ValueError("Frequency search must be strictly inside (0, Nyquist)")
        if self.model not in ("tone", "chirp") or self.detection_threshold < 0:
            raise ValueError("Unknown model or negative threshold")
        if self.maximum_chirp_cycles <= 0 or self.residual_peak_threshold <= 0:
            raise ValueError("Positive chirp bound and residual threshold required")
        if not 0 < self.residual_correlation_limit <= 1:
            raise ValueError("Residual correlation limit must lie in (0,1]")


@dataclass(frozen=True)
class Estimate:
    frequency_hz: float
    candidate_frequency_hz: float
    chirp_hz_per_s: float
    sigma_hz: float
    amplitude_v: float
    detection_score: float
    residual_peak_score: float
    residual_lag1: float
    residual_rms_v: float
    flag: str
    provenance: str


def _linear_fit(y: FloatArray, u: FloatArray, q: float, b: float
                ) -> tuple[FloatArray, FloatArray, FloatArray]:
    phase = 2 * np.pi * (q * u + .5 * b * u**2)
    design = np.column_stack((np.cos(phase), np.sin(phase), np.ones(len(y))))
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ coef
    return coef, residual, design


def residual_peak_score(y: FloatArray) -> float:
    """Unwindowed max periodogram / total power; diagnostic, not a p-value."""
    centered = y - np.mean(y)
    energy = float(centered @ centered)
    if energy <= np.finfo(float).tiny:
        return 0.0
    spectrum = np.fft.rfft(centered, n=4 * len(y))
    return float(np.max(abs(spectrum[1:-1])**2) / energy)


def fit_frame(voltage_v: FloatArray, config: FitConfig) -> Estimate:
    """Blind multistart variable projection in dimensionless f*T, chirp*T**2.

    DC is a fitted nuisance parameter. No known truth, transfer function, previous
    frequency, or target seed enters this estimator. The covariance assumes local
    iid Gaussian residuals and is conditional on this model and frequency basin.
    """
    y = np.asarray(voltage_v, dtype=np.float64)
    if y.ndim != 1 or len(y) < 32 or not np.isfinite(y).all():
        raise ValueError("Expected at least 32 finite real voltage samples")
    size = len(y)
    duration = size / config.sample_rate_hz
    u = (np.arange(size, dtype=float) - size / 2) / size
    scale = float(np.std(y))
    if scale <= np.finfo(float).tiny:
        return Estimate(np.nan, np.nan, np.nan, np.nan, 0., 0., 0., 0., 0.,
                        "NO_VARIATION", "unobserved")
    normalized = (y - np.mean(y)) / scale
    lo, hi = config.minimum_frequency_hz * duration, config.maximum_frequency_hz * duration
    qs = np.fft.fftfreq(4 * size) * size
    mask = (qs >= lo) & (qs <= hi)
    slopes = np.linspace(-config.maximum_chirp_cycles, config.maximum_chirp_cycles, 9)
    if config.model == "tone":
        slopes = np.array([0.])
    starts: list[tuple[float, float, float]] = []
    for trial_b in slopes:
        dechirped = normalized * np.exp(-1j * np.pi * trial_b * u**2)
        power = abs(np.fft.fft(dechirped, n=4 * size))**2
        indices = np.flatnonzero(mask)
        index = int(indices[np.argmax(power[mask])])
        starts.append((float(power[index]), float(qs[index]), float(trial_b)))
    fits: list[tuple[float, float, float, bool]] = []
    for _, q0, b0 in sorted(starts, reverse=True)[:3]:
        if config.model == "tone":
            def objective_tone(q: float) -> float:
                residual = _linear_fit(normalized, u, q, 0.)[1]
                return float(residual @ residual)
            opt = minimize_scalar(objective_tone, bounds=(max(lo, q0 - .75),
                                                         min(hi, q0 + .75)),
                                  method="bounded", options={"xatol": 1e-9})
            fits.append((float(opt.fun), float(opt.x), 0., bool(opt.success)))
        else:
            def objective_chirp(x: FloatArray) -> float:
                residual = _linear_fit(normalized, u, float(x[0]), float(x[1]))[1]
                return float(residual @ residual)
            opt = minimize(objective_chirp, np.array([q0, b0]), method="L-BFGS-B",
                           bounds=[(max(lo, q0 - 1.5), min(hi, q0 + 1.5)),
                                   (-config.maximum_chirp_cycles, config.maximum_chirp_cycles)],
                           options={"ftol": 1e-12, "maxiter": 90})
            fits.append((float(opt.fun), float(opt.x[0]), float(opt.x[1]), bool(opt.success)))
    rss, q, b, converged = min(fits)
    coef, residual, design = _linear_fit(normalized, u, q, b)
    score = .5 * size * np.log(size / max(rss, np.finfo(float).tiny))
    residual_score = residual_peak_score(residual)
    lag = float(residual[:-1] @ residual[1:] / max(rss, np.finfo(float).tiny))
    quadrature = -coef[0] * design[:, 1] + coef[1] * design[:, 0]
    columns = [design, (quadrature * 2 * np.pi * u)[:, None]]
    if config.model == "chirp":
        columns.append((quadrature * np.pi * u**2)[:, None])
    jacobian = np.column_stack(columns)
    information = jacobian.T @ jacobian
    covariance = np.linalg.pinv(information) * rss / (size - jacobian.shape[1])
    sigma = float(np.sqrt(max(0., covariance[3, 3])) / duration)
    reasons = []
    if not converged:
        reasons.append("OPTIMIZER_FAILED")
    if score < config.detection_threshold:
        reasons.append("NO_DETECTION")
    if residual_score > config.residual_peak_threshold:
        reasons.append("COMPETING_COMPONENT_OR_MODEL_MISMATCH")
    if abs(lag) > config.residual_correlation_limit:
        reasons.append("COLORED_RESIDUAL")
    if (q - abs(b) / 2 <= lo or q + abs(b) / 2 >= hi
            or (config.model == "chirp" and abs(b) >= .99 * config.maximum_chirp_cycles)):
        reasons.append("SEARCH_BOUNDARY")
    if np.linalg.cond(information) > 1e10 or not np.isfinite(sigma):
        reasons.append("ILL_CONDITIONED")
    frequency = q / duration
    return Estimate(np.nan if reasons else frequency, frequency, b / duration**2,
                    np.nan if reasons else sigma, float(np.hypot(*coef[:2]) * scale),
                    float(score), residual_score, lag, float(np.sqrt(rss / size) * scale),
                    "|".join(reasons) if reasons else "LOCAL_MODEL_SUPPORTED_IDENTITY_UNVERIFIED",
                    "rejected" if reasons else "estimated_from_waveform")


def alias_candidates(folded_hz: float, sample_rate_hz: float,
                     allowed_band_hz: tuple[float, float]) -> tuple[float, ...]:
    """Enumerate aliases; one surviving branch requires an independently justified band."""
    low, high = allowed_band_hz
    if not all(np.isfinite([folded_hz, sample_rate_hz, low, high])):
        raise ValueError("Finite frequency values required")
    if sample_rate_hz <= 0 or not 0 <= folded_hz <= sample_rate_hz / 2 or not 0 <= low < high:
        raise ValueError("Invalid folded frequency, rate or band")
    values = {k * sample_rate_hz + sign * folded_hz
              for k in range(int(high / sample_rate_hz) + 2) for sign in (-1, 1)}
    return tuple(sorted(value for value in values if low <= value <= high))


def apparent_velocity(frequency_hz: FloatArray, *, wavelength_m: float,
                      optical_offset_hz: float, signed_beat_branch: int) -> FloatArray:
    """Explicit optical convention f_signed=offset+2*v_app/lambda; no window correction."""
    if not np.isfinite(wavelength_m) or wavelength_m <= 0 or not np.isfinite(optical_offset_hz):
        raise ValueError("Explicit finite wavelength >0 and offset required")
    if signed_beat_branch not in (-1, 1):
        raise ValueError("The physical beat sign must be independently specified")
    return np.asarray((signed_beat_branch * frequency_hz - optical_offset_hz) * wavelength_m / 2)
