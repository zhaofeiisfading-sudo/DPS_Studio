"""Replay the five-channel methods and audit the label-free Phase 2 gates."""
from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

import numpy as np

from scripts.research.task023.common import RawEvaluator
from scripts.research.task023.methods import m4_phase_coherent
from scripts.research.task023.phase1_plots import save_channel_figures
from scripts.research.task023.phase1_run import (
    CHANNELS, METHODS, OUT, TASK_OUTPUT, Screening, _centers, _metric_masks, _metrics,
    _run_channel, _write_rows,
)
from scripts.research.task023.regime import Observables, Regime, Segmentation, observables, segment
from scripts.research.task023.waveform import Float

PHASE2_OUTPUT = TASK_OUTPUT / "phase2"
PHASE2_METHODS = (*METHODS, "M4")
VISUAL_TO_REGIME = {
    "noise": Regime.NOISE_OR_QUIET, "stationary": Regime.NOISE_OR_QUIET,
    "unknown": Regime.PRECURSOR_OR_CLUTTER, "onset": Regime.STEP_ONSET,
    "plateau": Regime.STEADY_RIDGE, "decline": Regime.CHIRPING_RIDGE,
    "acceleration": Regime.CHIRPING_RIDGE, "rebound": Regime.CHIRPING_RIDGE,
    "weak_signal": Regime.WEAK_COHERENT_TAIL,
}


@dataclass(frozen=True)
class Audit:
    screen: Screening
    regimes: Segmentation
    obs: Observables
    adaptive_snr_db: Float
    adaptive_half_db: Float
    adaptive_coherence: Float

    def columns(self) -> dict[str, Iterable[object]]:
        return {
            "regime": self.regimes.labels,
            "regime_emission_margin": self.regimes.margin,
            "regime_rms_split_ratio": np.full(len(self.regimes.index), self.regimes.rms_split_ratio),
            "regime_dc_or_rail_edge": self.obs.dc_step,
            "regime_local_rms_ratio": self.obs.local_rms_ratio,
            "regime_abs_chirp_rate_hz_s": self.obs.abs_chirp_rate,
            "regime_diagnostic_window_ns": self.regimes.diagnostic_window_ns,
            "regime_window_snr_full_db": self.adaptive_snr_db,
            "regime_window_snr_min_half_db": self.adaptive_half_db,
            "regime_window_split_half_coherence": self.adaptive_coherence,
        }


def _replay_phase1(screen: Screening) -> None:
    path = OUT / "tables" / f"phase1_centers_{screen.channel.id}.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        archive = list(csv.DictReader(stream))
    np.testing.assert_array_equal(screen.channel.q, [int(row["sample_index"]) for row in archive])
    np.testing.assert_array_equal(screen.channel.t[screen.channel.q],
                                  [float(row["time_s"]) for row in archive])
    for method in METHODS:
        trace = screen.results[method]
        for suffix, values in (("hz", trace.accepted_hz), ("candidate_hz", trace.candidate_hz),
                               ("chirp_hz_s", trace.chirp_hz_s)):
            np.testing.assert_array_equal(
                values, [float(row[f"{method}_{suffix}"]) for row in archive],
                err_msg=f"Phase 1B parity {screen.channel.id} {method} {suffix}",
            )


def _audit(screen: Screening, timings: list[dict[str, object]]) -> Audit:
    ch = replace(screen.channel, segments=())
    started = perf_counter()
    m4 = m4_phase_coherent(ch)
    timings.append(dict(channel=ch.id, method="M4", seconds=perf_counter()-started,
                        scope="cold estimator, quiet model and raw evidence"))
    started = perf_counter()
    obs = observables(ch, m4)
    regimes = segment(obs)
    full, half, coherence = (np.full(len(ch.q), np.nan) for _ in range(3))
    ev = RawEvaluator(ch)
    for duration in (6.4, 12.8, 25.6, 38.4):
        use = np.flatnonzero(regimes.diagnostic_window_ns == duration)
        fit = ev.matched(use, m4.accepted_hz[use], m4.chirp_hz_s[use], duration)
        full[use], half[use], coherence[use] = fit.snr_db, fit.half_snr_db, fit.rho
    timings.append(dict(channel=ch.id, method="regime", seconds=perf_counter()-started,
                        scope="label-free BIC, HMM and adaptive-window evidence"))
    return Audit(replace(screen, results={**screen.results, "M4": m4}), regimes, obs,
                 full, half, coherence)


