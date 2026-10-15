"""Fresh time-voltage benchmark and independent truth-only evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.models import SignalRecord
from dps_studio.research.task023e_waveform_benchmark import generate_case, oscillator_phase

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
FS_HZ = 40e9
COUNT = 32000
TOLERANCE_HZ = 200e6
FAMILIES = ("pre_event", "normal", "jump", "broadband", "fading", "competition",
            "fast_descent", "smooth_wrong", "crossing", "pure_noise", "colored_noise",
            "coherent_nontarget", "real_excursion", "weak_target")
SPLIT_BASES = {"TRAIN": 41010000, "CALIBRATION": 41020000, "VALIDATION": 41030000,
               "HELD_OUT": 41040000}
CORE_FAMILIES = ("separated_edges", "divergence", "merge_crossing", "internal_wrong_core",
                 "amplitude_exchange", "transient_leakage", "correct_and_fast", "dropout_noise")
EXTRA_FAMILIES = ("box_return",)


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    split: str
    seed: int
    record: SignalRecord
    truth_hz: FloatArray
    target_present: BoolArray
    focus: BoolArray
    weak: BoolArray
    fast: BoolArray
    normal: BoolArray
    parameters: dict[str, Any]


def generate(family: str, instance: int, split: str) -> Case:
    if split not in SPLIT_BASES or instance < 0 or instance >= 50:
        raise ValueError("Unregistered split or instance")
    all_families = (*FAMILIES, *("core_" + f for f in CORE_FAMILIES), *EXTRA_FAMILIES)
    if family not in all_families:
        raise ValueError("Unregistered family")
    seed = SPLIT_BASES[split] + 100 * all_families.index(family) + instance
    case_id = f"D001_{split}_{family}_{instance:02d}"
    if family.startswith("core_"):
        old = generate_case(family[5:], instance, seed=seed)
        present = np.isfinite(old.truth_hz)
        fast = np.r_[False, abs(np.diff(np.nan_to_num(old.truth_hz))) * FS_HZ > 5e15] & present
        return Case(case_id, family, split, seed, old.record, old.truth_hz, present, old.focus,
                    old.focus & (family == "core_amplitude_exchange"), fast,
                    ~old.focus & present, {**old.parameters, "generator": "fresh_E23_core"})
    rng = np.random.default_rng(seed)
    t = np.arange(COUNT) / FS_HZ
    f = rng.uniform(2.1e9, 3.1e9) + rng.uniform(-.3e15, .3e15) * (t - 400e-9)
    sign = rng.choice([-1, 1])
    other = f + sign * rng.uniform(.7e9, 1.3e9)
    start = rng.uniform(270e-9, 360e-9)
    duration = rng.uniform(25e-9, 110e-9)
    event = (t >= start) & (t < start + duration)
    amp, nuisance = np.ones(COUNT), np.zeros(COUNT)
    noise_sd = float(rng.uniform(.12, .4))
    noise = rng.normal(0, noise_sd, COUNT)
    weak = np.zeros(COUNT, dtype=bool)
    fast = np.zeros(COUNT, dtype=bool)
    if family == "pre_event":
        amp[t < start] = 0
        event = t < start
    elif family == "jump":
        nuisance[event] = rng.uniform(1.6, 2.5)
    elif family == "broadband":
        noise[event] += rng.normal(0, rng.uniform(4., 10.), int(event.sum()))
        noise[np.flatnonzero(event)[::65]] += 15.
    elif family == "fading":
        amp[event] = rng.uniform(.03, .12)
        nuisance[event] = .5
        weak = event.copy()
    elif family == "competition":
        nuisance[:] = .35
        nuisance[event] = rng.uniform(1.3, 2.)
    elif family == "fast_descent":
        duration = float(rng.uniform(18e-9, 45e-9))
        event = (t >= start) & (t < start + duration)
        f = 4.7e9 - 3.4e9 * np.clip((t - start) / duration, 0, 1)
        nuisance[:] = .15
        fast = event.copy()
    elif family == "smooth_wrong":
        duration = float(rng.uniform(130e-9, 240e-9))
        if instance % 2:
            start = 0.
        event = (t >= start) & (t < start + duration)
        nuisance[event] = 1.8
    elif family == "crossing":
        ramp = np.clip((t - start) / duration, 0, 1)
        other = f + 1.2e9 * (1 - 2 * ramp)
        nuisance[:] = .65
        nuisance[event] = 1.5
    elif family in ("pure_noise", "colored_noise", "coherent_nontarget"):
        amp[:] = 0
        event[:] = True
        if family == "colored_noise":
            # MA low-pass plus white noise: no coherent oscillator.
            noise += 2 * np.convolve(rng.normal(0, 1., COUNT), np.ones(9) / 3, mode="same")
        elif family == "coherent_nontarget":
            nuisance[:] = 1.
    elif family == "real_excursion":
        # Negative control: a true fall/return with a persistent faint alternative.
        duration = float(rng.uniform(8e-9, 20e-9))
        event = (t >= start) & (t < start + duration)
        other = f.copy()
        u = np.clip((t - start) / duration, 0, 1)
        f = f - 1.1e9 * np.sin(np.pi * u)**2
        nuisance[:] = rng.uniform(.25, .45)
        fast = event.copy()
    elif family == "weak_target":
        # Include a deliberately hard tail; presence does not imply observability.
        snr_db = (-22., -15., -8., 0.)[instance % 4]
        amp[:] = np.sqrt(2) * noise_sd * 10**(snr_db / 20)
        weak[:] = True
        event[:] = True
    elif family == "box_return":
        # A real excursion with plateau and 2 ns finite ramps, not a fake jump.
        duration = float(rng.uniform(65e-9, 110e-9))
        event = (t >= start) & (t < start + duration)
        other = f.copy()
        ramp = np.minimum(np.clip((t - start) / 2e-9, 0, 1),
                          np.clip((start + duration - t) / 2e-9, 0, 1))
        f = f - 1.1e9 * ramp
        nuisance[:] = rng.uniform(.25, .45)
        fast = event.copy()
    phase0 = rng.uniform(-np.pi, np.pi, 2)
    voltage = amp * np.cos(oscillator_phase(f, phase0=phase0[0]))
    voltage += nuisance * np.cos(oscillator_phase(other, phase0=phase0[1])) + noise
    present = amp > 0
    truth = np.where(present, f, np.nan)
    normal = present & ~event
    if family == "normal":
        normal[:] = True
    return Case(case_id, family, split, seed, SignalRecord(t, voltage), truth, present,
                event, weak, fast, normal,
                dict(generator="fresh_D001", sample_rate_hz=FS_HZ, count=COUNT,
                     noise_sd_v=noise_sd, start_s=float(start), duration_s=duration,
                     amplitude_min_v=float(amp.min()), amplitude_max_v=float(amp.max())))


def frame_labels(case: Case, time_s: FloatArray, window_samples: int) -> dict[str, NDArray[Any]]:
    indices = np.rint((time_s - case.record.time_s[0]) * case.record.sample_rate_hz).astype(int)
    half_s = window_samples / case.record.sample_rate_hz / 2
    # Keep transition-mixed frames in trajectory evaluation, report separately.
    lo = np.maximum(0, indices - window_samples // 2)
    hi = np.minimum(len(case.target_present), indices + window_samples // 2)
    cumulative = np.r_[0, np.cumsum(case.target_present)]
    fraction = (cumulative[hi] - cumulative[lo]) / (hi - lo)
    return dict(truth=case.truth_hz[indices], present=case.target_present[indices],
                focus=case.focus[indices], weak=case.weak[indices], fast=case.fast[indices],
                normal=case.normal[indices], homogeneous=(fraction == 0) | (fraction == 1),
                fully_absent=fraction == 0, half_window_s=np.full(len(indices), half_s))


def evaluate(path: FloatArray, reference: FloatArray, labels: dict[str, NDArray[Any]],
             signal_supported: BoolArray) -> dict[str, Any]:
    truth = labels["truth"]
    valid = np.isfinite(truth)
    finite = np.isfinite(path)
    comparable = valid & finite
    old_error, error = abs(reference - truth), abs(path - truth)
    changed = path != reference
    corrected = valid & (old_error > TOLERANCE_HZ) & finite & (error <= TOLERANCE_HZ)
    harmed = valid & (old_error <= TOLERANCE_HZ) & (~finite | (error > TOLERANCE_HZ))
    normal = valid & labels["normal"] & (old_error <= TOLERANCE_HZ)
    fast = valid & labels["fast"] & (old_error <= TOLERANCE_HZ)
    absent = labels["fully_absent"]
    weak = valid & labels["weak"] & labels["homogeneous"]
    present = valid & labels["homogeneous"]
    counts = dict(frames=len(path), finite_frames=int(finite.sum()), truth_frames=int(valid.sum()),
        sse_hz2=float(np.sum((path[comparable] - truth[comparable])**2)),
        squared_error_frames=int(comparable.sum()),
        wrong_frames=int((valid & (~finite | (error > TOLERANCE_HZ))).sum()),
        interventions=int(changed.sum()), truth_interventions=int((changed & valid).sum()),
        corrected_frames=int(corrected.sum()), harmed_frames=int(harmed.sum()),
        improved_error_frames=int((valid & changed & (old_error - error > 1e6)).sum()),
        worsened_error_frames=int((valid & changed & (error - old_error > 1e6)).sum()),
        normal_frames=int(normal.sum()), normal_preserved=int((normal & ~changed).sum()),
        fast_frames=int(fast.sum()), fast_preserved=int((fast & ~changed).sum()),
        fast_all=int((valid & labels["fast"]).sum()),
        fast_wrong=int((valid & labels["fast"] & (error > TOLERANCE_HZ)).sum()),
        focus_wrong=int((valid & labels["focus"] & (error > TOLERANCE_HZ)).sum()),
        focus_frames=int((valid & labels["focus"]).sum()),
        target_frames=int(present.sum()), target_detected=int((present & signal_supported).sum()),
        absent_frames=int(absent.sum()), absent_rejected=int((absent & ~signal_supported).sum()),
        false_supported=int((absent & signal_supported).sum()), weak_frames=int(weak.sum()),
        weak_rejected=int((weak & ~signal_supported).sum()),
        detection_tp=int((present & signal_supported).sum()),
        detection_fp=int((absent & signal_supported).sum()),
        mixed_boundary_frames=int((~labels["homogeneous"]).sum()))
    return counts


def ratios(counts: dict[str, Any]) -> dict[str, float | None]:
    def divide(a: str, b: str) -> float | None:
        return float(counts[a] / counts[b]) if counts[b] else None
    mse = divide("sse_hz2", "squared_error_frames")
    return dict(rmse_hz=float(np.sqrt(mse)) if mse is not None else None,
        wrong_branch_fraction=divide("wrong_frames", "truth_frames"),
        coverage=divide("finite_frames", "frames"),
        intervention_precision=divide("corrected_frames", "truth_interventions"),
        harm_rate=divide("harmed_frames", "truth_interventions"),
        normal_preservation=divide("normal_preserved", "normal_frames"),
        fast_preservation=divide("fast_preserved", "fast_frames"),
        target_present_recall=divide("target_detected", "target_frames"),
        no_target_rejection=divide("absent_rejected", "absent_frames"),
        false_supported_rate=divide("false_supported", "absent_frames"),
        weak_target_false_rejection=divide("weak_rejected", "weak_frames"),
        detection_precision=(counts["detection_tp"] / (counts["detection_tp"] + counts["detection_fp"])
                             if counts["detection_tp"] + counts["detection_fp"] else None))
