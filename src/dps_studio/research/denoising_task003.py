"""Observation-only vetoes of frozen bilateral proposals; research, not identity certification."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.research.denoising_task001 import Proposal, apply_repairs

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class RiskConfig:
    minimum_background_db: float = 12.
    maximum_step_hz: float = 200e6
    minimum_run_s: float = 12.8e-9
    minimum_supported_fraction: float = .8
    maximum_balance_db: float = 3.

    def __post_init__(self) -> None:
        if (not all(np.isfinite(v) for v in vars(self).values())
                or self.maximum_step_hz <= 0 or self.minimum_run_s <= 0
                or not 0 < self.minimum_supported_fraction <= 1
                or self.maximum_balance_db < 0):
            raise ValueError("Invalid risk configuration")


def diagnostics(peaks: RidgeCandidateSet, baseline_hz: FloatArray, proposal: Proposal,
                config: RiskConfig = RiskConfig()) -> dict[str, Any]:
    """No truth, component labels, family or outcome accepted at this boundary.

    Continuity is a frequency-nearness proxy, not a same-component assertion.
    Run duration uses frame-center span, not overlapping-window sample counts.
    """
    if (baseline_hz.shape != peaks.time_s.shape or not np.all(np.isfinite(baseline_hz))
            or proposal.first < 0 or proposal.stop > len(baseline_hz)
            or proposal.stop <= proposal.first):
        raise ValueError("Invalid baseline or proposal interval")
    indices = np.arange(proposal.first, proposal.stop)
    old = [min(peaks.candidates_by_frame[i],
               key=lambda c: abs(c.transition_frequency_hz - baseline_hz[i])) for i in indices]
    frequency = np.array([c.transition_frequency_hz for c in old])
    background = np.array([c.peak_to_background_db for c in old])
    supported = background >= config.minimum_background_db
    longest = 0.
    run_start = 0
    for k in range(len(indices)):
        if not supported[k]:
            run_start = k + 1
        elif k and (not supported[k - 1]
                    or abs(frequency[k] - frequency[k - 1]) > config.maximum_step_hz):
            run_start = k
        if supported[k]:
            longest = max(longest, float(peaks.time_s[indices[k]]
                                        - peaks.time_s[indices[run_start]]))
    balance = []
    old_amplitude = []
    new_amplitude = []
    for i, j in zip(proposal.frame_indices, proposal.candidate_indices, strict=True):
        a = old[int(i) - proposal.first].peak_amplitude
        b = peaks.candidates_by_frame[i][j].peak_amplitude
        balance.append(abs(20 * np.log10(max(a, 1e-300) / max(b, 1e-300))))
        old_amplitude.append(a)
        new_amplitude.append(b)
    continuous = (float(supported.mean()) >= config.minimum_supported_fraction
                  and longest + 1e-18 >= config.minimum_run_s)
    near_equal = float(np.median(balance)) <= config.maximum_balance_db
    return dict(supported_fraction=float(supported.mean()), longest_supported_run_s=longest,
                original_background_min_db=float(background.min()),
                original_background_median_db=float(np.median(background)),
                median_absolute_balance_db=float(np.median(balance)),
                original_amplitude_median_v=float(np.median(old_amplitude)),
                proposed_amplitude_median_v=float(np.median(new_amplitude)),
                original_internal_range_hz=float(np.ptp(frequency)),
                side_disagreement_hz=proposal.side_disagreement_hz,
                anchor_residual_hz=proposal.anchor_residual_hz,
                R1_veto=bool(continuous), R2_veto=bool(continuous and near_equal))


def risk_repair(peaks: RidgeCandidateSet, baseline_hz: FloatArray,
                proposals: tuple[Proposal, ...], *, rule: str = "R2",
                config: RiskConfig = RiskConfig(),
                ) -> tuple[FloatArray, tuple[str, ...], list[dict[str, Any]]]:
    """Veto whole proposals; retained baseline is only an unvalidated hypothesis.

    Validated frequency must remain NaN without external identity validation.
    """
    if rule not in ("R1", "R2"):
        raise ValueError("Unknown risk rule")
    kept = []
    rows = []
    flags = ["IDENTITY_UNVALIDATED"] * len(baseline_hz)
    for n, p in enumerate(proposals):
        features = diagnostics(peaks, baseline_hz, p, config)
        rejected = features[f"{rule}_veto"]
        rows.append(dict(proposal_id=n, first=p.first, stop=p.stop, rejected=rejected,
                         **features))
        if rejected:
            for i in range(p.first, p.stop):
                flags[i] = "AMBIGUOUS_INTERVENTION"
        else:
            kept.append(p)
    path, _ = apply_repairs(peaks, baseline_hz, tuple(kept))
    return path, tuple(flags), rows
