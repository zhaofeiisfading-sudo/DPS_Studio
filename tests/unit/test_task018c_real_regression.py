from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from pathlib import Path

import pytest

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics import convert_ridge_to_apparent_velocity
from dps_studio.core.ridge import (
    AutomaticRidgeExtractionMode,
    RidgeResult,
    RidgeSelectionOrigin,
)
from dps_studio.core.workflow import analyze_profile, load_workflow_config


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _analyze(mode: AutomaticRidgeExtractionMode):
    configuration = load_workflow_config(
        REPOSITORY_ROOT / "configs" / "pdv_studio_defaults.toml",
        repository_root=REPOSITORY_ROOT,
    )
    source = REPOSITORY_ROOT / "data" / "raw" / "20260630-1.csv"
    loaded = read_delimited_signals(
        source,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    )
    start_s = max(record.start_time_s for record in loaded.records.values())
    end_s = min(record.end_time_s for record in loaded.records.values())
    analyses = analyze_profile(
        loaded.records,
        profile=configuration.analysis.default_profile,
        analysis_start_time_s=start_s,
        analysis_end_time_s=end_s,
        manual_event_reference_time_s=None,
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        automatic_ridge_selection_config=replace(
            configuration.automatic_ridge_selection,
            mode=mode,
        ),
        background_guard_window_scale=(
            configuration.quality.background_guard_window_scale
        ),
        minimum_background_bin_count=(
            configuration.quality.minimum_background_bin_count
        ),
    )
    return analyses["pdv_channel_2"], source


def test_frame_1015_is_formally_promoted_and_legacy_remains_recoverable() -> None:
    continuity, source = _analyze(
        AutomaticRidgeExtractionMode.CONTINUITY_ASSISTED
    )
    source_hash = _sha256(source)
    legacy, _ = _analyze(AutomaticRidgeExtractionMode.LEGACY_STRONGEST_PEAK)
    assert _sha256(source) == source_hash

    frame = 1015
    assert legacy.refined_result.refined_frequency_hz[frame] == pytest.approx(
        508.751027843821e6
    )
    assert math.isnan(legacy.refined_velocity_m_s[frame])
    assert continuity.refined_result.refined_frequency_hz[frame] == pytest.approx(
        211.379347724094e6
    )
    assert continuity.signal_detection_result.signal_states[frame].value == "measured"
    assert continuity.automatic_ridge_selection_result.origins[frame] is (
        RidgeSelectionOrigin.CONTINUITY_ASSISTED_ALTERNATIVE
    )
    assert continuity.automatic_ridge_selection_result.selected_candidate_rank[
        frame
    ] == 2

    one_frame_ridge = RidgeResult(
        time_s=continuity.ridge_result.time_s[frame : frame + 1],
        frequency_hz=continuity.refined_result.refined_frequency_hz[
            frame : frame + 1
        ],
        peak_magnitude=continuity.ridge_result.peak_magnitude[frame : frame + 1],
        quality_flags=(continuity.ridge_result.quality_flags[frame],),
        minimum_frequency_hz=continuity.ridge_result.minimum_frequency_hz,
        maximum_frequency_hz=continuity.ridge_result.maximum_frequency_hz,
        event_start_time_s=None,
        analysis_end_time_s=None,
        source_path=continuity.ridge_result.source_path,
    )
    expected = convert_ridge_to_apparent_velocity(
        one_frame_ridge,
        vacuum_wavelength_m=(
            continuity.discrete_velocity_result.vacuum_wavelength_m
        ),
    ).apparent_velocity_m_s[0]
    assert continuity.refined_velocity_m_s[frame] == pytest.approx(expected)
    assert continuity.refined_velocity_m_s[frame] == pytest.approx(
        163.81899448617307
    )
    assert (
        continuity.stream_event_candidates.primary_candidate_time_s
        == legacy.stream_event_candidates.primary_candidate_time_s
    )
