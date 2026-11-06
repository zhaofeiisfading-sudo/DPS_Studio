"""Exhaustive raw inventory and physical forward-generated truth (SI)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt  # type: ignore[import-untyped]

from .audit import ROOT, sha
from .common import Float, Signal, WAVELENGTH_M

FAMILIES = ("step", "low_ramp", "fast_accel", "fast_decel", "two_shock",
            "weak_chirp", "dropout", "stationary_spur", "two_component",
            "phase_jump", "colored_noise", "noise_only")


@dataclass
class Case:
    signal: Signal
    truth_hz: Float
    other_hz: Float
    amplitude_v: Float
    onset_s: float | None
    family: str
    seed: int
    metadata: dict[str, Any]


def inventory() -> list[dict[str, Any]]:
    result = []
    for path in sorted((ROOT/"data/raw").rglob("*")):
        if not path.is_file():
            continue
        row: dict[str, Any] = dict(path=path.relative_to(ROOT).as_posix(),
                                   sha256=sha(path), bytes=path.stat().st_size)
        if "result" in path.name.lower():
            row.update(kind="PROCESSED_EXCLUDED", reason="Filename explicitly marks processed result")
        elif path.suffix.lower() not in (".csv", ".dat"):
            row.update(kind="AUXILIARY_EXCLUDED", reason="Image/placeholder, not time-voltage")
        else:
            row.update(kind="RAW_CANDIDATE", delimiter=",", time_scale=1.,
                       time_unit_basis="Numeric seconds consistent with archived acquisition configs; no header",
                       voltage_scale=1., wavelength_m=None,
                       equivalent_velocity_wavelength_m=WAVELENGTH_M)
            try:
                x = np.loadtxt(path, delimiter=",", ndmin=2)
                signal = Signal(np.array(x[:, 0]), np.array(x[:, 1]), path.stem)
                row.update(kind="RAW", samples=len(x), channels=x.shape[1]-1,
                           sample_rate_hz=signal.fs, start_s=float(x[0, 0]),
                           end_s=float(x[-1, 0]), max_relative_step_jitter=float(
                               np.max(abs(np.diff(x[:, 0])*signal.fs-1))),
                           header=False, physical_calibration="UNCONFIRMED")
            except Exception as exc:
                row.update(kind="RAW_UNREADABLE", reason=f"{type(exc).__name__}: {exc}")
        result.append(row)
    return result


def read_raw(row: dict[str, Any]) -> list[Signal]:
    path = ROOT/row["path"]
    x = np.loadtxt(path, delimiter=",", ndmin=2)
    return [Signal(np.array(x[:, 0]), np.array(x[:, c]),
                   f"{Path(row['path']).stem}_ch{c}") for c in range(1, x.shape[1])]


def generate(family: str, instance: int, *, development: bool = False,
             phase_stress: bool = False) -> Case:
    fi = FAMILIES.index(family)
    seed = (81000000 if development else 81100000)+1000*fi+instance
    if phase_stress:
        seed = 81200000+instance
    rng = np.random.default_rng(seed)
    fs, n = 40e9, 12800
    t = np.arange(n)/fs
    t0 = (60+rng.uniform(-.5, .5))*1e-9
    elapsed = np.maximum(t-t0, 0)
    active = t >= t0
    v = np.full(n, 600.)
    amp = np.full(n, .035)
    other = np.full(n, np.nan)
    snr_db = 12.
    cutoff = [0., 2e6, 15e6, 50e6][instance % 4]
    events: list[float] = []
    if family == "low_ramp":
        v = np.minimum(180., elapsed*2e9)
        if phase_stress:
            v = np.full(n, [15., 30., 50., 100., 200.][instance % 5])
            snr_db = [8., 16.][instance % 2]
    elif family == "fast_accel":
        v = np.minimum(1800., 80.+elapsed*40e9)
    elif family == "fast_decel":
        v = 1700.-np.clip((t-150e-9)*45e9, 0., 1620.)
        events = [150e-9, 186e-9]
    elif family == "two_shock":
        v = np.where(t < 105e-9, 240., 1150.)
        v += np.clip((t-190e-9)*5e9, 0., 350.)
        events = [105e-9, 190e-9]
    elif family == "weak_chirp":
        v = np.minimum(1300., 300.+elapsed*5e9)
        snr_db = -5.
    elif family == "dropout":
        v = 650.+elapsed*.8e9
        amp[(t >= 135e-9) & (t < 170e-9)] = 0.
        amp[(t >= 220e-9) & (t < 250e-9)] *= .12
        events = [135e-9, 170e-9, 220e-9, 250e-9]
    elif family == "stationary_spur":
        v = np.minimum(1200., 320.+elapsed*3e9)
    elif family == "two_component":
        v = 600.+np.minimum(elapsed*1e9, 200.)
        other = np.full(n, 680.)*2/WAVELENGTH_M
    elif family == "phase_jump":
        v = 700.+np.minimum(elapsed*2e9, 450.)
        events = [130e-9, 210e-9]
    elif family == "colored_noise":
        v = 250.+np.minimum(elapsed*2e9, 600.)
        snr_db = 4.
    elif family == "noise_only":
        amp[:] = 0.
    v = np.where(active, v, 0.)
    truth = v*2/WAVELENGTH_M
    phase = rng.uniform(0, 2*np.pi)+np.r_[0., np.cumsum(
        (truth[1:]+truth[:-1])*.5/fs)]*2*np.pi
    if family == "phase_jump":
        phase += np.where(t >= 130e-9, 1.4, 0)+np.where(t >= 210e-9, -2.2, 0)
    # Homodyne DC before motion, then causal AC transfer. At cutoff=0 subtract
    # the static optical level (receiver-balanced ideal), not a known velocity.
    clean = amp*np.cos(phase)
    if cutoff:
        clean = np.asarray(sosfilt(butter(1, cutoff, fs=fs, btype="highpass", output="sos"),
                                  clean-np.full(n, clean[0])))
    else:
        clean = clean-clean[0]
    if family == "two_component":
        ph2 = rng.uniform(0, 2*np.pi)+2*np.pi*np.cumsum(np.nan_to_num(other)*active)/fs
        clean += .035*.9*np.cos(ph2)*active
    if family == "stationary_spur":
        clean += .07*np.cos(2*np.pi*450e6*t+rng.uniform(0, 2*np.pi))
    sigma = .035/np.sqrt(2*10**(snr_db/10))
    noise = rng.normal(0., sigma, n)
    if family == "colored_noise":
        ar = np.asarray(sosfilt(butter(1, 300e6, fs=fs, output="sos"), rng.normal(size=n)))
        noise += ar/np.std(ar)*sigma
    x = clean+noise+.003*np.sin(2*np.pi*4e6*t)
    if family == "noise_only":
        truth[:] = np.nan
        t0_out = None
    else:
        truth[~active] = np.nan
        t0_out = float(t0)
    name = f"{'dev' if development else 'stress' if phase_stress else 'fresh'}_{family}_{instance:02d}"
    return Case(Signal(np.asarray(t), np.asarray(x), name), truth, other,
                np.where(active, amp, 0.), t0_out, family, seed,
                dict(snr_db=snr_db, highpass_cutoff_hz=cutoff, phase0_rad=float(phase[0]),
                     events_s=events, target_identity="generator_label_not_waveform_identifiable",
                     noise_sigma_v=float(sigma), wavelength_m=WAVELENGTH_M,
                     split="DEVELOPMENT" if development else "FRESH_FROZEN_EVALUATION"))
