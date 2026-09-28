"""Isolation and guardrail tests for TASK-021F Research node evidence."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from dps_studio.core.ridge import (
    GlobalPathConfig,
    candidate_node_cost,
    extract_global_path_candidates,
    track_global_candidate_path,
)
from dps_studio.research.global_path_benchmark import (
    DEFAULT_VACUUM_WAVELENGTH_M,
    calculate_ridge_metrics,
    generate_synthetic_global_path_cases,
)
from dps_studio.research.task021f_node_evidence import (
    _node_synthetic_scenarios,
    _run_lengths,
    build_node_models,
    candidate_graph_signature,
    candidate_node_cost_with_evidence,
    compute_candidate_evidence,
    fixed_transition_specs,
    solve_node_evidence_path,
    specificity_score,
)


def _fixture() -> tuple[object, object, GlobalPathConfig]:
    case = generate_synthetic_global_path_cases()[0]
    config = GlobalPathConfig(top_k=5)
    candidates = extract_global_path_candidates(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )
    frames = tuple(frame[: config.top_k] for frame in candidates.candidates_by_frame)
    evidence = compute_candidate_evidence(
        case.stft_result,
        frames,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )
    return case, candidates, evidence


def test_candidate_graph_and_stft_are_unchanged_by_evidence() -> None:
    case, candidates, _evidence = _fixture()
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)  # type: ignore[union-attr]
    signature = candidate_graph_signature(frames)
    spectrum = case.stft_result.spectrum.copy()
    frequency = case.stft_result.frequency_hz.copy()
    time_s = case.stft_result.time_s.copy()
    compute_candidate_evidence(
        case.stft_result,
        frames,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )

    assert candidate_graph_signature(frames) == signature
    assert np.array_equal(case.stft_result.spectrum, spectrum)
    assert np.array_equal(case.stft_result.frequency_hz, frequency)
    assert np.array_equal(case.stft_result.time_s, time_s)


def test_local_evidence_uses_physical_stft_resolution_and_is_bounded() -> None:
    _case, candidates, evidence = _fixture()
    expected_resolution = 6.4e9 / 64

    assert evidence.stft_resolution_hz == pytest.approx(expected_resolution)
    for item in evidence.by_key.values():
        assert item.stft_resolution_hz == pytest.approx(expected_resolution)
        assert 0.0 <= item.local_concentration <= 1.0
        assert 0.0 <= item.broadband_occupancy <= 1.0
        assert 0.0 <= item.specificity <= 1.0


def test_broadband_occupancy_is_deterministic() -> None:
    case, candidates, first = _fixture()
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)  # type: ignore[union-attr]
    second = compute_candidate_evidence(
        case.stft_result,
        frames,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )

    assert np.array_equal(first.frame_broadband_occupancy, second.frame_broadband_occupancy)
    assert first.by_key == second.by_key


def test_specificity_is_bounded_and_monotonic() -> None:
    low = specificity_score(0.2, 0.2, 0.2, 0.8)
    stronger = specificity_score(0.7, 0.2, 0.2, 0.8)
    less_broadband = specificity_score(0.7, 0.2, 0.2, 0.2)

    assert 0.0 <= low <= 1.0
    assert stronger > low
    assert less_broadband > stronger
    assert specificity_score(1.0, 1.0, 1.0, 1.0) == pytest.approx(1.0)


def test_high_broadband_low_prominence_receives_higher_penalty() -> None:
    _case, candidates, evidence = _fixture()
    config = GlobalPathConfig(top_k=5)
    n3 = next(item for item in build_node_models() if item.node_model_id == "N3")
    candidate = candidates.candidates_by_frame[0][0]  # type: ignore[union-attr]
    item = evidence.for_candidate(candidate)
    key = (candidate.frame_index, candidate.candidate_rank)
    weak = replace(
        item,
        broadband_occupancy=0.9,
        prominence_score=0.05,
        concentration_score=0.05,
        local_peak_sharpness=0.05,
        specificity=specificity_score(0.05, 0.05, 0.05, 0.9),
    )
    strong = replace(
        item,
        broadband_occupancy=0.9,
        prominence_score=0.95,
        concentration_score=0.95,
        local_peak_sharpness=0.95,
        specificity=specificity_score(0.95, 0.95, 0.95, 0.9),
    )
    weak_bundle = replace(evidence, by_key={**evidence.by_key, key: weak})
    strong_bundle = replace(evidence, by_key={**evidence.by_key, key: strong})

    assert candidate_node_cost_with_evidence(
        candidate, config=config, evidence=weak_bundle, node_model=n3
    ) > candidate_node_cost_with_evidence(
        candidate, config=config, evidence=strong_bundle, node_model=n3
    )
    assert candidate_node_cost_with_evidence(
        candidate, config=config, evidence=strong_bundle, node_model=n3
    ) >= candidate_node_cost(candidate, config)


def test_n0_exactly_reproduces_current_core_node_cost_and_path() -> None:
    case, candidates, evidence = _fixture()
    config = GlobalPathConfig(top_k=5)
    n0 = next(item for item in build_node_models() if item.node_model_id == "N0")
    e0 = next(item for item in fixed_transition_specs() if item.experiment_id == "E0")
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)  # type: ignore[union-attr]
    research = solve_node_evidence_path(
        frames,
        candidates.time_s,  # type: ignore[union-attr]
        config=config,
        evidence=evidence,
        node_model=n0,
        transition_spec=e0,
    )
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )

    assert np.array_equal(research.selected_candidate_rank, core.selected_candidate_rank)
    assert np.array_equal(
        research.selected_frequency_hz, core.selected_refined_frequency_hz, equal_nan=True
    )
    assert np.array_equal(research.cumulative_cost, core.cumulative_cost)
    assert candidate_node_cost_with_evidence(
        frames[0][0], config=config, evidence=evidence, node_model=n0
    ) == candidate_node_cost(frames[0][0], config)


def test_n1_to_n4_do_not_modify_default_core_cost() -> None:
    _case, candidates, evidence = _fixture()
    config = GlobalPathConfig(top_k=5)
    candidate = candidates.candidates_by_frame[0][0]  # type: ignore[union-attr]
    baseline = candidate_node_cost(candidate, config)

    values = [
        candidate_node_cost_with_evidence(
            candidate, config=config, evidence=evidence, node_model=item
        )
        for item in build_node_models()
    ]

    assert candidate_node_cost(candidate, config) == baseline
    assert values[0] == baseline
    assert all(value >= baseline for value in values[1:])
    assert GlobalPathConfig() == GlobalPathConfig(top_k=5)


def test_fixed_transitions_match_task021e_parameters() -> None:
    specs = {item.experiment_id: item for item in fixed_transition_specs()}

    assert set(specs) == {"E0", "E2", "E3"}
    assert specs["E0"].first_order_kind == "quadratic"
    assert specs["E0"].first_order_weight == 1.0
    assert specs["E2"].huber_delta_normalized == 0.25
    assert specs["E3"].huber_delta_normalized == 0.10
    assert all(item.curvature_weight == 0.0 for item in specs.values())


@pytest.mark.parametrize(
    ("case_id", "minimum_coverage", "maximum_longest"),
    (
        ("H_pure_noise", 0.0, 0),
        ("N_BROADBAND_VERTICAL_TRANSIENT", 0.0, 0),
        ("O_RIDGE_PLUS_BROADBAND", 0.50, 96),
        ("P_WEAK_RIDGE_IN_BROADBAND", 0.50, 96),
    ),
)
def test_synthetic_broadband_guardrails(
    case_id: str,
    minimum_coverage: float,
    maximum_longest: int,
) -> None:
    scenario = next(item for item in _node_synthetic_scenarios() if item.case.case_id == case_id)
    config = GlobalPathConfig(top_k=5)
    candidates = extract_global_path_candidates(
        scenario.case.stft_result,
        minimum_frequency_hz=scenario.minimum_frequency_hz,
        maximum_frequency_hz=scenario.maximum_frequency_hz,
        config=config,
    )
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)
    evidence = compute_candidate_evidence(
        scenario.case.stft_result,
        frames,
        minimum_frequency_hz=scenario.minimum_frequency_hz,
        maximum_frequency_hz=scenario.maximum_frequency_hz,
    )
    n3 = next(item for item in build_node_models() if item.node_model_id == "N3")
    e2 = next(item for item in fixed_transition_specs() if item.experiment_id == "E2")
    result = solve_node_evidence_path(
        frames,
        candidates.time_s,
        config=config,
        evidence=evidence,
        node_model=n3,
        transition_spec=e2,
    )
    metrics = calculate_ridge_metrics(
        scenario.case,
        result.selected_frequency_hz,
        selected_candidate_rank=result.selected_candidate_rank,
        method="TASK021F_test",
        top_k=5,
        vacuum_wavelength_m=DEFAULT_VACUUM_WAVELENGTH_M,
    )

    if case_id in {"H_pure_noise", "N_BROADBAND_VERTICAL_TRANSIENT"}:
        assert np.all(result.is_null)
    else:
        assert metrics.valid_selected_coverage >= minimum_coverage
    assert max(_run_lengths(~result.is_null), default=0) <= maximum_longest
    assert not math.isinf(result.total_path_cost)
