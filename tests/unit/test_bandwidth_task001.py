"""Scientific invariants and failure cases of the opt-in TASK-001 prototype."""

from dataclasses import replace
import math
from pathlib import Path

import numpy as np
import pytest

from dps_studio.research.bandwidth_task001 import (
    AnalogCase, NoiseModel, ToneSearch, alias_frequency, analog_response,
    ar_transform, checked_input, empirical_threshold, local_model_residual,
    residual_diagnostics, spectral_baselines, stationary_noise, synthesize, train_noise,
)


@pytest.mark.parametrize("order", [1, 4])
def test_bandwidth_is_continuous_minus_three_db_not_hard_cutoff(order: int) -> None:
    assert abs(analog_response(3e9, 3e9, order)) == pytest.approx(1 / np.sqrt(2))
    assert 0 < abs(analog_response(7.8e9, 3e9, order)) < 1 / np.sqrt(2)


@pytest.mark.parametrize("rho", [0., 0.85, -0.5])
def test_precision_factor_equals_dense_stationary_covariance(rho: float) -> None:
    rng = np.random.default_rng(101)
    x = rng.normal(size=24)
    innovation_std = 0.1
    c = innovation_std**2 / (1 - rho**2) * rho**np.abs(
        np.arange(24)[:, None] - np.arange(24)[None, :]
    )
    wx = ar_transform(x, rho)
    assert float(wx @ wx) / innovation_std**2 == pytest.approx(float(x @ np.linalg.solve(c, x)))


@pytest.mark.parametrize("rho", [0., 0.85])
def test_signal_and_design_receive_same_precision_transform(rho: float) -> None:
    n, fs, f = 256, 20e9, 4.81234e9
    t = (np.arange(n) - (n - 1) / 2) / fs
    y = 0.12 * np.cos(2 * np.pi * f * t + 0.8) + 0.015
    fit = ToneSearch(n, fs, NoiseModel(rho, 0.02)).fit(y)
    assert abs(fit.frequency_hz - f) < 100
    assert fit.amplitude_v == pytest.approx(0.12, rel=1e-5)
    assert np.linalg.norm(fit.residual_v) < 1e-5
    assert fit.score > 100


def test_independent_noise_training_recovers_sampled_ou_and_does_not_mutate() -> None:
    rng = np.random.default_rng(202)
    records = np.array([stationary_noise(rng, 2048, 0.035, 0.85) for _ in range(32)])
    saved = records.copy()
    model = train_noise(records)
    assert model.rho == pytest.approx(0.85, abs=0.015)
    assert model.innovation_std_v == pytest.approx(0.035 * np.sqrt(1 - 0.85**2), rel=0.03)
    np.testing.assert_array_equal(records, saved)
    whitened = ar_transform(records[0], model.rho)
    assert abs(residual_diagnostics(whitened, 20e9)["lag1"]) < 0.1


def test_entire_search_calibration_order_and_conservative_ties() -> None:
    assert empirical_threshold(np.arange(99, dtype=float), 0.05) == 94
    assert empirical_threshold(np.zeros(99), 0.05) == 0
    assert not 0 > empirical_threshold(np.zeros(99), 0.05)
    assert math.isinf(empirical_threshold(np.arange(9, dtype=float), 0.01))
    with pytest.raises(ValueError):
        empirical_threshold(np.array([math.nan]), 0.05)


@pytest.mark.parametrize("case", [AnalogCase(response_zero=True, noise_rms_v=0.),
                                       AnalogCase(amplitude_v=0.0002, noise_rms_v=0.,
                                                  adc_step_v=0.002)])
def test_lost_information_cannot_pass_positive_detection_threshold(case: AnalogCase) -> None:
    w = synthesize(case, 303)
    assert not np.any(w.voltage_v)
    fit = ToneSearch(case.n, case.sample_rate_hz, NoiseModel(0.85, 0.02)).fit(w.voltage_v)
    assert fit.score == 0
    assert not fit.score > 10
    baseline = spectral_baselines(w.voltage_v, case.sample_rate_hz)
    assert baseline.gate_statistic_db == -math.inf


