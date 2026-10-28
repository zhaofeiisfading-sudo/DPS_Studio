"""Oversampled analog-domain TASK007 experiments; all settings are synthetic."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, freqs  # type: ignore[import-untyped]

FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]


@dataclass(frozen=True)
class Acquisition:
    sample_rate_hz: float
    bandwidth_hz: float
    order: int
    snr_before_attenuation_db: float
    bits: int
    full_scale_v: float
    reference_oversampling: int
    response: str = "butterworth"
    count: int = 2048

    def __post_init__(self) -> None:
        if not all(np.isfinite([self.sample_rate_hz, self.bandwidth_hz,
                                self.snr_before_attenuation_db, self.full_scale_v])):
            raise ValueError("Finite acquisition values required")
        if min(self.sample_rate_hz, self.bandwidth_hz, self.full_scale_v) <= 0:
            raise ValueError("Rate, bandwidth and full-scale must be positive")
        if self.order not in (1, 4) or self.response not in ("butterworth", "zero"):
            raise ValueError("Unregistered response")
        if not 2 <= self.bits <= 24 or self.reference_oversampling < 4 or self.count < 256:
            raise ValueError("Invalid quantizer or reference grid")


@dataclass(frozen=True)
class SyntheticRecord:
    time_s: FloatArray
    voltage_v: FloatArray
    noiseless_sampled_v: FloatArray
    truth_hz: FloatArray
    competitor_hz: FloatArray
    clipped_fraction: float
    noise_sigma_v: float
    reference_rate_hz: float
    phase_rad: float
    target_present: bool


def transfer(frequency_hz: FloatArray, acquisition: Acquisition) -> ComplexArray:
    if acquisition.response == "zero":
        return np.zeros(frequency_hz.shape, dtype=np.complex128)
    numerator, denominator = butter(acquisition.order, 1., analog=True)
    _, response = freqs(numerator, denominator, worN=frequency_hz / acquisition.bandwidth_hz)
    return np.asarray(response, dtype=np.complex128)


def simulate(acquisition: Acquisition, *, frequency_hz: float, chirp_hz_per_s: float,
             seed: int, competitor_ratio: float = 0., target_present: bool = True,
             colored_noise: bool = False) -> SyntheticRecord:
    """Continuous phase -> analog complex H -> analog output noise -> sample -> ADC.

    An analytic H(jw) acts on a padded high-rate grid; central crop suppresses
    circular convolution transients. The synthetic output-noise spectrum is flat
    up to ADC Nyquist (or colored AR-like for a stress test), BEFORE decimation.
    This is not an instrument calibration. Quantization is never reversed.
    """
    rng = np.random.default_rng(seed)
    fs = acquisition.sample_rate_hz
    oversampling = acquisition.reference_oversampling
    rate = fs * oversampling
    guard = int(np.ceil(32 * fs / acquisition.bandwidth_hz))
    total = (acquisition.count + 2 * guard) * oversampling
    t = (np.arange(total) / oversampling - guard) / fs
    center = acquisition.count / (2 * fs)
    truth_ref = frequency_hz + chirp_hz_per_s * (t - center)
    if np.max(abs(truth_ref)) >= .4 * rate:
        raise ValueError("Reference grid cannot resolve continuous input; increase oversampling")
    phase0 = float(rng.uniform(-np.pi, np.pi))
    phase = 2 * np.pi * (frequency_hz * t + .5 * chirp_hz_per_s * (t - center)**2)
    signal = .2 * np.cos(phase + phase0) * target_present
    other = .65 * acquisition.bandwidth_hz
    signal += .2 * competitor_ratio * np.cos(2 * np.pi * other * t + .4)
    axis = np.fft.rfftfreq(total, 1 / rate)
    filtered = np.fft.irfft(np.fft.rfft(signal) * transfer(axis, acquisition), n=total)
    sigma = .2 / np.sqrt(2) * 10**(-acquisition.snr_before_attenuation_db / 20)
    noise = rng.normal(0, sigma * np.sqrt(oversampling), total)
    noise_response = np.asarray(axis <= fs / 2, dtype=float)
    if colored_noise:
        noise_response /= np.sqrt(1 + (axis / (.08 * fs))**2)
        noise_response *= np.sqrt(np.count_nonzero(axis <= fs / 2)
                                  / np.sum(noise_response**2))
    analog_noise = np.fft.irfft(np.fft.rfft(noise) * noise_response, n=total)
    indices = (guard + np.arange(acquisition.count)) * oversampling
    sampled = (filtered + analog_noise)[indices]
    step = 2 * acquisition.full_scale_v / 2**acquisition.bits
    clipped = float(np.mean((sampled < -acquisition.full_scale_v)
                            | (sampled > acquisition.full_scale_v - step)))
    digital = np.clip(np.round(sampled / step), -2**(acquisition.bits - 1),
                      2**(acquisition.bits - 1) - 1) * step
    return SyntheticRecord(np.arange(acquisition.count) / fs, digital, filtered[indices],
                           truth_ref[indices], np.full(acquisition.count, other), clipped,
                           sigma, rate, phase0, target_present)


def regularized_inverse_gain(response: ComplexArray, regularization: float) -> ComplexArray:
    """Diagnostic inverse only; zero-response bins stay zero, not reconstructed."""
    if not np.isfinite(regularization) or regularization <= 0:
        raise ValueError("Strictly positive regularization required")
    return np.asarray(np.conj(response) / (abs(response)**2 + regularization))
