"""Replay frozen acquisitions and persist exact, resumable center-level arrays."""
from __future__ import annotations

import csv
import json
from dataclasses import fields, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from scripts.research.task017.prepare import ROOT
from scripts.research.task018.inputs import inventory
from scripts.research.task023.common import Channel, Estimate, RawEvaluator, RawEvidence, load_channel
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.phase_coherent import m4_phase_coherent
from scripts.research.task024.ablations import FULL, NO_CHIRP, NO_STEP, VARIANTS, assert_exact, run_variant
from scripts.research.task024.controls import B1, BS, CONTROLS, QUAD, estimate, run_controls, verify_task020

OUTPUT = ROOT / "artifacts/TASK-024/study"
PHASE3 = ROOT / "artifacts/TASK-023/phase3b/tables"
OOB_CHANNEL = "20201214m_ch1"
METHODS = (*CONTROLS, *VARIANTS)
WIDE_METHODS = ("B1_8G", "STFT_25p6ns_quad_8G", "M4_8G")
RAW_KEYS = tuple(field.name for field in fields(RawEvidence))


def screen(ch: Channel, methods: dict[str, Estimate]) -> Screening:
    t = ch.t[ch.q]
    stages = np.full(len(t), "unknown", dtype="U32")
    segments = np.full(len(t), "", dtype="U32")
    for seg in ch.segments:
        mask = (t >= seg["start_s"]) & (t < seg["end_s"])
        stages[mask], segments[mask] = seg["stage"], seg["id"]
    if np.any(segments == ""):
        raise ValueError(f"Frozen stage plan does not cover the grid of {ch.id}")
    return Screening(ch, methods, stages, segments)


def _compare_column(path: Path, name: str, values: np.ndarray[Any, Any],
                    rows: list[dict[str, str]]) -> None:
    if values.dtype.kind == "b":
        expected: object = [row[name] == "True" for row in rows]
    elif values.dtype.kind in "iu":
        expected = [int(row[name]) for row in rows]
    else:
        expected = [float(row[name]) for row in rows]
    np.testing.assert_array_equal(values, expected, err_msg=f"{path.name}: {name}")


def verify_phase3(ch: Channel, estimates: dict[str, Estimate], *, wide: bool = False) -> int:
    pairs: tuple[tuple[str, str], ...]
    if wide:
        path = PHASE3 / "phase3_20201214m_8ghz_diagnostic.csv"
        pairs = (("B1_8G", "B1_8G"), ("M4_8G", "M4_8G"))
    else:
        path = PHASE3 / f"phase3_centers_{ch.id}.csv"
        pairs = ((B1, "B1"), (BS, "B+S"), (FULL, "M4"))
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for key, values in (("sample_index", ch.q), ("time_s", ch.t[ch.q]), ("primary", ch.primary)):
        _compare_column(path, key, values, rows)
    for name, label in pairs:
        result = estimates[name]
        _compare_column(path, f"{label}_candidate_hz", result.candidate_hz, rows)
        suffix = "accepted_hz" if wide else "hz"
        _compare_column(path, f"{label}_{suffix}", result.accepted_hz, rows)
        if not wide:
            _compare_column(path, f"{label}_chirp_hz_s", result.chirp_hz_s, rows)
            for key, values in result.diagnostics.items():
                if key != "support_samples":
                    _compare_column(path, f"{label}_{key}", values, rows)
        for key in RAW_KEYS:
            name_in_csv = f"{label}_{key}"
            if name_in_csv in rows[0]:
                _compare_column(path, name_in_csv, getattr(result.raw, key), rows)
    return len(rows)


def _save(
    path: Path, ch: Channel, results: dict[str, Estimate],
    times: dict[str, float], parity_n: int,
) -> None:
    arrays: dict[str, np.ndarray[Any, Any]] = {
        "sample_index": ch.q, "time_s": ch.t[ch.q], "primary": ch.primary,
        "meta": np.asarray(json.dumps({"seconds": times, "parity_n": parity_n})),
    }
    for name, result in results.items():
        arrays[f"{name}/candidate_hz"] = result.candidate_hz
        arrays[f"{name}/accepted_hz"] = result.accepted_hz
        arrays[f"{name}/chirp_hz_s"] = result.chirp_hz_s
        for key in RAW_KEYS:
            arrays[f"{name}/raw/{key}"] = getattr(result.raw, key)
        for key, values in result.diagnostics.items():
            arrays[f"{name}/diag/{key}"] = values
    with path.open("xb") as stream:
        np.savez_compressed(stream, allow_pickle=False, **arrays)


