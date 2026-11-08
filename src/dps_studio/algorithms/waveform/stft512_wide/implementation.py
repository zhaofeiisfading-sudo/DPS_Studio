"""Matched-band control: unchanged peak algorithm, explicit 5 MHz-8 GHz band."""
from __future__ import annotations

import numpy as np

from ..common import Context, Estimate, finish

PARAMETERS = dict(window=512, overlap=384, nfft=4096,
                  minimum_frequency_hz=5e6, maximum_frequency_hz=8e9,
                  event_gate=False, spectral_refinement="formal three-point log magnitude")


def run(context: Context) -> Estimate:
    result = finish(context, context.raw_seed_hz[context.seed_indices], mask_before_onset=False,
                    extra={"discrete_hz": context.raw_seed_discrete[context.seed_indices]},
                    details={"band_change_is_control_not_algorithmic_gain": True})
    # Same amplitude-window detector convention as legacy, independent of raw t0.
    energy = np.max(context.raw_spectrum[context.band], axis=0)**2
    high = np.flatnonzero(energy > max(float(np.median(energy[:max(3, len(energy)//10)]))*8, 1e-300))
    result.onset_s = float(context.seed_time[high[0]]) if len(high) else None
    return result
