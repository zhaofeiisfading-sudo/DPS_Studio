"""Raw-real variable projection with analytic objective gradient and multistart.

Frequency and chirp are nonlinear; cos, sin and a constant are eliminated by
SVD least squares. Searching frequency invalidates a naive fixed-design F test.
No finite-sample unbiasedness or uncalibrated p value is claimed.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]

from ..common import (FMAX, FMIN, Context, Estimate, Float, candidate_seeds,
                      finish, local_fft, projection)

PARAMETERS = dict(window=384, nonlinear_parameters="frequency and linear chirp",
                  linear_parameters="cos, sin, constant", starts=3,
                  maxiter=45, chirp_bound_hz_per_s=8e16, truncate_at_event=True,
                  statistical_test="heuristic R2; searched-frequency F pvalue prohibited")


def objective(q: Float, tau: Float, y: Float) -> tuple[float, Float]:
    phase = 2*np.pi*(q[0]*1e9*tau+.5*q[1]*1e17*tau**2)
    coeff, residual, _ = projection(y, phase)
    dy = -coeff[0]*np.sin(phase)+coeff[1]*np.cos(phase)
    basis = 2*np.pi*np.column_stack((1e9*tau, .5e17*tau**2))
    scale = max(float(np.sum((y-np.mean(y))**2)), 1e-30)
    gradient = -2*basis.T@(residual*dy)/scale
    return float(residual@residual)/scale, np.asarray(gradient)


def fit(tau: Float, y: Float, seeds: list[tuple[float, float]],
        maxiter: int = 45) -> tuple[float, float, float, float, int, bool]:
    best = None
    evaluations = 0
    for freq, rate in seeds:
        init = np.array([np.clip(freq/1e9, FMIN/1e9, FMAX/1e9),
                         np.clip(rate/1e17, -.8, .8)])
        result = minimize(objective, init, args=(tau, y), jac=True, method="L-BFGS-B",
                          bounds=[(FMIN/1e9, FMAX/1e9), (-.8, .8)],
                          options={"maxiter": maxiter, "ftol": 1e-10, "gtol": 1e-6,
                                   "maxls": 15})
        evaluations += int(result.nfev)
        if best is None or result.fun < best.fun:
            best = result
    assert best is not None
    freq, rate = float(best.x[0]*1e9), float(best.x[1]*1e17)
    _, _, condition = projection(y, 2*np.pi*(freq*tau+.5*rate*tau**2))
    return freq, rate, 1-float(best.fun), condition, evaluations, bool(best.success)


def run(context: Context) -> Estimate:
    count = len(context.centers)
    f, a, r2 = np.full(count, np.nan), np.zeros(count), np.full(count, np.nan)
    condition, evaluations = np.full(count, np.inf), np.zeros(count)
    converged = np.zeros(count)
    for i, center in enumerate(context.centers):
        if context.onset is None or center < context.onset:
            continue
        tau, y = context.segment(int(center), 384)
        if len(y) < 48:
            continue
        coarse_f, coarse_a, _ = local_fft(y, context.fs, np.linspace(-8e16, 8e16, 9))
        midpoint = float((tau[0]+tau[-1])/2)
        starts = [(coarse_f-coarse_a*midpoint, coarse_a)]
        starts += [(freq, 0.) for freq in candidate_seeds(context, i, 2)]
        f[i], a[i], r2[i], condition[i], evaluations[i], ok = fit(tau, y, starts)
        converged[i] = float(ok)
    return finish(context, f, chirp=a, r2=r2, condition=condition,
                  details={"total_function_evaluations": int(evaluations.sum())},
                  extra={"evaluations": evaluations, "optimizer_converged": converged})
