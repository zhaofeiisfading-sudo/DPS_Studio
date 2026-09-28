"""Frozen waveform-only frequency frontends; no truth or trajectory inputs.

R2 is frequency-only *energy* squeezing, not an invertible complex SST.
Reassignment identities follow librosa's documented derivative-window convention.
R3 maximizes local chirplet projections over a fixed physical chirp-rate bank.
No source samples are changed, resampled, reconstructed, or filtered.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import GlobalPathConfig, extract_global_path_candidates
from dps_studio.core.time_frequency import STFTResult, compute_stft

FloatArray = NDArray[np.float64]
Method = Literal['R0', 'R1', 'R2', 'R3']
METHODS: tuple[Method, ...] = ('R0', 'R1', 'R2', 'R3')
CHIRP_RATES = np.linspace(-2e17, 2e17, 41)
CHIRP_RATES.setflags(write=False)
K = 20


@dataclass(frozen=True)
class Observation:
    """Ranked hypotheses in Hz; missing entries NaN, never physical detections."""

    method: Method
    time_s: FloatArray
    frequency_axis_hz: FloatArray
    frequency_hz: FloatArray
    discrete_hz: FloatArray
    chirp_rate_hz_per_s: FloatArray
    evidence: FloatArray
    quality_flags: NDArray[np.str_]
    representation: FloatArray
    residual_fraction: FloatArray
    reassigned_energy_retained: float


def stft_input(record: SignalRecord, profile: AnalysisProfile) -> STFTResult:
    return compute_stft(record, window_length_samples=profile.window_length_samples,
                        overlap_samples=profile.overlap_samples, nfft=profile.nfft,
                        window_name=profile.window_name)


def raw_frames(record: SignalRecord, profile: AnalysisProfile) -> FloatArray:
    """Read-only strided view of exactly the original STFT supports."""
    if not record.is_uniformly_sampled:
        raise ValueError('Nonuniform input: resampling is forbidden')
    return np.lib.stride_tricks.sliding_window_view(
        record.voltage_v, profile.window_length_samples)[::profile.hop_samples]


def reassignment_coordinates(record: SignalRecord, profile: AnalysisProfile,
                             stft: STFTResult) -> tuple[FloatArray, FloatArray, FloatArray]:
    frames = raw_frames(record, profile)
    n, fs = profile.window_length_samples, record.sample_rate_hz
    u = np.arange(n, dtype=float)
    h = .5-.5*np.cos(2*np.pi*u/n)
    dh = np.pi*fs/n*np.sin(2*np.pi*u/n)
    tau = (u-n/2)/fs
    derivative = np.fft.rfft(frames*dh, n=profile.nfft, axis=1).T/h.sum()
    timed = np.fft.rfft(frames*(h*tau), n=profile.nfft, axis=1).T/h.sum()
    power = np.abs(stft.spectrum)**2
    # Numerical division guard only; NOT a learned support/interval detector.
    keep = (power > 1e-6*np.max(power, axis=0, keepdims=True)) & (power > 0)
    ratio_d = np.zeros_like(stft.spectrum)
    ratio_t = np.zeros_like(stft.spectrum)
    np.divide(derivative, stft.spectrum, out=ratio_d, where=keep)
    np.divide(timed, stft.spectrum, out=ratio_t, where=keep)
    freq = stft.frequency_hz[:, None]-ratio_d.imag/(2*np.pi)
    time = stft.time_s[None, :]+ratio_t.real
    return np.where(keep, freq, np.nan), np.where(keep, time, np.nan), power


def squeeze_energy(frequency_hz: FloatArray, time_s: FloatArray, power: FloatArray,
                   stft: STFTResult, *, move_time: bool) -> tuple[FloatArray, float]:
    """Nearest-cell deposition, no spectral smoothing or raw interpolation.

    Out-of-axis or numerical-guard energy is explicitly excluded and quantified.
    Time reassignment is bounded to the source window; no arbitrary long support.
    """
    df = stft.sample_rate_hz/stft.nfft
    dt = stft.hop_samples/stft.sample_rate_hz
    valid = np.isfinite(frequency_hz) & np.isfinite(time_s)
    fi = np.rint(np.where(valid, frequency_hz, 0)/df).astype(int)
    ti = (np.rint((np.where(valid, time_s, stft.time_s[0])-stft.time_s[0])/dt)
          .astype(int)) if move_time else np.broadcast_to(np.arange(power.shape[1]), power.shape)
    valid &= (fi >= 0) & (fi < power.shape[0]) & (ti >= 0) & (ti < power.shape[1])
    valid &= np.abs(time_s-stft.time_s[None, :]) <= (
        stft.window_length_samples/(2*stft.sample_rate_hz))
    result = np.zeros_like(power)
    np.add.at(result, (fi[valid], ti[valid]), power[valid])
    total = float(power.sum())
    return np.sqrt(result), float(result.sum()/total) if total else 0.


def chirplet_bank(record: SignalRecord, profile: AnalysisProfile,
                  ) -> tuple[FloatArray, FloatArray]:
    """Local quadratic-phase matched bank; f(t_center)=f0, slope in Hz/s.

    Search uses a copy of each window multiplied by its complex analysis kernel.
    It never returns a modified waveform. No sequential subtraction or tracking.
    """
    frames = raw_frames(record, profile)
    n, fs = profile.window_length_samples, record.sample_rate_hz
    tau = (np.arange(n)-n/2)/fs
    h = .5-.5*np.cos(2*np.pi*np.arange(n)/n)
    best = np.zeros((profile.nfft//2+1, len(frames)))
    rate = np.full_like(best, np.nan)
    for chirp in CHIRP_RATES:
        kernel = h*np.exp(-1j*np.pi*chirp*tau**2)
        amplitude = np.abs(np.fft.fft(frames*kernel, n=profile.nfft, axis=1)
                           [:, :profile.nfft//2+1]).T/h.sum()
        better = amplitude > best
        rate[better] = chirp
        np.maximum(best, amplitude, out=best)
    return best, rate


def estimate(record: SignalRecord, profile: AnalysisProfile, method: Method) -> Observation:
    """Complete frontend cost, including STFT reference axes and peak extraction."""
    if method not in METHODS:
        raise ValueError('Unregistered representation')
    stft = stft_input(record, profile)
    rate_grid: FloatArray | None = None
    retained = 1.
    if method == 'R0':
        amplitude = np.abs(stft.spectrum)
        candidate_input = stft
    elif method in ('R1', 'R2'):
        f, t, power = reassignment_coordinates(record, profile, stft)
        amplitude, retained = squeeze_energy(f, t, power, stft, move_time=method == 'R1')
        candidate_input = replace(stft, spectrum=amplitude.astype(np.complex128))
    else:
        amplitude, rate_grid = chirplet_bank(record, profile)
        candidate_input = replace(stft, spectrum=amplitude.astype(np.complex128))
    candidates = extract_global_path_candidates(candidate_input,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz, config=GlobalPathConfig(top_k=K))
    shape = (len(stft.time_s), K)
    frequency = np.full(shape, np.nan)
    discrete = np.full(shape, np.nan)
    rates = np.full(shape, np.nan)
    evidence = np.full(shape, np.nan)
    flags = np.full(shape, 'NO_ESTIMATE', dtype='<U40')
    for i, frame in enumerate(candidates.candidates_by_frame):
        for j, candidate in enumerate(frame):
            if candidate.peak_amplitude <= 0:
                continue
            frequency[i, j] = candidate.transition_frequency_hz
            discrete[i, j] = candidate.discrete_frequency_hz
            evidence[i, j] = candidate.peak_to_background_db
            flags[i, j] = 'HYPOTHESIS_UNCALIBRATED'
            if rate_grid is not None:
                rates[i, j] = rate_grid[candidate.discrete_bin_index, i]
                if abs(rates[i, j]) == CHIRP_RATES[-1]:
                    flags[i, j] = 'CHIRP_BANK_BOUNDARY'
    residual = np.full(len(stft.time_s), np.nan)
    if method == 'R3':
        n = profile.window_length_samples
        tau = (np.arange(n)-n/2)/record.sample_rate_hz
        h = .5-.5*np.cos(2*np.pi*np.arange(n)/n)
        for i, x in enumerate(raw_frames(record, profile)):
            if not np.isfinite(frequency[i, 0]):
                continue
            phase = 2*np.pi*(frequency[i, 0]*tau+.5*rates[i, 0]*tau**2)
            design = np.column_stack((np.cos(phase), np.sin(phase)))
            coefficients = np.linalg.lstsq(design*np.sqrt(h[:, None]), x*np.sqrt(h),
                                           rcond=None)[0]
            residual[i] = float(np.sum(h*(x-design@coefficients)**2)/np.sum(h*x**2))
    return Observation(method, stft.time_s, stft.frequency_hz, frequency, discrete, rates,
                       evidence, flags, amplitude, residual, retained)
