"""Bounded-memory STFT control experiment; estimators never receive truth.

This is a Research implementation, checked against the unchanged core API.
No interpolation, smoothing, sample deletion, or discrete fallback is applied.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.fft import rfft  # type: ignore[import-untyped]
from scipy.signal import get_window  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Signal

Float = NDArray[np.float64]
Int = NDArray[np.int64]
VELOCITY = 1550e-9 / 2
WINDOWS = (512, 768, 1024, 1536, 2048)
HOPS = (128, 64, 32, 16, 8, 1)


@dataclass(frozen=True)
class Spec:
    window: int
    hop: int
    nfft: int = 4096
    minimum_hz: float = 50e6
    maximum_hz: float = 6e9
    demean: bool = False
    label: str = "strict"

    def __post_init__(self) -> None:
        if self.window < 2 or not 0 < self.hop <= self.window or self.nfft < self.window:
            raise ValueError("Invalid window/hop/nfft")

    @property
    def name(self) -> str:
        return f"{self.label}_w{self.window}_h{self.hop}_n{self.nfft}"

    def parameters(self, fs: float) -> dict[str, Any]:
        return {**asdict(self), "name": self.name,
                "overlap_fraction": 1 - self.hop / self.window,
                "window_duration_s": self.window / fs,
                "frame_interval_s": self.hop / fs,
                "fft_grid_hz": fs / self.nfft,
                "hann_enbw_hz": 1.5 * fs / self.window,
                "hann_first_null_offset_hz": 2 * fs / self.window,
                "hann_null_to_null_width_hz": 4 * fs / self.window}


@dataclass
class Trace:
    spec: Spec
    indices: Int
    frequency_hz: Float
    discrete_hz: Float
    accepted_hz: Float
    contrast_db: Float
    peak_power_v2: Float
    r2: Float
    condition: Float
    flags: NDArray[np.str_]
    runtime_s: float


def common_centers(n: int) -> Int:
    """Exact raw sample indices valid for every window; never interpolated."""
    return np.arange(1024, n - 1024 + 1, 128, dtype=np.int64)


def support(signal: Signal, centers: Int, frequency: Float,
            onset: int | None, fs: float | None = None) -> tuple[Float, Float]:
    """Same 256-sample sin/cos/DC model and cut-at-event support for all W.

    Batched normal equations are used for support only, not frequency fitting.
    Small eigenvalues are flagged; estimates are not repaired by this check.
    """
    offset = np.arange(-128, 128)
    idx = centers[:, None] + offset
    valid = (idx >= 0) & (idx < len(signal.time_s))
    if onset is not None:
        valid &= ~((centers[:, None] >= onset) & (idx < onset))
    weight = valid.astype(float)
    y = signal.voltage_v[np.clip(idx, 0, len(signal.voltage_v) - 1)]
    fs = signal.fs if fs is None else fs
    phase = 2 * np.pi * np.nan_to_num(frequency)[:, None] * offset[None, :] / fs
    design = np.stack((np.cos(phase), np.sin(phase), np.ones_like(phase)), axis=2)
    gram = np.einsum("bki,bkj,bk->bij", design, design, weight, optimize=True)
    rhs = np.einsum("bki,bk,bk->bi", design, y, weight, optimize=True)
    values, vectors = np.linalg.eigh(gram)
    condition = np.sqrt(np.maximum(values[:, -1], 0) /
                        np.maximum(values[:, 0], 1e-300))
    transformed = np.einsum("bij,bi->bj", vectors, rhs)
    fitted_energy = np.sum(transformed**2 / np.maximum(values, 1e-100), axis=1)
    yy = np.sum(y * y * weight, axis=1)
    total = yy - np.sum(y * weight, axis=1)**2 / np.maximum(weight.sum(axis=1), 1)
    residual = np.maximum(yy - fitted_energy, 0)
    r2 = 1 - residual / np.maximum(total, 1e-300)
    r2[~np.isfinite(frequency) | (weight.sum(axis=1) < 16)] = np.nan
    return np.asarray(r2), np.asarray(condition)


def estimate(signal: Signal, spec: Spec, *, batch_frames: int = 128,
             onset: int | None = None) -> Trace:
    """Periodic Hann, spectrum scaling, unpadded centers, float64/complex128."""
    if batch_frames < 1 or len(signal.time_s) < spec.window:
        raise ValueError("Insufficient data or invalid batch size")
    start_clock = time.perf_counter()
    starts = np.arange(0, len(signal.time_s) - spec.window + 1, spec.hop, dtype=np.int64)
    centers = starts + spec.window // 2
    window = np.asarray(get_window("hann", spec.window, fftbins=True))
    fs = signal.fs
    frequency_grid = np.fft.rfftfreq(spec.nfft, d=1 / fs)
    band = np.flatnonzero((frequency_grid >= spec.minimum_hz) &
                          (frequency_grid <= spec.maximum_hz))
    if len(band) < 3:
        raise ValueError("Analysis band needs at least three FFT bins")
    arrays = [np.full(len(starts), np.nan) for _ in range(7)]
    refined, discrete, contrast, power, r2, condition, accepted = arrays
    frames = np.lib.stride_tricks.sliding_window_view(signal.voltage_v, spec.window)
    spacing = fs / spec.nfft
    for left in range(0, len(starts), batch_frames):
        right = min(left + batch_frames, len(starts))
        y = np.array(frames[starts[left:right]], copy=True)
        if spec.demean:
            y -= y.mean(axis=1, keepdims=True)
        magnitude = np.abs(rfft(y * window, n=spec.nfft, axis=1, workers=1)) / window.sum()
        local_band = magnitude[:, band]
        bins = band[np.argmax(local_band, axis=1)]
        rows = np.arange(len(bins))
        center = magnitude[rows, bins]
        local = magnitude[rows[:, None], bins[:, None] + np.array([-1, 0, 1])]
        logs = np.log(np.maximum(local, 1e-300))
        denominator = logs[:, 0] - 2 * logs[:, 1] + logs[:, 2]
        tolerance = 16 * np.finfo(float).eps * np.maximum.reduce(
            (np.ones(len(rows)), abs(logs[:, 0]), 2 * abs(logs[:, 1]), abs(logs[:, 2])))
        with np.errstate(divide="ignore", invalid="ignore"):
            delta = .5 * (logs[:, 0] - logs[:, 2]) / denominator
        values = frequency_grid[bins] + delta * spacing
        ok = ((bins > band[0]) & (bins < band[-1]) & (local > 0).all(axis=1)
              & np.isfinite(values) & (denominator < -tolerance) & (abs(delta) <= .5)
              & (values >= spec.minimum_hz) & (values <= spec.maximum_hz))
        values[~ok] = np.nan
        refined[left:right] = values
        discrete[left:right] = frequency_grid[bins]
        power[left:right] = center**2
        contrast[left:right] = 20 * np.log10(np.maximum(center, 1e-300) /
                                           np.maximum(np.median(local_band**2, axis=1),
                                                      1e-300)**.5)
        r2[left:right], condition[left:right] = support(
            signal, centers[left:right], values, onset, fs)
    good = (np.isfinite(refined) & (contrast >= 10) & (r2 >= .20) & (condition <= 1e5))
    accepted[good] = refined[good]
    flags = np.full(len(starts), "LOW_SUPPORT|IDENTITY_UNVALIDATED", dtype="U64")
    flags[good] = "SUPPORTED_HEURISTIC|IDENTITY_UNVALIDATED"
    flags[~np.isfinite(refined)] = "REFINEMENT_UNAVAILABLE|NO_FALLBACK"
    return Trace(spec, centers, refined, discrete, accepted, contrast, power,
                 r2, condition, flags, time.perf_counter() - start_clock)


def onset_threshold(trace: Trace) -> float:
    """Calibrate only on the H128 reference of this W; then freeze across H."""
    prefix = max(3, len(trace.indices) // 10)
    return max(float(np.median(trace.peak_power_v2[:prefix])) * 8, 1e-300)


def detected_onset(signal: Signal, trace: Trace, threshold: float) -> float | None:
    crossing = np.flatnonzero(trace.peak_power_v2 > threshold)
    return float(signal.time_s[trace.indices[crossing[0]]]) if len(crossing) else None


def metric(values_hz: Float, truth_hz: Float, region: NDArray[np.bool_],
           prefix: str) -> dict[str, Any]:
    target = region & np.isfinite(truth_hz)
    finite = target & np.isfinite(values_hz)
    errors = (values_hz[finite] - truth_hz[finite]) * VELOCITY
    n, m = int(target.sum()), int(finite.sum())
    return {prefix + "target_n": n, prefix + "finite_n": m,
            prefix + "sse_m2_s2": float(errors @ errors),
            prefix + "rmse_m_s": float(np.sqrt(np.mean(errors**2))) if m else None,
            prefix + "coverage": m / n if n else None,
            prefix + "failure_fraction": (n - m + int((abs(errors) > 77.5).sum())) / n
            if n else None,
            prefix + "failure_n": n - m + int((abs(errors) > 77.5).sum()),
            prefix + "failure_38p75_n": n - m + int((abs(errors) > 38.75).sum()),
            prefix + "failure_155_n": n - m + int((abs(errors) > 155).sum())}


def evaluate(signal: Signal, trace: Trace, truth: Float | None, family: str,
             truth_onset: float | None, events: list[float], threshold: float,
             raw_onset: int | None) -> dict[str, Any]:
    row: dict[str, Any] = dict(**trace.spec.parameters(signal.fs),
        frames=len(trace.indices), candidate_finite_n=int(np.isfinite(trace.frequency_hz).sum()),
        supported_finite_n=int(np.isfinite(trace.accepted_hz).sum()),
        native_supported_fraction=float(np.isfinite(trace.accepted_hz).mean()),
        runtime_s=trace.runtime_s, sample_rate_hz=signal.fs,
        retained_dense_complex_bytes=(trace.spec.nfft // 2 + 1) * len(trace.indices) * 16,
        spectral_onset_s=detected_onset(signal, trace, threshold),
        raw_energy_onset_s=float(signal.time_s[raw_onset]) if raw_onset is not None else None,
        onset_threshold_v2=threshold,
        equivalent_velocity_wavelength_m=2 * VELOCITY,
        real_accuracy="UNAVAILABLE" if truth is None else "SYNTHETIC_GT_ONLY")
    if truth is None:
        return row
    grid = common_centers(len(signal.time_s))
    positions = np.searchsorted(trace.indices, grid)
    if not np.array_equal(trace.indices[positions], grid):
        raise AssertionError("Common grid must contain exact sample indices")
    for grid_name, take in (("native", np.arange(len(trace.indices))), ("common", positions)):
        idx = trace.indices[take]
        gt = truth[idx]
        t = signal.time_s[idx]
        all_points = np.ones(len(idx), dtype=bool)
        fast = np.zeros(len(idx), dtype=bool)
        for event in events:
            fast |= abs(t - event) < 10e-9
        if family == "fast_accel" and truth_onset is not None:
            fast |= (t >= truth_onset) & (t < truth_onset + 45e-9)
        regions = {"motion": all_points, "low": gt * VELOCITY < 200, "fast": fast,
                   "onset40": (t >= truth_onset) & (t < truth_onset + 40e-9)
                   if truth_onset is not None else np.zeros(len(t), dtype=bool)}
        for state, values in (("candidate", trace.frequency_hz), ("supported", trace.accepted_hz)):
            for region_name, mask in regions.items():
                row.update(metric(values[take], gt, mask,
                                  f"{grid_name}_{state}_{region_name}_"))
        static = ~np.isfinite(gt)
        row[f"{grid_name}_static_n"] = int(static.sum())
        row[f"{grid_name}_static_supported_n"] = int(
            (static & np.isfinite(trace.accepted_hz[take])).sum())
    for name in ("spectral", "raw_energy"):
        detected = row[name + "_onset_s"]
        row[name + "_onset_error_ns"] = (detected - truth_onset) * 1e9 \
            if detected is not None and truth_onset is not None else None
        row[name + "_onset_missed"] = truth_onset is not None and detected is None
        row[name + "_false_event"] = truth_onset is None and detected is not None
    return row


def error_correlation(trace: Trace, truth: Float, family: str,
                      fs: float, onset_s: float | None) -> dict[str, Any]:
    """Residual lag correlations are descriptive; frames are never replicates."""
    idx = trace.indices
    valid = np.isfinite(trace.frequency_hz) & np.isfinite(truth[idx])
    if family == "step" and onset_s is not None:
        valid &= idx / fs > onset_s + 60e-9
    errors = (trace.frequency_hz - truth[idx]) * VELOCITY
    result: dict[str, Any] = {}
    for label, lag in (("lag1", 1), ("lag_128samples", max(1, 128 // trace.spec.hop))):
        good = valid[lag:] & valid[:-lag]
        a, b = errors[:-lag][good], errors[lag:][good]
        result[label + "_residual_correlation"] = float(np.corrcoef(a, b)[0, 1]) \
            if len(a) >= 4 and np.std(a) > 0 and np.std(b) > 0 else None
    result["window_overlap_inner_product"] = float(
        np.dot(np.hanning(trace.spec.window + 1)[:-1][trace.spec.hop:],
               np.hanning(trace.spec.window + 1)[:-1][:-trace.spec.hop]) /
        np.sum(np.hanning(trace.spec.window + 1)[:-1]**2))
    return result


def adaptive(short: Trace, long: Trace, signal: Signal,
             raw_onset: int | None) -> Trace:
    """Registered two-scale selection; no blending, interpolation, or truth.

    Switch to W512 within W2048/2 of a raw event or a >100 MHz change over
    256 raw samples in the short estimate. Dilate by 1024 raw samples.
    Missing long-support alone does not trigger a substitution.
    """
    common = np.intersect1d(short.indices, long.indices)
    si = np.searchsorted(short.indices, common)
    li = np.searchsorted(long.indices, common)
    f = short.frequency_hz[si]
    lag = 128 // short.spec.hop
    change = np.zeros(len(common), dtype=bool)
    change[lag:-lag] = abs(f[2 * lag:] - f[:-2 * lag]) > 100e6
    radius = 1024 // short.spec.hop
    use_short = np.convolve(change.astype(int), np.ones(2 * radius + 1), mode="same") > 0
    if raw_onset is not None:
        use_short |= abs(common - raw_onset) <= 1024
    def choose(a: Float, b: Float) -> Float:
        return np.where(use_short, a[si], b[li])
    spec = Spec(2048, short.spec.hop, minimum_hz=short.spec.minimum_hz,
                maximum_hz=short.spec.maximum_hz, demean=True, label="adaptive512_2048")
    flags = np.where(use_short, "SELECT_W512|IDENTITY_UNVALIDATED",
                     "SELECT_W2048|IDENTITY_UNVALIDATED")
    return Trace(spec, common, choose(short.frequency_hz, long.frequency_hz),
                 choose(short.discrete_hz, long.discrete_hz),
                 choose(short.accepted_hz, long.accepted_hz),
                 choose(short.contrast_db, long.contrast_db),
                 choose(short.peak_power_v2, long.peak_power_v2),
                 choose(short.r2, long.r2), choose(short.condition, long.condition), flags,
                 short.runtime_s + long.runtime_s)