def _read(
    path: Path, ch: Channel, names: tuple[str, ...],
) -> tuple[dict[str, Estimate], dict[str, float], int]:
    with np.load(path, allow_pickle=False) as arrays:
        np.testing.assert_array_equal(arrays["sample_index"], ch.q)
        np.testing.assert_array_equal(arrays["time_s"], ch.t[ch.q])
        np.testing.assert_array_equal(arrays["primary"], ch.primary)
        meta = json.loads(str(arrays["meta"]))
        results = {}
        for name in names:
            prefix = f"{name}/diag/"
            diag = {key.removeprefix(prefix): arrays[key] for key in arrays.files
                    if key.startswith(prefix)}
            raw = RawEvidence(*(arrays[f"{name}/raw/{key}"] for key in RAW_KEYS))
            results[name] = Estimate(ch.q, arrays[f"{name}/candidate_hz"],
                                     arrays[f"{name}/accepted_hz"], arrays[f"{name}/chirp_hz_s"],
                                     raw, diag)
    return results, dict(meta["seconds"]), int(meta["parity_n"])


def replay_channel(ch: Channel) -> tuple[dict[str, Estimate], dict[str, float], int]:
    clean = replace(ch, segments=())
    # Run the independent M4 cold first. STFT and other variants use fresh objects.
    full = run_variant(clean, FULL)
    started = perf_counter()
    native = m4_phase_coherent(clean)
    native_seconds = perf_counter()-started
    assert_exact(full.estimate, native)
    ev = RawEvaluator(clean)
    controls = run_controls(clean, ev)
    parity_n = verify_task020(clean, controls)
    results = {**controls, FULL: full.estimate}
    if verify_phase3(clean, results) != parity_n:
        raise AssertionError(f"TASK-020 and TASK-023 archive grid mismatch for {ch.id}")
    times = {**full.seconds, "independent_native_parity": native_seconds}
    for variant in VARIANTS[1:]:
        shared = None if variant in (NO_CHIRP, NO_STEP) else full.initial_bank
        trial = run_variant(clean, variant, shared)
        value = trial.estimate
        # Apply the ordinary raw evidence convention even to the no-step variant.
        if variant == NO_STEP:
            value = replace(value, raw=ev.evaluate(value.candidate_hz, value.chirp_hz_s))
        results[variant] = value
        times[variant] = trial.seconds["cold_total" if shared is None else "shared_total"]
    return results, times, parity_n


def wide_band(ch: Channel) -> dict[str, Estimate]:
    wide = replace(ch, segments=(), fmax=8e9)
    ev = RawEvaluator(wide)
    results = dict(zip(WIDE_METHODS, (
        estimate(wide, ev, B1), estimate(wide, ev, QUAD), m4_phase_coherent(wide),
    ), strict=True))
    verify_phase3(wide, results, wide=True)
    return results


def replay(
    output: Path, *, resume: bool = False,
) -> tuple[list[Screening], dict[str, dict[str, float]], dict[str, Estimate], int]:
    items, _ = inventory()
    centers = output / "centers"
    if centers.resolve() != centers:
        raise ValueError(f"Center array destination is a link: {centers}")
    centers.mkdir(exist_ok=True)
    screens, timing = [], {}
    checked = 0
    for item in items:
        name = str(item["id"])
        ch = load_channel(name)
        np.testing.assert_array_equal(ch.q, np.arange(384, len(ch.y)-383, 128))
        path = centers / f"{name}.npz"
        if path.exists():
            if not resume:
                raise FileExistsError(f"{path} already exists. Use --resume to verify and reuse it.")
            results, times, parity_n = _read(path, ch, METHODS)
            if verify_task020(ch, results) != parity_n or verify_phase3(ch, results) != parity_n:
                raise AssertionError(f"Restarted replay has an inconsistent archive count: {name}")
        else:
            print(f"{name} | running STFT controls, independent M4 parity and ablations", flush=True)
            results, times, parity_n = replay_channel(ch)
            _save(path, ch, results, times, parity_n)
        checked += parity_n
        screens.append(screen(ch, results))
        timing[name] = times
        print(f"{name} | {parity_n} exact archive centers | M4 cold {times['cold_total']:.2f} s",
              flush=True)
    primary_n = sum(int(item.channel.primary.sum()) for item in screens)
    if len(screens) != 14 or primary_n != 9475:
        raise AssertionError(f"Unexpected frozen cohort: {len(screens)} channels, {primary_n} centers")
    ch14 = next(item.channel for item in screens if item.channel.id == OOB_CHANNEL)
    path = centers / f"{OOB_CHANNEL}_8ghz.npz"
    if path.exists() and resume:
        wide, _, _ = _read(path, ch14, WIDE_METHODS)
        verify_phase3(replace(ch14, fmax=8e9), wide, wide=True)
    else:
        wide = wide_band(ch14)
        _save(path, ch14, wide, {}, len(ch14.q))
    return screens, timing, wide, checked
