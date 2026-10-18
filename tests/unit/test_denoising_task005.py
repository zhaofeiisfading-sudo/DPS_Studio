"""TASK-005: observed candidates, sparse guidance and support gaps on real STFTs."""
from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec
from inspect import signature
from typing import Any

import numpy as np
import pytest

from dps_studio.core.analysis_profiles import BALANCED_PROFILE, HIGH_TIME_RESOLUTION_PROFILE
from dps_studio.core.models import SignalRecord
from dps_studio.research.task028_consolidation import frontend


def method() -> Any:
    return import_module("dps_studio.research.denoising_task005")


def test_task005_module_exists_separately_from_frozen_methods() -> None:
    assert find_spec("dps_studio.research.denoising_task005") is not None, (
        "TASK005 requires a new isolated spectral-band research module")


def physical_input(*, gap: bool = False, competitor: bool = True,
                   profile: Any = BALANCED_PROFILE) -> tuple[Any, Any, np.ndarray]:
    t = np.arange(32000) / 40e9
    frequency = 2.8e9 + 1e15 * t
    phase = 2 * np.pi * np.cumsum(frequency) / 40e9
    envelope = np.ones(len(t))
    if gap:
        envelope[(t > 320e-9) & (t < 480e-9)] = 0
    voltage = envelope * np.cos(phase)
    if competitor:
        amplitude = np.where((t > 200e-9) & (t < 600e-9), 2., .1)
        voltage += amplitude * np.cos(2 * np.pi * 1.9e9 * t + .4)
    voltage += np.random.default_rng(50001001).normal(0, .03, len(t))
    stft, peaks = frontend(SignalRecord(t, voltage), profile)
    return stft, peaks, 2.8e9 + 1e15 * stft.time_s


