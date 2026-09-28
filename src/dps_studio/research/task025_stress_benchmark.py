"""Preregistered stress synthesis and GT evaluation labels; never detector inputs."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.models import SignalRecord
from dps_studio.research.task023e_waveform_benchmark import (
    SAMPLE_COUNT, SAMPLE_RATE_HZ, WaveformCase, generate_case, oscillator_phase,
)
from dps_studio.research.task025_informative_interval import runs


def registered_case(row: dict[str, Any]) -> WaveformCase:
    dataset, family = row['dataset'], row['family']
    i, seed = int(row['instance']), int(row['seed'])
    if dataset == 'CORE':
        return replace(generate_case(family, i, seed), case_id=row['waveform'],
                       observation_group=row['waveform'], split=row['split'])
    rng = np.random.default_rng(seed)
    t = np.arange(SAMPLE_COUNT) / SAMPLE_RATE_HZ
    carrier = rng.uniform(1.8e9, 3.0e9)
    center, duration = rng.uniform(.7e-6, 1.2e-6), rng.uniform(20e-9, 150e-9)
    phase, noise_sd = rng.uniform(-np.pi, np.pi), rng.uniform(.15, .5)
    focus = (t >= center) & (t < center+duration)
    ramp = np.clip((t-center)/duration, 0, 1)
    target = np.full(SAMPLE_COUNT, carrier)
    other = np.full(SAMPLE_COUNT, carrier+.7e9)
    target_amp, other_amp = np.ones(SAMPLE_COUNT), np.zeros(SAMPLE_COUNT)
    burst = np.zeros(SAMPLE_COUNT)
    if dataset == 'HARD_NEGATIVE':
        target_amp[:] = 0
        other[:] = carrier
        if family in ('H1', 'H6'):
            burst[focus] = rng.normal(0, 3., int(focus.sum()))
        if family in ('H2', 'H3', 'H5', 'H6'):
            other_amp[:] = 1
        elif family == 'H4':
            other_amp[focus] = 1
        elif family == 'H7':
            other_amp[:] = .4
            other[:] = 1.25e9
            phase = .3
        if family == 'H3':
            other = carrier - 1.5e15*(t-1e-6)
        if family == 'H5':
            burst += .8*np.cos(oscillator_phase(np.full(SAMPLE_COUNT, carrier+.7e9),
                                                phase0=phase+.7))
    elif dataset == 'POSITIVE_STRESS':
        if family == 'low_snr':
            noise_sd = float(np.sqrt(.5/10**([-10., -5., 0.][i % 3]/10)))
            focus[:] = True
        elif family == 'temporary_fading':
            target_amp[focus] = .05
        elif family == 'amplitude_fading':
            target_amp = 1-.98*ramp
            focus = t >= center
        elif family == 'fast_descent':
            target = 5e9-4.3e9*ramp
        elif family in ('branch_crossing', 'branch_merge'):
            other = target + 1.2e9*(1-(2 if family == 'branch_crossing' else 1)*ramp)
            other_amp[focus] = 1.2
        elif family == 'broadband_target':
            burst[focus] = rng.normal(0, 3., int(focus.sum()))
        elif family == 'leading_edge':
            target_amp[t < center] = 0
        elif family == 'trailing_edge':
            target_amp[t >= center] = 0
        elif family == 'short_segment':
            duration = rng.uniform(10e-9, 40e-9)
            focus = (t >= center) & (t < center+duration)
            target_amp[~focus] = 0
        else:
            raise ValueError(f'Unregistered positive family {family}')
    else:
        raise ValueError('Unknown dataset')
    voltage = (target_amp*np.cos(oscillator_phase(target, phase0=phase))
               + other_amp*np.cos(oscillator_phase(other, phase0=phase))
               + burst + rng.normal(0, noise_sd, SAMPLE_COUNT))
    truth = np.where(target_amp > 0, target, np.nan)
    nuisance = np.where(other_amp > 0, other, np.nan)
    return WaveformCase(row['waveform'], family, i, row['split'], seed,
        SignalRecord(t, voltage, source_path=f"synthetic/{row['waveform']}.npz"),
        truth, nuisance, focus, dict(variant=family, center_s=center, duration_s=duration,
                                    noise_sd_v=noise_sd, carrier_hz=carrier), row['waveform'])


def evaluation_masks(case: WaveformCase, dataset: str, time_s: NDArray[np.float64],
                     truth: NDArray[np.float64]) -> dict[str, NDArray[np.bool_]]:
    sample = np.rint(time_s*SAMPLE_RATE_HZ).astype(int)
    target = np.isfinite(truth)
    if dataset == 'HARD_NEGATIVE':
        structured = np.isfinite(case.nuisance_hz[sample])
    else:
        structured = target.copy()
    masks = dict(all=np.ones(len(time_s), dtype=bool), target_present=target,
                 structured=structured, low_information=~structured)
    empty = np.zeros(len(time_s), dtype=bool)
    leading, trailing = empty.copy(), empty.copy()
    for a, b in runs(target):
        leading[a:min(a+4, b)] = True
        trailing[max(a, b-4):b] = True
    masks.update(leading_edge=leading, trailing_edge=trailing, target_edge=leading | trailing)
    focus = case.focus[sample] & target
    ramp = ((time_s >= case.parameters['center_s']) &
            (time_s < case.parameters['center_s']+case.parameters['duration_s']) & target)
    variant = case.parameters['variant']
    masks['fast_descent'] = ramp if variant == 'fast_descent' else empty.copy()
    masks['temporary_fading'] = focus if case.family == 'temporary_fading' else empty.copy()
    masks['amplitude_fading'] = focus if case.family in (
        'amplitude_fading', 'amplitude_exchange') else empty.copy()
    masks['low_snr'] = target if case.parameters['noise_sd_v'] >= .3 else empty.copy()
    masks['broadband_target'] = focus if case.family in (
        'broadband_target', 'transient_leakage') else empty.copy()
    masks['branch_crossing'] = focus if variant in ('crossing', 'branch_crossing') else empty.copy()
    masks['branch_merge'] = focus if variant in ('merge', 'branch_merge') else empty.copy()
    masks['short_segment'] = target if case.family == 'short_segment' else empty.copy()
    # H1 is independently evaluated as broadband-only, not included in pure-noise gate.
    masks['pure_noise_dropout'] = (~structured if dataset != 'HARD_NEGATIVE' or
        case.family in ('H0', 'H4') else empty.copy())
    return masks
