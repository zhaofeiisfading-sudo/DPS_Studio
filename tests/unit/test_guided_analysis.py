from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dps_studio.core import BALANCED_PROFILE
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.core.ridge import (
    RidgeConfigurationError,
    RidgeCorridorConstraint,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeSpectralQualityStatus,
    RelatedFrequencyEvidenceStatus,
    assess_related_frequency_evidence,
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
    validate_ridge_corridor_for_stft,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import ChannelAnalysis, analyze_profile


def _stft() -> STFTResult:
    return STFTResult(
        time_s=np.array([0.0, 1.0, 2.0, 3.0]),
        frequency_hz=np.array([0.0, 10.0, 20.0, 30.0, 40.0]),
        spectrum=np.array(
            [
                [100.0, 100.0, 100.0, 100.0],
                [1.0, 2.0, 9.0, 4.0],
                [5.0, 8.0, 3.0, 1.0],
                [2.0, 4.0, 7.0, 6.0],
                [200.0, 200.0, 200.0, 200.0],
            ],
            dtype=np.complex128,
        ),
        window_name="hann",
        window_length_samples=8,
        overlap_samples=4,
        hop_samples=4,
        nfft=8,
        sample_rate_hz=80.0,
        source_path=None,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _constraint(
    times: object = (1.0, 2.0),
    frequencies: object = (20.0, 20.0),
    width: object = 1.0,
) -> RidgeCorridorConstraint:
    return RidgeCorridorConstraint(
        control_times_s=times,  # type: ignore[arg-type]
        control_frequencies_hz=frequencies,  # type: ignore[arg-type]
        half_width_hz=width,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("times", "frequencies", "width"),
    [
        ((1.0,), (20.0,), 1.0),
        ((1.0, 1.0), (20.0, 20.0), 1.0),
        ((2.0, 1.0), (20.0, 20.0), 1.0),
        ((1.0, 2.0), (20.0, np.nan), 1.0),
        ((1.0, 2.0), (-1.0, 20.0), 1.0),
        ((1.0, 2.0), (20.0, 20.0), 0.0),
        ((1.0, 2.0), (20.0, 20.0), np.inf),
    ],
)
def test_corridor_model_rejects_invalid_physical_coordinates(
    times: object,
    frequencies: object,
    width: object,
) -> None:
    with pytest.raises(RidgeConfigurationError):
        _constraint(times, frequencies, width)


def test_corridor_model_is_immutable_and_interpolates_linearly() -> None:
    constraint = _constraint((1.0, 3.0), (10.0, 30.0), 2.0)
    assert constraint.center_frequency_hz(2.0) == pytest.approx(20.0)
    assert constraint.allowed_band_hz(2.0) == pytest.approx((18.0, 22.0))
    assert constraint.allowed_band_hz(0.0) is None
    assert constraint.allowed_band_hz(4.0) is None
    assert not constraint.control_times_s.flags.writeable
    with pytest.raises(ValueError):
        constraint.control_times_s[0] = 0.0


def test_corridor_is_local_and_intersects_the_global_search_band() -> None:
    result = extract_peak_ridge(
        _stft(),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        ridge_constraint=_constraint((1.0, 2.0), (25.0, 25.0), 6.0),
    )
    np.testing.assert_array_equal(result.frequency_hz, [20.0, 20.0, 30.0, 30.0])
    assert result.quality_flags == (RidgeQualityFlag.CANDIDATE,) * 4


def test_empty_per_frame_intersection_produces_no_candidate_or_fallback() -> None:
    stft = _stft()
    result = extract_peak_ridge(
        stft,
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=30.0,
        ridge_constraint=_constraint((1.0, 2.0), (11.0, 19.0), 0.25),
    )
    np.testing.assert_array_equal(result.frequency_hz[[0, 3]], [20.0, 30.0])
    assert np.isnan(result.frequency_hz[1:3]).all()
    assert result.quality_flags[1:3] == (
        RidgeQualityFlag.NO_ALLOWED_BINS,
        RidgeQualityFlag.NO_ALLOWED_BINS,
    )
    refined = refine_peak_ridge_subbin(stft, result)
    assert refined.refinement_statuses[1:3] == (
        RidgeRefinementStatus.NO_CANDIDATE,
        RidgeRefinementStatus.NO_CANDIDATE,
    )
    assert np.isnan(refined.refined_frequency_hz[1:3]).all()
    spectral_quality = assess_ridge_spectral_quality(
        stft,
        refined,
        background_exclusion_half_width_hz=1.0,
        minimum_background_bin_count=1,
    )
    related = assess_related_frequency_evidence(
        stft,
        refined,
        spectral_quality,
        search_half_width_hz=1.0,
    )
    assert spectral_quality.assessment_statuses[1:3] == (
        RidgeSpectralQualityStatus.NO_CANDIDATE,
        RidgeSpectralQualityStatus.NO_CANDIDATE,
    )
    assert related.double_frequency_statuses[1:3] == (
        RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE,
        RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE,
    )


@pytest.mark.parametrize(
    "constraint",
    [
        _constraint((-1.0, 2.0), (20.0, 20.0), 1.0),
        _constraint((1.0, 2.0), (50.0, 50.0), 1.0),
        _constraint((1.0, 2.0), (30.0, 30.0), 1.0),
    ],
)
def test_corridor_is_validated_against_stft_analysis_and_global_band(
    constraint: RidgeCorridorConstraint,
) -> None:
    with pytest.raises(RidgeConfigurationError):
        validate_ridge_corridor_for_stft(
            constraint,
            _stft(),
            minimum_frequency_hz=10.0,
            maximum_frequency_hz=20.0,
            analysis_start_time_s=0.0,
            analysis_end_time_s=3.0,
        )


def _records(source_path: Path) -> dict[str, SignalRecord]:
    sample_rate_hz = 40.0e9
    sample_count = 4096
    time_s = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    return {
        "pdv_channel_1": SignalRecord(
            time_s,
            np.sin(2.0 * np.pi * 0.63e9 * time_s),
            source_path=source_path,
        ),
        "pdv_channel_2": SignalRecord(
            time_s,
            np.sin(2.0 * np.pi * 0.66e9 * time_s),
            source_path=source_path,
        ),
    }


def _automatic(records: dict[str, SignalRecord]) -> dict[str, ChannelAnalysis]:
    return dict(
        analyze_profile(
            records,
            profile=BALANCED_PROFILE,
            analysis_start_time_s=15.0e-9,
            analysis_end_time_s=85.0e-9,
            manual_event_reference_time_s=20.0e-9,
            vacuum_wavelength_m=1550.0e-9,
            assume_pre_event_zero_for_display=True,
        )
    )


def _assert_same_analysis(left: ChannelAnalysis, right: ChannelAnalysis) -> None:
    for first, second in (
        (left.stft_result.time_s, right.stft_result.time_s),
        (left.stft_result.frequency_hz, right.stft_result.frequency_hz),
        (left.stft_result.spectrum, right.stft_result.spectrum),
        (left.ridge_result.frequency_hz, right.ridge_result.frequency_hz),
        (left.refined_result.refined_frequency_hz, right.refined_result.refined_frequency_hz),
        (
            left.signal_detection_result.refined_frequency_hz,
            right.signal_detection_result.refined_frequency_hz,
        ),
        (
            left.signal_detection_result.apparent_velocity_m_s,
            right.signal_detection_result.apparent_velocity_m_s,
        ),
        (left.formal_discrete_velocity_m_s, right.formal_discrete_velocity_m_s),
        (left.refined_velocity_m_s, right.refined_velocity_m_s),
        (left.display_velocity_m_s, right.display_velocity_m_s),
    ):
        np.testing.assert_array_equal(first, second)
    assert left.ridge_result.quality_flags == right.ridge_result.quality_flags
    assert left.refined_result.refinement_statuses == right.refined_result.refinement_statuses
    assert (
        left.spectral_quality_result.assessment_statuses
        == right.spectral_quality_result.assessment_statuses
    )
    assert (
        left.signal_detection_result.signal_states
        == right.signal_detection_result.signal_states
    )
    assert left.velocity_origins == right.velocity_origins
    assert (
        left.signal_detection_result.detected_event_candidate_time_s
        == right.signal_detection_result.detected_event_candidate_time_s
    )


def test_no_constraint_is_an_exact_automatic_regression(tmp_path: Path) -> None:
    records = _records(tmp_path / "source.csv")
    before = _automatic(records)
    after = dict(
        analyze_profile(
            records,
            profile=BALANCED_PROFILE,
            analysis_start_time_s=15.0e-9,
            analysis_end_time_s=85.0e-9,
            manual_event_reference_time_s=20.0e-9,
            vacuum_wavelength_m=1550.0e-9,
            assume_pre_event_zero_for_display=True,
            ridge_constraints=None,
        )
    )
    for channel_name in records:
        _assert_same_analysis(before[channel_name], after[channel_name])


def test_guided_workflow_preserves_inputs_stft_and_automatic_results(
    tmp_path: Path,
) -> None:
    records = _records(tmp_path / "source.csv")
    record_time = {name: record.time_s.copy() for name, record in records.items()}
    record_voltage = {name: record.voltage_v.copy() for name, record in records.items()}
    automatic = _automatic(records)
    automatic_spectrum = {
        name: analysis.stft_result.spectrum.copy()
        for name, analysis in automatic.items()
    }
    axis = automatic["pdv_channel_1"].stft_result.time_s
    active = axis[(axis >= 35.0e-9) & (axis <= 65.0e-9)]
    constraint = RidgeCorridorConstraint(
        control_times_s=np.array([active[0], active[-1]]),
        control_frequencies_hz=np.array([0.60e9, 0.70e9]),
        half_width_hz=50.0e6,
    )
    guided = dict(
        analyze_profile(
            records,
            profile=BALANCED_PROFILE,
            analysis_start_time_s=15.0e-9,
            analysis_end_time_s=85.0e-9,
            manual_event_reference_time_s=20.0e-9,
            vacuum_wavelength_m=1550.0e-9,
            assume_pre_event_zero_for_display=True,
            ridge_constraints={"pdv_channel_1": constraint},
        )
    )
    for channel_name, record in records.items():
        np.testing.assert_array_equal(record.time_s, record_time[channel_name])
        np.testing.assert_array_equal(record.voltage_v, record_voltage[channel_name])
        np.testing.assert_array_equal(
            guided[channel_name].stft_result.spectrum,
            automatic_spectrum[channel_name],
        )
    _assert_same_analysis(automatic["pdv_channel_2"], guided["pdv_channel_2"])
    _assert_same_analysis(automatic["pdv_channel_1"], automatic["pdv_channel_1"])


def test_noise_only_corridor_never_becomes_formal_frequency_or_velocity(
    tmp_path: Path,
) -> None:
    records = _records(tmp_path / "source.csv")
    automatic = _automatic(records)
    axis = automatic["pdv_channel_1"].stft_result.time_s
    active = axis[(axis >= 35.0e-9) & (axis <= 65.0e-9)]
    constraint = RidgeCorridorConstraint(
        control_times_s=np.array([active[0], active[-1]]),
        control_frequencies_hz=np.array([1.50e9, 1.50e9]),
        half_width_hz=10.0e6,
    )
    guided = analyze_profile(
        records,
        profile=BALANCED_PROFILE,
        analysis_start_time_s=15.0e-9,
        analysis_end_time_s=85.0e-9,
        manual_event_reference_time_s=20.0e-9,
        vacuum_wavelength_m=1550.0e-9,
        assume_pre_event_zero_for_display=True,
        ridge_constraints={"pdv_channel_1": constraint},
    )["pdv_channel_1"]
    active_mask = (axis >= constraint.start_time_s) & (axis <= constraint.end_time_s)
    assert active_mask.any()
    assert np.isnan(
        guided.signal_detection_result.refined_frequency_hz[active_mask]
    ).all()
    assert np.isnan(
        guided.signal_detection_result.apparent_velocity_m_s[active_mask]
    ).all()
    assert all(
        state is not SignalState.MEASURED
        for state, selected in zip(
            guided.signal_detection_result.signal_states,
            active_mask,
        )
        if selected
    )
    assert all(
        status in {
            RidgeSpectralQualityStatus.ASSESSED,
            RidgeSpectralQualityStatus.NO_CANDIDATE,
            RidgeSpectralQualityStatus.INVALID_PEAK_MAGNITUDE,
        }
        for status, selected in zip(
            guided.spectral_quality_result.assessment_statuses,
            active_mask,
        )
        if selected
    )
