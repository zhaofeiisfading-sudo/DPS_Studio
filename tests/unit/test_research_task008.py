"""Physical/numerical contracts for isolated TASK-008 waveform estimators."""
from __future__ import annotations

import importlib
from collections.abc import Callable

import numpy as np
import pytest

from dps_studio.research.waveform import common, data
from dps_studio.algorithms.waveform.acmd.implementation import correction, envelopes
from dps_studio.algorithms.waveform.matrix_pencil.implementation import poles
from dps_studio.research.waveform.runner import metric
from dps_studio.algorithms.waveform.time_domain.implementation import integrated_basis
from dps_studio.algorithms.waveform.time_domain.implementation import objective as td_objective
from dps_studio.algorithms.waveform.varpro.implementation import fit
from dps_studio.algorithms.waveform.varpro.implementation import objective as vp_objective


def test_time_validation_does_not_sort_or_resample() -> None:
    t = np.arange(2048)/40e9
    t[100] = t[99]
    with pytest.raises(ValueError, match="Nonuniform/nonmonotone"):
        common.Signal(t, np.zeros(len(t)))


def test_signal_nan_does_not_silently_remove_samples() -> None:
    x = np.zeros(2048)
    x[100] = np.nan
    with pytest.raises(ValueError, match="sample deletion forbidden"):
        common.Signal(np.arange(2048)/40e9, x)


@pytest.mark.parametrize("window", [512, 768])
def test_unchanged_formal_baselines_keep_exact_refined_and_discrete(window: int) -> None:
    case = data.generate("step", 911, development=True)
    context = common.Context(case.signal)
    result = importlib.import_module(
        f"dps_studio.algorithms.waveform.stft{window}.implementation").run(context)
    _, refined, discrete, _ = common.strongest(case.signal, window, 50e6, 6e9)
    select = context.seed_indices if window == 512 else np.arange(len(refined))
    np.testing.assert_array_equal(result.frequency_hz, refined[select])
    np.testing.assert_array_equal(result.extra["discrete_hz"], discrete[select])


@pytest.mark.parametrize("which", ["varpro", "time_domain"])
def test_analytic_varpro_gradients_against_finite_differences(which: str) -> None:
    rng = np.random.default_rng(899001)
    objective: Callable[[common.Float], tuple[float, common.Float]]
    if which == "varpro":
        tau = (np.arange(256)-128)/40e9
        y = .03*np.cos(2*np.pi*(900e6*tau+.5*2e16*tau**2)+.37)+.004
        y += rng.normal(0, .001, len(y))
        q = np.array([.91, .19])
        def vp(v: common.Float) -> tuple[float, common.Float]:
            return vp_objective(v, np.asarray(tau, dtype=np.float64), y)
        objective = vp
    else:
        _, _, basis = integrated_basis(600, 40e9, 5)
        q = np.array([.90, .93, .98, 1.02, 1.04])
        y = .03*np.cos(basis@q+.37)+rng.normal(0, .001, len(basis))
        q = q+.001
        def td(v: common.Float) -> tuple[float, common.Float]:
            return td_objective(v, y, basis)
        objective = td
    _, analytic = objective(q)
    numerical = np.zeros(len(q))
    for i in range(len(q)):
        delta = np.zeros(len(q))
        delta[i] = 1e-6
        numerical[i] = (objective(q+delta)[0]-objective(q-delta)[0])/2e-6
    np.testing.assert_allclose(analytic, numerical, rtol=2e-5, atol=2e-7)


def test_subcycle_noiseless_fit_with_nuisance_dc_and_phase() -> None:
    tau = np.asarray((np.arange(128)-63.5)/40e9, dtype=np.float64)
    f = 120e6
    y = .03*np.cos(2*np.pi*f*tau+1.1)+.017
    estimated, chirp, r2, condition, _, _ = fit(tau, y, [(100e6, 0.), (180e6, 0.)], 100)
    assert abs(estimated-f) < 1e5
    assert abs(chirp) < 1e14
    assert r2 > .999999
    assert condition < 1e5


def test_time_domain_hat_integral_is_exact_for_linear_frequency() -> None:
    nodes, hats, basis = integrated_basis(731, 40e9, 9)
    q = .5+nodes*2e16/1e9
    t = np.arange(731)/40e9
    np.testing.assert_allclose(hats@q, .5+2e16*t/1e9, rtol=1e-13)
    np.testing.assert_allclose(basis@q, 2*np.pi*(.5e9*t+.5*2e16*t*t),
                               atol=1e-12, rtol=1e-13)


def test_acmd_phase_correction_sign() -> None:
    fs = 40e9
    t = np.arange(2048)/fs
    residual_hz = 50e6
    u = .03*np.cos(2*np.pi*residual_hz*t)
    v = -.03*np.sin(2*np.pi*residual_hz*t)
    delta = correction(u, v, fs, 1e-20)
    np.testing.assert_allclose(delta[1:-1], residual_hz, rtol=2e-5)


