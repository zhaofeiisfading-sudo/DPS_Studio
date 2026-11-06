"""Independent physical, numerical, information and missing-data contracts."""
from __future__ import annotations

import numpy as np
import pytest

from artifacts.research_clean_task13.repro.cases import VELOCITY, fresh, specifications
from artifacts.research_clean_task13.repro.experiment import metric
from artifacts.research_clean_task13.repro.stage import (
    Annotation, chirp_objective, frozen_estimate, grid, linear_fit, local_estimate,
    quality_gate, recommended, support,
)
from dps_studio.algorithms.task008.common import Signal, strongest


def tone(frequency: float, phase: float = .7) -> Signal:
    time = np.arange(4096, dtype=np.float64) / 40e9
    voltage = .04 * np.cos(2 * np.pi * frequency * time + phase) + .008 + 2e4 * time
    return Signal(time, voltage)


def plan(signal: Signal) -> tuple[Annotation, ...]:
    return (Annotation(0., float(signal.time_s[-1] + 1 / signal.fs), "plateau"),)


def test_analytic_variable_projection_gradient() -> None:
    tau = np.arange(-200, 212, dtype=np.float64) / 40e9
    y = .035 * np.cos(2 * np.pi * (700e6 * tau + .5 * 3e16 * tau**2) + .8) + .005
    q = np.array([.68, .25])
    _, gradient = chirp_objective(q, tau, y)
    numeric = []
    for j in range(2):
        step = np.zeros(2)
        step[j] = 1e-6
        numeric.append((chirp_objective(q + step, tau, y)[0]
                        - chirp_objective(q - step, tau, y)[0]) / 2e-6)
    np.testing.assert_allclose(gradient, numeric, rtol=2e-5, atol=2e-7)


@pytest.mark.parametrize("width", [512, 768])
def test_original_stft_candidate_is_unchanged(width: int) -> None:
    signal = tone(550e6)
    time, frequency, _, _ = strongest(signal, width, 50e6, 6e9)
    result = frozen_estimate(signal, f"stft{width}")
    take = np.searchsorted(time, signal.time_s[grid(signal)])
    np.testing.assert_allclose(result.candidate_hz, frequency[take], atol=1e-3, rtol=1e-12)


