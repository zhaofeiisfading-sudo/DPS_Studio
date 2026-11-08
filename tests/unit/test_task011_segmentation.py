"""Numerical, boundary, provenance and failure contracts for manual gating."""
from __future__ import annotations

import csv
import importlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import VelocityCorrectionConfig, WindowMaterial
from dps_studio.core.segmentation import (
    AlgorithmPool, BeatEstimate, EstimatorRequest, Segment, analyze_segments, default_pool,
    validate_plan,
)
from dps_studio.core.segmentation.export import export_segmented_results
from dps_studio.core.segmentation.pool import FunctionEstimator
from dps_studio.core.workflow import analyze_configuration
from dps_studio.gui.research_safety import protected_path, write_guard


@pytest.fixture
def request_data() -> EstimatorRequest:
    time = np.arange(2048) / 40e9
    rng = np.random.default_rng(11011)
    voltage = .001 * rng.normal(size=len(time))
    voltage[400:] += .2 * np.cos(2 * np.pi * 700e6 * time[400:])
    return EstimatorRequest(SignalRecord(time, voltage), float(time[0]), float(time[-1]), 1550e-9,
                            dict(window_length_samples=512, overlap_samples=384, nfft=4096,
                                 window_name="hann", minimum_frequency_hz=50e6,
                                 maximum_frequency_hz=3e9))


def plan(request: EstimatorRequest, algorithm: str = "stft") -> tuple[Segment, ...]:
    return (Segment("left", request.start_s, request.record.time_s[1024], algorithm=algorithm),
            Segment("right", request.record.time_s[1024], request.end_s, algorithm=algorithm))


def test_manual_stft_matches_formal_detection_and_keeps_window_context(request_data: EstimatorRequest) -> None:
    source = request_data.record.voltage_v.tobytes()
    result = analyze_segments(request_data, plan(request_data), correction_config=VelocityCorrectionConfig())
    baseline = analyze_configuration({"channel": request_data.record},
        **request_data.workflow_options, vacuum_wavelength_m=request_data.wavelength_m,
        analysis_start_time_s=request_data.start_s, analysis_end_time_s=request_data.end_s)["channel"]
    np.testing.assert_array_equal(result.time_s, baseline.stft_result.time_s)
    np.testing.assert_allclose(result.apparent_velocity_m_s, baseline.refined_velocity_m_s,
                               rtol=2e-15, equal_nan=True)
    np.testing.assert_allclose(result.corrected_velocity_m_s,
        baseline.velocity_correction_result.corrected_velocity_m_s, rtol=2e-15, equal_nan=True)
    assert source == request_data.record.voltage_v.tobytes()
    assert np.isnan(result.apparent_velocity_m_s).any()
    assert any("BOUNDARY_CONTEXT" in flag for flag in result.quality)
    moved = (replace(result.segments[0], end_s=29e-9), replace(result.segments[1], start_s=29e-9))
    again = analyze_segments(request_data, moved, correction_config=VelocityCorrectionConfig())
    np.testing.assert_array_equal(result.frequency_hz, again.frequency_hz)


def test_boundaries_have_single_owner_and_final_endpoint(request_data: EstimatorRequest) -> None:
    t = np.array([0., 10e-9, 20e-9, request_data.end_s])
    pool = AlgorithmPool()
    pool.register(FunctionEstimator("stub", "test", lambda request:
        BeatEstimate(t, np.full(4, 1e9), np.full(4, 1e9), ("OK",) * 4, "stub", "fixture", 128)))
    segments = (Segment("a", 0., 20e-9, algorithm="stub"),
                Segment("b", 20e-9, request_data.end_s, algorithm="stub"))
    result = analyze_segments(request_data, segments, pool=pool,
                              correction_config=VelocityCorrectionConfig(window_material=WindowMaterial.NONE))
    np.testing.assert_array_equal(result.time_s, t)
    assert result.segment_ids == ("a", "a", "b", "b")
    np.testing.assert_allclose(result.apparent_velocity_m_s, 775.)


@pytest.mark.parametrize("algorithm", ["dechirp", "varpro", "clutter_varpro"])
def test_adapters_preserve_frozen_frequency_flags_and_raw(request_data: EstimatorRequest, algorithm: str) -> None:
    from dps_studio.algorithms.waveform.common import Context, Signal

    module = importlib.import_module(f"dps_studio.algorithms.waveform.{algorithm}.implementation")
    before = request_data.record.voltage_v.tobytes()
    context = Context(Signal(np.array(request_data.record.time_s), np.array(request_data.record.voltage_v)))
    direct = module.run(context)
    estimate = default_pool().estimate(algorithm, request_data)
    np.testing.assert_array_equal(estimate.frequency_hz, direct.accepted_hz)
    np.testing.assert_array_equal(estimate.candidate_frequency_hz, direct.frequency_hz)
    assert estimate.quality == tuple(direct.flags)
    assert before == request_data.record.voltage_v.tobytes()
    assert "IDENTITY_UNVALIDATED" in "|".join(estimate.quality)


