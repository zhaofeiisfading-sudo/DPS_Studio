"""Opt-in TASK-002 frequency-limit experiments, with no GUI/default changes.

Reuses TASK-001's acquisition model and Gaussian tone likelihood. A digital
candidate never certifies an interface, an unaliased carrier, or a velocity.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray
from scipy import stats  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import (
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import STFTResult, compute_stft
from dps_studio.research.bandwidth_task001 import (
    AnalogCase,
    FloatArray,
    NoiseModel,
    ToneSearch,
    Waveform,
    ar_transform,
    stationary_noise,
    synthesize,
)

FS = 40e9
MINIMUM_HZ = 0.05e9
WIDE_MAXIMUM_HZ = 19.5e9
FREQUENCIES_HZ = (3e9, 5e9, 6.5e9, 8e9, 10e9, 12e9, 16e9, 18e9)
METHODS = ("A_default_peak", "B_wide_peak", "C_wide_gate", "D_ar1_glrt", "A_default_gate")
GATED = ("C_wide_gate", "D_ar1_glrt", "A_default_gate")


@dataclass(frozen=True)
class Window:
    name: str
    n: int
    overlap: int
    hop: int
    nfft: int

    def __post_init__(self) -> None:
        if (self.n < 32 or not 0 <= self.overlap < self.n
                or self.hop != self.n - self.overlap or self.nfft < self.n):
            raise ValueError("Invalid window/overlap/hop/nfft")


WINDOWS = (
    Window("short", 128, 0, 128, 1024),
    Window("balanced", 768, 640, 128, 4096),
    Window("high_time", 512, 384, 128, 4096),
)


@dataclass(frozen=True)
class Acceptance:
    tolerance_hz: float = 50e6
    correct_target: float = 0.95
    false_accept_target: float = 0.01
    family_alpha: float = 0.05
    # 5 conditions * 3 windows * 3 gated methods * 8 frequencies
    # + 2 noise populations * 3 windows * 3 gated null tests.
    family_size: int = 378

    def __post_init__(self) -> None:
        if (not math.isfinite(self.tolerance_hz) or self.tolerance_hz <= 0
                or not 0 < self.correct_target < 1
                or not 0 < self.false_accept_target < 1
                or not 0 < self.family_alpha < 1 or self.family_size < 1):
            raise ValueError("Invalid acceptance specification")

    @property
    def tail(self) -> float:
        return self.family_alpha / self.family_size


def binomial_bounds(k: int, n: int, tail: float = 0.025) -> tuple[float, float]:
    """Clopper-Pearson bounds; each tail has error probability ``tail``.

    Formal acceptance uses one relevant tail per test and Bonferroni across
    the frozen family; displayed ordinary intervals use tail=0.025.
    """
    if not 0 <= k <= n or n < 1 or not 0 < tail < 0.5:
        raise ValueError("Invalid binomial count/tail")
    lower = 0. if k == 0 else float(stats.beta.ppf(tail, k, n - k + 1))
    upper = 1. if k == n else float(stats.beta.ppf(1 - tail, k + 1, n - k))
    return lower, upper


def reliable_boundary(
    frequencies: list[float], correct: list[int], trials: list[int],
    null_accepted: int, null_trials: int, rule: Acceptance,
) -> float | None:
    """Highest passing prefix of tested points, starting at the lowest point.

    No interpolation across untested frequencies; no claim above the last
    passing point. Zero denotes neither a measured frequency nor a velocity.
    """
    if (not frequencies or len(frequencies) != len(correct) or len(correct) != len(trials)
            or any(not math.isfinite(f) or f <= 0 for f in frequencies)
            or any(a >= b for a, b in zip(frequencies, frequencies[1:]))):
        raise ValueError("Need aligned counts and strictly increasing frequencies")
    if binomial_bounds(null_accepted, null_trials, rule.tail)[1] > rule.false_accept_target:
        return None
    result = None
    for f, k, n in zip(frequencies, correct, trials, strict=True):
        if binomial_bounds(k, n, rule.tail)[0] < rule.correct_target:
            break
        result = f
    return result


def acquire(case: AnalogCase, seed: int, *, ideal: bool = False) -> Waveform:
    """Exact ideal receiver, or TASK-001 continuous Butterworth before ADC.

    Downstream OU/aperture noise precedes quantization. No filtering of an
    already sampled measured waveform is used to simulate an analog receiver.
    """
    if not ideal:
        return synthesize(case, seed)
    if (case.n < 32 or case.sample_rate_hz <= 0 or case.amplitude_v < 0
            or case.adc_step_v < 0 or not 0 <= case.noise_rho < 1):
        raise ValueError("Invalid ideal acquisition")
    rng = np.random.default_rng(seed)
    t = (np.arange(case.n) - (case.n - 1) / 2) / case.sample_rate_hz
    phase = 2 * np.pi * (case.frequency_hz * t + .5 * case.chirp_hz_per_s * t**2)
    clean = case.amplitude_v * np.cos(phase + rng.uniform(-np.pi, np.pi))
    if case.competitor_hz:
        clean += case.competitor_amplitude_v * np.cos(
            2 * np.pi * case.competitor_hz * t + rng.uniform(-np.pi, np.pi)
        )
    if case.response_zero:
        clean[:] = 0
    y = clean + stationary_noise(rng, case.n, case.noise_rms_v, case.noise_rho)
    if case.adc_step_v:
        y = case.adc_step_v * np.rint(y / case.adc_step_v)
    from dps_studio.research.bandwidth_task001 import alias_frequency

    snr = (10 * math.log10(float(np.mean(clean**2)) / case.noise_rms_v**2)
           if np.any(clean) and case.noise_rms_v else math.nan)
    return Waveform(y, clean, case.frequency_hz,
                    alias_frequency(case.frequency_hz, case.sample_rate_hz), snr)


class WideToneSearch(ToneSearch):
    """TASK-001 likelihood, with explicit sample rate and configurable band.

    Only the initialization/grid contract changes. fit(), _linear(), precision
    transform, scalar refinement, and Fisher curvature are inherited unchanged.
    """

    def __init__(
        self, n: int, fs: float, model: NoiseModel, *,
        minimum_hz: float = MINIMUM_HZ, maximum_hz: float = WIDE_MAXIMUM_HZ,
    ) -> None:
        if (n < 32 or not math.isfinite(fs) or fs <= 0
                or not 0 < minimum_hz < maximum_hz < fs / 2):
            raise ValueError("Tone search requires a positive band strictly below Nyquist")
        self.n, self.fs, self.model = n, fs, model
        self.t = (np.arange(n, dtype=float) - (n - 1) / 2) / fs
        self.grid = np.fft.rfftfreq(4 * n, 1 / fs)
        self.grid = self.grid[(self.grid >= minimum_hz) & (self.grid <= maximum_hz)]
        if len(self.grid) < 3:
            raise ValueError("Search band contains too few grid points")
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


@dataclass(frozen=True)
class SpectralFrame:
    default_peak_hz: float
    wide_peak_hz: float
    default_refined_hz: float
    wide_refined_hz: float
    default_score_db: float
    wide_score_db: float
    wide_background_db: float
    wide_competitor_db: float


def frame_stft(y: FloatArray, fs: float, window: Window) -> STFTResult:
    record = SignalRecord(time_s=np.arange(len(y), dtype=float) / fs, voltage_v=y)
    return compute_stft(record, window_length_samples=window.n,
                        overlap_samples=window.overlap, nfft=window.nfft)


def spectral_frame(stft: STFTResult) -> SpectralFrame:
    if len(stft.time_s) != 1:
        raise ValueError("Independent-waveform benchmark requires exactly one STFT frame")
    values: list[tuple[float, float, float, float, float]] = []
    for maximum in (6e9, WIDE_MAXIMUM_HZ):
        peak = extract_peak_ridge(stft, minimum_frequency_hz=MINIMUM_HZ,
                                  maximum_frequency_hz=maximum)
        refined = refine_peak_ridge_subbin(stft, peak)
        quality = assess_ridge_spectral_quality(
            stft, refined, background_exclusion_half_width_hz=2 * stft.sample_rate_hz
            / stft.window_length_samples, minimum_background_bin_count=8,
        )
        bg, competitor = (float(quality.peak_to_background_db[0]),
                          float(quality.peak_to_competitor_db[0]))
        f = float(refined.refined_frequency_hz[0])
        score = bg if competitor >= 3 and math.isfinite(bg) and math.isfinite(f) else -math.inf
        values.append((float(peak.frequency_hz[0]), f, score, bg, competitor))
    narrow, wide = values
    return SpectralFrame(narrow[0], wide[0], narrow[1], wide[1], narrow[2], wide[2],
                         wide[3], wide[4])


def noise_psd_v2_per_hz(f: FloatArray, fs: float, rms: float, rho: float) -> FloatArray:
    """One-sided sampled OU/aperture PSD (interior frequencies); not measured H(f)."""
    return np.asarray(2 * rms**2 * (1 - rho**2) / fs
                      / (1 + rho**2 - 2 * rho * np.cos(2 * np.pi * f / fs)),
                      dtype=np.float64)


BoolArray = NDArray[np.bool_]
