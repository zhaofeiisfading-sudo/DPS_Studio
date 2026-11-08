"""Ridge-guided digital demodulation, explicit FIR and local phase derivative.

Offline centered FIR/SG are used only after independently detected onset, so
this method does not supply a causal onset estimate. Mirror overlap and unwrap
failures remain limitations. All filters and boundary guards are recorded.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve, firwin, savgol_filter  # type: ignore[import-untyped]

from ..common import Context, Estimate, finish

PARAMETERS = dict(fir_taps=257, lowpass_cutoff_hz=200e6, derivative_samples=129,
                  polynomial_order=2, phase_unwrap=True, filter_phase="centered offline",
                  event_detection="shared unfiltered raw energy detector",
                  low_frequency_guard_hz=400e6, boundary_guard_samples=192)


def run(context: Context) -> Estimate:
    f = np.full(len(context.centers), np.nan)
    amp = np.full(len(f), np.nan)
    if context.onset is None:
        return finish(context, f, details={"reason": "NO_EVENT"})
    start = context.onset
    indices = np.arange(start, len(context.signal.time_s), dtype=np.int64)
    if len(indices) < 512:
        return finish(context, f, details={"reason": "EVENT_TOO_SHORT"})
    coarse = context.initializer(indices)
    phase = 2*np.pi*np.r_[0., np.cumsum((coarse[1:]+coarse[:-1])*.5/context.fs)]
    x = context.signal.voltage_v[start:]-np.median(
        context.signal.voltage_v[:int(context.event["prefix_samples"])])
    taps = firwin(257, 200e6, fs=context.fs)
    z = fftconvolve(x*np.exp(-1j*phase), taps, mode="same")
    unwrapped = np.unwrap(np.angle(z))
    delta = savgol_filter(unwrapped, 129, 2, deriv=1, delta=1/context.fs)/(2*np.pi)
    refined = coarse+delta
    usable = (context.centers >= start+192) & (context.centers < len(context.signal.time_s)-192)
    offset = context.centers[usable]-start
    f[usable] = refined[offset]
    amp[usable] = 2*abs(z[offset])
    chirp = np.zeros(len(f))
    if sum(usable) > 2:
        chirp[usable] = np.gradient(f[usable], context.time_s[usable])
    result = finish(context, f, chirp=chirp, extra={"baseband_amplitude_v": amp})
    invalid = (f < 400e6) | (amp < 2*context.noise)
    result.accepted_hz[invalid] = np.nan
    result.flags[invalid] = "MIRROR_OVERLAP_OR_LOW_ENVELOPE|UNOBSERVABLE"
    return result
