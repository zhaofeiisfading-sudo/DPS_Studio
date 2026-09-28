"""Isolation tests for TASK-021G spatiotemporal candidate coherence."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dps_studio.core.ridge import (
    GlobalPathConfig,
    candidate_node_cost,
    extract_global_path_candidates,
    track_global_candidate_path,
)
from dps_studio.research.global_path_benchmark import generate_synthetic_global_path_cases
from dps_studio.research.task021f_node_evidence import candidate_graph_signature
from dps_studio.research.task021g_candidate_coherence import (
    WINDOWS,
    build_coherence_models,
    candidate_node_cost_with_coherence,
    compute_candidate_coherence,
    fixed_transition_specs,
    solve_coherence_path,
)
from dps_studio.research.task021g_candidate_coherence import _task021g_synthetic_scenarios


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
    bundle = compute_candidate_coherence(
        case.stft_result,
        frames,
        config=config,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )
    return case, candidates, bundle


def test_coherence_preserves_candidate_graph_and_stft() -> None:
    case, candidates, _bundle = _fixture()
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)  # type: ignore[union-attr]
    graph = candidate_graph_signature(frames)
    spectrum = case.stft_result.spectrum.copy()
    frequency = case.stft_result.frequency_hz.copy()
    time_s = case.stft_result.time_s.copy()
    compute_candidate_coherence(
        case.stft_result,
        frames,
        config=GlobalPathConfig(top_k=5),
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )

    assert candidate_graph_signature(frames) == graph
    assert np.array_equal(case.stft_result.spectrum, spectrum)
    assert np.array_equal(case.stft_result.frequency_hz, frequency)
    assert np.array_equal(case.stft_result.time_s, time_s)


def test_support_and_rewards_are_deterministic_bounded_and_physical() -> None:
    case, candidates, first = _fixture()
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)  # type: ignore[union-attr]
    second = compute_candidate_coherence(
        case.stft_result,
        frames,
        config=GlobalPathConfig(top_k=5),
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )

    assert first.by_key == second.by_key
    assert np.array_equal(
        first.spectral_evidence.frame_broadband_occupancy,
        second.spectral_evidence.frame_broadband_occupancy,
    )
    assert first.link_tolerance_hz == pytest.approx(1.5e8)
    for item in first.by_key.values():
        assert item.link_tolerance_hz == pytest.approx(first.link_tolerance_hz)
        for direction in ("forward", "backward"):
            values = [item.window_value(direction, window) for window in WINDOWS]
            assert all(0.0 <= value <= 1.0 for value in values)
        assert 0.0 <= item.geometric_persistence <= 1.0
        assert 0.0 <= item.continuation_ambiguity <= 1.0
        assert 0.0 <= item.tube_coherence <= 1.0
        assert 0.0 <= item.coherent_spectral_support <= 1.0


def test_g0_reproduces_core_e0_exactly_and_other_models_floor_cost() -> None:
    case, candidates, bundle = _fixture()
    config = GlobalPathConfig(top_k=5)
    frames = tuple(frame[:5] for frame in candidates.candidates_by_frame)  # type: ignore[union-attr]
    g0 = next(item for item in build_coherence_models() if item.coherence_model_id == "G0")
    e0 = next(item for item in fixed_transition_specs() if item.experiment_id == "E0")
    research = solve_coherence_path(
        frames,
        candidates.time_s,  # type: ignore[union-attr]
        config=config,
        bundle=bundle,
        model=g0,
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
    candidate = frames[0][0]
    for model in build_coherence_models():
        baseline, reward, node = candidate_node_cost_with_coherence(
            candidate, config=config, bundle=bundle, model=model
        )
        assert baseline == candidate_node_cost(candidate, config)
        assert 0.0 <= reward <= model.reward_weight
        assert 0.0 <= node <= baseline


def test_transition_scope_and_null_semantics_are_fixed() -> None:
    specs = {item.experiment_id: item for item in fixed_transition_specs()}

    assert set(specs) == {"E0", "E2"}
    assert specs["E0"].first_order_kind == "quadratic"
    assert specs["E0"].first_order_weight == 1.0
    assert specs["E2"].first_order_kind == "pseudo_huber"
    assert specs["E2"].huber_delta_normalized == 0.25
    assert all(item.curvature_weight == 0.0 for item in specs.values())
    assert GlobalPathConfig() == GlobalPathConfig(top_k=5)
    assert math.isfinite(GlobalPathConfig().null_node_cost)


def test_geometry_diagnostics_distinguish_continuous_ridge_from_random_and_burst() -> None:
    scenarios = {item.case.case_id: item for item in _task021g_synthetic_scenarios()}
    medians: dict[str, float] = {}
    for case_id in (
        "R_COHERENT_WEAK_RIDGE",
        "S_RANDOM_CANDIDATE_CLOUD",
        "T_BROADBAND_VERTICAL_BURST",
    ):
        scenario = scenarios[case_id]
        config = GlobalPathConfig(top_k=5)
        candidates = extract_global_path_candidates(
            scenario.case.stft_result,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
            config=config,
        )
        frames = tuple(frame[: config.top_k] for frame in candidates.candidates_by_frame)
        bundle = compute_candidate_coherence(
            scenario.case.stft_result,
            frames,
            config=config,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
        )
        values = [item.tube_coherence for item in bundle.by_key.values()]
        if case_id == "R_COHERENT_WEAK_RIDGE":
            values = [
                item.tube_coherence
                for item in bundle.by_key.values()
                if abs(item.frequency_hz - 2.8e9) <= scenario.case.wrong_branch_tolerance_hz
            ]
        elif case_id == "T_BROADBAND_VERTICAL_BURST":
            values = [
                bundle.for_candidate(candidate).tube_coherence
                for frame in frames
                for candidate in frame
                if scenario.broadband_mask[candidate.frame_index]
            ]
        medians[case_id] = float(np.median(values))

    assert medians["R_COHERENT_WEAK_RIDGE"] > medians["S_RANDOM_CANDIDATE_CLOUD"]
    assert medians["R_COHERENT_WEAK_RIDGE"] > medians["T_BROADBAND_VERTICAL_BURST"]


def test_pure_noise_remains_null_with_coherence_reward() -> None:
    scenario = next(
        item for item in _task021g_synthetic_scenarios() if item.case.case_id == "H_pure_noise"
    )
    config = GlobalPathConfig(top_k=5)
    candidates = extract_global_path_candidates(
        scenario.case.stft_result,
        minimum_frequency_hz=scenario.minimum_frequency_hz,
        maximum_frequency_hz=scenario.maximum_frequency_hz,
        config=config,
    )
    frames = tuple(frame[: config.top_k] for frame in candidates.candidates_by_frame)
    bundle = compute_candidate_coherence(
        scenario.case.stft_result,
        frames,
        config=config,
        minimum_frequency_hz=scenario.minimum_frequency_hz,
        maximum_frequency_hz=scenario.maximum_frequency_hz,
    )
    g1 = next(item for item in build_coherence_models() if item.coherence_model_id == "G1")
    e2 = next(item for item in fixed_transition_specs() if item.experiment_id == "E2")
    result = solve_coherence_path(
        frames,
        scenario.case.stft_result.time_s,
        config=config,
        bundle=bundle,
        model=g1,
        transition_spec=e2,
    )

    assert np.all(result.is_null)
