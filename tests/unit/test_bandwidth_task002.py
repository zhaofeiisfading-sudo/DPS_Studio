"""Identifiability, search-range, and statistical invariants for TASK-002."""

from dataclasses import replace
import math

import numpy as np
import pytest

from dps_studio.core.analysis_profiles import (
    AnalysisParameterOverrides, BALANCED_PROFILE, build_analysis_run_parameters,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import extract_peak_ridge
from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.research.bandwidth_task001 import AnalogCase, NoiseModel, ToneSearch
from dps_studio.research.bandwidth_task002 import (
    Acceptance, FS, WINDOWS, WideToneSearch, Window, acquire, binomial_bounds,
    frame_stft, noise_psd_v2_per_hz, reliable_boundary, spectral_frame,
)


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("frequency", [8e9, 18e9])
def test_existing_stft_range_is_parameter_only(window: Window, frequency: float) -> None:
    case = AnalogCase(sample_rate_hz=FS, n=window.n, frequency_hz=frequency,
                      amplitude_v=.04, noise_rms_v=0.)
    y = acquire(case, 904, ideal=True).voltage_v
    before = y.copy()
    stft = frame_stft(y, FS, window)
    assert stft.frequency_hz[-1] == pytest.approx(20e9)
    assert stft.hop_samples == window.hop
    result = spectral_frame(stft)
    assert result.default_peak_hz <= 6e9
    assert abs(result.wide_peak_hz-frequency) <= FS/window.nfft/2
    assert abs(result.wide_refined_hz-frequency) < 1e6
    np.testing.assert_array_equal(y, before)


def test_run_override_validates_high_frequency_and_keeps_default() -> None:
    p = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE, base_vacuum_wavelength_m=1550e-9,
        overrides=AnalysisParameterOverrides(maximum_frequency_hz=19.5e9),
    )
    record = SignalRecord(time_s=np.arange(800)/FS, voltage_v=np.zeros(800))
    p.validate_for_records({"synthetic": record})
    assert p.maximum_frequency_hz == 19.5e9
    assert BALANCED_PROFILE.maximum_frequency_hz == 6e9
    bad = build_analysis_run_parameters(
        base_profile=BALANCED_PROFILE, base_vacuum_wavelength_m=1550e-9,
        overrides=AnalysisParameterOverrides(maximum_frequency_hz=20.1e9),
    )
    with pytest.raises(ValueError, match="exceeds"):
        bad.validate_for_records({"synthetic": record})


def test_wide_likelihood_is_same_task001_fit_at_same_grid() -> None:
    model = NoiseModel(.85, .02)
    y = np.random.default_rng(114).normal(0, .035, 128)
    old = ToneSearch(128, 20e9, model)
    wide = WideToneSearch(128, 20e9, model, minimum_hz=.2e9, maximum_hz=9.5e9)
    np.testing.assert_array_equal(old.grid, wide.grid)
    a, b = old.fit(y), wide.fit(y)
    assert a.frequency_hz == b.frequency_hz
    assert a.score == b.score
    np.testing.assert_array_equal(a.residual_v, b.residual_v)


@pytest.mark.parametrize("maximum", [20e9, 23e9, math.inf, -1.])
def test_search_does_not_produce_above_nyquist_claims(maximum: float) -> None:
    with pytest.raises(ValueError):
        WideToneSearch(128, FS, NoiseModel(.85, .02), maximum_hz=maximum)


def test_analog_alias_is_not_unwrapped_by_truth() -> None:
    case = AnalogCase(sample_rate_hz=FS, n=512, frequency_hz=23e9,
                      amplitude_v=.1, noise_rms_v=0.)
    wave = acquire(case, 95, ideal=True)
    assert wave.digital_frequency_hz == 17e9
    result = spectral_frame(frame_stft(wave.voltage_v, FS, WINDOWS[2]))
    fit = WideToneSearch(512, FS, NoiseModel(.85, .02)).fit(wave.voltage_v)
    assert abs(result.wide_refined_hz-17e9) < 1e6
    assert abs(fit.frequency_hz-17e9) < 100
    assert abs(fit.frequency_hz-case.frequency_hz) > 1e9


def test_zero_response_and_quantization_remove_information() -> None:
    base = AnalogCase(sample_rate_hz=FS, n=128, frequency_hz=12e9,
                      amplitude_v=.0005, noise_rms_v=0.)
    for ideal in (False, True):
        erased = acquire(replace(base, response_zero=True), 18, ideal=ideal)
        np.testing.assert_array_equal(erased.voltage_v, np.zeros(128))
    quantized = acquire(replace(base, adc_step_v=.002), 19, ideal=True)
    np.testing.assert_array_equal(quantized.voltage_v, np.zeros(128))
    result = spectral_frame(frame_stft(quantized.voltage_v, FS, WINDOWS[0]))
    assert result.wide_score_db == -math.inf


def test_statistical_boundary_requires_prefix_and_null_bound() -> None:
    rule = Acceptance()
    assert reliable_boundary([3e9, 5e9, 8e9], [400, 300, 400], [400]*3, 0, 4096, rule) == 3e9
    assert reliable_boundary([3e9, 5e9], [400, 400], [400]*2, 0, 4096, rule) == 5e9
    assert reliable_boundary([3e9], [300], [400], 0, 4096, rule) is None
    assert reliable_boundary([3e9], [400], [400], 100, 4096, rule) is None
    # Zero false accepts among 96 records cannot substantiate a 1% risk bound.
    assert reliable_boundary([3e9], [400], [400], 0, 96, rule) is None
    assert binomial_bounds(0, 4096, rule.tail)[1] < .01


@pytest.mark.parametrize("frequencies", [[5e9, 3e9], [3e9, 3e9], []])
def test_boundary_rejects_misordered_or_empty_grid(frequencies: list[float]) -> None:
    with pytest.raises(ValueError):
        reliable_boundary(frequencies, [400]*len(frequencies), [400]*len(frequencies),
                          0, 4096, Acceptance())


@pytest.mark.parametrize("counts", [(-1, 2), (3, 2), (0, 0)])
def test_binomial_invalid_counts(counts: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        binomial_bounds(*counts)


def test_noise_psd_integrates_to_declared_rms() -> None:
    f = np.linspace(0, FS/2, 100001)
    for rho in (0., .85):
        psd = noise_psd_v2_per_hz(f, FS, .035, rho)
        assert np.trapezoid(psd, f) == pytest.approx(.035**2, rel=1e-6)


def test_peak_validation_uses_grid_boundary() -> None:
    stft = frame_stft(np.ones(128), FS, WINDOWS[0])
    with pytest.raises(RidgeConfigurationError, match="exceeds"):
        extract_peak_ridge(stft, minimum_frequency_hz=.05e9, maximum_frequency_hz=21e9)


def test_window_and_acceptance_invalid_contracts() -> None:
    with pytest.raises(ValueError):
        Window("invalid", 512, 384, 256, 4096)
    with pytest.raises(ValueError):
        Acceptance(tolerance_hz=-1)
