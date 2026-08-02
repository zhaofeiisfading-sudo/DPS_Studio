from __future__ import annotations

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalDetectionConfig, SignalState
from dps_studio.core.workflow import (
    PRE_EVENT_DISPLAY_ORIGIN,
    analyze_configuration,
    build_display_velocity,
)


def test_default_pre_event_display_velocity_is_zero_m_s() -> None:
    time_s, states, formal = _mixed_states()
    display, origins = build_display_velocity(
        time_s,
        states,
        formal,
        manual_event_reference_time_s=3.0,
        enable_pre_event_display=True,
    )
    np.testing.assert_array_equal(display[:2], [0.0, 0.0])
    assert origins[:2] == (PRE_EVENT_DISPLAY_ORIGIN,) * 2


def test_nonzero_platform_changes_only_pre_event_nonmeasured_frames() -> None:
    time_s, states, formal = _mixed_states()
    formal_bytes = formal.tobytes()
    display, origins = build_display_velocity(
        time_s,
        states,
        formal,
        manual_event_reference_time_s=3.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    np.testing.assert_array_equal(display[:2], [12.5, 12.5])
    assert display[2] == formal[2]
    assert display[3] == formal[3]
    assert np.isnan(display[4:]).all()
    assert formal.tobytes() == formal_bytes
    assert np.isnan(formal[[0, 1, 4, 5]]).all()
    assert origins[0] == PRE_EVENT_DISPLAY_ORIGIN
    assert origins[1] == PRE_EVENT_DISPLAY_ORIGIN
    assert origins[2] == "quality_gated_measurement"
    assert origins[4] == SignalState.NO_DETECTABLE_BEAT.value
    assert origins[5] == SignalState.REFINEMENT_FAILED.value


@pytest.mark.parametrize(
    "post_event_state",
    [
        SignalState.NO_DETECTABLE_BEAT,
        SignalState.AMBIGUOUS_PEAK,
        SignalState.UNSTABLE_DETECTION,
        SignalState.REFINEMENT_FAILED,
        SignalState.INSUFFICIENT_CYCLES,
        SignalState.PEAK_AT_BAND_BOUNDARY,
        SignalState.OUTSIDE_ANALYSIS_WINDOW,
    ],
)
def test_every_post_event_invalid_state_stays_nan(
    post_event_state: SignalState,
) -> None:
    display, _origins = build_display_velocity(
        np.asarray([0.0, 2.0]),
        (SignalState.NO_DETECTABLE_BEAT, post_event_state),
        np.asarray([np.nan, np.nan]),
        manual_event_reference_time_s=1.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    assert display[0] == 12.5
    assert np.isnan(display[1])


def test_channels_apply_their_own_state_masks_without_fusion() -> None:
    time_s = np.asarray([0.0, 1.0, 2.0])
    first, _ = build_display_velocity(
        time_s,
        (
            SignalState.NO_DETECTABLE_BEAT,
            SignalState.MEASURED,
            SignalState.NO_DETECTABLE_BEAT,
        ),
        np.asarray([np.nan, 30.0, np.nan]),
        manual_event_reference_time_s=2.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    second, _ = build_display_velocity(
        time_s,
        (
            SignalState.MEASURED,
            SignalState.AMBIGUOUS_PEAK,
            SignalState.NO_DETECTABLE_BEAT,
        ),
        np.asarray([20.0, np.nan, np.nan]),
        manual_event_reference_time_s=2.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    np.testing.assert_array_equal(first, [12.5, 30.0, np.nan])
    np.testing.assert_array_equal(second, [20.0, 12.5, np.nan])


def test_platform_is_limited_to_analysis_start_and_valid_reference() -> None:
    time_s = np.arange(5, dtype=np.float64)
    formal = np.full(5, np.nan, dtype=np.float64)
    states = (
        SignalState.OUTSIDE_ANALYSIS_WINDOW,
        SignalState.NO_DETECTABLE_BEAT,
        SignalState.AMBIGUOUS_PEAK,
        SignalState.NO_DETECTABLE_BEAT,
        SignalState.OUTSIDE_ANALYSIS_WINDOW,
    )
    display, origins = build_display_velocity(
        time_s,
        states,
        formal,
        manual_event_reference_time_s=3.0,
        analysis_start_time_s=1.0,
        analysis_end_time_s=4.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    assert np.isnan(display[0])
    np.testing.assert_array_equal(display[1:3], [12.5, 12.5])
    assert np.isnan(display[3:]).all()
    assert origins[0] == "outside_analysis_window"

    invalid_reference, _ = build_display_velocity(
        time_s,
        states,
        formal,
        manual_event_reference_time_s=8.0,
        analysis_start_time_s=1.0,
        analysis_end_time_s=4.0,
        enable_pre_event_display=True,
        pre_event_display_velocity_m_s=12.5,
    )
    assert np.isnan(invalid_reference).all()


def test_workflow_platform_parameter_leaves_formal_velocity_bitwise_equal() -> None:
    sample_rate_hz = 4.0e9
    sample_count = 4096
    time_s = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    voltage_v = np.zeros(sample_count, dtype=np.float64)
    active = (time_s >= 0.4e-6) & (time_s < 0.8e-6)
    voltage_v[active] = np.sin(2.0 * np.pi * 200.0e6 * time_s[active])
    record = SignalRecord(time_s, voltage_v)
    common = dict(
        window_length_samples=256,
        overlap_samples=128,
        nfft=1024,
        window_name="hann",
        minimum_frequency_hz=20.0e6,
        maximum_frequency_hz=800.0e6,
        manual_event_reference_time_s=0.4e-6,
        vacuum_wavelength_m=1.55e-6,
        detection_config=SignalDetectionConfig(),
        assume_pre_event_zero_for_display=True,
    )
    zero = analyze_configuration(
        {"pdv": record},
        pre_event_display_velocity_m_s=0.0,
        **common,
    )["pdv"]
    nonzero = analyze_configuration(
        {"pdv": record},
        pre_event_display_velocity_m_s=12.5,
        **common,
    )["pdv"]
    np.testing.assert_array_equal(
        zero.signal_detection_result.apparent_velocity_m_s,
        nonzero.signal_detection_result.apparent_velocity_m_s,
    )
    assert (
        zero.signal_detection_result.signal_states
        == nonzero.signal_detection_result.signal_states
    )
    np.testing.assert_array_equal(
        zero.signal_detection_result.refined_frequency_hz,
        nonzero.signal_detection_result.refined_frequency_hz,
    )
    pre_display = (
        (zero.stft_result.time_s < 0.4e-6)
        & np.isnan(zero.signal_detection_result.apparent_velocity_m_s)
    )
    assert pre_display.any()
    np.testing.assert_array_equal(zero.display_velocity_m_s[pre_display], 0.0)
    np.testing.assert_array_equal(nonzero.display_velocity_m_s[pre_display], 12.5)


def _mixed_states() -> tuple[
    np.ndarray,
    tuple[SignalState, ...],
    np.ndarray,
]:
    return (
        np.arange(6, dtype=np.float64),
        (
            SignalState.NO_DETECTABLE_BEAT,
            SignalState.AMBIGUOUS_PEAK,
            SignalState.MEASURED,
            SignalState.MEASURED,
            SignalState.NO_DETECTABLE_BEAT,
            SignalState.REFINEMENT_FAILED,
        ),
        np.asarray([np.nan, np.nan, 20.0, 30.0, np.nan, np.nan]),
    )
