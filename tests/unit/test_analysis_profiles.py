from dataclasses import FrozenInstanceError

import pytest

from dps_studio.core import (
    BALANCED_PROFILE,
    DEFAULT_ANALYSIS_PROFILE,
    DEFAULT_OUTPUT_MODE,
    HIGH_FREQUENCY_RESOLUTION_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
    VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE,
    VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE,
    AnalysisProfile,
    AnalysisProfileId,
    OutputMode,
    get_analysis_profile,
)


def test_formal_profiles_have_exact_parameters() -> None:
    assert BALANCED_PROFILE.profile_id is AnalysisProfileId.BALANCED
    assert BALANCED_PROFILE.display_name == "Balanced"
    assert BALANCED_PROFILE.window_name == "hann"
    assert BALANCED_PROFILE.window_length_samples == 768
    assert BALANCED_PROFILE.overlap_samples == 640
    assert BALANCED_PROFILE.hop_samples == 128
    assert BALANCED_PROFILE.nfft == 4096
    assert BALANCED_PROFILE.minimum_frequency_hz == 0.05e9
    assert BALANCED_PROFILE.maximum_frequency_hz == 2.0e9
    assert (
        BALANCED_PROFILE.ridge_refinement
        == "log_magnitude_three_point_quadratic"
    )

    assert (
        HIGH_TIME_RESOLUTION_PROFILE.profile_id
        is AnalysisProfileId.HIGH_TIME_RESOLUTION
    )
    assert HIGH_TIME_RESOLUTION_PROFILE.display_name == "High time resolution"
    assert HIGH_TIME_RESOLUTION_PROFILE.window_name == "hann"
    assert HIGH_TIME_RESOLUTION_PROFILE.window_length_samples == 512
    assert HIGH_TIME_RESOLUTION_PROFILE.overlap_samples == 384
    assert HIGH_TIME_RESOLUTION_PROFILE.hop_samples == 128
    assert HIGH_TIME_RESOLUTION_PROFILE.nfft == 4096
    assert HIGH_TIME_RESOLUTION_PROFILE.minimum_frequency_hz == 0.05e9
    assert HIGH_TIME_RESOLUTION_PROFILE.maximum_frequency_hz == 2.0e9

    assert (
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE.profile_id
        is AnalysisProfileId.VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL
    )
    assert (
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE.window_length_samples,
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE.overlap_samples,
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE.hop_samples,
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE.nfft,
    ) == (256, 128, 128, 4096)
    assert (
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE.profile_id
        is AnalysisProfileId.VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL
    )
    assert (
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE.window_length_samples,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE.overlap_samples,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE.hop_samples,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE.nfft,
    ) == (2048, 1920, 128, 4096)
    for profile in (
        HIGH_FREQUENCY_RESOLUTION_PROFILE,
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE,
    ):
        assert profile.minimum_frequency_hz == 0.05e9
        assert profile.maximum_frequency_hz == 2.0e9
        assert profile.hop_samples == profile.window_length_samples - profile.overlap_samples


def test_defaults_are_balanced_production_and_profiles_are_identity_objects() -> None:
    assert DEFAULT_ANALYSIS_PROFILE is BALANCED_PROFILE
    assert DEFAULT_OUTPUT_MODE is OutputMode.PRODUCTION
    assert get_analysis_profile("balanced") is BALANCED_PROFILE
    assert (
        get_analysis_profile(AnalysisProfileId.HIGH_TIME_RESOLUTION)
        is HIGH_TIME_RESOLUTION_PROFILE
    )
    assert (
        get_analysis_profile(
            AnalysisProfileId.VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL
        )
        is VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE
    )


def test_profiles_are_frozen_identity_dataclasses() -> None:
    with pytest.raises(FrozenInstanceError):
        BALANCED_PROFILE.nfft = 8192  # type: ignore[misc]
    assert BALANCED_PROFILE == BALANCED_PROFILE
    assert BALANCED_PROFILE != AnalysisProfile(
        profile_id=AnalysisProfileId.BALANCED,
        display_name="Balanced",
        window_name="hann",
        window_length_samples=768,
        overlap_samples=640,
        hop_samples=128,
        nfft=4096,
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=2.0e9,
        ridge_refinement="log_magnitude_three_point_quadratic",
        tradeoff_note="same values, distinct identity",
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "error_type"),
    [
        ("window_length_samples", True, TypeError),
        ("overlap_samples", True, TypeError),
        ("hop_samples", True, TypeError),
        ("nfft", True, TypeError),
        ("minimum_frequency_hz", True, TypeError),
        ("maximum_frequency_hz", True, TypeError),
        ("hop_samples", 127, ValueError),
    ],
)
def test_invalid_profile_values_are_rejected_without_coercion(
    field_name: str,
    invalid_value: object,
    error_type: type[Exception],
) -> None:
    values: dict[str, object] = {
        "profile_id": AnalysisProfileId.BALANCED,
        "display_name": "Balanced",
        "window_name": "hann",
        "window_length_samples": 768,
        "overlap_samples": 640,
        "hop_samples": 128,
        "nfft": 4096,
        "minimum_frequency_hz": 0.1e9,
        "maximum_frequency_hz": 2.0e9,
        "ridge_refinement": "log_magnitude_three_point_quadratic",
        "tradeoff_note": "test",
    }
    values[field_name] = invalid_value
    with pytest.raises(error_type):
        AnalysisProfile(**values)  # type: ignore[arg-type]


def test_invalid_profile_identifier_is_explicit() -> None:
    with pytest.raises(ValueError, match="Unknown analysis profile"):
        get_analysis_profile("automatic")
    with pytest.raises(TypeError):
        get_analysis_profile(True)  # type: ignore[arg-type]


def test_high_time_profile_is_not_named_or_described_as_high_accuracy() -> None:
    assert "high accuracy" not in HIGH_TIME_RESOLUTION_PROFILE.display_name.lower()
    assert "higher-accuracy claim" in HIGH_TIME_RESOLUTION_PROFILE.tradeoff_note
    assert "frequency stability" in HIGH_TIME_RESOLUTION_PROFILE.tradeoff_note


def test_experimental_profiles_describe_tradeoffs_without_accuracy_claims() -> None:
    for profile in (
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE,
    ):
        assert "Experimental" in profile.display_name
        assert "higher-accuracy claim" not in profile.tradeoff_note
