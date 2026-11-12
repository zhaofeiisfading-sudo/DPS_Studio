"""Known waveform tests; no experimental motion ground truth is assumed."""

from __future__ import annotations

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.physics.dechirp import DechirpSettings, estimate_dechirp

FS = 40e9
LAMBDA = 1550e-9


@pytest.mark.parametrize("rate", [-6.25e16, 0.0, 7.65e16])
def test_dechirp_recovers_slope_from_voltage_with_constant_frequency_seed(rate: float) -> None:
    t = 143e-6 + np.arange(1024) / FS
    tau = t - t[512]
    f0 = 2.15e9
    voltage = 0.4 + 0.15 * np.cos(0.71 + 2*np.pi*f0*tau + np.pi*rate*tau**2)
    centers = t[[448, 512, 576]]
    result = estimate_dechirp(
        SignalRecord(t, voltage), centers, np.full(3, f0), vacuum_wavelength_m=LAMBDA,
    )
    assert result.flags == ("accepted",) * 3
    np.testing.assert_array_equal(result.time_s, centers)
    np.testing.assert_allclose(result.frequency_hz, f0 + rate * (centers-t[512]), atol=3000)
    np.testing.assert_allclose(result.rate_hz_s, rate, atol=3e11)
    np.testing.assert_allclose(result.apparent_acceleration_m_s2, LAMBDA * rate / 2, atol=3e5)
    assert min(result.r2) > .9999


def test_boundaries_candidates_and_weak_voltage_have_distinct_flags() -> None:
    t = 20e-6 + np.arange(4096) / FS
    rng = np.random.default_rng(2100)
    voltage = rng.normal(0, 0.3, t.size)
    centers = t[[64, 512, 1024, 3072]]
    result = estimate_dechirp(
        SignalRecord(t, voltage), centers, np.array([2e9, 2e9, np.nan, 2e9]),
        vacuum_wavelength_m=LAMBDA, boundaries_s=(float(t[590]),),
    )
    assert result.flags == ("window_edge", "crosses_boundary", "candidate_missing", "weak_model")
    assert np.isnan(result.apparent_acceleration_m_s2).all()


def test_rejects_resolved_competing_tone_and_seed_jump() -> None:
    t = np.arange(4096) / FS
    phase = 2*np.pi*2.1e9*t
    competing = np.cos(phase) + 0.78*np.cos(2*np.pi*3.2e9*t + .3)
    result = estimate_dechirp(
        SignalRecord(t, competing), t[[512, 1200, 1328]], np.array([2.1e9, 2.1e9, 3.2e9]),
        vacuum_wavelength_m=LAMBDA, settings=DechirpSettings(window_samples=512),
    )
    assert result.flags == ("competing_component", "crosses_boundary", "crosses_boundary")
    assert np.isnan(result.rate_hz_s).all()


def test_explicit_boundary_splits_a_frequency_step() -> None:
    t = np.arange(2048) / FS
    before = np.cos(2*np.pi*1.6e9*(t-t[1024]))
    after = np.cos(2*np.pi*2.0e9*(t-t[1024]))
    result = estimate_dechirp(
        SignalRecord(t, np.where(t < t[1024], before, after)),
        t[[512, 960, 1088, 1536]], np.array([1.6e9, 1.6e9, 2.0e9, 2.0e9]),
        vacuum_wavelength_m=LAMBDA, boundaries_s=(float(t[1024]),),
    )
    assert result.flags == ("accepted", "crosses_boundary", "crosses_boundary", "accepted")
    np.testing.assert_allclose(result.rate_hz_s[[0, 3]], 0, atol=3e11)
