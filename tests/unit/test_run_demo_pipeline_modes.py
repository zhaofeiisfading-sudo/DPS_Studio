from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dps_studio.core.workflow import load_workflow_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIRECTORY = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import run_demo_pipeline as pipeline  # noqa: E402


def test_cli_defaults_to_single_toml_and_timestamped_output() -> None:
    arguments = pipeline._parse_arguments([])  # noqa: SLF001
    assert arguments.config == pipeline.DEFAULT_CONFIG_PATH
    assert arguments.output_directory is None


def test_default_config_selects_both_formal_profiles_in_fixed_order() -> None:
    configuration = load_workflow_config(
        pipeline.DEFAULT_CONFIG_PATH,
        repository_root=PROJECT_ROOT,
    )
    assert [
        profile.profile_id.value for profile in configuration.analysis.profiles
    ] == ["balanced", "high_time_resolution"]


def test_new_default_directory_uses_contract_name(tmp_path: Path) -> None:
    output_directory = pipeline._new_default_output_directory(tmp_path)  # noqa: SLF001
    assert output_directory.parent == tmp_path
    assert output_directory.name.startswith("run_")
    assert len(output_directory.name) == len("run_YYYYMMDD_HHMMSS")


def test_daily_pipeline_source_has_no_development_or_profile_override() -> None:
    source = (SCRIPTS_DIRECTORY / "run_demo_pipeline.py").read_text(encoding="utf-8")
    assert "audit_legacy_velocity_reference" not in source
    assert "compare_real_ridge_refinement" not in source
    assert "assess_real_ridge" not in source
    assert '"--profile"' not in source
    assert '"--output-mode"' not in source


def test_run_pipeline_rejects_implicit_configuration(tmp_path: Path) -> None:
    try:
        pipeline.run_pipeline(
            tmp_path / "invalid",
            configuration="config.toml",  # type: ignore[arg-type]
        )
    except TypeError as exc:
        assert "WorkflowConfiguration" in str(exc)
    else:
        raise AssertionError("String configuration was silently accepted.")


def _temporary_output_configuration(tmp_path: Path) -> object:
    configuration = load_workflow_config(
        pipeline.DEFAULT_CONFIG_PATH,
        repository_root=PROJECT_ROOT,
    )
    return replace(
        configuration,
        output=replace(
            configuration.output,
            root=tmp_path / "outputs" / "production_runs",
        ),
    )


def test_formal_pipeline_rejects_output_outside_production_runs(
    tmp_path: Path,
) -> None:
    configuration = _temporary_output_configuration(tmp_path)
    with pytest.raises(ValueError, match="direct run directory"):
        pipeline.run_pipeline(
            tmp_path / "elsewhere" / "run_20260727_010500",
            configuration=configuration,
        )


def test_failed_production_does_not_update_latest_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _temporary_output_configuration(tmp_path)
    outputs_root = tmp_path / "outputs"
    outputs_root.mkdir()
    latest_path = outputs_root / "LATEST_RUN.txt"
    latest_path.write_text(
        "production_runs/run_previous\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        pipeline,
        "read_delimited_signals",
        lambda *args, **kwargs: SimpleNamespace(records={}),
    )

    def fail_run(*args: object, **kwargs: object) -> list[Path]:
        raise RuntimeError("synthetic production failure")

    monkeypatch.setattr(pipeline, "run_production_outputs", fail_run)
    with pytest.raises(RuntimeError, match="synthetic production failure"):
        pipeline.run_pipeline(
            configuration.output.root / "run_20260727_010501",
            configuration=configuration,
        )
    assert latest_path.read_text(encoding="utf-8") == (
        "production_runs/run_previous\n"
    )


def test_successful_production_updates_latest_run_and_prints_simple_exports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configuration = _temporary_output_configuration(tmp_path)
    monkeypatch.setattr(
        pipeline,
        "read_delimited_signals",
        lambda *args, **kwargs: SimpleNamespace(records={}),
    )

    def successful_run(
        output_directory: Path,
        *args: object,
        **kwargs: object,
    ) -> list[Path]:
        simple_directory = output_directory / "simple_exports"
        simple_directory.mkdir(parents=True)
        paths = []
        for profile_name in ("balanced", "high_time_resolution"):
            for channel_name in ("pdv_channel_1", "pdv_channel_2"):
                path = simple_directory / (
                    f"{profile_name}__{channel_name}"
                    "__apparent_velocity_time.csv"
                )
                path.write_text(
                    "time_s,apparent_velocity_m_s\n",
                    encoding="utf-8",
                )
                paths.append(path)
        return paths

    monkeypatch.setattr(pipeline, "run_production_outputs", successful_run)
    output_directory = (
        configuration.output.root / "run_20260727_010502"
    )
    pipeline.run_pipeline(
        output_directory,
        configuration=configuration,
    )

    latest_path = tmp_path / "outputs" / "LATEST_RUN.txt"
    assert latest_path.read_text(encoding="utf-8") == (
        "production_runs/run_20260727_010502\n"
    )
    terminal_output = capsys.readouterr().out
    assert "Production run completed:" in terminal_output
    assert "production_runs/run_20260727_010502" in terminal_output
    assert (
        "simple_exports/"
        "balanced__pdv_channel_1__apparent_velocity_time.csv"
    ) in terminal_output
