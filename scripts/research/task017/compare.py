"""Real-only full-record comparisons with explicit native candidates and gates."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
import gzip
import hashlib
import importlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.algorithms.waveform.common import Context, Signal
from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation import Segment, default_pool
from dps_studio.core.segmentation.models import EstimatorRequest
from dps_studio.core.segmentation.strategies import (
    STRATEGIES, Strategy, baseline, estimate_strategy, fit_tone,
)
from scripts.research.task017.prepare import OUT, load, records


@dataclass
class Trace:
    time: Any
    candidate: Any
    gated: Any
    flags: Any
    rate: Any
    width: int
    fmin: float
    fmax: float
    runtime: float
    details: Any
    source: str


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def frozen_plans() -> dict[str, Any]:
    lock = json.loads((OUT / "data/visual_freeze.json").read_text(encoding="utf-8"))
    if digest(OUT / "data/visual_annotations.json") != lock["annotations_sha256"]:
        raise RuntimeError("Frozen annotations changed")
    if digest(OUT / "data/inventory.json") != lock["inventory_sha256"]:
        raise RuntimeError("Frozen inventory changed")
    plans = json.loads((OUT / "data/visual_annotations.json").read_text(encoding="utf-8"))["plans"]
    return cast(dict[str, Any], plans)


def common_centers(n: int) -> Any:
    return np.arange(0, n, 128, dtype=np.int64)


def align(native_time: Any, t: Any, fs: float, q: Any) -> tuple[Any, Any]:
    centers = np.rint((native_time-t[0])*fs).astype(np.int64)
    if len(np.unique(centers)) != len(centers):
        raise ValueError("Duplicate native physical centers")
    if np.max(abs(native_time-t[centers]), initial=0.) > 5e-15:
        raise ValueError("Physical center mismatch beyond recorded rounding")
    positions = np.searchsorted(centers, q)
    ok = positions < len(centers)
    ok[ok] &= centers[positions[ok]] == q[ok]
    return positions, ok


def request(t: Any, y: Any, width: int = 1024, fmax: float = 6e9,
            fmin: float = 50e6) -> EstimatorRequest:
    return EstimatorRequest(SignalRecord(t, y), float(t[0]), float(t[-1]), 1.55e-6,
                            {"window_length_samples": width, "overlap_samples": width-64,
                             "nfft": max(4096, width), "window_name": "hann",
                             "minimum_frequency_hz": fmin, "maximum_frequency_hz": fmax})


def formal(t: Any, y: Any, width: int = 1024, fmax: float = 6e9) -> Trace:
    started = perf_counter()
    result = default_pool().estimate("stft", request(t, y, width, fmax))
    return Trace(result.time_s, result.candidate_frequency_hz, result.frequency_hz,
                 np.asarray(result.quality), np.zeros(len(result.time_s)), width, 50e6, fmax,
                 perf_counter()-started, dict(result.details),
                 "core.segmentation.pool._stft / formal workflow (original gate)")


def strategy(t: Any, y: Any, segments: list[dict[str, Any]], name: str,
             spec: Strategy, fmax: float = 6e9) -> Trace:
    started = perf_counter()
    q = common_centers(len(t))
    candidate = np.full(len(q), np.nan)
    gated, rates = candidate.copy(), np.zeros(len(q))
    flags = np.full(len(q), "NO_NATIVE_CENTER", dtype="U256")
    details = []
    req = request(t, y, fmax=fmax, fmin=5e6)
    for j, segment in enumerate(segments):
        seg = Segment(segment["id"], segment["start_s"], segment["end_s"], segment["stage"])
        result = estimate_strategy(replace(req, segment=seg), name, replace(spec, hop=128))
        pos, ok = align(result.time_s, t, float(req.record.sample_rate_hz), q)
        own = (t[q] >= seg.start_s) & ((t[q] <= seg.end_s) if j == len(segments)-1
                                     else (t[q] < seg.end_s))
        own &= ok
        candidate[own] = result.candidate_frequency_hz[pos[own]]
        gated[own] = result.frequency_hz[pos[own]]
        flags[own] = np.asarray(result.quality)[pos[own]]
        frame = list(result.details["frames"])
        rates[own] = np.asarray([f.get("chirp_hz_s", 0.) for f in frame])[pos[own]]
        details.append({"segment": seg.id, **dict(result.details)})
    return Trace(t[q], candidate, gated, flags, rates, spec.width, 5e6,
                 min(250e6, fmax) if spec.mode in ("band", "glrt") else fmax,
                 perf_counter()-started, details,
                 f"core.segmentation.strategies.estimate_strategy: {name}")


def native(context: Context, name: str, manual_sample: int | None = None) -> Trace:
    started = perf_counter()
    if manual_sample is not None:
        context = Context(context.signal)
        context.onset = manual_sample
        context.event = {**context.event, "manual_onset_sample": manual_sample,
                         "onset_source": "FROZEN_VISUAL_BOUNDARY_NOT_TRUTH"}
    module = importlib.import_module(f"dps_studio.algorithms.waveform.{name}.implementation")
    result = module.run(context)
    details = {"parameters": module.PARAMETERS, "diagnostics": result.details,
               "event": context.event, "extras": result.extra}
    return Trace(context.time_s, result.frequency_hz, result.accepted_hz, result.flags,
                 result.extra.get("chirp_hz_per_s", np.zeros(len(context.time_s))),
                 int(module.PARAMETERS.get("window", module.PARAMETERS.get("slab_samples", 512))),
                 5e6, 8e9, perf_counter()-started, details,
                 f"algorithms.waveform.{name}.implementation.run" +
                 (" / frozen visual onset override" if manual_sample is not None else ""))


def normalize(trace: Trace, t: Any, fs: float) -> dict[str, Any]:
    q = common_centers(len(t))
    pos, ok = align(trace.time, t, fs, q)
    values: dict[str, Any] = {"time_s": t[q], "sample_index": q,
                              "quality": np.full(len(q), "NO_NATIVE_CENTER", dtype="U256")}
    for name, data in (("raw_frequency_hz", trace.candidate),
                       ("gated_frequency_hz", trace.gated), ("chirp_hz_s", trace.rate)):
        array = np.full(len(q), np.nan)
        array[ok] = data[pos[ok]]
        values[name] = array
    values["quality"][ok] = trace.flags[pos[ok]]
    raw = values["raw_frequency_hz"]
    legal = np.isfinite(raw) & (raw >= trace.fmin) & (raw <= trace.fmax)
    values["frequency_hz"] = np.where(legal, raw, np.nan)
    gated = values["gated_frequency_hz"]
    values["gated_frequency_hz"] = np.where(np.isfinite(gated) & (gated >= trace.fmin)
                                            & (gated <= trace.fmax), gated, np.nan)
    values["apparent_velocity_m_s"] = np.full(len(q), np.nan)
    values["missing_reason"] = np.where(~ok, "NO_NATIVE_CENTER",
        np.where(~np.isfinite(raw), "NO_CANDIDATE_GENERATED",
                 np.where(~legal, "OUTSIDE_METHOD_BAND", "CANDIDATE_AVAILABLE")))
    return values


def evidence(t: Any, y: Any, fs: float, q: Any, background_stop: float,
             width: int = 256) -> dict[str, Any]:
    """Same ORIGINAL raw support for every method, never clutter-subtracted voltage."""
    nfft = max(4096, width*2)
    frequency = np.fft.rfftfreq(nfft, 1/fs)
    band = (frequency >= 50e6) & (frequency <= 8e9)
    last = min(max(4096, width*4), int(np.searchsorted(t, background_stop)))
    background = []
    # Keep the original 256-sample diagnostic unchanged. A long window must
    # include an exactly fitting final background frame, otherwise N=width is empty.
    stop = last-width//2+(1 if width > 256 else 0)
    for c in range(width//2, max(width//2, stop), 128):
        yy = y[c-width//2:c+width//2]
        background.append(abs(np.fft.rfft((yy-yy.mean())*np.hanning(width), n=nfft))**2)
    bg = np.median(background, axis=0) if background else np.full(len(frequency), np.nan)
    spectra, taus, raw = [], [], []
    for c in q:
        left, right = max(0, c-width//2), min(len(t), c+width//2)
        tau = (np.arange(left, right)-c)/fs
        yy = y[left:right]
        null = baseline(tau, 1)
        residual = yy-null@np.linalg.lstsq(null, yy, rcond=1e-10)[0]
        p = abs(np.fft.rfft(residual*np.hanning(len(yy)), n=nfft))**2
        spectra.append(p)
        taus.append(tau)
        raw.append(yy)
    return {"spectra": np.asarray(spectra), "background": bg, "frequency": frequency,
            "band": band, "tau": taus, "voltage": raw, "width": width}


def diagnose(values: dict[str, Any], ev: dict[str, Any], fs: float) -> dict[str, Any]:
    n = len(values["time_s"])
    names = ("spectral_contrast_db", "background_gain_db", "relative_strongest_db",
             "competitor_advantage_db", "raw_tone_r2", "raw_chirp_r2",
             "raw_tone_residual_rms_v", "raw_chirp_residual_rms_v", "cycles_256")
    result = {name: np.full(n, np.nan) for name in names}
    fgrid, bg, band = ev["frequency"], ev["background"], ev["band"]
    for i, hz in enumerate(values["frequency_hz"]):
        if not np.isfinite(hz):
            continue
        p = ev["spectra"][i]
        near = abs(fgrid-hz) <= fs/ev["width"]*.5
        selected = max(float(p[near].max()), 1e-30)
        noise = max(float(np.median(p[band])), 1e-30)
        base = max(float(bg[near].max()), 1e-30)
        strongest = max(float(p[band].max()), 1e-30)
        other = band & (abs(fgrid-hz) >= 2*fs/ev["width"])
        competitor = max(float(p[other].max()), 1e-30) if np.any(other) else 1e-30
        result["spectral_contrast_db"][i] = 10*np.log10(selected/noise)
        result["background_gain_db"][i] = 10*np.log10(selected/base)
        result["relative_strongest_db"][i] = 10*np.log10(selected/strongest)
        result["competitor_advantage_db"][i] = 10*np.log10(competitor/selected)
        tau, yy = ev["tau"][i], ev["voltage"][i]
        null = baseline(tau, 1)
        rate = values["chirp_hz_s"][i]
        rate = float(rate) if np.isfinite(rate) else 0.
        for label, a in (("tone", 0.), ("chirp", rate)):
            r2, _, _, residual = fit_tone(tau, yy, hz, null, a)
            result[f"raw_{label}_r2"][i] = r2
            result[f"raw_{label}_residual_rms_v"][i] = np.sqrt(np.mean(residual**2))
        result["cycles_256"][i] = hz*float(np.ptp(tau))
    result["spectrally_supported"] = ((result["spectral_contrast_db"] >= 10.)
        & (result["background_gain_db"] >= 6.) & (result["cycles_256"] >= 1.)
        & (np.maximum(result["raw_tone_r2"], result["raw_chirp_r2"]) >= .20))
    # A fit can support a clutter/harmonic; this flag NEVER establishes target identity.
    return result


def json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def execute(item: dict[str, Any], output: str) -> dict[str, Any]:
    dest = Path(output) / item["id"]
    dest.mkdir(exist_ok=False)
    segments = frozen_plans()[item["id"]]
    t, y, fs = load(item)
    signal = Signal(t, y, item["id"])
    q = common_centers(len(t))
    onset = next(seg for seg in segments if seg["stage"] == "onset")
    manual_sample = int(np.searchsorted(t, onset["start_s"]))
    ev = evidence(t, y, fs, q, onset["start_range_s"][0]-2e-9)
    ctx_started = perf_counter()
    context = Context(signal)
    context_cost = perf_counter()-ctx_started
    traces: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {}
    failures = []

    def store(name: str, tr: Trace) -> None:
        values = normalize(tr, t, fs)
        values.update(diagnose(values, ev, fs))
        stage = np.full(len(q), "unknown", dtype="U32")
        seg_id = np.full(len(q), "", dtype="U16")
        for j, seg in enumerate(segments):
            mask = (t[q] >= seg["start_s"]) & ((t[q] <= seg["end_s"]) if j == len(segments)-1
                                               else (t[q] < seg["end_s"]))
            stage[mask], seg_id[mask] = seg["stage"], seg["id"]
        values.update(stage=stage, segment_id=seg_id)
        values["primary_common_support"] = (q >= 1024) & (q <= len(t)-1024)
        np.savez_compressed(dest / f"{name}.npz", **values)
        np.savez_compressed(dest / f"{name}__native.npz", time_s=tr.time,
                            raw_frequency_hz=tr.candidate, gated_frequency_hz=tr.gated,
                            quality=tr.flags, chirp_hz_s=tr.rate)
        with gzip.open(dest / f"{name}__details.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(tr.details, handle, default=json_default)
        metadata[name] = {"runtime_s": tr.runtime, "source": tr.source,
                          "nominal_width_samples": tr.width, "band_hz": [tr.fmin, tr.fmax],
                          "candidate_n": int(np.isfinite(values["frequency_hz"]).sum()),
                          "gated_n": int(np.isfinite(values["gated_frequency_hz"]).sum()),
                          "supported_n": int(values["spectrally_supported"].sum())}
        traces[name] = values
        print(item["id"], name, metadata[name]["candidate_n"], flush=True)

    def run(name: str, function: Any) -> None:
        try:
            store(name, function())
        except Exception as exc:
            failures.append({"method": name, "error": f"{type(exc).__name__}: {exc}"})
            missing = np.full(len(q), np.nan)
            store(name, Trace(t[q], missing, missing, np.full(len(q), "ALGORITHM_ERROR"),
                               np.zeros(len(q)), 1, 5e6, 8e9, 0., failures[-1], "FAILED"))

    for name, width, maximum in (("M1_balanced", 1024, 6e9), ("formal_short512", 512, 6e9),
                                 ("formal_long2048", 2048, 6e9),
                                 ("balanced_wide8", 1024, 8e9),
                                 ("short_wide8", 512, 8e9)):
        run(name, lambda w=width, high=maximum: formal(t, y, w, high))
    for name in ("stft_short", "stft_long", "stft_low", "low_glrt", "tone_refine",
                 "signed_dechirp"):
        run(name, lambda key=name: strategy(t, y, segments, key, STRATEGIES[key]))
    run("stage_stft1024", lambda: strategy(t, y, segments, "stage_stft1024", Strategy()))
    full = [{"id": "full", "start_s": float(t[0]), "end_s": float(t[-1]), "stage": "unknown"}]
    run("unclipped_short", lambda: strategy(t, y, full, "unclipped_short",
                                           Strategy(width=512, boundary="full")))
    for name in ("dechirp", "varpro", "clutter_varpro", "acmd", "matrix_pencil", "time_domain"):
        run(name, lambda key=name: native(context, key))
    for name in ("dechirp", "varpro"):
        run("visual_onset_"+name, lambda key=name: native(context, key, manual_sample))

    def route(name: str, mapping: dict[str, str]) -> None:
        candidate, gated = np.full(len(q), np.nan), np.full(len(q), np.nan)
        flags = np.full(len(q), "EXPLICIT_NO_ESTIMATE", dtype="U256")
        rates, used = np.zeros(len(q)), set()
        for j, seg in enumerate(segments):
            method = mapping.get(seg["stage"], "M1_balanced")
            if method == "unobservable":
                continue
            v = traces[method]
            mask = (t[q] >= seg["start_s"]) & ((t[q] <= seg["end_s"]) if j == len(segments)-1
                                               else (t[q] < seg["end_s"]))
            candidate[mask], gated[mask] = v["raw_frequency_hz"][mask], v["gated_frequency_hz"][mask]
            rates[mask], flags[mask] = v["chirp_hz_s"][mask], v["quality"][mask]
            if method in ("dechirp", "clutter_varpro"):
                outside = mask & ((gated < 50e6) | (gated > 6e9))
                gated[outside] = np.nan
                flags[outside] = "OUTSIDE_USER_FREQUENCY_BAND"
            used.add(method)
        store(name, Trace(t[q], candidate, gated, flags, rates, 1024, 5e6, 6e9,
                          sum(metadata[k]["runtime_s"] for k in used), {"mapping": mapping,
                          "frozen_annotations": True, "components": sorted(used)},
                          "TASK-015 experiment.run routing, frozen real visual plan"))

    route("M2_task014_gui", {"acceleration": "dechirp", "noise": "unobservable"})
    simple = {"stationary": "stft_low", "onset": "stft_short", "rebound": "stft_short",
              "acceleration": "stft_short", "decline": "stft_short", "plateau": "stft_long",
              "noise": "stft_long", "weak_signal": "stft_long"}
    route("M3_parameters", simple)
    route("M4_specialized", {**simple, "stationary": "low_glrt", "plateau": "tone_refine",
                             "acceleration": "signed_dechirp", "decline": "signed_dechirp",
                             "noise": "clutter_varpro"})
    # Exact original TASK-014 research route; no synthetic waveform generator is called.
    def replay14() -> Trace:
        from scripts.research.task013 import stage as old
        from scripts.research.task014.study import route as route14
        plan = tuple(old.Annotation(seg["start_s"], seg["end_s"], seg["stage"],
                                    observation="weak" if seg["stage"] == "weak_signal" else "good")
                     for seg in segments)
        started = perf_counter()
        result = route14(signal, plan, {}, False)
        return Trace(t[old.grid(signal)], result.candidate_hz, result.accepted_hz,
                     result.quality, result.chirp_hz_s, 2048, 5e6, 8e9,
                     perf_counter()-started, result.details,
                     "scripts.research.task014.study.route(improved=False), unchanged")
    run("TASK014_research_simple", replay14)
    with (dest / "metadata.json").open("x", encoding="utf-8") as handle:
        json.dump({"channel": item["id"], "file_sha256": item["sha256"],
                   "context_runtime_s": context_cost, "context_event": context.event,
                   "manual_onset_sample": manual_sample,
                   "methods": metadata, "failures": failures,
                   "runtime_note": "single-thread kernels, up to 3 records concurrently; no speedup claim",
                   "wavelength_status": "UNCONFIRMED; internal API placeholder only"},
                  handle, indent=2, default=json_default)
    frames = []
    for name, v in traces.items():
        frame = pd.DataFrame(v)
        frame.insert(0, "channel", item["id"])
        frame.insert(1, "method", name)
        frame["candidate_source"] = metadata[name]["source"]
        frame["physical_branch"] = "requires experimental confirmation"
        frame["wavelength_m"] = np.nan
        frames.append(frame)
    pd.concat(frames, ignore_index=True).to_csv(dest / "candidates.csv.gz", index=False)
    return {"channel": item["id"], "methods": len(traces), "failures": failures,
            "centers": len(q)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--id")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(OUT / "data"):
        parser.error("Choose a new directory in artifacts/TASK-017/data")
    output.mkdir(exist_ok=False)
    frozen_plans()
    items = [r for r in records() if not args.id or r["id"] == args.id]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(execute, items, [str(output)]*len(items)))
    with (output / "complete.json").open("x", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    print("COMPLETE", len(results), "real channels", flush=True)


if __name__ == "__main__":
    main()
