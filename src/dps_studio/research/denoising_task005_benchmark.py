"""Small, independent known-truth voltage checks for the TASK005 real-data study.

These synthetic cases are auxiliary checks, not evidence of real-data accuracy.
The close approach and rapid return deliberately expose resolution and slope-gate
limitations. Frequencies and envelopes generate voltage directly; no ridge or
candidate is fabricated. The only identity cue is a coarse frequency at 100 ns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

import numpy as np
from numpy.typing import ArrayLike, NDArray

from dps_studio.core.models import SignalRecord

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

FAMILIES = (
    "persistent_competitor",
    "curved_competitor",
    "normal_chirp",
    "target_absence",
    "resolved_approach",
    "rapid_return",
)
SAMPLE_RATE_HZ = 40e9
SAMPLE_COUNT = 32000
SEED_TIME_S = 100e-9


class RegistrationRow(TypedDict):
    case_id: str
    family: str
    instance: int
    seed: int


class FrameTruth(TypedDict):
    truth_hz: FloatArray
    target_absent: BoolArray
    mixed_window: BoolArray


@dataclass(frozen=True, eq=False)
class Case:
    """Voltage and scoring-only truth; truth must not enter the inference path."""

    case_id: str
    family: str
    seed: int
    record: SignalRecord
    truth_frequency_hz: FloatArray
    target_present: BoolArray
    target_amplitude_v: FloatArray
    seed_time_s: float
    seed_frequency_hz: float
    parameters: dict[str, object]


def _case_id(family: str, seed: int) -> str:
    return f"task005_{family}_{seed}"


def registration() -> list[RegistrationRow]:
    """Return the fixed twelve-case registration without generating or scoring it."""
    return [
        {
            "case_id": _case_id(family, seed),
            "family": family,
            "instance": instance,
            "seed": seed,
        }
        for family_index, family in enumerate(FAMILIES)
        for instance in range(2)
        for seed in (53051000 + 100 * family_index + instance,)
    ]


def _phase(frequency_hz: FloatArray, initial_phase_rad: float) -> FloatArray:
    """Integrate sample-frequency values with the composite trapezoidal rule."""
    phase = np.empty_like(frequency_hz)
    phase[0] = initial_phase_rad
    phase[1:] = initial_phase_rad + (2 * np.pi / SAMPLE_RATE_HZ) * np.cumsum(
        0.5 * (frequency_hz[:-1] + frequency_hz[1:])
    )
    return phase


def generate(family: str, seed: int) -> Case:
    """Synthesize reproducible SI voltage from two phases plus white Gaussian noise.

    Mild seed variation changes the base frequencies, amplitudes, noise and phase.
    Event times and absence boundaries remain fixed. The rapid-return excursion
    has 20 ns linear ramps and a nominal 5e16 Hz/s rate, above the frozen gate.
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown TASK005 auxiliary family: {family!r}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    rng = np.random.default_rng(seed)
    time_s = np.arange(SAMPLE_COUNT, dtype=np.float64) / SAMPLE_RATE_HZ
    frequency_shift_hz = float(rng.uniform(-20e6, 20e6))
    competitor_base_hz = float(1.7e9 + rng.uniform(-20e6, 20e6))
    target_level_v = float(rng.uniform(0.9, 1.1))
    noise_std_v = float(rng.uniform(0.1, 0.18))
    target_phase_rad = float(rng.uniform(-np.pi, np.pi))
    competitor_phase_rad = float(rng.uniform(-np.pi, np.pi))

    target_hz = 2.6e9 + frequency_shift_hz + 0.8e9 * time_s / 800e-9
    competitor_hz = np.full(SAMPLE_COUNT, competitor_base_hz, dtype=np.float64)
    target_amplitude_v = np.full(SAMPLE_COUNT, target_level_v, dtype=np.float64)
    competitor_amplitude_v = np.full(SAMPLE_COUNT, 0.15, dtype=np.float64)
    parameters: dict[str, object] = {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": SAMPLE_COUNT,
        "frequency_shift_hz": frequency_shift_hz,
        "competitor_base_hz": competitor_base_hz,
        "target_level_v": target_level_v,
        "noise_std_v": noise_std_v,
        "target_initial_phase_rad": target_phase_rad,
        "competitor_initial_phase_rad": competitor_phase_rad,
        "phase_integration": "composite_trapezoidal",
        "seed_frequency_quantum_hz": 50e6,
    }

    if family == "persistent_competitor":
        event = (time_s >= 220e-9) & (time_s < 650e-9)
        competitor_amplitude_v[event] = 1.7
        parameters.update(event_start_s=220e-9, event_end_s=650e-9,
                          competitor_event_amplitude_v=1.7)
    elif family == "curved_competitor":
        target_hz = 2.8e9 + frequency_shift_hz + 0.55e9 * np.sin(
            2 * np.pi * (time_s - 100e-9) / 1000e-9
        )
        event = (time_s >= 180e-9) & (time_s < 650e-9)
        competitor_amplitude_v[event] = 1.6
        parameters.update(event_start_s=180e-9, event_end_s=650e-9,
                          competitor_event_amplitude_v=1.6,
                          target_sinusoid_amplitude_hz=0.55e9,
                          target_sinusoid_period_s=1000e-9)
    elif family == "normal_chirp":
        target_hz = 2.8e9 + frequency_shift_hz + 0.6e9 * (time_s / 800e-9) ** 2
        competitor_amplitude_v.fill(0.1)
        parameters.update(competitor_amplitude_v=0.1, target_quadratic_scale_hz=0.6e9)
    elif family == "target_absence":
        target_amplitude_v[(time_s >= 330e-9) & (time_s < 480e-9)] = 0.0
        event = (time_s >= 220e-9) & (time_s < 650e-9)
        competitor_amplitude_v[event] = 1.3
        parameters.update(absence_start_s=330e-9, absence_end_s=480e-9,
                          event_start_s=220e-9, event_end_s=650e-9,
                          competitor_event_amplitude_v=1.3)
    elif family == "resolved_approach":
        offset_hz = 0.7e9 - 0.64e9 * np.exp(-0.5 * ((time_s - 400e-9) / 60e-9) ** 2)
        competitor_hz = target_hz + offset_hz
        event = (time_s >= 180e-9) & (time_s < 650e-9)
        competitor_amplitude_v[event] = 1.3
        parameters.update(event_start_s=180e-9, event_end_s=650e-9,
                          competitor_event_amplitude_v=1.3,
                          closest_approach_time_s=400e-9,
                          approach_width_s=60e-9, minimum_separation_hz=60e6,
                          limitation="locally unresolved approach can exchange branches")
    else:  # rapid_return
        excursion = np.clip((time_s - 280e-9) / 20e-9, 0.0, 1.0)
        excursion -= np.clip((time_s - 330e-9) / 20e-9, 0.0, 1.0)
        target_hz = target_hz - 1e9 * excursion
        competitor_amplitude_v.fill(0.1)
        parameters.update(drop_start_s=280e-9, drop_end_s=300e-9,
                          return_start_s=330e-9, return_end_s=350e-9,
                          excursion_hz=1e9, ramp_duration_s=20e-9,
                          limitation="ramp rate exceeds the frozen slope gate")

    voltage_v = (
        target_amplitude_v * np.cos(_phase(target_hz, target_phase_rad))
        + competitor_amplitude_v * np.cos(_phase(competitor_hz, competitor_phase_rad))
        + rng.normal(0.0, noise_std_v, SAMPLE_COUNT)
    )
    present = target_amplitude_v > 0
    # Immutable buffers keep the scoring reference detached from inference.
    truth = np.frombuffer(np.where(present, target_hz, np.nan).tobytes(), dtype=np.float64)
    present = np.frombuffer(present.tobytes(), dtype=np.bool_)
    target_amplitude_v = np.frombuffer(target_amplitude_v.tobytes(), dtype=np.float64)
    seed_index = int(np.rint(SEED_TIME_S * SAMPLE_RATE_HZ))
    seed_frequency_hz = float(np.rint(target_hz[seed_index] / 50e6) * 50e6)
    return Case(
        case_id=_case_id(family, seed), family=family, seed=seed,
        record=SignalRecord(time_s, voltage_v, metadata={
            "synthetic": True, "family": family, "seed": seed,
            "generator": "denoising_task005_benchmark",
        }),
        truth_frequency_hz=truth, target_present=present,
        target_amplitude_v=target_amplitude_v, seed_time_s=SEED_TIME_S,
        seed_frequency_hz=seed_frequency_hz, parameters=parameters,
    )


