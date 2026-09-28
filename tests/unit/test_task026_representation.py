"""Physical-unit, immutable-input, assignment and leakage safeguards for TASK-026."""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import GlobalPathConfig, extract_global_path_candidates
from dps_studio.research.task023e_waveform_benchmark import PROFILES, generate_case
from dps_studio.research.task026_benchmark import (
    metrics, physical_truth, registration, synthesize, unique_resolution,
)
from dps_studio.research.task026_representation import (
    METHODS, Method, estimate, raw_frames, reassignment_coordinates, squeeze_energy, stft_input,
)


def tone(frequency: float = 2.321e9, chirp: float = 0., amplitude: float = 1.) -> SignalRecord:
    t = np.arange(2048)/40e9
    tau = t-25.6e-9
    return SignalRecord(t, amplitude*np.cos(2*np.pi*(frequency*tau+.5*chirp*tau**2)))


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('profile_index', (0, 1))
def test_same_raw_time_frames_units_stationary(method: Method, profile_index: int) -> None:
    record = tone()
    voltage, time = record.voltage_v.copy(), record.time_s.copy()
    profile = PROFILES[profile_index]
    obs = estimate(record, profile, method)
    assert np.array_equal(record.voltage_v, voltage)
    assert np.array_equal(record.time_s, time)
    assert np.array_equal(obs.time_s, stft_input(record, profile).time_s)
    assert np.max(np.abs(obs.frequency_hz[:, 0]-2.321e9)) < 5e6
    assert obs.frequency_hz.shape[1] == 20
    assert np.all(np.isfinite(obs.frequency_hz[:, 0]))
    assert np.shares_memory(raw_frames(record, profile), record.voltage_v)
    assert not raw_frames(record, profile).flags.writeable


@pytest.mark.parametrize('method', METHODS)
def test_zero_energy_nan_and_quality(method: Method) -> None:
    obs = estimate(tone(amplitude=0), PROFILES[0], method)
    assert np.isnan(obs.frequency_hz).all()
    assert np.all(obs.quality_flags == 'NO_ESTIMATE')


@pytest.mark.parametrize('chirp', (-4e16, 4e16))
def test_chirplet_sign_and_si_units(chirp: float) -> None:
    record = tone(chirp=chirp)
    obs = estimate(record, PROFILES[0], 'R3')
    expected = 2.321e9+chirp*(obs.time_s-25.6e-9)
    assert np.max(np.abs(obs.frequency_hz[:, 0]-expected)) < 1e6
    assert np.max(np.abs(obs.chirp_rate_hz_per_s[:, 0]-chirp)) <= 1e16
    assert np.max(obs.residual_fraction) < .001


def test_original_baseline_exact_candidates() -> None:
    record = tone(chirp=1e16)
    profile = PROFILES[0]
    stft = stft_input(record, profile)
    original = extract_global_path_candidates(stft,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz, config=GlobalPathConfig(top_k=20))
    actual = estimate(record, profile, 'R0')
    for i, frame in enumerate(original.candidates_by_frame):
        assert np.array_equal(actual.frequency_hz[i, :len(frame)],
                              [c.transition_frequency_hz for c in frame])


def test_derivative_reassignment_and_energy_accounting() -> None:
    record = tone()
    stft = stft_input(record, PROFILES[0])
    f, t, power = reassignment_coordinates(record, PROFILES[0], stft)
    peak = np.argmax(power, axis=0)
    assert np.max(np.abs(f[peak, np.arange(len(peak))]-2.321e9)) < 1e4
    for move in (False, True):
        compressed, retained = squeeze_energy(f, t, power, stft, move_time=move)
        assert 0 < retained <= 1+1e-12
        assert np.isclose(np.sum(compressed**2)/power.sum(), retained)


@pytest.mark.parametrize(('hypotheses', 'first', 'second', 'expected'), (
    ([1e9], .95e9, 1.05e9, False),
    ([1e9, 1e9], 1e9, 1e9, False),
    ([1e9, 1.01e9], 1e9, 1.01e9, True),
    ([1e9, 1.4e9], 1e9, 1.4e9, True),
    ([1.02e9, 1.08e9], 1e9, 1.1e9, True),
    ([1.03e9, 1.08e9], 1e9, 1.1e9, False),
    ([1e9, np.nan], 1e9, 1.1e9, False),
))
def test_one_to_one_resolution(hypotheses: list[float], first: float, second: float,
                               expected: bool) -> None:
    assert unique_resolution(np.asarray(hypotheses), first, second) is expected


def test_split_seeds_core_distribution_and_latent_nuisance() -> None:
    rows = registration()
    assert len({r['seed'] for r in rows}) == len(rows)
    assert len({r['waveform'] for r in rows}) == len(rows)
    core = [r for r in rows if r['dataset'] == 'CORE']
    assert len(core) == 128
    for row in core[::16]:
        row = dict(row, seed=26990001)
        old = generate_case(row['family'], row['instance'], row['seed'])
        new = synthesize(row)
        assert np.array_equal(old.record.voltage_v, new.record.voltage_v)
        assert np.array_equal(old.truth_hz, new.truth_hz, equal_nan=True)
        assert new.split == row['split']
    row = next(r for r in core if r['family'] == 'dropout_noise')
    case = synthesize(dict(row, seed=26990002))
    _, second, _ = physical_truth(case, 'CORE', stft_input(case.record, PROFILES[0]).time_s)
    assert np.isnan(second).all()


def test_gt_cannot_enter_estimator_and_backend_not_called() -> None:
    from dps_studio.research import task026_representation as module
    assert tuple(inspect.signature(estimate).parameters) == ('record', 'profile', 'method')
    source = inspect.getsource(module)
    for forbidden in ('truth_hz', 'nuisance_hz', 'solve_global', 'optimize_smooth',
                      'beam_search', 'interp(', 'savgol', 'wiener', 'resample('):
        assert forbidden not in source


def test_failed_estimates_count_as_failures() -> None:
    obs = estimate(tone(amplitude=0), PROFILES[0], 'R0')
    truth = np.full(len(obs.time_s), 2e9)
    result = metrics(obs, truth, np.full_like(truth, np.nan), np.ones(len(truth), dtype=bool))
    assert result['failure_rate'] == 1
    assert result['candidate_recall'] == 0
    assert result['valid_estimate_fraction'] == 0


def test_nonuniform_samples_rejected_without_resampling() -> None:
    record = tone()
    t = record.time_s.copy()
    t[100] += .1/40e9
    with pytest.raises(ValueError, match='resampling'):
        raw_frames(SignalRecord(t, record.voltage_v), PROFILES[0])
