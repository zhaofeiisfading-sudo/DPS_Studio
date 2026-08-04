from __future__ import annotations

from pathlib import Path

import numpy as np

from dps_studio.core import (
    BALANCED_PROFILE,
    HIGH_FREQUENCY_RESOLUTION_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import RidgeCorridorConstraint
from dps_studio.core.workflow import (
    analyze_profile,
    analyze_stft_results,
    compute_profile_stfts,
)


def _records(source_path: Path) -> dict[str, SignalRecord]:
    sample_rate_hz = 40.0e9
    time_s = np.arange(4096, dtype=np.float64) / sample_rate_hz
    return {
        name: SignalRecord(
            time_s,
            np.sin(2.0 * np.pi * frequency_hz * time_s),
            source_path=source_path,
        )
        for name, frequency_hz in (("a", 0.63e9), ("b", 0.68e9))
    }


def test_cached_stft_automatic_is_exactly_the_one_click_workflow(
    tmp_path: Path,
) -> None:
    records = _records(tmp_path / "source.csv")
    one_click = analyze_profile(
        records,
        profile=BALANCED_PROFILE,
        analysis_start_time_s=15.0e-9,
        analysis_end_time_s=85.0e-9,
        vacuum_wavelength_m=1550.0e-9,
    )
    stft_results = compute_profile_stfts(records, profile=BALANCED_PROFILE)
    staged = analyze_stft_results(
        stft_results,
        minimum_frequency_hz=BALANCED_PROFILE.minimum_frequency_hz,
        maximum_frequency_hz=BALANCED_PROFILE.maximum_frequency_hz,
        analysis_start_time_s=15.0e-9,
        analysis_end_time_s=85.0e-9,
        vacuum_wavelength_m=1550.0e-9,
        profile_name=BALANCED_PROFILE.profile_id.value,
    )

    for channel_name in records:
        assert staged[channel_name].stft_result is stft_results[channel_name]
        for left, right in (
            (staged[channel_name].stft_result.spectrum, one_click[channel_name].stft_result.spectrum),
            (staged[channel_name].ridge_result.frequency_hz, one_click[channel_name].ridge_result.frequency_hz),
            (
                staged[channel_name].refined_result.refined_frequency_hz,
                one_click[channel_name].refined_result.refined_frequency_hz,
            ),
            (
                staged[channel_name].signal_detection_result.refined_frequency_hz,
                one_click[channel_name].signal_detection_result.refined_frequency_hz,
            ),
            (
                staged[channel_name].signal_detection_result.apparent_velocity_m_s,
                one_click[channel_name].signal_detection_result.apparent_velocity_m_s,
            ),
        ):
            np.testing.assert_array_equal(left, right)


def test_guided_domain_is_local_nan_and_never_falls_back_to_automatic(
    tmp_path: Path,
) -> None:
    records = {"a": _records(tmp_path / "source.csv")["a"]}
    stft_results = compute_profile_stfts(records, profile=BALANCED_PROFILE)
    time_s = stft_results["a"].time_s
    constraint = RidgeCorridorConstraint(
        control_times_s=np.array([time_s[5], time_s[-6]]),
        control_frequencies_hz=np.array([0.63e9, 0.63e9]),
        half_width_hz=70.0e6,
    )
    guided = analyze_stft_results(
        stft_results,
        minimum_frequency_hz=BALANCED_PROFILE.minimum_frequency_hz,
        maximum_frequency_hz=BALANCED_PROFILE.maximum_frequency_hz,
        analysis_start_time_s=float(time_s[1]),
        analysis_end_time_s=float(time_s[-2]),
        vacuum_wavelength_m=1550.0e-9,
        ridge_constraints={"a": constraint},
    )["a"]
    outside = (time_s < constraint.start_time_s) | (time_s > constraint.end_time_s)
    assert np.isnan(guided.ridge_result.frequency_hz[outside]).all()
    assert np.isnan(
        guided.signal_detection_result.refined_frequency_hz[outside]
    ).all()
    assert np.isnan(
        guided.signal_detection_result.apparent_velocity_m_s[outside]
    ).all()
    assert guided.signal_detection_result.analysis_start_time_s == (
        constraint.start_time_s
    )
    assert guided.signal_detection_result.analysis_end_time_s == constraint.end_time_s


def test_formal_profiles_preserve_old_values_and_add_one_audited_long_window() -> None:
    assert (
        BALANCED_PROFILE.window_length_samples,
        BALANCED_PROFILE.overlap_samples,
        BALANCED_PROFILE.hop_samples,
        BALANCED_PROFILE.nfft,
    ) == (768, 640, 128, 4096)
    assert (
        HIGH_TIME_RESOLUTION_PROFILE.window_length_samples,
        HIGH_TIME_RESOLUTION_PROFILE.overlap_samples,
        HIGH_TIME_RESOLUTION_PROFILE.hop_samples,
        HIGH_TIME_RESOLUTION_PROFILE.nfft,
    ) == (512, 384, 128, 4096)
    assert (
        HIGH_FREQUENCY_RESOLUTION_PROFILE.window_length_samples,
        HIGH_FREQUENCY_RESOLUTION_PROFILE.overlap_samples,
        HIGH_FREQUENCY_RESOLUTION_PROFILE.hop_samples,
        HIGH_FREQUENCY_RESOLUTION_PROFILE.nfft,
    ) == (1024, 896, 128, 4096)
    assert HIGH_FREQUENCY_RESOLUTION_PROFILE.minimum_frequency_hz == 0.05e9
    assert HIGH_FREQUENCY_RESOLUTION_PROFILE.maximum_frequency_hz == 2.0e9

