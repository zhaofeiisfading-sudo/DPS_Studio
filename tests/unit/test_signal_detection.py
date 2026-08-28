from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import (
    SignalDetectionConfig,
    SignalState,
    detect_beat_signal,
)
from dps_studio.core.ridge import (
    RidgeRefinementStatus,
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import analyze_configuration


SAMPLE_RATE_HZ = 4.0e9
WINDOW_SAMPLES = 256
OVERLAP_SAMPLES = 128
NFFT = 1024
WAVELENGTH_M = 1550e-9


def _detection_config(
    *,
    minimum_peak_to_background_db: float = 18.0,
    tracking_minimum_peak_to_background_db: float | None = None,
    minimum_peak_to_competitor_db: float = 4.0,
    maximum_tracking_frequency_step_hz: float | None = None,
    peak_exclusion_half_width_bins: int = 8,
    minimum_consecutive_frames: int = 3,
    minimum_cycles_in_window: float = 1.0,
) -> SignalDetectionConfig:
    return SignalDetectionConfig(
        minimum_peak_to_background_db=minimum_peak_to_background_db,
        tracking_minimum_peak_to_background_db=(
            tracking_minimum_peak_to_background_db
        ),
        minimum_peak_to_competitor_db=minimum_peak_to_competitor_db,
        maximum_tracking_frequency_step_hz=(
            maximum_tracking_frequency_step_hz
        ),
        peak_exclusion_half_width_bins=peak_exclusion_half_width_bins,
        minimum_consecutive_frames=minimum_consecutive_frames,
        minimum_cycles_in_window=minimum_cycles_in_window,
        enabled=True,
    )


def _analyze_voltage(
    voltage_v: np.ndarray,
    *,
    config: SignalDetectionConfig | None = None,
    minimum_frequency_hz: float = 20.0e6,
    maximum_frequency_hz: float = 800.0e6,
    manual_event_reference_time_s: float | None = None,
    assume_pre_event_zero_for_display: bool = False,
    pre_event_display_velocity_m_s: float = 0.0,
) -> object:
    time_s = np.arange(voltage_v.size, dtype=np.float64) / SAMPLE_RATE_HZ
    records = {
        "pdv_channel_1": SignalRecord(
            time_s,
            voltage_v,
            source_path=Path("synthetic.csv"),
        )
    }
    return analyze_configuration(
        records,
        window_length_samples=WINDOW_SAMPLES,
        overlap_samples=OVERLAP_SAMPLES,
        nfft=NFFT,
        window_name="hann",
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        manual_event_reference_time_s=manual_event_reference_time_s,
        vacuum_wavelength_m=WAVELENGTH_M,
        detection_config=config or _detection_config(),
        minimum_background_bin_count=2,
        assume_pre_event_zero_for_display=assume_pre_event_zero_for_display,
        pre_event_display_velocity_m_s=pre_event_display_velocity_m_s,
    )["pdv_channel_1"]


def _manual_detection(
    spectrum: np.ndarray,
    *,
    minimum_frequency_hz: float = 50.0,
    maximum_frequency_hz: float = 400.0,
    config: SignalDetectionConfig | None = None,
) -> object:
    frame_count = spectrum.shape[1]
    stft = STFTResult(
        time_s=0.01 + np.arange(frame_count, dtype=np.float64) * 0.01,
        frequency_hz=np.arange(11, dtype=np.float64) * 50.0,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=20,
        overlap_samples=10,
        hop_samples=10,
        nfft=20,
        sample_rate_hz=1000.0,
        source_path=None,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    ridge = extract_peak_ridge(
        stft,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
    )
    refined = refine_peak_ridge_subbin(stft, ridge)
    quality = assess_ridge_spectral_quality(
        stft,
        refined,
        background_exclusion_half_width_hz=75.0,
        minimum_background_bin_count=2,
    )
    return detect_beat_signal(
        stft,
        refined,
        quality,
        detection_config=config
        or _detection_config(
            minimum_peak_to_background_db=10.0,
            minimum_peak_to_competitor_db=3.0,
            peak_exclusion_half_width_bins=1,
            minimum_consecutive_frames=1,
            minimum_cycles_in_window=1.0,
        ),
        vacuum_wavelength_m=WAVELENGTH_M,
    )


def test_seeded_pure_noise_never_becomes_formal_velocity() -> None:
    rng = np.random.default_rng(20260726)
    analysis = _analyze_voltage(rng.normal(0.0, 1.0, 8192))
    detection = analysis.signal_detection_result
    assert np.isnan(detection.refined_frequency_hz).all()
    assert np.isnan(detection.apparent_velocity_m_s).all()
    assert detection.detected_event_candidate_time_s is None
    assert SignalState.MEASURED not in detection.signal_states


def test_clear_tone_onset_is_detected_without_a_manual_time_gate() -> None:
    rng = np.random.default_rng(1301)
    sample_count = 8192
    time_s = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE_HZ
    onset_s = 0.8e-6
    voltage = rng.normal(0.0, 0.02, sample_count)
    after = time_s >= onset_s
    voltage[after] += 2.0 * np.sin(2.0 * np.pi * 200.0e6 * time_s[after])
    analysis = _analyze_voltage(voltage)
    detection = analysis.signal_detection_result
    candidate = detection.detected_event_candidate_time_s
    assert candidate is not None
    assert candidate >= onset_s - detection.window_duration_s / 2.0
    assert candidate <= onset_s + detection.window_duration_s / 2.0
    before = detection.time_s < onset_s - detection.window_duration_s / 2.0
    assert set(np.asarray(detection.signal_states, dtype=object)[before]) == {
        SignalState.NO_DETECTABLE_BEAT
    }
    measured = np.asarray(
        [state is SignalState.MEASURED for state in detection.signal_states]
    )
    assert measured.any()
    np.testing.assert_allclose(
        detection.refined_frequency_hz[measured],
        200.0e6,
        rtol=0.0,
        atol=2.0 * SAMPLE_RATE_HZ / NFFT,
    )
    np.testing.assert_allclose(
        detection.apparent_velocity_m_s[measured],
        WAVELENGTH_M * detection.refined_frequency_hz[measured] / 2.0,
    )


def test_full_record_tone_is_measurable_from_first_stft_frame() -> None:
    time_s = np.arange(4096, dtype=np.float64) / SAMPLE_RATE_HZ
    analysis = _analyze_voltage(np.sin(2.0 * np.pi * 200.0e6 * time_s))
    detection = analysis.signal_detection_result
    assert detection.signal_states[0] is SignalState.MEASURED
    assert detection.detected_event_candidate_time_s == detection.time_s[0]


def test_weak_tone_below_threshold_stays_nan() -> None:
    rng = np.random.default_rng(1302)
    time_s = np.arange(8192, dtype=np.float64) / SAMPLE_RATE_HZ
    voltage = rng.normal(0.0, 1.0, time_s.size)
    voltage += 0.01 * np.sin(2.0 * np.pi * 200.0e6 * time_s)
    detection = _analyze_voltage(voltage).signal_detection_result
    assert np.isnan(detection.apparent_velocity_m_s).all()
    assert SignalState.MEASURED not in detection.signal_states


def test_equal_competing_lines_are_ambiguous() -> None:
    spectrum = np.ones((11, 3), dtype=np.complex128)
    spectrum[4, :] = 100.0
    spectrum[7, :] = 100.0
    result = _manual_detection(spectrum)
    assert result.signal_states == (SignalState.AMBIGUOUS_PEAK,) * 3
    assert np.isnan(result.apparent_velocity_m_s).all()


def test_peak_at_search_boundary_is_not_formal() -> None:
    spectrum = np.ones((11, 3), dtype=np.complex128)
    spectrum[2, :] = 100.0
    result = _manual_detection(
        spectrum,
        minimum_frequency_hz=100.0,
        maximum_frequency_hz=400.0,
    )
    assert result.signal_states == (SignalState.PEAK_AT_BAND_BOUNDARY,) * 3
    assert result.peak_is_at_band_boundary.all()
    assert np.isnan(result.refined_frequency_hz).all()


def test_insufficient_cycle_candidate_is_nan_not_zero() -> None:
    spectrum = np.ones((11, 3), dtype=np.complex128)
    spectrum[2, :] = 100.0
    result = _manual_detection(
        spectrum,
        minimum_frequency_hz=50.0,
        maximum_frequency_hz=400.0,
        config=_detection_config(
            minimum_peak_to_background_db=10.0,
            minimum_peak_to_competitor_db=3.0,
            peak_exclusion_half_width_bins=1,
            minimum_consecutive_frames=1,
            minimum_cycles_in_window=3.0,
        ),
    )
    assert result.signal_states == (SignalState.INSUFFICIENT_CYCLES,) * 3
    assert np.isnan(result.apparent_velocity_m_s).all()
    assert not np.equal(result.apparent_velocity_m_s, 0.0).any()


def test_below_0_1_ghz_tone_can_pass_when_cycles_and_quality_are_sufficient() -> None:
    time_s = np.arange(8192, dtype=np.float64) / SAMPLE_RATE_HZ
    analysis = _analyze_voltage(
        2.0 * np.sin(2.0 * np.pi * 80.0e6 * time_s),
        minimum_frequency_hz=40.0e6,
    )
    detection = analysis.signal_detection_result
    measured = np.asarray(
        [state is SignalState.MEASURED for state in detection.signal_states]
    )
    assert measured.any()
    assert np.nanmedian(detection.refined_frequency_hz) == pytest.approx(
        80.0e6,
        abs=2.0 * SAMPLE_RATE_HZ / NFFT,
    )


def test_refinement_failure_is_explicit_and_nan() -> None:
    spectrum = np.ones((11, 3), dtype=np.complex128)
    spectrum[4, :] = 100.0
    spectrum[3, :] = 0.0
    result = _manual_detection(spectrum)
    assert result.refinement_statuses == (
        RidgeRefinementStatus.INVALID_LOCAL_PEAK,
    ) * 3
    assert result.signal_states == (SignalState.REFINEMENT_FAILED,) * 3
    assert np.isnan(result.refined_frequency_hz).all()


def test_two_frame_isolated_run_is_unstable_and_has_no_event_candidate() -> None:
    spectrum = np.ones((11, 7), dtype=np.complex128)
    spectrum[4, 2:4] = 100.0
    result = _manual_detection(
        spectrum,
        config=_detection_config(
            minimum_peak_to_background_db=10.0,
            minimum_peak_to_competitor_db=3.0,
            peak_exclusion_half_width_bins=1,
            minimum_consecutive_frames=3,
            minimum_cycles_in_window=1.0,
        ),
    )
    assert result.signal_states[2:4] == (SignalState.UNSTABLE_DETECTION,) * 2
    assert result.detected_event_candidate_time_s is None
    assert np.isnan(result.apparent_velocity_m_s).all()


def test_hysteresis_tracks_brief_weaker_frames_without_fragmenting_segment() -> None:
    spectrum = np.ones((11, 12), dtype=np.complex128)
    spectrum[4, :] = 100.0
    spectrum[4, 5:7] = 2.5
    result = _manual_detection(
        spectrum,
        config=_detection_config(
            minimum_peak_to_background_db=10.0,
            tracking_minimum_peak_to_background_db=7.0,
            minimum_peak_to_competitor_db=3.0,
            maximum_tracking_frequency_step_hz=75.0,
            peak_exclusion_half_width_bins=1,
            minimum_consecutive_frames=3,
        ),
    )
    assert result.signal_states == (SignalState.MEASURED,) * 12
    assert result.peak_to_background_db[5] < 10.0
    assert result.peak_to_background_db[5] >= 7.0


def test_hysteresis_does_not_reacquire_random_strong_noise_path() -> None:
    spectrum = np.ones((11, 18), dtype=np.complex128)
    spectrum[4, :6] = 100.0
    for frame, peak_bin in enumerate((2, 7, 3, 6, 2, 7, 3, 6, 2, 7, 3, 6), 6):
        spectrum[peak_bin, frame] = 100.0
    result = _manual_detection(
        spectrum,
        config=_detection_config(
            minimum_peak_to_background_db=10.0,
            tracking_minimum_peak_to_background_db=7.0,
            minimum_peak_to_competitor_db=3.0,
            maximum_tracking_frequency_step_hz=75.0,
            peak_exclusion_half_width_bins=1,
            minimum_consecutive_frames=3,
        ),
    )
    assert result.signal_states[:6] == (SignalState.MEASURED,) * 6
    assert SignalState.MEASURED not in result.signal_states[6:]
    assert np.isnan(result.refined_frequency_hz[6:]).all()


def test_hysteresis_strictly_reacquires_a_sustained_returning_signal() -> None:
    spectrum = np.ones((11, 18), dtype=np.complex128)
    spectrum[4, :6] = 100.0
    spectrum[6, 11:] = 100.0
    result = _manual_detection(
        spectrum,
        config=_detection_config(
            minimum_peak_to_background_db=10.0,
            tracking_minimum_peak_to_background_db=7.0,
            minimum_peak_to_competitor_db=3.0,
            maximum_tracking_frequency_step_hz=75.0,
            peak_exclusion_half_width_bins=1,
            minimum_consecutive_frames=3,
        ),
    )
    assert result.signal_states[:6] == (SignalState.MEASURED,) * 6
    assert SignalState.MEASURED not in result.signal_states[6:11]
    assert result.signal_states[11:] == (SignalState.MEASURED,) * 7


def test_manual_reference_changes_no_formal_detection_values() -> None:
    time_s = np.arange(4096, dtype=np.float64) / SAMPLE_RATE_HZ
    voltage = np.sin(2.0 * np.pi * 200.0e6 * time_s)
    first = _analyze_voltage(voltage, manual_event_reference_time_s=0.2e-6)
    second = _analyze_voltage(voltage, manual_event_reference_time_s=1.2e-6)
    np.testing.assert_array_equal(
        first.signal_detection_result.refined_frequency_hz,
        second.signal_detection_result.refined_frequency_hz,
    )
    np.testing.assert_array_equal(
        first.refined_velocity_m_s,
        second.refined_velocity_m_s,
    )
    assert (
        first.signal_detection_result.signal_states
        == second.signal_detection_result.signal_states
    )


def test_explicit_pre_event_platform_overrides_measured_display_only() -> None:
    time_s = np.arange(4096, dtype=np.float64) / SAMPLE_RATE_HZ
    voltage = np.sin(2.0 * np.pi * 200.0e6 * time_s)
    reference_s = 0.5e-6
    analysis = _analyze_voltage(
        voltage,
        manual_event_reference_time_s=reference_s,
        assume_pre_event_zero_for_display=True,
    )
    before = analysis.stft_result.time_s < reference_s
    measured = np.asarray(
        [
            state is SignalState.MEASURED
            for state in analysis.signal_detection_result.signal_states
        ]
    )
    assert before.any()
    assert measured[before].all()
    np.testing.assert_array_equal(
        analysis.display_velocity_m_s[before],
        0.0,
    )
    assert np.isfinite(analysis.corrected_velocity_m_s[before]).all()
    assert set(
        np.asarray(analysis.velocity_origins, dtype=object)[before]
    ) == {
        "configured_pre_event_display_velocity_only"
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minimum_peak_to_background_db": math.nan},
        {"minimum_peak_to_background_db": -1.0},
        {
            "minimum_peak_to_background_db": 6.0,
            "tracking_minimum_peak_to_background_db": 7.0,
        },
        {"minimum_peak_to_competitor_db": math.inf},
        {"maximum_tracking_frequency_step_hz": 0.0},
        {"peak_exclusion_half_width_bins": -1},
        {"minimum_consecutive_frames": 0},
        {"minimum_cycles_in_window": 0.0},
        {"enabled": 1},
    ],
)
def test_detection_config_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        SignalDetectionConfig(**kwargs)  # type: ignore[arg-type]