def _confusion(audits: list[Audit]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for group in [[audit] for audit in audits] + [audits]:
        channel = group[0].screen.channel.id if len(group) == 1 else "all"
        primary = [audit.screen.channel.primary for audit in group]
        visual = np.concatenate([audit.screen.stages[mask]
                                 for audit, mask in zip(group, primary, strict=True)])
        inferred = np.concatenate([audit.regimes.index[mask]
                                   for audit, mask in zip(group, primary, strict=True)])
        for stage in sorted(set(visual)):
            mapped = VISUAL_TO_REGIME[str(stage)]
            own = inferred[visual == stage]
            for regime in Regime:
                count = int(np.count_nonzero(own == regime))
                rows.append(dict(channel=channel, visual_stage=stage, mapped_regime=mapped.name,
                                 inferred_regime=regime.name, count=count, visual_centers=len(own),
                                 fraction=count/len(own), agreement=(mapped == regime)))
    return rows


def _summary(group: list[Audit], method: str, stage: str) -> dict[str, object]:
    screens = [audit.screen for audit in group]
    row = _metrics(screens, method, stage)
    cw = competing_cw = isolated = noise_excluding_cw = long_only = 0
    window_eligible = adaptive_confirmed = 0
    first_onset = float("nan")
    for audit in group:
        screen = audit.screen
        mask, accepted = _metric_masks(screen, method, stage)
        earliest = np.flatnonzero(accepted & (screen.stages == "onset"))
        if len(group) == 1 and len(earliest):
            first_onset = float(screen.channel.t[screen.channel.q[earliest[0]]])
        if method != "M4":
            continue
        result = screen.results["M4"]
        d = result.diagnostics
        persistent = audit.regimes.index == Regime.PERSISTENT_CW_TAIL
        cw += int(np.count_nonzero(accepted & persistent))
        competing_cw += int(np.count_nonzero(accepted & np.asarray(d["competing_cw_present"], bool)))
        isolated += int(np.count_nonzero(mask & np.asarray(d["island_removed"], bool)))
        background = np.isin(screen.stages, ("noise", "stationary"))
        noise_excluding_cw += int(np.count_nonzero(accepted & background & ~persistent))
        long_only += int(np.count_nonzero(accepted & (d["verification_window_ns"] >= 25.6)
                                          & (result.raw.raw_chirp_r2_256ns < .10)))
        eligible = accepted & ~audit.obs.dc_step & np.isfinite(audit.adaptive_snr_db)
        window_eligible += int(np.count_nonzero(eligible))
        confirm = ((audit.adaptive_snr_db >= 11.) & (audit.adaptive_half_db >= 5.)
                   & (audit.adaptive_coherence >= .58))
        adaptive_confirmed += int(np.count_nonzero(eligible & confirm))
    row.update(first_published_onset_s=first_onset,
               regime_cw_n=cw if method == "M4" else "",
               competing_cw_n=competing_cw if method == "M4" else "",
               noise_stationary_excluding_regime_cw_n=noise_excluding_cw if method == "M4" else "",
               island_suppressed_n=isolated if method == "M4" else "",
               narrowband_long_below_legacy_r2_n=long_only if method == "M4" else "",
               regime_window_eligible_n=window_eligible if method == "M4" else "",
               regime_window_coherent_n=adaptive_confirmed if method == "M4" else "")
    return row


def run(output: Path) -> None:
    """Create a fresh screening tree while preserving the Phase 1B freeze."""
    output = output.resolve()
    if (TASK_OUTPUT.resolve() != TASK_OUTPUT or not output.is_relative_to(TASK_OUTPUT)
            or output == TASK_OUTPUT or output.is_relative_to(OUT)):
        raise ValueError("Output must be fresh and inside TASK-023, outside the Phase 1 tree")
    output.mkdir(parents=True, exist_ok=False)
    tables, figures = output / "tables", output / "figures"
    tables.mkdir()
    figures.mkdir()
    audits: list[Audit] = []
    timing: list[dict[str, object]] = []
    for name in CHANNELS:
        screen = _run_channel(name, timing)
        started = perf_counter()
        _replay_phase1(screen)
        timing.append(dict(channel=name, method="phase1_parity", seconds=perf_counter()-started,
                           scope="exact Phase 1B times, candidate, published and chirp arrays"))
        audit = _audit(screen, timing)
        screen = audit.screen
        audits.append(audit)
        _centers(tables / f"phase2_centers_{name}.csv", screen, audit.columns())
        started = perf_counter()
        save_channel_figures(screen.channel, screen.results, figures, audit.regimes)
        timing.append(dict(channel=name, method="figures", seconds=perf_counter()-started,
                           scope="overview and hard zoom cards in PNG and SVG"))
        print(f"{name} | M4={np.count_nonzero(audit.obs.tracked & screen.channel.primary)} "
              "primary centers accepted", flush=True)
    _write_rows(tables / "phase2_summary.csv", [
        _summary(group, method, "all") for group in [[audit] for audit in audits] + [audits]
        for method in PHASE2_METHODS
    ])
    _write_rows(tables / "phase2_per_channel_stage.csv", [
        _summary([audit], method, stage) for audit in audits
        for stage in dict.fromkeys(audit.screen.stages[audit.screen.channel.primary])
        for method in PHASE2_METHODS
    ])
    _write_rows(tables / "phase2_timing.csv", timing)
    _write_rows(tables / "phase2_regime_confusion.csv", _confusion(audits))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PHASE2_OUTPUT)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
