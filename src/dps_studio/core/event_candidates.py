"""Pure event-segment enumeration and multi-stream consensus.

This module consumes final per-frame :class:`SignalDetectionResult` values.
It never changes spectral detection states, frequencies, or apparent velocity.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real

import numpy as np

from dps_studio.core.quality import SignalDetectionResult, SignalState


class PhysicalBranchReviewStatus(str, Enum):
    """Human physical-identity review state for a spectrally qualified branch."""

    UNREVIEWED = "unreviewed"


class EventSegmentRejectionReason(str, Enum):
    """Event-level assessment result for one already-detected segment."""

    SEGMENT_TOO_SHORT = "segment_too_short"
    SEGMENT_DURATION_TOO_SHORT = "segment_duration_too_short"
    FREQUENCY_PATH_UNSTABLE = "frequency_path_unstable"
    INSUFFICIENT_EVENT_LEVEL_CONTRAST = "insufficient_event_level_contrast"
    ELIGIBLE = "eligible"


class ProfileConsensusStatus(str, Enum):
    """Status of a same-profile, cross-channel event consensus."""

    DUAL_CHANNEL_CONSENSUS = "dual_channel_consensus"
    SINGLE_CHANNEL_ONLY = "single_channel_only"
    NO_ELIGIBLE_SEGMENTS = "no_eligible_segments"
    NO_COMPATIBLE_SEGMENTS = "no_compatible_segments"


class CrossProfileConsensusStatus(str, Enum):
    """Status of the final consensus across analysis profiles."""

    CROSS_PROFILE_CONSENSUS = "cross_profile_consensus"
    SINGLE_PROFILE_DUAL_CHANNEL_SUPPORT = "single_profile_dual_channel_support"
    PROFILE_TIME_MISMATCH = "profile_time_mismatch"
    NO_PROFILE_CONSENSUS = "no_profile_consensus"


@dataclass(frozen=True, slots=True)
class EventCandidateConfig:
    """Independent development defaults for event-level segment eligibility.

    ``minimum_segment_duration_s`` applies to the difference between the first
    and last STFT frame centers. It is not applied to the window-support union.
    These settings do not feed back into formal per-frame signal detection.
    """

    minimum_segment_frames: int = 8
    minimum_segment_duration_s: float = 20.0e-9
    maximum_adjacent_frequency_step_hz: float = 100.0e6
    minimum_median_peak_to_background_db: float | None = None
    minimum_median_peak_to_competitor_db: float | None = None

    DEFAULT_STATUS = (
        "development defaults; event-level synthetic behavior verified; "
        "experimental calibration remains required"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_segment_frames",
            _positive_integer(
                self.minimum_segment_frames,
                field_name="minimum_segment_frames",
            ),
        )
        object.__setattr__(
            self,
            "minimum_segment_duration_s",
            _nonnegative_finite(
                self.minimum_segment_duration_s,
                field_name="minimum_segment_duration_s",
            ),
        )
        object.__setattr__(
            self,
            "maximum_adjacent_frequency_step_hz",
            _positive_finite(
                self.maximum_adjacent_frequency_step_hz,
                field_name="maximum_adjacent_frequency_step_hz",
            ),
        )
        for field_name in (
            "minimum_median_peak_to_background_db",
            "minimum_median_peak_to_competitor_db",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_finite(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class EventConsensusConfig:
    """Development defaults for channel matching and profile matching only."""

    channel_start_time_tolerance_s: float = 25.0e-9
    minimum_interval_overlap_fraction: float = 0.5
    channel_start_frequency_tolerance_hz: float = 150.0e6
    cross_profile_time_tolerance_s: float = 25.0e-9

    DEFAULT_STATUS = (
        "development defaults; consensus metadata only; no voltage or velocity fusion"
    )

    def __post_init__(self) -> None:
        for field_name in (
            "channel_start_time_tolerance_s",
            "channel_start_frequency_tolerance_hz",
            "cross_profile_time_tolerance_s",
        ):
            object.__setattr__(
                self,
                field_name,
                _positive_finite(getattr(self, field_name), field_name=field_name),
            )
        overlap = _finite(
            self.minimum_interval_overlap_fraction,
            field_name="minimum_interval_overlap_fraction",
        )
        if not 0.0 <= overlap <= 1.0:
            raise ValueError(
                "minimum_interval_overlap_fraction must lie in the closed interval "
                "[0, 1]."
            )
        object.__setattr__(self, "minimum_interval_overlap_fraction", overlap)


@dataclass(frozen=True, slots=True)
class SpectralDetectionSegment:
    """One exact continuous run of final ``SignalState.MEASURED`` frames.

    ``span_duration_s`` is the last frame center minus the first frame center.
    ``support_duration_s`` is that center span plus one complete STFT window,
    i.e. the union of the overlapping window supports. Neither definition
    asserts the physical event duration.
    """

    segment_id: str
    profile_name: str
    channel_name: str
    start_frame_index: int
    end_frame_index: int
    start_time_s: float
    end_time_s: float
    frame_count: int
    span_duration_s: float
    support_duration_s: float
    start_frequency_hz: float
    median_frequency_hz: float
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    maximum_adjacent_frequency_step_hz: float
    median_peak_to_background_db: float
    median_peak_to_competitor_db: float
    minimum_peak_to_background_db: float
    minimum_peak_to_competitor_db: float
    physical_branch_review_status: PhysicalBranchReviewStatus

    def __post_init__(self) -> None:
        _nonempty_string(self.segment_id, field_name="segment_id")
        _nonempty_string(self.profile_name, field_name="profile_name")
        _nonempty_string(self.channel_name, field_name="channel_name")
        start_index = _nonnegative_integer(
            self.start_frame_index,
            field_name="start_frame_index",
        )
        end_index = _nonnegative_integer(
            self.end_frame_index,
            field_name="end_frame_index",
        )
        frame_count = _positive_integer(self.frame_count, field_name="frame_count")
        if end_index < start_index or frame_count != end_index - start_index + 1:
            raise ValueError(
                "frame_count must equal end_frame_index - start_frame_index + 1."
            )
        start_time = _finite(self.start_time_s, field_name="start_time_s")
        end_time = _finite(self.end_time_s, field_name="end_time_s")
        if end_time < start_time:
            raise ValueError("end_time_s must not precede start_time_s.")
        span = _nonnegative_finite(
            self.span_duration_s,
            field_name="span_duration_s",
        )
        support = _positive_finite(
            self.support_duration_s,
            field_name="support_duration_s",
        )
        if not math.isclose(span, end_time - start_time, rel_tol=0.0, abs_tol=1e-18):
            raise ValueError(
                "span_duration_s must equal the first-to-last frame-center difference."
            )
        if support < span:
            raise ValueError("support_duration_s must not be smaller than center span.")
        for field_name in (
            "start_frequency_hz",
            "median_frequency_hz",
            "minimum_frequency_hz",
            "maximum_frequency_hz",
            "maximum_adjacent_frequency_step_hz",
            "median_peak_to_background_db",
            "median_peak_to_competitor_db",
            "minimum_peak_to_background_db",
            "minimum_peak_to_competitor_db",
        ):
            _finite(getattr(self, field_name), field_name=field_name)
        if self.minimum_frequency_hz > self.maximum_frequency_hz:
            raise ValueError("minimum_frequency_hz must not exceed maximum_frequency_hz.")
        if self.maximum_adjacent_frequency_step_hz < 0.0:
            raise ValueError(
                "maximum_adjacent_frequency_step_hz must be non-negative."
            )
        if not isinstance(
            self.physical_branch_review_status,
            PhysicalBranchReviewStatus,
        ):
            raise TypeError(
                "physical_branch_review_status must be PhysicalBranchReviewStatus."
            )


@dataclass(frozen=True, slots=True)
class EventSegmentAssessment:
    """Independent event-level eligibility for one spectral detection segment."""

    segment: SpectralDetectionSegment
    candidate_eligible: bool
    rejection_reasons: tuple[EventSegmentRejectionReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.segment, SpectralDetectionSegment):
            raise TypeError("segment must be a SpectralDetectionSegment.")
        if not isinstance(self.candidate_eligible, bool):
            raise TypeError("candidate_eligible must be boolean.")
        reasons = tuple(self.rejection_reasons)
        if not reasons or not all(
            isinstance(reason, EventSegmentRejectionReason) for reason in reasons
        ):
            raise TypeError(
                "rejection_reasons must contain EventSegmentRejectionReason values."
            )
        eligible_only = reasons == (EventSegmentRejectionReason.ELIGIBLE,)
        if self.candidate_eligible != eligible_only:
            raise ValueError(
                "Eligible assessments must contain only the eligible reason; "
                "rejected assessments must not contain it."
            )
        object.__setattr__(self, "rejection_reasons", reasons)


@dataclass(frozen=True, slots=True)
class StreamEventCandidates:
    """All assessed segments and the earliest event-level eligible segment."""

    profile_name: str
    channel_name: str
    segment_assessments: tuple[EventSegmentAssessment, ...]
    primary_candidate_segment_id: str | None
    primary_candidate_time_s: float | None
    config: EventCandidateConfig

    def __post_init__(self) -> None:
        _nonempty_string(self.profile_name, field_name="profile_name")
        _nonempty_string(self.channel_name, field_name="channel_name")
        assessments = tuple(self.segment_assessments)
        if not all(
            isinstance(item, EventSegmentAssessment) for item in assessments
        ):
            raise TypeError(
                "segment_assessments must contain EventSegmentAssessment values."
            )
        if not isinstance(self.config, EventCandidateConfig):
            raise TypeError("config must be an EventCandidateConfig.")
        eligible = [item.segment for item in assessments if item.candidate_eligible]
        expected_id = eligible[0].segment_id if eligible else None
        expected_time = eligible[0].start_time_s if eligible else None
        if (
            self.primary_candidate_segment_id != expected_id
            or self.primary_candidate_time_s != expected_time
        ):
            raise ValueError(
                "Primary candidate must be the earliest event-level eligible segment."
            )
        object.__setattr__(self, "segment_assessments", assessments)

    @property
    def eligible_segments(self) -> tuple[SpectralDetectionSegment, ...]:
        """Return all eligible segments in time order."""
        return tuple(
            item.segment
            for item in self.segment_assessments
            if item.candidate_eligible
        )


@dataclass(frozen=True, slots=True)
class SupportingSegment:
    """Stable reference to one segment supporting a consensus result."""

    profile_name: str
    channel_name: str
    segment_id: str
    start_time_s: float
    end_time_s: float


@dataclass(frozen=True, slots=True)
class ProfileConsensusResult:
    """Same-profile consensus metadata; no signal or velocity fusion."""

    profile_name: str
    profile_consensus_candidate_time_s: float | None
    profile_consensus_status: ProfileConsensusStatus
    supporting_channel_segments: tuple[SupportingSegment, ...]
    channel_start_time_difference_s: float | None
    interval_overlap_fraction: float | None
    frequency_agreement_metric_hz: float | None
    rejection_reason: str | None
    candidate_time_method: str


@dataclass(frozen=True, slots=True)
class CrossProfileConsensusResult:
    """Final cross-profile event metadata; manual reference is diagnostic only."""

    consensus_event_candidate_time_s: float | None
    consensus_event_status: CrossProfileConsensusStatus
    supporting_profiles: tuple[str, ...]
    supporting_channels: tuple[str, ...]
    candidate_time_spread_s: float | None
    reference_time_difference_s: float | None
    rejection_reason: str | None
    candidate_time_method: str


def enumerate_measured_segments(
    detection_result: SignalDetectionResult,
    *,
    profile_name: str,
    channel_name: str,
) -> tuple[SpectralDetectionSegment, ...]:
    """Enumerate every exact final-MEASURED run without interpolation or bridging."""
    if not isinstance(detection_result, SignalDetectionResult):
        raise TypeError("detection_result must be a SignalDetectionResult.")
    _nonempty_string(profile_name, field_name="profile_name")
    _nonempty_string(channel_name, field_name="channel_name")
    states = detection_result.signal_states
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(states):
        if states[index] is not SignalState.MEASURED:
            index += 1
            continue
        start = index
        while index < len(states) and states[index] is SignalState.MEASURED:
            index += 1
        runs.append((start, index))

    segments: list[SpectralDetectionSegment] = []
    for ordinal, (start, stop) in enumerate(runs, start=1):
        frequency = detection_result.refined_frequency_hz[start:stop]
        peak_to_background = detection_result.peak_to_background_db[start:stop]
        peak_to_competitor = detection_result.peak_to_competitor_db[start:stop]
        time_s = detection_result.time_s[start:stop]
        maximum_step = (
            float(np.max(np.abs(np.diff(frequency)))) if frequency.size > 1 else 0.0
        )
        segments.append(
            SpectralDetectionSegment(
                segment_id=(
                    f"{profile_name}:{channel_name}:segment_{ordinal:03d}"
                ),
                profile_name=profile_name,
                channel_name=channel_name,
                start_frame_index=start,
                end_frame_index=stop - 1,
                start_time_s=float(time_s[0]),
                end_time_s=float(time_s[-1]),
                frame_count=stop - start,
                span_duration_s=float(time_s[-1] - time_s[0]),
                support_duration_s=float(
                    time_s[-1]
                    - time_s[0]
                    + detection_result.window_duration_s
                ),
                start_frequency_hz=float(frequency[0]),
                median_frequency_hz=float(np.median(frequency)),
                minimum_frequency_hz=float(np.min(frequency)),
                maximum_frequency_hz=float(np.max(frequency)),
                maximum_adjacent_frequency_step_hz=maximum_step,
                median_peak_to_background_db=float(
                    np.median(peak_to_background)
                ),
                median_peak_to_competitor_db=float(
                    np.median(peak_to_competitor)
                ),
                minimum_peak_to_background_db=float(
                    np.min(peak_to_background)
                ),
                minimum_peak_to_competitor_db=float(
                    np.min(peak_to_competitor)
                ),
                physical_branch_review_status=(
                    PhysicalBranchReviewStatus.UNREVIEWED
                ),
            )
        )
    return tuple(segments)


def assess_event_segments(
    segments: Sequence[SpectralDetectionSegment],
    *,
    config: EventCandidateConfig,
) -> tuple[EventSegmentAssessment, ...]:
    """Assess event eligibility without changing any per-frame detection result."""
    if not isinstance(config, EventCandidateConfig):
        raise TypeError("config must be an EventCandidateConfig.")
    assessments: list[EventSegmentAssessment] = []
    for segment in segments:
        if not isinstance(segment, SpectralDetectionSegment):
            raise TypeError("segments must contain SpectralDetectionSegment values.")
        reasons: list[EventSegmentRejectionReason] = []
        if segment.frame_count < config.minimum_segment_frames:
            reasons.append(EventSegmentRejectionReason.SEGMENT_TOO_SHORT)
        if segment.span_duration_s < config.minimum_segment_duration_s:
            reasons.append(
                EventSegmentRejectionReason.SEGMENT_DURATION_TOO_SHORT
            )
        if (
            segment.maximum_adjacent_frequency_step_hz
            > config.maximum_adjacent_frequency_step_hz
        ):
            reasons.append(EventSegmentRejectionReason.FREQUENCY_PATH_UNSTABLE)
        if (
            config.minimum_median_peak_to_background_db is not None
            and segment.median_peak_to_background_db
            < config.minimum_median_peak_to_background_db
        ) or (
            config.minimum_median_peak_to_competitor_db is not None
            and segment.median_peak_to_competitor_db
            < config.minimum_median_peak_to_competitor_db
        ):
            reasons.append(
                EventSegmentRejectionReason.INSUFFICIENT_EVENT_LEVEL_CONTRAST
            )
        eligible = not reasons
        assessments.append(
            EventSegmentAssessment(
                segment=segment,
                candidate_eligible=eligible,
                rejection_reasons=(
                    (EventSegmentRejectionReason.ELIGIBLE,)
                    if eligible
                    else tuple(reasons)
                ),
            )
        )
    return tuple(assessments)


def build_stream_event_candidates(
    detection_result: SignalDetectionResult,
    *,
    profile_name: str,
    channel_name: str,
    config: EventCandidateConfig,
) -> StreamEventCandidates:
    """Enumerate, assess, and retain all eligible segments for one stream."""
    segments = enumerate_measured_segments(
        detection_result,
        profile_name=profile_name,
        channel_name=channel_name,
    )
    assessments = assess_event_segments(segments, config=config)
    eligible = [item.segment for item in assessments if item.candidate_eligible]
    return StreamEventCandidates(
        profile_name=profile_name,
        channel_name=channel_name,
        segment_assessments=assessments,
        primary_candidate_segment_id=eligible[0].segment_id if eligible else None,
        primary_candidate_time_s=eligible[0].start_time_s if eligible else None,
        config=config,
    )


def build_profile_consensus(
    streams: Mapping[str, StreamEventCandidates],
    *,
    profile_name: str,
    config: EventConsensusConfig,
) -> ProfileConsensusResult:
    """Match all eligible segments across the two channels of one profile."""
    if not isinstance(streams, Mapping):
        raise TypeError("streams must be a mapping.")
    if not isinstance(config, EventConsensusConfig):
        raise TypeError("config must be an EventConsensusConfig.")
    _nonempty_string(profile_name, field_name="profile_name")
    if len(streams) != 2:
        raise ValueError("Profile consensus requires exactly two channel streams.")
    channel_names = tuple(sorted(streams))
    left_stream = streams[channel_names[0]]
    right_stream = streams[channel_names[1]]
    for channel_name, stream in streams.items():
        if not isinstance(stream, StreamEventCandidates):
            raise TypeError("streams values must be StreamEventCandidates.")
        if stream.profile_name != profile_name or stream.channel_name != channel_name:
            raise ValueError("Stream names must match the profile/channel mapping keys.")

    left = left_stream.eligible_segments
    right = right_stream.eligible_segments
    if not left and not right:
        return _empty_profile_consensus(
            profile_name,
            status=ProfileConsensusStatus.NO_ELIGIBLE_SEGMENTS,
            rejection_reason="no_event_level_eligible_segments",
        )
    if not left or not right:
        supporting = left if left else right
        return ProfileConsensusResult(
            profile_name=profile_name,
            profile_consensus_candidate_time_s=None,
            profile_consensus_status=ProfileConsensusStatus.SINGLE_CHANNEL_ONLY,
            supporting_channel_segments=(
                (_supporting_segment(supporting[0]),) if supporting else ()
            ),
            channel_start_time_difference_s=None,
            interval_overlap_fraction=None,
            frequency_agreement_metric_hz=None,
            rejection_reason="single_channel_only",
            candidate_time_method="none_without_dual_channel_support",
        )

    evaluated: list[
        tuple[
            SpectralDetectionSegment,
            SpectralDetectionSegment,
            float,
            float,
            float,
            bool,
        ]
    ] = []
    for left_segment in left:
        for right_segment in right:
            start_difference = abs(
                left_segment.start_time_s - right_segment.start_time_s
            )
            overlap_fraction = _interval_overlap_fraction(
                left_segment,
                right_segment,
            )
            frequency_difference = abs(
                left_segment.start_frequency_hz
                - right_segment.start_frequency_hz
            )
            time_compatible = (
                start_difference <= config.channel_start_time_tolerance_s
                or overlap_fraction >= config.minimum_interval_overlap_fraction
            )
            frequency_compatible = (
                frequency_difference
                <= config.channel_start_frequency_tolerance_hz
            )
            evaluated.append(
                (
                    left_segment,
                    right_segment,
                    start_difference,
                    overlap_fraction,
                    frequency_difference,
                    time_compatible and frequency_compatible,
                )
            )

    compatible = [item for item in evaluated if item[-1]]
    if compatible:
        selected = min(
            compatible,
            key=lambda item: (
                max(item[0].start_time_s, item[1].start_time_s),
                item[2],
                item[4],
            ),
        )
        left_segment, right_segment, start_difference, overlap, frequency, _ = (
            selected
        )
        candidate_time = (
            left_segment.start_time_s + right_segment.start_time_s
        ) / 2.0
        return ProfileConsensusResult(
            profile_name=profile_name,
            profile_consensus_candidate_time_s=candidate_time,
            profile_consensus_status=(
                ProfileConsensusStatus.DUAL_CHANNEL_CONSENSUS
            ),
            supporting_channel_segments=(
                _supporting_segment(left_segment),
                _supporting_segment(right_segment),
            ),
            channel_start_time_difference_s=start_difference,
            interval_overlap_fraction=overlap,
            frequency_agreement_metric_hz=frequency,
            rejection_reason=None,
            candidate_time_method="mean_of_supporting_segment_start_frame_centers",
        )

    closest = min(
        evaluated,
        key=lambda item: (item[2], item[4]),
    )
    time_ok = (
        closest[2] <= config.channel_start_time_tolerance_s
        or closest[3] >= config.minimum_interval_overlap_fraction
    )
    frequency_ok = (
        closest[4] <= config.channel_start_frequency_tolerance_hz
    )
    if not time_ok and not frequency_ok:
        rejection_reason = "time_and_start_frequency_incompatible"
    elif not time_ok:
        rejection_reason = "time_incompatible"
    else:
        rejection_reason = "start_frequency_incompatible"
    return ProfileConsensusResult(
        profile_name=profile_name,
        profile_consensus_candidate_time_s=None,
        profile_consensus_status=ProfileConsensusStatus.NO_COMPATIBLE_SEGMENTS,
        supporting_channel_segments=(),
        channel_start_time_difference_s=closest[2],
        interval_overlap_fraction=closest[3],
        frequency_agreement_metric_hz=closest[4],
        rejection_reason=rejection_reason,
        candidate_time_method="none_without_compatible_dual_channel_pair",
    )


def build_cross_profile_consensus(
    profile_results: Mapping[str, ProfileConsensusResult],
    *,
    config: EventConsensusConfig,
    manual_event_reference_time_s: float | None = None,
) -> CrossProfileConsensusResult:
    """Combine profile consensus metadata without using the manual reference."""
    if not isinstance(profile_results, Mapping):
        raise TypeError("profile_results must be a mapping.")
    if not isinstance(config, EventConsensusConfig):
        raise TypeError("config must be an EventConsensusConfig.")
    manual_reference = _optional_finite(
        manual_event_reference_time_s,
        field_name="manual_event_reference_time_s",
    )
    supported = [
        result
        for result in profile_results.values()
        if result.profile_consensus_status
        is ProfileConsensusStatus.DUAL_CHANNEL_CONSENSUS
    ]
    if len(supported) >= 2:
        ordered = sorted(supported, key=lambda result: result.profile_name)
        times = [
            result.profile_consensus_candidate_time_s for result in ordered
        ]
        if any(value is None for value in times):
            raise ValueError("Dual-channel profile consensus must have a time.")
        finite_times = [float(value) for value in times if value is not None]
        spread = max(finite_times) - min(finite_times)
        if spread <= config.cross_profile_time_tolerance_s:
            candidate_time = float(np.mean(finite_times))
            channels = tuple(
                f"{support.profile_name}/{support.channel_name}/{support.segment_id}"
                for result in ordered
                for support in result.supporting_channel_segments
            )
            return CrossProfileConsensusResult(
                consensus_event_candidate_time_s=candidate_time,
                consensus_event_status=(
                    CrossProfileConsensusStatus.CROSS_PROFILE_CONSENSUS
                ),
                supporting_profiles=tuple(
                    result.profile_name for result in ordered
                ),
                supporting_channels=channels,
                candidate_time_spread_s=spread,
                reference_time_difference_s=(
                    candidate_time - manual_reference
                    if manual_reference is not None
                    else None
                ),
                rejection_reason=None,
                candidate_time_method=(
                    "mean_of_profile_dual_channel_consensus_times"
                ),
            )
        return CrossProfileConsensusResult(
            consensus_event_candidate_time_s=None,
            consensus_event_status=(
                CrossProfileConsensusStatus.PROFILE_TIME_MISMATCH
            ),
            supporting_profiles=tuple(result.profile_name for result in ordered),
            supporting_channels=(),
            candidate_time_spread_s=spread,
            reference_time_difference_s=None,
            rejection_reason="profile_consensus_times_exceed_tolerance",
            candidate_time_method="none_when_profile_times_are_incompatible",
        )
    if len(supported) == 1:
        result = supported[0]
        single_candidate_time = result.profile_consensus_candidate_time_s
        if single_candidate_time is None:
            raise ValueError("Dual-channel profile consensus must have a time.")
        return CrossProfileConsensusResult(
            consensus_event_candidate_time_s=single_candidate_time,
            consensus_event_status=(
                CrossProfileConsensusStatus.SINGLE_PROFILE_DUAL_CHANNEL_SUPPORT
            ),
            supporting_profiles=(result.profile_name,),
            supporting_channels=tuple(
                f"{support.profile_name}/{support.channel_name}/{support.segment_id}"
                for support in result.supporting_channel_segments
            ),
            candidate_time_spread_s=0.0,
            reference_time_difference_s=(
                single_candidate_time - manual_reference
                if manual_reference is not None
                else None
            ),
            rejection_reason="only_one_profile_has_dual_channel_support",
            candidate_time_method="single_supported_profile_consensus_time",
        )
    return CrossProfileConsensusResult(
        consensus_event_candidate_time_s=None,
        consensus_event_status=CrossProfileConsensusStatus.NO_PROFILE_CONSENSUS,
        supporting_profiles=(),
        supporting_channels=(),
        candidate_time_spread_s=None,
        reference_time_difference_s=None,
        rejection_reason="no_profile_has_dual_channel_support",
        candidate_time_method="none_without_profile_consensus",
    )


def _empty_profile_consensus(
    profile_name: str,
    *,
    status: ProfileConsensusStatus,
    rejection_reason: str,
) -> ProfileConsensusResult:
    return ProfileConsensusResult(
        profile_name=profile_name,
        profile_consensus_candidate_time_s=None,
        profile_consensus_status=status,
        supporting_channel_segments=(),
        channel_start_time_difference_s=None,
        interval_overlap_fraction=None,
        frequency_agreement_metric_hz=None,
        rejection_reason=rejection_reason,
        candidate_time_method="none_without_dual_channel_support",
    )


def _supporting_segment(segment: SpectralDetectionSegment) -> SupportingSegment:
    return SupportingSegment(
        profile_name=segment.profile_name,
        channel_name=segment.channel_name,
        segment_id=segment.segment_id,
        start_time_s=segment.start_time_s,
        end_time_s=segment.end_time_s,
    )


def _interval_overlap_fraction(
    left: SpectralDetectionSegment,
    right: SpectralDetectionSegment,
) -> float:
    overlap = max(
        0.0,
        min(left.end_time_s, right.end_time_s)
        - max(left.start_time_s, right.start_time_s),
    )
    shorter_span = min(left.span_duration_s, right.span_duration_s)
    if shorter_span == 0.0:
        return 1.0 if left.start_time_s == right.start_time_s else 0.0
    return overlap / shorter_span


def _nonempty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite numeric value.")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} must be finite.")
    return converted


def _positive_finite(value: object, *, field_name: str) -> float:
    converted = _finite(value, field_name=field_name)
    if converted <= 0.0:
        raise ValueError(f"{field_name} must be strictly positive.")
    return converted


def _nonnegative_finite(value: object, *, field_name: str) -> float:
    converted = _finite(value, field_name=field_name)
    if converted < 0.0:
        raise ValueError(f"{field_name} must be non-negative.")
    return converted


def _optional_finite(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite(value, field_name=field_name)


def _nonnegative_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{field_name} must be an integer.")
    converted = int(value)
    if converted < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return converted


def _positive_integer(value: object, *, field_name: str) -> int:
    converted = _nonnegative_integer(value, field_name=field_name)
    if converted < 1:
        raise ValueError(f"{field_name} must be at least 1.")
    return converted


__all__ = [
    "CrossProfileConsensusResult",
    "CrossProfileConsensusStatus",
    "EventCandidateConfig",
    "EventConsensusConfig",
    "EventSegmentAssessment",
    "EventSegmentRejectionReason",
    "PhysicalBranchReviewStatus",
    "ProfileConsensusResult",
    "ProfileConsensusStatus",
    "SpectralDetectionSegment",
    "StreamEventCandidates",
    "SupportingSegment",
    "assess_event_segments",
    "build_cross_profile_consensus",
    "build_profile_consensus",
    "build_stream_event_candidates",
    "enumerate_measured_segments",
]
