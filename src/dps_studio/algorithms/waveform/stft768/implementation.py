"""Unchanged formal Hann 768/640/4096, original 0.05-6 GHz band."""
from __future__ import annotations

import numpy as np

from ..common import Context, Estimate, finish, strongest

PARAMETERS = dict(window=768, overlap=640, hop=128, nfft=4096,
                  minimum_frequency_hz=50e6, maximum_frequency_hz=6e9,
                  window_name="hann", boundary=None, padded=False, detrend=False)


def run(context: Context) -> Estimate:
    time_s, f, discrete, spectrum = strongest(context.signal, 768, 50e6, 6e9)
    if len(f) != len(context.centers):
        raise AssertionError("Expected common center subset")
    result = finish(context, f, mask_before_onset=False,
                    details={"baseline": "unchanged formal API; no event gate"},
                    extra={"discrete_hz": discrete})
    energy = np.max(spectrum[context.band], axis=0)**2
    prefix = max(3, int(.1*len(energy)))
    high = np.flatnonzero(energy > max(float(np.median(energy[:prefix]))*8, 1e-300))
    result.onset_s = float(time_s[high[0]]) if len(high) else None
    return result
