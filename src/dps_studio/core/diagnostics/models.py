"""SI records for TASK-022. Arrays are immutable snapshots, never filled measurements.

B0/B1 follow TASK-018's candidate curves (selection=C, native gate=G).
B+S publishes B1 only where S; Dechirp/VarPro are native candidate curves.
TASK-020's gated A/B outputs are obtained with ``np.where(curve.g_accepted,
curve.frequency_hz, np.nan)``. Estimator identifiers remain lowercase in rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

DIAGNOSTIC_FMIN_HZ = 50.0e6
DIAGNOSTIC_FMAX_HZ = 6.0e9
CLUSTER_WIDTH_HZ = 100.0e6
EVIDENCE_CONTRAST_MIN_DB = 10.0
EVIDENCE_BG_GAIN_MIN_DB = 6.0
EVIDENCE_MIN_CYCLES_256 = 1.0
EVIDENCE_MIN_R2 = 0.20
COMPARED_CURVE_METHODS = ("B0", "B1", "B+S", "Dechirp", "VarPro", "S2")
METHODS = ("B1", "B2", "B0", "dechirp", "varpro", "clutter_varpro", "low_glrt", "matrix_pencil")
FAMILY = dict(
    zip(
        METHODS,
        ("STFT", "STFT", "STFT", "Dechirp", "VarPro", "VarPro", "LowGLRT", "Subspace"),
        strict=True,
    )
)
FAMILIES = tuple(dict.fromkeys(FAMILY.values()))
ESTIMATOR_DISPLAY = {"dechirp": "Dechirp", "varpro": "VarPro"}


def _seal(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        value = getattr(instance, name)
        object.__setattr__(
            instance, name, np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)
        )


class DiagnosticComputeMode(StrEnum):
    FAST_CORE = "fast_core"
    FULL_S2 = "full_s2"
    PRECOMPUTED_STACK = "precomputed_stack"


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    source_row: int
    sample_index: int
    time_s: float
    estimator: str
    family: str
    native_rank: int = 1
    source_label: str = ""
    raw_frequency_hz: float = np.nan
    frequency_hz: float = np.nan
    native_gated_hz: float = np.nan
    chirp_hz_s: float = np.nan
    native_quality: str = ""
    applicable: bool = False
    run_status: str = "NOT_RUN"
    c_present: bool = False
    g_accepted: bool = False
    s_supported: bool = False
    spectral_contrast_db: float = np.nan
    background_gain_db: float = np.nan
    relative_strongest_db: float = np.nan
    competitor_advantage_db: float = np.nan
    raw_tone_r2: float = np.nan
    raw_chirp_r2: float = np.nan
    raw_tone_residual_rms_v: float = np.nan
    raw_chirp_residual_rms_v: float = np.nan
    cycles_256: float = np.nan
    cluster_id: int = -1
    s0_score: float = np.nan
    s1_score: float = np.nan
    s2_score: float = np.nan
    family_votes: int = 0
    supported_family_votes: int = 0
    competing_clusters: int = 0
    s0_selected: bool = False
    s1_selected: bool = False
    s2_selected: bool = False
    verdict_code: str = ""
    accept_reasons_zh: tuple[str, ...] = ()
    reject_reasons_zh: tuple[str, ...] = ()
    evaluation_max_hz: float = DIAGNOSTIC_FMAX_HZ

    def with_explanation(
        self, verdict: str, accepted: tuple[str, ...], rejected: tuple[str, ...]
    ) -> CandidateEntry:
        """Copy without per-row dataclass reflection in the frozen CSV hot path."""
        return CandidateEntry(
            self.source_row,
            self.sample_index,
            self.time_s,
            self.estimator,
            self.family,
            self.native_rank,
            self.source_label,
            self.raw_frequency_hz,
            self.frequency_hz,
            self.native_gated_hz,
            self.chirp_hz_s,
            self.native_quality,
            self.applicable,
            self.run_status,
            self.c_present,
            self.g_accepted,
            self.s_supported,
            self.spectral_contrast_db,
            self.background_gain_db,
            self.relative_strongest_db,
            self.competitor_advantage_db,
            self.raw_tone_r2,
            self.raw_chirp_r2,
            self.raw_tone_residual_rms_v,
            self.raw_chirp_residual_rms_v,
            self.cycles_256,
            self.cluster_id,
            self.s0_score,
            self.s1_score,
            self.s2_score,
            self.family_votes,
            self.supported_family_votes,
            self.competing_clusters,
            self.s0_selected,
            self.s1_selected,
            self.s2_selected,
            verdict,
            accepted,
            rejected,
            self.evaluation_max_hz,
        )


@dataclass(frozen=True, slots=True)
class ClusterSummary:
    sample_index: int
    time_s: float
    cluster_id: int
    frequency_lo_hz: float
    frequency_hi_hz: float
    frequency_hz: float
    members: int
    branches_at_center: int
    s_clusters_at_center: int
    conflict: bool
    high_consensus: bool
    high_without_s: bool
    harmonic_like: bool
    edge_like: bool
    low_background_gain: bool
    s0_score: float
    s1_score: float
    s2_score: float
    s2_voters: int
    s2_eligible: int
    s2_g: bool
    s2_s: bool
    s2_selected: bool
    s2_contributors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MethodCurve:
    method: str
    sample_index: IntArray
    time_s: FloatArray
    c_present: BoolArray
    g_accepted: BoolArray
    s_supported: BoolArray
    selected: BoolArray
    frequency_hz: FloatArray
    proposal_hz: FloatArray
    selected_source: tuple[str, ...]
    quality: tuple[str, ...]
    cluster_id: IntArray

    def __post_init__(self) -> None:
        _seal(
            self,
            (
                "sample_index",
                "time_s",
                "c_present",
                "g_accepted",
                "s_supported",
                "selected",
                "frequency_hz",
                "proposal_hz",
                "cluster_id",
            ),
        )


@dataclass(frozen=True, slots=True)
class StageSegment:
    segment_id: str
    start_s: float
    end_s: float
    stage: str
    visual_evidence: str = ""
    confidence: str = "unspecified"
    physical_branch: str = "requires experimental confirmation"
    # Frozen TASK-017 uncertainty is needed for the exact quiet-prefix cutoff.
    start_range_s: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class FrameTags:
    stage: tuple[str, ...]
    disagreement_mask: BoolArray
    g_without_s_mask: BoolArray
    s2_rescued_mask: BoolArray
    competing_clusters_mask: BoolArray
    high_without_s_mask: BoolArray

    def __post_init__(self) -> None:
        _seal(
            self,
            (
                "disagreement_mask",
                "g_without_s_mask",
                "s2_rescued_mask",
                "competing_clusters_mask",
                "high_without_s_mask",
            ),
        )


@dataclass(frozen=True, slots=True)
class SpectrogramLayer:
    """Power is (n_frequency, n_time), dB re 1 V² of Hann-normalized STFT power.

    Time coordinates are common raw sample centers. Incomplete windows are NaN;
    no padding, interpolation, or relative color normalization is applied.
    """

    time_s: FloatArray
    frequency_hz: FloatArray
    power_db: FloatArray
    label: str

    def __post_init__(self) -> None:
        _seal(self, ("time_s", "frequency_hz", "power_db"))


@dataclass(frozen=True, slots=True)
class LocalFrameEvidence:
    sample_index: int
    time_s: float
    window_width: int
    background_stop_index: int
    tau_s: FloatArray
    raw_voltage_v: FloatArray
    baseline_v: FloatArray
    detrended_v: FloatArray
    dc_offset_v: float
    baseline_span_v: float
    spectrum_freq_hz: FloatArray
    local_psd_db: FloatArray
    background_psd_db: FloatArray
    focus_frequency_hz: float
    focus_chirp_hz_s: float
    focus_label: str
    tone_fit_detrended_v: FloatArray
    chirp_fit_detrended_v: FloatArray
    tone_fit_raw_v: FloatArray
    chirp_fit_raw_v: FloatArray
    spectral_contrast_db: float
    background_gain_db: float
    relative_strongest_db: float
    competitor_advantage_db: float
    raw_tone_r2: float
    raw_chirp_r2: float
    raw_tone_residual_rms_v: float
    raw_chirp_residual_rms_v: float
    cycles_256: float
    spectrally_supported: bool
    strongest_peak_hz: float
    strongest_competitor_hz: float

    def __post_init__(self) -> None:
        _seal(
            self,
            (
                "tau_s",
                "raw_voltage_v",
                "baseline_v",
                "detrended_v",
                "spectrum_freq_hz",
                "local_psd_db",
                "background_psd_db",
                "tone_fit_detrended_v",
                "chirp_fit_detrended_v",
                "tone_fit_raw_v",
                "chirp_fit_raw_v",
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticBundle:
    channel_name: str
    source_path: Path | None
    sample_rate_hz: float
    background_stop_index: int
    eval_fmin_hz: float
    eval_fmax_hz: float
    time_s: FloatArray
    voltage_v: FloatArray
    common_sample_indices: IntArray
    common_times_s: FloatArray
    raw_spectrogram: SpectrogramLayer
    demeaned_spectrogram: SpectrogramLayer
    curves: dict[str, MethodCurve]
    candidates_by_frame: tuple[tuple[CandidateEntry, ...], ...]
    clusters_by_frame: tuple[tuple[ClusterSummary, ...], ...]
    stages: tuple[StageSegment, ...]
    frame_tags: FrameTags
    summary_metrics: dict[str, int | float | str]
    compute_mode: str
    provenance_note: str

    def __post_init__(self) -> None:
        _seal(self, ("time_s", "voltage_v", "common_sample_indices", "common_times_s"))

    def frame_index_for_time(self, time_s: float) -> int:
        if not np.isfinite(time_s):
            raise ValueError("Time must be finite")
        return int(np.argmin(abs(self.common_times_s - time_s)))

    def indices_for_filter(self, category: str) -> list[int]:
        if category in ("onset", "decline", "weak_signal"):
            return [i for i, stage in enumerate(self.frame_tags.stage) if stage == category]
        masks = {
            "disagreement": self.frame_tags.disagreement_mask,
            "g_without_s": self.frame_tags.g_without_s_mask,
            "s2_rescued": self.frame_tags.s2_rescued_mask,
            "competing": self.frame_tags.competing_clusters_mask,
            "high_without_s": self.frame_tags.high_without_s_mask,
        }
        if category not in masks:
            raise ValueError(f"Unknown diagnostic filter: {category}")
        return [int(i) for i in np.flatnonzero(masks[category])]


@dataclass(frozen=True, slots=True)
class FrameSummaryText:
    agreement_zh: str
    selection_reasons_zh: tuple[str, ...]
    rejection_reasons_zh: tuple[str, ...]
    warnings_zh: tuple[str, ...]
    physical_identity_caveat_zh: str


@dataclass(frozen=True, slots=True)
class DiagnosticPreset:
    channel_id: str
    relative_path: Path
    voltage_column: int
    highlight_zh: str
    time_scale_to_s: float = 1.0
    voltage_scale_to_v: float = 1.0
    has_header: bool = False
    delimiter: str = ","
    unit_provenance: str = "Inherited headerless mapping; not a new calibration"
