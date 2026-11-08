"""Deterministic piecewise-linear frequency forward inversion, per coherent slab.

Analytic integrated hat basis; VarPro phase/amplitude/DC; L-BFGS with analytic
gradient. Slabs reset phase, avoiding an assumed record-long speckle coherence.
This is regularized least squares, not calibrated Bayesian posterior inference.
No unknown receiver transfer or noise covariance is invented; no Laplace band.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]

from ..common import FMAX, FMIN, Context, Estimate, Float, finish, projection

PARAMETERS = dict(slab_samples=2048, frequency_knots=9, maxiter=100,
                  regularization=.0001, phase_reset="each slab",
                  envelope="constant cos/sin coefficients and offset per slab",
                  initial_frequency="linear evaluation of strongest STFT frequency model",
                  receiver_transfer="unknown, omitted; reported model mismatch risk",
                  uncertainty="not calibrated; no posterior intervals reported")


def integrated_basis(n: int, fs: float, knots: int = 9) -> tuple[Float, Float, Float]:
    t = np.arange(n)/fs
    nodes = np.linspace(0, t[-1], knots)
    hats = np.column_stack([np.interp(t, nodes, np.eye(knots)[j]) for j in range(knots)])
    # Exact continuous integral of the piecewise linear hat basis. Interval
    # endpoints include knots even when a knot lies between raw sample times.
    basis = np.zeros((n, knots))
    for j in range(knots-1):
        width = nodes[j+1]-nodes[j]
        elapsed = np.clip(t-nodes[j], 0., width)
        basis[:, j] += elapsed-elapsed**2/(2*width)
        basis[:, j+1] += elapsed**2/(2*width)
    return np.asarray(nodes), np.asarray(hats), np.asarray(2*np.pi*1e9*basis)


def objective(q: Float, y: Float, phase_basis: Float, penalty: float = .0001
              ) -> tuple[float, Float]:
    phase = phase_basis@q
    coeff, residual, _ = projection(y, phase)
    scale = max(float(np.sum((y-np.mean(y))**2)), 1e-30)
    dy = -coeff[0]*np.sin(phase)+coeff[1]*np.cos(phase)
    second = np.diff(q, n=2)
    grad = -2*phase_basis.T@(residual*dy)/scale
    regularizer = np.zeros(len(q))
    regularizer[:-2] += second
    regularizer[1:-1] -= 2*second
    regularizer[2:] += second
    grad += 2*penalty*regularizer
    return float(residual@residual)/scale+penalty*float(second@second), np.asarray(grad)


def run(context: Context) -> Estimate:
    f = np.full(len(context.centers), np.nan)
    slabs = []
    if context.onset is None:
        return finish(context, f, details={"reason": "NO_EVENT"})
    n = len(context.signal.time_s)
    for start in range(context.onset, n, 2048):
        end = min(n, start+2048)
        if end-start < 64:
            slabs.append(dict(start=start, end=end, reason="TAIL_TOO_SHORT"))
            continue
        nodes, hats, basis = integrated_basis(end-start, context.fs)
        indices = np.arange(start, end, dtype=np.int64)
        coarse = context.initializer(indices)
        q = np.interp(nodes, np.arange(end-start)/context.fs, coarse)/1e9
        y = np.asarray(context.signal.voltage_v[start:end])
        initial, _ = objective(q, y, basis)
        result = minimize(objective, q, args=(y, basis), jac=True, method="L-BFGS-B",
                          bounds=[(FMIN/1e9, FMAX/1e9)]*len(q),
                          options={"maxiter": 100, "ftol": 1e-9, "maxls": 15})
        phase = basis@result.x
        _, residual, condition = projection(y, phase)
        r2 = 1-float(residual@residual)/max(float(np.sum((y-y.mean())**2)), 1e-300)
        freq = hats@result.x*1e9
        mask = (context.centers >= start) & (context.centers < end)
        f[mask] = freq[context.centers[mask]-start]
        slabs.append(dict(start=start, end=end, converged=bool(result.success),
                          initial_cost=initial, final_cost=float(result.fun),
                          nfev=int(result.nfev), r2=r2, condition=condition,
                          termination=str(result.message)))
    chirp = np.zeros(len(f))
    finite = np.isfinite(f)
    if sum(finite) > 2:
        chirp[finite] = np.gradient(f[finite], context.time_s[finite])
    return finish(context, f, chirp=chirp, details={"slabs": slabs})
