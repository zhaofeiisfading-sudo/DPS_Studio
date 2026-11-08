"""Unchanged formal Hann 512/384/4096, original 0.05-6 GHz band."""
from __future__ import annotations

import numpy as np

from ..common import Context, Estimate, finish, strongest

PARAMETERS = dict(window=512, overlap=384, hop=128, nfft=4096,
                  minimum_frequency_hz=50e6, maximum_frequency_hz=6e9,
                  window_name="hann", boundary=None, padded=False, detrend=False)


def run(context: Context) -> Estimate:
    _, f, discrete, _ = strongest(context.signal, 512, 50e6, 6e9)
    result = finish(context, f[context.seed_indices], mask_before_onset=False,
                    details={"baseline": "unchanged formal API; no event gate"},
                    extra={"discrete_hz": discrete[context.seed_indices]})
    # A baseline event estimate is threshold crossing on window-centered power.
    energy = np.max(context.raw_spectrum[context.band], axis=0)**2
    prefix = max(3, int(.1*len(energy)))
    threshold = max(float(np.median(energy[:prefix]))*8, 1e-300)
    high = np.flatnonzero(energy > threshold)
    result.onset_s = float(context.seed_time[high[0]]) if len(high) else None
    return result
