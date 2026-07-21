from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pytest import MonkeyPatch

from dps_studio.core import BALANCED_PROFILE, OutputMode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIRECTORY = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import run_demo_pipeline as pipeline  # noqa: E402


def test_cli_defaults_are_balanced_production() -> None:
    arguments = pipeline._parse_arguments([])  # noqa: SLF001
    assert arguments.profile == "balanced"
    assert arguments.output_mode == "production"


def test_diagnostic_mode_reuses_all_existing_stages_without_window_scan(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    def task007(output_directory: Path, **kwargs: object) -> list[Path]:
        calls.append(("task007", kwargs))
        return [output_directory / f"task007_{index}.out" for index in range(19)]

    def task008a(output_directory: Path, **kwargs: object) -> list[Path]:
        calls.append(("task008a", kwargs))
        return [output_directory / f"task008a_{index}.out" for index in range(7)]

    def task008b(output_directory: Path, **kwargs: object) -> list[Path]:
        calls.append(("task008b", kwargs))
        return [output_directory / f"task008b_{index}.out" for index in range(12)]

    monkeypatch.setattr(pipeline, "run_demo", task007)
    monkeypatch.setattr(pipeline, "run_spectral_quality_demo", task008a)
    monkeypatch.setattr(pipeline, "run_ridge_diagnostics_demo", task008b)

    paths = pipeline._run_diagnostic(  # noqa: SLF001
        tmp_path / "diagnostic",
        BALANCED_PROFILE,
    )

    assert len(paths) == 38
    assert [name for name, _ in calls] == ["task007", "task008a", "task008b"]
    assert calls[0][1] == {
        "run_window_diagnostics": False,
        "profile": BALANCED_PROFILE,
    }
    assert calls[1][1] == {"profile": BALANCED_PROFILE}
    assert calls[2][1] == {"profile": BALANCED_PROFILE}


def test_daily_pipeline_source_does_not_reference_development_audit() -> None:
    source = (SCRIPTS_DIRECTORY / "run_demo_pipeline.py").read_text(encoding="utf-8")
    assert "audit_legacy_velocity_reference" not in source
    assert "window-diagnostics" not in source


def test_run_pipeline_rejects_implicit_output_mode(tmp_path: Path) -> None:
    try:
        pipeline.run_pipeline(
            tmp_path / "invalid",
            profile=BALANCED_PROFILE,
            output_mode="production",  # type: ignore[arg-type]
        )
    except TypeError as exc:
        assert "OutputMode" in str(exc)
    else:
        raise AssertionError("String output_mode was silently accepted.")


def test_invalid_cli_values_return_nonzero() -> None:
    for arguments in (
        ("--profile", "automatic"),
        ("--output-mode", "everything"),
    ):
        completed = subprocess.run(
            (sys.executable, SCRIPTS_DIRECTORY / "run_demo_pipeline.py", *arguments),
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode != 0
        assert "invalid choice" in completed.stderr


def test_output_modes_are_explicit_and_complete() -> None:
    assert tuple(mode.value for mode in OutputMode) == ("production", "diagnostic")
