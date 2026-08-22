"""Ground-truth acceptance tests for all TASK-021A synthetic cases."""

from __future__ import annotations

import numpy as np
import pytest

from dps_studio.core.ridge import GlobalPathConfig
from dps_studio.research.global_path_benchmark import (
    generate_synthetic_global_path_cases,
    run_synthetic_global_path_benchmark,
)


def _global_metrics(result: object) -> object:
    return next(
        item
        for item in result.metrics  # type: ignore[attr-defined]
        if item.method == "task021a_global_path"
    )


@pytest.fixture(scope="module")
def benchmark_results() -> tuple[object, ...]:
    return run_synthetic_global_path_benchmark(config=GlobalPathConfig(top_k=5))


def test_fixed_seed_cases_are_deterministic_and_complete() -> None:
    first = generate_synthetic_global_path_cases(seed=21021)
    second = generate_synthetic_global_path_cases(seed=21021)

    assert [item.case_id[0] for item in first] == list("ABCDEFGH")
    assert all(
        np.array_equal(left.stft_result.spectrum, right.stft_result.spectrum)
        for left, right in zip(first, second)
    )


def test_case_a_clean_global_is_not_worse_than_argmax(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[0]
    argmax, _, global_metrics = result.metrics  # type: ignore[attr-defined]

    assert global_metrics.frequency_rmse_hz <= argmax.frequency_rmse_hz * 1.1
    assert global_metrics.wrong_branch_frame_count == 0


def test_case_b_isolated_distractor_selects_rank_two(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[1]
    argmax, _, global_metrics = result.metrics  # type: ignore[attr-defined]

    assert argmax.wrong_branch_frame_count == 2
    assert global_metrics.wrong_branch_frame_count == 0
    assert np.count_nonzero(result.global_path.selected_candidate_rank == 2) == 2  # type: ignore[attr-defined]


def test_case_c_sustained_branch_is_globally_rejected(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[2]
    global_metrics = _global_metrics(result)

    assert global_metrics.wrong_branch_frame_count == 0  # type: ignore[attr-defined]
    assert global_metrics.rank_2_fraction > 0.5  # type: ignore[attr-defined]


def test_case_d_weak_true_ridge_stays_on_lower_rank_candidate(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[3]
    global_metrics = _global_metrics(result)

    assert global_metrics.wrong_branch_frame_count == 0  # type: ignore[attr-defined]
    assert global_metrics.rank_2_fraction > 0.0  # type: ignore[attr-defined]


def test_case_e_dropout_is_null_and_recovers_without_fill(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[4]
    global_metrics = _global_metrics(result)
    dropout = result.case.dropout_mask  # type: ignore[attr-defined]

    assert np.all(result.global_path.is_null[dropout])  # type: ignore[attr-defined]
    assert global_metrics.recovery_after_dropout_frames == 0  # type: ignore[attr-defined]


def test_case_f_onset_enters_from_null_without_false_pre_event_detection(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[5]
    global_metrics = _global_metrics(result)

    assert global_metrics.false_pre_event_detection_count == 0  # type: ignore[attr-defined]
    assert np.all(result.global_path.is_null[:20])  # type: ignore[attr-defined]
    assert not result.global_path.is_null[20]  # type: ignore[attr-defined]


def test_case_g_plateau_unloading_is_not_over_smoothed(
    benchmark_results: tuple[object, ...],
) -> None:
    global_metrics = _global_metrics(benchmark_results[6])

    assert global_metrics.valid_selected_coverage == 1.0  # type: ignore[attr-defined]
    assert global_metrics.frequency_rmse_hz < 1.0e6  # type: ignore[attr-defined]


def test_case_h_pure_noise_is_all_null(
    benchmark_results: tuple[object, ...],
) -> None:
    result = benchmark_results[7]
    global_metrics = _global_metrics(result)

    assert np.all(result.global_path.is_null)  # type: ignore[attr-defined]
    assert global_metrics.null_fraction == 1.0  # type: ignore[attr-defined]


@pytest.mark.parametrize("top_k", [3, 5, 10])
def test_required_top_k_values_run_deterministically(top_k: int) -> None:
    first = run_synthetic_global_path_benchmark(config=GlobalPathConfig(top_k=top_k))
    second = run_synthetic_global_path_benchmark(config=GlobalPathConfig(top_k=top_k))

    assert all(
        np.array_equal(
            left.global_path.selected_candidate_rank,
            right.global_path.selected_candidate_rank,
        )
        for left, right in zip(first, second)
    )
    for result in first:
        metrics = _global_metrics(result)
        total = (
            metrics.rank_1_fraction  # type: ignore[attr-defined]
            + metrics.rank_2_fraction  # type: ignore[attr-defined]
            + metrics.rank_3_fraction  # type: ignore[attr-defined]
            + metrics.rank_4_plus_fraction  # type: ignore[attr-defined]
            + metrics.null_fraction  # type: ignore[attr-defined]
        )
        assert total == pytest.approx(1.0)
