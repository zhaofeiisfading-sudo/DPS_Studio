"""Local chirp-bank Fourier concentration directly on real raw windows.

This is an asymptotic frequency projection, not an exact likelihood or a
causal analytic-signal implementation of the attachment's CB-LCMLE.
"""
from __future__ import annotations

import numpy as np

from ..common import Context, Estimate, finish, local_fft

PARAMETERS = dict(window=512, nfft=4096, chirp_min_hz_per_s=-8e16,
                  chirp_max_hz_per_s=8e16, chirp_count=17, truncate_at_event=True,
                  analytic_transform=False, slope_center_transport=True)


def run(context: Context) -> Estimate:
    f = np.full(len(context.centers), np.nan)
    a = np.zeros(len(f))
    rates = np.linspace(-8e16, 8e16, 17)
    for i, center in enumerate(context.centers):
        if context.onset is None or center < context.onset:
            continue
        tau, y = context.segment(int(center), 512)
        if len(y) < 48:
            continue
        freq, rate, _ = local_fft(y, context.fs, rates)
        midpoint = float((tau[0]+tau[-1])/2)
        f[i], a[i] = freq-rate*midpoint, rate
    return finish(context, f, chirp=a)
