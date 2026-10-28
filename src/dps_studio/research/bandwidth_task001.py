"""TASK-001: independent-noise AR(1) likelihood and residual attribution.

All arrays use SI units. Detection establishes a digital component, not a
physical interface, signed velocity, or an unaliased analog carrier.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy import optimize, signal  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import (
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import compute_stft

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class NoiseModel:
    rho: float
    innovation_std_v: float
    source: str = "independent_noise_training"

    def __post_init__(self) -> None:
        if not math.isfinite(self.rho) or abs(self.rho) >= 1:
            raise ValueError("AR(1) requires finite abs(rho) < 1")
        if not math.isfinite(self.innovation_std_v) or self.innovation_std_v <= 0:
            raise ValueError("Noise standard deviation must be positive")


def train_noise(records: FloatArray) -> NoiseModel:
    """Estimate only from separate noise records; never from fitted residuals."""
    if records.ndim != 2 or min(records.shape) < 4 or not np.isfinite(records).all():
        raise ValueError("Need finite independent noise records, shape (records, samples)")
    x = records - records.mean(axis=1, keepdims=True)
    denominator = float(np.sum(x[:, :-1] ** 2))
    if denominator <= 0:
        raise ValueError("Degenerate noise training")
    rho = float(np.clip(np.sum(x[:, 1:] * x[:, :-1]) / denominator, -0.98, 0.98))
    std = float(np.sqrt(np.mean((x[:, 1:] - rho * x[:, :-1]) ** 2)))
    return NoiseModel(rho, std)


def stationary_noise(
    rng: np.random.Generator, n: int, rms_v: float, rho: float,
) -> FloatArray:
    """Exact ADC-time samples of stationary OU noise (rho>0), or iid aperture noise.

    For OU, tau = -1/(fs*log(rho)); the Markov recursion is the exact sampled
    continuous Gaussian process, not a digital filter applied to measured data.
    """
    if n < 2 or rms_v < 0 or not 0 <= rho < 1:
        raise ValueError("Invalid stationary noise parameters")
    innovation = rng.normal(0, rms_v * np.sqrt(1 - rho**2), n)
    innovation[0] = rng.normal(0, rms_v)
    return np.asarray(signal.lfilter([1.0], [1.0, -rho], innovation), dtype=np.float64)


@dataclass(frozen=True)
class AnalogCase:
    sample_rate_hz: float = 20e9
    bandwidth_hz: float = 3e9
    order: int = 1
    n: int = 256
    frequency_hz: float = 4.8e9
    amplitude_v: float = 0.08
    noise_rms_v: float = 0.035
    noise_rho: float = 0.85
    chirp_hz_per_s: float = 0.0
    am_depth: float = 0.0
    competitor_hz: float = 0.0
    competitor_amplitude_v: float = 0.0
    phase_mod_rad: float = 0.0
    response_zero: bool = False
    adc_step_v: float = 0.0
    oversample: int = 8


@dataclass(frozen=True)
class Waveform:
    voltage_v: FloatArray
    clean_v: FloatArray
    analog_frequency_hz: float
    digital_frequency_hz: float
    residual_snr_db: float


def alias_frequency(frequency_hz: float, sample_rate_hz: float) -> float:
    return abs((frequency_hz + sample_rate_hz / 2) % sample_rate_hz - sample_rate_hz / 2)


def analog_response(frequency_hz: float, bandwidth_hz: float, order: int) -> complex:
    """Continuous Butterworth H(j*2*pi*f); B is the analog -3 dB point."""
    b, a = signal.butter(order, 2 * np.pi * bandwidth_hz, analog=True)
    return complex(np.polyval(b, 2j * np.pi * frequency_hz)
                   / np.polyval(a, 2j * np.pi * frequency_hz))


@lru_cache(maxsize=32)
def _analog_discretization(order: int, ratio: float, oversample: int) -> tuple[
    FloatArray, FloatArray,
]:
    # Time coordinate u=fs*t avoids poorly scaled SI state matrices. This is an
    # oversampled numerical approximation to a continuous analog ODE, before ADC.
    b, a = signal.butter(order, 2 * np.pi * ratio, analog=True)
    bd, ad, _ = signal.cont2discrete((b, a), 1 / oversample, method="zoh")
    return np.asarray(bd[0], dtype=np.float64), np.asarray(ad, dtype=np.float64)


def synthesize(case: AnalogCase, seed: int) -> Waveform:
    """Continuous fringe -> analog receiver -> electronics noise -> ADC/quantizer.

    Stationary tones use the exact continuous steady-state response; changing
    fringes use an oversampled ZOH solution with discarded analog startup.
    No inverse response or truth frequency is supplied to the estimators.
    """
    if (case.n < 32 or case.order not in (1, 4) or case.oversample < 4
            or case.sample_rate_hz <= 0 or case.bandwidth_hz <= 0
            or case.amplitude_v < 0 or case.adc_step_v < 0
            or not 0 <= case.am_depth <= 1):
        raise ValueError("Invalid synthetic acquisition configuration")
    rng = np.random.default_rng(seed)
    phase = rng.uniform(-np.pi, np.pi)
    fs = case.sample_rate_hz
    t = (np.arange(case.n, dtype=float) - (case.n - 1) / 2) / fs
    varying = bool(case.chirp_hz_per_s or case.am_depth or case.phase_mod_rad)
    if varying:
        burn = int(np.ceil(16 * fs / case.bandwidth_hz))
        u = np.arange(-burn * case.oversample, case.n * case.oversample) / case.oversample
        th = (u - (case.n - 1) / 2) / fs
        fringe = case.amplitude_v * (1 + case.am_depth * np.cos(2 * np.pi * 0.25e9 * th))
        phi = 2 * np.pi * (case.frequency_hz * th + 0.5 * case.chirp_hz_per_s * th**2)
        phi += phase + case.phase_mod_rad * np.sin(2 * np.pi * 0.25e9 * th)
        input_v = fringe * np.cos(phi)
        if case.competitor_hz:
            input_v += case.competitor_amplitude_v * np.cos(2 * np.pi * case.competitor_hz * th)
        b, a = _analog_discretization(case.order, case.bandwidth_hz / fs, case.oversample)
        full = signal.lfilter(b, a, input_v)
        clean = np.asarray(full[burn * case.oversample::case.oversample], dtype=np.float64)
    else:
        h = analog_response(case.frequency_hz, case.bandwidth_hz, case.order)
        clean = case.amplitude_v * np.abs(h) * np.cos(
            2 * np.pi * case.frequency_hz * t + phase + np.angle(h)
        )
        if case.competitor_hz:
            hc = analog_response(case.competitor_hz, case.bandwidth_hz, case.order)
            clean += case.competitor_amplitude_v * abs(hc) * np.cos(
                2 * np.pi * case.competitor_hz * t + rng.uniform(-np.pi, np.pi) + np.angle(hc)
            )
    if case.response_zero:
        clean = np.zeros(case.n)
    noise = stationary_noise(rng, case.n, case.noise_rms_v, case.noise_rho)
    y = clean + noise
    if case.adc_step_v:
        y = case.adc_step_v * np.rint(y / case.adc_step_v)
    snr = (10 * np.log10(float(np.mean(clean**2)) / case.noise_rms_v**2)
           if np.any(clean) and case.noise_rms_v else math.nan)
    return Waveform(y, clean, case.frequency_hz, alias_frequency(case.frequency_hz, fs), snr)


def ar_transform(x: FloatArray, rho: float) -> FloatArray:
    """Exact stationary AR(1) precision factor, applied to BOTH data and design."""
    result = x.copy()
    result[0] *= np.sqrt(1 - rho**2)
    result[1:] = x[1:] - rho * x[:-1]
    return result


@dataclass(frozen=True)
class ToneFit:
    frequency_hz: float
    score: float
    nominal_sigma_hz: float
    residual_v: FloatArray
    amplitude_v: float


class ToneSearch:
    """Profile Gaussian likelihood with frozen external covariance.

    H0: d=c+e; H1: d=c+a*cos(2*pi*f*t)+b*sin(2*pi*f*t)+e.
    score=max_f (RSS0-RSS1)/sigma_innovation**2. Entire-search null
    calibration accounts for frequency selection; no chi-square shortcut.
    """

    def __init__(self, n: int, fs: float, model: NoiseModel) -> None:
        self.n, self.fs, self.model = n, fs, model
        self.t = (np.arange(n, dtype=float) - (n - 1) / 2) / fs
        self.grid = np.fft.rfftfreq(4 * n, 1 / fs)
        self.grid = self.grid[(self.grid >= 0.2e9) & (self.grid <= 9.5e9)]
        if fs != 20e9 or n < 32:
            raise ValueError("TASK-001 search is explicitly limited to fs=20 GHz, n>=32")
        self.offset = ar_transform(np.ones(n), model.rho)
        self.offset_norm = float(self.offset @ self.offset)
        phase = 2 * np.pi * self.t[:, None] * self.grid[None, :]
        self.cos = ar_transform(np.cos(phase), model.rho)
        self.sin = ar_transform(np.sin(phase), model.rho)
        self.cos -= self.offset[:, None] * (self.offset @ self.cos)[None, :] / self.offset_norm
        self.sin -= self.offset[:, None] * (self.offset @ self.sin)[None, :] / self.offset_norm
        self.cc = np.sum(self.cos**2, axis=0)
        self.ss = np.sum(self.sin**2, axis=0)
        self.cs = np.sum(self.cos * self.sin, axis=0)
        self.det = self.cc * self.ss - self.cs**2

    def _linear(self, yw: FloatArray, frequency_hz: float) -> tuple[float, FloatArray, FloatArray]:
        phase = 2 * np.pi * frequency_hz * self.t
        x = np.column_stack((np.ones(self.n), np.cos(phase), np.sin(phase)))
        xw = ar_transform(x, self.model.rho)
        beta = np.linalg.lstsq(xw, yw, rcond=None)[0]
        residual = yw - xw @ beta
        return float(residual @ residual), np.asarray(beta), x

    def fit(self, y: FloatArray, *, refine: bool = True) -> ToneFit:
        if y.shape != (self.n,) or not np.isfinite(y).all():
            raise ValueError("Frame must have the configured finite sample count")
        yw = ar_transform(y, self.model.rho)
        yc = yw - self.offset * float(self.offset @ yw) / self.offset_norm
        c, s = yc @ self.cos, yc @ self.sin
        gains = (self.ss * c**2 - 2 * self.cs * c * s + self.cc * s**2) / self.det
        i = int(np.argmax(gains))
        f = float(self.grid[i])
        if refine:
            lo, hi = float(self.grid[max(i - 1, 0)]), float(self.grid[min(i + 1, len(self.grid) - 1)])
            opt = optimize.minimize_scalar(
                lambda q: self._linear(yw, float(q) * self.fs)[0],
                bounds=(lo / self.fs, hi / self.fs), method="bounded",
                options={"xatol": 1e-11},
            )
            if opt.success:
                f = float(opt.x * self.fs)
        rss, beta, x = self._linear(yw, f)
        derivative = 2 * np.pi * self.t * (-beta[1] * x[:, 2] + beta[2] * x[:, 1])
        dw, xw = ar_transform(derivative, self.model.rho), ar_transform(x, self.model.rho)
        dw -= xw @ np.linalg.lstsq(xw, dw, rcond=None)[0]
        information = float(dw @ dw) / self.model.innovation_std_v**2
        sigma = 1 / np.sqrt(information) if information > 0 else math.inf
        return ToneFit(f, max(0., float(yc @ yc) - rss) / self.model.innovation_std_v**2,
                       sigma, y - x @ beta, float(np.hypot(beta[1], beta[2])))


@dataclass(frozen=True)
class SpectralBaseline:
    peak_hz: float
    refined_hz: float
    gate_statistic_db: float
    background_db: float
    competitor_db: float


def spectral_baselines(y: FloatArray, fs: float) -> SpectralBaseline:
    """Production STFT/peak/refinement/contrast APIs, no tracking or GUI state."""
    n = len(y)
    record = SignalRecord(time_s=np.arange(n, dtype=float) / fs, voltage_v=y)
    stft = compute_stft(record, window_length_samples=n, overlap_samples=0, nfft=4 * n)
    maximum = min(9.5e9, 0.475 * fs)
    peak = extract_peak_ridge(stft, minimum_frequency_hz=0.2e9, maximum_frequency_hz=maximum)
    refined = refine_peak_ridge_subbin(stft, peak)
    quality = assess_ridge_spectral_quality(
        stft, refined, background_exclusion_half_width_hz=2 * fs / n,
        minimum_background_bin_count=8,
    )
    bg, competitor = float(quality.peak_to_background_db[0]), float(quality.peak_to_competitor_db[0])
    statistic = bg if competitor >= 3 and math.isfinite(bg) else -math.inf
    return SpectralBaseline(float(peak.frequency_hz[0]), float(refined.refined_frequency_hz[0]),
                            statistic, bg, competitor)


def empirical_threshold(scores: FloatArray, alpha: float) -> float:
    """Split-conformal upper null order statistic, with strict > acceptance.

    Marginal false acceptance <= alpha only under exchangeable calibration/test
    nulls. Ties are conservative. This is not a distribution-shift guarantee.
    """
    if scores.ndim != 1 or np.isnan(scores).any() or not 0 < alpha < 1:
        raise ValueError("Invalid calibration scores or alpha")
    k = int(np.ceil((len(scores) + 1) * (1 - alpha)))
    return float(np.sort(scores)[k - 1]) if k <= len(scores) else math.inf


def residual_diagnostics(residual_v: FloatArray, fs: float, lags: int = 20) -> dict[str, float]:
    """Descriptive diagnostics; overlapping lags are never independent tests."""
    r = residual_v - residual_v.mean()
    energy = float(r @ r)
    acf = [float(r[k:] @ r[:-k]) / energy if energy > 0 else math.nan
           for k in range(1, min(lags + 1, len(r)))]
    f, p = signal.welch(r, fs=fs, nperseg=min(128, len(r)))
    chunks = np.array_split(r, 4)
    powers = np.array([np.mean(a**2) for a in chunks])
    return {"lag1": acf[0], "acf_abs_max_20": max(abs(x) for x in acf),
            "psd_peak_hz": float(f[np.argmax(p)]),
            "psd_peak_fraction": float(np.max(p) / np.sum(p)) if np.sum(p) > 0 else math.nan,
            "quarter_power_ratio": float(powers.max() / powers.min()) if powers.min() > 0
            else math.nan, "residual_rms_v": float(np.sqrt(energy / len(r)))}


def local_model_residual(y: FloatArray, fs: float, kind: str) -> tuple[FloatArray, dict[str, float]]:
    """Tone/chirp/two-tone attribution, descriptive fits without acceptance claims."""
    n = len(y)
    t = (np.arange(n, dtype=float) - (n - 1) / 2) / n
    seed = spectral_baselines(y, fs).peak_hz / fs

    def project(q: FloatArray) -> tuple[FloatArray, FloatArray]:
        phi = 2 * np.pi * n * (q[0] * t + (0.5 * q[1] * t**2 if kind == "chirp" else 0))
        columns = [np.ones(n), np.cos(phi), np.sin(phi)]
        if kind == "two_tone":
            phi2 = 2 * np.pi * n * q[1] * t
            columns += [np.cos(phi2), np.sin(phi2)]
        x = np.column_stack(columns)
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        return y - x @ beta, np.asarray(beta)

    if kind not in {"tone", "chirp", "two_tone"}:
        raise ValueError("Unknown local model")
    starts = [np.array([seed])]
    lower, upper = 0.2e9 / fs, min(9.5e9 / fs, 0.475)
    bounds = ([lower], [upper])
    if kind == "chirp":
        starts = [np.array([seed, slope]) for slope in (-0.15, 0., 0.15)]
        bounds = ([lower, -0.35], [upper, 0.35])
    elif kind == "two_tone":
        r = project(np.array([seed, 0.1]))[0]
        second = spectral_baselines(r, fs).peak_hz / fs
        starts = [np.array([seed, second])]
        bounds = ([lower, lower], [upper, upper])
    fits = [optimize.least_squares(lambda q: project(q)[0], q, bounds=bounds,
                                   max_nfev=100) for q in starts]
    best = min(fits, key=lambda a: float(a.fun @ a.fun))
    residual, beta = project(np.asarray(best.x))
    return residual, {"frequency_hz": float(best.x[0] * fs),
                      "chirp_hz_per_s": float(best.x[1] * fs**2 / n)
                      if kind == "chirp" else 0., "amplitude_v": float(np.hypot(beta[1], beta[2])),
                      "converged": float(best.success)}


def checked_input(path: Path, root: Path) -> Path:
    """Real diagnostics may read only files already inside this worktree's raw."""
    resolved = path.resolve(strict=True)
    raw_root = (root.resolve() / "data" / "raw").resolve(strict=True)
    if (not raw_root.is_relative_to(root.resolve())
            or not resolved.is_relative_to(raw_root) or not resolved.is_file()):
        raise ValueError("Real input must resolve inside this worktree data/raw")
    return resolved
