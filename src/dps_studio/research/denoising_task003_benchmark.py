"""Fresh paired-polarity voltage stress benchmark; labels never enter inference."""
from __future__ import annotations

from typing import Any

import numpy as np

from dps_studio.core.models import SignalRecord
from dps_studio.research.denoising_task002 import COUNT, FS_HZ, Case
from dps_studio.research.task023e_waveform_benchmark import oscillator_phase

FAMILIES = ('normal', 'short_noise_peak', 'obvious_jump', 'true_return',
            'wrong_branch_gain', 'anchor_exchange', 'coherent_nontarget',
            'nonlinear_valley', 'amplitude_fading', 'fast_physical_change',
            'persistent_wrong', 'no_target_information')
SPLITS = {'TRAIN': (43010000, 2), 'CALIBRATION': (43020000, 2), 'HELD_OUT': (43040000, 4)}
VARIANTS = ('repair_opportunity', 'harm_counterexample')


def registration() -> list[dict[str, Any]]:
    return [dict(case_id=f'D003_{split}_{family}_{variant}_{i:02d}', split=split,
                 family=family, variant=variant, instance=i, seed=base + 100*j + 10*v + i)
            for split, (base, count) in SPLITS.items()
            for j, family in enumerate(FAMILIES) for v, variant in enumerate(VARIANTS)
            for i in range(count)]


def generate(family: str, variant: str, instance: int, split: str) -> Case:
    if (family not in FAMILIES or variant not in VARIANTS or split not in SPLITS
            or not 0 <= instance < SPLITS[split][1]):
        raise ValueError('Unregistered fresh waveform')
    seed = SPLITS[split][0] + 100*FAMILIES.index(family) + 10*VARIANTS.index(variant) + instance
    rng = np.random.default_rng(seed)
    t = np.arange(COUNT, dtype=float)/FS_HZ
    upper = rng.uniform(2.65e9, 3.25e9) + rng.uniform(-.2e15, .2e15)*(t-400e-9)
    start = float(rng.uniform(245e-9, 285e-9))
    duration = float(rng.uniform(65e-9, 145e-9))
    depth = float(rng.uniform(.8e9, 1.4e9))
    ramp = float(rng.uniform(1.5e-9, 8e-9))
    if family == 'short_noise_peak':
        duration = float(rng.uniform(22e-9, 42e-9))
    if family == 'fast_physical_change':
        ramp = float(rng.uniform(.5e-9, 2e-9))
    shape = np.minimum(np.clip((t-start)/ramp, 0, 1),
                       np.clip((start+duration-t)/ramp, 0, 1))
    if family == 'nonlinear_valley':
        x = np.clip((t-start)/duration, 0, 1)
        shape = np.sin(np.pi*x)**2
    event = (t >= start) & (t <= start+duration)
    target = upper.copy()
    other = upper-depth
    a = np.ones(COUNT)
    b = np.full(COUNT, .08)
    # Independently generated favorable and adverse polarity in EVERY context.
    # Ratios overlap deliberately: amplitude is not an oracle of target identity.
    ratio = float(rng.uniform(1.08, 2.15))
    if variant == 'repair_opportunity':
        b[event] = ratio
    else:
        target = upper-depth*shape
        other = upper.copy()
        b[:] = 1/ratio
        # Unresolved anchors exchange dominance; inside the target remains strong.
        transition = np.clip((t-start)/duration, 0, 1)
        a = 1.15-.98*transition
        a[event] = 1.05
        b[~event] = (.08+1.02*transition)[~event]
    if family == 'obvious_jump' and variant == 'repair_opportunity':
        b[event] = rng.uniform(1.8, 2.4)
    elif family == 'wrong_branch_gain':
        b[event] *= 1.15
    elif family == 'true_return' and variant == 'repair_opportunity':
        # Additional clean true return outside the repair probe.
        q = np.clip((t-570e-9)/65e-9, 0, 1)
        target -= .9e9*np.sin(np.pi*q)**2
    elif family == 'anchor_exchange' and variant == 'repair_opportunity':
        a = np.where(t < start, 1.1, np.where(t > start+duration, .75, .9))
    elif family == 'amplitude_fading':
        a *= 1-.65*np.exp(-.5*((t-start-duration/2)/30e-9)**2)
    elif family == 'persistent_wrong':
        # A distinct >180ns hard interval, plus the short local probe.
        long = (t >= 470e-9) & (t < 730e-9)
        other[long] = upper[long]-.95e9
        b[long] = 1.8
        event |= long
    elif family in ('no_target_information', 'coherent_nontarget'):
        absent = (t >= 535e-9) & (t <= 715e-9)
        a[absent] = 0
        b[absent] = 0 if family == 'no_target_information' else 1.
        event |= absent
    noise_sd = float(rng.uniform(.1, .3))
    noise = rng.normal(0, noise_sd, COUNT)
    if family == 'short_noise_peak':
        noise[event] += rng.normal(0, .7, int(event.sum()))
    phase = rng.uniform(-np.pi, np.pi, 2)
    voltage = (a*np.cos(oscillator_phase(target, phase0=float(phase[0])))
               + b*np.cos(oscillator_phase(other, phase0=float(phase[1]))) + noise)
    present = a > 0
    fast = np.r_[False, abs(np.diff(target))*FS_HZ > 5e15] & present
    focus = event | (abs(target-upper) > 1e6)
    params = dict(generator='D003_independent_polarity_voltage', variant=variant,
                  start_s=start, duration_s=duration, ramp_s=ramp, depth_hz=depth,
                  ratio_draw=ratio, noise_sd_v=noise_sd, phase_rad=phase.tolist(),
                  sample_rate_hz=FS_HZ, count=COUNT)
    return Case(f'D003_{split}_{family}_{variant}_{instance:02d}', family, split,
                instance, seed, SignalRecord(t, voltage), np.where(present, target, np.nan),
                present, focus, fast, present & ~focus, params, a, other, b)
