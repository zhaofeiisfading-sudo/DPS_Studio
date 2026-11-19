"""Label-free physical regime decoding on raw-voltage and M4 observables."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np
from numpy.typing import NDArray

from scripts.research.task023.coherent import off_threshold
from scripts.research.task023.common import Channel, Estimate
from scripts.research.task023.phase_coherent import CW_RATE_HZ_S
from scripts.research.task023.waveform import FLOOR, Bool, Float, Int


class Regime(IntEnum):
    NOISE_OR_QUIET = 0
    PRECURSOR_OR_CLUTTER = 1
    STEP_ONSET = 2
    STEADY_RIDGE = 3
    CHIRPING_RIDGE = 4
    WEAK_COHERENT_TAIL = 5
    PERSISTENT_CW_TAIL = 6
    MULTI_BRANCH_TRANSITION = 7


@dataclass(frozen=True)
class Observables:
    dc_step: Bool
    local_rms_ratio: Float
    m4_score: Float
    split_half_coherence: Float
    verification_window_ns: Float
    short_r2: Float
    abs_chirp_rate: Float
    rail_clipped: Bool
    persistent_cw_overlap: Bool
    multi_branch: Bool
    tracked: Bool


@dataclass(frozen=True)
class Segmentation:
    index: Int
    margin: Float
    diagnostic_window_ns: Float
    rms_split_ratio: float

    @property
    def labels(self) -> NDArray[np.str_]:
        return np.asarray([state.name for state in Regime])[self.index]


def _bic_rms_split(rms: Float) -> float:
    """Fit one or two ordered log-RMS classes with shared residual variance."""
    x = np.sort(np.log(np.maximum(rms[np.isfinite(rms)], FLOOR)))
    n = len(x)
    minimum = max(4, n//10)
    splits = np.arange(minimum, n-minimum+1)
    if not len(splits):
        return 1.5
    sum_x, sum_xx = np.cumsum(x), float(x @ x)
    left, right = sum_x[splits-1], sum_x[-1] - sum_x[splits-1]
    total = sum_xx - sum_x[-1]**2/n
    error = sum_xx - left**2/splits - right**2/(n-splits)
    # Penalize the additional class mean and boundary, and account for class
    # prevalence in the two-class Gaussian likelihood.
    fraction = splits/n
    mixing_cost = -2*(splits*np.log(fraction)+(n-splits)*np.log1p(-fraction))
    bic = n*np.log(np.maximum(error/n, .03**2)) + mixing_cost + 4*np.log(n)
    best = np.argmin(bic)
    one_bic = n*np.log(max(total/n, .03**2)) + 2*np.log(n)
    cut = splits[best]
    if bic[best] >= one_bic:
        return 1.5
    return max(1.5, float(np.exp((x[cut-1] + x[cut])/2)))


def _emission(obs: Observables, rms_split: float) -> Float:
    log_rms = np.log(np.maximum(obs.local_rms_ratio, FLOOR))
    strength = np.clip(np.nan_to_num((log_rms - np.log(rms_split))/.35), -3., 3.)
    score = np.clip(np.nan_to_num(obs.m4_score - off_threshold(), nan=-3.), -3., 4.)
    coherence = np.nan_to_num(obs.split_half_coherence)
    chirping = np.clip(np.nan_to_num(obs.abs_chirp_rate / CW_RATE_HZ_S - 1.), -1., 3.)
    tracked, step = obs.tracked, obs.dc_step
    quiet = ~tracked & ~step
    short_support = (obs.verification_window_ns <= 12.8) | (obs.short_r2 >= .25)
    weak_tail = (tracked & ~short_support & (obs.verification_window_ns >= 25.6)
                 & ((obs.abs_chirp_rate <= CW_RATE_HZ_S) | (strength < 0.)))
    favored = np.column_stack((
        np.where(quiet, 2.2 - strength - .40*score, -np.inf),
        np.where(~tracked, .65 + strength + .35*score + obs.rail_clipped, -np.inf),
        np.where(step & tracked, 12. + obs.rail_clipped, -np.inf),
        np.where(tracked, 2.7 + .55*strength - chirping, -np.inf),
        np.where(tracked, 2. + .50*strength + chirping, -np.inf),
        np.where(weak_tail, 2.7 - 1.2*strength + 1.5*coherence - .40*score, -np.inf),
        np.where(tracked & obs.persistent_cw_overlap, 10., -np.inf),
        np.where(tracked & obs.multi_branch, 9., -np.inf),
    ))
    return np.asarray(favored, dtype=np.float64)


def _decode(emission: Float) -> Int:
    """Maximum a posteriori path in a sticky finite-state HMM."""
    n, states = emission.shape
    indices = np.arange(states)
    transition = np.full((states, states), -1.35)
    np.fill_diagonal(transition, 0.)
    back = np.zeros((n, states), dtype=np.int64)
    state = emission[0]
    for i in range(1, n):
        candidate = state[:, None] + transition
        back[i] = np.argmax(candidate, axis=0)
        state = candidate[back[i], indices] + emission[i]
    decoded = np.empty(n, dtype=np.int64)
    decoded[-1] = np.argmax(state)
    for i in range(n-1, 0, -1):
        decoded[i-1] = back[i, decoded[i]]
    return decoded


def segment(obs: Observables) -> Segmentation:
    """Infer regimes from physical observables for one record."""
    if not len(obs.tracked):
        return Segmentation(np.empty(0, dtype=np.int64), np.empty(0), np.empty(0), 1.5)
    split = _bic_rms_split(obs.local_rms_ratio[obs.tracked & ~obs.persistent_cw_overlap])
    emission = _emission(obs, split)
    index = _decode(emission)
    competing = emission.copy()
    competing[np.arange(len(index)), index] = -np.inf
    margin = emission[np.arange(len(index)), index] - competing.max(axis=1)
    windows = np.array([np.nan, np.nan, 6.4, 12.8, 12.8, 25.6, 38.4, 25.6])
    return Segmentation(index, margin, windows[index], split)


def observables(channel: Channel, m4: Estimate) -> Observables:
    """Read same-center waveform diagnostics. The channel supplies the SI grid."""
    if not np.array_equal(channel.q, m4.sample_index):
        raise ValueError("M4 and waveform centers must use the same grid")
    d = m4.diagnostics
    return Observables(
        np.asarray(d["detected_dc_step"], dtype=np.bool_)
        | np.asarray(d["rail_entry_edge"], dtype=np.bool_),
        np.sqrt(10**(m4.raw.local_center_snr_32ns/10)),
        np.asarray(d["whitened_score"], dtype=np.float64),
        np.asarray(d["split_half_coherence"], dtype=np.float64),
        np.asarray(d["verification_window_ns"], dtype=np.float64),
        m4.raw.raw_chirp_r2_64ns,
        abs(m4.chirp_hz_s),
        np.asarray(d["rail_clipped"], dtype=np.bool_),
        np.asarray(d["persistent_cw_overlap"], dtype=np.bool_),
        np.isfinite(d["secondary_hz"]),
        np.isfinite(m4.accepted_hz),
    )
