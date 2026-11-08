"""Waveform-only stage estimators and explicit manual-information routing.

Two opt-in variants: longer constant-frequency variable projection, and local
linear chirp projection with manual support and a slope-sign prior. All units
are SI. No truth, velocity corrections, smoothing or gap filling enters here.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import time
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize, minimize_scalar  # type: ignore[import-untyped]
from scipy.signal import find_peaks, get_window  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Context, Signal, finish, strongest

Float = NDArray[np.float64]
Int = NDArray[np.int64]
FMIN, FMAX = 5e6, 8e9
METHODS = ("stft512", "stft768", "dechirp", "varpro", "clutter_varpro",
           "clip_stft512", "clip_stft2048", "profile512", "profile2048", "bounded_chirp512",
           "current_map", "stage_map", "unobservable")


@dataclass(frozen=True)
class Annotation:
    start_s: float
    end_s: float
    stage: str
    observation: str = "good"
    persistent_clutter: bool = False


@dataclass
class Trace:
    candidate_hz: Float
    accepted_hz: Float
    chirp_hz_s: Float
    quality: NDArray[np.str_]
    r2: Float
    condition: Float
    support_samples: Int
    runtime_s: float = 0.
    details: dict[str, Any] | None = None


def grid(signal: Signal) -> Int:
    return np.arange(1024, len(signal.time_s) - 1024 + 1, 128, dtype=np.int64)


def annotation_at(plan: tuple[Annotation, ...], t: float) -> Annotation:
    for item in plan:
        if item.start_s <= t < item.end_s or t == item.end_s == plan[-1].end_s:
            return item
    raise ValueError("Manual plan does not cover query center")


def validate(plan: tuple[Annotation, ...], signal: Signal) -> None:
    if not plan or plan[0].start_s > signal.time_s[0] or plan[-1].end_s < signal.time_s[-1]:
        raise ValueError("Manual plan must cover the complete record")
    if any(p.start_s >= p.end_s for p in plan):
        raise ValueError("Empty manual interval")
    if any(a.end_s != b.start_s for a, b in zip(plan, plan[1:])):
        raise ValueError("Manual intervals must be contiguous")


def support(signal: Signal, center: int, width: int,
            item: Annotation) -> tuple[Float, Float]:
    left = max(center - width // 2,
               int(np.searchsorted(signal.time_s, item.start_s, side="left")), 0)
    right = min(center + width // 2,
                int(np.searchsorted(signal.time_s, item.end_s, side="left")),
                len(signal.time_s))
    tau = (np.arange(left, right) - center) / signal.fs
    return np.asarray(tau), np.asarray(signal.voltage_v[left:right])


def nuisance(tau: Float) -> Float:
    scale = max(float(np.ptp(tau)), 1e-30)
    return np.column_stack((np.ones(len(tau)), tau / scale))


def linear_fit(tau: Float, y: Float, frequency_hz: float,
               chirp_hz_s: float = 0.) -> tuple[Float, Float, float, float]:
    phase = 2 * np.pi * (frequency_hz * tau + .5 * chirp_hz_s * tau**2)
    null = nuisance(tau)
    design = np.column_stack((np.cos(phase), np.sin(phase), null))
    coeff, _, _, singular = np.linalg.lstsq(design, y, rcond=1e-10)
    residual = np.asarray(y - design @ coeff)
    base = y - null @ np.linalg.lstsq(null, y, rcond=1e-10)[0]
    base_energy = float(base @ base)
    r2 = 1 - float(residual @ residual) / base_energy if base_energy > 1e-24 else 0.
    condition = float(singular[0] / max(singular[-1], 1e-300))
    return np.asarray(coeff), residual, r2, condition


def chirp_objective(q: Float, tau: Float, y: Float) -> tuple[float, Float]:
    frequency, rate = q[0] * 1e9, q[1] * 1e17
    phase = 2 * np.pi * (frequency * tau + .5 * rate * tau**2)
    coeff, residual, _, _ = linear_fit(tau, y, frequency, rate)
    dy = -coeff[0] * np.sin(phase) + coeff[1] * np.cos(phase)
    basis = 2 * np.pi * np.column_stack((1e9 * tau, .5e17 * tau**2))
    null = nuisance(tau)
    base = y - null @ np.linalg.lstsq(null, y, rcond=1e-10)[0]
    scale = max(float(base @ base), 1e-30)
    return float(residual @ residual) / scale, np.asarray(-2 * basis.T @ (residual * dy) / scale)


def fft_candidates(tau: Float, y: Float, fs: float,
                   rates: Float | None = None) -> list[tuple[float, float]]:
    """Explicit DC/linear baseline projection, no analytic-signal transform."""
    null = nuisance(tau)
    residual = y - null @ np.linalg.lstsq(null, y, rcond=1e-10)[0]
    rates = np.zeros(1) if rates is None else rates
    midpoint = float((tau[0] + tau[-1]) / 2)
    centered = tau - midpoint
    atoms = residual * np.asarray(get_window("hann", len(y), fftbins=True))
    fft = np.fft.fft(atoms[None, :] * np.exp(-1j * np.pi * rates[:, None] * centered**2),
                     n=4096, axis=1)
    frequency = np.fft.fftfreq(4096, 1 / fs)
    band = np.flatnonzero((frequency >= FMIN) & (frequency <= min(FMAX, fs * .49)))
    power = abs(fft[:, band])**2
    r, _ = np.unravel_index(np.argmax(power), power.shape)
    peaks, _ = find_peaks(power[r])
    if not len(peaks):
        peaks = np.array([int(np.argmax(power[r]))])
    peaks = peaks[np.argsort(power[r, peaks])[::-1]][:2]
    seeds = []
    for peak in peaks:
        b = int(band[peak])
        logs = np.log(np.maximum(abs(fft[r, b - 1:b + 2]), 1e-300))
        denominator = logs[0] - 2 * logs[1] + logs[2]
        delta = float(np.clip(.5 * (logs[0] - logs[2]) / denominator, -.5, .5)) \
            if denominator < -1e-14 else 0.
        seeds.append((float((b + delta) * fs / 4096 - rates[r] * midpoint), float(rates[r])))
    return seeds


def tone_fit(tau: Float, y: Float, fs: float) -> tuple[float, float, float]:
    span = fs / len(y)
    best_frequency, best_cost = np.nan, np.inf
    for seed, _ in fft_candidates(tau, y, fs):
        lower, upper = max(FMIN, seed - span), min(FMAX, fs * .49, seed + span)
        if lower >= upper:
            continue

        def objective(q: float) -> float:
            return 1 - linear_fit(tau, y, q * 1e9)[2]

        result = minimize_scalar(objective, bounds=(lower / 1e9, upper / 1e9),
                                 method="bounded", options={"xatol": 1e-10, "maxiter": 60})
        if result.fun < best_cost:
            best_cost, best_frequency = float(result.fun), float(result.x * 1e9)
    return float(best_frequency), 0., float(best_cost)


def chirp_fit(tau: Float, y: Float, fs: float, stage: str) -> tuple[float, float, float]:
    lo, hi = (-.8, 0.) if stage == "decline" else (0., .8) \
        if stage in ("acceleration", "rebound") else (-.8, .8)
    rates = np.linspace(lo * 1e17, hi * 1e17, 9)
    seeds = fft_candidates(tau, y, fs, rates)
    seeds += [(seeds[0][0], 0.)]
    best_frequency, best_rate, best_cost = np.nan, 0., np.inf
    for frequency, rate in seeds:
        initial = np.array([np.clip(frequency / 1e9, FMIN / 1e9, min(FMAX, fs * .49) / 1e9),
                            np.clip(rate / 1e17, lo, hi)])
        result = minimize(chirp_objective, initial, args=(tau, y), jac=True, method="L-BFGS-B",
                          bounds=[(FMIN / 1e9, min(FMAX, fs * .49) / 1e9), (lo, hi)],
                          options={"maxiter": 40, "ftol": 1e-10, "gtol": 1e-6, "maxls": 15})
        if result.fun < best_cost:
            best_cost = float(result.fun)
            best_frequency, best_rate = float(result.x[0] * 1e9), float(result.x[1] * 1e17)
    return float(best_frequency), float(best_rate), float(best_cost)


def quality_gate(tau: Float, y: Float, f: float, rate: float) -> tuple[bool, str, float, float]:
    _, _, r2, condition = linear_fit(tau, y, f, rate)
    duration = float(np.ptp(tau))
    endpoints = f + rate * np.array([tau[0], tau[-1]])
    if not np.isfinite(f) or f <= FMIN * 1.02 or f >= FMAX * .999:
        flag = "SEARCH_BOUNDARY_UNRESOLVED"
    elif f * duration < .75 or condition > 1e4:
        flag = "LOW_FREQUENCY_UNOBSERVABLE_NOT_ZERO"
    elif float(np.min(endpoints)) < 0 or r2 < .20:
        flag = "LOW_WAVEFORM_SUPPORT"
    else:
        flag = "MODEL_SUPPORTED|IDENTITY_UNVALIDATED|MANUAL_BOUNDARY"
    return flag.startswith("MODEL_SUPPORTED"), flag, r2, condition


def empty(n: int) -> Trace:
    return Trace(np.full(n, np.nan), np.full(n, np.nan), np.zeros(n),
                 np.full(n, "UNOBSERVABLE_NOT_ZERO", dtype="U128"),
                 np.full(n, np.nan), np.full(n, np.inf), np.zeros(n, dtype=np.int64))


def local_estimate(signal: Signal, plan: tuple[Annotation, ...], name: str) -> Trace:
    validate(plan, signal)
    start = time.perf_counter()
    centers = grid(signal)
    result = empty(len(centers))
    width = 2048 if name.endswith("2048") else 512
    for i, center in enumerate(centers):
        item = annotation_at(plan, float(signal.time_s[center]))
        tau, y = support(signal, int(center), width, item)
        result.support_samples[i] = len(y)
        if len(y) < 48:
            result.quality[i] = "INSUFFICIENT_BOUNDARY_SUPPORT"
            continue
        if name.startswith("clip_stft"):
            f, rate = fft_candidates(tau, y, signal.fs)[0]
        elif name.startswith("profile"):
            f, rate, _ = tone_fit(tau, y, signal.fs)
        elif name == "bounded_chirp512":
            f, rate, _ = chirp_fit(tau, y, signal.fs, item.stage)
        else:
            raise ValueError(name)
        result.candidate_hz[i], result.chirp_hz_s[i] = f, rate
        ok, flag, r2, condition = quality_gate(tau, y, f, rate)
        result.r2[i], result.condition[i], result.quality[i] = r2, condition, flag
        if ok:
            result.accepted_hz[i] = f
    result.runtime_s = time.perf_counter() - start
    return result


def frozen_estimate(signal: Signal, name: str, context: Context | None = None) -> Trace:
    start = time.perf_counter()
    context = Context(signal) if context is None else context
    if name in ("stft512", "stft768"):
        width = int(name[4:])
        time_s, frequency, _, _ = strongest(signal, width, 50e6, min(6e9, signal.fs * .49))
        positions = (context.centers - width // 2) // 128
        if not np.allclose(time_s[positions], context.time_s, rtol=0, atol=5e-15):
            raise AssertionError("Original STFT grid mismatch")
        native = finish(context, frequency[positions], mask_before_onset=False)
    else:
        module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
        native = module.run(context)
    positions = np.searchsorted(context.centers, grid(signal))
    if not np.array_equal(context.centers[positions], grid(signal)):
        raise AssertionError("Frozen model grid mismatch")
    r2 = native.extra.get("r2", np.full(len(context.centers), np.nan))
    condition = native.extra.get("design_condition", np.full(len(context.centers), np.inf))
    rate = native.extra.get("chirp_hz_per_s", np.zeros(len(context.centers)))
    width = {"varpro": 384, "clutter_varpro": 384, "dechirp": 512,
             "stft512": 512, "stft768": 768}[name]
    return Trace(native.frequency_hz[positions], native.accepted_hz[positions], rate[positions],
                 native.flags[positions].astype("U128"), r2[positions], condition[positions],
                 np.full(len(positions), width, dtype=np.int64), time.perf_counter() - start,
                 native.details)


def recommended(item: Annotation, *, current: bool = False) -> str:
    if current:
        return "dechirp" if item.stage == "acceleration" else "unobservable" \
            if item.stage == "noise" else "stft768"
    if item.stage in ("stationary", "noise") or item.observation == "unobservable":
        return "unobservable"
    if item.persistent_clutter:
        return "clutter_varpro"
    if item.stage in ("onset", "turnaround"):
        return "clip_stft512"
    if item.stage in ("acceleration", "decline", "rebound"):
        return "bounded_chirp512"
    if item.observation == "weak" or item.stage == "weak_signal":
        return "clip_stft2048"
    if item.stage in ("plateau", "low_frequency"):
        return "profile2048"
    return "stft768"


def route(signal: Signal, plan: tuple[Annotation, ...], traces: dict[str, Trace],
          *, current: bool = False) -> Trace:
    centers = grid(signal)
    result = empty(len(centers))
    for i, center in enumerate(centers):
        name = recommended(annotation_at(plan, float(signal.time_s[center])), current=current)
        source = traces[name]
        for key in ("candidate_hz", "accepted_hz", "chirp_hz_s", "quality", "r2",
                    "condition", "support_samples"):
            getattr(result, key)[i] = getattr(source, key)[i]
    result.details = {"routing": "predefined manual annotations; no truth or winner selection",
                      "manual_input": True, "current_default_window": "768 for this comparison"}
    return result


def run_all(signal: Signal, plan: tuple[Annotation, ...]) -> dict[str, Trace]:
    context = Context(signal)
    traces = {name: frozen_estimate(signal, name, context) for name in METHODS[:5]}
    traces.update({name: local_estimate(signal, plan, name) for name in METHODS[5:10]})
    traces["unobservable"] = empty(len(grid(signal)))
    traces["current_map"] = route(signal, plan, traces, current=True)
    traces["stage_map"] = route(signal, plan, traces)
    return traces
