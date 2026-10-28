"""Physical counterexamples and regression checks for the isolated TASK007 prototype."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import numpy as np
import pytest

from dps_studio.research.bandwidth_task007 import (
    FitConfig, Model, alias_candidates, apparent_velocity, fit_frame,
)
from dps_studio.research.bandwidth_task007_simulation import (
    Acquisition, regularized_inverse_gain, simulate, transfer,
)


def config(model: str = "tone") -> FitConfig:
    assert model in ("tone", "chirp")
    return FitConfig(16e9, 125e6, 7.875e9, cast(Model, model), 14.)


def acquisition() -> Acquisition:
    return Acquisition(16e9, 2e9, 4, 30., 12, 4., 8)


def test_nominal_bandwidth_is_not_a_hard_cutoff() -> None:
    response = transfer(np.array([0., 2e9, 3e9, 6e9]), acquisition())
    assert abs(response[0]) == pytest.approx(1.)
    assert abs(response[1]) == pytest.approx(1 / np.sqrt(2))
    assert 0 < abs(response[3]) < abs(response[2]) < abs(response[1])


def test_exact_zero_response_destroys_frequency_information() -> None:
    cfg = replace(acquisition(), response="zero")
    first = simulate(cfg, frequency_hz=3e9, chirp_hz_per_s=0., seed=54)
    second = simulate(cfg, frequency_hz=6e9, chirp_hz_per_s=0., seed=54)
    np.testing.assert_array_equal(first.noiseless_sampled_v, 0.)
    np.testing.assert_array_equal(first.voltage_v, second.voltage_v)


def test_reference_grid_convergence_and_analytic_attenuation() -> None:
    cfg = acquisition()
    coarse = simulate(cfg, frequency_hz=3.13e9, chirp_hz_per_s=1e15, seed=3)
    fine = simulate(replace(cfg, reference_oversampling=16), frequency_hz=3.13e9,
                    chirp_hz_per_s=1e15, seed=3)
    assert np.max(abs(coarse.noiseless_sampled_v - fine.noiseless_sampled_v)) < 1e-5
    tone = simulate(cfg, frequency_hz=3.13e9, chirp_hz_per_s=0., seed=3)
    measured_rms = np.std(tone.noiseless_sampled_v)
    expected = .2 / np.sqrt(2) * abs(transfer(np.array([3.13e9]), cfg)[0])
    assert measured_rms == pytest.approx(expected, rel=.002)


def test_aliases_require_an_external_band_prior() -> None:
    assert alias_candidates(3e9, 10e9, (0., 30e9)) == (3e9, 7e9, 13e9, 17e9, 23e9, 27e9)
    assert alias_candidates(3e9, 10e9, (6e9, 8e9)) == (7e9,)
    t = np.arange(1024) / 10e9
    np.testing.assert_allclose(np.cos(2 * np.pi * 3e9 * t),
                               np.cos(2 * np.pi * 7e9 * t), atol=2e-12)


def test_inverse_does_not_create_snr_or_fill_zeros() -> None:
    response = np.array([.5 + .1j, .01 + .002j, 0j])
    gain = regularized_inverse_gain(response, .001)
    assert gain[-1] == 0
    np.testing.assert_allclose(abs(gain[:2] * response[:2])**2 / abs(gain[:2])**2,
                               abs(response[:2])**2)
    assert np.max(abs(gain)) <= 1 / (2 * np.sqrt(.001))


@pytest.mark.parametrize("model", ["tone", "chirp"])
def test_local_estimator_recovers_observable_subbin_tone_without_mutation(model: str) -> None:
    t = np.arange(256) / 16e9
    rng = np.random.default_rng(17)
    voltage = .1 * np.cos(2 * np.pi * 3.123e9 * t + .2) + rng.normal(0, .005, len(t))
    saved = voltage.copy()
    result = fit_frame(voltage, config(model))
    np.testing.assert_array_equal(voltage, saved)
    assert abs(result.frequency_hz - 3.123e9) < 1e6
    assert 0 < result.sigma_hz < 1e6
    assert result.provenance == "estimated_from_waveform"


def test_chirp_is_fitted_locally_and_competing_lines_are_rejected() -> None:
    u = (np.arange(256) - 128) / 16e9
    rng = np.random.default_rng(18)
    y = .1 * np.cos(2 * np.pi * (3.1e9 * u + .5 * 1.1e16 * u**2))
    y += rng.normal(0, .004, len(u))
    fitted = fit_frame(y, config("chirp"))
    assert abs(fitted.frequency_hz - 3.1e9) < 1e6
    assert fitted.chirp_hz_per_s == pytest.approx(1.1e16, rel=.03)
    competitor = .1 * np.cos(2 * np.pi * 2e9 * u) + .08 * np.cos(2 * np.pi * 4e9 * u)
    rejected = fit_frame(competitor, config())
    assert np.isnan(rejected.frequency_hz)
    assert "COMPETING_COMPONENT" in rejected.flag
    assert np.isfinite(rejected.candidate_frequency_hz)


def test_noise_and_constant_frames_are_not_turned_into_smooth_predictions() -> None:
    assert np.isnan(fit_frame(np.ones(256), config()).frequency_hz)
    rng = np.random.default_rng(700777)
    accepted = sum(np.isfinite(fit_frame(rng.normal(size=256), config()).frequency_hz)
                   for _ in range(40))
    assert accepted <= 2  # independent null regression, not a claimed confidence bound


def test_explicit_velocity_and_unknown_window_correction_separation() -> None:
    v = apparent_velocity(np.array([3e9, np.nan]), wavelength_m=1550e-9,
                          optical_offset_hz=1e9, signed_beat_branch=1)
    assert v[0] == pytest.approx(1550.)
    assert np.isnan(v[1])
    with pytest.raises(ValueError):
        apparent_velocity(np.array([3e9]), wavelength_m=np.nan,
                          optical_offset_hz=0., signed_beat_branch=1)


@pytest.mark.parametrize("change", [{"sample_rate_hz": -1.}, {"maximum_frequency_hz": 8e9},
                                   {"detection_threshold": np.nan}])
def test_invalid_fit_configuration_is_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(config(), **change)


def test_nonfinite_or_short_waveforms_are_not_repaired() -> None:
    with pytest.raises(ValueError):
        fit_frame(np.full(256, np.nan), config())
    with pytest.raises(ValueError):
        fit_frame(np.ones(8), config())
