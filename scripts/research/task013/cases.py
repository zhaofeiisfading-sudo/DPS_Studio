"""Frozen old waveforms plus independently seeded stage-specific simulations."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Signal
from .stage import Annotation, Float

ROOT = Path(__file__).resolve().parents[3]
VELOCITY = 1550e-9 / 2
FAMILIES = ("static_unobservable", "low_plateau", "onset_step", "fast_accel", "fast_decel",
            "turnaround", "stable_plateau", "weak_spur", "drifting_spur", "target_in_prefix",
            "dropout", "phase_reset", "gradual_onset", "crossing", "colored_noise", "noise_only")


@dataclass
class Case:
    signal: Signal
    truth_hz: Float
    other_hz: Float
    amplitude_v: Float
    plan: tuple[Annotation, ...]
    stage_truth: np.ndarray[Any, np.dtype[np.str_]]
    onset_s: float | None
    family: str
    split: str
    metadata: dict[str, Any]


def make_plan(time_s: Float, events: list[tuple[float, str, str, bool]],
              seed: int, jitter_ns: float = 2.) -> tuple[Annotation, ...]:
    rng = np.random.default_rng(seed + 931)
    starts = [float(time_s[0])]
    starts += [float(e[0] + rng.uniform(-jitter_ns, jitter_ns) * 1e-9) for e in events[1:]]
    ends = starts[1:] + [float(time_s[-1] + np.median(np.diff(time_s)))]
    if np.any(np.diff(starts) <= 0):
        raise ValueError("Jitter reordered manually declared segments")
    return tuple(Annotation(start, end, event[1], event[2], event[3])
                 for start, end, event in zip(starts, ends, events, strict=True))


def truth_labels(time_s: Float, events: list[tuple[float, str, str, bool]]) -> np.ndarray[
        Any, np.dtype[np.str_]]:
    result = np.full(len(time_s), events[0][1], dtype="U32")
    for start, stage, _, _ in events:
        result[time_s >= start] = stage
    return result


def fresh(family: str, instance: int, *, development: bool = False) -> Case:
    # Reserve disjoint blocks for every family across development/evaluation.
    # 16 families occupy <16000 seeds, so a 100000 offset prevents cross-family reuse.
    seed = (81300000 if development else 81400000) + 1000 * FAMILIES.index(family) + instance
    rng = np.random.default_rng(seed)
    fs, n = 40e9, 12800
    t = np.arange(n, dtype=np.float64) / fs
    t0 = (60 + rng.uniform(-1., 1.)) * 1e-9
    elapsed = np.maximum(t - t0, 0.)
    active = t >= t0
    velocity = np.full(n, 600.)
    amp = np.full(n, .035)
    other = np.full(n, np.nan)
    snr, cutoff = 12., 0.
    onset: float | None = float(t0)
    events = [(0., "stationary", "unobservable", False),
              (t0, "onset", "good", False), (t0 + 8e-9, "plateau", "good", False)]
    if family == "static_unobservable":
        velocity[:] = 0.
        active[:] = True
        onset = None
        events = [(0., "stationary", "unobservable", False)]
    elif family == "low_plateau":
        velocity[:] = (15., 30., 60., 120.)[instance % 4]
        cutoff = (0., 2e6, 15e6, 50e6)[(instance // 4) % 4]
        snr = (8., 16.)[instance % 2]
        active[:] = True
        onset = None
        events = [(0., "low_frequency", "good", False)]
    elif family == "fast_accel":
        velocity = np.minimum(1700., 80. + elapsed * (35e9 + 10e9 * (instance % 3)))
        end = t0 + 1620. / (35e9 + 10e9 * (instance % 3))
        events[-1] = (t0 + 8e-9, "acceleration", "good", False)
        events.append((end, "plateau", "good", False))
    elif family == "fast_decel":
        velocity = 1700. - np.clip((t - 130e-9) * 45e9, 0., 1580.)
        events += [(130e-9, "decline", "good", False),
                   ((130 + 1580. / 45.) * 1e-9, "plateau", "good", False)]
    elif family == "turnaround":
        velocity = 1250. - np.clip((t - 120e-9) * 22e9, 0., 1100.)
        velocity += np.clip((t - 170e-9) * 30e9, 0., 1200.)
        events += [(120e-9, "decline", "good", False),
                   (166e-9, "turnaround", "good", False),
                   (174e-9, "rebound", "good", False), (210e-9, "plateau", "good", False)]
    elif family == "stable_plateau":
        velocity[:] = 400. + 80. * instance
        snr = (0., 4., 8., 12.)[instance % 4]
    elif family in ("weak_spur", "drifting_spur"):
        velocity = np.minimum(1250., 320. + elapsed * 3e9)
        amp[:] = .018
        snr = (0., 4., 8., 12.)[instance % 4]
        events = [(0., "stationary", "unobservable", False),
                  (t0, "weak_signal", "weak", True)]
    elif family == "target_in_prefix":
        velocity[:] = 200. + 50. * (instance % 4)
        active[:] = True
        onset = None
        events = [(0., "plateau", "good", False)]
    elif family == "dropout":
        velocity = 650. + elapsed * 1e9
        amp[(t >= 135e-9) & (t < 175e-9)] = 0.
        amp[(t >= 220e-9) & (t < 245e-9)] *= .12
        events += [(135e-9, "weak_signal", "weak", False),
                   (175e-9, "acceleration", "good", False),
                   (220e-9, "weak_signal", "weak", False),
                   (245e-9, "acceleration", "good", False)]
    elif family == "phase_reset":
        velocity = 700. + np.minimum(elapsed * 2e9, 400.)
        events[-1] = (t0 + 8e-9, "acceleration", "good", False)
        # Phase jumps are an observation issue; no extra manual boundary is given.
    elif family == "gradual_onset":
        velocity[:] = 350.
        amp *= np.clip(elapsed / 25e-9, 0., 1.)
        snr = 0.
        events[-1] = (t0 + 8e-9, "weak_signal", "weak", False)
    elif family == "crossing":
        velocity = 300. + np.minimum(elapsed * 3e9, 850.)
        other = (1200. - np.minimum(elapsed * 3e9, 850.)) / VELOCITY
        events[-1] = (t0 + 8e-9, "acceleration", "good", False)
    elif family == "colored_noise":
        velocity = 250. + np.minimum(elapsed * 2e9, 450.)
        snr = 2.
        events[-1] = (t0 + 8e-9, "acceleration", "good", False)
    elif family == "noise_only":
        amp[:] = 0.
        onset = None
        events = [(0., "noise", "noise", False)]
    elif family != "onset_step":
        raise ValueError(family)
    velocity = np.where(active, velocity, 0.)
    truth = velocity / VELOCITY
    phase0 = float(rng.uniform(0, 2 * np.pi))
    phase = phase0 + 2 * np.pi * np.r_[0., np.cumsum((truth[1:] + truth[:-1]) * .5 / fs)]
    if family == "phase_reset":
        phase += np.where(t >= 130e-9, 1.5, 0.) + np.where(t >= 210e-9, -2.1, 0.)
    clean = amp * np.cos(phase)
    clean -= clean[0]
    if cutoff:
        clean = np.asarray(sosfilt(butter(1, cutoff, fs=fs, btype="highpass", output="sos"), clean))
    if family in ("weak_spur", "drifting_spur"):
        rate = 0. if family == "weak_spur" else (2e14 + instance * 3e13)
        nuisance_phase = 2 * np.pi * (450e6 * t + .5 * rate * t**2) + rng.uniform(0, 2 * np.pi)
        clean += .07 * np.cos(nuisance_phase)
        other = 450e6 + rate * t
    if family == "crossing":
        phase2 = rng.uniform(0, 2 * np.pi) + 2 * np.pi * np.cumsum(other * active) / fs
        clean += .035 * 1.05 * np.cos(phase2) * active
    sigma = .035 / np.sqrt(2 * 10**(snr / 10))
    noise = rng.normal(0., sigma, n)
    if family == "colored_noise":
        colored = np.asarray(sosfilt(butter(1, 250e6, fs=fs, output="sos"), rng.normal(size=n)))
        noise += colored / np.std(colored) * sigma
    voltage = clean + noise + .003 * np.sin(2 * np.pi * 4e6 * t)
    truth[~active] = np.nan
    if family == "noise_only":
        truth[:] = np.nan
    plan = make_plan(t, events, seed)
    split = "development" if development else "independent"
    name = f"{split}_{family}_{instance:02d}"
    return Case(Signal(t, np.asarray(voltage), name), np.asarray(truth), np.asarray(other),
                np.where(active, amp, 0.), plan, truth_labels(t, events), onset, family, split,
                {"seed": seed, "snr_db": snr, "highpass_cutoff_hz": cutoff,
                 "phase0_rad": phase0, "events": events, "manual_jitter_ns": 2.,
                 "noise_sigma_v": float(sigma), "wavelength_m": VELOCITY * 2,
                 "target_identity": "generator label; not waveform-certified"})


def legacy(split: str, family: str, instance: int) -> Case:
    name = f"{'stress' if split == 'phase_stress' else 'fresh'}_{family}_{instance:02d}"
    path = ROOT / "artifacts/TASK-008/datasets" / split / name
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(path.with_suffix(".npz")) as z:
        signal = Signal(np.array(z["time_s"]), np.array(z["voltage_v"]), name)
        truth, other, amplitude = (np.array(z[key]) for key in ("truth_hz", "other_hz", "amplitude_v"))
    t0 = metadata["onset_s"]
    if t0 is None:
        events = [(0., "noise", "noise", False)]
    else:
        events = [(0., "stationary", "unobservable", False),
                  (t0, "onset", "good", False), (t0 + 8e-9, "plateau", "good", False)]
        if family in ("fast_accel", "low_ramp", "phase_jump", "colored_noise"):
            events[-1] = (t0 + 8e-9, "acceleration", "good", False)
            if family == "fast_accel":
                events.append((t0 + 43e-9, "plateau", "good", False))
            elif family == "low_ramp" and split != "phase_stress":
                events.append((t0 + 90e-9, "plateau", "good", False))
            elif split == "phase_stress":
                events[-1] = (t0 + 8e-9, "low_frequency", "good", False)
        elif family == "fast_decel":
            events += [(150e-9, "decline", "good", False), (186e-9, "plateau", "good", False)]
        elif family == "two_shock":
            events += [(101e-9, "onset", "good", False), (109e-9, "plateau", "good", False),
                       (190e-9, "acceleration", "good", False), (260e-9, "plateau", "good", False)]
        elif family in ("weak_chirp", "stationary_spur"):
            events[-1] = (t0 + 8e-9, "weak_signal" if family == "weak_chirp" else "acceleration",
                          "weak" if family == "weak_chirp" else "good", family == "stationary_spur")
        elif family == "dropout":
            events += [(135e-9, "weak_signal", "weak", False),
                       (170e-9, "acceleration", "good", False),
                       (220e-9, "weak_signal", "weak", False),
                       (250e-9, "acceleration", "good", False)]
    plan = make_plan(signal.time_s, events, int(metadata["seed"]))
    return Case(signal, truth, other, amplitude, plan, truth_labels(signal.time_s, events),
                t0, family, "legacy_" + split, metadata)


def specifications(*, development: bool = False) -> list[tuple[str, str, int]]:
    old = ("step", "low_ramp", "fast_accel", "fast_decel", "two_shock", "weak_chirp",
           "dropout", "stationary_spur", "two_component", "phase_jump", "colored_noise", "noise_only")
    if development:
        return [("development", family, i) for family in FAMILIES
                for i in range(6 if family == "low_plateau" else 2)]
    return ([("fresh", family, i) for family in old for i in range(8)]
            + [("phase_stress", "low_ramp", i) for i in range(50)]
            + [("independent", family, i) for family in FAMILIES
               for i in range(24 if family == "low_plateau" else 8)])


def load(specification: tuple[str, str, int]) -> Case:
    split, family, instance = specification
    return fresh(family, instance, development=split == "development") \
        if split in ("development", "independent") else legacy(split, family, instance)


def plan_dict(plan: tuple[Annotation, ...]) -> list[dict[str, Any]]:
    return [asdict(item) for item in plan]
