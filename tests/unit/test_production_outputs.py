from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np
import pandas as pd
import pytest

from dps_studio.core import (
    BALANCED_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
    EventCandidateConfig,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import analyze_profile, load_workflow_config


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from production_outputs import (  # noqa: E402
    CHANNEL_FILENAMES,
    CHANNEL_PLOT_FILENAMES,
    COMPARISON_FILENAMES,
    DETAILED_DIAGNOSTIC_FILENAMES,
    INTERPRETATION_GUARDS,
    LOWER_BOUND_ARGMAX_NOTE,
    PROFILE_FILENAMES,
    QUALITY_UNFILTERED_PREVIEW_LABEL,
    THRESHOLD_CALIBRATION_CANDIDATES_DB,
    THRESHOLD_CALIBRATION_PROVENANCE,
    _build_full_range_preview,
    _build_reviewed_velocity_series,
    _production_root_entries,
    _save_apparent_velocity_full_overview,
    _save_apparent_velocity_full_time_reviewed,
    _simple_export_filename,
    _simple_export_velocity_m_s,
    _select_threshold_candidate,
    _velocity_plot_series,
    _write_simple_velocity_csv,
    run_production_outputs,
)


SAMPLE_RATE_HZ = 40.0e9
START_TIME_S = 554.65e-6
EVENT_START_TIME_S = 554.668e-6
ANALYSIS_END_TIME_S = 554.673e-6
WAVELENGTH_M = 1550e-9
REPOSITORY_OUTPUTS = Path(__file__).resolve().parents[2] / "outputs"


def _output_file_snapshot() -> tuple[tuple[str, int], ...]:
    if not REPOSITORY_OUTPUTS.exists():
        return ()
    return tuple(
        sorted(
            (
                str(path.relative_to(REPOSITORY_OUTPUTS)).replace("\\", "/"),
                path.stat().st_size,
            )
            for path in REPOSITORY_OUTPUTS.rglob("*")
            if path.is_file()
        )
    )


@pytest.fixture(scope="module", autouse=True)
def repository_outputs_are_not_polluted() -> object:
    before = _output_file_snapshot()
    yield
    assert _output_file_snapshot() == before


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


def _config_text() -> str:
    return f"""
[input]
path = "source.csv"
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
profiles = ["balanced", "high_time_resolution"]
analysis_start_time_s = {START_TIME_S!r}
analysis_end_time_s = {ANALYSIS_END_TIME_S!r}
manual_event_reference_time_s = {EVENT_START_TIME_S!r}
vacuum_wavelength_m = {WAVELENGTH_M!r}
[quality]
background_guard_window_scale = 2.0
minimum_background_bin_count = 2
minimum_peak_to_background_db = 10.0
minimum_peak_to_competitor_db = 3.0
peak_exclusion_half_width_bins = 12
minimum_consecutive_frames = 3
minimum_cycles_in_window = 1.0
enabled = true
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
[output]
root = "outputs"
"""


@pytest.fixture(scope="module")
def production_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("dual_profile_production")
    source_path = root / "source.csv"
    source_path.write_text("deterministic synthetic source\n", encoding="utf-8")
    config_path = root / "config.toml"
    config_path.write_text(_config_text(), encoding="utf-8")
    configuration = load_workflow_config(config_path, repository_root=root)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    output_directory = root / "run_20260723_120000"
    paths = run_production_outputs(
        output_directory,
        _records(source_path),
        configuration=configuration,
        source_sha256=source_sha256,
    )
    assert len(paths) == 59
    return output_directory


@pytest.fixture(scope="module")
def formal_analyses(
    production_run: Path,
) -> tuple[object, dict[str, object]]:
    root = production_run.parent
    configuration = load_workflow_config(
        root / "config.toml",
        repository_root=root,
    )
    analyses = {
        profile.profile_id.value: analyze_profile(
            _records(root / "source.csv"),
            profile=profile,
            analysis_start_time_s=configuration.analysis.analysis_start_time_s,
            analysis_end_time_s=configuration.analysis.analysis_end_time_s,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
            detection_config=configuration.quality.signal_detection,
            event_candidate_config=configuration.event_candidate,
            background_guard_window_scale=(
                configuration.quality.background_guard_window_scale
            ),
            minimum_background_bin_count=(
                configuration.quality.minimum_background_bin_count
            ),
            assume_pre_event_zero_for_display=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
        )
        for profile in configuration.analysis.profiles
    }
    return configuration, analyses


def test_production_writes_exact_dual_profile_tree_and_manifest(
    production_run: Path,
) -> None:
    assert {path.name for path in production_run.iterdir()} == set(
        _production_root_entries(
            (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)
        )
    )
    assert {path.name for path in (production_run / "comparisons").iterdir()} == set(
        COMPARISON_FILENAMES
    )
    profile_shapes = []
    for profile_name in ("balanced", "high_time_resolution"):
        profile_directory = production_run / profile_name
        assert {path.name for path in profile_directory.iterdir()} == {
            "pdv_channel_1",
            "pdv_channel_2",
            *PROFILE_FILENAMES,
        }
        profile_shapes.append(
            sorted(
                str(path.relative_to(profile_directory)).replace("\\", "/")
                for path in profile_directory.rglob("*")
                if path.is_file()
            )
        )
        for channel_name in ("pdv_channel_1", "pdv_channel_2"):
            assert {
                path.name for path in (profile_directory / channel_name).iterdir()
            } == set(CHANNEL_FILENAMES)
    assert profile_shapes[0] == profile_shapes[1]
    assert not list(production_run.rglob("*two_channel*velocity*.png"))

    manifest = json.loads((production_run / "run_manifest.json").read_text())
    assert manifest["profiles"] == ["balanced", "high_time_resolution"]
    assert manifest["root_entries"] == list(
        _production_root_entries(
            (BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE)
        )
    )
    assert manifest["output_contract"] == "dual-profile-task013c-r-v1"
    assert len(manifest["generated_files"]) == 59
    assert manifest["simple_exports"]["display_or_preview_values_used"] is False
    assert manifest["simple_exports"]["all_stft_frames_retained"] is True
    assert manifest["simple_exports"]["columns"] == [
        "time_s",
        "corrected_velocity_m_s",
    ]
    assert (
        manifest["simple_exports"]["pre_consensus_zero_fill"]
        == "unconditional for every frame"
    )
    assert manifest["simple_exports"]["zero_fill_is_measurement"] is False
    assert manifest["plot"]["reviewed_display"]["same_array_as_simple_export"] is True
    calibration = manifest["quality"]["threshold_calibration"]
    assert calibration["candidate_pairs_db"] == [
        [10.0, 3.0],
        [12.0, 4.0],
        [14.0, 5.0],
        [16.0, 6.0],
    ]
    assert calibration["provenance"] == THRESHOLD_CALIBRATION_PROVENANCE
    assert manifest["interpretation_guards"] == list(INTERPRETATION_GUARDS)
    assert manifest["cross_profile_consensus"]["consensus_event_status"] in {
        "cross_profile_consensus",
        "single_profile_dual_channel_support",
        "profile_time_mismatch",
        "no_profile_consensus",
    }
    assert (
        manifest["measured_semantics"]
        == "MEASURED means spectrally qualified under the configured detection "
        "rules. It does not confirm the physical identity of the selected branch."
    )


def test_csv_keeps_all_frames_and_display_zero_separate_from_measurement(
    production_run: Path,
) -> None:
    required_columns = {
        "time_s",
        "time_relative_to_event_s",
        "coarse_peak_frequency_hz",
        "discrete_frequency_hz",
        "provisional_refined_frequency_hz",
        "refined_frequency_hz",
        "discrete_apparent_velocity_m_s",
        "apparent_velocity_m_s",
        "angle_corrected_apparent_velocity_m_s",
        "corrected_velocity_m_s",
        "display_velocity_m_s",
        "velocity_origin",
        "quality_flag",
        "signal_state",
        "minimum_peak_to_background_threshold_db",
        "minimum_peak_to_competitor_threshold_db",
        "threshold_provenance",
        "measured_semantics",
        "physical_branch_review_status",
        "event_segment_id",
        "event_segment_candidate_eligible",
        "event_segment_rejection_reasons",
        "refinement_status",
        "peak_to_background_db",
        "peak_to_competitor_db",
        "cycles_in_window",
        "peak_is_at_band_boundary",
        "continuity_status",
        "frequency_step_hz",
        "frequency_slope_hz_s",
        "preview_frequency_hz",
        "preview_apparent_velocity_m_s",
        "preview_velocity_origin",
        "preview_quality_flag",
        "preview_signal_state",
        "preview_uses_refined_frequency",
        "preview_is_formal_candidate",
    }
    first = pd.read_csv(
        production_run
        / "balanced"
        / "pdv_channel_1"
        / "apparent_velocity_diagnostics.csv"
    )
    second = pd.read_csv(
        production_run
        / "balanced"
        / "pdv_channel_2"
        / "apparent_velocity_diagnostics.csv"
    )
    manifest = json.loads(
        (production_run / "balanced" / "profile_manifest.json").read_text()
    )
    assert required_columns <= set(first.columns)
    assert len(first) == manifest["channel_summaries"]["pdv_channel_1"][
        "total_frame_count"
    ]
    measured = first["signal_state"].eq("measured")
    outside = first["signal_state"].eq("outside_analysis_window")
    assert measured.any()
    assert first.loc[~measured, "apparent_velocity_m_s"].isna().all()
    assert first["display_velocity_m_s"].equals(first["corrected_velocity_m_s"])
    assert not first["velocity_origin"].eq(
        "assumed_pre_event_zero_display_only"
    ).any()
    assert first.loc[outside, "apparent_velocity_m_s"].isna().all()
    assert first.loc[outside, "display_velocity_m_s"].isna().all()
    assert first.loc[outside, "preview_apparent_velocity_m_s"].notna().all()
    assert first.loc[outside, "preview_is_formal_candidate"].eq(False).all()
    assert first.loc[outside, "preview_quality_flag"].eq(
        "preview_only_outside_formal_window"
    ).all()
    assert not np.array_equal(
        first["apparent_velocity_m_s"].to_numpy(),
        second["apparent_velocity_m_s"].to_numpy(),
        equal_nan=True,
    )
    summary = pd.read_csv(production_run / "balanced" / "quality_summary.csv")
    assert summary["channel_name"].tolist() == ["pdv_channel_1", "pdv_channel_2"]
    assert "selected_channel" not in summary.columns


def test_formal_csv_columns_match_the_unchanged_formal_analysis(
    production_run: Path,
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    _, analyses_by_profile = formal_analyses
    for profile_name, analyses in analyses_by_profile.items():
        for channel_name, analysis in analyses.items():
            frame = pd.read_csv(
                production_run
                / profile_name
                / channel_name
                / "apparent_velocity_diagnostics.csv"
            )
            np.testing.assert_allclose(
                frame["time_s"].to_numpy(),
                analysis.refined_result.time_s,
                rtol=0.0,
                atol=2.0e-17,
            )
            np.testing.assert_allclose(
                frame["apparent_velocity_m_s"].to_numpy(),
                analysis.refined_velocity_m_s,
                rtol=1.0e-15,
                atol=0.0,
                equal_nan=True,
            )
            np.testing.assert_allclose(
                frame["display_velocity_m_s"].to_numpy(),
                analysis.display_velocity_m_s,
                rtol=1.0e-15,
                atol=0.0,
                equal_nan=True,
            )
            assert frame["quality_flag"].tolist() == [
                flag.value for flag in analysis.refined_result.quality_flags
            ]
            np.testing.assert_array_equal(
                frame["apparent_velocity_m_s"].isna().to_numpy(),
                np.isnan(analysis.refined_velocity_m_s),
            )


def test_velocity_plot_series_has_no_default_display_zero_or_bridge(
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    _, analyses_by_profile = formal_analyses
    analysis = analyses_by_profile["balanced"]["pdv_channel_1"]
    series = _velocity_plot_series(analysis)
    assert np.isnan(series.pre_event_velocity_m_s).all()
    assert series.bridge_time_s.size == 0
    assert series.bridge_velocity_m_s.size == 0


def test_preview_covers_full_stft_axis_without_the_formal_time_gate(
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    configuration, analyses_by_profile = formal_analyses
    for profile in configuration.analysis.profiles:
        analysis = analyses_by_profile[profile.profile_id.value]["pdv_channel_1"]
        preview = _build_full_range_preview(
            analysis,
            minimum_frequency_hz=profile.minimum_frequency_hz,
            maximum_frequency_hz=profile.maximum_frequency_hz,
            vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        )
        np.testing.assert_array_equal(preview.time_s, analysis.stft_result.time_s)
        assert np.isfinite(preview.frequency_hz).all()
        assert np.isfinite(preview.apparent_velocity_m_s).all()
        assert (preview.frequency_hz >= 0.05e9).all()
        assert (preview.frequency_hz <= 2.0e9).all()
        formal_finite = np.isfinite(analysis.refined_velocity_m_s)
        assert preview.apparent_velocity_m_s.size > np.count_nonzero(formal_finite)
        outside = np.asarray(
            [
                state is SignalState.OUTSIDE_ANALYSIS_WINDOW
                for state in analysis.signal_detection_result.signal_states
            ]
        )
        assert outside.any()
        assert np.isfinite(preview.apparent_velocity_m_s[outside]).all()
        np.testing.assert_array_equal(
            preview.frequency_hz,
            analysis.ridge_result.frequency_hz,
        )
        np.testing.assert_allclose(
            preview.apparent_velocity_m_s,
            (
                configuration.analysis.vacuum_wavelength_m
                * analysis.ridge_result.frequency_hz
                / 2.0
            ),
            rtol=0.0,
            atol=0.0,
        )
        assert not preview.uses_refined_frequency.any()
        np.testing.assert_array_equal(
            analysis.display_velocity_m_s,
            analysis.corrected_velocity_m_s,
        )


def test_full_band_and_analysis_plot_ranges_are_explicit_and_images_are_readable(
    production_run: Path,
) -> None:
    for profile_name in ("balanced", "high_time_resolution"):
        manifest = json.loads(
            (production_run / profile_name / "profile_manifest.json").read_text()
        )
        assert manifest["search_frequency_range_hz"] == [0.05e9, 2.0e9]
        assert manifest["full_range_preview"]["frequency_range_hz"] == [
            0.05e9,
            2.0e9,
        ]
        assert manifest["full_range_preview"]["formal_quality_gate_applied"] is False
        assert manifest["full_range_preview"]["legend"] == (
            QUALITY_UNFILTERED_PREVIEW_LABEL
        )
        assert manifest["full_range_preview"]["lower_bound_note"] == (
            LOWER_BOUND_ARGMAX_NOTE
        )
        assert "state-layered" in manifest["full_range_preview"]["rendering"]
        assert "no state markers" in (
            manifest["full_range_preview"]["overview_rendering"]
        )
        assert manifest["full_range_preview"]["state_diagnostics_filename"] == (
            "apparent_velocity_state_diagnostics.png"
        )
        assert manifest["analysis_display_frequency_range_hz"] == [0.0, 2.0e9]
        for channel_name in ("pdv_channel_1", "pdv_channel_2"):
            full_range = manifest["full_band_frequency_range_hz_by_channel"][
                channel_name
            ]
            nyquist = manifest["nyquist_frequency_hz_by_channel"][channel_name]
            assert full_range[0] == 0.0
            assert full_range[1] == pytest.approx(nyquist)
            assert full_range[1] == pytest.approx(SAMPLE_RATE_HZ / 2.0, rel=1e-9)
            for filename in CHANNEL_PLOT_FILENAMES:
                image = mpimg.imread(production_run / profile_name / channel_name / filename)
                assert image.ndim == 3
                assert image.shape[0] > 100
                assert image.shape[1] > 100


def test_preview_boundary_is_explicitly_not_zero_and_state_layered(
    production_run: Path,
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (
            production_run
            / "high_time_resolution"
            / "profile_manifest.json"
        ).read_text()
    )
    assert manifest["full_range_preview"]["lower_bound_note"] == (
        "lower-bound argmax is not zero velocity"
    )
    sample_count = 2048
    relative_time_s = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE_HZ
    lower_grid_frequency_hz = 6.0 * SAMPLE_RATE_HZ / 4096.0
    analysis = analyze_profile(
        {
            "pdv_channel_2": SignalRecord(
                START_TIME_S + relative_time_s,
                np.sin(2.0 * np.pi * lower_grid_frequency_hz * relative_time_s),
                source_path=production_run / "boundary-source.csv",
            )
        },
        profile=HIGH_TIME_RESOLUTION_PROFILE,
        vacuum_wavelength_m=WAVELENGTH_M,
    )["pdv_channel_2"]
    preview = _build_full_range_preview(
        analysis,
        minimum_frequency_hz=(
            HIGH_TIME_RESOLUTION_PROFILE.minimum_frequency_hz
        ),
        maximum_frequency_hz=(
            HIGH_TIME_RESOLUTION_PROFILE.maximum_frequency_hz
        ),
        vacuum_wavelength_m=WAVELENGTH_M,
    )
    boundary = np.asarray(
        [
            state is SignalState.PEAK_AT_BAND_BOUNDARY
            for state in analysis.signal_detection_result.signal_states
        ]
    )
    assert boundary.any()
    assert np.isnan(
        analysis.signal_detection_result.apparent_velocity_m_s[boundary]
    ).all()
    assert (preview.apparent_velocity_m_s[boundary] > 0.0).all()
    assert preview.apparent_velocity_m_s[boundary][0] == pytest.approx(
        WAVELENGTH_M * lower_grid_frequency_hz / 2.0
    )
    simple_path = _write_simple_velocity_csv(
        tmp_path,
        "high_time_resolution",
        "pdv_channel_2",
        analysis,
        zero_before_time_s=float(analysis.refined_result.time_s[-1]),
    )
    simple = pd.read_csv(simple_path)
    pre_consensus = analysis.refined_result.time_s < analysis.refined_result.time_s[-1]
    assert np.all(simple.loc[pre_consensus, "corrected_velocity_m_s"] == 0.0)
    assert np.isnan(simple.loc[~pre_consensus, "corrected_velocity_m_s"]).all()


def test_duplicate_apparent_velocity_csv_alias_is_not_generated(
    production_run: Path,
) -> None:
    assert DETAILED_DIAGNOSTIC_FILENAMES == (
        "apparent_velocity_diagnostics.csv",
    )
    for profile_name in ("balanced", "high_time_resolution"):
        for channel_name in ("pdv_channel_1", "pdv_channel_2"):
            channel_directory = production_run / profile_name / channel_name
            assert (channel_directory / "apparent_velocity_diagnostics.csv").is_file()
            assert not (channel_directory / "apparent_velocity.csv").exists()


def test_all_streams_write_primary_overview_reviewed_and_state_diagnostics(
    production_run: Path,
) -> None:
    required = {
        "apparent_velocity_full_overview.png",
        "apparent_velocity_full_time_reviewed.png",
        "apparent_velocity_full_time_formal.png",
        "apparent_velocity_event_detail.png",
        "apparent_velocity_state_diagnostics.png",
        "apparent_velocity_diagnostics.csv",
    }
    for profile_name in ("balanced", "high_time_resolution"):
        for channel_name in ("pdv_channel_1", "pdv_channel_2"):
            channel_directory = production_run / profile_name / channel_name
            assert required <= {
                path.name for path in channel_directory.iterdir()
            }


def test_primary_overview_uses_preview_and_formal_without_state_markers() -> None:
    source = inspect.getsource(_save_apparent_velocity_full_overview)
    assert "preview.apparent_velocity_m_s" in source
    assert "analysis.refined_velocity_m_s" in source
    assert QUALITY_UNFILTERED_PREVIEW_LABEL == (
        "quality-unfiltered argmax preview; not a measurement"
    )
    assert "axis.scatter" not in source
    assert "marker=" not in source
    assert "Red preview is diagnostic only." in source
    assert "Lower-bound argmax is not zero velocity." in source


def test_reviewed_display_uses_simple_series_without_mutating_formal_velocity(
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    _, analyses_by_profile = formal_analyses
    analysis = analyses_by_profile["balanced"]["pdv_channel_1"]
    consensus_time_s = float(analysis.refined_result.time_s[5])
    formal_before = analysis.corrected_velocity_m_s.copy()

    reviewed = _build_reviewed_velocity_series(
        analysis,
        consensus_event_time_s=consensus_time_s,
    )

    pre_mask = analysis.refined_result.time_s < consensus_time_s
    assert pre_mask.any()
    assert np.isfinite(formal_before[pre_mask]).any()
    assert np.all(reviewed.pre_event_zero_velocity_m_s[pre_mask] == 0.0)
    assert np.all(reviewed.simple_export_velocity_m_s[pre_mask] == 0.0)
    assert np.isnan(reviewed.post_event_velocity_m_s[pre_mask]).all()
    np.testing.assert_allclose(
        reviewed.simple_export_velocity_m_s[~pre_mask],
        formal_before[~pre_mask],
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        reviewed.post_event_velocity_m_s[~pre_mask],
        formal_before[~pre_mask],
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_array_equal(
        analysis.corrected_velocity_m_s,
        formal_before,
    )

    plot_source = inspect.getsource(_save_apparent_velocity_full_time_reviewed)
    assert "bridge" not in plot_source
    assert "axvline" not in plot_source
    assert "reviewed.simple_export_velocity_m_s" in plot_source
    assert "pre-event baseline defined as zero for plotting" in plot_source
    assert "quality-gated corrected velocity after event" in plot_source
    assert (
        "Pre-event zero is a plotting convention based on the consensus event time."
        in plot_source
    )
    assert "preview" not in plot_source
    assert "red" not in plot_source.lower()


def test_simple_exports_are_origin_ready_two_column_roundtrips(
    production_run: Path,
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    _, analyses_by_profile = formal_analyses
    run_manifest = json.loads((production_run / "run_manifest.json").read_text())
    zero_before_time_s = run_manifest["cross_profile_consensus"][
        "consensus_event_candidate_time_s"
    ]
    simple_directory = production_run / "simple_exports"
    expected_csv_names = {
        _simple_export_filename(profile_name, channel_name)
        for profile_name in analyses_by_profile
        for channel_name in analyses_by_profile[profile_name]
    }
    assert expected_csv_names == {
        "balanced__pdv_channel_1__velocity_time.csv",
        "balanced__pdv_channel_2__velocity_time.csv",
        "high_time_resolution__pdv_channel_1__velocity_time.csv",
        "high_time_resolution__pdv_channel_2__velocity_time.csv",
    }
    assert {path.name for path in simple_directory.glob("*.csv")} == expected_csv_names
    assert (simple_directory / "README.txt").is_file()
    banned_global_names = {
        "final_velocity.csv",
        "recommended_velocity.csv",
        "merged_velocity.csv",
        "fused_velocity.csv",
        "best_velocity.csv",
    }
    assert not {
        path.name for path in production_run.rglob("*.csv")
    } & banned_global_names

    for profile_name, analyses in analyses_by_profile.items():
        for channel_name, analysis in analyses.items():
            path = simple_directory / _simple_export_filename(
                profile_name,
                channel_name,
            )
            frame = pd.read_csv(path)
            assert frame.columns.tolist() == [
                "time_s",
                "corrected_velocity_m_s",
            ]
            assert len(frame) == analysis.stft_result.time_s.size
            assert np.all(np.diff(frame["time_s"].to_numpy()) > 0.0)
            np.testing.assert_allclose(
                frame["time_s"].to_numpy(),
                analysis.refined_result.time_s,
                rtol=0.0,
                atol=2.0e-18,
            )
            np.testing.assert_allclose(
                frame["corrected_velocity_m_s"].to_numpy(),
                _simple_export_velocity_m_s(
                    analysis,
                    zero_before_time_s=zero_before_time_s,
                ),
                rtol=1.0e-15,
                atol=0.0,
                equal_nan=True,
            )
            finite_indices = np.flatnonzero(
                np.isfinite(analysis.corrected_velocity_m_s)
            )
            assert finite_indices.size > 0
            assert np.isfinite(
                frame["corrected_velocity_m_s"].iloc[finite_indices[-1]]
            )

            detailed = pd.read_csv(
                production_run
                / profile_name
                / channel_name
                / "apparent_velocity_diagnostics.csv"
            )
            np.testing.assert_array_equal(
                frame["time_s"].to_numpy(),
                detailed["time_s"].to_numpy(),
            )
            np.testing.assert_allclose(
                detailed["apparent_velocity_m_s"].to_numpy(),
                analysis.refined_velocity_m_s,
                rtol=1.0e-15,
                atol=0.0,
                equal_nan=True,
            )
            if zero_before_time_s is None:
                np.testing.assert_allclose(
                    frame["corrected_velocity_m_s"].to_numpy(),
                    detailed["corrected_velocity_m_s"].to_numpy(),
                    rtol=1.0e-15,
                    atol=0.0,
                    equal_nan=True,
                )
            else:
                pre_mask = frame["time_s"].to_numpy() < zero_before_time_s
                post_mask = ~pre_mask
                assert np.all(
                    frame.loc[pre_mask, "corrected_velocity_m_s"] == 0.0
                )
                np.testing.assert_allclose(
                    frame.loc[post_mask, "corrected_velocity_m_s"].to_numpy(),
                    detailed.loc[post_mask, "corrected_velocity_m_s"].to_numpy(),
                    rtol=1.0e-15,
                    atol=0.0,
                    equal_nan=True,
                )


def test_simple_export_zero_overrides_every_pre_consensus_formal_value(
    tmp_path: Path,
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    _, analyses_by_profile = formal_analyses
    analysis = analyses_by_profile["balanced"]["pdv_channel_1"]
    zero_before_time_s = float(analysis.refined_result.time_s[-1])
    expected_zero = analysis.refined_result.time_s < zero_before_time_s
    formal_before = analysis.corrected_velocity_m_s.copy()
    assert expected_zero.sum() == analysis.refined_result.time_s.size - 1
    assert np.isfinite(formal_before[expected_zero]).any()

    simple_velocity = _simple_export_velocity_m_s(
        analysis,
        zero_before_time_s=zero_before_time_s,
    )
    assert np.all(simple_velocity[expected_zero] == 0.0)
    np.testing.assert_allclose(
        simple_velocity[~expected_zero],
        formal_before[~expected_zero],
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_array_equal(
        analysis.corrected_velocity_m_s,
        formal_before,
    )
    path = _write_simple_velocity_csv(
        tmp_path,
        "balanced",
        "pdv_channel_1",
        analysis,
        zero_before_time_s=zero_before_time_s,
    )
    written = pd.read_csv(path)
    np.testing.assert_allclose(
        written["corrected_velocity_m_s"].to_numpy(),
        simple_velocity,
        rtol=1.0e-15,
        atol=0.0,
        equal_nan=True,
    )


def test_simple_export_fields_ignore_manual_reference_and_event_candidate_config(
    tmp_path: Path,
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    configuration, analyses_by_profile = formal_analyses
    profile = configuration.analysis.profiles[0]
    records = _records(configuration.input.path)
    base = analyses_by_profile["balanced"]["pdv_channel_1"]
    changed_manual = analyze_profile(
        records,
        profile=profile,
        analysis_start_time_s=configuration.analysis.analysis_start_time_s,
        analysis_end_time_s=configuration.analysis.analysis_end_time_s,
        manual_event_reference_time_s=EVENT_START_TIME_S + 1.0e-6,
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=configuration.event_candidate,
        background_guard_window_scale=(
            configuration.quality.background_guard_window_scale
        ),
        minimum_background_bin_count=(
            configuration.quality.minimum_background_bin_count
        ),
    )["pdv_channel_1"]
    changed_candidate = analyze_profile(
        records,
        profile=profile,
        analysis_start_time_s=configuration.analysis.analysis_start_time_s,
        analysis_end_time_s=configuration.analysis.analysis_end_time_s,
        manual_event_reference_time_s=(
            configuration.analysis.manual_event_reference_time_s
        ),
        vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
        detection_config=configuration.quality.signal_detection,
        event_candidate_config=EventCandidateConfig(
            minimum_segment_frames=1,
            minimum_segment_duration_s=0.0,
            maximum_adjacent_frequency_step_hz=1.0e12,
        ),
        background_guard_window_scale=(
            configuration.quality.background_guard_window_scale
        ),
        minimum_background_bin_count=(
            configuration.quality.minimum_background_bin_count
        ),
    )["pdv_channel_1"]
    for index, analysis in enumerate((base, changed_manual, changed_candidate)):
        path = _write_simple_velocity_csv(
            tmp_path,
            f"balanced_{index}",
            "pdv_channel_1",
            analysis,
            zero_before_time_s=float(base.refined_result.time_s[0]),
        )
        frame = pd.read_csv(path)
        np.testing.assert_allclose(
            frame["time_s"].to_numpy(),
            base.refined_result.time_s,
            rtol=0.0,
            atol=2.0e-18,
        )
        np.testing.assert_allclose(
            frame["corrected_velocity_m_s"].to_numpy(),
            base.corrected_velocity_m_s,
            rtol=1.0e-15,
            atol=0.0,
            equal_nan=True,
        )


def test_simple_export_consensus_unavailable_copies_formal_without_manual_fallback(
    formal_analyses: tuple[object, dict[str, object]],
) -> None:
    _, analyses_by_profile = formal_analyses
    analysis = analyses_by_profile["balanced"]["pdv_channel_1"]
    formal_before = analysis.corrected_velocity_m_s.copy()

    simple = _simple_export_velocity_m_s(
        analysis,
        zero_before_time_s=None,
    )
    reviewed = _build_reviewed_velocity_series(
        analysis,
        consensus_event_time_s=None,
    )

    assert not np.shares_memory(simple, analysis.corrected_velocity_m_s)
    np.testing.assert_allclose(
        simple,
        formal_before,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        reviewed.simple_export_velocity_m_s,
        formal_before,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    assert np.isnan(reviewed.pre_event_zero_velocity_m_s).all()
    np.testing.assert_allclose(
        reviewed.post_event_velocity_m_s,
        formal_before,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )


def test_simple_readme_states_origin_semantics_and_formal_reference(
    production_run: Path,
) -> None:
    readme = (
        production_run / "simple_exports" / "README.txt"
    ).read_text(encoding="utf-8")
    assert "direct use in Origin or Excel" in readme
    assert "corrected_velocity_m_s is the final angle- and window-corrected" in readme
    assert "every frame with time_s before" in readme
    assert "invalid frames remain NaN" in readme
    assert "interpolated, smoothed, bridged, or resampled" in readme
    assert "use the configured observation-angle and window correction" in readme
    assert "preserve apparent, angle-corrected apparent, corrected" in readme
    assert THRESHOLD_CALIBRATION_PROVENANCE in readme


def test_detailed_diagnostics_record_selected_thresholds_and_provenance(
    production_run: Path,
) -> None:
    for profile_name in ("balanced", "high_time_resolution"):
        for channel_name in ("pdv_channel_1", "pdv_channel_2"):
            frame = pd.read_csv(
                production_run
                / profile_name
                / channel_name
                / "apparent_velocity_diagnostics.csv"
            )
            assert set(
                frame["minimum_peak_to_background_threshold_db"]
            ) == {10.0}
            assert set(
                frame["minimum_peak_to_competitor_threshold_db"]
            ) == {3.0}
            assert set(frame["threshold_provenance"]) == {
                THRESHOLD_CALIBRATION_PROVENANCE
            }


def test_threshold_calibration_csv_covers_exact_candidates_and_streams(
    production_run: Path,
) -> None:
    frame = pd.read_csv(
        production_run / "comparisons" / "threshold_calibration.csv"
    )
    required_columns = {
        "peak_to_background_threshold_db",
        "peak_to_competitor_threshold_db",
        "profile",
        "channel",
        "pre_event_measured_count",
        "main_event_baseline_count",
        "main_event_retained_count",
        "main_event_retention_fraction",
        "post_event_nan_count",
        "post_event_added_nan_count",
        "consensus_status",
        "selected",
    }
    assert required_columns <= set(frame.columns)
    assert len(frame) == 16
    assert {
        tuple(pair)
        for pair in frame[
            [
                "peak_to_background_threshold_db",
                "peak_to_competitor_threshold_db",
            ]
        ].drop_duplicates().to_numpy()
    } == set(THRESHOLD_CALIBRATION_CANDIDATES_DB)
    assert set(frame["profile"]) == {
        "balanced",
        "high_time_resolution",
    }
    assert set(frame["channel"]) == {
        "pdv_channel_1",
        "pdv_channel_2",
    }
    assert frame["selected"].sum() == 4
    assert set(frame.loc[frame["selected"], "consensus_status"]) == {
        "no_eligible_segments"
    }


def test_threshold_selection_is_deterministic_and_chooses_smallest_qualifier() -> None:
    summaries = [
        {
            "peak_to_background_threshold_db": background,
            "peak_to_competitor_threshold_db": competitor,
            "qualifies": background >= 12.0,
        }
        for background, competitor in reversed(
            THRESHOLD_CALIBRATION_CANDIDATES_DB
        )
    ]
    assert _select_threshold_candidate(summaries) == (
        12.0,
        4.0,
        "smallest_candidate_meeting_all_criteria",
    )


def test_threshold_selection_falls_back_to_10_3_when_none_qualify() -> None:
    summaries = [
        {
            "peak_to_background_threshold_db": background,
            "peak_to_competitor_threshold_db": competitor,
            "qualifies": False,
        }
        for background, competitor in THRESHOLD_CALIBRATION_CANDIDATES_DB
    ]
    assert _select_threshold_candidate(summaries) == (
        10.0,
        3.0,
        "no_candidate_met_all_criteria_fallback_to_10_3",
    )


def test_production_source_has_no_private_compare_dependency() -> None:
    source = (SCRIPTS_DIRECTORY / "production_outputs.py").read_text(encoding="utf-8")
    assert "compare_real_ridge_refinement" not in source
    assert "_analyze_configuration" not in source
