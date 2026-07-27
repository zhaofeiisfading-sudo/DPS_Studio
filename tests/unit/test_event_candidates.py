from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from dps_studio.core.event_candidates import (
    CrossProfileConsensusStatus,
    EventCandidateConfig,
    EventConsensusConfig,
    EventSegmentRejectionReason,
    ProfileConsensusStatus,
    ProfileConsensusResult,
    StreamEventCandidates,
    assess_event_segments,
    build_cross_profile_consensus,
    build_profile_consensus,
    build_stream_event_candidates,
    enumerate_measured_segments,
)
from dps_studio.core.quality import (
    SignalDetectionConfig,
    SignalDetectionResult,
    SignalState,
)
from dps_studio.core.ridge import RidgeRefinementStatus


HOP_S = 3.2e-9
WINDOW_S = 19.2e-9


def _detection(
    measured_runs: tuple[tuple[int, int], ...],
    *,
    frame_count: int = 80,
    frequency_hz: np.ndarray | None = None,
) -> SignalDetectionResult:
    time_s = 554.0e-6 + np.arange(frame_count, dtype=np.float64) * HOP_S
    states = [SignalState.NO_DETECTABLE_BEAT] * frame_count
    for start, stop in measured_runs:
        states[start:stop] = [SignalState.MEASURED] * (stop - start)
    measured = np.asarray([state is SignalState.MEASURED for state in states])
    if frequency_hz is None:
        provisional = np.full(frame_count, 650.0e6, dtype=np.float64)
    else:
        provisional = np.asarray(frequency_hz, dtype=np.float64)
    formal_frequency = np.where(measured, provisional, np.nan)
    velocity = np.where(measured, 1.55e-6 * provisional / 2.0, np.nan)
    first_run = measured_runs[0] if measured_runs else None
    return SignalDetectionResult(
        time_s=time_s,
        coarse_peak_frequency_hz=provisional,
        refined_frequency_hz=formal_frequency,
        apparent_velocity_m_s=velocity,
        signal_states=tuple(states),
        peak_amplitude=np.full(frame_count, 10.0),
        background_level=np.full(frame_count, 1.0),
        strongest_competitor_level=np.full(frame_count, 5.0),
        peak_to_background_db=np.full(frame_count, 20.0),
        peak_to_competitor_db=np.full(frame_count, 6.0),
        peak_bin_index=np.full(frame_count, 20, dtype=np.int64),
        peak_is_at_band_boundary=np.zeros(frame_count, dtype=np.bool_),
        cycles_in_window=provisional * WINDOW_S,
        refinement_statuses=tuple(
            RidgeRefinementStatus.REFINED for _ in range(frame_count)
        ),
        detection_config=SignalDetectionConfig(),
        analysis_start_time_s=None,
        analysis_end_time_s=None,
        manual_event_reference_time_s=None,
        detected_event_candidate_time_s=(
            float(time_s[first_run[0]]) if first_run is not None else None
        ),
        detected_event_candidate_run_frame_count=(
            first_run[1] - first_run[0] if first_run is not None else 0
        ),
        detected_event_candidate_source="spectral_detection",
        window_duration_s=WINDOW_S,
        hop_duration_s=HOP_S,
        minimum_resolvable_frequency_by_cycle_rule_hz=1.0 / WINDOW_S,
        corresponding_apparent_velocity_m_s=1.55e-6 / (2.0 * WINDOW_S),
        detection_method=SignalDetectionResult.DETECTION_METHOD,
    )


def _stream(
    profile: str,
    channel: str,
    runs: tuple[tuple[int, int], ...],
    *,
    frame_count: int = 100,
    frequency_hz: np.ndarray | None = None,
    candidate_config: EventCandidateConfig | None = None,
) -> StreamEventCandidates:
    return build_stream_event_candidates(
        _detection(
            runs,
            frame_count=frame_count,
            frequency_hz=frequency_hz,
        ),
        profile_name=profile,
        channel_name=channel,
        config=candidate_config or EventCandidateConfig(),
    )


def test_enumerates_multiple_runs_without_merging_nan_gap() -> None:
    result = _detection(((3, 8), (9, 20)))
    segments = enumerate_measured_segments(
        result,
        profile_name="balanced",
        channel_name="pdv_channel_1",
    )
    assert [(item.start_frame_index, item.end_frame_index) for item in segments] == [
        (3, 7),
        (9, 19),
    ]
    assert segments[0].span_duration_s == pytest.approx(4 * HOP_S)
    assert segments[0].support_duration_s == pytest.approx(
        4 * HOP_S + WINDOW_S
    )