def test_sparse_seed_follows_long_weaker_observed_chirp() -> None:
    m = method()
    stft, peaks, truth = physical_input()
    observations = m.make_observations(stft, peaks)
    seed = m.BandSeed(time_s=150e-9, frequency_hz=2.95e9)
    result = m.track_band(observations, seed=seed)
    finite = np.isfinite(result.frequency_hz)
    assert finite.mean() > .90
    assert np.max(abs(result.frequency_hz[finite] - truth[finite])) < 100e6
    baseline = np.array([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    repaired = finite & (abs(baseline - truth) > 200e6)
    assert repaired.sum() > 60
    for i in np.flatnonzero(finite):
        c = peaks.candidates_by_frame[i][result.candidate_indices[i]]
        assert result.frequency_hz[i] == c.transition_frequency_hz
    assert result.mode == "guided"
    assert result.seed == seed
    assert np.isnan(result.validated_frequency_hz).all()


def test_no_observation_gap_is_not_filled_with_prediction() -> None:
    m = method()
    stft, peaks, _ = physical_input(gap=True)
    observation = m.make_observations(stft, peaks)
    result = m.track_band(observation, seed=m.BandSeed(150e-9, 2.95e9))
    absent = (stft.time_s > 350e-9) & (stft.time_s < 450e-9)
    assert np.isnan(result.frequency_hz[absent]).all()
    assert all("SUPPORTED" not in result.quality_flags[i] for i in np.flatnonzero(absent))


def test_clear_normal_ridge_preserves_original_candidate_values() -> None:
    m = method()
    stft, peaks, _ = physical_input(competitor=False)
    result = m.track_band(m.make_observations(stft, peaks),
                          seed=m.BandSeed(150e-9, 2.95e9))
    finite = np.isfinite(result.frequency_hz)
    baseline = np.array([frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame])
    assert finite.mean() > .95
    np.testing.assert_array_equal(result.frequency_hz[finite], baseline[finite])


def test_input_voltage_spectrum_and_peak_arrays_are_not_mutated() -> None:
    m = method()
    stft, peaks, _ = physical_input()
    old = stft.spectrum.copy()
    before = [tuple(c.transition_frequency_hz for c in frame)
              for frame in peaks.candidates_by_frame]
    observations = m.make_observations(stft, peaks)
    old_f = observations.candidate_frequency_hz.copy()
    m.track_band(observations, seed=m.BandSeed(150e-9, 2.95e9))
    np.testing.assert_array_equal(stft.spectrum, old)
    np.testing.assert_array_equal(observations.candidate_frequency_hz, old_f)
    assert before == [tuple(c.transition_frequency_hz for c in frame)
                      for frame in peaks.candidates_by_frame]


def test_unsupported_seed_returns_nan_and_quality_flags() -> None:
    m = method()
    stft, peaks, _ = physical_input()
    observations = m.make_observations(stft, peaks)
    observations = replace(observations,
                           candidate_background_db=np.full_like(
                               observations.candidate_background_db, -20.))
    result = m.track_band(observations, seed=m.BandSeed(150e-9, 2.95e9))
    assert np.isnan(result.frequency_hz).all()
    assert np.all(result.candidate_indices == -1)
    assert all("SEED_UNSUPPORTED" in flag for flag in result.quality_flags)


@pytest.mark.parametrize("time_s, frequency_hz", [(-1e-9, 3e9), (1e-6, 3e9), (150e-9, 10e9)])
def test_seed_outside_observation_domain_is_an_error(time_s: float, frequency_hz: float) -> None:
    m = method()
    stft, peaks, _ = physical_input()
    with pytest.raises(ValueError):
        m.track_band(m.make_observations(stft, peaks), seed=m.BandSeed(time_s, frequency_hz))


def test_inference_does_not_take_truth_or_a_reference_trajectory() -> None:
    m = method()
    parameters = signature(m.track_band).parameters
    assert "truth" not in parameters
    assert "baseline" not in parameters
    assert "p3" not in parameters


def test_seed_perturbation_does_not_encode_a_hand_drawn_path() -> None:
    m = method()
    stft, peaks, _ = physical_input()
    observation = m.make_observations(stft, peaks)
    a = m.track_band(observation, seed=m.BandSeed(150e-9, 2.95e9))
    b = m.track_band(observation, seed=m.BandSeed(153e-9, 2.98e9))
    common = np.isfinite(a.frequency_hz) & np.isfinite(b.frequency_hz)
    assert common.mean() > .90
    assert np.mean(a.frequency_hz[common] == b.frequency_hz[common]) > .99


def test_equal_persistent_components_do_not_identify_a_target_automatically() -> None:
    m = method()
    t = np.arange(16000) / 40e9
    voltage = np.cos(2 * np.pi * 2.4e9 * t) + np.cos(2 * np.pi * 3.4e9 * t + .7)
    stft, peaks = frontend(SignalRecord(t, voltage), BALANCED_PROFILE)
    result = m.track_band(m.make_observations(stft, peaks))
    assert np.isnan(result.frequency_hz).all()
    assert all("IDENTITY_AMBIGUOUS" in flag for flag in result.quality_flags)


def test_connected_parallel_bands_disclose_structural_branching() -> None:
    m = method()
    t = np.arange(16000) / 40e9
    voltage = np.cos(2 * np.pi * 3e9 * t) + .8 * np.cos(2 * np.pi * 3.15e9 * t + .7)
    stft, peaks = frontend(SignalRecord(t, voltage), BALANCED_PROFILE)
    result = m.track_band(m.make_observations(stft, peaks), seed=m.BandSeed(150e-9, 3e9))
    finite = np.isfinite(result.frequency_hz)
    assert finite.mean() > .9
    assert result.diagnostics["selected_component_branch_frame_count"] > 0
    assert all("BRANCHED_COMPONENT" in result.quality_flags[i] for i in np.flatnonzero(finite))
    assert all("IDENTITY_UNVALIDATED" in result.quality_flags[i] for i in np.flatnonzero(finite))


def test_research_100mhz_gate_preserves_supported_chirp_and_absence() -> None:
    m = method()
    config = m.BandConfig(max_link_delta_hz=100e6)
    for gap in (False, True):
        stft, peaks, truth = physical_input(gap=gap)
        result = m.track_band(m.make_observations(stft, peaks),
                              seed=m.BandSeed(150e-9, 2.95e9), config=config)
        finite = np.isfinite(result.frequency_hz)
        assert finite.any()
        assert np.max(abs(result.frequency_hz[finite] - truth[finite])) < 100e6
        if gap:
            absent = (stft.time_s > 350e-9) & (stft.time_s < 450e-9)
            assert np.isnan(result.frequency_hz[absent]).all()
        else:
            assert finite.mean() > .9


def test_paired_windows_preserve_original_candidates_on_a_moving_weaker_band() -> None:
    m = method()
    stft, peaks, truth = physical_input()
    other_stft, other_peaks, _ = physical_input(profile=HIGH_TIME_RESOLUTION_PROFILE)
    original = m.make_observations(stft, peaks)
    companion = m.make_observations(other_stft, other_peaks)
    result = m.track_band(original, companion=companion,
                          seed=m.BandSeed(150e-9, 2.95e9),
                          config=m.BandConfig(max_link_delta_hz=100e6))
    finite = np.isfinite(result.frequency_hz)
    assert finite.mean() > .9
    assert np.max(abs(result.frequency_hz[finite] - truth[finite])) < 100e6
    assert result.diagnostics["companion_used"] == 1
    for i in np.flatnonzero(finite):
        assert result.frequency_hz[i] == original.candidate_frequency_hz[i, result.candidate_indices[i]]
        frame = int(np.argmin(abs(companion.time_s - original.time_s[i])))
        difference = abs(companion.candidate_frequency_hz[frame] - result.frequency_hz[i])
        assert np.nanmin(difference) <= .5 * max(original.resolution_hz, companion.resolution_hz)


def test_missing_companion_evidence_abstains_without_mutating_primary_data() -> None:
    m = method()
    stft, peaks, _ = physical_input()
    original = m.make_observations(stft, peaks)
    absent = replace(original, candidate_background_db=np.full_like(
        original.candidate_background_db, -20.))
    saved = original.candidate_background_db.copy()
    result = m.track_band(original, companion=absent, seed=m.BandSeed(150e-9, 2.95e9))
    assert np.isnan(result.frequency_hz).all()
    assert np.all(result.candidate_indices == -1)
    np.testing.assert_array_equal(saved, original.candidate_background_db)


@pytest.mark.parametrize("offset_s, expected", [(0.05e-9, True), (0.051e-9, False)])
def test_companion_time_tolerance_is_inclusive_without_accepting_outside_frames(
    offset_s: float, expected: bool,
) -> None:
    m = method()
    stft, peaks, _ = physical_input(competitor=False)
    original = m.make_observations(stft, peaks)
    companion = replace(original, time_s=original.time_s + offset_s)
    result = m.track_band(original, companion=companion, seed=m.BandSeed(150e-9, 2.95e9))
    eligible = np.isfinite(original.candidate_frequency_hz) & (original.candidate_background_db >= 6)
    assert np.all(result.candidate_companion_support[eligible] == expected)
