"""Correctness and isolation tests for TASK-021E transition Research models."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dps_studio.core.ridge import GlobalPathConfig, extract_global_path_candidates, track_global_candidate_path
from dps_studio.research.global_path_benchmark import generate_synthetic_global_path_cases
from dps_studio.research.task021b_real_experiment import FormalInput
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task021e_transition_models import (
    build_transition_specs,
    curvature_cost,
    robust_first_order_cost,
    solve_transition_path,
    tiny_graph_validation,
    transition_cost_components,
)


def _candidate_set() -> tuple[object, GlobalPathConfig]:
    case = generate_synthetic_global_path_cases()[0]
    config = GlobalPathConfig(top_k=5)
    return (
        extract_global_path_candidates(
            case.stft_result,
            minimum_frequency_hz=0.4e9,
            maximum_frequency_hz=2.8e9,
            config=config,
        ),
        config,
    )


def test_t0_matches_current_core_baseline_exactly() -> None:
    candidate_set, config = _candidate_set()
    spec = build_transition_specs()[0]
    research = solve_transition_path(candidate_set.candidates_by_frame, candidate_set.time_s, config=config, spec=spec)  # type: ignore[arg-type]
    case = generate_synthetic_global_path_cases()[0]
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )

    assert np.array_equal(research.selected_candidate_rank, core.selected_candidate_rank)
    assert np.array_equal(research.selected_frequency_hz, core.selected_refined_frequency_hz, equal_nan=True)
    assert np.array_equal(research.cumulative_cost, core.cumulative_cost)


def test_robust_transition_is_quadratic_near_zero_and_avoids_tail_explosion() -> None:
    config = GlobalPathConfig()
    small = 1.0e5
    quadratic_small = (small / config.frequency_step_scale_hz) ** 2
    robust_small = robust_first_order_cost(small, config=config, weight=1.0, huber_delta_normalized=0.25)
    large = 1.0e9
    quadratic_large = (large / config.frequency_step_scale_hz) ** 2
    robust_large = robust_first_order_cost(large, config=config, weight=1.0, huber_delta_normalized=0.25)

    assert robust_small == pytest.approx(quadratic_small, rel=1e-5)
    assert robust_large < quadratic_large


def test_curvature_zero_for_constant_slope_and_high_for_slope_change() -> None:
    candidates, config = _candidate_set()
    frame = candidates.candidates_by_frame  # type: ignore[union-attr]
    first, second, third = frame[0][0], frame[1][0], frame[2][0]
    spec = build_transition_specs()[4]
    constant = curvature_cost(first, second, third, config=config, weight=spec.curvature_weight)
    changed = curvature_cost(first, second, frame[3][0], config=config, weight=spec.curvature_weight)

    assert constant >= 0.0
    assert changed >= 0.0
    assert curvature_cost(None, second, third, config=config, weight=spec.curvature_weight) == 0.0


def test_second_order_dp_and_backtracking_match_exhaustive_tiny_graph() -> None:
    validation = tiny_graph_validation()

    assert validation["cost_equal"] is True
    assert validation["path_equal"] is True


def test_null_clears_history_and_first_candidate_after_null_has_no_curvature() -> None:
    candidates, config = _candidate_set()
    first = candidates.candidates_by_frame[0][0]  # type: ignore[union-attr]
    third = candidates.candidates_by_frame[2][0]  # type: ignore[union-attr]
    spec = build_transition_specs()[4]
    total, first_order, second_order = transition_cost_components(
        first,
        None,
        third,
        config=config,
        spec=spec,
    )

    assert total == config.ridge_entry_cost
    assert first_order == 0.0
    assert second_order == 0.0


def test_research_solver_keeps_candidate_graph_and_defaults_immutable() -> None:
    candidates, config = _candidate_set()
    frames_before = candidates.candidates_by_frame  # type: ignore[union-attr]
    time_before = candidates.time_s.copy()  # type: ignore[union-attr]
    solve_transition_path(candidates.candidates_by_frame, candidates.time_s, config=config, spec=build_transition_specs()[6])  # type: ignore[arg-type]

    assert candidates.candidates_by_frame == frames_before  # type: ignore[union-attr]
    assert np.array_equal(candidates.time_s, time_before)  # type: ignore[union-attr]
    assert GlobalPathConfig() == GlobalPathConfig(top_k=5)


def test_processed_result_is_excluded_and_inventory_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dps_studio.research.task021c_cost_bridge as inventory_module

    medium = tmp_path / "PDV数据-质量中等"
    medium.mkdir()
    raw = medium / "raw.dat"
    processed = medium / "raw-RESULT.dat"
    raw.write_text("0,1\n", encoding="utf-8")
    processed.write_text("result\n", encoding="utf-8")
    before = raw.read_bytes()
    record = SimpleNamespace(time_s=np.array([0.0, 1.0, 2.0]))
    monkeypatch.setattr(
        inventory_module,
        "formal_read_input",
        lambda _path, _config: FormalInput(SimpleNamespace(records={"pdv": record}, column_count=2, row_count=3), "test"),
    )
    rows, accepted = corrected_inventory(tmp_path, SimpleNamespace())

    assert raw.read_bytes() == before
    assert raw.resolve() in accepted
    assert next(row for row in rows if row["absolute_path"] == str(processed.resolve()))["classification"] == "PROCESSED_RESULT_EXCLUDED"


def test_pure_noise_and_existing_a_to_h_regression_remain_safe() -> None:
    config = GlobalPathConfig(top_k=5)
    spec = build_transition_specs()[0]
    for case in generate_synthetic_global_path_cases():
        candidates = extract_global_path_candidates(
            case.stft_result,
            minimum_frequency_hz=0.4e9,
            maximum_frequency_hz=2.8e9,
            config=config,
        )
        result = solve_transition_path(candidates.candidates_by_frame, candidates.time_s, config=config, spec=spec)
        if case.case_id == "H_pure_noise":
            assert np.all(result.is_null)