def test_failure_is_nan_flagged_and_other_segments_survive(request_data: EstimatorRequest) -> None:
    def broken(_request: EstimatorRequest) -> BeatEstimate:
        raise RuntimeError("intentional algorithm failure")

    pool = default_pool()
    pool.register(FunctionEstimator("broken", "broken", broken))
    segments = (replace(plan(request_data)[0], algorithm="broken"), plan(request_data)[1])
    result = analyze_segments(request_data, segments, pool=pool, correction_config=VelocityCorrectionConfig())
    failed = np.asarray(result.segment_ids) == "left"
    assert np.isnan(result.frequency_hz[failed]).all()
    assert all("ALGORITHM_ERROR" in flag for flag, mask in zip(result.quality, failed) if mask)
    assert result.valid[~failed].any()
    assert result.metadata["algorithms"][0]["error"] == "RuntimeError: intentional algorithm failure"


def test_explicit_exclusion_never_fills_static_zero(request_data: EstimatorRequest) -> None:
    result = analyze_segments(request_data, plan(request_data, "unobservable"),
                              correction_config=VelocityCorrectionConfig())
    assert not result.valid.any()
    assert np.isnan(result.corrected_velocity_m_s).all()
    assert all("UNOBSERVABLE_NOT_ZERO" in flag for flag in result.quality)


def test_known_angle_lif_order_and_nan_propagation(request_data: EstimatorRequest) -> None:
    config = VelocityCorrectionConfig(measurement_angle_rad=np.pi / 3)
    result = analyze_segments(request_data, plan(request_data), correction_config=config)
    expected_angle = result.apparent_velocity_m_s / np.cos(np.pi / 3)
    expected_lif = 1000 * .7895 * (expected_angle / 1000) ** .9918
    np.testing.assert_allclose(result.angle_corrected_velocity_m_s, expected_angle, equal_nan=True)
    np.testing.assert_allclose(result.corrected_velocity_m_s, expected_lif, equal_nan=True)
    assert result.metadata["physical_correction"]["window"]["source_doi"] == "10.1063/1.4890714"


def test_exports_roundtrip_precision_quality_and_sources(request_data: EstimatorRequest, tmp_path: Path) -> None:
    result = analyze_segments(request_data, plan(request_data), correction_config=VelocityCorrectionConfig())
    paths = export_segmented_results({"ch/1": result}, tmp_path / "export")
    with paths[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    metadata = json.loads(paths[1].read_text(encoding="utf-8"))
    np.testing.assert_array_equal([float(row["absolute_time_s"]) for row in rows], result.time_s)
    np.testing.assert_array_equal([float(row["corrected_velocity_m_s"]) for row in rows], result.corrected_velocity_m_s)
    assert [row["segment_id"] for row in rows] == list(result.segment_ids)
    assert metadata["segments"][0]["algorithm"] == "stft"
    assert metadata["valid_count"] == result.valid.sum()
    with pytest.raises(FileExistsError):
        export_segmented_results({"ch1": result}, tmp_path / "export")
    with pytest.raises(ValueError, match="read-only"):
        export_segmented_results({"ch1": result}, tmp_path / "data/raw/out")


@pytest.mark.parametrize("segments", [(), (Segment("a", 0, 1), Segment("a", 1, 2)),
    (Segment("a", 0, 1), Segment("b", .9, 2)), (Segment("a", .1, 2),)])
def test_plan_rejects_missing_overlap_duplicate_or_wrong_roi(segments: tuple[Segment, ...]) -> None:
    with pytest.raises(ValueError):
        validate_plan(segments, 0, 2)


def test_contract_rejects_shape_and_infinity_and_is_immutable() -> None:
    with pytest.raises(ValueError):
        BeatEstimate(np.array([0., 1.]), np.array([1.]), np.array([1.]), ("OK",), "x", "test", 2)
    with pytest.raises(ValueError):
        BeatEstimate(np.array([0.]), np.array([np.inf]), np.array([1.]), ("OK",), "x", "test", 2)
    estimate = BeatEstimate(np.array([0.]), np.array([1.]), np.array([1.]), ("OK",), "x", "test", 2)
    with pytest.raises(ValueError):
        estimate.frequency_hz[0] = 0


def test_write_guard_protects_production_and_raw_without_touching_them(tmp_path: Path) -> None:
    production = Path("D:/Code/Python_Projects/DPS_Studio/test.txt")
    assert protected_path(production)
    assert protected_path(tmp_path / "data/raw/test.csv")
    assert not protected_path(tmp_path / "results/test.csv")
    with pytest.raises(PermissionError):
        write_guard("open", (str(production), "w", 0))
    with pytest.raises(PermissionError):
        write_guard("os.rename", (str(tmp_path / "safe"), str(production), -1, -1))