def test_alias_has_equivalent_real_samples_and_is_not_unique_analog_truth() -> None:
    fs = 20e9
    assert alias_frequency(13e9, fs) == 7e9
    t = np.arange(256) / fs
    y = np.cos(2 * np.pi * 13e9 * t)
    np.testing.assert_allclose(y, np.cos(2 * np.pi * 7e9 * t), atol=1e-12)
    fit = ToneSearch(256, fs, NoiseModel(0., 0.02)).fit(y)
    assert abs(fit.frequency_hz - 7e9) < 100
    assert abs(fit.frequency_hz - 13e9) > 5e9


def test_reproducible_adc_arrays_and_analog_truth_not_changed() -> None:
    case = AnalogCase(order=4, frequency_hz=7.8e9)
    a, b = synthesize(case, 404), synthesize(case, 404)
    np.testing.assert_array_equal(a.voltage_v, b.voltage_v)
    assert a.analog_frequency_hz == 7.8e9
    assert not np.array_equal(a.voltage_v, synthesize(case, 405).voltage_v)


def test_chirp_model_can_remove_structure_which_is_not_correlated_noise() -> None:
    case = AnalogCase(n=512, frequency_hz=1.5e9, amplitude_v=0.2,
                      noise_rho=0., noise_rms_v=0., chirp_hz_per_s=1e16)
    y = synthesize(case, 505).voltage_v
    tone, _ = local_model_residual(y, 20e9, "tone")
    chirp, parameters = local_model_residual(y, 20e9, "chirp")
    assert np.linalg.norm(chirp) < 0.25 * np.linalg.norm(tone)
    assert parameters["chirp_hz_per_s"] == pytest.approx(1e16, rel=0.1)


def test_oversampled_changing_signal_converges() -> None:
    case = AnalogCase(n=256, frequency_hz=1e9, noise_rms_v=0., am_depth=0.8)
    a, b, c = [synthesize(replace(case, oversample=s), 606).clean_v for s in (8, 16, 32)]
    assert np.linalg.norm(b - c) < np.linalg.norm(a - c)


def test_reference_sample_rate_uses_explicit_hz_search_bounds() -> None:
    fs, f = 40e9, 0.3e9
    y = 0.1 * np.cos(2 * np.pi * f * np.arange(512) / fs)
    residual, fitted = local_model_residual(y, fs, "tone")
    assert abs(fitted["frequency_hz"] - f) < 100
    assert np.linalg.norm(residual) < 1e-5


@pytest.mark.parametrize("rho,std", [(1., 0.1), (0., 0.), (math.nan, 0.1)])
def test_invalid_covariance_is_rejected(rho: float, std: float) -> None:
    with pytest.raises(ValueError):
        NoiseModel(rho, std)


def test_invalid_inputs_fail_explicitly() -> None:
    with pytest.raises(ValueError):
        train_noise(np.zeros((4, 16)))
    with pytest.raises(ValueError):
        ToneSearch(256, 10e9, NoiseModel(0., 0.1))
    search = ToneSearch(256, 20e9, NoiseModel(0., 0.1))
    with pytest.raises(ValueError):
        search.fit(np.zeros(128))
    with pytest.raises(ValueError):
        search.fit(np.full(256, math.nan))
    with pytest.raises(ValueError):
        local_model_residual(np.zeros(256), 20e9, "unknown")


def test_real_input_requires_local_raw_and_rejects_other_files(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    raw = root / "data" / "raw"
    raw.mkdir(parents=True)
    path = raw / "trace.csv"
    path.write_text("0,0\n", encoding="utf-8")
    assert checked_input(path, root) == path.resolve()
    other = tmp_path / "other.csv"
    other.write_text("0,0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        checked_input(other, root)
