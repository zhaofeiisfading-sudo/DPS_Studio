from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.ridge import extract_peak_ridge, refine_peak_ridge_subbin
from dps_studio.core.time_frequency import compute_stft
from scripts.audit_legacy_velocity_reference import (
    EXPECTED_RAW_SHA256,
    VACUUM_WAVELENGTH_M,
    AuditConfiguration,
    alignment_metrics,
    estimate_frequency_series,
    generate_synthetic_signal,
    infer_velocity_quantization,
    production_snapshot,
    read_legacy_reference,
    search_integer_frame_offset,
    synthetic_metrics,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "20260607.csv"
LEGACY_SAMPLE_RATE_HZ = 40.0e9
LEGACY_TIME_STEP_NS = 3.2
LEGACY_VELOCITY_GRID_M_S = 0.12109375


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_deterministic_legacy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "legacy_velocity_time.csv"
    rows = ["time_us,velocity_m_s,velocity_km_s,data_flag"]
    for frame_index in range(32):
        time_us = frame_index * LEGACY_TIME_STEP_NS * 1.0e-3
        if frame_index < 27:
            velocity_m_s = 0.0
            data_flag = "zero_masked"
        else:
            velocity_m_s = (500 + frame_index - 27) * LEGACY_VELOCITY_GRID_M_S
            data_flag = "measured"
        rows.append(
            ",".join(
                (
                    format(time_us, ".12g"),
                    format(velocity_m_s, ".12g"),
                    format(velocity_m_s / 1000.0, ".12g"),
                    data_flag,
                )
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_generated_legacy_fixture_flags_quantization_and_nfft(
    tmp_path: Path,
) -> None:
    fixture_path = _write_deterministic_legacy_fixture(tmp_path)
    source_hash_before = _sha256(fixture_path)
    result = read_legacy_reference(fixture_path)

    assert result.row_count == 32
    assert result.measured_count == 5
    assert result.zero_masked_count == 27
    assert result.strictly_3p2_ns_grid
    assert result.time_step_median_ns == pytest.approx(3.2, abs=1.0e-9)
    assert result.velocity_grid_spacing_m_s == LEGACY_VELOCITY_GRID_M_S
    assert result.expected_spacing_integer_multiple
    assert result.expected_spacing_max_integer_residual == 0.0
    frequency_grid_spacing_hz = (
        2.0 * result.velocity_grid_spacing_m_s / VACUUM_WAVELENGTH_M
    )
    inferred_nfft = LEGACY_SAMPLE_RATE_HZ / frequency_grid_spacing_hz
    assert frequency_grid_spacing_hz == 156_250.0
    assert inferred_nfft == 256_000.0

    candidate_time_s = np.arange(6, dtype=np.float64) * 3.2e-9
    candidate_velocity_m_s = np.concatenate(
        (np.array([999.0]), result.measured_velocity_m_s)
    )
    alignment = search_integer_frame_offset(
        result.measured_time_relative_s,
        result.measured_velocity_m_s,
        candidate_time_s,
        candidate_velocity_m_s,
        minimum_offset_frames=-2,
        maximum_offset_frames=2,
    )
    assert alignment.offset_frames == 1
    assert alignment.time_offset_ns == pytest.approx(3.2)
    assert alignment.metrics.rmse_m_s == 0.0
    assert _sha256(fixture_path) == source_hash_before


def test_quantization_inference_uses_actual_unique_values() -> None:
    values = np.array([0.0, 0.25, 1.0, 0.5, 0.25])
    spacing, residual = infer_velocity_quantization(values)

    assert spacing == 0.25
    assert residual == 0.0


def test_integer_frame_offset_search_recovers_known_shift_without_interpolation() -> None:
    reference_time = np.arange(5, dtype=np.float64) * 3.2e-9
    candidate_time = np.arange(6, dtype=np.float64) * 3.2e-9
    reference = np.array([1.0, 3.0, 6.0, 10.0, 15.0])
    candidate = np.array([99.0, 1.0, 3.0, 6.0, 10.0, 15.0])

    result = search_integer_frame_offset(
        reference_time,
        reference,
        candidate_time,
        candidate,
        minimum_offset_frames=-2,
        maximum_offset_frames=2,
    )

    assert result.offset_frames == 1
    assert result.time_offset_ns == pytest.approx(3.2)
    assert result.metrics.rmse_m_s == 0.0
    assert np.array_equal(result.reference_values_m_s, reference)
    assert np.array_equal(result.candidate_values_m_s, candidate[1:])
    assert set(result.candidate_values_m_s).issubset(set(candidate))


def test_mismatched_steps_are_rejected_instead_of_interpolated() -> None:
    with pytest.raises(ValueError, match="interpolation and time stretching"):
        search_integer_frame_offset(
            np.arange(5, dtype=np.float64) * 3.2e-9,
            np.arange(5, dtype=np.float64),
            np.arange(5, dtype=np.float64) * 3.1e-9,
            np.arange(5, dtype=np.float64),
        )


def test_alignment_metrics_are_mathematically_exact() -> None:
    result = alignment_metrics(
        np.array([1.0, 2.0]),
        np.array([2.0, 4.0]),
    )

    assert result.paired_count == 2
    assert result.bias_m_s == 1.5
    assert result.mae_m_s == 1.5
    assert result.rmse_m_s == pytest.approx(np.sqrt(2.5))
    assert result.maximum_absolute_error_m_s == 2.0
    assert result.pearson_correlation == pytest.approx(1.0)


def test_fixed_seed_synthetic_signal_is_reproducible() -> None:
    first = generate_synthetic_signal(
        "constant",
        sample_rate_hz=40.0e9,
        noise_standard_deviation=0.05,
        random_seed=1234,
        duration_s=0.08e-6,
    )
    second = generate_synthetic_signal(
        "constant",
        sample_rate_hz=40.0e9,
        noise_standard_deviation=0.05,
        random_seed=1234,
        duration_s=0.08e-6,
    )

    assert np.array_equal(first.record.time_s, second.record.time_s)
    assert np.array_equal(first.record.voltage_v, second.record.voltage_v)


def test_synthetic_constant_frequency_is_recovered() -> None:
    signal = generate_synthetic_signal(
        "constant",
        sample_rate_hz=40.0e9,
        noise_standard_deviation=0.0,
        random_seed=1,
        duration_s=0.08e-6,
    )
    estimate = estimate_frequency_series(
        signal.record,
        AuditConfiguration("hann", 768, 4096, "subbin"),
        event_start_time_s=None,
        analysis_end_time_s=None,
    )
    metrics = synthetic_metrics(signal, estimate)

    assert float(metrics["frequency_rmse_hz"]) < 2.0e5
    assert float(metrics["velocity_rmse_m_s"]) < 0.2
    assert metrics["wrong_branch_frame_count"] == 0


def test_synthetic_fast_decline_has_known_endpoints_and_finite_onset_error() -> None:
    signal = generate_synthetic_signal(
        "fast_decline",
        sample_rate_hz=40.0e9,
        noise_standard_deviation=0.0,
        random_seed=2,
    )
    endpoints = signal.truth_frequency(np.array([0.0, 0.76e-6]))
    estimate = estimate_frequency_series(
        signal.record,
        AuditConfiguration("hann", 384, 4096, "subbin"),
        event_start_time_s=None,
        analysis_end_time_s=None,
    )
    metrics = synthetic_metrics(signal, estimate)

    assert np.array_equal(endpoints, np.array([0.73e9, 0.28e9]))
    assert metrics["transition_onset_error_ns"] is not None
    assert float(metrics["frequency_rmse_hz"]) < 20.0e6


def test_competing_band_counts_short_window_wrong_branch_frames() -> None:
    signal = generate_synthetic_signal(
        "competition",
        sample_rate_hz=40.0e9,
        noise_standard_deviation=0.30,
        random_seed=20261015,
    )
    baseline = estimate_frequency_series(
        signal.record,
        AuditConfiguration("hann", 768, 4096, "subbin"),
        event_start_time_s=None,
        analysis_end_time_s=None,
    )
    short = estimate_frequency_series(
        signal.record,
        AuditConfiguration("blackman", 416, 4096, "subbin"),
        event_start_time_s=None,
        analysis_end_time_s=None,
    )

    baseline_wrong = int(synthetic_metrics(signal, baseline)["wrong_branch_frame_count"])
    short_wrong = int(synthetic_metrics(signal, short)["wrong_branch_frame_count"])
    assert baseline_wrong == 0
    assert short_wrong > baseline_wrong


def test_development_estimator_matches_current_core_subbin_baseline() -> None:
    signal = generate_synthetic_signal(
        "constant",
        sample_rate_hz=40.0e9,
        noise_standard_deviation=0.01,
        random_seed=9,
        duration_s=0.08e-6,
    )
    direct = estimate_frequency_series(
        signal.record,
        AuditConfiguration("hann", 768, 4096, "subbin"),
        event_start_time_s=None,
        analysis_end_time_s=None,
    )
    stft = compute_stft(
        signal.record,
        window_length_samples=768,
        overlap_samples=640,
        nfft=4096,
        window_name="hann",
    )
    ridge = extract_peak_ridge(
        stft,
        minimum_frequency_hz=0.1e9,
        maximum_frequency_hz=2.0e9,
    )
    refined = refine_peak_ridge_subbin(stft, ridge)

    assert np.allclose(direct.time_s, refined.time_s, rtol=0.0, atol=1.0e-18)
    assert np.allclose(
        direct.frequency_hz,
        refined.refined_frequency_hz,
        rtol=0.0,
        atol=1.0e-6,
    )
    assert np.allclose(np.diff(direct.time_s), 3.2e-9, rtol=0.0, atol=1.0e-18)


def test_real_production_baseline_and_task008_fingerprints_are_unchanged() -> None:
    raw_hash = _sha256(RAW_DATA_PATH)
    loaded = read_delimited_signals(
        RAW_DATA_PATH,
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
    )
    snapshot, _ = production_snapshot(loaded.records, source_sha256=raw_hash)

    assert raw_hash == EXPECTED_RAW_SHA256
    expected = {
        "pdv_channel_1": {
            "stft": "b2e2ee32ef32f34935f76aeb1880b0e60641f22b76ff20bd1fcabf179cbb5d3b",
            "ridge": "ecc18d273bcb38b1daa818efa5c1830d7be0d572e834787a7950a85de7963214",
            "refined": "48379de47c0845f6d318ba2d05a1eddc7bd106f1694650c7a77bf47af243c0a5",
            "velocity": "9c322e7982787fab38a9ae4c18129c6ac368b13d57232d7316a8d8448b9d5b9a",
            "display": "719299bc4d85f9d4f452f9412a7add44aeb3314a1237f04d6a57b56b835bf181",
            "quality": "ea0bd4661b243725a3c07ad9e16b9684642033e978cecb727084ebf544679b9c",
            "continuity": "9564848c7e4b4a5d6475fb69c7898658827fa095dff3e11bb517104b9769c635",
            "related": "91dd99061ab7b01e40a625ab3fa66a37deb0c48f1a97ed0a323fbc3cecb4eb36",
        },
        "pdv_channel_2": {
            "stft": "96a5c3d5b9155ad0ef4b919e0d381dc2a2ef6bb7b2b41054e6208b323d4ce8d2",
            "ridge": "2cee1e2bd6909843f63691e39de8b923ffb9f1444b72d10bed71a1cc4cc1e084",
            "refined": "04c6f2811b03cb02dd3d8c1272de68cb0cb6920cbab591e1d49f6479bae5b8f8",
            "velocity": "3ccf592ae432a34049617a290f4c301aa64f5513801bce7bd2d3527f8271be18",
            "display": "2ccb2d6916b99e86bc1d5c56d9052687817b27482baee749e9d2a04c4de3f757",
            "quality": "c7b0a7f0f3027670afce07b9eceeff60a760915653d271c99b3741ebe1f920b2",
            "continuity": "bf8f6ce2ed1e290badd2164472f8c8bae5a296767edfd84dc936d75690c31756",
            "related": "5176b2a99f84857a7277c7254df3b293dbc8509f5ef56ee2cfef350f5668c800",
        },
    }
    for channel_name, hashes in expected.items():
        production = snapshot["task001_to_task007"][channel_name]
        assert production["stft_result"]["spectrum"]["data_sha256"] == hashes["stft"]
        assert production["ridge_result"]["frequency_hz"]["data_sha256"] == hashes[
            "ridge"
        ]
        assert production["refined_result"]["refined_frequency_hz"][
            "data_sha256"
        ] == hashes["refined"]
        assert production["refined_velocity_m_s"]["data_sha256"] == hashes["velocity"]
        assert production["display_velocity_m_s"]["data_sha256"] == hashes["display"]
        assert snapshot["task008a"][channel_name]["peak_to_background_db"][
            "data_sha256"
        ] == hashes["quality"]
        assert snapshot["task008b_continuity"][channel_name]["frequency_step_hz"][
            "data_sha256"
        ] == hashes["continuity"]
        assert snapshot["task008b_related_frequency"][channel_name][
            "main_to_double_frequency_db"
        ]["data_sha256"] == hashes["related"]
    assert _sha256(RAW_DATA_PATH) == raw_hash
