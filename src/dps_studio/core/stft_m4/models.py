"""Read-only SI results and pointwise evidence for the comparison workspace."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.models import SignalRecord

from .waveform import Bool, Complex, Float, Int

_Scalar = TypeVar("_Scalar", bound=np.generic)


def readonly(array: NDArray[_Scalar]) -> NDArray[_Scalar]:
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


class ComparisonCancelledError(Exception):
    """The requested comparison was cancelled before publication."""


class DiffCategory(StrEnum):
    BOTH_AGREE = "both_agree"
    M4_ADDED_SUPPORTED = "m4_added_supported"
    M4_ADDED_AMBIGUOUS = "m4_added_ambiguous"
    BRANCH_DIFF_MINOR = "branch_diff_minor"
    BRANCH_DIFF_MAJOR = "branch_diff_major"
    M4_DROPPED_WEAK = "m4_dropped_weak"
    M4_DROPPED_STRONG_RISK = "m4_dropped_strong_risk"
    BOTH_REJECTED = "both_rejected"


CATEGORY_ZH: Mapping[DiffCategory, str] = MappingProxyType({
    DiffCategory.BOTH_AGREE: "一致",
    DiffCategory.M4_ADDED_SUPPORTED: "M4 新增 · 波形支持",
    DiffCategory.M4_ADDED_AMBIGUOUS: "M4 新增 · 归属争议",
    DiffCategory.BRANCH_DIFF_MINOR: "分歧 50–250 MHz",
    DiffCategory.BRANCH_DIFF_MAJOR: "分歧 >250 MHz",
    DiffCategory.M4_DROPPED_WEAK: "M4 拒收 · 短窗支持弱或缺失",
    DiffCategory.M4_DROPPED_STRONG_RISK: "疑似误伤 · B1 强短窗被拒",
    DiffCategory.BOTH_REJECTED: "均未发布",
})


class RejectionReason(StrEnum):
    ACCEPTED = "accepted"
    RAW_GATE = "all_hypotheses_failed_raw_gate"
    LOW_FREQ = "lowfreq_sustained_failed"
    PRE_EDGE = "pre_edge_side_veto"
    ISLAND = "island_cleanup_veto"
    PATH_OFF = "path_selected_off"
    NO_PROPOSAL = "no_proposal_above_threshold"


REASON_ZH: Mapping[RejectionReason, str] = MappingProxyType({
    RejectionReason.ACCEPTED: "M4 验证通过并由路径发布",
    RejectionReason.RAW_GATE: "进入验证的候选均未通过原波形门槛",
    RejectionReason.LOW_FREQ: "低频候选未通过持续两侧振荡验证",
    RejectionReason.PRE_EDGE: "中心位于阶跃或触轨退出边界前侧，触发单侧否决",
    RejectionReason.ISLAND: "孤立候选未满足短窗锚定或持续时间要求",
    RejectionReason.PATH_OFF: "存在已验证候选，路径选择 OFF",
    RejectionReason.NO_PROPOSAL: "无候选达到初次验证的提名阈值",
})


@dataclass(frozen=True, slots=True)
class SpectrogramMap:
    time_s: Float
    frequency_hz: Float
    power_db: Float  # (time, frequency)

    def __post_init__(self) -> None:
        if self.power_db.shape != (len(self.time_s), len(self.frequency_hz)):
            raise ValueError("Spectrogram shape must match its time and frequency axes")
        for name in ("time_s", "frequency_hz", "power_db"):
            object.__setattr__(self, name, readonly(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class RawEvidence:
    raw_tone_r2_64ns: Float
    raw_chirp_r2_64ns: Float
    raw_chirp_r2_256ns: Float
    split_half_coherence_256ns: Float
    local_center_snr_32ns: Float

    def __post_init__(self) -> None:
        for field in fields(self):
            object.__setattr__(self, field.name, readonly(getattr(self, field.name)))


@dataclass(frozen=True, slots=True)
class MatchedEvidence:
    phasor: Complex
    r2: Float
    snr_db: Float
    half_snr_db: Float
    rho: Float
    snr_left_db: Float
    snr_right_db: Float


DiagnosticArray = Float | Int | Bool


@dataclass(frozen=True, slots=True)
class Estimate:
    sample_index: Int
    candidate_hz: Float
    accepted_hz: Float
    chirp_hz_s: Float
    raw: RawEvidence
    diagnostics: Mapping[str, DiagnosticArray]
    quality_flags: tuple[str, ...]
    rejection_reasons: tuple[RejectionReason, ...] = ()

    def __post_init__(self) -> None:
        for name in ("sample_index", "candidate_hz", "accepted_hz", "chirp_hz_s"):
            object.__setattr__(self, name, readonly(getattr(self, name)))
        values = {name: readonly(data) for name, data in self.diagnostics.items()}
        object.__setattr__(self, "diagnostics", MappingProxyType(values))

    @property
    def rejected_mask(self) -> Bool:
        return np.isfinite(self.candidate_hz) & ~np.isfinite(self.accepted_hz)

    @property
    def secondary_hz(self) -> Float:
        return np.asarray(self.diagnostics["secondary_hz"], dtype=np.float64)

    @property
    def persistent_cw_overlap(self) -> Bool:
        return np.asarray(self.diagnostics["persistent_cw_overlap"], dtype=np.bool_)

    @property
    def verification_window_ns(self) -> Float:
        return np.asarray(self.diagnostics["verification_window_ns"], dtype=np.float64)

    @property
    def m4_rejection_reason_code(self) -> tuple[str, ...]:
        return tuple(reason.value for reason in self.rejection_reasons)

    @property
    def m4_rejection_reason_zh(self) -> tuple[str, ...]:
        return tuple(REASON_ZH[reason] for reason in self.rejection_reasons)


@dataclass(frozen=True, slots=True)
class InterestingRegion:
    kind: str
    title_zh: str
    frame_indices: tuple[int, ...]
    start_time_s: float
    end_time_s: float
    summary_zh: str


@dataclass(frozen=True, slots=True)
class StftM4ComparisonBundle:
    record: SignalRecord
    channel_name: str
    source_path: Path | None
    sample_rate_hz: float
    q: Int
    frame_time_s: Float
    fmin_hz: float
    fmax_hz: float
    b1_wall_s: float
    m4_wall_s: float
    matched_stft_wall_s: float | None
    total_wall_s: float
    b1_spectrogram: SpectrogramMap
    m4_coherent_map: SpectrogramMap | None
    dc_step_indices: Int
    rail_exit_indices: Int
    rail_mask: Bool
    b1: Estimate
    m4: Estimate
    matched_stft: Estimate | None
    diff_categories: tuple[DiffCategory, ...]
    interesting_regions: tuple[InterestingRegion, ...]

    def __post_init__(self) -> None:
        for name in ("q", "frame_time_s", "dc_step_indices", "rail_exit_indices", "rail_mask"):
            object.__setattr__(self, name, readonly(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class PointEvidence:
    accepted_hz: float
    candidate_hz: float
    chirp_hz_s: float
    raw_tone_r2_64ns: float
    raw_chirp_r2_64ns: float
    raw_chirp_r2_256ns: float
    split_half_coherence_256ns: float
    local_center_snr_32ns: float
    verification_window_ns: float
    verification_snr_db: float
    secondary_hz: float
    persistent_cw_overlap: bool
    quality_flag: str


@dataclass(frozen=True, slots=True)
class LocalComparisonWaveform:
    frame_index: int
    center_time_s: float
    time_s: Float
    voltage_v: Float
    baseline_v: Float
    residual_v: Float
    dc_step_time_s: Float
    rail_time_s: Float
    rail_voltage_v: Float
    rail_exit_time_s: Float
    fit_time_s: Float
    fit_window_s: tuple[float, float]
    b1_fit_v: Float
    m4_fit_v: Float
    b1: PointEvidence
    m4: PointEvidence
    category: DiffCategory
    reason: RejectionReason
    decision_zh: str
