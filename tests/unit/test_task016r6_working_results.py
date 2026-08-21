from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from dps_studio.core import EventCandidateConfig, WorkingRidgeSource
from dps_studio.core.quality import SignalDetectionConfig, SignalState
from dps_studio.core.ridge import (
    ManualFrequencyBoundary,
    ManualFrequencyRegion,
    RidgeRefinementStatus,
    RidgeSelectionOrigin,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import analyze_stft_results, build_display_velocity


def _stft(
    selected_bins: tuple[int, ...] = (2, 2, 2, 2, 2, 2),
    *,
    competitor_ratio: float = 0.01,
) -> STFTResult:
    frequency_hz = np.arange(6, dtype=np.float64) * 10.0
    spectrum = np.full(
        (frequency_hz.size, len(selected_bins)),
        competitor_ratio,
        dtype=np.complex128,
    )
    spectrum[0, :] = competitor_ratio * 0.5
    for frame, selected_bin in enumerate(selected_bins):
        spectrum[selected_bin, frame] = 10.0
        if 0 < selected_bin < frequency_hz.size - 1:
            spectrum[selected_bin - 1, frame] = 2.0
            spectrum[selected_bin + 1, frame] = 3.0
    return STFTResult(
        time_s=np.arange(len(selected_bins), dtype=np.float64),
        frequency_hz=frequency_hz,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=16,
        overlap_samples=8,
        hop_samples=8,
        nfft=16,
        sample_rate_hz=100.0,
        source_path=None,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _analyze(
    stft: STFTResult,
    *,
    detection_config: SignalDetectionConfig | None = None,
    analysis_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    manual_event_reference_time_s: float | None = None,
    ridge_constraint: ManualFrequencyRegion | None = None,
    event_candidate_config: EventCandidateConfig | None = None,
):
    return analyze_stft_results(
        {"pdv_channel_1": stft},
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=40.0,
        analysis_start_time_s=analysis_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        manual_event_reference_time_s=manual_event_reference_time_s,
        vacuum_wavelength_m=2.0,
        detection_config=detection_config
        or SignalDetectionConfig(
            minimum_peak_to_background_db=0.0,
            minimum_peak_to_competitor_db=0.0,
            peak_exclusion_half_width_bins=0,
            minimum_consecutive_frames=1,
            minimum_cycles_in_window=0.1,
        ),
        event_candidate_config=event_candidate_config,
        background_guard_window_scale=0.1,
        minimum_background_bin_count=1,
        assume_pre_event_zero_for_display=True,
        pre_event_display_velocity_m_s=7.5,
        ridge_constraints=(
            {"pdv_channel_1": ridge_constraint}
            if ridge_constraint is not None
            else None
        ),
    )["pdv_channel_1"]


def test_normal_frames_make_identical_working_and_formal_ridges() -> None:
    analysis = _analyze(_stft())
    assert set(analysis.signal_detection_result.signal_states) == {
        SignalState.MEASURED
    }
    np.testing.assert_array_equal(
        analysis.working_frequency_hz,
        analysis.signal_detection_result.refined_frequency_hz,
    )
    assert set(analysis.working_source) == {WorkingRidgeSource.REFINED}


def test_refinement_failure_falls_back_to_same_frame_discrete_peak() -> None:
    analysis = _analyze(_stft((1, 1, 1, 1, 1, 1)))
    assert set(analysis.refined_result.refinement_statuses) == {
        RidgeRefinementStatus.BOUNDARY_PEAK
    }
    assert np.isnan(
        analysis.signal_detection_result.refined_frequency_hz
    ).all()
    np.testing.assert_array_equal(
        analysis.working_frequency_hz,
        analysis.ridge_result.frequency_hz,
    )
    assert set(analysis.working_source) == {
        WorkingRidgeSource.DISCRETE_FALLBACK
    }


def test_unaccepted_continuity_jump_retains_strongest_same_frame_candidate() -> None:
    analysis = _analyze(_stft((2, 2, 3, 2, 2, 2)))
    jump_index = 2
    assert (
        analysis.automatic_ridge_selection_result.origins[jump_index]
        is RidgeSelectionOrigin.STRONGEST_PEAK
    )
    assert (
        analysis.automatic_ridge_selection_result.selected_candidate_rank[
            jump_index
        ]
        == 1
    )
    assert analysis.ridge_result.frequency_hz[jump_index] == 30.0
    assert np.isfinite(analysis.working_frequency_hz[jump_index])


@pytest.mark.parametrize(
    ("config", "expected_state"),
    [
        (
            SignalDetectionConfig(
                minimum_peak_to_background_db=0.0,
                minimum_peak_to_competitor_db=0.0,
                peak_exclusion_half_width_bins=0,
                minimum_consecutive_frames=1,
                minimum_cycles_in_window=100.0,
            ),
            SignalState.INSUFFICIENT_CYCLES,
        ),
        (
            SignalDetectionConfig(
                minimum_peak_to_background_db=100.0,
                minimum_peak_to_competitor_db=0.0,
                peak_exclusion_half_width_bins=0,
                minimum_consecutive_frames=1,
                minimum_cycles_in_window=0.1,
            ),
            SignalState.NO_DETECTABLE_BEAT,
        ),
        (
            SignalDetectionConfig(
                minimum_peak_to_background_db=0.0,
                minimum_peak_to_competitor_db=100.0,
                peak_exclusion_half_width_bins=0,
                minimum_consecutive_frames=1,
                minimum_cycles_in_window=0.1,
            ),
            SignalState.AMBIGUOUS_PEAK,
        ),
    ],
)
def test_low_quality_states_keep_working_and_formal_nan(
    config: SignalDetectionConfig,
    expected_state: SignalState,
) -> None:
    analysis = _analyze(_stft(), detection_config=config)
    assert set(analysis.signal_detection_result.signal_states) == {expected_state}
    assert np.isfinite(analysis.working_frequency_hz).all()
    assert np.isnan(
        analysis.signal_detection_result.refined_frequency_hz
    ).all()
    assert set(analysis.working_source) == {
        WorkingRidgeSource.LOW_CONFIDENCE_FALLBACK
    }


def test_search_boundary_peak_is_a_finite_discrete_working_point() -> None:
    analysis = _analyze(_stft((4, 4, 4, 4, 4, 4)))
    assert set(analysis.signal_detection_result.signal_states) == {
        SignalState.PEAK_AT_BAND_BOUNDARY
    }
    np.testing.assert_array_equal(analysis.working_frequency_hz, 40.0)
    assert np.isnan(
        analysis.signal_detection_result.refined_frequency_hz
    ).all()


def test_outside_analysis_frames_are_the_only_time_window_hard_nan() -> None:
    analysis = _analyze(
        _stft(),
        analysis_start_time_s=1.0,
        analysis_end_time_s=4.0,
    )
    np.testing.assert_array_equal(
        np.isfinite(analysis.working_frequency_hz),
        [False, True, True, True, True, False],
    )
    assert analysis.working_source[0] is WorkingRidgeSource.OUTSIDE_ANALYSIS_WINDOW
    assert analysis.working_source[-1] is WorkingRidgeSource.OUTSIDE_ANALYSIS_WINDOW


def test_manual_region_empty_frame_is_hard_nan_but_other_frames_remain_finite() -> None:
    region = ManualFrequencyRegion(
        lower_boundary=ManualFrequencyBoundary(
            control_times_s=np.asarray([0.0, 2.0, 3.0, 4.0, 5.0]),
            control_frequencies_hz=np.asarray(
                [15.0, 15.0, 25.1, 15.0, 15.0]
            ),
        ),
        upper_boundary=ManualFrequencyBoundary(
            control_times_s=np.asarray([0.0, 2.0, 3.0, 4.0, 5.0]),
            control_frequencies_hz=np.asarray(
                [25.0, 25.0, 25.2, 25.0, 25.0]
            ),
        ),
    )
    analysis = _analyze(_stft(), ridge_constraint=region)
    assert np.isnan(analysis.working_frequency_hz[3])
    assert (
        analysis.working_source[3]
        is WorkingRidgeSource.NO_ALLOWED_FINITE_BIN
    )
    assert np.isfinite(analysis.working_frequency_hz[[0, 1, 2, 4, 5]]).all()


def test_pre_event_working_frequency_does_not_pollute_display_platform() -> None:
    analysis = _analyze(
        _stft(),
        manual_event_reference_time_s=3.0,
    )
    assert np.isfinite(analysis.working_frequency_hz[:3]).all()
    assert np.all(analysis.working_velocity_m_s[:3] > 7.5)
    np.testing.assert_array_equal(analysis.display_velocity_m_s[:3], 7.5)
    np.testing.assert_array_equal(
        analysis.display_velocity_m_s[3:],
        analysis.working_corrected_velocity_m_s[3:],
    )


def test_display_platform_overrides_even_formal_measured_pre_event_frames() -> None:
    time_s = np.asarray([0.0, 1.0, 2.0])
    display, origins = build_display_velocity(
        time_s,
        (SignalState.MEASURED,) * 3,
        np.asarray([100.0, 101.0, 102.0]),
        manual_event_reference_time_s=2.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=7.5,
    )
    np.testing.assert_array_equal(display, [7.5, 7.5, 102.0])
    assert origins[:2] == (
        "configured_pre_event_display_velocity_only",
    ) * 2


def test_formal_arrays_are_unchanged_when_only_working_display_is_reconfigured() -> None:
    analysis = _analyze(_stft(), manual_event_reference_time_s=3.0)
    formal_frequency = analysis.signal_detection_result.refined_frequency_hz.copy()
    formal_velocity = analysis.corrected_velocity_m_s.copy()
    changed = replace(analysis, display_velocity_m_s=analysis.display_velocity_m_s)
    np.testing.assert_array_equal(
        changed.signal_detection_result.refined_frequency_hz,
        formal_frequency,
    )
    np.testing.assert_array_equal(changed.corrected_velocity_m_s, formal_velocity)


def test_strict_event_rejection_preserves_existing_detector_fallback_candidate() -> None:
    analysis = _analyze(
        _stft(),
        event_candidate_config=EventCandidateConfig(minimum_segment_frames=100),
    )
    assert analysis.stream_event_candidates.primary_candidate_time_s is None
    assert (
        analysis.signal_detection_result.detected_event_candidate_time_s
        is not None
    )
    assert np.isfinite(analysis.working_frequency_hz).all()
