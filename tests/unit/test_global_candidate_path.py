"""TASK-021A Top-K candidate and exact global-path tests."""

from __future__ import annotations

import inspect
import itertools
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.quality import SignalDetectionConfig
from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    RidgeCandidateSet,
    RidgeConfigurationError,
    RidgeRefinementStatus,
    candidate_node_cost,
    candidate_transition_cost,
    extract_global_path_candidates,
    solve_global_candidate_path,
    track_global_candidate_path,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import analyze_stft_results


def _stft(magnitudes: np.ndarray, *, frequency_step_hz: float = 10.0) -> STFTResult:
    values = np.asarray(magnitudes, dtype=np.float64)
    if values.ndim == 1:
        values = values[:, None]
    frequency_hz = np.arange(values.shape[0], dtype=np.float64) * frequency_step_hz
    nfft = 2 * (values.shape[0] - 1)
    phase = np.exp(1j * np.linspace(0.0, 0.5, values.size).reshape(values.shape))
    return STFTResult(
        time_s=np.arange(values.shape[1], dtype=np.float64) * 1.0e-9,
        frequency_hz=frequency_hz,
        spectrum=np.asarray(values * phase, dtype=np.complex128),
        window_name="hann",
        window_length_samples=min(8, nfft),
        overlap_samples=min(4, nfft - 1),
        hop_samples=min(8, nfft) - min(4, nfft - 1),
        nfft=nfft,
        sample_rate_hz=nfft * frequency_step_hz,
        source_path=Path("synthetic.csv"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _extraction_config(**changes: object) -> GlobalPathConfig:
    base = GlobalPathConfig(
        top_k=5,
        minimum_candidate_separation_hz=15.0,
        background_exclusion_half_width_hz=10.0,
    )
    return replace(base, **changes)


def _candidate(
    frame_index: int,
    rank: int,
    frequency_hz: float,
    *,
    background_db: float = 10.0,
    competitor_db: float = 3.0,
    refined: bool = True,
) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame_index,
        time_s=frame_index * 1.0e-9,
        candidate_rank=rank,
        discrete_bin_index=int(frequency_hz // 10.0),
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=frequency_hz if refined else np.nan,
        peak_amplitude=10.0 / rank,
        peak_to_background_db=background_db,
        peak_to_competitor_db=competitor_db,
        cycles_in_window=4.0,
        is_band_boundary=False,
        refinement_status=(
            RidgeRefinementStatus.REFINED
            if refined
            else RidgeRefinementStatus.INVALID_LOCAL_PEAK
        ),
    )


def _path_config(**changes: object) -> GlobalPathConfig:
    base = GlobalPathConfig(
        top_k=5,
        minimum_candidate_separation_hz=10.0,
        background_exclusion_half_width_hz=10.0,
        background_contrast_weight=1.0,
        competitor_contrast_weight=0.0,
        cycles_weight=0.0,
        boundary_weight=0.0,
        refinement_failure_weight=0.0,
        background_reference_db=10.0,
        background_deficit_scale_db=10.0,
        frequency_step_scale_hz=100.0,
        continuity_weight=1.0,
        null_node_cost=100.0,
        null_stay_cost=0.0,
        ridge_entry_cost=0.0,
        ridge_exit_cost=0.0,
    )
    return replace(base, **changes)


def _candidate_set(
    frames: tuple[tuple[RidgeCandidate, ...], ...],
    config: GlobalPathConfig,
) -> RidgeCandidateSet:
    return RidgeCandidateSet(
        time_s=np.arange(len(frames), dtype=np.float64) * 1.0e-9,
        candidates_by_frame=frames,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=1_000.0,
        effective_candidate_separation_hz=10.0,
        effective_background_exclusion_half_width_hz=10.0,
        config=config,
        source_path=Path("synthetic.csv"),
    )


def test_top_k_local_maxima_are_ranked_by_amplitude() -> None:
    magnitudes = np.array([0.1, 3.0, 0.2, 9.0, 0.2, 7.0, 0.2, 5.0, 0.1])

    result = extract_global_path_candidates(
        _stft(magnitudes),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=80.0,
        config=_extraction_config(top_k=3),
    )

    assert [item.discrete_bin_index for item in result.candidates_by_frame[0]] == [3, 5, 7]
    assert [item.candidate_rank for item in result.candidates_by_frame[0]] == [1, 2, 3]


def test_plateau_is_represented_by_one_candidate() -> None:
    result = extract_global_path_candidates(
        _stft(np.array([0.1, 0.2, 5.0, 5.0, 5.0, 0.2, 0.1])),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=60.0,
        config=_extraction_config(minimum_candidate_separation_hz=5.0),
    )

    assert len(result.candidates_by_frame[0]) == 1
    assert result.candidates_by_frame[0][0].discrete_bin_index == 3


def test_candidate_separation_is_enforced_in_hz() -> None:
    result = extract_global_path_candidates(
        _stft(np.array([0.1, 8.0, 0.1, 7.0, 0.1, 0.2, 6.0, 0.1])),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=70.0,
        config=_extraction_config(minimum_candidate_separation_hz=25.0),
    )

    assert [item.discrete_frequency_hz for item in result.candidates_by_frame[0]] == [10.0, 60.0]
    assert result.effective_candidate_separation_hz == 25.0


def test_band_boundary_candidate_is_retained_and_penalizable() -> None:
    config = _extraction_config(boundary_weight=3.0)
    result = extract_global_path_candidates(
        _stft(np.array([9.0, 2.0, 1.0, 0.5, 0.2, 0.1])),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=50.0,
        config=config,
    )

    candidate = result.candidates_by_frame[0][0]
    assert candidate.is_band_boundary
    assert candidate.refinement_status is RidgeRefinementStatus.BOUNDARY_PEAK
    assert candidate_node_cost(candidate, config) >= 3.0


def test_null_state_exists_even_when_frame_has_candidates() -> None:
    config = _path_config()
    frames = ((_candidate(0, 1, 100.0),),)

    result = solve_global_candidate_path(_candidate_set(frames, config))

    assert result.candidate_set.candidates_by_frame[0]
    assert result.selected_candidate_rank[0] == 1


def test_clean_ridge_selects_same_frequency_as_frame_argmax() -> None:
    config = _path_config()
    frames = tuple((_candidate(index, 1, 100.0 + index),) for index in range(5))

    result = solve_global_candidate_path(_candidate_set(frames, config))

    assert np.all(result.selected_candidate_rank == 1)
    assert np.allclose(result.selected_refined_frequency_hz, np.arange(100.0, 105.0))


def test_single_stronger_distractor_does_not_force_branch_jump() -> None:
    config = _path_config()
    frames = (
        (_candidate(0, 1, 100.0),),
        (_candidate(1, 1, 500.0), _candidate(1, 2, 100.0, background_db=9.0)),
        (_candidate(2, 1, 100.0),),
    )

    result = solve_global_candidate_path(_candidate_set(frames, config))

    assert result.selected_candidate_rank.tolist() == [1, 2, 1]
    assert result.selected_refined_frequency_hz.tolist() == [100.0, 100.0, 100.0]


def test_sustained_competing_branch_keeps_lower_rank_true_path() -> None:
    config = _path_config()
    frames: list[tuple[RidgeCandidate, ...]] = []
    for index in range(10):
        if 2 <= index <= 7:
            frames.append(
                (
                    _candidate(index, 1, 500.0),
                    _candidate(index, 2, 100.0, background_db=9.5),
                )
            )
        else:
            frames.append((_candidate(index, 1, 100.0),))

    result = solve_global_candidate_path(_candidate_set(tuple(frames), config))

    assert np.all(result.selected_refined_frequency_hz == 100.0)
    assert np.count_nonzero(result.selected_candidate_rank == 2) == 6


def test_temporarily_weak_true_ridge_remains_selected() -> None:
    config = _path_config()
    frames = tuple(
        (
            (_candidate(index, 1, 500.0), _candidate(index, 2, 100.0, background_db=3.0))
            if 2 <= index <= 4
            else (_candidate(index, 1, 100.0),)
        )
        for index in range(7)
    )

    result = solve_global_candidate_path(_candidate_set(frames, config))

    assert np.all(result.selected_refined_frequency_hz == 100.0)


def test_true_dropout_enters_null_without_interpolation() -> None:
    config = _path_config(
        null_node_cost=1.0,
        ridge_entry_cost=0.2,
        ridge_exit_cost=0.2,
    )
    frames = (
        (_candidate(0, 1, 100.0),),
        (_candidate(1, 1, 100.0),),
        (),
        (),
        (_candidate(4, 1, 100.0),),
    )

    result = solve_global_candidate_path(_candidate_set(frames, config))

    assert result.is_null.tolist() == [False, False, True, True, False]
    assert np.all(np.isnan(result.selected_refined_frequency_hz[2:4]))


def test_pure_noise_without_candidates_remains_all_null() -> None:
    config = _path_config(null_node_cost=0.25)
    result = solve_global_candidate_path(_candidate_set(((), (), (), ()), config))

    assert np.all(result.is_null)
    assert np.all(result.selected_candidate_rank == 0)


def test_shock_onset_uses_null_to_candidate_transition() -> None:
    config = _path_config(null_node_cost=1.0, ridge_entry_cost=0.5)
    frames = ((), (), (_candidate(2, 1, 700.0),), (_candidate(3, 1, 700.0),))

    result = solve_global_candidate_path(_candidate_set(frames, config))

    assert result.is_null.tolist() == [True, True, False, False]
    assert result.transition_cost[2] == config.ridge_entry_cost


def test_global_recurrence_finds_exact_lowest_cost_path_when_greedy_fails() -> None:
    config = _path_config()
    frames = (
        (_candidate(0, 1, 100.0),),
        (_candidate(1, 1, 500.0), _candidate(1, 2, 100.0, background_db=5.0)),
        (_candidate(2, 1, 100.0),),
    )
    candidate_set = _candidate_set(frames, config)

    result = solve_global_candidate_path(candidate_set)
    greedy_rank = min(frames[1], key=lambda item: candidate_node_cost(item, config)).candidate_rank

    assert greedy_rank == 1
    assert result.selected_candidate_rank[1] == 2
    assert result.total_path_cost == pytest.approx(0.5)


def test_backtracking_matches_brute_force_path_cost() -> None:
    config = _path_config(null_node_cost=3.0)
    frames = (
        (_candidate(0, 1, 100.0), _candidate(0, 2, 300.0, background_db=8.0)),
        (_candidate(1, 1, 300.0), _candidate(1, 2, 100.0, background_db=8.0)),
        (_candidate(2, 1, 100.0), _candidate(2, 2, 300.0, background_db=8.0)),
    )
    result = solve_global_candidate_path(_candidate_set(frames, config))

    costs: list[float] = []
    for path in itertools.product(*(range(len(frame)) for frame in frames)):
        total = candidate_node_cost(frames[0][path[0]], config)
        for index in range(1, len(frames)):
            total += candidate_node_cost(frames[index][path[index]], config)
            total += candidate_transition_cost(
                frames[index - 1][path[index - 1]],
                frames[index][path[index]],
                config,
            )
        costs.append(total)

    assert result.total_path_cost == pytest.approx(min(costs))
    assert result.selected_candidate_rank.tolist() == [1, 2, 1]


def test_manual_event_reference_cannot_enter_global_path_api() -> None:
    parameters = inspect.signature(track_global_candidate_path).parameters

    assert "manual_event_reference_time_s" not in parameters
    assert "event_start_time_s" not in parameters


def test_changing_manual_reference_does_not_change_candidates_or_path() -> None:
    magnitudes = np.array(
        [
            [0.1, 0.1, 0.1],
            [0.2, 0.2, 0.2],
            [8.0, 8.0, 8.0],
            [0.3, 0.3, 0.3],
            [0.2, 0.2, 0.2],
            [5.0, 5.0, 5.0],
            [0.2, 0.2, 0.2],
            [0.1, 0.1, 0.1],
            [0.1, 0.1, 0.1],
        ]
    )
    stft = _stft(magnitudes)
    production_runs = tuple(
        analyze_stft_results(
            {"channel": stft},
            minimum_frequency_hz=0.0,
            maximum_frequency_hz=80.0,
            manual_event_reference_time_s=reference,
            vacuum_wavelength_m=1.55e-6,
            detection_config=SignalDetectionConfig(
                peak_exclusion_half_width_bins=1,
                minimum_consecutive_frames=1,
            ),
        )["channel"]
        for reference in (-1.0, 1.0)
    )
    results = tuple(
        track_global_candidate_path(
            analysis.stft_result,
            minimum_frequency_hz=0.0,
            maximum_frequency_hz=80.0,
            config=_extraction_config(),
        )
        for analysis in production_runs
    )

    candidate_bins = tuple(
        tuple(
            tuple(item.discrete_bin_index for item in frame)
            for frame in result.candidate_set.candidates_by_frame
        )
        for result in results
    )
    assert candidate_bins[0] == candidate_bins[1]
    assert np.array_equal(
        results[0].selected_candidate_rank,
        results[1].selected_candidate_rank,
    )
    assert np.array_equal(
        results[0].selected_refined_frequency_hz,
        results[1].selected_refined_frequency_hz,
        equal_nan=True,
    )


def test_transition_uses_hz_not_bin_count() -> None:
    config = _path_config(frequency_step_scale_hz=10.0, continuity_weight=2.0)
    previous = _candidate(0, 1, 100.0)
    current = _candidate(1, 1, 130.0)

    assert candidate_transition_cost(previous, current, config) == pytest.approx(18.0)


def test_null_frequencies_are_nan_and_rank_uses_explicit_sentinel() -> None:
    config = _path_config(null_node_cost=0.0)
    result = solve_global_candidate_path(_candidate_set(((),), config))

    assert result.selected_candidate_rank[0] == result.NULL_RANK == 0
    assert np.isnan(result.selected_discrete_frequency_hz[0])
    assert np.isnan(result.selected_refined_frequency_hz[0])


def test_extraction_and_tracking_do_not_modify_input_arrays() -> None:
    stft = _stft(np.array([[0.1, 0.2], [3.0, 4.0], [0.2, 0.2], [2.0, 1.0], [0.1, 0.1]]))
    before = stft.spectrum.copy()

    track_global_candidate_path(
        stft,
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=40.0,
        config=_extraction_config(),
    )

    assert np.array_equal(stft.spectrum, before)
    assert not stft.spectrum.flags.writeable


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"top_k": 0}, "top_k"),
        ({"top_k": True}, "top_k"),
        ({"minimum_candidate_separation_hz": 0.0}, "minimum_candidate_separation_hz"),
        ({"frequency_step_scale_hz": 0.0}, "frequency_step_scale_hz"),
        ({"continuity_weight": -1.0}, "continuity_weight"),
        ({"ridge_entry_cost": -1.0}, "ridge_entry_cost"),
    ],
)
def test_config_validation(changes: dict[str, object], message: str) -> None:
    with pytest.raises(RidgeConfigurationError, match=message):
        GlobalPathConfig(**changes)  # type: ignore[arg-type]


def test_config_metadata_is_serializable_and_marked_uncalibrated() -> None:
    metadata = GlobalPathConfig().to_metadata()

    assert metadata["top_k"] == 5
    assert metadata["development_status"] == "development / uncalibrated"


def test_candidate_generation_is_deterministic_for_fixed_seed_spectrum() -> None:
    rng = np.random.default_rng(21021)
    magnitudes = rng.uniform(0.1, 1.0, size=(32, 12))
    first = extract_global_path_candidates(
        _stft(magnitudes),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=310.0,
        config=_extraction_config(top_k=10),
    )
    second = extract_global_path_candidates(
        _stft(magnitudes),
        minimum_frequency_hz=0.0,
        maximum_frequency_hz=310.0,
        config=_extraction_config(top_k=10),
    )

    assert [
        [(item.discrete_bin_index, item.candidate_rank) for item in frame]
        for frame in first.candidates_by_frame
    ] == [
        [(item.discrete_bin_index, item.candidate_rank) for item in frame]
        for frame in second.candidates_by_frame
    ]
