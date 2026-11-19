"""Failure case measurements and tracing of the frozen regime decoder."""
from __future__ import annotations

import csv
from dataclasses import replace

import numpy as np

from scripts.research.task023 import regime
from scripts.research.task023.common import Estimate
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.phase3_pairs import PairComparison, agreement_metrics
from scripts.research.task023.phase_coherent import CW_RATE_HZ_S
from scripts.research.task023.waveform import Bool
from scripts.research.task024.ablations import FULL, NO_PATH
from scripts.research.task024.controls import B1, LONG_QUAD, QUAD
from scripts.research.task024.metrics import fraction, median, number
from scripts.research.task024.replay import OOB_CHANNEL, PHASE3, WIDE_METHODS
from scripts.research.task024.taxonomy import Row

CASE_METHODS = (B1, QUAD, LONG_QUAD, FULL)
QUIET_CHANNELS = (
    "20260630-1_ch1", "20260630-1_ch2", "20260630-2_ch1", "20260630-2_ch2",
    "20260701_ch1", "20260701_ch2", "ch3_ch1", "20201210m_ch1", OOB_CHANNEL,
)
CW_STATE = regime.Regime.PERSISTENT_CW_TAIL
WEAK_STATE = regime.Regime.WEAK_COHERENT_TAIL


def _readout(item: Screening, method: str, result: Estimate, mask: Bool) -> Row:
    t = item.channel.t[item.channel.q]
    hz = result.accepted_hz
    accepted = mask & np.isfinite(hz)
    hit = hz[accepted]
    return dict(
        channel=item.channel.id, method=method, centers_n=number(mask),
        accepted_n=number(accepted), time_start_s=float(min(t[mask], default=np.nan)),
        time_end_s=float(max(t[mask], default=np.nan)),
        first_accepted_s=float(min(t[accepted], default=np.nan)),
        last_accepted_s=float(max(t[accepted], default=np.nan)),
        accepted_hz_min=float(min(hit, default=np.nan)),
        accepted_hz_median=median(hit), accepted_hz_max=float(max(hit, default=np.nan)),
        median_raw_chirp_r2_64ns=median(result.raw.raw_chirp_r2_64ns[accepted]),
        median_raw_chirp_r2_256ns=median(result.raw.raw_chirp_r2_256ns[accepted]),
        median_rho_256ns=median(result.raw.split_half_coherence_256ns[accepted]),
        near_1p83ghz_n=number(accepted & (abs(hz-1.83e9) <= 50e6)),
        near_100mhz_n=number(accepted & (abs(hz-100e6) <= 25e6)),
        accepted_above_6ghz_n=number(accepted & (hz > 6e9)),
        persistent_cw_overlap_n=number(accepted & np.asarray(result.diagnostics.get(
            "persistent_cw_overlap", np.zeros_like(mask)), dtype=np.bool_)),
    )


def case_rows(
    screens: dict[str, Screening], pairs: list[PairComparison], wide: dict[str, Estimate],
) -> list[Row]:
    rows: list[Row] = []
    for name in QUIET_CHANNELS:
        item = screens[name]
        ch = item.channel
        onset = next(seg["start_s"] for seg in ch.segments if seg["stage"] == "onset")
        slices = (("stationary", item.stages == "stationary"),
                  ("pre_onset", ch.t[ch.q] < onset), ("noise", item.stages == "noise"))
        for scope, mask in slices:
            if not (mask & ch.primary).any():
                continue
            for method in CASE_METHODS:
                rows.append(dict(case="quiet_precursor_and_noise_publications", visual_stage=scope,
                                 **_readout(item, method, item.results[method], mask & ch.primary)))
    late = next(pair for pair in pairs if pair.shot == "20260607")
    mask = (late.time_s >= 555.70e-6) & (late.time_s <= 555.75e-6)
    for name in (B1, QUAD, NO_PATH, FULL):
        left, right = late.accepted_ch1[name], late.accepted_ch2[name]
        rows.append(dict(case="dual_gain_late_split", channel=late.shot, method=name,
                         time_start_s=late.time_s[mask].min(), time_end_s=late.time_s[mask].max(),
                         **agreement_metrics(left[mask], right[mask])))
        for i in np.flatnonzero(mask & (abs(left-right) > 250e6)):
            rows.append(dict(case="dual_gain_late_split_point", channel=late.shot, method=name,
                             time_s=late.time_s[i], abs_delta_hz=abs(left[i]-right[i]),
                             ch1_accepted_hz=left[i], ch2_accepted_hz=right[i]))
    for name in ("20260701_ch1", "20260701_ch2"):
        item = screens[name]
        for stage in ("plateau", "weak_signal", "noise"):
            for method in (*CASE_METHODS, "M4_no_cw_harmonic"):
                rows.append(dict(
                    case="dual_gain_late_cw_asymmetry", visual_stage=stage,
                    **_readout(item, method, item.results[method],
                               item.channel.primary & (item.stages == stage)),
                ))
    item = screens[OOB_CHANNEL]
    times = item.channel.t[item.channel.q]
    scopes = {"all": item.channel.primary,
              "plateau_82_974_83_340": (times >= 82.974e-6) & (times <= 83.340e-6),
              **{str(stage): item.stages == stage for stage in np.unique(item.stages)}}
    for scope, mask in scopes.items():
        for method, result in (
            ("B1_6G", item.results[B1]), (f"{QUAD}_6G", item.results[QUAD]),
            ("M4_6G", item.results[FULL]), *((name, wide[name]) for name in WIDE_METHODS),
        ):
            rows.append(dict(case="band_ceiling_6_vs_8ghz", visual_stage=scope,
                             **_readout(item, method, result, mask & item.channel.primary)))
    return rows


