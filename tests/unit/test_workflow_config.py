from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from dps_studio.core import (
    BALANCED_PROFILE,
    HIGH_FREQUENCY_RESOLUTION_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
    VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE,
    VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE,
)
from dps_studio.core.workflow import (
    WorkflowConfigurationError,
    load_workflow_config,
)


def _valid_toml() -> str:
    return """
[input]
path = "data/source.csv"
time_column = 0
delimiter = ","
has_header = false
encoding = "utf-8"
time_scale = 1.0
[input.voltage_columns]
pdv_channel_1 = 1
pdv_channel_2 = 2
[input.voltage_scales]
pdv_channel_1 = 1.0
pdv_channel_2 = 1.0
[analysis]
default_profile = "balanced"
profiles = ["very_high_time_resolution_experimental", "high_time_resolution", "balanced", "high_frequency_resolution", "very_high_frequency_resolution_experimental"]
analysis_start_time_s = 5.54650e-4
analysis_end_time_s = 5.5545e-4
manual_event_reference_time_s = 5.54668e-4
vacuum_wavelength_m = 1.55e-6
[quality]
background_guard_window_scale = 2.0
minimum_background_bin_count = 2
minimum_peak_to_background_db = 10.0
minimum_peak_to_competitor_db = 3.0
peak_exclusion_half_width_bins = 12
minimum_consecutive_frames = 3
minimum_cycles_in_window = 1.0
enabled = true
[automatic_ridge_selection]
mode = "continuity_assisted"
top_k_candidates = 3
continuity_reselection_enabled = true
minimum_candidate_peak_to_background_db = 10.0
minimum_candidate_relative_to_strongest_db = -6.0
[event_candidate]
minimum_segment_frames = 8
minimum_segment_duration_s = 2.0e-8
maximum_adjacent_frequency_step_hz = 1.0e8
[event_consensus]
channel_start_time_tolerance_s = 2.5e-8
minimum_interval_overlap_fraction = 0.5
channel_start_frequency_tolerance_hz = 1.5e8
cross_profile_time_tolerance_s = 2.5e-8
[plot]
relative_db_floor = -60.0
analysis_display_minimum_frequency_hz = 0.0
analysis_display_maximum_frequency_hz = 2.0e9
event_detail_before_s = 1.0e-7
event_detail_after_s = 2.0e-7
assume_pre_event_zero_for_display = false
pre_event_display_velocity_m_s = 0.0
[output]
root = "outputs/production_runs"
"""


def _load(tmp_path: Path, text: str) -> object:
    config_path = tmp_path / "config.toml"
    config_path.write_text(text, encoding="utf-8")
    return load_workflow_config(config_path, repository_root=tmp_path)


def test_toml_loads_relative_paths_profiles_and_immutable_mappings(
    tmp_path: Path,
) -> None:
    configuration = _load(tmp_path, _valid_toml())
    assert configuration.input.path == (tmp_path / "data" / "source.csv").resolve()
    assert configuration.output.root == (
        tmp_path / "outputs" / "production_runs"
    ).resolve()
    assert configuration.analysis.profiles == (
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE,
        HIGH_TIME_RESOLUTION_PROFILE,
        BALANCED_PROFILE,
        HIGH_FREQUENCY_RESOLUTION_PROFILE,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE,
    )
    assert configuration.analysis.default_profile is BALANCED_PROFILE
    assert configuration.analysis.manual_event_reference_time_s == 5.54668e-4
    assert configuration.analysis.event_reference_time_s == 5.54668e-4
    assert configuration.analysis.event_start_time_s == 5.54668e-4
    assert configuration.quality.signal_detection.minimum_consecutive_frames == 3
    assert configuration.automatic_ridge_selection.mode.value == "continuity_assisted"
    assert configuration.automatic_ridge_selection.top_k_candidates == 3
    assert configuration.automatic_ridge_selection.recovery_tolerance_hz is None
    assert configuration.event_candidate.minimum_segment_frames == 8
    assert configuration.event_candidate.minimum_median_peak_to_background_db is None
    assert configuration.event_consensus.minimum_interval_overlap_fraction == 0.5
    assert configuration.plot.assume_pre_event_zero_for_display is False
    assert configuration.plot.pre_event_display_velocity_m_s == 0.0
    with pytest.raises(FrozenInstanceError):
        configuration.analysis.vacuum_wavelength_m = 1064e-9  # type: ignore[misc]
    with pytest.raises(TypeError):
        configuration.input.voltage_columns["pdv_channel_1"] = 9  # type: ignore[index]
    columns = dict(configuration.input.voltage_columns)
    columns["pdv_channel_1"] = 9
    assert configuration.input.voltage_columns["pdv_channel_1"] == 1


