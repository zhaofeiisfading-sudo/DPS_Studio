from pathlib import Path

import numpy as np

from dps_studio.core.ridge import (
    CandidateReselectionReason,
    ContinuityReselectionConfig,
    EventAwareContinuityConfig,
    LocalPeakCandidateConfig,
    ReselectionFrameStatus,
    assess_event_aware_ridge_continuity,
    extract_local_peak_candidates,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
    reselect_isolated_jump_candidates,
)
from dps_studio.core.time_frequency import STFTResult


MHZ = 1.0e6
NS = 1.0e-9


def _stft(
    legacy_frequency_mhz: list[float | None],
    *,
    alternative_frame: int | None = None,
    alternative_frequency_mhz: float = 102.0,
    alternative_magnitude: float = 8.0,
) -> STFTResult:
    frame_count = len(legacy_frequency_mhz)
    frequency_hz = np.arange(501, dtype=np.float64) * MHZ
    magnitude = np.full((501, frame_count), 0.1, dtype=np.float64)
    for frame_index, frequency_mhz in enumerate(legacy_frequency_mhz):
        if frequency_mhz is None:
            continue
        bin_index = int(frequency_mhz)
        magnitude[bin_index - 1 : bin_index + 2, frame_index] = [1.0, 10.0, 1.0]
    if alternative_frame is not None:
        bin_index = int(alternative_frequency_mhz)
        magnitude[bin_index - 1 : bin_index + 2, alternative_frame] = [
            1.0,
            alternative_magnitude,
            1.0,
        ]
    return STFTResult(
        time_s=np.arange(frame_count, dtype=np.float64) * NS,
        frequency_hz=frequency_hz,
        spectrum=magnitude.astype(np.complex128),
        window_name="hann",
        window_length_samples=8,
        overlap_samples=4,
        hop_samples=4,
        nfft=1000,
        sample_rate_hz=1.0e9,
        source_path=Path("synthetic.csv"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _run(
    legacy_frequency_mhz: list[float | None],
    *,
    alternative_frame: int | None = None,
    alternative_frequency_mhz: float = 102.0,
    alternative_magnitude: float = 8.0,
    event_frame: int | None = None,
) -> object:
    stft = _stft(
        legacy_frequency_mhz,
        alternative_frame=alternative_frame,
        alternative_frequency_mhz=alternative_frequency_mhz,
        alternative_magnitude=alternative_magnitude,
    )
    ridge = extract_peak_ridge(
        stft,
        minimum_frequency_hz=1.0 * MHZ,
        maximum_frequency_hz=499.0 * MHZ,
    )
    refined = refine_peak_ridge_subbin(stft, ridge)
    event_time_s = None if event_frame is None else event_frame * NS
    continuity = assess_event_aware_ridge_continuity(
        refined,
        event_reference_time_s=event_time_s,
        event_reference_source=("test_event" if event_time_s is not None else None),
        stft_window_duration_s=NS,
        config=EventAwareContinuityConfig(
            isolated_jump_threshold_hz=100.0 * MHZ,
            neighbor_recovery_tolerance_hz=5.0 * MHZ,
        ),
    )
    candidates = extract_local_peak_candidates(
        stft,
        minimum_frequency_hz=1.0 * MHZ,
        maximum_frequency_hz=499.0 * MHZ,
        background_exclusion_half_width_hz=MHZ,
        minimum_background_bin_count=2,
        config=LocalPeakCandidateConfig(3),
    )
    return reselect_isolated_jump_candidates(
        refined,
        candidates,
        continuity,
        config=ContinuityReselectionConfig(
            minimum_peak_to_background_db=6.0,
            minimum_peak_to_competitor_db=-6.0,
            maximum_neighbor_distance_hz=5.0 * MHZ,
        ),
    )


def test_isolated_wrong_strongest_reselects_strong_continuous_alternative() -> None:
    result = _run(
        [100.0, 101.0, 300.0, 102.0, 103.0],
        alternative_frame=2,
    )

    assert result.frame_statuses[2] is ReselectionFrameStatus.RESELECTED
    assert result.experimental_frequency_hz[2] == 102.0 * MHZ
    selected = [item for item in result.evidence_by_frame[2] if item.experimental_selected]
    assert len(selected) == 1
    assert selected[0].candidate_rank == 2
    assert selected[0].reselection_reason is CandidateReselectionReason.RESELECTED


def test_weak_alternative_is_not_selected() -> None:
    result = _run(
        [100.0, 101.0, 300.0, 102.0, 103.0],
        alternative_frame=2,
        alternative_magnitude=2.0,
    )

    assert result.frame_statuses[2] is ReselectionFrameStatus.NO_ELIGIBLE_ALTERNATIVE
    assert result.experimental_frequency_hz[2] == result.legacy_frequency_hz[2]
    assert any(
        evidence.reselection_reason
        is CandidateReselectionReason.PEAK_TO_COMPETITOR_TOO_LOW
        for evidence in result.evidence_by_frame[2]
    )


def test_sustained_branch_change_is_not_reselected() -> None:
    result = _run([100.0, 120.0, 140.0, 160.0], alternative_frame=2)

    assert result.reselected_frame_indices == ()
    np.testing.assert_array_equal(
        result.experimental_frequency_hz,
        result.legacy_frequency_hz,
    )


def test_event_transition_is_protected() -> None:
    result = _run(
        [60.0, 60.0, 430.0, 440.0],
        alternative_frame=2,
        alternative_frequency_mhz=60.0,
        event_frame=2,
    )

    assert result.frame_statuses[2] is ReselectionFrameStatus.EVENT_TRANSITION_PROTECTED
    assert result.experimental_frequency_hz[2] == 430.0 * MHZ


def test_gap_is_not_crossed_or_filled() -> None:
    result = _run([100.0, None, 300.0, 102.0], alternative_frame=2)

    assert result.reselected_frame_indices == ()
    assert np.isnan(result.experimental_frequency_hz[1])


def test_isolated_jump_without_alternative_preserves_legacy() -> None:
    result = _run([100.0, 101.0, 300.0, 102.0, 103.0])

    assert result.frame_statuses[2] is ReselectionFrameStatus.NO_ALTERNATIVE
    assert result.experimental_frequency_hz[2] == 300.0 * MHZ