def regime_rows(screens: list[Screening]) -> list[Row]:
    rows: list[Row] = []
    aggregate: dict[tuple[str, str], int] = {}
    totals: dict[str, int] = {}
    for item in screens:
        ch = replace(item.channel, segments=())
        m4 = item.results[FULL]
        obs = regime.observables(ch, m4)
        decoded = regime.segment(obs)
        archive = PHASE3 / f"phase3_centers_{ch.id}.csv"
        with archive.open(encoding="utf-8", newline="") as stream:
            np.testing.assert_array_equal(decoded.labels, [r["regime"] for r in csv.DictReader(stream)])
        emissions = regime._emission(obs, decoded.rms_split_ratio)
        without_cw = emissions.copy()
        without_cw[:, CW_STATE] = -np.inf
        decoded_without_cw = regime._decode(without_cw)
        short = (obs.verification_window_ns <= 12.8) | (obs.short_r2 >= .25)
        weak_eligible = np.isfinite(emissions[:, WEAK_STATE])
        for stage in np.unique(item.stages):
            label = str(stage)
            mask = ch.primary & (item.stages == stage)
            n = number(mask)
            totals[label] = totals.get(label, 0) + n
            for state in regime.Regime:
                count = number(mask & (decoded.index == state))
                key = label, state.name
                aggregate[key] = aggregate.get(key, 0) + count
                rows.append(dict(row_kind="confusion", channel=ch.id, visual_stage=label,
                                 decoded_regime=state.name, centers_n=n, count=count,
                                 fraction=fraction(count, n)))
            if label not in ("weak_signal", "plateau"):
                continue
            cw = mask & (decoded.index == CW_STATE)
            finite_rival = without_cw[cw].max(axis=1)
            rows.append(dict(
                row_kind="gate_trace", channel=ch.id, visual_stage=label, centers_n=n,
                tracked_n=number(mask & obs.tracked),
                tracked_short_support_n=number(mask & obs.tracked & short),
                tracked_without_short_support_n=number(mask & obs.tracked & ~short),
                tracked_long_without_short_n=number(
                    mask & obs.tracked & ~short & (obs.verification_window_ns >= 25.6)),
                weak_emission_eligible_n=number(mask & weak_eligible),
                weak_decoded_n=number(mask & (decoded.index == WEAK_STATE)),
                eligible_but_cw_decoded_n=number(cw & weak_eligible),
                weak_decoded_counterfactual_no_cw_emission_n=number(
                    mask & (decoded_without_cw == WEAK_STATE)),
                cw_decoded_n=number(cw), cw_overlap_n=number(mask & obs.persistent_cw_overlap),
                cw_line_median_hz=median(m4.accepted_hz[cw]),
                cw_max_abs_rate_hz_s=float(max(obs.abs_chirp_rate[cw], default=np.nan)),
                cw_rate_cut_hz_s=CW_RATE_HZ_S,
                cw_emission_value=median(emissions[cw, CW_STATE]),
                cw_median_best_competing_emission=median(finite_rival),
                cw_median_decoded_emission_margin=median(decoded.margin[cw]),
                cw_counterfactual_states="|".join(
                    f"{state.name}={number(cw & (decoded_without_cw == state))}"
                    for state in regime.Regime if (cw & (decoded_without_cw == state)).any()),
                rms_split_ratio=decoded.rms_split_ratio,
            ))
    for (stage, state_name), count in aggregate.items():
        n = totals[stage]
        rows.append(dict(row_kind="confusion", channel="all_14", visual_stage=stage,
                         decoded_regime=state_name, centers_n=n, count=count,
                         fraction=fraction(count, n)))
    return rows
