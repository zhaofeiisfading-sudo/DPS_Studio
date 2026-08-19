from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.ridge import (
    EventAwareContinuityConfig,
    RefinedRidgeResult,
    RidgeConfigurationError,
    RidgeContinuityStatus,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    assess_event_aware_ridge_continuity,
)


MHZ = 1.0e6
NS = 1.0e-9
CONFIG = EventAwareContinuityConfig(
    isolated_jump_threshold_hz=100.0 * MHZ,
    neighbor_recovery_tolerance_hz=52.0 * MHZ,
)


def _refined(frequency_mhz: list[float]) -> RefinedRidgeResult:
    requested_hz = np.asarray(frequency_mhz, dtype=np.float64) * MHZ
    frame_count = requested_hz.size
    discrete_hz = requested_hz.copy()
    refined_hz = requested_hz.copy()
    bin_indices = np.arange(1, frame_count + 1, dtype=np.int64)
    offsets = np.zeros(frame_count, dtype=np.float64)
    magnitudes = np.ones(frame_count, dtype=np.float64)
    statuses: list[RidgeRefinementStatus] = []
    for index, value in enumerate(requested_hz):
        if np.isfinite(value):
            statuses.append(RidgeRefinementStatus.REFINED)
            continue
        discrete_hz[index] = 100.0 * MHZ
        refined_hz[index] = np.nan
        offsets[index] = np.nan
        statuses.append(RidgeRefinementStatus.INVALID_LOCAL_PEAK)
    return RefinedRidgeResult(
        time_s=np.arange(frame_count, dtype=np.float64) * NS,
        discrete_frequency_hz=discrete_hz,
        refined_frequency_hz=refined_hz,
        discrete_frequency_bin_index=bin_indices,
        frequency_bin_offset=offsets,
        peak_magnitude=magnitudes,
        quality_flags=(RidgeQualityFlag.CANDIDATE,) * frame_count,
        refinement_statuses=tuple(statuses),
        minimum_frequency_hz=1.0 * MHZ,
        maximum_frequency_hz=500.0 * MHZ,
        event_start_time_s=None,
        analysis_end_time_s=None,
        refinement_method=RefinedRidgeResult.REFINEMENT_METHOD,
        source_path=Path("real-shot.csv"),
    )


def _assess(
    frequency_mhz: list[float],
    *,
    event_frame: int | None = None,
    window_duration_s: float = NS,
) -> object:
    event_time = None if event_frame is None else event_frame * NS
    return assess_event_aware_ridge_continuity(
        _refined(frequency_mhz),
        event_reference_time_s=event_time,
        event_reference_source=("test_event" if event_time is not None else None),
        stft_window_duration_s=window_duration_s,
        config=CONFIG,
    )


def test_normal_continuity_is_not_an_isolated_discontinuity() -> None:
    result = _assess([100.0, 101.0, 102.0, 103.0])

    assert result.statuses == (
        RidgeContinuityStatus.INSUFFICIENT_CONTEXT,
        RidgeContinuityStatus.NORMAL_CONTINUITY,
        RidgeContinuityStatus.NORMAL_CONTINUITY,
        RidgeContinuityStatus.INSUFFICIENT_CONTEXT,
    )
    assert RidgeContinuityStatus.ISOLATED_JUMP not in result.statuses


def test_isolated_false_peak_has_recovery_and_anomaly() -> None:
    result = _assess([100.0, 101.0, 300.0, 102.0, 103.0])

    assert result.statuses[2] is RidgeContinuityStatus.ISOLATED_JUMP
    assert result.delta_frequency_from_previous_hz[2] == 199.0 * MHZ
    assert result.delta_frequency_to_next_hz[2] == -198.0 * MHZ
    assert result.neighbor_recovery_difference_hz[2] == 1.0 * MHZ


def test_sustained_change_is_not_equated_with_isolated_noise() -> None:
    result = _assess([100.0, 120.0, 140.0, 160.0])

    assert result.statuses[1:3] == (
        RidgeContinuityStatus.NORMAL_CONTINUITY,
        RidgeContinuityStatus.NORMAL_CONTINUITY,
    )
    assert RidgeContinuityStatus.ISOLATED_JUMP not in result.statuses


def test_event_jump_is_classified_by_stft_window_support() -> None:
    result = _assess(
        [60.0, 60.0, 60.0, 430.0, 440.0, 445.0],
        event_frame=3,
        window_duration_s=2.0 * NS,
    )

    assert result.statuses[2:5] == (
        RidgeContinuityStatus.EVENT_TRANSITION,
        RidgeContinuityStatus.EVENT_TRANSITION,
        RidgeContinuityStatus.EVENT_TRANSITION,
    )
    assert RidgeContinuityStatus.ISOLATED_JUMP not in result.statuses


def test_nan_gap_is_preserved_and_never_bridged() -> None:
    result = _assess([100.0, 101.0, np.nan, 103.0])

    assert result.statuses == (
        RidgeContinuityStatus.INSUFFICIENT_CONTEXT,
        RidgeContinuityStatus.INSUFFICIENT_CONTEXT,
        RidgeContinuityStatus.GAP,
        RidgeContinuityStatus.INSUFFICIENT_CONTEXT,
    )
    assert np.isnan(result.frequency_hz[2])
    assert np.isnan(result.delta_frequency_to_next_hz[1])
    assert np.isnan(result.delta_frequency_from_previous_hz[3])
    assert np.isnan(result.neighbor_recovery_difference_hz[1:]).all()


def test_boundaries_and_si_units_are_explicit() -> None:
    result = _assess([100.0, 101.0, 102.0])

    assert result.statuses[0] is RidgeContinuityStatus.INSUFFICIENT_CONTEXT
    assert result.statuses[-1] is RidgeContinuityStatus.INSUFFICIENT_CONTEXT
    assert result.time_s[1] == NS
    assert result.delta_frequency_from_previous_hz[1] == MHZ
    assert result.local_frequency_slope_hz_per_s[1] == pytest.approx(MHZ / NS)
    assert result.source_path == Path("real-shot.csv")
    assert result.frequency_hz.flags.writeable is False


def test_explicit_config_and_event_source_are_validated() -> None:
    with pytest.raises(RidgeConfigurationError, match="strictly positive"):
        EventAwareContinuityConfig(
            isolated_jump_threshold_hz=0.0,
            neighbor_recovery_tolerance_hz=1.0,
        )

    with pytest.raises(RidgeConfigurationError, match="event_reference_source"):
        assess_event_aware_ridge_continuity(
            _refined([100.0, 101.0, 102.0]),
            event_reference_time_s=NS,
            event_reference_source=None,
            stft_window_duration_s=NS,
            config=CONFIG,
        )
