"""Minimal truncation ablation; no whitening, adaptive tracking or smoothing."""
from __future__ import annotations

import numpy as np

from ..common import Context, Estimate, finish, local_fft

PARAMETERS = dict(window=256, hop=128, nfft=4096, truncate_at_raw_energy_change=True,
                  minimum_frequency_hz=5e6, maximum_frequency_hz=8e9,
                  preprocessing="local mean removal only; no voltage resampling")


def run(context: Context) -> Estimate:
    f = np.full(len(context.centers), np.nan)
    for i, center in enumerate(context.centers):
        if context.onset is None or center < context.onset:
            continue
        _, y = context.segment(int(center), 256)
        if len(y) >= 32:
            f[i] = local_fft(y, context.fs)[0]
    return finish(context, f)
