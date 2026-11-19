"""Verify the clipping-harmonic fix on 14 channels and audit natural dual-gain pairs."""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np

from scripts.research.task017.compare import normalize
from scripts.research.task017.prepare import records
from scripts.research.task018.inputs import strategy_trace
from scripts.research.task023.common import Channel, Estimate, RawEvaluator
from scripts.research.task023.methods import m4_phase_coherent
from scripts.research.task023.phase1_plots import save_channel_figures
from scripts.research.task023.phase1_run import (
    CHANNELS, OUT, TASK_OUTPUT, Screening, _centers, _run_channel, _write_rows,
)
from scripts.research.task023.phase2_run import (
    PHASE2_METHODS, PHASE2_OUTPUT, Audit, _audit, _confusion, _summary,
)
from scripts.research.task023.phase3_pairs import PAIR_SHOTS, compare_pair, pair_rows
from scripts.research.task023.phase3_plots import PLATEAU_US, save_oob_figure, save_pair_figure
from scripts.research.task023.waveform import FMAX, FMIN

PHASE2B_OUTPUT = TASK_OUTPUT / "phase2b"
PHASE3_OUTPUT = TASK_OUTPUT / "phase3"
PHASE3B_OUTPUT = TASK_OUTPUT / "phase3b"
OOB_CHANNEL = "20201214m_ch1"
DIAGNOSTIC_FMAX = 8e9


def verify_archived_centers(actual: Path, archive: Path) -> int:
    """Require every archived field to match exactly, in the original row order."""
    with (
        actual.open(encoding="utf-8", newline="") as current_stream,
        archive.open(encoding="utf-8", newline="") as archive_stream,
    ):
        current, frozen = csv.reader(current_stream), csv.reader(archive_stream)
        current_fields, archive_fields = next(current), next(frozen)
        positions = [current_fields.index(field) for field in archive_fields]
        count = 0
        for line, (row, expected) in enumerate(zip(current, frozen, strict=True), start=2):
            for field, position, value in zip(archive_fields, positions, expected, strict=True):
                if row[position] != value:
                    raise ValueError(
                        f"{archive.name}:{line} {field}: {row[position]!r} != {value!r}"
                    )
            count += len(archive_fields)
        return count


def _report_phase2b_deltas(actual: Path, archive: Path, channel: str) -> tuple[int, int]:
    """Log value changes from the Phase 2B replay by center and field."""
    with (
        actual.open(encoding="utf-8", newline="") as current_stream,
        archive.open(encoding="utf-8", newline="") as archive_stream,
    ):
        current, frozen = csv.reader(current_stream), csv.reader(archive_stream)
        fields = next(frozen)
        if next(current) != fields:
            raise ValueError(f"{archive.name}: expected matching center CSV columns")
        time_column = fields.index("time_s")
        centers = changed_fields = 0
        for row, expected in zip(current, frozen, strict=True):
            changes = [f"{field} {old} -> {new}"
                       for field, old, new in zip(fields, expected, row, strict=True) if old != new]
            if changes:
                centers += 1
                changed_fields += len(changes)
                time_us = float(row[time_column]) * 1e6
                print(f"{channel} | Phase 2B delta at {time_us:.6f} us | "
                      + "; ".join(changes), flush=True)
        return centers, changed_fields


def wide_band_estimates(channel: Channel) -> tuple[Channel, dict[str, Estimate]]:
    """Run just B1 and M4 on a label-free channel copy with the 8 GHz cap."""
    wide = replace(channel, segments=(), fmax=DIAGNOSTIC_FMAX)
    trace = strategy_trace(wide.t, wide.y, "B1", fmax=wide.fmax)
    normalized = normalize(trace, wide.t, wide.fs)
    grid = wide.q//128
    candidate, accepted, rate = (
        np.asarray(normalized[key][grid], dtype=np.float64)
        for key in ("frequency_hz", "gated_frequency_hz", "chirp_hz_s")
    )
    b1 = Estimate(wide.q, candidate, accepted, rate, RawEvaluator(wide).evaluate(candidate, rate), {})
    return wide, {"B1_8G": b1, "M4_8G": m4_phase_coherent(wide)}


def _diagnostic(screen: Screening, tables: Path, figures: Path) -> None:
    wide, results = wide_band_estimates(screen.channel)
    results = {"B1_6G": screen.results["B1"], "M4_6G": screen.results["M4"], **results}
    time = wide.t[wide.q]
    lo, hi = (boundary*1e-6 for boundary in PLATEAU_US)
    rows: list[dict[str, object]] = []
    for i, (q, t) in enumerate(zip(wide.q, time, strict=True)):
        row: dict[str, object] = dict(
            sample_index=q, time_s=t, primary=wide.primary[i], visual_stage=screen.stages[i],
            segment_id=screen.segments[i], plateau_82_974_83_340=lo <= t <= hi,
            primary_fmax_hz=FMAX, diagnostic_fmax_hz=wide.fmax,
        )
        for name, trace in results.items():
            row[f"{name}_candidate_hz"] = trace.candidate_hz[i]
            row[f"{name}_accepted_hz"] = trace.accepted_hz[i]
            row[f"{name}_above_6ghz"] = bool(trace.accepted_hz[i] > FMAX)
            row[f"{name}_raw_chirp_r2_64ns"] = trace.raw.raw_chirp_r2_64ns[i]
            row[f"{name}_raw_chirp_r2_256ns"] = trace.raw.raw_chirp_r2_256ns[i]
            row[f"{name}_split_half_coherence_256ns"] = trace.raw.split_half_coherence_256ns[i]
        rows.append(row)
    _write_rows(tables / "phase3_20201214m_8ghz_diagnostic.csv", rows)
    save_oob_figure(wide, {key: trace.accepted_hz for key, trace in results.items()}, figures)


