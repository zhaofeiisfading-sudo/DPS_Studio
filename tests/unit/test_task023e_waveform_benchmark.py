"""Truth integration, split grouping and real-STFT validation."""

import numpy as np

from dps_studio.research.task023e_waveform_benchmark import (
    FAMILIES, PROFILES, SAMPLE_COUNT, SAMPLE_RATE_HZ, ambiguous_pair, array_hash,
    generate_case, oscillator_phase, profile_input, strongest_metrics,
)


def test_phase_increment_matches_injected_frequency_in_si():
    frequency = np.linspace(0.5e9, 5.5e9, 1000)
    phase = oscillator_phase(frequency, phase0=0.2)
    np.testing.assert_allclose(np.diff(phase) * SAMPLE_RATE_HZ / (2 * np.pi),
                               frequency[:-1], rtol=1e-11)


def test_manifest_group_split_seed_and_voltage_are_unique():
    seeds, hashes, groups = set(), set(), set()
    counts = {"CALIBRATION": 0, "FRESH_HELD_OUT": 0}
    for family in FAMILIES:
        for instance in range(24):
            case = generate_case(family, instance)
            assert case.seed not in seeds
            assert case.observation_group not in groups
            signature = array_hash(case.record.voltage_v)
            assert signature not in hashes
            seeds.add(case.seed)
            hashes.add(signature)
            groups.add(case.observation_group)
            counts[case.split] += 1
            assert case.record.sample_count == SAMPLE_COUNT
            assert np.all(np.isfinite(case.record.voltage_v))
            truth = case.truth_hz[np.isfinite(case.truth_hz)]
            assert np.all((truth >= 0.5e9) & (truth <= 5.5e9))
    assert counts == {"CALIBRATION": 64, "FRESH_HELD_OUT": 128}


def test_generation_is_reproducible_and_label_swap_does_not_change_voltage():
    np.testing.assert_array_equal(generate_case("divergence", 11).record.voltage_v,
                                  generate_case("divergence", 11).record.voltage_v)
    for index in range(16):
        a, b = ambiguous_pair(index)
        assert a.observation_group == b.observation_group
        assert a.split == b.split == "AMBIGUITY_DIAGNOSTIC"
        np.testing.assert_array_equal(a.record.voltage_v, b.record.voltage_v)
        assert np.all(a.truth_hz != b.truth_hz)


def test_real_stft_profile_axes_and_no_mutation():
    case = generate_case("correct_and_fast", 8)
    before = array_hash(case.record.voltage_v)
    for profile in PROFILES:
        stft, candidates, truth, _ = profile_input(case, profile)
        assert stft.window_length_samples == profile.window_length_samples
        assert stft.nfft == profile.nfft
        assert not stft.boundary_padding_applied
        np.testing.assert_allclose(np.diff(stft.time_s), profile.hop_samples / SAMPLE_RATE_HZ)
        np.testing.assert_allclose(np.diff(stft.frequency_hz), SAMPLE_RATE_HZ / profile.nfft)
        assert len(truth) == len(candidates.candidates_by_frame)
        assert all(len(frame) <= 20 for frame in candidates.candidates_by_frame)
    assert array_hash(case.record.voltage_v) == before


def test_pure_noise_denominator_is_not_reported_as_zero_rmse_or_perfect_precision():
    row = strongest_metrics(generate_case("dropout_noise", 9), PROFILES[0])
    assert row["truth_frames"] == 0
    assert row["rmse_hz"] is None
    assert row["wrong_branch_fraction"] is None
    assert row["intervention_precision"] is None
    assert row["intervention_harm_rate"] is None
    assert row["quality_reference_origin"] == "GENERATOR_TRUTH_NOT_ALGORITHM_DETECTION"
