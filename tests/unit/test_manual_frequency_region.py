from __future__ import annotations

import numpy as np
import pytest

from dps_studio.core.quality import SignalDetectionConfig, SignalState
from dps_studio.core.ridge import (
    ManualFrequencyBoundary,
    ManualFrequencyRegion,
    RidgeConfigurationError,
    evaluate_manual_frequency_region_bounds,
    manual_frequency_region_mask,
    validate_manual_frequency_region_for_stft,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import analyze_stft_results


def _stft() -> STFTResult:
    frequencies = np.arange(0.0, 1.01e9, 0.05e9)
    times = np.arange(5, dtype=np.float64)
    spectrum = np.ones((frequencies.size, times.size), dtype=np.complex128)
    ridge_hz = (0.2e9, 0.2e9, 0.2e9, 0.8e9, 0.8e9)
    for frame, frequency_hz in enumerate(ridge_hz):
        index = int(np.argmin(np.abs(frequencies - frequency_hz)))
        spectrum[index, frame] = 100.0
    return STFTResult(
        time_s=times,
        frequency_hz=frequencies,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=20,
        overlap_samples=10,
        hop_samples=10,
        nfft=40,
        sample_rate_hz=2.0e9,
        source_path=None,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _boundary(times: object, frequencies: object) -> ManualFrequencyBoundary:
    return ManualFrequencyBoundary(
        control_times_s=times,  # type: ignore[arg-type]
        control_frequencies_hz=frequencies,  # type: ignore[arg-type]
    )


def test_no_boundary_mask_is_complete_global_search_band() -> None:
    stft = _stft()
    mask = manual_frequency_region_mask(
        ManualFrequencyRegion(),
        stft,
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=0.9e9,
    )
    expected = (stft.frequency_hz >= 0.1e9) & (stft.frequency_hz <= 0.9e9)
    np.testing.assert_array_equal(
        mask,
        np.broadcast_to(expected[:, np.newaxis], stft.spectrum.shape),
    )
    assert not mask.flags.writeable


def test_upper_lower_and_both_boundaries_extend_endpoints_and_stay_ordered() -> None:
    upper = _boundary((1.0, 3.0), (0.3e9, 0.9e9))
    lower = _boundary((1.0, 3.0), (0.1e9, 0.7e9))
    upper_only = ManualFrequencyRegion(upper_boundary=upper)
    lower_only = ManualFrequencyRegion(lower_boundary=lower)
    both = ManualFrequencyRegion(upper_boundary=upper, lower_boundary=lower)
    assert upper.frequency_hz(2.0) == pytest.approx(0.6e9)
    assert upper.frequency_hz(0.0) == pytest.approx(0.3e9)
    assert upper.frequency_hz(4.0) == pytest.approx(0.9e9)
    assert upper_only.effective_bounds_hz(
        2.0,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=1.0e9,
    ) == pytest.approx((0.0, 0.6e9))
    assert lower_only.effective_bounds_hz(
        2.0,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=1.0e9,
    ) == pytest.approx((0.4e9, 1.0e9))
    assert both.effective_bounds_hz(
        2.0,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=1.0e9,
    ) == pytest.approx((0.4e9, 0.6e9))
    assert both.effective_bounds_hz(
        0.0,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=1.0e9,
    ) == pytest.approx((0.1e9, 0.3e9))
    assert both.effective_bounds_hz(
        4.0,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=1.0e9,
    ) == pytest.approx((0.7e9, 0.9e9))


def test_search_band_intersection_and_empty_intersection_are_explicit() -> None:
    stft = _stft()
    region = ManualFrequencyRegion(
        lower_boundary=_boundary((1.0, 3.0), (0.25e9, 0.25e9)),
        upper_boundary=_boundary((1.0, 3.0), (0.75e9, 0.75e9)),
    )
    mask = manual_frequency_region_mask(
        region,
        stft,
        minimum_frequency_hz=0.2e9,
        maximum_frequency_hz=0.8e9,
    )
    assert mask[:, 0].sum() == 11
    assert mask[:, 2].sum() == 11
    empty = ManualFrequencyRegion(
        lower_boundary=_boundary((1.0, 3.0), (0.95e9, 0.95e9))
    )
    with pytest.raises(RidgeConfigurationError, match="exceeds the upper"):
        validate_manual_frequency_region_for_stft(
            empty,
            stft,
            minimum_frequency_hz=0.1e9,
            maximum_frequency_hz=0.9e9,
        )


def test_mismatched_control_spans_evaluate_every_frame_and_crossing_is_rejected() -> None:
    stft = _stft()
    region = ManualFrequencyRegion(
        upper_boundary=_boundary((0.5, 1.5), (0.8e9, 0.7e9)),
        lower_boundary=_boundary((2.5, 3.5), (0.2e9, 0.3e9)),
    )
    lower, upper = evaluate_manual_frequency_region_bounds(
        region,
        stft.time_s,
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=0.9e9,
    )
    np.testing.assert_allclose(lower, [0.2e9, 0.2e9, 0.2e9, 0.25e9, 0.3e9])
    np.testing.assert_allclose(upper, [0.8e9, 0.75e9, 0.7e9, 0.7e9, 0.7e9])
    assert lower.shape == stft.time_s.shape
    assert upper.shape == stft.time_s.shape

    with pytest.raises(RidgeConfigurationError, match="exceeds the upper"):
        ManualFrequencyRegion(
            upper_boundary=_boundary((0.0, 1.0), (0.6e9, 0.6e9)),
            lower_boundary=_boundary((2.0, 3.0), (0.7e9, 0.5e9)),
        )


def test_crossing_single_duplicate_and_decreasing_points_are_rejected() -> None:
    with pytest.raises(RidgeConfigurationError, match="at least two"):
        _boundary((1.0,), (0.5e9,))
    for times in ((1.0, 1.0), (2.0, 1.0)):
        with pytest.raises(RidgeConfigurationError, match="strictly increasing"):
            _boundary(times, (0.5e9, 0.5e9))
    with pytest.raises(RidgeConfigurationError, match="exceeds the upper"):
        ManualFrequencyRegion(
            upper_boundary=_boundary((1.0, 3.0), (0.6e9, 0.2e9)),
            lower_boundary=_boundary((1.0, 3.0), (0.1e9, 0.7e9)),
        )


def test_sharp_jump_region_rasterizes_without_fixed_half_width() -> None:
    stft = _stft()
    region = ManualFrequencyRegion(
        upper_boundary=_boundary(
            (0.0, 2.0, 3.0, 4.0),
            (0.25e9, 0.25e9, 0.9e9, 0.9e9),
        ),
        lower_boundary=_boundary(
            (0.0, 2.0, 3.0, 4.0),
            (0.15e9, 0.15e9, 0.7e9, 0.7e9),
        ),
    )
    mask = manual_frequency_region_mask(
        region,
        stft,
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=0.95e9,
    )
    allowed_frame_2 = stft.frequency_hz[mask[:, 2]]
    allowed_frame_3 = stft.frequency_hz[mask[:, 3]]
    np.testing.assert_array_equal(allowed_frame_2, [0.15e9, 0.2e9, 0.25e9])
    np.testing.assert_array_equal(
        allowed_frame_3,
        [0.7e9, 0.75e9, 0.8e9, 0.85e9, 0.9e9],
    )


def test_manual_pipeline_preserves_stft_and_uses_production_candidates() -> None:
    stft = _stft()
    spectrum_before = stft.spectrum.copy()
    region = ManualFrequencyRegion(
        upper_boundary=_boundary((0.0, 4.0), (0.9e9, 0.9e9)),
        lower_boundary=_boundary((0.0, 4.0), (0.1e9, 0.1e9)),
    )
    analysis = analyze_stft_results(
        {"pdv": stft},
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=0.9e9,
        analysis_start_time_s=0.0,
        analysis_end_time_s=4.0,
        manual_event_reference_time_s=0.0,
        vacuum_wavelength_m=1550.0e-9,
        detection_config=SignalDetectionConfig(enabled=False),
        ridge_constraints={"pdv": region},
    )["pdv"]
    np.testing.assert_array_equal(stft.spectrum, spectrum_before)
    assert analysis.stft_result is stft
    assert analysis.local_peak_candidates is not None
    assert analysis.experimental_reselection_result is not None
    np.testing.assert_array_equal(
        analysis.ridge_result.frequency_hz,
        [0.2e9, 0.2e9, 0.2e9, 0.8e9, 0.8e9],
    )


def test_manual_region_does_not_force_a_ridge_when_no_peak_is_credible() -> None:
    stft = _stft()
    spectrum_before = stft.spectrum.copy()
    region = ManualFrequencyRegion(
        upper_boundary=_boundary((0.0, 4.0), (0.5e9, 0.5e9)),
        lower_boundary=_boundary((0.0, 4.0), (0.4e9, 0.4e9)),
    )
    analysis = analyze_stft_results(
        {"pdv": stft},
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=0.9e9,
        analysis_start_time_s=0.0,
        analysis_end_time_s=4.0,
        manual_event_reference_time_s=0.0,
        vacuum_wavelength_m=1550.0e-9,
        detection_config=SignalDetectionConfig(
            enabled=True,
            peak_exclusion_half_width_bins=1,
        ),
        minimum_background_bin_count=2,
        ridge_constraints={"pdv": region},
    )["pdv"]

    np.testing.assert_array_equal(stft.spectrum, spectrum_before)
    assert np.isnan(
        analysis.signal_detection_result.refined_frequency_hz
    ).all()
    assert np.isnan(
        analysis.signal_detection_result.apparent_velocity_m_s
    ).all()
    assert all(
        state is not SignalState.MEASURED
        for state in analysis.signal_detection_result.signal_states
    )


def test_manual_mask_preserves_the_same_pre_event_display_platform() -> None:
    stft = _stft()
    common = dict(
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=0.9e9,
        analysis_start_time_s=0.0,
        analysis_end_time_s=4.0,
        manual_event_reference_time_s=2.0,
        vacuum_wavelength_m=1550.0e-9,
        detection_config=SignalDetectionConfig(
            enabled=True,
            minimum_peak_to_background_db=100.0,
        ),
        assume_pre_event_zero_for_display=True,
        pre_event_display_velocity_m_s=0.0,
    )
    automatic = analyze_stft_results({"pdv": stft}, **common)["pdv"]
    manual = analyze_stft_results(
        {"pdv": stft},
        **common,
        ridge_constraints={
            "pdv": ManualFrequencyRegion(
                upper_boundary=_boundary((1.0, 3.0), (0.85e9, 0.85e9)),
                lower_boundary=_boundary((0.5, 2.5), (0.15e9, 0.15e9)),
            )
        },
    )["pdv"]

    pre_event = stft.time_s < 2.0
    np.testing.assert_array_equal(
        automatic.display_velocity_m_s[pre_event],
        manual.display_velocity_m_s[pre_event],
    )
    np.testing.assert_array_equal(manual.display_velocity_m_s[pre_event], 0.0)
    assert np.isnan(automatic.apparent_velocity_m_s[pre_event]).all()
    assert np.isnan(manual.apparent_velocity_m_s[pre_event]).all()
