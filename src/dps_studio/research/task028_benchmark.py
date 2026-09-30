"""Small fixed graduation benchmark; truth is used only by this evaluator."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from dps_studio.core.models import SignalRecord
from dps_studio.research.task023e_waveform_benchmark import oscillator_phase
from dps_studio.research.task028_consolidation import FloatArray

FAMILIES = ('A_normal', 'B_noise_peak', 'C_short_switch', 'D_broadband',
            'E_fading', 'F_smooth_wrong', 'G_fast_change', 'H_identity_ambiguity')
FS_HZ = 40e9
COUNT = 32000
SEED_BASE = 28092000
TOLERANCE_HZ = 200e6


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    seed: int
    record: SignalRecord
    truth_hz: FloatArray
    other_hz: FloatArray
    event_start_s: float
    event_end_s: float


def generate(family: str, instance: int, *, seed_base: int = SEED_BASE) -> Case:
    if family not in FAMILIES or not 0 <= instance < 8:
        raise ValueError('Expected registered family and instance 0..7')
    seed = seed_base + 100 * FAMILIES.index(family) + instance
    rng = np.random.default_rng(seed)
    t = np.arange(COUNT) / FS_HZ
    base = rng.uniform(2.1e9, 3.1e9)
    slope = rng.uniform(-.3e15, .3e15)
    truth = base + slope * (t - 400e-9)
    other = truth + rng.choice([-1, 1]) * rng.uniform(.8e9, 1.3e9)
    start = rng.uniform(280e-9, 380e-9)
    duration = rng.uniform(30e-9, 85e-9)
    end = start + duration
    target_amp = np.ones(COUNT)
    nuisance_amp = np.zeros(COUNT)
    event = (t >= start) & (t < end)
    noise = rng.normal(0, rng.uniform(.08, .22), COUNT)
    nuisance_phase = oscillator_phase(other, phase0=rng.uniform(-np.pi, np.pi))
    if family == 'B_noise_peak':
        nuisance_amp[event] = 2.4
        nuisance_phase += np.cumsum(rng.normal(0, .12, COUNT))
    elif family == 'C_short_switch':
        end = start + rng.uniform(20e-9, 40e-9)
        event = (t >= start) & (t < end)
        nuisance_amp[event] = rng.uniform(1.6, 2.3)
    elif family == 'D_broadband':
        noise[event] += rng.normal(0, 9., int(event.sum()))
        noise[np.flatnonzero(event)[::80]] += 20.
    elif family == 'E_fading':
        target_amp[event] = .04
        nuisance_amp[event] = .45
    elif family == 'F_smooth_wrong':
        # Long coherent alternative, alternating internal and boundary corruption.
        if instance % 2:
            start, end = 0., duration
            event = t < end
        nuisance_amp[event] = 1.8
    elif family == 'G_fast_change':
        end = start + rng.uniform(20e-9, 45e-9)
        truth = 4.7e9 - 3.4e9 * np.clip((t-start)/(end-start), 0, 1)
        nuisance_amp[:] = .15
    elif family == 'H_identity_ambiguity':
        nuisance_amp[:] = 1.
        start, end = 0., COUNT / FS_HZ
    voltage = target_amp * np.cos(oscillator_phase(truth, phase0=rng.uniform(-np.pi, np.pi)))
    voltage += nuisance_amp * np.cos(nuisance_phase) + noise
    case_id = f'T28_{family}_{instance:02d}'
    return Case(case_id, family, seed, SignalRecord(t, voltage), truth, other, start, end)


def metrics(path: FloatArray, baseline: FloatArray, truth: FloatArray,
            normal: np.ndarray[Any, np.dtype[np.bool_]],
            fast: np.ndarray[Any, np.dtype[np.bool_]],
            obvious: np.ndarray[Any, np.dtype[np.bool_]]) -> dict[str, Any]:
    valid = np.isfinite(truth)
    finite = np.isfinite(path)
    comparable = valid & finite
    error, old = abs(path - truth), abs(baseline - truth)
    changed = (path != baseline) & ~(np.isnan(path) & np.isnan(baseline))
    improved = comparable & changed & (old - error > 1e6)
    harmed = comparable & changed & (error - old > 1e6)
    corrected = valid & (old > TOLERANCE_HZ) & finite & (error <= TOLERANCE_HZ)
    damaged = valid & (old <= TOLERANCE_HZ) & (~finite | (error > TOLERANCE_HZ))
    old_good = valid & (old <= TOLERANCE_HZ)
    normal_den = normal & old_good
    fast_den = fast & old_good
    obvious_den = obvious & valid & (old > TOLERANCE_HZ)
    return dict(frames=len(path), finite_frames=int(finite.sum()), truth_frames=int(valid.sum()),
        sse_hz2=float(np.sum((path[comparable]-truth[comparable])**2)),
        squared_error_frames=int(comparable.sum()),
        wrong_frames=int(np.sum(valid & (~finite | (error > TOLERANCE_HZ)))),
        interventions=int(changed.sum()), corrected_frames=int(corrected.sum()),
        harmed_frames=int(damaged.sum()), improved_error_frames=int(improved.sum()),
        worsened_error_frames=int(harmed.sum()),
        normal_frames=int(normal_den.sum()), normal_preserved=int((normal_den & ~changed).sum()),
        fast_frames=int(fast_den.sum()), fast_preserved=int((fast_den & ~changed).sum()),
        fast_all=int(fast.sum()), fast_correct=int((fast & (error <= TOLERANCE_HZ)).sum()),
        obvious_frames=int(obvious_den.sum()), obvious_corrected=int((obvious_den & corrected).sum()))


def ratios(row: dict[str, Any]) -> dict[str, Any]:
    def ratio(a: str, b: str) -> float | None:
        return float(row[a] / row[b]) if row[b] else None
    value = ratio('sse_hz2', 'squared_error_frames')
    return dict(rmse_hz=float(np.sqrt(value)) if value is not None else None,
        wrong_branch_fraction=ratio('wrong_frames', 'truth_frames'),
        coverage=ratio('finite_frames', 'frames'),
        candidate_recall=ratio('candidate_recalled', 'truth_frames'),
        intervention_precision=ratio('corrected_frames', 'interventions'),
        harm_rate=ratio('harmed_frames', 'interventions'),
        error_improvement_precision=ratio('improved_error_frames', 'interventions'),
        error_worsening_rate=ratio('worsened_error_frames', 'interventions'),
        normal_region_preservation=ratio('normal_preserved', 'normal_frames'),
        fast_change_preservation=ratio('fast_preserved', 'fast_frames'),
        fast_all_correct_fraction=ratio('fast_correct', 'fast_all'),
        obvious_jump_correction_rate=ratio('obvious_corrected', 'obvious_frames'))
