"""TASK-002 counterexamples, truth-only scoring and observational diagnostics.

No changes to TASK-001 estimators. Envelopes are deliberately simplified models,
not validated speckle statistics. All estimator inputs remain time-voltage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.research.denoising_task001 import Proposal
from dps_studio.research.task023e_waveform_benchmark import oscillator_phase

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
FS_HZ = 40e9
COUNT = 32000
TOLERANCE_HZ = 200e6
FAMILIES = (
    "normal_platform", "normal_fast_step", "normal_fast_return",
    "return_faint", "return_coherent", "return_anchor_exchange",
    "quadratic_clean", "quadratic_competition", "curved_return",
    "amplitude_decay", "amplitude_valley", "asymmetric_envelope", "speckle_proxy",
    "wrong_burst", "branch_approach", "anchor_switch",
    "long_wrong", "edge_wrong", "coherent_nontarget", "colored_noise",
)
SPLITS = {"DEVELOPMENT": (42010000, 3), "CALIBRATION": (42020000, 3),
          "HELD_OUT": (42040000, 8)}


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    split: str
    instance: int
    seed: int
    record: SignalRecord
    truth_hz: FloatArray
    target_present: BoolArray
    focus: BoolArray
    fast: BoolArray
    normal: BoolArray
    parameters: dict[str, Any]
    target_amplitude_v: FloatArray
    competitor_hz: FloatArray
    competitor_amplitude_v: FloatArray


def registration() -> list[dict[str, Any]]:
    return [dict(case_id=f"D002_{split}_{family}_{i:02d}", split=split, family=family,
                 instance=i, seed=base + 100 * j + i)
            for split, (base, count) in SPLITS.items()
            for j, family in enumerate(FAMILIES) for i in range(count)]


def generate(family: str, instance: int, split: str) -> Case:
    if family not in FAMILIES or split not in SPLITS or not 0 <= instance < SPLITS[split][1]:
        raise ValueError("Unregistered waveform")
    seed = SPLITS[split][0] + 100 * FAMILIES.index(family) + instance
    rng = np.random.default_rng(seed)
    t = np.arange(COUNT, dtype=float) / FS_HZ
    base = float(rng.uniform(2.6e9, 3.2e9))
    slope = float(rng.uniform(-.25e15, .25e15))
    target = base + slope * (t - 400e-9)
    upper = target.copy()
    competitor = target + rng.choice([-1, 1]) * rng.uniform(.7e9, 1.25e9)
    a = np.ones(COUNT)
    b = np.zeros(COUNT)
    start = float(rng.uniform(280e-9, 340e-9))
    duration = float((40., 72., 112., 160.)[instance % 4] * 1e-9)
    ramp_s = float((2., 5., 10.)[instance % 3] * 1e-9)
    depth = float(rng.uniform(.8e9, 1.45e9))
    event = (t >= start) & (t < start + duration)
    noise_sd = float(rng.uniform(.1, .28))
    noise = rng.normal(0., noise_sd, COUNT)
    phi = rng.uniform(-np.pi, np.pi, 2)
    ratio = float((.58, .72, .86, .96)[instance % 4])
    curvature_width_s = float((32., 55., 85., 125.)[instance % 4] * 1e-9)
    envelope_sigma = float((.15, .4, .75, 1.1)[instance % 4])
    if family == "normal_platform":
        target[:] = base
        event[:] = False
    elif family == "normal_fast_step":
        target = upper - depth * np.clip((t - start) / ramp_s, 0, 1)
        event = (t >= start) & (t <= start + ramp_s)
    elif family in ("normal_fast_return", "return_faint", "return_coherent",
                    "return_anchor_exchange"):
        shape = np.minimum(np.clip((t - start) / ramp_s, 0, 1),
                           np.clip((start + duration - t) / ramp_s, 0, 1))
        target = upper - depth * shape
        competitor = upper.copy()
        if family == "return_faint":
            b[:] = rng.uniform(.25, .43)
        elif family == "return_coherent":
            b[:] = ratio
            # Explicit phase strata expose same-frequency constructive interference.
            phi[:] = (0., (0., np.pi / 2, np.pi)[instance % 3])
        elif family == "return_anchor_exchange":
            # Left anchors mostly target; right anchors mostly competitor. Same band.
            transition = np.clip((t - start) / duration, 0, 1)
            a = 1.15 - .98 * transition
            a[event] = 1.05
            b = .08 + 1.02 * transition
            b[event] = ratio
    elif family in ("quadratic_clean", "quadratic_competition", "curved_return"):
        center = start + duration / 2
        x = (t - center) / curvature_width_s
        if family == "curved_return":
            shape = np.exp(-.5 * x**2)
        else:
            shape = np.maximum(0., 1 - x**2)
        target = upper - depth * shape
        event = abs(x) < (3 if family == "curved_return" else 1)
        if family == "quadratic_competition":
            b[:] = .12
            b[(t >= center - 20e-9) & (t < center + 35e-9)] = 1.8
        elif family == "curved_return":
            competitor = upper.copy()
            b[:] = ratio
    elif family in ("amplitude_decay", "amplitude_valley", "asymmetric_envelope",
                    "speckle_proxy"):
        b[:] = .18
        b[event] = 1.65
        if family == "amplitude_decay":
            a = 1.4 * np.exp(-t / (450e-9 + instance % 3 * 150e-9))
        elif family == "amplitude_valley":
            floor = (.05, .15, .35, .6)[instance % 4]
            a = 1 - (1 - floor) * np.exp(-.5 * ((t-start-duration/2)/35e-9)**2)
            b[event] = .75
        elif family == "asymmetric_envelope":
            a = np.where(t < start, 1.25,
                         np.where(t > start + duration, .35 + .3 * (instance % 4), .9))
        else:
            # A finite random Fourier envelope, explicitly not a speckle law.
            periods = rng.uniform(12e-9, 110e-9, 6)
            phases = rng.uniform(-np.pi, np.pi, 6)
            log_envelope = sum(np.sin(2*np.pi*t/p + q)
                               for p, q in zip(periods, phases, strict=True)) / np.sqrt(3)
            a = np.clip(np.exp(envelope_sigma * log_envelope), .03, 3.5)
    elif family == "wrong_burst":
        b[:] = .25
        b[event] = rng.uniform(1.5, 2.3)
    elif family == "branch_approach":
        center = start + duration / 2
        competitor = upper + .95e9 - (.82e9 + .03e9 * (instance % 4)) * np.exp(
            -.5 * ((t-center)/45e-9)**2)
        b[:] = .5
        b[event] = 1.5
    elif family == "anchor_switch":
        center = start + duration / 2
        competitor = upper + .9e9 * np.tanh((t-center)/45e-9)
        a[:] = .8
        b = np.where(t < center, 1.1, .55)
    elif family in ("long_wrong", "edge_wrong"):
        duration = float((230., 300., 370., 440.)[instance % 4] * 1e-9)
        start = (float(rng.uniform(100e-9, 160e-9)) if family == "long_wrong"
                 else (0. if instance % 2 == 0 else 800e-9-duration))
        event = (t >= start) & (t < start + duration)
        b[:] = .2
        b[event] = 1.8
    elif family in ("coherent_nontarget", "colored_noise"):
        a[:] = 0
        event[:] = True
        if family == "coherent_nontarget":
            b[:] = 1.
        else:
            noise += 2 * np.convolve(rng.normal(0., 1., COUNT), np.ones(9)/3, mode="same")
    phase = oscillator_phase(target, phase0=float(phi[0]))
    other_phase = oscillator_phase(competitor, phase0=float(phi[1]))
    voltage = a * np.cos(phase) + b * np.cos(other_phase) + noise
    present = a > 0
    truth = np.where(present, target, np.nan)
    fast = np.r_[False, abs(np.diff(target)) * FS_HZ > 5e15] & present
    params = dict(generator="D002_fresh_voltage", sample_rate_hz=FS_HZ, count=COUNT,
                  base_hz=base, linear_slope_hz_per_s=slope, start_s=start, duration_s=duration,
                  ramp_s=ramp_s, depth_hz=depth, competitor_ratio=ratio,
                  curvature_width_s=curvature_width_s, envelope_sigma=envelope_sigma,
                  noise_sd_v=noise_sd, phase_target_rad=float(phi[0]),
                  phase_competitor_rad=float(phi[1]), amplitude_min_v=float(a.min()),
                  amplitude_max_v=float(a.max()), speckle_statistics_validated=False)
    return Case(f"D002_{split}_{family}_{instance:02d}", family, split, instance, seed,
                SignalRecord(t, voltage), truth, present, event, fast, present & ~event,
                params, a, competitor, b)


def frame_labels(case: Case, time_s: FloatArray, window_samples: int) -> dict[str, Any]:
    index = np.rint(time_s * FS_HZ).astype(int)
    lo = np.maximum(0, index - window_samples // 2)
    hi = np.minimum(COUNT, index + window_samples // 2)

    def window_any(mask: BoolArray) -> BoolArray:
        cumulative = np.r_[0, np.cumsum(mask)]
        return np.asarray(cumulative[hi] - cumulative[lo] > 0)

    fast_support = window_any(case.fast)
    focus_support = window_any(case.focus)
    return dict(truth=case.truth_hz[index], present=case.target_present[index],
                focus=focus_support, fast=fast_support,
                normal=case.normal[index] & ~focus_support & ~fast_support,
                weak=case.target_amplitude_v[index] < .2,
                target_amplitude_v=case.target_amplitude_v[index],
                competitor_hz=case.competitor_hz[index],
                competitor_amplitude_v=case.competitor_amplitude_v[index])


def metrics(path: FloatArray, reference: FloatArray, labels: dict[str, Any]) -> dict[str, Any]:
    truth = labels["truth"]
    valid = np.isfinite(truth)
    error, old_error = abs(path-truth), abs(reference-truth)
    wrong = ~np.isfinite(path) | (error > TOLERANCE_HZ)
    old_wrong = ~np.isfinite(reference) | (old_error > TOLERANCE_HZ)
    changed = path != reference
    normal = valid & labels["normal"]
    fast = valid & labels["fast"]
    correct_normal = normal & ~old_wrong
    correct_fast = fast & ~old_wrong
    finite = valid & np.isfinite(path)
    return dict(frames=len(path), truth_frames=int(valid.sum()), finite_frames=int(
        np.isfinite(path).sum()), sse_hz2=float(np.sum((path[finite]-truth[finite])**2)),
        squared_error_frames=int(finite.sum()), wrong_frames=int((valid & wrong).sum()),
        interventions=int(changed.sum()), truth_interventions=int((changed & valid).sum()),
        corrected_frames=int((valid & old_wrong & ~wrong).sum()),
        harmed_frames=int((valid & ~old_wrong & wrong).sum()),
        worsened_error_frames=int((valid & changed & (error-old_error > 1e6)).sum()),
        normal_all=int(normal.sum()), normal_wrong=int((normal & wrong).sum()),
        normal_frames=int(correct_normal.sum()),
        normal_preserved=int((correct_normal & ~changed).sum()),
        normal_exact_all=int((normal & ~changed).sum()),
        fast_all=int(fast.sum()), fast_wrong=int((fast & wrong).sum()),
        fast_frames=int(correct_fast.sum()), fast_preserved=int((correct_fast & ~changed).sum()),
        focus_frames=int((valid & labels["focus"]).sum()),
        focus_wrong=int((valid & labels["focus"] & wrong).sum()))


def ratios(row: dict[str, Any]) -> dict[str, float | None]:
    def divide(a: str, b: str) -> float | None:
        return float(row[a]/row[b]) if row[b] else None
    mse = divide("sse_hz2", "squared_error_frames")
    return dict(rmse_hz=float(np.sqrt(mse)) if mse is not None else None,
                wrong_branch_fraction=divide("wrong_frames", "truth_frames"),
                coverage=divide("finite_frames", "frames"),
                intervention_precision=divide("corrected_frames", "truth_interventions"),
                harm_per_intervention=divide("harmed_frames", "truth_interventions"),
                normal_preservation=divide("normal_preserved", "normal_frames"),
                fast_preservation=divide("fast_preserved", "fast_frames"),
                normal_truth_accuracy=(1-row["normal_wrong"]/row["normal_all"]
                                       if row["normal_all"] else None),
                fast_truth_accuracy=(1-row["fast_wrong"]/row["fast_all"]
                                     if row["fast_all"] else None))


def observational_flags(peaks: RidgeCandidateSet, strongest: FloatArray,
                        p3: FloatArray) -> tuple[tuple[str, ...], ...]:
    """Fixed diagnostics only. They never alter a candidate or certify identity."""
    output = []
    for i, frame in enumerate(peaks.candidates_by_frame):
        selected = min(frame, key=lambda c: abs(c.transition_frequency_hz-p3[i]))
        alternatives = [c for c in frame if abs(c.transition_frequency_hz-p3[i]) > TOLERANCE_HZ]
        flags = []
        if abs(p3[i]-strongest[i]) > TOLERANCE_HZ:
            flags.append("P3_DISAGREES_STRONGEST")
        if selected.peak_to_background_db < 12:
            flags.append("P3_LOW_BACKGROUND_SUPPORT")
        if any(c.peak_to_background_db >= 12 and c.peak_amplitude >= .55 * selected.peak_amplitude
               for c in alternatives):
            flags.append("COMPETING_OBSERVED_BAND")
        output.append(tuple(flags))
    return tuple(output)


def proposal_truth_audit(proposal: Proposal, peaks: RidgeCandidateSet,
                         labels: dict[str, Any], stride: int, p3: FloatArray) -> dict[str, Any]:
    """Post-estimation synthetic audit; never called inside an estimator."""
    count = 4  # Caller verifies the frozen configuration has four anchors.
    left = proposal.first-stride*np.arange(1, count+1)
    right = proposal.stop+stride*np.arange(1, count+1)
    anchor_rows = []
    for side, indices in (("left", left), ("right", right)):
        for index in indices:
            i = int(index)
            c = min(peaks.candidates_by_frame[i], key=lambda c: abs(c.transition_frequency_hz-p3[i]))
            target_distance = abs(c.transition_frequency_hz-labels["truth"][i])
            other_distance = abs(c.transition_frequency_hz-labels["competitor_hz"][i])
            cofrequency = bool(target_distance <= TOLERANCE_HZ and other_distance <= TOLERANCE_HZ)
            identity = ("COFREQUENCY_UNIDENTIFIABLE" if cofrequency else
                        "TARGET_NEAR" if target_distance <= TOLERANCE_HZ else
                        "COMPETITOR_NEAR" if other_distance <= TOLERANCE_HZ else "OTHER")
            anchor_rows.append(dict(side=side, frame=i, time_s=float(peaks.time_s[i]),
                frequency_hz=float(p3[i]), amplitude_v=float(c.peak_amplitude),
                background_db=float(c.peak_to_background_db), identity=identity,
                target_hz=float(labels["truth"][i]) if np.isfinite(labels["truth"][i]) else None,
                competitor_hz=float(labels["competitor_hz"][i]),
                target_amplitude_v=float(labels["target_amplitude_v"][i]),
                competitor_amplitude_v=float(labels["competitor_amplitude_v"][i])))
    return dict(anchors=anchor_rows, anchor_identity_observable=False,
                target_near_anchors=sum(r["identity"] == "TARGET_NEAR" for r in anchor_rows),
                cofrequency_anchors=sum(r["identity"] == "COFREQUENCY_UNIDENTIFIABLE"
                                        for r in anchor_rows))
