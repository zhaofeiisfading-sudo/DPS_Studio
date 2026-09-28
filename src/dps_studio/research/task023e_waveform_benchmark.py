"""Physically sampled synthetic inputs for TASK-023E, never fitted to real ch3.

No tracker outputs define truth. Target and nuisance oscillator identities are
explicit. Label-swap pairs intentionally cannot be resolved from the voltage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast

import numpy as np

from dps_studio.core.analysis_profiles import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE, AnalysisProfile
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidateSet, extract_global_path_candidates
from dps_studio.core.time_frequency import STFTResult, compute_stft

SAMPLE_RATE_HZ = 40e9
SAMPLE_COUNT = 80000
FAMILIES = (
    "separated_edges", "divergence", "merge_crossing", "internal_wrong_core",
    "amplitude_exchange", "transient_leakage", "correct_and_fast", "dropout_noise",
)
PROFILES = (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)


@dataclass(frozen=True)
class WaveformCase:
    case_id: str
    family: str
    instance: int
    split: str
    seed: int
    record: SignalRecord
    truth_hz: np.ndarray
    nuisance_hz: np.ndarray
    focus: np.ndarray
    parameters: dict[str, Any]
    observation_group: str


def oscillator_phase(
    frequency_hz: np.ndarray, sample_rate_hz: float = SAMPLE_RATE_HZ, phase0: float = 0.0,
) -> np.ndarray:
    """Integrate a piecewise-constant instantaneous frequency on the sample grid."""
    frequency_hz = np.asarray(frequency_hz, dtype=float)
    if frequency_hz.ndim != 1 or not np.all(np.isfinite(frequency_hz)):
        raise ValueError("Frequency must be a finite one-dimensional array")
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("Sample rate must be positive")
    return cast(np.ndarray, phase0 + 2 * np.pi * np.r_[0.0, np.cumsum(frequency_hz[:-1])] / sample_rate_hz)


def generate_case(family: str, instance: int, seed: int | None = None) -> WaveformCase:
    if family not in FAMILIES or not 0 <= instance < 24:
        raise ValueError("Expected a fixed family and instance in [0, 24)")
    family_index = FAMILIES.index(family)
    seed = 2305000 + family_index * 100 + instance if seed is None else seed
    rng = np.random.default_rng(seed)
    t = np.arange(SAMPLE_COUNT) / SAMPLE_RATE_HZ
    duration = rng.uniform(20e-9, 150e-9)
    center = rng.uniform(0.6e-6, 1.4e-6)
    amplitude_ratio = rng.uniform(0.6, 2.0)
    noise_sd = rng.uniform(0.05, 0.5)
    # Both slope signs occur, independently of target/nuisance identity.
    base = rng.uniform(1.8e9, 3.0e9)
    slope = rng.uniform(-0.5e15, 0.5e15)
    target = np.clip(base + slope * (t - 1e-6), 0.5e9, 5.5e9)
    nuisance = np.clip(target + rng.choice([-1, 1]) * rng.uniform(0.6e9, 1.4e9),
                       0.5e9, 5.5e9)
    target_amplitude = np.ones(SAMPLE_COUNT)
    nuisance_amplitude = np.zeros(SAMPLE_COUNT)
    focus = (t >= center) & (t < center + duration)
    truth = target.copy()
    variant = family
    if family == "separated_edges":
        leading = instance % 2 == 0
        focus = t < duration if leading else t >= 2e-6 - duration
        nuisance_amplitude[focus] = amplitude_ratio
        variant = "leading" if leading else "trailing"
    elif family == "divergence":
        ramp = np.clip((t - center) / duration, 0, 1)
        nuisance = np.clip(target + rng.choice([-1, 1]) * 1.2e9 * ramp, 0.5e9, 5.5e9)
        nuisance_amplitude[focus] = amplitude_ratio
    elif family == "merge_crossing":
        crossing = instance % 2 == 1
        ramp = np.clip((t - center) / duration, 0, 1)
        nuisance = np.clip(target + 1.2e9 * (1 - (2 if crossing else 1) * ramp),
                           0.5e9, 5.5e9)
        nuisance_amplitude[focus] = amplitude_ratio
        variant = "crossing" if crossing else "merge"
    elif family == "internal_wrong_core":
        nuisance_amplitude[focus] = amplitude_ratio
    elif family == "amplitude_exchange":
        nuisance_amplitude[focus] = amplitude_ratio
        target_amplitude[focus] = 0.2
    elif family == "transient_leakage":
        nuisance_amplitude[focus] = amplitude_ratio
        # Short coherent bursts yield window leakage; white burst yields broad spectrum.
        nuisance_amplitude *= (np.sin(2 * np.pi * (t - center) / 5e-9) > 0)
    elif family == "correct_and_fast":
        variant = "correct" if instance % 2 == 0 else "fast_descent"
        if variant == "fast_descent":
            ramp = np.clip((t - center) / duration, 0, 1)
            target = 5.0e9 - 4.3e9 * ramp
            truth = target.copy()
        nuisance_amplitude[:] = 0.15
        focus[:] = True
    elif family == "dropout_noise":
        variant = "dropout" if instance % 2 == 0 else "pure_noise"
        if variant == "pure_noise":
            focus[:] = True
        target_amplitude[focus] = 0
        truth[focus] = np.nan
    noise = rng.normal(0, noise_sd, SAMPLE_COUNT)
    if family == "transient_leakage":
        noise[focus] += rng.normal(0, 2.0, np.count_nonzero(focus))
    phase0 = rng.uniform(-np.pi, np.pi, 2)
    voltage = (
        target_amplitude * np.cos(oscillator_phase(target, phase0=phase0[0]))
        + nuisance_amplitude * np.cos(oscillator_phase(nuisance, phase0=phase0[1])) + noise
    )
    case_id = f"E23_{family}_{instance:02d}"
    return WaveformCase(
        case_id, family, instance, "CALIBRATION" if instance < 8 else "FRESH_HELD_OUT",
        seed, SignalRecord(t, voltage, source_path=f"synthetic/{case_id}.npz"),
        truth, nuisance, focus,
        {"duration_s": duration, "center_s": center, "amplitude_ratio": amplitude_ratio,
         "noise_sd_v": noise_sd, "variant": variant, "base_hz": base,
         "slope_hz_per_s": slope}, case_id,
    )


def ambiguous_pair(index: int) -> tuple[WaveformCase, ...]:
    """Same two equally persistent oscillators; only target identity changes."""
    if not 0 <= index < 16:
        raise ValueError("Expected ambiguity index in [0, 16)")
    rng = np.random.default_rng(2390000 + index)
    t = np.arange(SAMPLE_COUNT) / SAMPLE_RATE_HZ
    first = np.full(SAMPLE_COUNT, rng.uniform(1e9, 2e9))
    second = np.full(SAMPLE_COUNT, rng.uniform(3e9, 4e9))
    voltage = np.cos(oscillator_phase(first)) + np.cos(oscillator_phase(second, phase0=0.7))
    voltage += rng.normal(0, 0.1, SAMPLE_COUNT)
    group = f"E23_AMBIGUOUS_{index:02d}"
    record = SignalRecord(t, voltage, source_path=f"synthetic/{group}.npz")
    return tuple(WaveformCase(
        f"{group}_{label}", "ambiguity_label_swap", index, "AMBIGUITY_DIAGNOSTIC",
        2390000 + index, record, truth, other, np.ones(SAMPLE_COUNT, dtype=bool),
        {"identifiability": "UNIDENTIFIABLE_FROM_OBSERVATION", "target_label": label}, group,
    ) for label, truth, other in (("A", first, second), ("B", second, first)))


def array_hash(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def profile_input(
    case: WaveformCase, profile: AnalysisProfile,
) -> tuple[STFTResult, RidgeCandidateSet, np.ndarray, np.ndarray]:
    """Unmodified production STFT function and original main Top-20 extraction."""
    stft = compute_stft(
        case.record, window_length_samples=profile.window_length_samples,
        overlap_samples=profile.overlap_samples, nfft=profile.nfft,
        window_name=profile.window_name,
    )
    candidates = extract_global_path_candidates(
        stft, minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz, config=GlobalPathConfig(top_k=20),
    )
    sample_indices = np.rint(stft.time_s * SAMPLE_RATE_HZ).astype(int)
    return stft, candidates, case.truth_hz[sample_indices], case.focus[sample_indices]


def strongest_metrics(case: WaveformCase, profile: AnalysisProfile) -> dict[str, Any]:
    stft, candidates, truth, focus = profile_input(case, profile)
    strongest = np.array([frame[0].transition_frequency_hz if frame else np.nan
                          for frame in candidates.candidates_by_frame])
    valid = np.isfinite(truth)
    selected = np.isfinite(strongest)
    comparable = valid & selected
    errors = strongest[comparable] - truth[comparable]
    available = np.array([any(abs(c.transition_frequency_hz - truth[i]) <= 200e6 for c in frame)
                          for i, frame in enumerate(candidates.candidates_by_frame)])
    return {
        "case_id": case.case_id, "family": case.family, "variant": case.parameters["variant"],
        "split": case.split, "observation_group": case.observation_group,
        "profile": profile.profile_id.value, "method": "STRONGEST_ONLY_PHASE_B",
        "frames": len(truth), "truth_frames": int(valid.sum()),
        "truth_selected_frames": int(comparable.sum()), "coverage": float(selected.mean()),
        "truth_coverage": float(comparable.sum() / valid.sum()) if valid.any() else None,
        "squared_error_sum_hz2": float(np.sum(errors ** 2)),
        "rmse_hz": float(np.sqrt(np.mean(errors ** 2))) if errors.size else None,
        "wrong_branch_count": int(np.sum(np.abs(errors) > 200e6)),
        "wrong_branch_fraction": float(np.mean(np.abs(errors) > 200e6)) if errors.size else None,
        "candidate_available_truth_frames": int(np.sum(available & valid)),
        "no_target_frames": int((~valid).sum()), "focus_frames": int(focus.sum()),
        "modification_fraction": 0.0, "corrected_frames": 0, "harmed_frames": 0,
        "intervention_precision": None, "intervention_harm_rate": None,
        "no_target_quality_reference": "NO_SIGNAL" if (~valid).any() else "NOT_APPLICABLE",
        "quality_reference_origin": "GENERATOR_TRUTH_NOT_ALGORITHM_DETECTION",
        "stft_sha256": array_hash(stft.spectrum), "strongest_sha256": array_hash(strongest),
    }
