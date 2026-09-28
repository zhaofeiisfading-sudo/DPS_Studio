"""TASK-027: one fixed, explicit waveform intervention; no truth or learning."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import firwin  # type: ignore[import-untyped]

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidateSet, extract_global_path_candidates
from dps_studio.core.time_frequency import STFTResult, compute_stft
from dps_studio.research import task023d_smooth_branch_rescue as d
from dps_studio.research import task023f_proposals as f
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import EdgeRescueConfig, TrustedCoreConfig

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class FilterConfig:
    taps: int = 129
    cutoff_hz: float = 7e9
    kaiser_beta: float = 8.0
    padding: str = 'reflect'


def preprocess(record: SignalRecord, config: FilterConfig = FilterConfig()) -> SignalRecord:
    """Centered single-pass Type-I FIR; explicit reflection, no sample removal."""
    if not record.is_uniformly_sampled:
        raise ValueError('Nonuniform time axis; resampling forbidden')
    if config.taps < 3 or config.taps % 2 != 1 or config.padding != 'reflect':
        raise ValueError('Expected odd FIR length and explicit reflection padding')
    if len(record.time_s) <= config.taps or not 0 < config.cutoff_hz < record.sample_rate_hz / 2:
        raise ValueError('Record too short or cutoff outside Nyquist')
    coefficients = firwin(config.taps, config.cutoff_hz, fs=record.sample_rate_hz,
                          window=('kaiser', config.kaiser_beta), scale=True)
    half = (config.taps - 1) // 2
    voltage = np.convolve(np.pad(record.voltage_v, half, mode='reflect'),
                          np.asarray(coefficients, dtype=float), mode='valid')
    return SignalRecord(record.time_s, voltage, source_path=record.source_path,
                        metadata={'task027_processing': asdict(config),
                                  'phase_convention': 'centered_noncausal_single_pass',
                                  'edge_support_s': half / record.sample_rate_hz,
                                  'source_is_processed_copy': True})


def frontend(record: SignalRecord, profile: AnalysisProfile) -> tuple[STFTResult, RidgeCandidateSet]:
    stft = compute_stft(record, window_length_samples=profile.window_length_samples,
                        overlap_samples=profile.overlap_samples, nfft=profile.nfft,
                        window_name=profile.window_name)
    peaks = extract_global_path_candidates(stft,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz, config=GlobalPathConfig(top_k=20))
    return stft, peaks


def strongest(peaks: RidgeCandidateSet) -> FloatArray:
    return np.asarray([frame[0].transition_frequency_hz if frame else np.nan
                       for frame in peaks.candidates_by_frame], dtype=float)


def frozen_p3(stft: STFTResult, peaks: RidgeCandidateSet,
              activation: dict[str, Any]) -> FloatArray:
    """Literal F/P3 with frozen E4, challenge permission and diversity B8."""
    if not activation['core'] or not activation['diversity']:
        raise ValueError('TASK-027 requires the registered P3 activation')
    cfg = activation['config']
    ambiguity = d.BranchAmbiguityConfig(**cfg['ambiguity_config'])
    original = d.optimize_smooth_wrong_branches(peaks,
        method=d.SmoothBranchMethod.E4_CONSERVATIVE_BRANCH,
        core_config=TrustedCoreConfig(**cfg['core_config']),
        edge_config=EdgeRescueConfig(**cfg['edge_config']),
        internal_config=SegmentRescueConfig(**cfg['internal_config']),
        ambiguity_config=ambiguity, trim_config=d.CoreTrimConfig(**cfg['trim_config']),
        branch_config=d.BranchCompetitionConfig(**cfg['branch_config']), stft_result=stft)
    config = d.BranchCompetitionConfig(**activation['effective_e4'])
    broadband = f.broadband_evidence(stft)
    windows = f.windows(original, f.ProposalConfig(**activation['proposal_config']), ambiguity)
    searches = tuple(f.generate_proposals(w, original, peaks, ambiguity, config,
                                          broadband, diversity=True) for w in windows)
    return np.asarray(f.apply_searches(searches, original, peaks, ambiguity,
                                      config, broadband).final_frequency_hz)


def require_gate(gate: dict[str, bool]) -> None:
    if not gate or not all(gate.values()):
        raise RuntimeError('Stage prohibited: prerequisite gate failed or missing')
