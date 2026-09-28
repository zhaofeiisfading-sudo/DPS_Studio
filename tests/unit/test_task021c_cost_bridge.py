"""Safety regressions for TASK-021C corrected inventory and bridge hypotheses."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dps_studio.core.ridge import GlobalPathConfig, track_global_candidate_path
from dps_studio.research.global_path_benchmark import generate_synthetic_global_path_cases
from dps_studio.research.task021b_real_experiment import FormalInput
from dps_studio.research.task021c_cost_bridge import (
    Normalization,
    bridge_null_gaps,
    corrected_inventory,
    path_view_from_core,
)


def test_medium_result_is_excluded_before_reader_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dps_studio.research.task021c_cost_bridge as experiment

    medium = tmp_path / "PDV数据-质量中等" / "one"
    medium.mkdir(parents=True)
    processed = medium / "INPUT-ReSuLt.DAT"
    raw = medium / "raw_input.dat"
    processed.write_text("already processed", encoding="utf-8")
    raw.write_text("0,1\n", encoding="utf-8")
    called: list[Path] = []
    record = SimpleNamespace(time_s=np.array([0.0, 1.0, 2.0], dtype=np.float64))

    def fake_reader(path: Path, _: object) -> FormalInput:
        called.append(path)
        return FormalInput(
            SimpleNamespace(records={"pdv": record}, column_count=2, row_count=3),
            "test",
        )

    monkeypatch.setattr(experiment, "formal_read_input", fake_reader)
    rows, accepted = corrected_inventory(tmp_path, SimpleNamespace())

    result_row = next(row for row in rows if row["absolute_path"] == str(processed.resolve()))
    assert result_row["classification"] == "PROCESSED_RESULT_EXCLUDED"
    assert processed not in called
    assert raw in called
    assert raw.resolve() in accepted


def test_corrected_inventory_is_read_only_for_raw_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The corrected inventory must not alter an accepted numerical raw file."""
    import dps_studio.research.task021c_cost_bridge as experiment

    raw = tmp_path / "raw_input.dat"
    raw.write_text("0,1\n", encoding="utf-8")
    before = raw.read_bytes()
    record = SimpleNamespace(time_s=np.array([0.0, 1.0, 2.0], dtype=np.float64))

    monkeypatch.setattr(
        experiment,
        "formal_read_input",
        lambda _path, _configuration: FormalInput(
            SimpleNamespace(records={"pdv": record}, column_count=2, row_count=3),
            "test",
        ),
    )
    corrected_inventory(tmp_path, SimpleNamespace())

    assert raw.read_bytes() == before


def test_candidate_bridge_keeps_original_global_path_immutable() -> None:
    case = generate_synthetic_global_path_cases()[0]
    config = GlobalPathConfig(top_k=5)
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )
    import dps_studio.research.task021c_cost_bridge as experiment

    forced = experiment._masked_synthetic_path(path_view_from_core(core), case.truth_frequency_hz, 1)
    assert forced is not None
    original_core_frequency = core.selected_refined_frequency_hz.copy()
    bridge = bridge_null_gaps(
        forced,
        method="candidate_aware",
        max_gap_frames=1,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )

    assert np.array_equal(core.selected_refined_frequency_hz, original_core_frequency, equal_nan=True)
    assert np.all(np.isnan(forced.selected_frequency_hz[forced.is_null]))
    assert "MEASURED" not in bridge.bridge_status
    assert all(status in {"ORIGINAL_GLOBAL", "BRIDGED_CANDIDATE", "NULL_UNCHANGED"} for status in bridge.bridge_status)


def test_leading_trailing_and_too_long_nulls_are_not_bridged() -> None:
    case = generate_synthetic_global_path_cases()[0]
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=GlobalPathConfig(top_k=5),
    )
    base = path_view_from_core(core)
    frequency = base.selected_frequency_hz.copy()
    rank = base.selected_candidate_rank.copy()
    null = base.is_null.copy()
    frequency[:2] = np.nan
    frequency[-2:] = np.nan
    frequency[20:26] = np.nan
    rank[:2] = 0
    rank[-2:] = 0
    rank[20:26] = 0
    null[:2] = True
    null[-2:] = True
    null[20:26] = True
    forced = replace(base, selected_frequency_hz=frequency, selected_candidate_rank=rank, is_null=null)
    bridge = bridge_null_gaps(
        forced,
        method="linear",
        max_gap_frames=5,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )

    assert all(item == "NULL_UNCHANGED" for item in bridge.bridge_status[:2])
    assert all(item == "NULL_UNCHANGED" for item in bridge.bridge_status[-2:])
    assert all(item == "NULL_UNCHANGED" for item in bridge.bridge_status[20:26])


