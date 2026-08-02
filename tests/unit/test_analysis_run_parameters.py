from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from dps_studio.core import (
    BALANCED_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
    AnalysisParameterOverrides,
    build_analysis_run_parameters,
)
from dps_studio.core.models import SignalRecord


def _record(*, sample_count: int = 4096, sample_interval_s: float = 1.0e-10) -> SignalRecord:
    time_s = np.arange(sample_count, dtype=np.float64) * sample_interval_s
    return SignalRecord(time_s, np.sin(2.0 * np.pi * 0.5e9 * time_s))


def test_unchanged_formal_presets_produce_no_overrides() -> None:
    for profile in (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE):
        parameters = build_analysis_run_parameters(
            base_profile=profile,
            base_vacuum_wavelength_m=1.55e-6,
        )
        assert parameters.base_profile is profile
        assert parameters.preset_name == profile.display_name
        assert parameters.preset_id == profile.profile_id.value
        assert not parameters.is_custom
        assert not parameters.custom_overrides
        assert parameters.window_length_samples == profile.window_length_samples
        assert parameters.overlap_samples == profile.overlap_samples
        assert parameters.hop_samples == profile.hop_samples
        assert parameters.nfft == profile.nfft
        assert parameters.minimum_frequency_hz == profile.minimum_frequency_hz
        assert parameters.maximum_frequency_hz == profile.maximum_frequency_hz


def test_explicit_overrides_are_immutable_and_do_not_mutate_balanced() -> None:
    original = (
        BALANCED_PROFILE.window_length_samples,
        BALANCED_PROFILE.overlap_samples,
        BALANCED_PROFILE.hop_samples,
        BALANCED_PROFILE.nfft,
        BALANCED_PROFILE.minimum_frequency_hz,
        BALANCED_PROFILE.maximum_frequency_hz,
    )
    parameters = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE,
        base_vacuum_wavelength_m=1.55e-6,
        overrides=AnalysisParameterOverrides(
            vacuum_wavelength_m=1.064e-6,
            window_length_samples=1024,
            overlap_samples=768,
            nfft=4095,
            minimum_frequency_hz=0.1e9,
            maximum_frequency_hz=1.8e9,
        ),
    )
    assert parameters.is_custom
    assert parameters.preset_name == "Balanced"
    assert parameters.preset_id == "custom"
    assert parameters.provenance_name == "custom_based_on_balanced"
    assert parameters.hop_samples == 256
    assert dict(parameters.custom_overrides) == {
        "vacuum_wavelength_m": 1.064e-6,
        "window_length_samples": 1024,
        "overlap_samples": 768,
        "nfft": 4095,
        "minimum_frequency_hz": 0.1e9,
        "maximum_frequency_hz": 1.8e9,
    }
    assert original == (
        BALANCED_PROFILE.window_length_samples,
        BALANCED_PROFILE.overlap_samples,
        BALANCED_PROFILE.hop_samples,
        BALANCED_PROFILE.nfft,
        BALANCED_PROFILE.minimum_frequency_hz,
        BALANCED_PROFILE.maximum_frequency_hz,
    )
    with pytest.raises(FrozenInstanceError):
        parameters.nfft = 8192  # type: ignore[misc]


def test_hop_is_derived_and_cannot_be_overridden_independently() -> None:
    parameters = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE,
        base_vacuum_wavelength_m=1.55e-6,
        overrides=AnalysisParameterOverrides(overlap_samples=512),
    )
    assert parameters.window_length_samples == 768
    assert parameters.overlap_samples == 512
    assert parameters.hop_samples == 256
    assert "hop_samples" not in AnalysisParameterOverrides.__dataclass_fields__


def test_nfft_uses_formal_greater_than_or_equal_to_window_rule() -> None:
    odd_nfft = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE,
        base_vacuum_wavelength_m=1.55e-6,
        overrides=AnalysisParameterOverrides(nfft=4095),
    )
    assert odd_nfft.nfft == 4095
    with pytest.raises(ValueError, match="nfft"):
        build_analysis_run_parameters(
            base_profile=BALANCED_PROFILE,
            base_vacuum_wavelength_m=1.55e-6,
            overrides=AnalysisParameterOverrides(nfft=767),
        )


def test_search_band_uses_static_and_exact_loaded_grid_validation() -> None:
    with pytest.raises(ValueError, match="maximum_frequency_hz"):
        build_analysis_run_parameters(
            base_profile=BALANCED_PROFILE,
            base_vacuum_wavelength_m=1.55e-6,
            overrides=AnalysisParameterOverrides(
                minimum_frequency_hz=2.0e9,
                maximum_frequency_hz=1.0e9,
            ),
        )
    odd_nfft = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE,
        base_vacuum_wavelength_m=1.55e-6,
        overrides=AnalysisParameterOverrides(
            nfft=4095,
            maximum_frequency_hz=5.0e9,
        ),
    )
    with pytest.raises(ValueError, match="STFT/Nyquist"):
        odd_nfft.validate_for_records({"pdv": _record()})


def test_loaded_record_window_limit_is_not_silently_clamped() -> None:
    parameters = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE,
        base_vacuum_wavelength_m=1.55e-6,
        overrides=AnalysisParameterOverrides(window_length_samples=2048),
    )
    with pytest.raises(ValueError, match="record.sample_count"):
        parameters.validate_for_records({"pdv": _record(sample_count=1024)})
    assert parameters.window_length_samples == 2048


def test_normalized_non_override_uses_exact_base_value() -> None:
    parameters = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE,
        base_vacuum_wavelength_m=1.55e-6,
        overrides=AnalysisParameterOverrides(
            vacuum_wavelength_m=1550.0e-9,
            nfft=8192,
        ),
    )
    assert parameters.vacuum_wavelength_m == 1.55e-6
    assert dict(parameters.custom_overrides) == {"nfft": 8192}
