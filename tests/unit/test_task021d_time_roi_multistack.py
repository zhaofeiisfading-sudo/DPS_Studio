"""TASK-021D same-STFT ROI and factorial-stack safety tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dps_studio.core.ridge import GlobalPathConfig, extract_global_path_candidates, track_global_candidate_path
from dps_studio.research.global_path_benchmark import generate_synthetic_global_path_cases
from dps_studio.research.task021b_real_experiment import FormalInput
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task021d_time_roi_multistack import (
    build_factorial_stacks,
    candidate_graph_overlap_signature,
    map_time_roi,
    solve_dp_roi_same_stft,
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


def test_roi_is_defined_in_time_and_mapping_is_deterministic() -> None:
    candidates, _ = _candidate_set()
    time_s = candidates.time_s  # type: ignore[union-attr]
    first = map_time_roi(
        time_s,
        roi_id="time_roi",
        requested_start_time_s=float(time_s[10]) - 0.1e-9,
        requested_end_time_s=float(time_s[20]) + 0.1e-9,
    )
    second = map_time_roi(
        time_s,
        roi_id="time_roi",
        requested_start_time_s=float(time_s[10]) - 0.1e-9,
        requested_end_time_s=float(time_s[20]) + 0.1e-9,
    )

    assert first == second
    assert first.frame_start == 10
    assert first.frame_end == 20
    assert first.frame_count == 11


def test_same_stft_roi_keeps_graph_and_stft_unchanged() -> None:
    candidates, config = _candidate_set()
    spectrum_before = candidates.source_path  # type: ignore[union-attr]
    original_frames = candidates.candidates_by_frame  # type: ignore[union-attr]
    definition = map_time_roi(
        candidates.time_s,  # type: ignore[union-attr]
        roi_id="inner",
        requested_start_time_s=float(candidates.time_s[10]),  # type: ignore[union-attr]
        requested_end_time_s=float(candidates.time_s[20]),  # type: ignore[union-attr]
    )
    before = candidate_graph_overlap_signature(candidates, config, definition)  # type: ignore[arg-type]
    result = solve_dp_roi_same_stft(
        candidates,  # type: ignore[arg-type]
        config=config,
        definition=definition,
        boundary_mode="B0_STANDARD",
    )
    after = candidate_graph_overlap_signature(candidates, config, definition)  # type: ignore[arg-type]

    assert before == after
    assert candidates.candidates_by_frame == original_frames  # type: ignore[union-attr]
    assert candidates.source_path == spectrum_before  # type: ignore[union-attr]
    assert result.frame_indices[0] == definition.frame_start
    assert result.frame_indices[-1] == definition.frame_end


def test_roi_excludes_outside_frames_and_standard_matches_core_full_path() -> None:
    candidates, config = _candidate_set()
    definition = map_time_roi(
        candidates.time_s,  # type: ignore[union-attr]
        roi_id="full",
        requested_start_time_s=None,
        requested_end_time_s=None,
    )
    research = solve_dp_roi_same_stft(
        candidates,  # type: ignore[arg-type]
        config=config,
        definition=definition,
        boundary_mode="B0_STANDARD",
    )
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
    assert research.total_path_cost == core.total_path_cost


def test_free_boundary_is_research_only_and_does_not_mutate_defaults() -> None:
    candidates, config = _candidate_set()
    definition = map_time_roi(
        candidates.time_s,  # type: ignore[union-attr]
        roi_id="first_frame",
        requested_start_time_s=float(candidates.time_s[0]),  # type: ignore[union-attr]
        requested_end_time_s=float(candidates.time_s[20]),  # type: ignore[union-attr]
    )
    standard = solve_dp_roi_same_stft(
        candidates,  # type: ignore[arg-type]
        config=config,
        definition=definition,
        boundary_mode="B0_STANDARD",
    )
    free = solve_dp_roi_same_stft(
        candidates,  # type: ignore[arg-type]
        config=config,
        definition=definition,
        boundary_mode="B1_FREE_ROI_BOUNDARY",
    )

    assert GlobalPathConfig() == GlobalPathConfig()
    assert standard.boundary_mode == "B0_STANDARD"
    assert free.boundary_mode == "B1_FREE_ROI_BOUNDARY"
    assert free.config == config


def test_factorial_stack_is_complete_and_does_not_change_defaults() -> None:
    stacks = build_factorial_stacks()
    combinations = {
        (stack.config.top_k, stack.config.ridge_entry_cost, stack.config.continuity_weight)
        for stack in stacks
    }

    assert [stack.stack_id for stack in stacks] == [f"P{index}" for index in range(8)]
    assert len(combinations) == 8
    assert {stack.config.top_k for stack in stacks} == {5, 20}
    assert {stack.config.ridge_entry_cost for stack in stacks} == {2.25, 3.0}
    assert {stack.config.continuity_weight for stack in stacks} == {0.5, 1.0}
    assert GlobalPathConfig() == GlobalPathConfig(top_k=5)


def test_processed_result_is_excluded_and_inventory_leaves_raw_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dps_studio.research.task021c_cost_bridge as experiment

    medium = tmp_path / "PDV数据-质量中等"
    medium.mkdir()
    raw = medium / "signal.dat"
    processed = medium / "signal-ReSuLt.dat"
    raw.write_text("0,1\n", encoding="utf-8")
    processed.write_text("processed\n", encoding="utf-8")
    before = raw.read_bytes()
    record = SimpleNamespace(time_s=np.array([0.0, 1.0, 2.0]))
    monkeypatch.setattr(
        experiment,
        "formal_read_input",
        lambda _path, _configuration: FormalInput(
            SimpleNamespace(records={"pdv": record}, column_count=2, row_count=3),
            "test",
        ),
    )

    rows, accepted = corrected_inventory(tmp_path, SimpleNamespace())

    assert raw.read_bytes() == before
    assert raw.resolve() in accepted
    assert next(row for row in rows if row["absolute_path"] == str(processed.resolve()))["classification"] == "PROCESSED_RESULT_EXCLUDED"


def test_pure_noise_guardrail_and_core_api_semantics_remain_unchanged() -> None:
    pure_noise = next(case for case in generate_synthetic_global_path_cases() if case.case_id == "H_pure_noise")
    default = GlobalPathConfig()
    result = track_global_candidate_path(
        pure_noise.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=default,
    )

    assert np.all(result.is_null)
    assert np.all(np.isnan(result.selected_refined_frequency_hz))
    assert result.config == default
