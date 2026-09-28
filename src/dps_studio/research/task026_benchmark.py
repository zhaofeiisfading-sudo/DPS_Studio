"""Preregistered synthesis and evaluator, separated from waveform-only estimators."""
from __future__ import annotations

from dataclasses import replace
from itertools import product
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.models import SignalRecord
from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, SAMPLE_RATE_HZ, WaveformCase, generate_case,
)
from dps_studio.research.task026_representation import Observation

FloatArray = NDArray[np.float64]
SNRS = (-20., -10., 0., 10., 30.)
SEPARATIONS = (25e6, 50e6, 100e6, 150e6, 250e6, 500e6)


def registration() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(dataset: str, family: str, replicate: int, **parameters: float) -> None:
        index = len(rows)
        rows.append(dict(dataset=dataset, family=family, instance=replicate,
                         seed=26010000+index, waveform=f'T26_{index:05d}',
                         split='CALIBRATION' if replicate == 0 else 'HELD_OUT', **parameters))

    for family, instance in product(FAMILIES, range(8, 24)):
        add('CORE', family, instance)
        rows[-1]['split'] = 'CALIBRATION' if instance < 12 else 'HELD_OUT'
    for snr, f, c, a, rep in product(SNRS, (1.3e9, 3e9, 4.7e9),
            (0., -1e15, 1e15, -1e16, 1e16, -4e16, 4e16), (.2, 1.), range(3)):
        family = ('stationary' if c == 0 else 'slow_chirp' if abs(c) == 1e15 else
                  'medium_chirp' if abs(c) == 1e16 else 'fast_chirp')
        add('SINGLE', family, rep, snr_db=snr, carrier_hz=f, chirp_hz_per_s=c,
            amplitude_v=a, fade_depth=1., separation_hz=0., amplitude_ratio=0.,
            slope_difference_hz_per_s=0.)
    for family, fade, snr, rep in product(('temporary_fading', 'amplitude_ramp',
                                         'nonlinear_chirp'), (.05, .2, .7), SNRS, range(3)):
        add('SINGLE', family, rep, snr_db=snr, carrier_hz=3e9, chirp_hz_per_s=4e16,
            amplitude_v=1., fade_depth=fade, separation_hz=0., amplitude_ratio=0.,
            slope_difference_hz_per_s=0.)
    for sep, snr, ratio, dc, fade, rep in product(SEPARATIONS, SNRS, (.25, 1., 4.),
                                                (0., 2e15, 1e16), (1., .1), range(3)):
        family = ('temporary_target_fading' if fade < 1 else 'strong_wrong_component'
                  if ratio == 4 else 'parallel_close' if dc == 0 else 'sloped_close')
        add('TWO', family, rep, snr_db=snr, carrier_hz=3e9, chirp_hz_per_s=0.,
            amplitude_v=1., fade_depth=fade, separation_hz=sep, amplitude_ratio=ratio,
            slope_difference_hz_per_s=dc)
    for family, sep, snr, rep in product(('crossing', 'merging', 'diverging'),
                                       SEPARATIONS, SNRS, range(3)):
        add('TWO', family, rep, snr_db=snr, carrier_hz=3e9, chirp_hz_per_s=0.,
            amplitude_v=1., fade_depth=1., separation_hz=sep, amplitude_ratio=1.,
            slope_difference_hz_per_s=sep/12.8e-9)
    return rows


def synthesize(row: dict[str, Any]) -> WaveformCase:
    """Core calls the original unchanged generator. Controlled records separate."""
    if row['dataset'] == 'CORE':
        return replace(generate_case(row['family'], row['instance'], row['seed']),
                       case_id=row['waveform'], observation_group=row['waveform'],
                       split=row['split'])
    rng = np.random.default_rng(row['seed'])
    t = np.arange(2048)/SAMPLE_RATE_HZ
    tau = t-25.6e-9
    f0, chirp = row['carrier_hz'], row['chirp_hz_per_s']
    f1 = f0+chirp*tau
    phase1 = 2*np.pi*(f0*tau+.5*chirp*tau**2)
    a1 = np.full(len(t), row['amplitude_v'])
    family = row['family']
    focus = np.abs(tau) <= 9.6e-9
    if family in ('temporary_fading', 'temporary_target_fading'):
        a1[np.abs(tau) < 8e-9] *= row['fade_depth']
    elif family == 'amplitude_ramp':
        a1 *= 1-(1-row['fade_depth'])*(t/t[-1])
    elif family == 'nonlinear_chirp':
        # Smooth cubic phase, known analytic derivative, no numerical phase bias.
        curvature = (2*row['fade_depth']-1)*8e23
        f1 += .5*curvature*tau**2
        phase1 += 2*np.pi*curvature*tau**3/6
    f2 = f0+row['separation_hz']+row['slope_difference_hz_per_s']*tau
    phase2 = 2*np.pi*((f0+row['separation_hz'])*tau+
                      .5*row['slope_difference_hz_per_s']*tau**2)
    if family in ('crossing', 'merging', 'diverging'):
        slope = row['slope_difference_hz_per_s']
        if family == 'crossing':
            f2 = f0+slope*tau
            phase2 = 2*np.pi*(f0*tau+.5*slope*tau**2)
        else:
            u = np.minimum(tau, 0.) if family == 'merging' else np.maximum(tau, 0.)
            sign = -1 if family == 'merging' else 1
            f2 = f0+sign*slope*u
            phase2 = 2*np.pi*(f0*tau+.5*sign*slope*u**2)
    a2 = row['amplitude_ratio']*row['amplitude_v']
    noise_sd = row['amplitude_v']/np.sqrt(2*10**(row['snr_db']/10))
    phases = rng.uniform(-np.pi, np.pi, 2)
    voltage = (a1*np.cos(phase1+phases[0])+a2*np.cos(phase2+phases[1])+
               rng.normal(0, noise_sd, len(t)))
    nuisance = f2 if a2 else np.full(len(t), np.nan)
    return WaveformCase(row['waveform'], family, row['instance'], row['split'], row['seed'],
        SignalRecord(t, voltage, source_path=f"synthetic/{row['waveform']}.npz"),
        f1, nuisance, focus, dict(**row, noise_sd_v=noise_sd), row['waveform'])


