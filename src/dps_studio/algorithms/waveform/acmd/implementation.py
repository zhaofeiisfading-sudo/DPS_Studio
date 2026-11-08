"""Single-mode boundary-aware ACMD-inspired real-envelope experiment.

This implements a stated variant, not a reproduction of the complete VNCMD
paper: solve two penalized real envelopes, differentiate them, update the IF.
For x=u*cos(theta)+v*sin(theta), the physical phase is theta-atan2(v,u),
so its correction is (v*u'-u*v')/(2*pi*(u^2+v^2)). The sign matters.
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import solveh_banded  # type: ignore[import-untyped]

from ..common import FMAX, FMIN, Context, Estimate, Float, finish

PARAMETERS = dict(modes=1, iterations=6, envelope_bandwidth_hz=150e6,
                  ridge=1e-6, correction_limit_hz=100e6, update_damping=.7,
                  boundary="disconnect at detected onset by solving post-onset only",
                  initializer="linear evaluation of strongest STFT frequency model",
                  output="candidate; locally waveform-gated; no dropout bridging")


def envelopes(x: Float, phase: Float, alpha: float) -> tuple[Float, Float]:
    n = len(x)
    c, s = np.cos(phase), np.sin(phase)
    diag = np.full(n, 6.)
    diag[:2], diag[-2:] = [1., 5.], [5., 1.]
    off = np.full(n-1, -4.)
    off[0], off[-1] = -2., -2.
    # Interleaved [u0,v0,u1,v1,...] yields SPD bandwidth 4.
    band = np.zeros((5, 2*n))
    band[0, 0::2] = c*c+alpha*diag+1e-6
    band[0, 1::2] = s*s+alpha*diag+1e-6
    band[1, 0::2] = c*s
    band[2, :2*n-2] = alpha*np.repeat(off, 2)
    band[4, :2*n-4] = alpha
    rhs = np.empty(2*n)
    rhs[0::2], rhs[1::2] = c*x, s*x
    result = solveh_banded(band, rhs, lower=True, check_finite=False)
    return np.asarray(result[0::2]), np.asarray(result[1::2])


def correction(u: Float, v: Float, fs: float, floor: float) -> Float:
    energy = u*u+v*v
    return np.asarray((v*np.gradient(u)*fs-u*np.gradient(v)*fs)
                      /(2*np.pi*np.maximum(energy, floor)))


def run(context: Context) -> Estimate:
    out = np.full(len(context.centers), np.nan)
    if context.onset is None:
        return finish(context, out, details={"reason": "NO_EVENT"})
    start = context.onset
    indices = np.arange(start, len(context.signal.time_s), dtype=np.int64)
    x = np.asarray(context.signal.voltage_v[start:]-np.median(
        context.signal.voltage_v[:int(context.event["prefix_samples"])]))
    f = context.initializer(indices)
    alpha = (context.fs/(2*np.pi*150e6))**4
    history = []
    amplitude = np.zeros(len(x))
    for _ in range(6):
        phase = 2*np.pi*np.r_[0., np.cumsum((f[1:]+f[:-1])*.5/context.fs)]
        u, v = envelopes(x, phase, alpha)
        amplitude = np.sqrt(u*u+v*v)
        delta = correction(u, v, context.fs, context.noise**2)
        # Below-envelope points are model extrapolation; do not update from them.
        delta[amplitude < 2*context.noise] = 0.
        delta = np.clip(delta, -100e6, 100e6)
        f = np.clip(f+.7*delta, FMIN, FMAX)
        residual = x-u*np.cos(phase)-v*np.sin(phase)
        history.append(dict(rms_residual_v=float(np.sqrt(np.mean(residual**2))),
                            max_frequency_correction_hz=float(np.max(abs(delta)))))
    valid = context.centers >= start
    out[valid] = f[context.centers[valid]-start]
    amp = np.full(len(out), np.nan)
    amp[valid] = amplitude[context.centers[valid]-start]
    # Approximate local chirp for waveform evidence, same center geometry.
    chirp = np.zeros(len(out))
    if np.sum(valid) > 2:
        chirp[valid] = np.gradient(out[valid], context.time_s[valid])
    result = finish(context, out, chirp=chirp, details={"alpha": alpha, "iterations": history},
                    extra={"envelope_v": amp})
    weak = amp < 2*context.noise
    result.accepted_hz[weak] = np.nan
    result.flags[weak] = "ENVELOPE_DROPOUT|UNOBSERVABLE_NOT_ZERO"
    return result
