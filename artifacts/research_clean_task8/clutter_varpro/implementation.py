"""Coherent quiet-prefix nuisance prediction followed by real VarPro.

Not PSD whitening: fit the phase, amplitude and frequency of ONE stationary
pre-existing tone, predict its voltage, and subtract in an in-memory copy.
Its persistence/coherence is an assumption. A moving target already in the
prefix can be removed; drifting/evolving clutter leaves a residual. This
algorithm never certifies target identity or writes a processed raw file.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar  # type: ignore[import-untyped]

from ..common import Context, Estimate, Float, Signal, projection
from ..varpro.implementation import run as real_varpro

PARAMETERS = dict(prefix_fraction=.1, prefix_cap_samples=4096, nuisance_tones=1,
                  minimum_nuisance_hz=50e6, minimum_prefix_r2=.45,
                  predictor="stationary phase-coherent sine/cosine and offset",
                  subtraction="in-memory only; raw remains unchanged",
                  target_estimator="exact same real VarPro configuration",
                  assumptions="quiet prefix and persistent phase-coherent nuisance",
                  independent_new_context=True)


def prefix_tone(signal: Signal) -> tuple[Float, dict[str, float | str]]:
    n = max(128, min(len(signal.time_s)//10, 4096))
    tau = signal.time_s-signal.time_s[0]
    y = np.asarray(signal.voltage_v[:n])
    fft = np.fft.rfft((y-y.mean())*np.hanning(n), n=16384)
    grid = np.fft.rfftfreq(16384, 1/signal.fs)
    band = (grid >= 50e6) & (grid <= 8e9)
    candidates = np.flatnonzero(band)
    f0 = float(grid[candidates[np.argmax(abs(fft[band]))]])
    span = signal.fs/n
    total = max(float(np.sum((y-y.mean())**2)), 1e-30)

    def cost(q: float) -> float:
        _, res, _ = projection(y, 2*np.pi*q*1e9*tau[:n])
        return float(res@res)/total

    result = minimize_scalar(cost, bounds=(max(50e6, f0-span)/1e9, min(8e9, f0+span)/1e9),
                             method="bounded", options={"xatol": 1e-10, "maxiter": 70})
    frequency = float(result.x*1e9)
    coeff, _, _ = projection(y, 2*np.pi*frequency*tau[:n])
    r2 = 1-float(result.fun)
    if r2 < .45:
        return np.zeros(len(tau)), {"reason": "NO_STRONG_COHERENT_PREFIX_TONE", "prefix_r2": r2}
    prediction = coeff[0]*np.cos(2*np.pi*frequency*tau)+coeff[1]*np.sin(2*np.pi*frequency*tau)
    return np.asarray(prediction), {"reason": "SUBTRACTED_PREDICTED_NUISANCE_UNVERIFIED",
                                    "prefix_r2": r2, "frequency_hz": frequency,
                                    "amplitude_v": float(np.hypot(coeff[0], coeff[1]))}


def run(context: Context) -> Estimate:
    prediction, meta = prefix_tone(context.signal)
    residual = Signal(np.array(context.signal.time_s),
                       np.asarray(context.signal.voltage_v-prediction), context.signal.name)
    new_context = Context(residual)
    result = real_varpro(new_context)
    result.details["nuisance"] = meta
    result.details["residual_event"] = new_context.event
    result.details["quality_support_domain"] = "original minus predicted nuisance; conditional on prefix assumption"
    result.extra["predicted_nuisance_at_centers_v"] = prediction[context.centers]
    finite = np.isfinite(result.accepted_hz)
    result.flags[finite] = "WAVEFORM_SUPPORTED|IDENTITY_UNVALIDATED|PREFIX_NUISANCE_ASSUMPTION"
    return result