def test_explicit_default_profile_is_loaded_and_validated(tmp_path: Path) -> None:
    text = _valid_toml().replace(
        'default_profile = "balanced"',
        'default_profile = "high_time_resolution"',
        1,
    )
    configuration = _load(tmp_path, text)
    assert configuration.analysis.default_profile is HIGH_TIME_RESOLUTION_PROFILE

    invalid = text.replace(
        'default_profile = "high_time_resolution"',
        'default_profile = "unknown"',
        1,
    )
    with pytest.raises(
        WorkflowConfigurationError,
        match=r"analysis\.default_profile",
    ):
        _load(tmp_path, invalid)


@pytest.mark.parametrize(
    ("old", "new", "field_name"),
    [
        (
            'profiles = ["very_high_time_resolution_experimental", "high_time_resolution", "balanced", "high_frequency_resolution", "very_high_frequency_resolution_experimental"]',
            'profiles = ["balanced"]',
            "analysis.profiles",
        ),
        ("pdv_channel_1 = 1\npdv_channel_2 = 2", "pdv_channel_1 = -1\npdv_channel_2 = 2", "input.voltage_columns.pdv_channel_1"),
        ("pdv_channel_1 = 1\npdv_channel_2 = 2", "pdv_channel_1 = 1\npdv_channel_2 = 1", "input.voltage_columns"),
        ("time_column = 0", "time_column = 1", "input.time_column"),
        ("vacuum_wavelength_m = 1.55e-6", "vacuum_wavelength_m = 0.0", "analysis.vacuum_wavelength_m"),
        ("analysis_start_time_s = 5.54650e-4", "analysis_start_time_s = 5.5550e-4", "analysis.analysis_start_time_s"),
        ("background_guard_window_scale = 2.0", "background_guard_window_scale = 0.0", "quality.background_guard_window_scale"),
        ("minimum_background_bin_count = 2", "minimum_background_bin_count = 0", "quality.minimum_background_bin_count"),
        ("minimum_peak_to_background_db = 10.0", "minimum_peak_to_background_db = nan", "quality.minimum_peak_to_background_db"),
        ("minimum_peak_to_competitor_db = 3.0", "minimum_peak_to_competitor_db = -1.0", "quality.minimum_peak_to_competitor_db"),
        ("peak_exclusion_half_width_bins = 12", "peak_exclusion_half_width_bins = -1", "quality.peak_exclusion_half_width_bins"),
        ("minimum_consecutive_frames = 3", "minimum_consecutive_frames = 0", "quality.minimum_consecutive_frames"),
        ("minimum_cycles_in_window = 1.0", "minimum_cycles_in_window = 0.0", "quality.minimum_cycles_in_window"),
        ('mode = "continuity_assisted"', 'mode = "unknown"', "automatic_ridge_selection.mode"),
        ("top_k_candidates = 3", "top_k_candidates = 0", "automatic_ridge_selection.top_k_candidates"),
        ("minimum_candidate_peak_to_background_db = 10.0", "minimum_candidate_peak_to_background_db = nan", "automatic_ridge_selection.minimum_candidate_peak_to_background_db"),
        ("minimum_segment_frames = 8", "minimum_segment_frames = 0", "event_candidate.minimum_segment_frames"),
        ("minimum_segment_duration_s = 2.0e-8", "minimum_segment_duration_s = -1.0", "event_candidate.minimum_segment_duration_s"),
        ("maximum_adjacent_frequency_step_hz = 1.0e8", "maximum_adjacent_frequency_step_hz = 0.0", "event_candidate.maximum_adjacent_frequency_step_hz"),
        ("channel_start_time_tolerance_s = 2.5e-8", "channel_start_time_tolerance_s = 0.0", "event_consensus.channel_start_time_tolerance_s"),
        ("minimum_interval_overlap_fraction = 0.5", "minimum_interval_overlap_fraction = 1.1", "event_consensus.minimum_interval_overlap_fraction"),
        ("channel_start_frequency_tolerance_hz = 1.5e8", "channel_start_frequency_tolerance_hz = 0.0", "event_consensus.channel_start_frequency_tolerance_hz"),
        ("cross_profile_time_tolerance_s = 2.5e-8", "cross_profile_time_tolerance_s = 0.0", "event_consensus.cross_profile_time_tolerance_s"),
        ("analysis_display_maximum_frequency_hz = 2.0e9", "analysis_display_maximum_frequency_hz = 0.0", "plot.analysis_display_maximum_frequency_hz"),
        ("event_detail_before_s = 1.0e-7", "event_detail_before_s = -1.0e-7", "plot.event_detail_before_s"),
        ("pre_event_display_velocity_m_s = 0.0", "pre_event_display_velocity_m_s = nan", "plot.pre_event_display_velocity_m_s"),
    ],
)
def test_invalid_config_reports_specific_field(
    tmp_path: Path,
    old: str,
    new: str,
    field_name: str,
) -> None:
    text = _valid_toml().replace(old, new, 1)
    with pytest.raises(WorkflowConfigurationError, match=field_name.replace(".", r"\.")):
        _load(tmp_path, text)