def test_three_frame_strong_segment_is_enumerated_but_event_ineligible() -> None:
    segment = enumerate_measured_segments(
        _detection(((10, 13),)),
        profile_name="balanced",
        channel_name="pdv_channel_1",
    )[0]
    assessment = assess_event_segments(
        (segment,),
        config=EventCandidateConfig(),
    )[0]
    assert segment.frame_count == 3
    assert assessment.candidate_eligible is False
    assert assessment.rejection_reasons == (
        EventSegmentRejectionReason.SEGMENT_TOO_SHORT,
        EventSegmentRejectionReason.SEGMENT_DURATION_TOO_SHORT,
    )


def test_seeded_transient_strong_noise_segment_is_rejected() -> None:
    generator = np.random.default_rng(13)
    frequency = np.full(80, 650.0e6)
    frequency[10:13] = generator.uniform(0.1e9, 1.9e9, size=3)
    stream = _stream(
        "balanced",
        "pdv_channel_1",
        ((10, 13),),
        frame_count=80,
        frequency_hz=frequency,
    )
    assessment = stream.segment_assessments[0]
    assert assessment.segment.frame_count == 3
    assert assessment.candidate_eligible is False
    assert EventSegmentRejectionReason.SEGMENT_TOO_SHORT in (
        assessment.rejection_reasons
    )


def test_long_stable_and_low_frequency_segments_are_eligible() -> None:
    frequencies = np.full(100, 80.0e6)
    stream = _stream(
        "balanced",
        "pdv_channel_1",
        ((10, 35),),
        frequency_hz=frequencies,
    )
    assert stream.segment_assessments[0].candidate_eligible is True
    assert stream.primary_candidate_time_s == pytest.approx(
        554.0e-6 + 10 * HOP_S
    )


def test_seeded_long_random_frequency_path_is_rejected() -> None:
    generator = np.random.default_rng(20260726)
    frequency = np.full(100, 650.0e6)
    frequency[10:50] = generator.choice(
        np.asarray([100.0e6, 400.0e6, 900.0e6, 1.5e9]),
        size=40,
    )
    stream = _stream(
        "balanced",
        "pdv_channel_1",
        ((10, 50),),
        frequency_hz=frequency,
    )
    assert stream.segment_assessments[0].candidate_eligible is False
    assert (
        EventSegmentRejectionReason.FREQUENCY_PATH_UNSTABLE
        in stream.segment_assessments[0].rejection_reasons
    )


def test_nearby_dual_channel_segments_form_profile_consensus() -> None:
    streams = {
        "pdv_channel_1": _stream(
            "balanced",
            "pdv_channel_1",
            ((10, 50),),
        ),
        "pdv_channel_2": _stream(
            "balanced",
            "pdv_channel_2",
            ((12, 52),),
        ),
    }
    result = build_profile_consensus(
        streams,
        profile_name="balanced",
        config=EventConsensusConfig(),
    )
    assert result.profile_consensus_status is ProfileConsensusStatus.DUAL_CHANNEL_CONSENSUS
    assert result.channel_start_time_difference_s == pytest.approx(2 * HOP_S)
    assert len(result.supporting_channel_segments) == 2


def test_large_channel_time_difference_does_not_form_consensus() -> None:
    streams = {
        "pdv_channel_1": _stream(
            "balanced",
            "pdv_channel_1",
            ((2, 12),),
        ),
        "pdv_channel_2": _stream(
            "balanced",
            "pdv_channel_2",
            ((60, 75),),
        ),
    }
    result = build_profile_consensus(
        streams,
        profile_name="balanced",
        config=EventConsensusConfig(),
    )
    assert result.profile_consensus_status is ProfileConsensusStatus.NO_COMPATIBLE_SEGMENTS
    assert result.profile_consensus_candidate_time_s is None


def test_single_channel_only_never_produces_consensus_time() -> None:
    streams = {
        "pdv_channel_1": _stream(
            "balanced",
            "pdv_channel_1",
            ((10, 30),),
        ),
        "pdv_channel_2": _stream("balanced", "pdv_channel_2", ()),
    }
    result = build_profile_consensus(
        streams,
        profile_name="balanced",
        config=EventConsensusConfig(),
    )
    assert result.profile_consensus_status is ProfileConsensusStatus.SINGLE_CHANNEL_ONLY
    assert result.profile_consensus_candidate_time_s is None


def test_later_common_segments_are_matched_when_earliest_segments_differ() -> None:
    streams = {
        "pdv_channel_1": _stream(
            "balanced",
            "pdv_channel_1",
            ((5, 15), (40, 75)),
        ),
        "pdv_channel_2": _stream(
            "balanced",
            "pdv_channel_2",
            ((20, 30), (42, 77)),
        ),
    }
    result = build_profile_consensus(
        streams,
        profile_name="balanced",
        config=EventConsensusConfig(
            channel_start_time_tolerance_s=10.0e-9,
        ),
    )
    assert result.profile_consensus_status is ProfileConsensusStatus.DUAL_CHANNEL_CONSENSUS
    assert all(
        support.segment_id.endswith("segment_002")
        for support in result.supporting_channel_segments
    )


