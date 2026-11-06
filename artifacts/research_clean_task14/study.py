"""TASK-014 preselected one-peak tone refinement on the frozen TASK-013 grid."""
import argparse
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from scipy.optimize import minimize_scalar  # type: ignore[import-untyped]

from artifacts.research_clean_task13.repro import stage as s
from artifacts.research_clean_task13.repro.cases import fresh
from artifacts.research_clean_task13.repro.experiment import score
from dps_studio.algorithms.task008.common import Signal
from dps_studio.research.task009_data import inventory, read_raw

OUT = Path(__file__).parent


def one_peak(signal: Signal, plan: tuple[s.Annotation, ...]) -> s.Trace:
    s.validate(plan, signal)
    fs = signal.fs
    started = perf_counter()
    centers = s.grid(signal)
    result = s.empty(len(centers))
    for i, center in enumerate(centers):
        item = s.annotation_at(plan, signal.time_s[center])
        tau, y = s.support(signal, center, 2048, item)
        result.support_samples[i] = len(y)
        if len(y) < 48:
            result.quality[i] = "INSUFFICIENT_BOUNDARY_SUPPORT"
            continue
        seed = s.fft_candidates(tau, y, fs)[0][0]
        span = fs / len(y)
        bounds = max(s.FMIN, seed - span), min(s.FMAX, fs * .49, seed + span)
        if bounds[0] >= bounds[1]:
            result.quality[i] = "EMPTY_SEARCH_BAND"
            continue
        fit = minimize_scalar(lambda hz: 1 - s.linear_fit(tau, y, hz)[2],
                              bounds=bounds, method="bounded", options={"xatol": .1})
        if not fit.success or not np.isfinite(fit.x):
            result.quality[i] = "FIT_FAILED"
            continue
        f = fit.x
        ok, flag, r2, cond = s.quality_gate(tau, y, f, 0.)
        result.candidate_hz[i] = f
        result.accepted_hz[i] = f if ok else np.nan
        result.quality[i], result.r2[i], result.condition[i] = flag, r2, cond
    result.runtime_s = perf_counter() - started
    return result


def route(signal: Signal, plan: tuple[s.Annotation, ...], cache: dict[str, s.Trace],
          improved: bool) -> s.Trace:
    result = s.empty(len(s.grid(signal)))
    used = set()
    for i, center in enumerate(s.grid(signal)):
        item = s.annotation_at(plan, signal.time_s[center])
        name = s.recommended(item)
        if name == "unobservable":
            continue
        if name == "bounded_chirp512":
            name = "dechirp"
        if name == "profile2048":
            name = "one_peak" if improved and item.stage == "low_frequency" else "clip_stft2048"
        if name not in cache:
            cache[name] = (s.local_estimate(signal, plan, name) if name.startswith("clip")
                           else s.frozen_estimate(signal, name))
        used.add(name)
        for key in ("candidate_hz", "accepted_hz", "quality"):
            getattr(result, key)[i] = getattr(cache[name], key)[i]
    # Full component cost; independent methods do not receive a cache discount.
    result.runtime_s = sum(cache[name].runtime_s for name in used)
    return result


def experiment() -> None:
    rows = []
    for family in ("low_plateau", "onset_step", "fast_accel", "fast_decel", "turnaround",
                   "weak_spur", "crossing", "dropout", "noise_only"):
        for index in range(32, 48 if family == "low_plateau" else 36):
            case = fresh(family, index)
            signal, plan = case.signal, case.plan
            traces = {"stft768": s.frozen_estimate(signal, "stft768"),
                      "one_peak": one_peak(signal, plan),
                      "clip_stft2048": s.local_estimate(signal, plan, "clip_stft2048"),
                      "profile2048": s.local_estimate(signal, plan, "profile2048")}
            traces["simple_map"] = route(signal, plan, traces, False)
            traces["low_refined_map"] = route(signal, plan, traces, True)
            rows.extend(score(case, traces))
    pd.DataFrame(rows).to_csv(OUT / "synthetic.csv", index=False)


def real() -> None:
    rows = []
    for item in inventory():
        if item["kind"] != "RAW":
            continue
        for original in read_raw(item):
            signal = Signal(original.time_s, original.voltage_v, original.name)
            plan = (s.Annotation(signal.time_s[0], signal.time_s[-1]+1/signal.fs, "unknown"),)
            base = s.frozen_estimate(signal, "stft768")
            for name, trace in (("stft768", base), ("one_peak", one_peak(signal, plan)),
                                ("clip_stft2048", s.local_estimate(signal, plan, "clip_stft2048"))):
                paired = np.isfinite(base.accepted_hz) & np.isfinite(trace.accepted_hz)
                diff = abs(base.accepted_hz[paired] - trace.accepted_hz[paired])
                rows.append(dict(file=item["local_path"], channel=original.name, method=name,
                                 centers=len(paired), finite=np.isfinite(trace.accepted_hz).sum(),
                                 paired=paired.sum(), disagreement_100MHz=(diff > 1e8).sum(),
                                 runtime_s=trace.runtime_s))
    pd.DataFrame(rows).to_csv(OUT / "real.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    requested = parser.parse_args().output.resolve()
    if not requested.is_relative_to(OUT.resolve()):
        parser.error("Choose a new output directory inside the TASK-014 artifact")
    requested.mkdir(parents=True, exist_ok=False)
    OUT = requested
    experiment()
    real()
