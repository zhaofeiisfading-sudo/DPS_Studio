"""Replay TASK-020 baselines and screen the five frozen TASK-023 channels."""
from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from pathlib import Path
from time import perf_counter

import numpy as np
from numpy.typing import NDArray

from scripts.research.task017.prepare import ROOT
from scripts.research.task023.common import (
    Channel, Estimate, RawEvidence, load_channel, run_baselines, verify_baselines,
)
from scripts.research.task023.methods import m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod
from scripts.research.task023.phase1_plots import save_channel_figures
from scripts.research.task023.waveform import Bool, Float

CHANNELS = ("20201210m_ch1", "20201211m_ch1", "20221017a_ch1", "20260630-1_ch2", "ch3_ch1")
METHODS = ("B0", "B1", "B+S", "M1", "M2", "M3")
TASK_OUTPUT = ROOT / "artifacts/TASK-023"
OUT = TASK_OUTPUT / "phase1"
METRICS = ("raw_chirp_r2_64ns", "raw_chirp_r2_256ns", "split_half_coherence_256ns")


@dataclass(frozen=True)
class Screening:
    channel: Channel
    results: dict[str, Estimate]
    stages: NDArray[np.str_]
    segments: NDArray[np.str_]


def _run_channel(name: str, timing: list[dict[str, object]]) -> Screening:
    started = perf_counter()
    ch = load_channel(name)
    timing.append(dict(channel=name, method="load", seconds=perf_counter()-started,
                       scope="read and normalize frozen input"))
    baseline_times: dict[str, float] = {}
    results = run_baselines(ch, baseline_times)
    scopes = ("estimate and evidence, including shared legacy setup",
              "estimate and evidence, reusing shared legacy setup", "incremental B1 support mask")
    for (method, elapsed), scope in zip(baseline_times.items(), scopes, strict=True):
        timing.append(dict(channel=name, method=method, seconds=elapsed, scope=scope))
    started = perf_counter()
    verify_baselines(ch, results)
    timing.append(dict(channel=name, method="baseline_parity", seconds=perf_counter()-started,
                       scope="exact TASK-020 readout at every Phase 1 center"))
    for method, run in zip(METHODS[3:], (m1_sw_wpd_tbd, m2_mc_decomp, m3_ss_demod), strict=True):
        started = perf_counter()
        results[method] = run(replace(ch))
        timing.append(dict(channel=name, method=method, seconds=perf_counter()-started,
                           scope="cold estimator, quiet model and raw evidence"))
    time_s = ch.t[ch.q]
    stages = np.full(len(ch.q), "unknown", dtype="U32")
    segments = np.full(len(ch.q), "", dtype="U32")
    for segment in ch.segments:
        mask = (time_s >= segment["start_s"]) & (time_s < segment["end_s"])
        stages[mask] = segment["stage"]
        segments[mask] = segment["id"]
    counts = "  ".join(f"{method}={np.count_nonzero(np.isfinite(r.accepted_hz) & ch.primary)}"
                       for method, r in results.items())
    print(f"{name} | exact B0/B1/B+S parity | {counts} primary centers accepted", flush=True)
    return Screening(ch, results, stages, segments)


def _centers(
    path: Path, screen: Screening, extra: dict[str, Iterable[object]] | None = None,
) -> None:
    ch = screen.channel
    columns: dict[str, Iterable[object]] = {
        "sample_index": ch.q, "time_s": ch.t[ch.q], "primary": ch.primary,
        "stage": screen.stages, "segment_id": screen.segments,
        "local_center_snr_32ns": screen.results["B1"].raw.local_center_snr_32ns,
    }
    for method, result in screen.results.items():
        columns[f"{method}_candidate_hz"] = result.candidate_hz
        columns[f"{method}_hz"] = result.accepted_hz
        columns[f"{method}_chirp_hz_s"] = result.chirp_hz_s
        for field in fields(RawEvidence):
            if field.name != "local_center_snr_32ns":
                columns[f"{method}_{field.name}"] = getattr(result.raw, field.name)
        for name, values in result.diagnostics.items():
            columns[f"{method}_{name}"] = values
    if extra is not None:
        columns.update(extra)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(zip(*columns.values(), strict=True))