def _output_path(output: Path) -> Path:
    resolved = output.resolve()
    if (TASK_OUTPUT.resolve() != TASK_OUTPUT or resolved != output.absolute()
            or not resolved.is_relative_to(TASK_OUTPUT) or resolved == TASK_OUTPUT
            or any(resolved.is_relative_to(freeze)
                   for freeze in (OUT, PHASE2_OUTPUT, PHASE2B_OUTPUT, PHASE3_OUTPUT))):
        raise ValueError("Output must be fresh inside TASK-023 and outside the frozen phase trees")
    return resolved


def run(output: Path) -> None:
    inventory = records()
    names = [str(row["id"]) for row in inventory]
    if (len(names) != 14 or len(set(names)) != 14
            or len({row["file"] for row in inventory}) != 10 or not set(CHANNELS) <= set(names)):
        raise ValueError("Expected the 10-file, 14-channel inventory with all five screening channels")
    output = _output_path(output)
    output.mkdir(parents=True, exist_ok=False)
    tables, figures = output / "tables", output / "figures"
    tables.mkdir()
    figures.mkdir()
    audits: list[Audit] = []
    timing: list[dict[str, object]] = []
    phase1_fields = phase2b_changed_centers = phase2b_changed_fields = 0
    for name in names:
        screen = _run_channel(name, timing)
        audit = _audit(screen, timing)
        screen = audit.screen
        for method, trace in screen.results.items():
            np.testing.assert_array_equal(trace.sample_index, screen.channel.q)
            published = trace.accepted_hz[np.isfinite(trace.accepted_hz)]
            if np.any((published < FMIN) | (published > FMAX)):
                raise ValueError(f"{name} {method} published outside the primary band")
        audits.append(audit)
        center_path = tables / f"phase3_centers_{name}.csv"
        _centers(center_path, screen, audit.columns())
        if name in CHANNELS:
            started = perf_counter()
            phase1_fields += verify_archived_centers(
                center_path, OUT / "tables" / f"phase1_centers_{name}.csv",
            )
            centers, fields = _report_phase2b_deltas(
                center_path, PHASE2B_OUTPUT / "tables" / f"phase2_centers_{name}.csv", name,
            )
            phase2b_changed_centers += centers
            phase2b_changed_fields += fields
            timing.append(dict(channel=name, method="frozen_csv_parity", seconds=perf_counter()-started,
                               scope="exact Phase 1B center fields and Phase 2B delta report"))
        started = perf_counter()
        save_channel_figures(screen.channel, screen.results, figures, audit.regimes)
        timing.append(dict(channel=name, method="figures", seconds=perf_counter()-started,
                           scope="overview and hard zoom cards in PNG and SVG"))
        print(f"{name} | M4={np.count_nonzero(audit.obs.tracked & screen.channel.primary)} "
              "primary centers accepted", flush=True)

    if phase1_fields != 317_223:
        raise ValueError(f"Expected 317,223 exact Phase 1B fields, checked {phase1_fields:,}")
    groups = {
        "screening_5": [audit for audit in audits if audit.screen.channel.id in CHANNELS],
        "heldout_9": [audit for audit in audits if audit.screen.channel.id not in CHANNELS],
        "all_14": audits,
    }
    by_channel = {audit.screen.channel.id: audit.screen for audit in audits}
    _write_rows(tables / "phase3_summary.csv", [
        _summary([audit], method, "all") for audit in audits for method in PHASE2_METHODS
    ] + [
        {**_summary(group, method, "all"), "channel": label}
        for label, group in groups.items() for method in PHASE2_METHODS
    ])
    _write_rows(tables / "phase3_per_channel_stage.csv", [
        _summary([audit], method, stage) for audit in audits
        for stage in dict.fromkeys(audit.screen.stages[audit.screen.channel.primary])
        for method in PHASE2_METHODS
    ])
    confusion = [{**row, "channel": "all_14"} if row["channel"] == "all" else row
                 for row in _confusion(audits)]
    _write_rows(tables / "phase3_regime_confusion.csv", [
        row for row in confusion if row["channel"] != "all_14"
    ] + [
        {**row, "channel": label} for label in ("screening_5", "heldout_9")
        for row in _confusion(groups[label]) if row["channel"] == "all"
    ] + [row for row in confusion if row["channel"] == "all_14"])

    pairs: list[dict[str, object]] = []
    for shot in PAIR_SHOTS:
        pair = compare_pair(shot, by_channel[f"{shot}_ch1"], by_channel[f"{shot}_ch2"])
        pairs.extend(pair_rows(pair))
        save_pair_figure(pair, figures)
        print(f"{shot} | {len(pair.time_s)} exact paired primary centers | "
              f"raw lag {pair.lag.samples:+d} samples", flush=True)
    _write_rows(tables / "phase3_dual_gain_pairs.csv", pairs)
    _diagnostic(by_channel[OOB_CHANNEL], tables, figures)
    _write_rows(tables / "phase3_timing.csv", timing)
    print(f"Exact screening parity | Phase 1B {phase1_fields:,} fields", flush=True)
    print(f"Phase 2B screening delta | {phase2b_changed_centers:,} centers | "
          f"{phase2b_changed_fields:,} fields", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PHASE3B_OUTPUT)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