def test_acmd_banded_envelope_solve_matches_independent_dense_normal_equations() -> None:
    n = 83
    phase = np.asarray(np.arange(n)*.21+.2, dtype=np.float64)
    x = .03*np.cos(phase+.4)
    alpha = 2.3
    u, v = envelopes(x, phase, alpha)
    design = np.zeros((n, 2*n))
    design[np.arange(n), 2*np.arange(n)] = np.cos(phase)
    design[np.arange(n), 2*np.arange(n)+1] = np.sin(phase)
    d = np.diff(np.eye(n), n=2, axis=0)
    penalty = np.zeros((2*(n-2), 2*n))
    penalty[:n-2, 0::2] = d
    penalty[n-2:, 1::2] = d
    exact = np.linalg.solve(design.T@design+alpha*penalty.T@penalty+np.eye(2*n)*1e-6,
                            design.T@x)
    np.testing.assert_allclose(u, exact[0::2], rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(v, exact[1::2], rtol=1e-10, atol=1e-12)


def test_missing_outputs_count_as_failures() -> None:
    truth = np.array([1e9, 1e9, 1e9])
    result = metric(np.array([1e9, np.nan, 1.5e9]), truth, np.ones(3, dtype=bool), "")
    assert result["failure_n"] == 2
    assert result["finite_n"] == 2
    assert result["coverage"] == pytest.approx(2/3)


def test_noise_is_never_labeled_measured_zero() -> None:
    case = data.generate("noise_only", 913, development=True)
    context = common.Context(case.signal)
    method = importlib.import_module("dps_studio.algorithms.waveform.gated_stft256.implementation")
    result = method.run(context)
    assert np.isnan(result.accepted_hz).all()
    assert not np.any(result.accepted_hz == 0)


@pytest.mark.parametrize("method", common.METHODS)
def test_estimator_keeps_input_bytes_and_exposes_missing_or_identity_flags(method: str) -> None:
    case = data.generate("step", 915, development=True)
    before = (case.signal.time_s.tobytes(), case.signal.voltage_v.tobytes())
    context = common.Context(case.signal)
    result = importlib.import_module(f"dps_studio.algorithms.waveform.{method}.implementation").run(context)
    assert len(result.frequency_hz) == len(context.centers)
    assert result.flags.shape == result.accepted_hz.shape
    assert before == (case.signal.time_s.tobytes(), case.signal.voltage_v.tobytes())
    for f, flag in zip(result.accepted_hz, result.flags, strict=True):
        if np.isfinite(f):
            assert "IDENTITY_UNVALIDATED" in flag
        else:
            assert flag


def test_raw_inventory_covers_all_thirteen_waveforms_and_excludes_results() -> None:
    items = data.inventory()
    raw = [r for r in items if r["kind"] == "RAW"]
    assert len(raw) == 13
    assert sum(r["channels"] for r in raw) == 17
    assert not any("result" in r["path"].lower() for r in raw)
    assert sum(r["kind"] == "PROCESSED_EXCLUDED" for r in items) == 5
    assert sum(r["sample_rate_hz"] > 60e9 for r in raw) == 2


def test_two_component_poles_are_not_guaranteed_by_short_window() -> None:
    # A high-SNR single tone must at least provide its positive-frequency pole.
    t = np.arange(96)/40e9
    f, _, _ = poles(np.asarray(np.cos(2*np.pi*900e6*t+.7)), 40e9)
    assert len(f) > 0
    assert np.min(abs(f-900e6)) < 5e6


def test_pencil_resolves_noiseless_dual_tones_with_dc_nuisance() -> None:
    t = np.arange(96)/40e9
    x = np.cos(2*np.pi*900e6*t+.4)+.8*np.cos(2*np.pi*980e6*t+.7)+.3
    f, _, _ = poles(x, 40e9)
    assert len(f) == 2
    np.testing.assert_allclose(np.sort(f), [900e6, 980e6], rtol=1e-6)


def test_coherent_nuisance_uses_phase_and_does_not_erase_new_tone() -> None:
    module = importlib.import_module("dps_studio.algorithms.waveform.clutter_varpro.implementation")
    t = np.arange(12800)/40e9
    nuisance = .05*np.cos(2*np.pi*450e6*t+.3)
    x = nuisance+.025*np.cos(2*np.pi*900e6*t+.2)*(t >= 60e-9)
    signal = common.Signal(t, x)
    prediction, meta = module.prefix_tone(signal)
    assert meta["prefix_r2"] > .999
    assert np.sqrt(np.mean((prediction-nuisance)**2)) < 1e-6
    np.testing.assert_allclose(x-prediction, .025*np.cos(2*np.pi*900e6*t+.2)*(t >= 60e-9),
                               atol=1e-6)