def _profile_result(
    profile: str,
    *,
    first_frame: int,
) -> ProfileConsensusResult:
    streams = {
        "pdv_channel_1": _stream(
            profile,
            "pdv_channel_1",
            ((first_frame, first_frame + 30),),
        ),
        "pdv_channel_2": _stream(
            profile,
            "pdv_channel_2",
            ((first_frame + 1, first_frame + 31),),
        ),
    }
    return build_profile_consensus(
        streams,
        profile_name=profile,
        config=EventConsensusConfig(),
    )


def test_compatible_profiles_form_cross_profile_consensus() -> None:
    profiles = {
        "balanced": _profile_result("balanced", first_frame=20),
        "high_time_resolution": _profile_result(
            "high_time_resolution",
            first_frame=21,
        ),
    }
    result = build_cross_profile_consensus(
        profiles,
        config=EventConsensusConfig(),
        manual_event_reference_time_s=0.0,
    )
    assert result.consensus_event_status is CrossProfileConsensusStatus.CROSS_PROFILE_CONSENSUS
    assert result.candidate_time_spread_s == pytest.approx(HOP_S)


def test_one_supported_profile_has_explicit_status() -> None:
    supported = _profile_result("balanced", first_frame=20)
    unsupported_streams = {
        "pdv_channel_1": _stream(
            "high_time_resolution",
            "pdv_channel_1",
            ((20, 50),),
        ),
        "pdv_channel_2": _stream("high_time_resolution", "pdv_channel_2", ()),
    }
    unsupported = build_profile_consensus(
        unsupported_streams,
        profile_name="high_time_resolution",
        config=EventConsensusConfig(),
    )
    result = build_cross_profile_consensus(
        {
            "balanced": supported,
            "high_time_resolution": unsupported,
        },
        config=EventConsensusConfig(),
    )
    assert (
        result.consensus_event_status
        is CrossProfileConsensusStatus.SINGLE_PROFILE_DUAL_CHANNEL_SUPPORT
    )


def test_manual_reference_changes_only_diagnostic_difference() -> None:
    profiles = {
        "balanced": _profile_result("balanced", first_frame=20),
        "high_time_resolution": _profile_result(
            "high_time_resolution",
            first_frame=21,
        ),
    }
    first = build_cross_profile_consensus(
        profiles,
        config=EventConsensusConfig(),
        manual_event_reference_time_s=554.0e-6,
    )
    second = build_cross_profile_consensus(
        profiles,
        config=EventConsensusConfig(),
        manual_event_reference_time_s=555.0e-6,
    )
    assert first.consensus_event_candidate_time_s == second.consensus_event_candidate_time_s
    assert first.supporting_channels == second.supporting_channels
    assert first.reference_time_difference_s != second.reference_time_difference_s


def test_candidate_config_cannot_change_formal_detection_arrays() -> None:
    detection = _detection(((5, 8), (20, 50)))
    states_before = detection.signal_states
    frequency_before = detection.refined_frequency_hz.copy()
    velocity_before = detection.apparent_velocity_m_s.copy()
    finite_before = int(np.count_nonzero(np.isfinite(velocity_before)))
    strict = build_stream_event_candidates(
        detection,
        profile_name="balanced",
        channel_name="pdv_channel_1",
        config=EventCandidateConfig(minimum_segment_frames=40),
    )
    permissive = build_stream_event_candidates(
        detection,
        profile_name="balanced",
        channel_name="pdv_channel_1",
        config=EventCandidateConfig(
            minimum_segment_frames=1,
            minimum_segment_duration_s=0.0,
        ),
    )
    assert strict.primary_candidate_time_s is None
    assert permissive.primary_candidate_time_s is not None
    assert detection.signal_states == states_before
    np.testing.assert_array_equal(detection.refined_frequency_hz, frequency_before)
    np.testing.assert_array_equal(detection.apparent_velocity_m_s, velocity_before)
    assert np.count_nonzero(np.isfinite(detection.apparent_velocity_m_s)) == finite_before


@pytest.mark.parametrize(
    "config",
    [
        EventCandidateConfig(),
        replace(EventCandidateConfig(), minimum_segment_frames=3),
        replace(
            EventCandidateConfig(),
            minimum_median_peak_to_background_db=15.0,
        ),
    ],
)
def test_event_candidate_config_is_independent_and_validated(
    config: EventCandidateConfig,
) -> None:
    assert isinstance(config, EventCandidateConfig)
