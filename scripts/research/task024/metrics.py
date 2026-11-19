"""Post-estimation stage, pair, chirp and runtime readouts."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from scripts.research.task023.common import Estimate
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.phase3_pairs import CLIP_WINDOW_NS, PairComparison, agreement_metrics
from scripts.research.task023.waveform import FMAX, Bool, Float
from scripts.research.task024.ablations import FULL, NO_CHIRP, VARIANTS
from scripts.research.task024.controls import B1, LONG_QUAD, QUAD, strategy
from scripts.research.task024.replay import METHODS, RAW_KEYS, WIDE_METHODS
from scripts.research.task024.taxonomy import Row

CHIRP_METHODS = (B1, QUAD, LONG_QUAD, NO_CHIRP, FULL)
CHIRP_BINS = ("<0.5", "0.5–1.5", "1.5–3.0", ">=3.0", "missing_rate")
SCALE_STAGES = tuple(f"_scale_peaks_{ns:g}ns" for ns in (6.4, 12.8, 25.6, 38.4))
PURSUIT_STAGES = tuple(f"_pursue_{ns:g}ns" for ns in (6.4, 12.8, 25.6))
GAP_STAGES = ("_around_gaps", "_verify_gap", "_select_final")
PROFILE_STAGES = ("quiet_model", *SCALE_STAGES, *PURSUIT_STAGES, "proposal_other",
                  "_verify_initial", "_select_initial", "gap_and_reselect",
                  "RawEvaluator.evaluate", "other")


def number(mask: Bool) -> int:
    return int(np.count_nonzero(mask))


def median(values: Float) -> float:
    finite = values[np.isfinite(values)]
    return float(np.median(finite)) if len(finite) else float("nan")


def fraction(n: int, total: int) -> float:
    return n / total if total else float("nan")


def stage_masks(screen: Screening) -> dict[str, Bool]:
    ch = screen.channel
    d = screen.results[FULL].diagnostics
    noise = screen.stages == "noise"
    stationary = screen.stages == "stationary"
    no_cw = ~np.asarray(d["persistent_cw_overlap"], dtype=np.bool_)
    return {
        "all": ch.primary,
        **{str(stage): ch.primary & (screen.stages == stage) for stage in np.unique(screen.stages)},
        "noise_or_stationary": ch.primary & (noise | stationary),
        "noise_excluding_M4_CW_overlap": ch.primary & noise & no_cw,
        "stationary_excluding_M4_CW_overlap": ch.primary & stationary & no_cw,
    }


def _summarize(name: str, groups: list[tuple[Screening, Bool]]) -> Row:
    estimates = [(item.results[name], item.results[FULL], mask)
                 for item, mask in groups]
    n = sum(number(mask) for _, _, mask in estimates)
    candidates = sum(number(mask & np.isfinite(x.candidate_hz)) for x, _, mask in estimates)
    gated = [(x, full, mask & np.isfinite(x.accepted_hz)) for x, full, mask in estimates]
    accepted = sum(number(mask) for _, _, mask in gated)
    metrics: Row = dict(centers_n=n, candidate_n=candidates, accepted_n=accepted,
                        rejected_n=n-accepted, accepted_fraction=fraction(accepted, n))
    for key in RAW_KEYS:
        if key == "S_256":
            continue
        values = np.concatenate([getattr(x.raw, key)[mask] for x, _, mask in gated])
        metrics[f"median_{key}"] = median(values)
        metrics[f"{key}_finite_n"] = number(np.isfinite(values))
    delta = np.concatenate([abs(x.accepted_hz[mask] - full.accepted_hz[mask])
                            for x, full, mask in gated])
    metrics.update(
        jointly_published_M4_n=number(np.isfinite(delta)),
        median_abs_delta_M4_mhz=median(delta)/1e6,
        disagreements_M4_gt250mhz_n=number(delta > 250e6),
        adjacent_jumps_gt250mhz_n=sum(
            number(mask[1:] & mask[:-1] & (abs(np.diff(x.accepted_hz)) > 250e6))
            for x, _, mask in gated
        ),
    )
    if name not in VARIANTS:
        complete_n = complete_accepted_n = 0
        for item, mask in groups:
            result = item.results[name]
            nominal = strategy(name, item.channel.fs).width
            complete = mask & (result.diagnostics["support_samples"] == nominal)
            complete_n += number(complete)
            complete_accepted_n += number(complete & np.isfinite(result.accepted_hz))
        metrics.update(full_window_n=complete_n, full_window_published_n=complete_accepted_n,
                       full_window_published_fraction=fraction(complete_accepted_n, complete_n))
    return metrics


def stage_comparison(screens: list[Screening]) -> tuple[list[Row], list[Row]]:
    by_channel: list[Row] = []
    grouped: dict[str, list[tuple[Screening, Bool]]] = {}
    for item in screens:
        ch = item.channel
        for stage, mask in stage_masks(item).items():
            grouped.setdefault(stage, []).append((item, mask))
            for name in METHODS:
                row = dict(channel=ch.id, sample_rate_hz=ch.fs, visual_stage=stage, method=name,
                           **_summarize(name, [(item, mask)]))
                if name not in VARIANTS:
                    spec = strategy(name, ch.fs)
                    row.update(window_samples=spec.width, window_duration_ns=spec.width/ch.fs*1e9,
                               nfft=spec.nfft, degree=spec.degree)
                by_channel.append(row)
    pooled = [dict(cohort="all_14", visual_stage=stage, method=name, **_summarize(name, groups))
              for stage, groups in grouped.items() for name in METHODS]
    return pooled, by_channel


def pair_comparison(pairs: Iterable[PairComparison]) -> list[Row]:
    rows: list[Row] = []
    for pair in pairs:
        clipped = pair.clipped_ch1 | pair.clipped_ch2
        all_centers = np.ones(len(pair.time_s), dtype=np.bool_)
        stages = {"all": all_centers, **{str(s): pair.stage == s for s in np.unique(pair.stage)}}
        if pair.shot == "20260607":
            stages["late_555p70_to_555p75us"] = (pair.time_s >= 555.70e-6) & (
                pair.time_s <= 555.75e-6)
        for stage, mask in stages.items():
            for label, clip in (("all", all_centers), ("clipped", clipped), ("unclipped", ~clipped)):
                use = mask & clip
                for method in METHODS:
                    rows.append(dict(
                        shot=pair.shot, method=method, visual_stage=stage, clipping=label,
                        clip_width_ns=CLIP_WINDOW_NS,
                        clipped_ch1_n=number(use & pair.clipped_ch1),
                        clipped_ch2_n=number(use & pair.clipped_ch2),
                        unmatched_ch1_centers=pair.unmatched_ch1_centers,
                        unmatched_ch2_centers=pair.unmatched_ch2_centers,
                        raw_lag_samples=pair.lag.samples, raw_lag_s=pair.lag.seconds,
                        raw_lag_correlation=pair.lag.correlation,
                        raw_lag_peak_margin=pair.lag.peak_margin,
                        raw_lag_search_radius_samples=pair.lag.search_radius_samples,
                        **agreement_metrics(pair.accepted_ch1[method][use],
                                            pair.accepted_ch2[method][use]),
                    ))
    return rows


def chirp_comparison(screens: list[Screening]) -> list[Row]:
    stages = np.concatenate([item.stages[item.channel.primary] for item in screens])
    combined = np.isin(stages, ("decline", "weak_signal"))
    rate = np.concatenate([item.results[FULL].chirp_hz_s[item.channel.primary] for item in screens])
    outputs = {name: np.concatenate([item.results[name].accepted_hz[item.channel.primary]
                                    for item in screens]) for name in CHIRP_METHODS}
    diagnostics = {
        name: {
            key: np.concatenate([getattr(item.results[name].raw, key)[item.channel.primary]
                                 for item in screens])
            for key in ("raw_chirp_r2_256ns", "split_half_coherence_256ns")
        } for name in CHIRP_METHODS
    }
    full = outputs[FULL]
    published = np.isfinite(full)
    rows = []
    for duration in (25.6, 38.4):
        beta = abs(rate)*(duration*1e-9)**2
        beta_bin = np.where(np.isfinite(beta), np.digitize(beta, [.5, 1.5, 3.]), 4)
        for stage, stage_mask in (("decline_and_weak_signal", combined),
                                  ("decline", stages == "decline"),
                                  ("weak_signal", stages == "weak_signal")):
            for i, label in enumerate(CHIRP_BINS):
                in_bin = stage_mask & (beta_bin == i)
                cohorts = (("all", in_bin), ("M4_published_rate", in_bin & published),
                           ("M4_unpublished_center", in_bin & ~published))
                for cohort, use in cohorts:
                    n = number(use)
                    for name in CHIRP_METHODS:
                        valid = use & np.isfinite(outputs[name])
                        delta = abs(full[valid] - outputs[name][valid])
                        accepted = number(valid)
                        rows.append(dict(
                            visual_stage=stage, rate_cohort=cohort, observation_ns=duration,
                            beta_bin_cycles=label, median_beta_cycles=median(beta[use]), method=name,
                            centers_n=n, n_M4_published=number(use & published),
                            n_M4_finite_rate=number(use & np.isfinite(rate)),
                            published_n=accepted, published_fraction=fraction(accepted, n),
                            jointly_published_M4_n=number(np.isfinite(delta)),
                            median_abs_delta_M4_mhz=median(delta)/1e6,
                            **{f"median_{key}": median(value[valid])
                               for key, value in diagnostics[name].items()},
                            **{f"{key}_finite_n": number(valid & np.isfinite(value))
                               for key, value in diagnostics[name].items()},
                        ))
    return rows


def runtime_rows(timings: dict[str, dict[str, float]]) -> list[Row]:
    rows = []
    for channel, timing in timings.items():
        values = dict(timing)
        values["gap_and_reselect"] = sum(values.get(key, 0.) for key in GAP_STAGES)
        values["proposal_other"] = (values["_propose_total"]
                                    - sum(values[key] for key in (*SCALE_STAGES, *PURSUIT_STAGES)))
        total = values["cold_total"]
        values["other"] = total - sum(values[key] for key in PROFILE_STAGES if key != "other")
        rows.append(dict(channel=channel, standalone_cold_total_s=total,
                         **{f"{key}_s": values.get(key, 0.) for key in
                            (*PROFILE_STAGES, *GAP_STAGES, "_propose_total",
                             "independent_native_parity", *VARIANTS[1:])},
                         **{f"{key}_fraction": values[key]/total for key in PROFILE_STAGES}))
    return rows


def wide_rows(item: Screening, wide: dict[str, Estimate]) -> list[Row]:
    ch = item.channel
    results = {**{f"{name}_6G": item.results[key]
                  for name, key in zip(("B1", QUAD, "M4"), (B1, QUAD, FULL), strict=True)},
               **{name: wide[name] for name in WIDE_METHODS}}
    rows = []
    for i, time in enumerate(ch.t[ch.q]):
        row: Row = dict(sample_index=ch.q[i], time_s=time, primary=ch.primary[i],
                        visual_stage=item.stages[i], segment_id=item.segments[i],
                        plateau_82_974_83_340=82.974e-6 <= time <= 83.340e-6,
                        primary_fmax_hz=FMAX, diagnostic_fmax_hz=8e9)
        for name, result in results.items():
            row.update({f"{name}_candidate_hz": result.candidate_hz[i],
                        f"{name}_accepted_hz": result.accepted_hz[i],
                        f"{name}_above_6ghz": result.accepted_hz[i] > FMAX,
                        **{f"{name}_{key}": getattr(result.raw, key)[i] for key in RAW_KEYS}})
        rows.append(row)
    return rows
