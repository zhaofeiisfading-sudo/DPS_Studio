"""Static safety checks for Research worktree launcher scripts."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _launcher(name: str) -> str:
    return (REPOSITORY_ROOT / name).read_text(encoding="utf-8")


def test_global_path_launcher_uses_its_own_root_and_research_source() -> None:
    launcher = _launcher("run_research_global_path.bat")

    assert 'set "ROOT=%~dp0"' in launcher
    assert 'set "DPS_RESEARCH_SRC=%ROOT%src"' in launcher
    assert 'set "PYTHONPATH=%DPS_RESEARCH_SRC%;%PYTHONPATH%"' in launcher
    assert "conda" in launcher.lower()
    assert "dps_studio import:" in launcher
    assert "is_relative_to(research_src)" in launcher
    assert "OpenFileDialog" in launcher
    assert "--mode real --raw-data \"%RAW_DATA%\"" in launcher
    assert "--raw-data" in launcher
    assert "--output-directory" in launcher


def test_research_gui_launcher_checks_import_before_starting_gui() -> None:
    launcher = _launcher("run_research_gui.bat")

    assert 'set "ROOT=%~dp0"' in launcher
    assert 'set "PYTHONPATH=%DPS_RESEARCH_SRC%;%PYTHONPATH%"' in launcher
    assert "dps_studio import:" in launcher
    assert "is_relative_to(research_src)" in launcher
    assert "python -m dps_studio.gui" in launcher
    assert "Type RUN" in launcher


def test_legacy_gui_entry_delegates_to_the_research_safe_launcher() -> None:
    launcher = _launcher("run_pdv_studio_gui.bat")

    assert "This is the Research worktree." in launcher
    assert "run_research_global_path.bat" in launcher
    assert 'call "%~dp0run_research_gui.bat" %*' in launcher


def test_production_demo_is_explicitly_disabled_in_research_worktree() -> None:
    launcher = _launcher("run_demo_pipeline.bat")

    assert "Production demo launcher is disabled in Research worktree." in launcher
    assert "run_research_global_path.bat" in launcher


def test_research_worktree_documentation_names_the_safe_entry_points() -> None:
    document = _launcher("RESEARCH_WORKTREE.md")

    assert "TASK-021A Global Candidate-Path Ridge Tracking" in document
    assert "run_research_global_path.bat" in document
    assert "run_research_gui.bat" in document
