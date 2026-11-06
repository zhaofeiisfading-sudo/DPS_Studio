"""Shared SI-unit records, baseline frontend, and explicitly heuristic evidence.

No truth is accepted by Context or any estimator. Interpolation below evaluates
frequency *model initializers*, never resamples voltage or fills measurements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import find_peaks  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import extract_peak_ridge, refine_peak_ridge_subbin
from dps_studio.core.time_frequency import compute_stft

Float = NDArray[np.float64]
WAVELENGTH_M = 1550e-9  # Synthetic specification; real equivalent-velocity assumption only.
FMIN = 5e6
FMAX = 8e9
HOP = 128
NFFT = 4096
METHODS = ("stft512", "stft768", "stft512_wide", "gated_stft256", "gated_stft512", "dechirp", "varpro", "clutter_varpro",
           "acmd", "matrix_pencil", "time_domain", "baseband")


@dataclass(frozen=True)
class Signal:
    time_s: Float
    voltage_v: Float
    name: str = ""

    def __post_init__(self) -> None:
        if self.time_s.ndim != 1 or self.time_s.shape != self.voltage_v.shape:
            raise ValueError("Expected equally sized one-dimensional time/voltage")
        if len(self.time_s) < 1024 or not np.isfinite(self.time_s).all():
            raise ValueError("Time nonfinite or record shorter than 1024 samples")
        if not np.isfinite(self.voltage_v).all():
            raise ValueError("Nonfinite voltage: implicit sample deletion forbidden")
        steps = np.diff(self.time_s)
        if np.any(steps <= 0) or not np.allclose(steps, np.median(steps), rtol=1e-5, atol=0):
            raise ValueError("Nonuniform/nonmonotone time; no implicit resampling")
        self.time_s.setflags(write=False)
        self.voltage_v.setflags(write=False)

    @property
    def fs(self) -> float:
        return 1 / float(np.median(np.diff(self.time_s)))


@dataclass
class Estimate:
    frequency_hz: Float
    accepted_hz: Float
    flags: NDArray[np.str_]
    onset_s: float | None
    details: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Float] = field(default_factory=dict)


def strongest(signal: Signal, window: int, minimum: float = FMIN,
              maximum: float = FMAX) -> tuple[Float, Float, Float, Float]:
    """Call the unchanged formal STFT, peak extractor and log-subbin kernel."""
    record = SignalRecord(signal.time_s, signal.voltage_v)
    stft = compute_stft(record, window_length_samples=window,
                        overlap_samples=window-HOP, nfft=NFFT, window_name="hann")
    ridge = extract_peak_ridge(stft, minimum_frequency_hz=minimum, maximum_frequency_hz=maximum)
    refined = refine_peak_ridge_subbin(stft, ridge)
    # Preserve discrete values separately; refinement failures remain NaN.
    return (np.asarray(stft.time_s), np.asarray(refined.refined_frequency_hz),
            np.asarray(ridge.frequency_hz), np.asarray(abs(stft.spectrum)))


def event_detector(signal: Signal) -> tuple[int | None, dict[str, Any]]:
    """Offline change in unfiltered raw block energy; quiet-prefix assumption.

    Baseline is first 10%, capped at 4096 samples. No causal/25 ps precision
    claim: 16-sample blocks, two-block confirmation, offline split refinement.
    The prefix may itself contain motion on real data; this is recorded.
    """
    x = signal.voltage_v
    block = 16
    n = len(x)//block
    prefix_n = max(128, min(len(x)//10, 4096))
    baseline = x[:prefix_n]-np.median(x[:prefix_n])
    sigma = float(np.median(abs(baseline-np.median(baseline)))/.67448975)
    sigma = max(sigma, float(np.std(baseline))*.3, 1e-15)
    centered = x[:n*block].reshape(n, block)-np.median(x[:prefix_n])
    energy = np.mean(centered**2, axis=1)
    pre = energy[:prefix_n//block]
    med = float(np.median(pre))
    scatter = float(np.median(abs(pre-med))/.67448975)
    threshold = max(med+6*scatter, med*2.5, sigma**2*2.5)
    high = energy > threshold
    candidates = np.flatnonzero(high[:-1] & high[1:])
    candidates = candidates[candidates >= prefix_n//block]
    meta: dict[str, Any] = dict(block_samples=block, prefix_samples=prefix_n,
                               noise_sigma_v=sigma, energy_threshold_v2=threshold,
                               prefix_is_quiet="ASSUMPTION_NOT_VERIFIED", causal=False)
    if not len(candidates):
        return None, {**meta, "reason": "NO_CONFIRMED_ENERGY_CHANGE"}
    coarse = int(candidates[0]*block)
    lo, hi = max(prefix_n, coarse-4*block), min(len(x), coarse+5*block)
    # Two-variance Gaussian change cost on this fixed local interval.
    y = (x[lo:hi]-np.median(x[:prefix_n]))**2
    cs = np.cumsum(y)
    k = np.arange(8, len(y)-8)
    cost = k*np.log(np.maximum(cs[k-1]/k, sigma**2*.01))
    cost += (len(y)-k)*np.log(np.maximum((cs[-1]-cs[k-1])/(len(y)-k), sigma**2*.01))
    onset = lo+int(k[np.argmin(cost)])
    return onset, {**meta, "coarse_index": coarse, "refined_index": onset,
                   "reason": "ENERGY_CHANGE_NOT_PHYSICAL_ZERO_MEASUREMENT"}


class Context:
    """Only waveform-derived shared evidence and uniform query indices."""

    def __init__(self, signal: Signal):
        self.signal = signal
        self.centers = np.arange(384, len(signal.time_s)-383, HOP, dtype=np.int64)
        self.time_s = np.asarray(signal.time_s[self.centers])
        self.fs = signal.fs
        self.onset, self.event = event_detector(signal)
        self.noise = float(self.event["noise_sigma_v"])
        self.seed_time, self.raw_seed_hz, self.raw_seed_discrete, self.raw_spectrum = strongest(signal, 512)
        # All common centers are an exact subset of the 512-frame centers.
        self.seed_indices = (self.centers-256)//HOP
        if not np.allclose(self.seed_time[self.seed_indices], self.time_s, rtol=0, atol=5e-15):
            raise AssertionError("Shared grid is not aligned to unchanged STFT")
        self.freq_grid = np.fft.rfftfreq(NFFT, d=1/self.fs)
        self.band = (self.freq_grid >= FMIN) & (self.freq_grid <= FMAX)
        # Explicit local-DC nuisance removal for coarse MODEL initialization.
        # The unchanged no-detrend baselines use raw_seed_* and raw_spectrum.
        frames = np.lib.stride_tricks.sliding_window_view(signal.voltage_v, 512)[::HOP]
        hann = .5-.5*np.cos(2*np.pi*np.arange(512)/512)
        self.spectrum = np.asarray(abs(np.fft.rfft(
            (frames-frames.mean(axis=1, keepdims=True))*hann, n=NFFT, axis=1)).T/hann.sum())
        indices = np.flatnonzero(self.band)
        bins = indices[np.argmax(self.spectrum[self.band], axis=0)]
        self.seed_discrete = np.asarray(self.freq_grid[bins])
        logs = np.log(np.maximum(self.spectrum, 1e-300))
        cols = np.arange(len(bins))
        denom = logs[bins-1, cols]-2*logs[bins, cols]+logs[bins+1, cols]
        delta = np.zeros(len(bins))
        ok = denom < -1e-14
        delta[ok] = np.clip(.5*(logs[bins[ok]-1, cols[ok]]-logs[bins[ok]+1, cols[ok]])
                            /denom[ok], -.5, .5)
        self.seed_hz = np.asarray((bins+delta)*self.fs/NFFT)
        self.seed = self.seed_hz[self.seed_indices]
        power = self.spectrum[:, self.seed_indices]**2
        self.contrast = 10*np.log10(np.maximum(np.max(power[self.band], axis=0), 1e-300)
                                    /np.maximum(np.median(power[self.band], axis=0), 1e-300))

    @property
    def onset_s(self) -> float | None:
        return None if self.onset is None else float(self.signal.time_s[self.onset])

    def initializer(self, indices: NDArray[np.int64]) -> Float:
        usable = np.isfinite(self.seed_hz)
        if not np.any(usable):
            raise ValueError("No finite coarse initializer")
        return np.asarray(np.interp(self.signal.time_s[indices], self.seed_time[usable],
                                    self.seed_hz[usable]))

    def segment(self, center: int, width: int, truncate: bool = True) -> tuple[Float, Float]:
        left = max(0, center-width//2)
        if truncate and self.onset is not None and center >= self.onset:
            left = max(left, self.onset)
        right = min(len(self.signal.time_s), center+width//2)
        return ((np.arange(left, right)-center)/self.fs,
                np.asarray(self.signal.voltage_v[left:right]))


def projection(y: Float, phase: Float) -> tuple[Float, Float, float]:
    design = np.column_stack((np.cos(phase), np.sin(phase), np.ones(len(y))))
    coeff, _, _, singular = np.linalg.lstsq(design, y, rcond=1e-10)
    residual = np.asarray(y-design@coeff)
    condition = float(singular[0]/max(singular[-1], 1e-300))
    return np.asarray(coeff), residual, condition


def waveform_r2(context: Context, frequency: Float, chirp: Float | None = None,
                width: int = 256) -> tuple[Float, Float]:
    r2, condition = np.full(len(frequency), np.nan), np.full(len(frequency), np.inf)
    for i, (c, f) in enumerate(zip(context.centers, frequency, strict=True)):
        if not np.isfinite(f):
            continue
        tau, y = context.segment(int(c), width)
        if len(y) < 16:
            continue
        a = 0.0 if chirp is None else float(chirp[i])
        _, res, cond = projection(y, 2*np.pi*(f*tau+.5*a*tau**2))
        total = float(np.sum((y-np.mean(y))**2))
        r2[i] = 1-float(res@res)/max(total, 1e-300)
        condition[i] = cond
    return r2, condition


def finish(context: Context, frequency: Float, *, chirp: Float | None = None,
           r2: Float | None = None, condition: Float | None = None,
           mask_before_onset: bool = True, details: dict[str, Any] | None = None,
           extra: dict[str, Float] | None = None) -> Estimate:
    f = np.array(frequency, dtype=float, copy=True)
    model_extra: dict[str, Float] = {}
    if r2 is not None:
        model_extra["native_model_r2"] = r2
    if condition is not None:
        model_extra["native_design_condition"] = condition
    # Equal 256-sample validation support for all methods. These are in-sample
    # waveform checks, not independent accuracy validation or identity tests.
    r2, condition = waveform_r2(context, f, chirp)
    supported = (np.isfinite(f) & (f >= FMIN) & (f <= FMAX) & (r2 >= .20)
                 & (condition <= 1e5) & (context.contrast >= 10))
    flags = np.full(len(f), "LOW_WAVEFORM_SUPPORT", dtype="U96")
    flags[supported] = "WAVEFORM_SUPPORTED|IDENTITY_UNVALIDATED"
    if mask_before_onset:
        if context.onset is None:
            supported[:] = False
            flags[:] = "NO_EVENT|UNOBSERVABLE_NOT_ZERO"
        else:
            before = context.centers < context.onset
            supported[before] = False
            flags[before] = "PRE_EVENT_UNOBSERVABLE|STATIC_ONLY_IF_PRIOR"
    accepted = np.where(supported, f, np.nan)
    aux = dict(r2=r2, design_condition=condition, **model_extra)
    if chirp is not None:
        aux["chirp_hz_per_s"] = chirp
    if extra:
        aux.update(extra)
    return Estimate(f, np.asarray(accepted), flags, context.onset_s,
                    {"evidence_is_heuristic_not_pvalue": True, **(details or {})}, aux)


def local_fft(y: Float, fs: float, rates: Float | None = None,
              nfft: int = NFFT) -> tuple[float, float, float]:
    """Complex dechirp on real data; retains mirror bias, no Hilbert filtering."""
    tau = (np.arange(len(y))-(len(y)-1)/2)/fs
    rates = np.array([0.]) if rates is None else rates
    atoms = (y-np.mean(y))*np.hanning(len(y))
    values = np.fft.fft(atoms[None, :]*np.exp(-1j*np.pi*rates[:, None]*tau**2),
                        n=nfft, axis=1)
    freq = np.fft.fftfreq(nfft, 1/fs)
    idx = np.flatnonzero((freq >= FMIN) & (freq <= FMAX))
    power = abs(values[:, idx])**2
    j, k = np.unravel_index(np.argmax(power), power.shape)
    b = int(idx[k])
    delta = 0.
    if 0 < b < nfft//2-1:
        logp = np.log(np.maximum(abs(values[j, b-1:b+2]), 1e-300))
        denom = logp[0]-2*logp[1]+logp[2]
        if denom < -1e-14:
            delta = float(np.clip(.5*(logp[0]-logp[2])/denom, -.5, .5))
    return float((b+delta)*fs/nfft), float(rates[j]), float(tau[len(tau)//2])


def candidate_seeds(context: Context, index: int, count: int = 2) -> list[float]:
    mag = context.spectrum[:, context.seed_indices[index]]
    peaks, _ = find_peaks(mag)
    peaks = peaks[context.band[peaks]]
    peaks = peaks[np.argsort(mag[peaks])[::-1]][:count]
    seeds = [float(context.freq_grid[k]) for k in peaks]
    return seeds or [float(context.seed_discrete[context.seed_indices[index]])]
