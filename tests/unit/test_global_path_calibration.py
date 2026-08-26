"""TASK-021B Research-only DP-cost audit and calibration regression tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    RidgeCandidateSet,
    RidgeRefinementStatus,
    solve_global_candidate_path,
)
from dps_studio.research.global_path_benchmark import run_synthetic_global_path_benchmark
from dps_studio.research.global_path_calibration import (
    audit_global_candidate_path,
    audit_matches_global_path_result,
    audit_rows,
    calibration_metrics,
    candidate_set_for_top_k,
    research_aggressiveness_presets,
)


def _candidate(frame_index: int, rank: int, frequency_hz: float) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame_index,
        time_s=frame_index * 1.0e-9,
        candidate_rank=rank,
        discrete_bin_index=int(frequency_hz // 10.0),
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=frequency_hz,
        peak_amplitude=10.0 / rank,
        peak_to_background_db=20.0,
        peak_to_competitor_db=10.0,
        cycles_in_window=4.0,
        is_band_boundary=False,
        refinement_status=RidgeRefinementStatus.REFINED,
    )


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


def _auditable_config(**changes: float | int) -> GlobalPathConfig:
    base = GlobalPathConfig(
        top_k=20,
        minimum_candidate_separation_hz=10.0,
        background_exclusion_half_width_hz=10.0,
        background_contrast_weight=0.0,
        competitor_contrast_weight=0.0,
        cycles_weight=0.0,
        boundary_weight=0.0,
        refinement_failure_weight=0.0,
        continuity_weight=0.0,
        null_node_cost=0.25,
        null_stay_cost=0.0,
        ridge_entry_cost=0.1,
        ridge_exit_cost=0.1,
    )
    return replace(base, **changes)


@pytest.mark.parametrize("top_k", [5, 10, 15, 20])
def test_calibration_presets_support_required_top_k(top_k: int) -> None:
    presets = research_aggressiveness_presets(top_k=top_k)

    assert set(presets) == {"conservative", "balanced", "permissive"}
    assert all(config.top_k == top_k for config in presets.values())
    assert presets["conservative"] == GlobalPathConfig(top_k=top_k)
    assert presets["balanced"].null_node_cost > presets["conservative"].null_node_cost
    assert presets["permissive"].ridge_entry_cost < presets["balanced"].ridge_entry_cost


def test_fixed_maximum_candidate_cloud_has_deterministic_lower_k_prefixes() -> None:
    maximum_config = _auditable_config()
    maximum = _candidate_set(
        (
            (_candidate(0, 1, 100.0), _candidate(0, 2, 200.0), _candidate(0, 3, 300.0)),
            (_candidate(1, 1, 100.0), _candidate(1, 2, 200.0), _candidate(1, 3, 300.0)),
        ),
        maximum_config,
    )
    lower_config = _auditable_config(top_k=2)

    first = candidate_set_for_top_k(maximum, config=lower_config)
    second = candidate_set_for_top_k(maximum, config=lower_config)

    assert first.config == lower_config
    assert [[candidate.candidate_rank for candidate in frame] for frame in first.candidates_by_frame] == [
        [1, 2],
        [1, 2],
    ]
    assert first.candidates_by_frame == second.candidates_by_frame


def test_cost_audit_exactly_matches_solver_and_margin_sign() -> None:
    config = _auditable_config(top_k=2)
    candidate_set = _candidate_set(
        ((_candidate(0, 1, 100.0),), (_candidate(1, 1, 100.0),)),
        config,
    )
    result = solve_global_candidate_path(candidate_set)
    audit = audit_global_candidate_path(candidate_set)

    assert audit_matches_global_path_result(audit, result)
    assert result.selected_candidate_rank.tolist() == [1, 1]
    assert audit.candidate_vs_null_cost_margin[0] == pytest.approx(-0.15)
    assert np.all(audit.candidate_vs_null_cost_margin < 0.0)


def test_audit_rows_expose_every_candidate_and_null_state() -> None:
    config = _auditable_config(top_k=2)
    candidate_set = _candidate_set(((_candidate(0, 1, 100.0),), ()), config)
    audit = audit_global_candidate_path(candidate_set)
    rows = audit_rows(audit)
    null_rows = [row for row in rows if row["state_type"] == "NULL"]

    assert len(rows) == 3
    assert len(null_rows) == 2
    assert null_rows[0]["time_s"] == pytest.approx(0.0)
    assert {
        "node_cost",
        "transition_cost",
        "cumulative_cost",
        "winning_predecessor",
        "null_node_cost",
        "null_transition_cost",
        "null_cumulative_cost",
    } <= set(null_rows[1])
    assert {
        "candidate_vs_null_cost_margin",
        "selected_state",
        "selected_cumulative_cost",
        "selected_winning_predecessor",
    } <= set(rows[0])


def test_permissive_preset_keeps_explicit_null_path() -> None:
    config = research_aggressiveness_presets(top_k=5)["permissive"]
    result = solve_global_candidate_path(_candidate_set(((), (), ()), config))

    assert np.all(result.is_null)
    assert np.all(result.selected_candidate_rank == 0)


def test_calibration_metrics_include_required_competition_and_coverage_fields() -> None:
    config = _auditable_config(top_k=2)
    candidate_set = _candidate_set(
        ((_candidate(0, 1, 100.0),), (_candidate(1, 1, 100.0),)),
        config,
    )
    result = solve_global_candidate_path(candidate_set)
    metrics = calibration_metrics(
        result=result,
        audit=audit_global_candidate_path(candidate_set),
        production_frequency_hz=np.array([100.0, 100.0]),
        pre_event_reference_time_s=1.0e-9,
    ).to_metadata()

    assert metrics["candidate_available_fraction"] == 1.0
    assert metrics["null_fraction"] == 0.0
    assert metrics["median_candidate_vs_null_cost_margin"] < 0.0
    assert metrics["longest_continuous_selected_segment"] == 2
    assert metrics["pre_event_non_null_fraction"] == 1.0


@pytest.fixture(scope="module")
def permissive_benchmarks() -> tuple[object, ...]:
    return run_synthetic_global_path_benchmark(
        config=research_aggressiveness_presets(top_k=20)["permissive"]
    )


def test_permissive_regression_keeps_pure_noise_null(
    permissive_benchmarks: tuple[object, ...],
) -> None:
    pure_noise = permissive_benchmarks[7]

    assert np.all(pure_noise.global_path.is_null)  # type: ignore[attr-defined]


def test_permissive_regression_preserves_dropout_and_onset(
    permissive_benchmarks: tuple[object, ...],
) -> None:
    dropout = permissive_benchmarks[4]
    onset = permissive_benchmarks[5]

    assert np.all(dropout.global_path.is_null[dropout.case.dropout_mask])  # type: ignore[attr-defined]
    assert np.all(onset.global_path.is_null[:20])  # type: ignore[attr-defined]
    assert np.all(~onset.global_path.is_null[20:])  # type: ignore[attr-defined]
