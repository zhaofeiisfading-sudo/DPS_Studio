"""Boundary-aware strategies sharing one raw real-waveform projection engine.

No truth inputs, correction, interpolation or prior-zero filling. GLRT-like
scores are in-sample diagnostics, not calibrated probabilities. A sinusoid
supported by voltage is not a certified physical target branch.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar  # type: ignore[import-untyped]
from scipy.signal import find_peaks  # type: ignore[import-untyped]

from .models import BeatEstimate, EstimatorRequest

Float = NDArray[np.float64]


@dataclass(frozen=True)
class Strategy:
    width: int = 1024
    hop: int = 64
    nfft: int = 8192
    boundary: str = "clip"
    degree: int = 1
    mode: str = "fft"
    low_max_hz: float = 250e6
    min_cycles: float = 1.25
    min_r2: float = .20
    min_contrast_db: float = 10.
    slope_sign: bool = False
    project_nuisance: bool = True


STRATEGIES = {
    "stft_short": Strategy(width=512),
    "stft_long": Strategy(width=2048),
    "stft_low": Strategy(width=4096, degree=2, mode="band"),
    "low_prior": Strategy(width=4096, degree=2, mode="prior"),
    "low_glrt": Strategy(width=4096, degree=2, mode="glrt"),
    "tone_refine": Strategy(width=2048, mode="tone"),
    "signed_dechirp": Strategy(width=512, mode="chirp", slope_sign=True),
}


def project_out(design: Float, values: Float) -> Float:
    return np.asarray(values - design @ np.linalg.lstsq(design, values, rcond=1e-10)[0])


def baseline(tau: Float, degree: int) -> Float:
    scaled = (tau - np.mean(tau)) / max(float(np.ptp(tau)), 1e-30)
    return np.asarray(np.polynomial.legendre.legvander(scaled * 2, degree), dtype=np.float64)


def fit_tone(tau: Float, y: Float, hz: float, null: Float,
             rate: float = 0.) -> tuple[float, float, float, Float]:
    """Partial out nuisance from both y and real cosine/sine; stable SVD solve."""
    phase = 2 * np.pi * (hz * tau + .5 * rate * tau**2)
    atoms = np.column_stack((np.cos(phase), np.sin(phase)))
    residual = project_out(null, y)
    projected = project_out(null, atoms)
    coeff, _, _, _ = np.linalg.lstsq(projected, residual, rcond=1e-10)
    error = np.asarray(residual - projected @ coeff)
    rss0, rss1 = float(residual @ residual), float(error @ error)
    r2 = 1 - rss1 / max(rss0, 1e-30)
    statistic = max(0., rss0-rss1) / 2 / max(rss1 / max(1, len(y)-null.shape[1]-2), 1e-30)
    condition = float(np.linalg.cond(np.column_stack((null, atoms))))
    return r2, statistic, condition, error


def spectral_candidates(tau: Float, residual: Float, fs: float, spec: Strategy,
                        fmin: float, fmax: float, stage: str) -> tuple[list[dict[str, float]], float]:
    rates = np.zeros(1)
    if spec.mode == "chirp":
        rates = np.linspace(-8e16, 8e16, 17)
        if spec.slope_sign and stage in ("acceleration", "rebound"):
            rates = rates[rates >= 0]
        elif spec.slope_sign and stage == "decline":
            rates = rates[rates <= 0]
    midpoint = float((tau[0]+tau[-1])/2)
    windowed = residual * (.5 - .5 * np.cos(2*np.pi*np.arange(len(residual))/len(residual)))
    spectrum = np.abs(np.fft.fft(windowed[None, :] * np.exp(
        -1j*np.pi*rates[:, None]*(tau-midpoint)**2), n=spec.nfft, axis=1))**2
    freq = np.fft.fftfreq(spec.nfft, 1/fs)
    band = np.flatnonzero((freq >= fmin) & (freq <= fmax))
    if not len(band):
        return [], np.nan
    noise = max(float(np.median(spectrum[:, band])), 1e-30)
    candidates = []
    for row, rate in enumerate(rates):
        peaks = find_peaks(spectrum[row, band])[0]
        # Include band-edge maxima so a boundary failure remains auditable.
        peaks = np.unique(np.r_[peaks, np.argmax(spectrum[row, band])])
        for peak in peaks[np.argsort(spectrum[row, band[peaks]])[-8:]]:
            b = int(band[peak])
            logs = np.log(np.maximum(spectrum[row, b-1:b+2], 1e-300))
            delta = 0.
            if len(logs) == 3 and logs[0]-2*logs[1]+logs[2] < -1e-14:
                delta = float(np.clip(.5*(logs[0]-logs[2])/(logs[0]-2*logs[1]+logs[2]), -.5, .5))
            hz = float((b+delta)*fs/spec.nfft-rate*midpoint)
            power_ratio = float(spectrum[row, b]/noise)
            candidates.append(dict(frequency_hz=hz, chirp_hz_s=float(rate),
                                   contrast_db=float(10*np.log10(max(power_ratio, 1e-30))),
                                   score=float(np.log1p(power_ratio))))
    return sorted(candidates, key=lambda x: -x["score"]), noise


def estimate_strategy(request: EstimatorRequest, name: str,
                      spec: Strategy | None = None) -> BeatEstimate:
    spec = STRATEGIES[name] if spec is None else spec
    record = request.record
    fs = record.sample_rate_hz
    segment = request.segment
    stage = segment.stage if segment else "unknown"
    start = segment.start_s if segment else request.start_s
    end = segment.end_s if segment else request.end_s
    first = int(np.searchsorted(record.time_s, start))
    last = int(np.searchsorted(record.time_s, end, side="left"))
    if end == record.end_time_s:
        last = len(record.time_s)
    centers = np.arange(0, len(record.time_s), spec.hop, dtype=np.int64)
    centers = centers[(record.time_s[centers] >= start) & (record.time_s[centers] <= end)]
    frequency = np.full(len(centers), np.nan)
    candidates = frequency.copy()
    flags: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    fmin = max(1., float(request.workflow_options["minimum_frequency_hz"]))
    fmax = min(float(request.workflow_options["maximum_frequency_hz"]), fs*.49)
    for i, center in enumerate(centers):
        left, right = max(0, int(center)-spec.width//2), min(len(record.time_s), int(center)+spec.width//2)
        if spec.boundary == "clip":
            left, right = max(left, first), min(right, last)
        elif spec.boundary == "one_sided":
            left, right = max(first, int(center)-spec.width+1), min(last, int(center)+1)
        tau = (np.arange(left, right)-center)/fs
        y = np.asarray(record.voltage_v[left:right])
        detail: dict[str, Any] = dict(center_sample=int(center), support_samples=len(y),
                                     support_start_sample=left, support_end_sample=right,
                                     candidates=[], source="UNOBSERVABLE", prior_zero_m_s=
                                     0. if stage == "stationary" else None)
        diagnostics.append(detail)
        if len(y) < 48 or fmin >= fmax:
            flags.append("INSUFFICIENT_SUPPORT|UNOBSERVABLE_NOT_ZERO")
            continue
        null = baseline(tau, spec.degree)
        residual = project_out(null, y)
        peaks, _ = spectral_candidates(tau, residual, fs, spec, fmin, fmax, stage)
        detail["candidates"] = peaks
        if not peaks:
            flags.append("EMPTY_BAND|UNOBSERVABLE_NOT_ZERO")
            continue
        chosen = peaks[0].copy()
        upper = min(fmax, spec.low_max_hz)
        if spec.mode in ("band", "glrt"):
            low_peaks, _ = spectral_candidates(tau, residual, fs, spec, fmin, upper, stage)
            if spec.mode == "glrt":
                # Nuisance is estimated from voltage, not a truth-supplied spur frequency.
                high = [p for p in peaks if p["frequency_hz"] > upper*1.5]
                if spec.project_nuisance and high and high[0]["contrast_db"] >= 15.:
                    seed = high[0]["frequency_hz"]
                    span = fs / len(y)
                    fit = minimize_scalar(lambda f: -fit_tone(tau, y, f, null)[0],
                        bounds=(max(fmin, seed-span), min(fmax, seed+span)), method="bounded")
                    phase = 2*np.pi*float(fit.x)*tau
                    detail["nuisance_hz"] = float(fit.x)
                    null = np.column_stack((null, np.cos(phase), np.sin(phase)))
                residual = project_out(null, y)
                low_peaks, _ = spectral_candidates(tau, residual, fs, spec, fmin, upper, stage)
                detail["residual_candidates"] = low_peaks
            if not low_peaks:
                flags.append("NO_LOW_FREQUENCY_CANDIDATE|UNOBSERVABLE_NOT_ZERO")
                continue
            chosen = low_peaks[0].copy()
        elif spec.mode == "prior":
            chosen = max(peaks, key=lambda p: p["score"] - min(6., (p["frequency_hz"]/upper)**2)).copy()
        f, rate = chosen["frequency_hz"], chosen["chirp_hz_s"]
        if spec.mode in ("glrt", "tone"):
            ceiling = upper if spec.mode == "glrt" else fmax
            span = fs/len(y)
            lo, hi = max(fmin, f-span), min(ceiling, f+span)
            if lo < hi:
                fit = minimize_scalar(lambda q: -fit_tone(tau, y, q, null)[0],
                                      bounds=(lo, hi), method="bounded")
                if fit.success:
                    f = float(fit.x)
        r2, statistic, condition, _ = fit_tone(tau, y, f, null, rate)
        cycles = f*float(np.ptp(tau))
        candidates[i] = f
        detail.update(selected_candidate_hz=f, r2=r2, statistic=statistic,
                      condition=condition, cycles=cycles, chirp_hz_s=rate,
                      contrast_db=chosen["contrast_db"])
        ceiling = upper if spec.mode in ("band", "glrt") else fmax
        if f <= fmin*1.02 or f >= ceiling*.999 or f+rate*tau[0] < 0 or f+rate*tau[-1] < 0:
            flag = "SEARCH_BOUNDARY_UNRESOLVED"
        elif cycles < spec.min_cycles or condition > 1e4:
            flag = "TOO_FEW_CYCLES|UNOBSERVABLE_NOT_ZERO"
        elif r2 < spec.min_r2 or chosen["contrast_db"] < spec.min_contrast_db or statistic < 12.:
            flag = "LOW_WAVEFORM_SUPPORT|UNOBSERVABLE_NOT_ZERO"
        else:
            frequency[i] = f
            detail["source"] = "MEASURED_CONDITIONAL"
            flag = "WAVEFORM_SUPPORTED|IDENTITY_UNVALIDATED"
            if spec.mode == "glrt":
                flag += "|LOCAL_NUISANCE_ASSUMPTION"
        if stage == "stationary":
            flag += "|OPERATOR_STATIONARY_PRIOR_NOT_MEASUREMENT"
            if f > spec.low_max_hz and np.isfinite(frequency[i]):
                flag += "|STATIONARY_LABEL_CONFLICT"
        if spec.boundary != "full":
            flag += "|MANUAL_BOUNDARY_SUPPORT"
        flags.append(flag)
    return BeatEstimate(np.asarray(record.time_s[centers]), frequency, candidates, tuple(flags),
                        name, "TASK-015 raw-waveform shared strategy engine", spec.width,
                        dict(strategy=asdict(spec), frames=diagnostics,
                             support_policy=spec.boundary, observation_quality=
                             segment.observation_quality if segment else "unspecified",
                             prior_zero_is_measurement=False, uncertainty=
                             "profile diagnostics are not calibrated confidence intervals"))
