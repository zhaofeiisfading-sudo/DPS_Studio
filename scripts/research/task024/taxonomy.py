"""Mutually exclusive evidence categories and full strong-drop audit."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray

from scripts.research.task023 import phase_coherent as m4
from scripts.research.task023.coherent import Hypotheses, off_threshold
from scripts.research.task023.common import Estimate, MatchedEvidence, RawEvaluator
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.pursuit import rail_mask
from scripts.research.task023.waveform import FMAX, Bool, Float, samples_for_ns
from scripts.research.task024.ablations import FULL, VARIANTS
from scripts.research.task024.controls import B1
from scripts.research.task024.replay import OOB_CHANNEL, RAW_KEYS

Row: TypeAlias = dict[str, object]
AGREE = "both_agree_50MHz"
DISAGREE_MID = "both_disagree_50_250MHz"
DISAGREE_HIGH = "both_disagree_gt250MHz"
ADD_STRONG = "m4_added_strong_raw"
ADD_WEAK = "m4_added_weak_coherent"
ADD_AMBIG = "m4_added_cw_or_lowamp_ambiguous"
DROP_WEAK = "m4_dropped_weak_or_artifact"
DROP_RISK = "m4_dropped_strong_short_risk"
REJECT = "both_rejected"
CATEGORIES = (
    AGREE, DISAGREE_MID, DISAGREE_HIGH, ADD_STRONG, ADD_WEAK, ADD_AMBIG, DROP_WEAK, DROP_RISK,
    REJECT,
)
LOWAMP_DB = 3.


@dataclass(frozen=True)
class Classification:
    category: NDArray[np.str_]
    delta_hz: Float
    low_wideband_snr: Bool
    strong_raw: Bool
    weak_coherent_raw: Bool


def classify(b1: Estimate, full: Estimate) -> Classification:
    np.testing.assert_array_equal(b1.sample_index, full.sample_index)
    a, b = np.isfinite(b1.accepted_hz), np.isfinite(full.accepted_hz)
    delta = abs(full.accepted_hz-b1.accepted_hz)
    short, long, rho = (full.raw.raw_chirp_r2_64ns, full.raw.raw_chirp_r2_256ns,
                        full.raw.split_half_coherence_256ns)
    cw = np.asarray(full.diagnostics["persistent_cw_overlap"], dtype=np.bool_)
    lowamp = full.raw.local_center_snr_32ns < LOWAMP_DB
    strong = (short >= .15) | ((long >= .08) & (rho >= .60))
    weak = (long >= .04) & (rho >= .58) & ~strong
    clean = ~cw & ~lowamp
    added, dropped = b & ~a, a & ~b
    drop_risk = b1.raw.raw_chirp_r2_64ns >= .15
    both = a & b
    masks = (
        both & (delta <= 50e6),
        both & (delta > 50e6) & (delta <= 250e6),
        both & (delta > 250e6),
        added & clean & strong,
        added & clean & weak,
        added & ~(clean & (strong | weak)),
        dropped & ~drop_risk,
        dropped & drop_risk,
        ~(a | b),
    )
    if not np.all(np.sum(masks, axis=0) == 1):
        raise AssertionError("The evidence categories fail the pointwise partition check")
    return Classification(np.select(masks, CATEGORIES, default=""), delta, lowamp, strong, weak)


def _evidence(result: Estimate, name: str, i: int | np.int64) -> Row:
    return {
        f"{name}_candidate_hz": result.candidate_hz[i],
        f"{name}_accepted_hz": result.accepted_hz[i],
        f"{name}_chirp_hz_s": result.chirp_hz_s[i],
        **{f"{name}_{key}": getattr(result.raw, key)[i] for key in RAW_KEYS},
    }


def point_rows(screen: Screening, label: Classification) -> list[Row]:
    ch, results = screen.channel, screen.results
    baseline, full = results[B1], results[FULL]
    lower = np.minimum(baseline.accepted_hz, full.accepted_hz)
    higher = np.maximum(baseline.accepted_hz, full.accepted_hz)
    order = np.rint(higher/lower)
    tolerance = np.minimum(120e6, .06*higher+35e6)
    harmonic = (order >= 2) & (order <= 8) & (abs(higher-order*lower) <= tolerance)
    rows: list[Row] = []
    for i in np.flatnonzero(ch.primary):
        row: Row = dict(channel=ch.id, sample_index=ch.q[i], time_s=ch.t[ch.q[i]],
                        primary=True, visual_stage=screen.stages[i],
                        segment_id=screen.segments[i], category=label.category[i],
                        abs_delta_hz=label.delta_hz[i],
                        low_wideband_snr=label.low_wideband_snr[i],
                        strong_raw_threshold_pass=label.strong_raw[i],
                        weak_coherent_threshold_pass=label.weak_coherent_raw[i])
        row.update(_evidence(baseline, B1, i))
        row.update(_evidence(full, FULL, i))
        row.update(
            M4_minus_B1_raw_r2_64ns=(
                full.raw.raw_chirp_r2_64ns[i] - baseline.raw.raw_chirp_r2_64ns[i]),
            M4_minus_B1_raw_r2_256ns=(
                full.raw.raw_chirp_r2_256ns[i] - baseline.raw.raw_chirp_r2_256ns[i]),
            M4_minus_B1_rho_256ns=(
                full.raw.split_half_coherence_256ns[i] - baseline.raw.split_half_coherence_256ns[i]),
            accepted_frequency_ratio_high_to_low=higher[i]/lower[i],
            nearby_integer_harmonic_order=order[i] if harmonic[i] else np.nan,
        )
        row.update({f"M4_{key}": values[i] for key, values in full.diagnostics.items()})
        rows.append(row)
    return rows


def _drop_reason(
    island: bool, has_verified: bool, near: bool, post: bool, score: float,
) -> str:
    if island:
        return "island_cleanup_veto"
    if has_verified:
        return "kinematic_path_selected_OFF_with_verified_hypotheses"
    if near:
        return "post_edge_gate_failed" if post else "pre_edge_side_veto"
    if not np.isfinite(score) or score < off_threshold() - .75:
        return "no_proposal_above_initial_verification_score"
    return "all_scored_hypotheses_failed_raw_verification"


def _probe_gate(
    i: int, hz: float, near: bool, post: bool, fit: m4.Verification,
    short: MatchedEvidence, low_loss: float, sustained: bool,
) -> str:
    if fit.valid[i]:
        return "passed"
    if near:
        if not post:
            return "pre_edge_side_veto"
        misses = (("post_R2_below_0p25", fit.post_step_r2[i] >= .25),
                  ("post_SNR_below_10dB", fit.snr_full_db[i] >= 10.),
                  ("usable_fewer_than_1_cycle", fit.cycles[i] >= 1.))
        return "|".join(name for name, passed in misses if not passed)
    short_misses = (("short_R2_below_0p15", fit.short_r2[i] >= .15),
                    ("short_full_SNR_below_9dB", short.snr_db[i]-low_loss >= 9.),
                    ("short_min_half_SNR_below_3dB", short.half_snr_db[i]-low_loss >= 3.),
                    ("short_coherence_below_0p25", short.rho[i] >= .25),
                    ("short_fewer_than_1_cycle", hz*6.4e-9 >= 1.))
    return "|".join((
        *(name for name, passed in short_misses if not passed),
        "lowfreq_requires_long_verification" if hz < 250e6 else "long_fallback_not_verified",
        *(("lowfreq_sustained_evaluator_failed",) if hz < 250e6 and not sustained else ()),
    ))


def strong_drop_details(
    screen: Screening, label: Classification, wide: dict[str, Estimate],
) -> tuple[list[Row], list[Row]]:
    ch = replace(screen.channel, segments=())
    centers = np.flatnonzero(ch.primary & (label.category == DROP_RISK))
    if not len(centers):
        return [], []
    full, b1 = (screen.results[name] for name in (FULL, B1))
    d = full.diagnostics
    rail = rail_mask(ch.y)
    edges, rail_exit = m4._support_edges(ch, rail)
    ev = RawEvaluator(ch)
    hz, rate = b1.accepted_hz, b1.chirp_hz_s
    # Test the exact B1 hypothesis with the raw gates, granting it nomination.
    # This is a counterfactual raw-fit probe and leaves the actual M4 path intact.
    scores = np.full(len(ch.q), off_threshold())
    short = ev.matched(centers, hz[centers], rate[centers], 6.4)
    long = ev.matched(centers, hz[centers], rate[centers], 25.6)
    longest = ev.matched(centers, hz[centers], rate[centers], 38.4)
    noise = m4._VerificationNoise(ch)
    low_loss = noise.low_frequency_loss(hz[centers])
    short_width = samples_for_ns(6.4, ch.fs)
    near, post, nearest = m4._edge_at(ch.q[centers], edges.index, short_width//2)
    rail_boundary = near & np.isin(nearest, rail_exit)
    fit = m4._verify(ch, ev, Hypotheses(hz[:, None], rate[:, None], scores[:, None],
                                      scores[:, None], scores[:, None]), centers,
                     np.zeros_like(centers), edges, rail, noise)
    sustained = ev.low_frequency_supported(centers, hz[centers], rate[centers])
    cuts = np.flatnonzero(np.diff(centers) != 1)+1
    clusters = np.split(np.arange(len(centers)), cuts)
    details, summaries = [], []
    for number, cluster in enumerate(clusters, start=1):
        cluster_id = f"{ch.id}:{number:02d}"
        indexes = centers[cluster]
        times = ch.t[ch.q[indexes]]
        reasons = []
        above_any = False
        forced_valid = 0
        for j in cluster:
            i = centers[j]
            score = float(d["whitened_score"][i])
            reason = _drop_reason(bool(d["island_removed"][i]),
                                  bool(d["verified_hypothesis_count"][i]), bool(near[j]),
                                  bool(post[j]), score)
            wide_hz = float(wide["M4_8G"].accepted_hz[i]) if ch.id == OOB_CHANNEL else np.nan
            above = bool(wide_hz > FMAX)
            reasons.append(reason)
            above_any |= above
            forced_valid += int(fit.valid[j])
            row: Row = dict(
                channel=ch.id, cluster_id=cluster_id, time_s=ch.t[ch.q[i]], sample_index=ch.q[i],
                visual_stage=screen.stages[i], rejection_stage=reason,
                nearby_boundary=("rail_exit" if rail_boundary[j] else "detected_DC_step"
                                 if near[j] else ""),
                offset_from_boundary_ns=(ch.q[i]-nearest[j])/ch.fs*1e9 if near[j] else np.nan,
                m4_wide_hz=wide_hz, wide_published_above_primary_band=above,
                b1_probe_passes_m4_raw_gate=fit.valid[j], b1_probe_duration_ns=fit.duration_ns[j],
                b1_probe_gate_detail=_probe_gate(
                    int(j), float(hz[i]), bool(near[j]), bool(post[j]), fit, short,
                    float(low_loss[j]), bool(sustained[j])),
                b1_probe_post_step_r2=fit.post_step_r2[j], b1_probe_cycles=fit.cycles[j],
                b1_probe_short_r2=fit.short_r2[j], b1_probe_short_full_db=short.snr_db[j],
                b1_probe_short_half_db=short.half_snr_db[j], b1_probe_short_rho=short.rho[j],
                b1_probe_low_floor_loss_db=low_loss[j],
                b1_probe_25p6ns_r2=long.r2[j], b1_probe_25p6ns_rho=long.rho[j],
                b1_probe_25p6ns_min_half_db=long.half_snr_db[j],
                b1_probe_38p4ns_r2=longest.r2[j], b1_probe_38p4ns_rho=longest.rho[j],
                b1_probe_38p4ns_min_half_db=longest.half_snr_db[j],
                b1_probe_lowfreq_evaluator_sustained=sustained[j],
                b1_probe_38p4ns_short_amplitude_ratio=(
                    abs(short.phasor[j])/max(abs(longest.phasor[j]), 1e-30)),
            )
            row.update(_evidence(b1, B1, i))
            row.update(_evidence(full, FULL, i))
            row.update({f"M4_{key}": values[i] for key, values in d.items()})
            row.update({f"{v}_accepted_hz": screen.results[v].accepted_hz[i]
                        for v in VARIANTS[1:]})
            details.append(row)
        summaries.append(dict(
            case="strong_short_drop_cluster", channel=ch.id, cluster_id=cluster_id, method=FULL,
            time_start_s=times[0], time_end_s=times[-1], centers_n=len(cluster),
            b1_hz_min=np.min(hz[indexes]), b1_hz_max=np.max(hz[indexes]),
            b1_short_r2_min=np.min(b1.raw.raw_chirp_r2_64ns[indexes]),
            b1_short_r2_max=np.max(b1.raw.raw_chirp_r2_64ns[indexes]),
            rejection_stages="|".join(dict.fromkeys(reasons)),
            b1_probe_passes_raw_gate_n=forced_valid,
            wide_published_above_primary_band=above_any,
        ))
    return details, summaries
