"""Regression tests for explicit TASK-021A real-data orchestration."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPOSITORY_ROOT / "scripts" / "run_task021a_global_path_research.py"


@pytest.fixture()
def runner_module() -> ModuleType:
    """Load the standalone research runner without changing package structure."""
    module_name = "task021a_real_runner_test_module"
    specification = importlib.util.spec_from_file_location(module_name, RUNNER_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def _write_two_column_input(path: Path, *, offset: float) -> bytes:
    content = "".join(
        f"{offset + index * 1.0e-9:.12e},{index * 1.0e-3:.12e}\n"
        for index in range(12)
    )
    path.write_text(content, encoding="utf-8")
    return path.read_bytes()


def test_two_column_input_uses_formal_single_channel_rule(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    source = tmp_path / "ch3.csv"
    _write_two_column_input(source, offset=1.0e-4)
    configuration = runner_module.load_workflow_config(
        runner_module.DEFAULT_CONFIG_PATH,
        repository_root=REPOSITORY_ROOT,
    )

    loaded_input = runner_module._load_real_input(
        raw_path=source.resolve(),
        configuration=configuration,
    )

    assert loaded_input.loaded.source_path == source
    assert loaded_input.selection_mode == "single_voltage_column_from_two_column_file"
    assert tuple(loaded_input.loaded.records) == ("pdv_channel_1",)
    assert loaded_input.loaded.voltage_column_indices == {"pdv_channel_1": 1}


def test_real_mode_preserves_selected_source_identity_and_skips_synthetic(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "ch3.csv"
    original_bytes = _write_two_column_input(source, offset=1.0e-4)
    output_directory = tmp_path / "real_output"
    captured_sources: list[Path] = []

    def fake_real_run(*, loaded: object, **_: object) -> object:
        captured_sources.append(loaded.source_path)  # type: ignore[attr-defined]
        return runner_module.RealDataRun((), (), ())

    monkeypatch.setattr(runner_module, "_run_real_data", fake_real_run)
    monkeypatch.setattr(runner_module, "_write_real_result_summary", lambda *_: None)
    monkeypatch.setattr(
        runner_module,
        "_run_synthetic_benchmark",
        lambda _: pytest.fail("real mode must not run synthetic benchmarks"),
    )

    assert runner_module.main(
        [
            "--mode",
            "real",
            "--raw-data",
            str(source),
            "--output-directory",
            str(output_directory),
        ]
    ) == 0

    metadata = json.loads((output_directory / "run_metadata.json").read_text(encoding="utf-8"))
    assert captured_sources == [source]
    assert metadata["mode"] == "real"
    assert metadata["source_path"] == str(source.resolve())
    assert metadata["source_filename"] == "ch3.csv"
    assert metadata["source_sha256"] == hashlib.sha256(original_bytes).hexdigest().upper()
    assert not (output_directory / "synthetic").exists()
    assert source.read_bytes() == original_bytes


def test_different_explicit_inputs_produce_different_source_metadata(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "ch1.csv"
    second_source = tmp_path / "ch3.csv"
    _write_two_column_input(first_source, offset=1.0e-4)
    _write_two_column_input(second_source, offset=2.0e-4)

    monkeypatch.setattr(
        runner_module,
        "_run_real_data",
        lambda **_: runner_module.RealDataRun((), (), ()),
    )
    monkeypatch.setattr(runner_module, "_write_real_result_summary", lambda *_: None)

    first_output = tmp_path / "first_output"
    second_output = tmp_path / "second_output"
    for source, output_directory in (
        (first_source, first_output),
        (second_source, second_output),
    ):
        assert runner_module.main(
            ["--raw-data", str(source), "--output-directory", str(output_directory)]
        ) == 0

    first_metadata = json.loads((first_output / "run_metadata.json").read_text(encoding="utf-8"))
    second_metadata = json.loads((second_output / "run_metadata.json").read_text(encoding="utf-8"))
    assert first_metadata["source_path"] == str(first_source.resolve())
    assert second_metadata["source_path"] == str(second_source.resolve())
    assert first_metadata["source_sha256"] != second_metadata["source_sha256"]


def test_benchmark_mode_is_explicit_and_does_not_require_real_input(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "benchmark_output"
    captured_output_directories: list[Path] = []

    monkeypatch.setattr(
        runner_module,
        "_run_synthetic_benchmark",
        lambda path: captured_output_directories.append(path),
    )

    assert runner_module.main(
        ["--mode", "benchmark", "--output-directory", str(output_directory)]
    ) == 0
    assert captured_output_directories == [output_directory.resolve()]


def test_calibration_mode_requires_and_forwards_distinct_explicit_inputs(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "ch1.csv"
    second_source = tmp_path / "ch3.csv"
    _write_two_column_input(first_source, offset=1.0e-4)
    _write_two_column_input(second_source, offset=2.0e-4)
    output_directory = tmp_path / "calibration_output"
    captured: list[tuple[Path, ...]] = []

    def fake_calibration(*, raw_paths: tuple[Path, ...], **_: object) -> None:
        captured.append(raw_paths)

    monkeypatch.setattr(runner_module, "_run_real_data_calibration", fake_calibration)

    assert runner_module.main(
        [
            "--mode",
            "calibration",
            "--raw-data",
            str(first_source),
            "--raw-data",
            str(second_source),
            "--output-directory",
            str(output_directory),
        ]
    ) == 0
    assert captured == [(first_source.resolve(), second_source.resolve())]
    with pytest.raises(ValueError, match="unique"):
        runner_module.main(
            [
                "--mode",
                "calibration",
                "--raw-data",
                str(first_source),
                "--raw-data",
                str(first_source),
                "--output-directory",
                str(tmp_path / "invalid_calibration"),
            ]
        )


def test_calibration_metadata_records_grid_and_research_only_constraints(
    runner_module: ModuleType,
    tmp_path: Path,
) -> None:
    metadata = runner_module._calibration_run_metadata(
        configuration=SimpleNamespace(config_path=tmp_path / "config.toml"),
        input_metadata=({"source_filename": "ch3.csv"},),
        profile_metadata=({"profile_id": "balanced"},),
        output_directory=tmp_path / "output",
    )

    assert {
        "mode",
        "task",
        "raw_inputs",
        "stft_profiles",
        "top_k_sweep",
        "presets_by_top_k",
        "fixed_scientific_definitions",
        "calibrated_cost_terms",
        "manual_event_reference_in_path_cost",
        "production_default_modified",
        "dps_studio_import_path",
    } <= set(metadata)
    assert metadata["mode"] == "calibration"
    assert metadata["top_k_sweep"] == [5, 10, 15, 20]
    assert set(metadata["presets_by_top_k"]["20"]) == {
        "conservative",
        "balanced",
        "permissive",
    }
    assert not metadata["manual_event_reference_in_path_cost"]
    assert not metadata["production_default_modified"]


def test_real_mode_rejects_missing_or_invalid_input(runner_module: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--raw-data"):
        runner_module.main(["--output-directory", str(tmp_path / "missing")])
    with pytest.raises(FileNotFoundError, match="Raw input does not exist"):
        runner_module.main(
            [
                "--raw-data",
                str(tmp_path / "missing.csv"),
                "--output-directory",
                str(tmp_path / "invalid"),
            ]
        )
