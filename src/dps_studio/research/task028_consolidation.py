"""Frozen graduation interface: candidate trajectories are uncalibrated hypotheses.

No artifact reads, truth inputs, waveform filters or production changes. Constants
are the literal TASK-023F activation, not the historical classes' default values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidateSet, extract_global_path_candidates
from dps_studio.core.time_frequency import STFTResult, compute_stft
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f
from dps_studio.research.task021b_real_experiment import node_cost_components
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import EdgeRescueConfig, TrustedCoreConfig

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True)
class FinalMethodConfig:
    """Serializable fixed P3 recipe; parameters were selected before TASK-028."""

    core: TrustedCoreConfig = field(default_factory=lambda: TrustedCoreConfig(trust_threshold=.64))
    edge: EdgeRescueConfig = field(default_factory=EdgeRescueConfig)
    internal: SegmentRescueConfig = field(default_factory=lambda: SegmentRescueConfig(
        minimum_rescue_background_db=18., acceptance_margin=2.))
    ambiguity: d.BranchAmbiguityConfig = field(default_factory=d.BranchAmbiguityConfig)
    trim: d.CoreTrimConfig = field(default_factory=lambda: d.CoreTrimConfig(ambiguity_threshold=.36))
    branch: d.BranchCompetitionConfig = field(default_factory=lambda: d.BranchCompetitionConfig(
        deviation_weight=.006, identity_break_penalty=8., branch_acceptance_margin=1.))
    proposal: f.ProposalConfig = field(default_factory=f.ProposalConfig)
    top_k: int = 20
    wavelength_m: float = 1550e-9
    challenge_core: bool = True
    diversity: bool = True

    def __post_init__(self) -> None:
        if self.top_k != 20 or not self.challenge_core or not self.diversity:
            raise ValueError('Final method requires Top-20, challenge permission and diversity B8')
        if self.branch.beam_width != 8 or not np.isfinite(self.wavelength_m) or self.wavelength_m <= 0:
            raise ValueError('Expected B8 and a finite positive wavelength in metres')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FinalMethodConfig:
        data = dict(value)
        for name, constructor in (
            ('core', TrustedCoreConfig), ('edge', EdgeRescueConfig),
            ('internal', SegmentRescueConfig), ('ambiguity', d.BranchAmbiguityConfig),
            ('trim', d.CoreTrimConfig), ('branch', d.BranchCompetitionConfig),
            ('proposal', f.ProposalConfig),
        ):
            data[name] = constructor(**data[name])
        return cls(**data)


@dataclass(frozen=True)
class Trajectory:
    frequency_hz: FloatArray
    candidate_rank: IntArray
    modified: BoolArray
    quality_flags: tuple[str, ...]
    apparent_velocity_m_per_s: FloatArray
    # Separate measurement channel: no target-identity calibration is available.
    validated_frequency_hz: FloatArray
    validated_apparent_velocity_m_per_s: FloatArray


@dataclass(frozen=True)
class ConsolidatedResult:
    time_s: FloatArray
    trajectories: dict[str, Trajectory]
    window_audit: tuple[dict[str, Any], ...]
    ambiguity: FloatArray


def frontend(record: SignalRecord, profile: AnalysisProfile) -> tuple[STFTResult, RidgeCandidateSet]:
    if not record.is_uniformly_sampled:
        raise ValueError('Nonuniform sampling: implicit resampling is forbidden')
    stft = compute_stft(record, window_length_samples=profile.window_length_samples,
                        overlap_samples=profile.overlap_samples, nfft=profile.nfft,
                        window_name=profile.window_name)
    candidates = extract_global_path_candidates(stft,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz, config=GlobalPathConfig(top_k=20))
    return stft, candidates


def simple_continuity(peaks: RidgeCandidateSet) -> FloatArray:
    """M1: causal greedy node + pseudo-Huber step, using inherited B/C scales.

    Starts at strongest. No core, anchor, hysteresis, beam or lookahead. The
    0.22/1/100 MHz/0.25 constants are EdgeRescueConfig defaults, frozen here.
    """
    cfg = EdgeRescueConfig()
    result = np.full(len(peaks.time_s), np.nan)
    previous = np.nan
    for i, frame in enumerate(peaks.candidates_by_frame):
        if not frame:
            previous = np.nan
            continue
        if not np.isfinite(previous):
            best = frame[0]
        else:
            def cost(index: int) -> tuple[float, int]:
                candidate = frame[index]
                x = (candidate.transition_frequency_hz - previous) / cfg.frequency_scale_hz
                delta = cfg.huber_delta_normalized
                step = 2 * delta**2 * (np.sqrt(1 + (x / delta)**2) - 1)
                node = node_cost_components(candidate, peaks.config)['total_candidate_node_cost']
                return float(cfg.node_weight * node + cfg.transition_weight * step), index
            best = frame[min(range(len(frame)), key=cost)]
        result[i] = previous = best.transition_frequency_hz
    return result


def consolidate(stft: STFTResult, peaks: RidgeCandidateSet,
                config: FinalMethodConfig = FinalMethodConfig()) -> ConsolidatedResult:
    """Run exactly M0/M1/M2 on one shared candidate graph, then diagnose quality."""
    if peaks.config.top_k != config.top_k or not np.array_equal(stft.time_s, peaks.time_s):
        raise ValueError('Expected shared STFT axis and registered Top-K')
    if any(not frame for frame in peaks.candidates_by_frame):
        raise ValueError('P3 requires candidates in every frame; no fabricated fallback is allowed')
    original = d.optimize_smooth_wrong_branches(peaks,
        method=d.SmoothBranchMethod.E4_CONSERVATIVE_BRANCH, core_config=config.core,
        edge_config=config.edge, internal_config=config.internal, ambiguity_config=config.ambiguity,
        trim_config=config.trim, branch_config=config.branch, stft_result=stft)
    effective = f.effective_e4(config.branch)
    broadband = f.broadband_evidence(stft)
    registry = f.windows(original, config.proposal, config.ambiguity)
    searches = tuple(f.generate_proposals(w, original, peaks, config.ambiguity, effective,
                                          broadband, diversity=True) for w in registry)
    selected = f.apply_searches(searches, original, peaks, config.ambiguity, effective, broadband)
    baseline = np.array([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    if not np.array_equal(baseline, selected.strongest_frequency_hz):
        raise AssertionError('Strongest reference drifted')
    paths = {'M0': baseline, 'M1': simple_continuity(peaks), 'M2': selected.final_frequency_hz}
    trajectories = {}
    for name, path in paths.items():
        rank = np.array([next(c.candidate_rank for c in frame if c.transition_frequency_hz == path[i])
                         for i, frame in enumerate(peaks.candidates_by_frame)], dtype=np.int64)
        modified = path != baseline
        flags = tuple('|'.join(['HYPOTHESIS_UNCALIBRATED']
            + (['CANDIDATE_UPDATE'] if modified[i] else [])
            + (['AMBIGUOUS'] if original.ambiguity.branch_ambiguity[i] >= .36 else [])
            + (['BROADBAND_ELEVATED'] if broadband[i] >= 3 else [])
            + (['LOW_SPECTRAL_SUPPORT'] if next(c for c in peaks.candidates_by_frame[i]
                 if c.candidate_rank == rank[i]).peak_to_background_db < 10 else []))
            for i in range(len(path)))
        arrays = [np.array(path, dtype=float), rank, modified,
                  np.asarray(path * config.wavelength_m / 2),
                  np.full(len(path), np.nan), np.full(len(path), np.nan)]
        for array in arrays:
            array.setflags(write=False)
        trajectories[name] = Trajectory(arrays[0], arrays[1], arrays[2], flags,
                                       arrays[3], arrays[4], arrays[5])
    audit = tuple(dict(window_id=s.window.window_id, kind=s.window.kind,
        anchor=s.window.anchor, frames=list(s.window.indices), status=a.status, margin=a.margin,
        accepted=sum(a.accepted), proposals=len(s.proposals), expansions=len(s.lineage))
        for s, a in zip(searches, selected.selections, strict=True))
    return ConsolidatedResult(np.array(peaks.time_s), trajectories, audit,
                              np.asarray(original.ambiguity.branch_ambiguity))
