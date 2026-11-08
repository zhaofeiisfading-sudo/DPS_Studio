"""Matched-window control for Dechirp/VarPro: local DC + event truncation only."""
from __future__ import annotations

import numpy as np

from ..common import Context, Estimate, finish, local_fft

PARAMETERS = dict(window=512, hop=128, nfft=4096, truncate_at_raw_energy_change=True,
                  minimum_frequency_hz=5e6, maximum_frequency_hz=8e9,
                  preprocessing="explicit local mean removal; no voltage resampling")


def run(context: Context) -> Estimate:
    f = np.full(len(context.centers), np.nan)
    for i, center in enumerate(context.centers):
        if context.onset is None or center < context.onset:
            continue
        _, y = context.segment(int(center), 512)
        if len(y) >= 32:
            f[i] = local_fft(y, context.fs)[0]
    return finish(context, f)
