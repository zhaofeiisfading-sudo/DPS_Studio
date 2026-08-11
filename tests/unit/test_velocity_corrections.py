"""Regression tests for formal angle and LiF velocity corrections."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dps_studio.core.physics import (
    LIF_RIGG_2014_1550NM,
    VelocityConfigurationError,
    VelocityCorrectionConfig,
    WindowMaterial,
    apply_velocity_corrections,
    correct_lif_window_velocity,
    correct_observation_angle,
    velocity_correction_metadata,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import analyze_configuration


def test_disabled_window_and_zero_angle_are_identity() -> None:
    source = np.asarray([0.0, 1000.0, np.nan], dtype=np.float64)
    result = apply_velocity_corrections(
        source,
        config=VelocityCorrectionConfig(window_material=WindowMaterial.NONE),
        vacuum_wavelength_m=1550.0e-9,
    )

    np.testing.assert_array_equal(
        result.angle_corrected_apparent_velocity_m_s,
        source,
    )
    np.testing.assert_array_equal(result.corrected_velocity_m_s, source)


def test_lif_known_values_use_paper_km_per_second_units() -> None:
    corrected = correct_lif_window_velocity(
        np.asarray([1000.0, 2000.0], dtype=np.float64)
    )

    # 1.000 km/s maps to 0.7895 km/s exactly. The second value was evaluated
    # independently as 1000 * 0.7895 * 2**0.9918.
    np.testing.assert_allclose(
        corrected,
        np.asarray([789.5, 1570.0507260007835]),
        rtol=1e-14,
        atol=1e-12,
    )


def test_lif_unit_regression_rejects_direct_m_per_second_power_law() -> None:
    corrected = float(correct_lif_window_velocity(np.asarray([2000.0]))[0])
    dimensionally_wrong = 0.7895 * 2000.0**0.9918

    assert corrected == pytest.approx(1570.0507260007835, rel=1e-14)
    assert corrected != pytest.approx(dimensionally_wrong, rel=1e-3)


def test_lif_preserves_zero_and_nan() -> None:
    corrected = correct_lif_window_velocity(np.asarray([0.0, np.nan]))

    assert corrected[0] == 0.0
    assert math.isnan(float(corrected[1]))


def test_angle_zero_is_exact_identity_and_known_angle_uses_projection() -> None:
    source = np.asarray([1000.0, np.nan])

    np.testing.assert_array_equal(
        correct_observation_angle(source, measurement_angle_rad=0.0),
        source,
    )
    sixty = correct_observation_angle(
        source,
        measurement_angle_rad=math.radians(60.0),
    )
    assert sixty[0] == pytest.approx(2000.0)
    assert math.isnan(float(sixty[1]))


@pytest.mark.parametrize(
    "angle",
    [math.nan, math.inf, -0.1, math.pi / 2.0, math.radians(100.0)],
)
def test_angle_validation_rejects_unsafe_values(angle: float) -> None:
    with pytest.raises(VelocityConfigurationError):
        correct_observation_angle(
            np.asarray([1000.0]),
            measurement_angle_rad=angle,
        )


def test_combined_correction_applies_angle_before_nonlinear_lif_model() -> None:
    result = apply_velocity_corrections(
        np.asarray([1000.0, np.nan]),
        config=VelocityCorrectionConfig(
            window_material=WindowMaterial.LIF,
            measurement_angle_rad=math.radians(60.0),
        ),
        vacuum_wavelength_m=1550.0e-9,
    )

    assert result.angle_corrected_apparent_velocity_m_s[0] == pytest.approx(2000.0)
    assert result.corrected_velocity_m_s[0] == pytest.approx(
        1570.0507260007835
    )
    assert math.isnan(float(result.corrected_velocity_m_s[1]))


def test_metadata_records_full_model_provenance_and_wavelength_warning() -> None:
    result = apply_velocity_corrections(
        np.asarray([1000.0]),
        vacuum_wavelength_m=1064.0e-9,
    )
    metadata = velocity_correction_metadata(result)
    angle = metadata["angle"]
    window = metadata["window"]

    assert isinstance(angle, dict)
    assert isinstance(window, dict)
    assert angle["angle_rad"] == 0.0
    assert angle["source_doi"] == "10.1063/1.4940935"
    assert window["material"] == "LiF"
    assert window["model"] == "Rigg2014_Eq16"
    assert window["b1"] == LIF_RIGG_2014_1550NM.b1
    assert window["b2"] == LIF_RIGG_2014_1550NM.b2
    assert window["source_doi"] == "10.1063/1.4890714"
    assert window["wavelength_matches_model_reference"] is False
    assert "1550 nm" in str(window["wavelength_validation_message"])


def test_formal_workflow_preserves_quality_states_and_nan_mask() -> None:
    sample_rate_hz = 2.0e9
    time_s = np.arange(2048, dtype=np.float64) / sample_rate_hz
    active = time_s >= 0.3e-6
    voltage_v = np.zeros_like(time_s)
    voltage_v[active] = np.sin(2.0 * np.pi * 200.0e6 * time_s[active])
    analysis = analyze_configuration(
        {"pdv_channel_1": SignalRecord(time_s, voltage_v)},
        window_length_samples=128,
        overlap_samples=64,
        nfft=512,
        window_name="hann",
        minimum_frequency_hz=20.0e6,
        maximum_frequency_hz=600.0e6,
        vacuum_wavelength_m=1550.0e-9,
    )["pdv_channel_1"]

    apparent_nan = np.isnan(analysis.apparent_velocity_m_s)
    np.testing.assert_array_equal(
        np.isnan(analysis.angle_corrected_apparent_velocity_m_s),
        apparent_nan,
    )
    np.testing.assert_array_equal(
        np.isnan(analysis.corrected_velocity_m_s),
        apparent_nan,
    )
    for index, state in enumerate(analysis.signal_detection_result.signal_states):
        if state is not SignalState.MEASURED:
            assert math.isnan(float(analysis.corrected_velocity_m_s[index]))