def _metric_masks(screen: Screening, method: str, stage: str) -> tuple[Bool, Bool]:
    mask = screen.channel.primary.copy()
    if stage != "all":
        mask &= screen.stages == stage
    return mask, mask & np.isfinite(screen.results[method].accepted_hz)


def _metrics(screens: list[Screening], method: str, stage: str) -> dict[str, object]:
    channel = screens[0].channel.id if len(screens) == 1 else "all"
    eligible = accepted_n = candidate_n = background_n = background_accepted_n = jumps = 0
    onset_times: list[float] = []
    quality: dict[str, list[Float]] = {name: [] for name in METRICS}
    for screen in screens:
        result = screen.results[method]
        mask, accepted = _metric_masks(screen, method, stage)
        background = np.isin(screen.stages, ("noise", "stationary"))
        eligible += int(mask.sum())
        candidate_n += int(np.count_nonzero(mask & np.isfinite(result.candidate_hz)))
        accepted_n += int(accepted.sum())
        background_n += int(np.count_nonzero(mask & background))
        background_accepted_n += int(np.count_nonzero(accepted & background))
        jumps += int(np.count_nonzero(
            accepted[1:] & accepted[:-1] & (np.diff(result.sample_index) == 128)
            & (abs(np.diff(result.accepted_hz)) > 250e6)
        ))
        raw = result.raw
        raw_support = (raw.raw_chirp_r2_64ns >= .13) | (
            (raw.raw_chirp_r2_256ns >= .10) & (raw.split_half_coherence_256ns >= .55)
        )
        supported_onset = accepted & raw_support & (screen.stages == "onset")
        onset_index = np.flatnonzero(supported_onset)
        if len(onset_index):
            onset_times.append(float(screen.channel.t[result.sample_index[onset_index[0]]]))
        for name in METRICS:
            values = getattr(raw, name)[accepted]
            quality[name].append(values[np.isfinite(values)])
    metrics: dict[str, object] = dict(channel=channel, stage=stage, method=method,
                                     centers=eligible, candidate_n=candidate_n, accepted_n=accepted_n,
                                     missing_n=eligible-accepted_n)
    for name, series in quality.items():
        values = np.concatenate(series)
        metrics[name] = float(np.median(values)) if len(values) else float("nan")
        metrics[f"{name}_n"] = len(values)
    metrics.update(
        jumps_250mhz=jumps,
        first_onset_supported_s=(onset_times[0] if channel != "all" and onset_times else float("nan")),
        noise_stationary_centers=background_n,
        noise_stationary_false_n=background_accepted_n,
        baseline_exact_parity=True if method in METHODS[:3] else "",
    )
    return metrics


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(output: Path) -> None:
    """Create a fresh complete screening output tree."""
    output = output.resolve()
    if (TASK_OUTPUT.resolve() != TASK_OUTPUT or not output.is_relative_to(TASK_OUTPUT)
            or output == TASK_OUTPUT):
        raise ValueError("Output must be a new directory in the Research TASK-023 artifact tree")
    output.mkdir(parents=True, exist_ok=False)
    tables, figures = output / "tables", output / "figures"
    tables.mkdir()
    figures.mkdir()
    timing: list[dict[str, object]] = []
    screens: list[Screening] = []
    for channel in CHANNELS:
        screen = _run_channel(channel, timing)
        screens.append(screen)
        _centers(tables / f"phase1_centers_{channel}.csv", screen)
        started = perf_counter()
        save_channel_figures(screen.channel, screen.results, figures)
        timing.append(dict(channel=channel, method="figures", seconds=perf_counter()-started,
                           scope="overview and zoom cards, PNG and SVG"))
    by_stage = [_metrics([screen], method, stage) for screen in screens
                for stage in dict.fromkeys(screen.stages[screen.channel.primary])
                for method in METHODS]
    overall = [_metrics([screen], method, "all") for screen in screens for method in METHODS]
    overall.extend(_metrics(screens, method, "all") for method in METHODS)
    _write_rows(tables / "phase1_per_channel_stage.csv", by_stage)
    _write_rows(tables / "phase1_summary.csv", overall)
    _write_rows(tables / "phase1_timing.csv", timing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT,
                        help="fresh directory inside the TASK-023 artifact tree")
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
