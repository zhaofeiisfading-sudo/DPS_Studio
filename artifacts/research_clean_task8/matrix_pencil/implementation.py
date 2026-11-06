"""Rank-five real subspace shift estimator (LS-ESPRIT / matrix-pencil family).

No claim of TLS, guaranteed superresolution or subcycle identifiability. Two
positive poles are fitted in the original real domain; stronger amplitude wins.
"""
from __future__ import annotations

import numpy as np

from ..common import FMAX, FMIN, Context, Estimate, Float, finish, projection

PARAMETERS = dict(window=96, hankel_columns=32, rank=5, max_positive_poles=2,
                  minimum_radius=.80, maximum_radius=1.20, selection="strongest fitted amplitude",
                  chirp_model=False, dc_pole="explicit rank-five constant nuisance",
                  method="LS subspace shift, not TLS")


def poles(y: Float, fs: float) -> tuple[Float, Float, Float]:
    y = y-np.mean(y)
    hankel = np.lib.stride_tricks.sliding_window_view(y, 32)
    u, singular, _ = np.linalg.svd(hankel, full_matrices=False)
    # Mean subtraction adds a constant to the four complex exponential poles.
    # Keep its fifth rank; discard its zero-angle root at the frequency gate.
    sub = u[:, :5]
    rotation = np.linalg.lstsq(sub[:-1], sub[1:], rcond=1e-10)[0]
    z = np.linalg.eigvals(rotation)
    frequency = np.angle(z)*fs/(2*np.pi)
    radius = abs(z)
    keep = ((frequency >= FMIN) & (frequency <= FMAX) & (radius >= .80) & (radius <= 1.20))
    f = np.asarray(frequency[keep], dtype=float)
    return f, np.asarray(radius[keep], dtype=float), np.asarray(singular, dtype=float)


def run(context: Context) -> Estimate:
    n = len(context.centers)
    f, secondary = np.full(n, np.nan), np.full(n, np.nan)
    r2, cond = np.full(n, np.nan), np.full(n, np.inf)
    pole_radius, ratio = np.full(n, np.nan), np.full(n, np.nan)
    for i, center in enumerate(context.centers):
        if context.onset is None or center < context.onset:
            continue
        tau, y = context.segment(int(center), 96)
        if len(y) < 64:
            continue
        freq, radius, singular = poles(y, context.fs)
        ratio[i] = float(singular[4]/max(singular[5], 1e-300))
        if not len(freq):
            continue
        design = np.column_stack([part for fr in freq
                                  for part in (np.cos(2*np.pi*fr*tau),
                                               np.sin(2*np.pi*fr*tau))]+[np.ones(len(y))])
        coeff = np.linalg.lstsq(design, y, rcond=1e-10)[0]
        amps = np.sqrt(coeff[:-1:2]**2+coeff[1:-1:2]**2)
        order = np.argsort(amps)[::-1]
        f[i], pole_radius[i] = freq[order[0]], radius[order[0]]
        if len(freq) > 1:
            secondary[i] = freq[order[1]]
        _, residual, cond[i] = projection(y, 2*np.pi*f[i]*tau)
        r2[i] = 1-float(residual@residual)/max(float(np.sum((y-y.mean())**2)), 1e-300)
    return finish(context, f, r2=r2, condition=cond,
                  extra={"secondary_frequency_hz": secondary, "pole_radius": pole_radius,
                         "singular_gap_rank5": ratio})