def test_original_stft_uses_integer_samples_with_absolute_acquisition_time() -> None:
    base = tone(550e6)
    time = np.array(base.time_s) - 4.1e-6
    time += 1e-18 * np.sin(np.arange(len(time)))
    signal = Signal(time, np.array(base.voltage_v))
    _, frequency, _, _ = strongest(signal, 768, 50e6, 6e9)
    result = frozen_estimate(signal, "stft768")
    np.testing.assert_allclose(result.candidate_hz, frequency[(grid(signal) - 384) // 128],
                               atol=1e-3, rtol=1e-12)


@pytest.mark.parametrize("phase", [0., .7, 1.5, 3.1])
def test_long_profile_recovers_observable_tone_with_unknown_linear_baseline(phase: float) -> None:
    signal = tone(30. / VELOCITY, phase)
    result = local_estimate(signal, plan(signal), "profile2048")
    assert np.isfinite(result.accepted_hz).mean() > .8
    np.testing.assert_allclose(result.accepted_hz, 30. / VELOCITY, rtol=1e-5, atol=50.)


def test_subcycle_fit_is_not_claimed_as_velocity_measurement() -> None:
    signal = tone(15. / VELOCITY)
    result = local_estimate(signal, plan(signal), "profile512")
    assert np.isnan(result.accepted_hz).all()
    assert any("UNOBSERVABLE" in flag for flag in result.quality)


def test_exact_stationary_dc_or_linear_voltage_cannot_become_measured_zero() -> None:
    signal = tone(0.)
    result = local_estimate(signal, plan(signal), "profile2048")
    assert np.isnan(result.accepted_hz).all()
    assert not np.any(result.candidate_hz == 0.)
    tau = np.arange(512, dtype=np.float64) / signal.fs
    _, _, r2, _ = linear_fit(tau, np.full(512, .01), 500e6)
    assert r2 == 0.


def test_manual_support_never_reads_across_boundary() -> None:
    signal = tone(600e6)
    boundary = float(signal.time_s[2048])
    manual = (Annotation(0., boundary, "plateau"),
              Annotation(boundary, float(signal.time_s[-1] + 1 / signal.fs), "plateau"))
    altered = np.array(signal.voltage_v)
    altered[2048:] += np.random.default_rng(13).normal(size=2048)
    changed = Signal(np.array(signal.time_s), altered)
    first = local_estimate(signal, manual, "profile2048")
    second = local_estimate(changed, manual, "profile2048")
    before = grid(signal) < 2048
    np.testing.assert_array_equal(first.accepted_hz[before], second.accepted_hz[before])
    tau, y = support(signal, 1920, 2048, manual[0])
    assert len(y) == 1152
    assert signal.time_s[1920] + tau[-1] < boundary


def test_no_estimate_control_cannot_win_by_conditional_rmse() -> None:
    truth = np.array([1e9, 1e9, 1e9])
    row = metric(np.array([1e9, np.nan, 2e9]), truth, np.full(3, np.nan), np.ones(3, dtype=bool))
    assert row["target_n"] == 3
    assert row["finite_n"] == 2
    assert row["failure_n"] == 2
    missing = metric(np.full(3, np.nan), truth, np.full(3, np.nan), np.ones(3, dtype=bool))
    assert missing["rmse_m_s"] is None
    assert missing["failure_fraction"] == 1.


def test_slope_prior_and_observability_have_explicit_route_provenance() -> None:
    assert recommended(Annotation(0., 1., "stationary")) == "unobservable"
    assert recommended(Annotation(0., 1., "low_frequency")) == "profile2048"
    assert recommended(Annotation(0., 1., "decline")) == "bounded_chirp512"
    assert recommended(Annotation(0., 1., "rebound")) == "bounded_chirp512"
    assert recommended(Annotation(0., 1., "weak_signal", "weak", True)) == "clutter_varpro"
    assert recommended(Annotation(0., 1., "unknown")) == "stft768"


def test_training_and_independent_test_waveforms_and_seeds_differ() -> None:
    dev = fresh("fast_accel", 0, development=True)
    heldout = fresh("fast_accel", 0)
    assert dev.metadata["seed"] != heldout.metadata["seed"]
    assert not np.array_equal(dev.signal.voltage_v, heldout.signal.voltage_v)
    assert len(specifications()) == 290


def test_all_development_and_evaluation_random_streams_are_disjoint_across_families() -> None:
    from artifacts.research_clean_task13.repro.cases import load

    development = {load(spec).metadata["seed"] for spec in specifications(development=True)}
    evaluation = {load(spec).metadata["seed"] for spec in specifications() if spec[0] == "independent"}
    assert len(development) == 36
    assert len(evaluation) == 144
    assert development.isdisjoint(evaluation)


def test_all_local_estimators_leave_voltage_and_time_bytes_unchanged() -> None:
    signal = tone(800e6)
    before = signal.time_s.tobytes(), signal.voltage_v.tobytes()
    for name in ("clip_stft512", "clip_stft2048", "profile512", "profile2048", "bounded_chirp512"):
        result = local_estimate(signal, plan(signal), name)
        assert result.accepted_hz.shape == grid(signal).shape
        assert not np.isinf(result.accepted_hz).any()
    assert before == (signal.time_s.tobytes(), signal.voltage_v.tobytes())


def test_profile_gate_checks_instantaneous_frequency_at_support_edges() -> None:
    tau = np.arange(-256, 256, dtype=np.float64) / 40e9
    y = np.cos(2 * np.pi * (100e6 * tau + .5 * 8e16 * tau**2))
    accepted, flag, _, _ = quality_gate(tau, y, 100e6, 8e16)
    assert not accepted
    assert flag == "LOW_WAVEFORM_SUPPORT"