def _float_vector(value: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or np.isinf(array).any():
        raise ValueError(f"{name} must be a one-dimensional vector of finite values or NaNs")
    return array


def frame_truth(case: Case, stft_time_s: ArrayLike, window_samples: int) -> FrameTruth:
    """Label full absent windows separately from mixed presence/absence windows.

    A frame uses the nearest sample as its center and ``window_samples // 2``
    samples before it. Support is clipped to the recorded samples at the edges.
    TASK005's unpadded STFT uses complete windows, so clipping is normally unused.
    Mixed windows have no scalar scoring truth and are not pure absence frames.
    """
    times = _float_vector(stft_time_s, "stft_time_s")
    if not np.isfinite(times).all():
        raise ValueError("stft_time_s must contain only finite values")
    if (isinstance(window_samples, bool) or not isinstance(window_samples, int)
            or not 0 < window_samples <= case.record.sample_count):
        raise ValueError("window_samples must be a positive integer no longer than the record")
    if np.any((times < case.record.start_time_s) | (times > case.record.end_time_s)):
        raise ValueError("stft_time_s must lie inside the record")
    centers = np.rint((times - case.record.start_time_s) * SAMPLE_RATE_HZ).astype(np.int64)
    starts = np.maximum(0, centers - window_samples // 2)
    stops = np.minimum(case.record.sample_count, centers - window_samples // 2 + window_samples)
    prefix = np.concatenate((np.zeros(1, dtype=np.int64),
                             np.cumsum(case.target_present, dtype=np.int64)))
    present_count = prefix[stops] - prefix[starts]
    absent = present_count == 0
    mixed = (present_count > 0) & (present_count < stops - starts)
    truth = np.where(absent | mixed, np.nan, case.truth_frequency_hz[centers])
    return {"truth_hz": truth, "target_absent": absent, "mixed_window": mixed}


def score_path(
    output: ArrayLike,
    truth: ArrayLike,
    baseline: ArrayLike | None = None,
    tolerance_hz: float = 100e6,
    absent_mask: ArrayLike | None = None,
) -> dict[str, int | float]:
    """Score finite errors and missing present outputs with separate denominators.

    RMSE uses finite present outputs; failure rate includes every missing present
    output. Empty denominators return NaN. Pass pure-absence frame labels from
    ``frame_truth`` so mixed windows do not count as absence false positives.
    """
    predicted = _float_vector(output, "output")
    reference = _float_vector(truth, "truth")
    if predicted.shape != reference.shape:
        raise ValueError("output and truth must have aligned shapes")
    if not np.isfinite(tolerance_hz) or tolerance_hz <= 0:
        raise ValueError("tolerance_hz must be finite and positive")
    present = np.isfinite(reference)
    finite = np.isfinite(predicted)
    if absent_mask is None:
        absent = ~present
    else:
        absent = np.asarray(absent_mask)
        if absent.shape != reference.shape or absent.dtype.kind != "b":
            raise ValueError("absent_mask must be a boolean vector aligned with truth")
        if np.any(absent & present):
            raise ValueError("absent_mask cannot mark frames with finite truth")
    error_hz = np.abs(predicted - reference)
    correct = present & finite & (error_hz <= tolerance_hz)
    wrong = present & finite & (error_hz > tolerance_hz)
    missing = present & ~finite
    corrected = harmed = abstained = 0
    if baseline is not None:
        previous = _float_vector(baseline, "baseline")
        if previous.shape != reference.shape:
            raise ValueError("baseline must be aligned with truth")
        previous_error_hz = np.abs(previous - reference)
        previous_correct = present & np.isfinite(previous) & (previous_error_hz <= tolerance_hz)
        previous_wrong = present & np.isfinite(previous) & (previous_error_hz > tolerance_hz)
        corrected = int(np.count_nonzero(previous_wrong & correct))
        harmed = int(np.count_nonzero(previous_correct & wrong))
        abstained = int(np.count_nonzero(previous_correct & missing))
    present_count = int(np.count_nonzero(present))
    finite_count = int(np.count_nonzero(present & finite))
    wrong_count = int(np.count_nonzero(wrong))
    missing_count = int(np.count_nonzero(missing))
    errors = predicted[present & finite] - reference[present & finite]
    sum_squared_error_hz2 = float(np.dot(errors, errors))
    return {
        "present_frames": present_count,
        "finite_present_frames": finite_count,
        "coverage": finite_count / present_count if present_count else float("nan"),
        "wrong_frames": wrong_count,
        "missing_frames": missing_count,
        "failure_frames": wrong_count + missing_count,
        "failure_rate": (wrong_count + missing_count) / present_count
        if present_count else float("nan"),
        "rmse_hz": float(np.sqrt(sum_squared_error_hz2 / finite_count))
        if finite_count else float("nan"),
        "sum_squared_error_hz2": sum_squared_error_hz2,
        "corrected_frames": corrected,
        "harmed_frames": harmed,
        "abstained_previously_correct": abstained,
        "finite_absent_frames": int(np.count_nonzero(absent & finite)),
    }