def physical_truth(case: WaveformCase, dataset: str, time_s: FloatArray,
                   ) -> tuple[FloatArray, FloatArray, NDArray[np.bool_]]:
    """Sample-index GT, no interpolation; mask core nuisance when physically absent.

    Legacy nuisance_hz contains latent frequencies even when its amplitude is zero.
    The existence mask must follow original synthesis, not that latent array.
    """
    sample = np.rint((time_s-case.record.time_s[0])*SAMPLE_RATE_HZ).astype(int)
    first, second = case.truth_hz[sample], case.nuisance_hz[sample].copy()
    if dataset == 'CORE':
        active = case.focus[sample].copy()
        if case.family == 'correct_and_fast':
            active[:] = True
        elif case.family == 'dropout_noise':
            active[:] = False
        elif case.family == 'transient_leakage':
            active &= np.sin(2*np.pi*(case.record.time_s[sample]-
                                      case.parameters['center_s'])/5e-9) > 0
        second[~active] = np.nan
        focus = np.ones(len(sample), dtype=bool)
    else:
        focus = case.focus[sample]
    return first, second, focus


def unique_resolution(candidates: FloatArray, first: float, second: float) -> bool:
    """Two distinct outputs, disjoint <=min(50 MHz, separation/4) neighborhoods.

    Exact crossing is unresolved under this frequency-only definition. Sorted
    frequency ties cannot become two components; truth identities never inferred.
    """
    if not np.isfinite(first+second) or first == second:
        return False
    tolerance = min(50e6, abs(first-second)/4)
    a = np.flatnonzero(np.isfinite(candidates) & (np.abs(candidates-first) <= tolerance))
    b = np.flatnonzero(np.isfinite(candidates) & (np.abs(candidates-second) <= tolerance))
    return any(i != j and candidates[i] != candidates[j] for i in a for j in b)


def metrics(observation: Observation, first: FloatArray, second: FloatArray,
            selected: NDArray[np.bool_]) -> dict[str, float | int]:
    f = observation.frequency_hz
    valid_truth = selected & np.isfinite(first)
    comparable = valid_truth & np.isfinite(f[:, 0])
    error = f[comparable, 0]-first[comparable]
    discrete_error = observation.discrete_hz[comparable, 0]-first[comparable]
    near = np.isfinite(f) & (np.abs(f-first[:, None]) <= 200e6)
    has = near.any(axis=1)
    rank = np.where(has, np.argmax(near, axis=1)+1., np.nan)
    both = selected & np.isfinite(first) & np.isfinite(second)
    resolved = np.array([unique_resolution(c, a, b) for c, a, b in zip(f, first, second)])
    false = np.isfinite(f) & ((~np.isfinite(first[:, None])) |
                              (np.abs(f-first[:, None]) > 200e6))
    false &= ((~np.isfinite(second[:, None])) | (np.abs(f-second[:, None]) > 200e6))
    count = int(np.isfinite(f[selected]).sum())
    target_n = int(valid_truth.sum())
    nearest = np.min(np.where(np.isfinite(f), np.abs(f-first[:, None]), np.inf), axis=1)
    matched = valid_truth & has
    return dict(frames=int(selected.sum()), truth_frames=target_n,
        valid_frames=int(comparable.sum()), candidate_hits=int((valid_truth & has).sum()),
        candidate_recall=float(has[valid_truth].mean()) if target_n else np.nan,
        truth_near_rank=float(np.nanmean(rank[matched])) if matched.any() else np.nan,
        rmse_hz=float(np.sqrt(np.mean(error**2))) if error.size else np.nan,
        bias_hz=float(np.mean(error)) if error.size else np.nan,
        p95_absolute_error_hz=float(np.percentile(np.abs(error), 95)) if error.size else np.nan,
        discrete_rmse_hz=float(np.sqrt(np.mean(discrete_error**2))) if error.size else np.nan,
        discrete_bias_hz=float(discrete_error.mean()) if error.size else np.nan,
        nearest_candidate_rmse_hz=float(np.sqrt(np.mean(nearest[matched]**2)))
            if matched.any() else np.nan,
        sub_bin_shift_rmse_hz=float(np.sqrt(np.mean((error-discrete_error)**2)))
            if error.size else np.nan,
        valid_estimate_fraction=float(comparable.sum()/target_n) if target_n else np.nan,
        failure_rate=float(1-np.count_nonzero(np.abs(error) <= 200e6)/target_n)
            if target_n else np.nan,
        two_component_frames=int(both.sum()), resolved_frames=int(resolved[both].sum()),
        resolution_rate=float(resolved[both].mean()) if both.any() else np.nan,
        candidate_count=count, candidate_multiplicity=float(count/selected.sum()),
        false_candidates=int(false[selected].sum()),
        false_candidate_rate=float(false[selected].sum()/count) if count else np.nan,
        noise_frames=int((selected & ~np.isfinite(first) & ~np.isfinite(second)).sum()),
        energy_retained=observation.reassigned_energy_retained,
        residual_fraction=float(np.nanmean(observation.residual_fraction[selected]))
            if np.isfinite(observation.residual_fraction[selected]).any() else np.nan)
