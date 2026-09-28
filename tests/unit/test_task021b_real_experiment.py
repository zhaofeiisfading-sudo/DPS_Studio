"""Focused regression tests for the read-only TASK-021B Research runner."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from dps_studio.core.ridge import (
    GlobalPathConfig,
    candidate_node_cost,
    track_global_candidate_path,
)
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research.global_path_benchmark import generate_synthetic_global_path_cases
from dps_studio.research.task021b_real_experiment import (
    build_experiment_matrix,
    candidate_capacity_counts,
    detailed_cost_audit_rows,
    inventory_raw_files,
    node_cost_components,
    sha256_file,
)
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    REPOSITORY_ROOT,
    FormalInput,
    PreparedStream as Task021BPreparedStream,
    prepare_streams,
)


def test_sha256_is_stable_and_source_is_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("0,1\n1,2\n", encoding="utf-8")

    before = sha256_file(source)
    _ = sha256_file(source)

    assert sha256_file(source) == before
    assert source.read_text(encoding="utf-8") == "0,1\n1,2\n"


def test_matrix_is_deterministic_and_does_not_modify_default_config() -> None:
    default = GlobalPathConfig()

    first = build_experiment_matrix()
    second = build_experiment_matrix()

    assert [item.row() for item in first] == [item.row() for item in second]
    assert first[0].config == default
    assert default == GlobalPathConfig()
    assert {item.stage for item in first} == {
        "baseline",
        "top_k",
        "null_axis_entry",
        "continuity",
        "stack",
    }


def test_inventory_skips_invalid_file_and_continues(tmp_path: Path) -> None:
    valid = tmp_path / "valid.csv"
    valid.write_text("0.0,1.0\n1.0,2.0\n2.0,3.0\n", encoding="utf-8")
    invalid = tmp_path / "result.dat"
    invalid.write_text("0.0 1.0\n1.0 2.0\n", encoding="utf-8")
    configuration = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=REPOSITORY_ROOT)

    rows, accepted = inventory_raw_files(tmp_path, configuration)

    assert valid.resolve() in accepted
    skipped = next(row for row in rows if row["relative_path"] == "result.dat")
    assert skipped["reader_status"] == "SKIPPED_MAPPING_UNKNOWN"
    assert skipped["usable"] is False


def test_cost_audit_matches_frame_count_and_preserves_null_sentinel() -> None:
    case = generate_synthetic_global_path_cases()[0]
    config = GlobalPathConfig(top_k=5)
    result = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )
    from dps_studio.research.global_path_calibration import audit_global_candidate_path

    audit = audit_global_candidate_path(result.candidate_set)
    stream = Task021BPreparedStream(
        source_path=Path("synthetic.csv"),
        source_sha256="synthetic",
        quality_group="test",
        profile_id="test",
        profile_display_name="test",
        channel_name="synthetic",
        analysis=type("Analysis", (), {"signal_detection_result": type("Detection", (), {"refined_frequency_hz": np.full(result.time_s.size, np.nan)})()})(),
        candidate_set_maximum=result.candidate_set,
        candidate_counts_before_top_k=np.full(result.time_s.size, 5, dtype=np.int64),
        candidate_counts_after_separation=np.full(result.time_s.size, 5, dtype=np.int64),
        manual_reference_time_s=None,
    )

    rows = detailed_cost_audit_rows(stream=stream, result=result, audit=audit)

    assert len({int(row["frame_index"]) for row in rows}) == result.time_s.size
    assert all(
        np.isnan(row["refined_frequency_hz"])
        for row in rows
        if row["state_type"] == "NULL"
    )
    assert all(
        row["rank"] == 0
        for row in rows
        if row["state_type"] == "NULL"
    )


def test_capacity_count_and_cost_components_are_observational_only() -> None:
    case = generate_synthetic_global_path_cases()[1]
    config = GlobalPathConfig(top_k=5)
    result = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )
    before, after = candidate_capacity_counts(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )

    assert before.shape == result.time_s.shape
    assert after.shape == result.time_s.shape
    assert np.all(after <= before)
    candidate = result.candidate_set.candidates_by_frame[0][0]
    components = node_cost_components(candidate, config)
    assert np.isclose(
        components["total_candidate_node_cost"],
        candidate_node_cost(candidate, config),
    )


def test_config_override_keeps_candidate_order_and_default_immutable() -> None:
    case = generate_synthetic_global_path_cases()[2]
    baseline = GlobalPathConfig(top_k=5)
    result = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=baseline,
    )
    original_order = [
        tuple(candidate.candidate_rank for candidate in frame)
        for frame in result.candidate_set.candidates_by_frame
    ]
    overridden = replace(baseline, ridge_entry_cost=2.25)

    assert baseline == GlobalPathConfig(top_k=5)
    assert overridden != baseline
    assert original_order == [
        tuple(candidate.candidate_rank for candidate in frame)
        for frame in result.candidate_set.candidates_by_frame
    ]


def test_baseline_reproducibility_keeps_null_nan_semantics() -> None:
    case = generate_synthetic_global_path_cases()[3]
    config = GlobalPathConfig(top_k=5)
    first = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )
    second = track_global_candidate_path(
        case.stft_result,
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
        config=config,
    )

    assert np.array_equal(first.selected_candidate_rank, second.selected_candidate_rank)
    assert np.array_equal(
        first.selected_refined_frequency_hz,
        second.selected_refined_frequency_hz,
        equal_nan=True,
    )
    assert np.all(np.isnan(first.selected_refined_frequency_hz[first.is_null]))


def test_batch_runner_records_one_code_failure_and_continues(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    import dps_studio.research.task021b_real_experiment as experiment

    case = generate_synthetic_global_path_cases()[0]
    bad_path = tmp_path / "bad.csv"
    good_path = tmp_path / "good.csv"
    bad_path.write_text("0,1\n", encoding="utf-8")
    good_path.write_text("0,1\n", encoding="utf-8")
    record = SimpleNamespace(time_s=np.array([0.0, 1.0], dtype=np.float64))
    accepted = {
        bad_path.resolve(): FormalInput(
            SimpleNamespace(records={"bad": record}),
            "test",
        ),
        good_path.resolve(): FormalInput(
            SimpleNamespace(records={"good": record}),
            "test",
        ),
    }
    profile = SimpleNamespace(
        profile_id=SimpleNamespace(value="test"),
        display_name="test",
        minimum_frequency_hz=0.4e9,
        maximum_frequency_hz=2.8e9,
    )
    configuration = SimpleNamespace(
        analysis=SimpleNamespace(
            profiles=(profile,),
            manual_event_reference_time_s=None,
            vacuum_wavelength_m=1.55e-6,
        ),
        event_candidate=None,
        automatic_ridge_selection=None,
        velocity_correction=None,
        quality=SimpleNamespace(
            signal_detection=None,
            background_guard_window_scale=2.0,
            minimum_background_bin_count=2,
        ),
    )

    def fake_analyze(
        records: object,
        **_: object,
    ) -> dict[str, object]:
        channel_name = next(iter(records))  # type: ignore[arg-type]
        if channel_name == "bad":
            raise RuntimeError("synthetic runner failure")
        analysis = SimpleNamespace(
            stft_result=case.stft_result,
            signal_detection_result=SimpleNamespace(
                refined_frequency_hz=np.full(case.stft_result.time_s.size, np.nan)
            ),
        )
        return {channel_name: analysis}

    monkeypatch.setattr(experiment, "analyze_profile", fake_analyze)  # type: ignore[attr-defined]

    streams, failures = prepare_streams(
        raw_root=tmp_path,
        configuration=configuration,
        accepted_inputs=accepted,
    )

    assert len(streams) == 1, failures
    assert streams[0].source_path == good_path.resolve()
    assert len(failures) == 1
    assert failures[0].status == "CODE_FAILURE"