def test_pure_noise_has_no_anchors_and_no_bridge() -> None:
    case = next(item for item in generate_synthetic_global_path_cases() if item.case_id == "H_pure_noise")
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=GlobalPathConfig(top_k=5),
    )
    bridge = bridge_null_gaps(
        path_view_from_core(core),
        method="candidate_aware",
        max_gap_frames=5,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )

    assert np.all(np.isnan(bridge.bridged_frequency_hz))
    assert set(bridge.bridge_status) == {"NULL_UNCHANGED"}


def test_linear_bridge_status_is_explicit_and_deterministic() -> None:
    case = generate_synthetic_global_path_cases()[0]
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=GlobalPathConfig(top_k=5),
    )
    import dps_studio.research.task021c_cost_bridge as experiment

    forced = experiment._masked_synthetic_path(path_view_from_core(core), case.truth_frequency_hz, 1)
    assert forced is not None
    first = bridge_null_gaps(
        forced,
        method="linear",
        max_gap_frames=1,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )
    second = bridge_null_gaps(
        forced,
        method="linear",
        max_gap_frames=1,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )

    assert "BRIDGED_INTERPOLATED" in first.bridge_status
    assert first.bridge_status == second.bridge_status
    assert np.array_equal(first.bridged_frequency_hz, second.bridged_frequency_hz, equal_nan=True)


def test_candidate_bridge_uses_only_existing_top_k_and_is_deterministic() -> None:
    case = generate_synthetic_global_path_cases()[0]
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=GlobalPathConfig(top_k=5),
    )
    import dps_studio.research.task021c_cost_bridge as experiment

    forced = experiment._masked_synthetic_path(path_view_from_core(core), case.truth_frequency_hz, 1)
    assert forced is not None
    first = bridge_null_gaps(
        forced,
        method="candidate_aware",
        max_gap_frames=1,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )
    second = bridge_null_gaps(
        forced,
        method="candidate_aware",
        max_gap_frames=1,
        node_cost_function=lambda candidate: candidate.peak_amplitude * 0.0,
    )

    bridged_indices = [
        index for index, status in enumerate(first.bridge_status) if status == "BRIDGED_CANDIDATE"
    ]
    assert bridged_indices
    for index in bridged_indices:
        allowed = [item.transition_frequency_hz for item in forced.candidate_set.candidates_by_frame[index]]
        assert first.bridged_frequency_hz[index] in allowed
        assert first.selected_candidate_rank_if_any[index] > 0
    assert first.bridge_status == second.bridge_status
    assert np.array_equal(first.bridged_frequency_hz, second.bridged_frequency_hz, equal_nan=True)


@pytest.mark.parametrize("case_id", ["E_temporary_dropout", "F_shock_like_onset"])
def test_synthetic_mask_never_targets_dropout_or_pre_event(case_id: str) -> None:
    import dps_studio.research.task021c_cost_bridge as experiment

    case = next(item for item in generate_synthetic_global_path_cases() if item.case_id == case_id)
    core = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=GlobalPathConfig(top_k=5),
    )
    base = path_view_from_core(core)
    forced = experiment._masked_synthetic_path(base, case.truth_frequency_hz, 1)
    assert forced is not None

    artificially_masked = forced.is_null & ~base.is_null
    assert not np.any(artificially_masked & case.dropout_mask)
    assert not np.any(artificially_masked & case.pre_event_mask)


def test_normalization_does_not_mutate_default_config() -> None:
    default = GlobalPathConfig()
    normalization = Normalization(
        normalization_id="N1_good_reference_robust_node",
        reference_profile_median=0.5,
        reference_profile_iqr=0.25,
        profile_median={"balanced": 0.4},
        profile_iqr={"balanced": 0.2},
        calibration_source="test",
        _config=default,
    )

    assert normalization.normalization_id.startswith("N1")
    assert default == GlobalPathConfig()
