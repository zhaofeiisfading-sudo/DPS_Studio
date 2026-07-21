from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dps_studio.core import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.core.models import SignalRecord


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from compare_real_ridge_refinement import _analyze_configuration  # noqa: E402
from production_outputs import (  # noqa: E402
    INTERPRETATION_GUARDS,
    PRODUCTION_FILENAMES,
    run_production_outputs,
)


SAMPLE_RATE_HZ = 40.0e9
START_TIME_S = 554.65e-6
EVENT_START_TIME_S = 554.662e-6
ANALYSIS_END_TIME_S = 554.69e-6
WAVELENGTH_M = 1550e-9


def _records(source_path: Path) -> dict[str, SignalRecord]:
    sample_count = 1536
    relative_time_s = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE_HZ
    time_s = START_TIME_S + relative_time_s
    records = {}
    for channel_name, frequency_hz in (
        ("pdv_channel_1", 0.63e9),
        ("pdv_channel_2", 0.66e9),
    ):
        voltage_v = np.sin(2.0 * np.pi * frequency_hz * relative_time_s)
        records[channel_name] = SignalRecord(time_s, voltage_v, source_path=source_path)
    return records


def test_production_writes_exact_practical_files_and_manifest(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_text("deterministic synthetic source\n", encoding="utf-8")
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    output_directory = tmp_path / "production"

    paths = run_production_outputs(
        output_directory,
        _records(source_path),
        profile=BALANCED_PROFILE,
        vacuum_wavelength_m=WAVELENGTH_M,
        event_start_time_s=EVENT_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        source_path=source_path,
        source_sha256=source_sha256,
    )

    assert len(paths) == 8
    assert {path.name for path in paths} == set(PRODUCTION_FILENAMES)
    assert {path.name for path in output_directory.iterdir()} == set(
        PRODUCTION_FILENAMES
    )
    assert not any("diagnostic" in path.name for path in paths)
    assert not any("related_frequency" in path.name for path in paths)
    assert not any("legacy" in path.name for path in paths)

    manifest = json.loads((output_directory / "run_manifest.json").read_text())
    assert manifest["profile_id"] == "balanced"
    assert manifest["output_mode"] == "production"
    assert manifest["wavelength_m"] == WAVELENGTH_M
    assert manifest["event_start_time_s"] == EVENT_START_TIME_S
    assert manifest["analysis_end_time_s"] == ANALYSIS_END_TIME_S
    assert manifest["sample_rate_hz"] == pytest.approx(SAMPLE_RATE_HZ, rel=1.0e-9)
    assert manifest["source_path"] == str(source_path)
    assert manifest["source_sha256"] == source_sha256
    assert set(manifest["versions"]) == {"python", "numpy", "scipy", "dps-studio"}
    assert isinstance(manifest["git_head"], str)
    assert isinstance(manifest["git_worktree_dirty"], bool)
    assert set(manifest["generated_files"]) == set(PRODUCTION_FILENAMES)
    assert manifest["interpretation_guards"] == list(INTERPRETATION_GUARDS)


def test_csv_distinguishes_display_zero_from_measurement_and_keeps_channels_separate(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_text("deterministic synthetic source\n", encoding="utf-8")
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    output_directory = tmp_path / "production"
    run_production_outputs(
        output_directory,
        _records(source_path),
        profile=BALANCED_PROFILE,
        vacuum_wavelength_m=WAVELENGTH_M,
        event_start_time_s=EVENT_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        source_path=source_path,
        source_sha256=source_sha256,
    )

    first = pd.read_csv(output_directory / "pdv_channel_1_apparent_velocity.csv")
    second = pd.read_csv(output_directory / "pdv_channel_2_apparent_velocity.csv")
    required_columns = {
        "time_s",
        "time_relative_to_event_s",
        "refined_frequency_hz",
        "apparent_velocity_m_s",
        "display_velocity_m_s",
        "velocity_origin",
        "quality_flag",
        "refinement_status",
        "peak_to_background_db",
        "peak_to_competitor_db",
        "continuity_status",
        "frequency_step_hz",
        "frequency_slope_hz_s",
    }
    assert set(first.columns) == required_columns
    pre_event = first["quality_flag"].eq("pre_event")
    assert pre_event.any()
    assert first.loc[pre_event, "apparent_velocity_m_s"].isna().all()
    assert first.loc[pre_event, "display_velocity_m_s"].eq(0.0).all()
    assert first.loc[pre_event, "velocity_origin"].eq(
        "assumed_pre_event_zero"
    ).all()
    measured = first["velocity_origin"].eq("refined_candidate_measurement")
    assert first.loc[measured, "apparent_velocity_m_s"].notna().all()
    assert not np.array_equal(
        first["apparent_velocity_m_s"].to_numpy(),
        second["apparent_velocity_m_s"].to_numpy(),
        equal_nan=True,
    )
    summary = pd.read_csv(output_directory / "quality_summary.csv")
    assert summary["channel_name"].tolist() == ["pdv_channel_1", "pdv_channel_2"]
    assert "selected_channel" not in summary.columns


def test_high_time_analysis_does_not_mutate_balanced_results(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_text("deterministic synthetic source\n", encoding="utf-8")
    records = _records(source_path)
    balanced_before, _ = _analyze_configuration(
        records,
        BALANCED_PROFILE.window_length_samples,
        BALANCED_PROFILE.overlap_samples,
        BALANCED_PROFILE.nfft,
    )
    high_time, _ = _analyze_configuration(
        records,
        HIGH_TIME_RESOLUTION_PROFILE.window_length_samples,
        HIGH_TIME_RESOLUTION_PROFILE.overlap_samples,
        HIGH_TIME_RESOLUTION_PROFILE.nfft,
    )
    balanced_after, _ = _analyze_configuration(
        records,
        BALANCED_PROFILE.window_length_samples,
        BALANCED_PROFILE.overlap_samples,
        BALANCED_PROFILE.nfft,
    )

    for channel_name in balanced_before:
        np.testing.assert_array_equal(
            balanced_before[channel_name].stft_result.spectrum,
            balanced_after[channel_name].stft_result.spectrum,
        )
        np.testing.assert_array_equal(
            balanced_before[channel_name].refined_result.refined_frequency_hz,
            balanced_after[channel_name].refined_result.refined_frequency_hz,
        )
        assert high_time[channel_name].stft_result.window_length_samples == 512
        assert balanced_after[channel_name].stft_result.window_length_samples == 768
