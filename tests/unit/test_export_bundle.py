from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio import __version__
from dps_studio.core.export import (
    BUNDLE_SCHEMA_VERSION,
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultBundleOptions,
    ResultExportValidationError,
    ResultExportWriteError,
    allocate_bundle_directory,
    build_display_velocity_curve,
    channel_token,
    export_result_bundle,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import WindowMaterial, VelocityCorrectionConfig
from dps_studio.core.quality import SignalDetectionResult, SignalState
from dps_studio.core.workflow import analyze_configuration, configure_channel_event_reference, load_workflow_config


ROOT = Path(__file__).resolve().parents[2]


def _make_dual_analyses() -> dict:
    sample_rate_hz = 20.0e9
    time_s = 100.0e-9 + np.arange(4096, dtype=np.float64) / sample_rate_hz
    active = (time_s >= 140.0e-9) & (time_s <= 260.0e-9)
    records = {
        "pdv_channel_1": SignalRecord(
            time_s,
            np.where(active, np.sin(2.0 * np.pi * 1.2e9 * (time_s - time_s[0])), 0.0),
        ),
        "pdv_channel_2": SignalRecord(
            time_s,
            np.where(active, np.sin(2.0 * np.pi * 1.5e9 * (time_s - time_s[0])), 0.0),
        ),
    }
    base = load_workflow_config(ROOT / "configs/pdv_studio_defaults.toml", repository_root=ROOT)
    profile = next(p for p in base.analysis.profiles if p.profile_id.value == "balanced")
    return analyze_configuration(
        records,
        window_length_samples=128,
        overlap_samples=96,
        nfft=512,
        window_name=profile.window_name,
        minimum_frequency_hz=0.2e9,
        maximum_frequency_hz=4.0e9,
        analysis_start_time_s=float(time_s[0]),
        analysis_end_time_s=float(time_s[-1]),
        vacuum_wavelength_m=1.55e-6,
        detection_config=base.quality.signal_detection,
        event_candidate_config=base.event_candidate,
        automatic_ridge_selection_config=base.automatic_ridge_selection,
        velocity_correction_config=VelocityCorrectionConfig(
            window_material=WindowMaterial.LIF,
            measurement_angle_rad=0.0,
        ),
    )


def _with_synthetic_states(base_analysis, states: list[SignalState], corrected_vals: np.ndarray):
    detection: SignalDetectionResult = base_analysis.signal_detection_result
    measured = np.array([s is SignalState.MEASURED for s in states], dtype=np.bool_)
    new_refined = np.where(measured, 1.0e9, np.nan)
    new_app = np.where(measured, corrected_vals, np.nan)
    new_detection = replace(
        detection,
        signal_states=tuple(states),
        refined_frequency_hz=new_refined,
        apparent_velocity_m_s=new_app,
    )
    new_corr = replace(
        base_analysis.velocity_correction_result,
        apparent_velocity_m_s=new_app,
        angle_corrected_apparent_velocity_m_s=new_app,
        corrected_velocity_m_s=new_app,
    )
    return replace(
        base_analysis,
        signal_detection_result=new_detection,
        refined_velocity_m_s=new_app,
        velocity_correction_result=new_corr,
    )


def test_build_display_velocity_curve_smoothing_bridging_and_platform() -> None:
    analysis = _make_dual_analyses()["pdv_channel_1"]
    time_s = analysis.stft_result.time_s
    n = time_s.size
    cand_t = analysis.stream_event_candidates.primary_candidate_time_s
    assert cand_t is not None
    cand_idx = int(np.searchsorted(time_s, cand_t))
    base = cand_idx + 5
    assert n >= base + 22

    states = [SignalState.NO_DETECTABLE_BEAT] * n
    corrected = np.full(n, np.nan, dtype=np.float64)

    # Segment 1 (len=5): base..base+4 -> smoothed interior; endpoints preserved
    seg1_vals = [100.0, 120.0, 100.0, 140.0, 100.0]
    for offset, val in enumerate(seg1_vals):
        states[base + offset] = SignalState.MEASURED
        corrected[base + offset] = val

    # Gap 1 (len=3 <= 5): base+5..base+7 -> linearly bridged between base+4 (100.0) and base+8 (180.0)
    # Segment 2 (len=2): base+8..base+9 -> len < 3 stays unsmoothed
    states[base + 8] = SignalState.MEASURED
    states[base + 9] = SignalState.MEASURED
    corrected[base + 8] = 180.0
    corrected[base + 9] = 200.0

    # Gap 2 (len=6 > 5): base+10..base+15 -> MUST stay NaN (not bridged)
    # Segment 3 (len=3): base+16..base+18
    for offset, val in zip((16, 17, 18), (300.0, 340.0, 300.0), strict=True):
        states[base + offset] = SignalState.MEASURED
        corrected[base + offset] = val

    synthetic = _with_synthetic_states(analysis, states, corrected)
    curve = build_display_velocity_curve(synthetic, pre_event_display_enabled=True)
    assert curve.measured_frames == 10
    assert curve.bridged_gap_count == 1
    assert curve.bridged_frame_count == 3
    assert curve.bridged_intervals == ((base + 5, base + 7),)
    assert curve.smoothing_applied is True
    assert curve.pre_event_source == "stream_event_candidate"
    assert curve.pre_event_time_s == pytest.approx(cand_t)

    # Pre-event platform strictly before cand_t, gap between cand_t and base stays NaN
    before_cand = time_s < cand_t
    assert np.any(before_cand)
    np.testing.assert_array_equal(curve.values[before_cand], 0.0)
    assert np.all(np.isnan(curve.values[~before_cand & (np.arange(n) < base)]))

    # Endpoints preserved & interior [1,2,1]/4 smoothed
    assert curve.values[base] == pytest.approx(100.0)
    assert curve.values[base + 1] == pytest.approx(0.25 * 100 + 0.5 * 120 + 0.25 * 100)
    assert curve.values[base + 2] == pytest.approx(0.25 * 120 + 0.5 * 100 + 0.25 * 140)
    assert curve.values[base + 3] == pytest.approx(0.25 * 100 + 0.5 * 140 + 0.25 * 100)
    assert curve.values[base + 4] == pytest.approx(100.0)

    # Bridged gap base+5..base+7 between 100.0 and 180.0
    np.testing.assert_allclose(curve.values[base + 5 : base + 8], [120.0, 140.0, 160.0], rtol=1e-9)
    assert curve.values[base + 8] == pytest.approx(180.0)
    assert curve.values[base + 9] == pytest.approx(200.0)

    # Gap > 5 stays NaN; after last measured frame stays NaN
    assert np.all(np.isnan(curve.values[base + 10 : base + 16]))
    assert curve.values[base + 16] == pytest.approx(300.0)
    assert curve.values[base + 17] == pytest.approx(320.0)
    assert curve.values[base + 18] == pytest.approx(300.0)
    assert np.all(np.isnan(curve.values[base + 19 :]))


def test_build_display_velocity_curve_zero_measured_never_fabricates() -> None:
    analysis = _make_dual_analyses()["pdv_channel_1"]
    n = analysis.stft_result.time_s.size
    zero_states = [SignalState.PEAK_AT_BAND_BOUNDARY] * n
    synthetic = _with_synthetic_states(analysis, zero_states, np.full(n, np.nan))
    curve = build_display_velocity_curve(synthetic, pre_event_display_enabled=True)
    assert curve.measured_frames == 0
    assert curve.pre_event_source == "no_measured_frames"
    assert curve.bridged_gap_count == 0
    assert curve.bridged_intervals == ()
    assert np.all(np.isnan(curve.values))


def test_export_result_bundle_five_files_empty_cells_and_multi_channel(tmp_path: Path) -> None:
    analyses = _make_dual_analyses()
    ref_time = float(next(iter(analyses.values())).stft_result.time_s[15])
    analyses = {
        name: configure_channel_event_reference(
            analysis,
            event_reference_time_s=ref_time,
            event_reference_source="manual",
            enable_pre_event_display=True,
            pre_event_display_velocity_m_s=0.0,
        )
        for name, analysis in analyses.items()
    }

    bundle_dir = allocate_bundle_directory(
        tmp_path,
        source_path=Path("shot_01.dat"),
        analysis_mode=ResultAnalysisMode.AUTOMATIC,
    )
    assert bundle_dir == tmp_path / "shot_01_auto"

    def render_dummy_png(dst: Path) -> None:
        dst.write_bytes(b"\x89PNG\r\n\x1a\ndummy")

    report = export_result_bundle(
        ResultBundleOptions(
            output_directory=bundle_dir,
            analysis_mode=ResultAnalysisMode.AUTOMATIC,
            channel_analyses=analyses,
            time_origin=ExportTimeOrigin.EVENT,
            source_path=Path("shot_01.dat"),
            source_sha256="abc123",
            event_reference_source="manual",
            event_time_source="manual",
            spectrogram_renderer=render_dummy_png,
        )
    )

    produced_names = {p.name for p in bundle_dir.iterdir()}
    assert produced_names == {
        "velocity_raw.csv",
        "velocity_gated.csv",
        "velocity_display.csv",
        "run_summary.json",
        "spectrogram_ridge.png",
    }
    assert report.acceleration_csv_path is None
    assert not report.detail_csv_paths
    assert channel_token("pdv_channel_1") == "ch1"

    for csv_path in (
        report.velocity_raw_csv_path,
        report.velocity_gated_csv_path,
        report.velocity_display_csv_path,
    ):
        text = csv_path.read_text(encoding="utf-8")
        assert "nan" not in text.lower()
        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == analyses["pdv_channel_1"].stft_result.time_s.size
        assert "time_from_event_s" in rows[0]

    with report.velocity_gated_csv_path.open(encoding="utf-8", newline="") as handle:
        gated_rows = list(csv.DictReader(handle))
    assert set(gated_rows[0]) == {
        "time_from_event_s",
        "ch1_gated_velocity_m_s",
        "ch2_gated_velocity_m_s",
    }
    assert any(row["ch1_gated_velocity_m_s"] == "" for row in gated_rows)
    assert any(row["ch1_gated_velocity_m_s"] != "" for row in gated_rows)

    summary = json.loads(report.run_summary_json_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert summary["software_version"] == __version__
    assert summary["channels"] == ["pdv_channel_1", "pdv_channel_2"]
    assert summary["outputs"]["acceleration_csv"] is None
    assert summary["outputs"]["detail_csvs"] == {}
    assert summary["display_processing"]["pdv_channel_1"]["pre_event_source"] == "manual"

    # Next allocation does not overwrite
    next_dir = allocate_bundle_directory(
        tmp_path,
        source_path=Path("shot_01.dat"),
        analysis_mode=ResultAnalysisMode.AUTOMATIC,
    )
    assert next_dir == tmp_path / "shot_01_auto_2"

    # Reject re-export collision & data/raw guard
    with pytest.raises(ResultExportWriteError):
        export_result_bundle(
            ResultBundleOptions(
                output_directory=bundle_dir,
                analysis_mode=ResultAnalysisMode.AUTOMATIC,
                channel_analyses=analyses,
            )
        )
    with pytest.raises(ResultExportValidationError):
        allocate_bundle_directory(
            tmp_path / "data" / "raw",
            source_path=Path("shot_01.dat"),
            analysis_mode=ResultAnalysisMode.AUTOMATIC,
        )
