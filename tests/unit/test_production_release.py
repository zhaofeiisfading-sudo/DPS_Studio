"""Regressions for PATH contamination and runtime component validation."""

import os
import runpy
import sys
from pathlib import Path

import pytest


BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/build_production_release.py"))


def test_build_and_smoke_environments_exclude_foreign_dll_paths(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\foreign\poppler;C:\another\Qt")
    monkeypatch.setenv("PYTHONPATH", r"C:\foreign\python")
    monkeypatch.setenv("QT_PLUGIN_PATH", r"C:\foreign\plugins")
    monkeypatch.setenv("CONDA_PREFIX", r"C:\foreign\conda")
    smoke = BUILD["isolated_environment"]()
    build = BUILD["build_environment"]()
    assert "foreign" not in smoke["PATH"]
    assert "foreign" not in build["PATH"]
    for environment in (smoke, build):
        assert "PYTHONPATH" not in environment
        assert "QT_PLUGIN_PATH" not in environment
        assert "CONDA_PREFIX" not in environment
    assert str(Path(sys.executable).parent) in build["PATH"].split(os.pathsep)


def test_runtime_validation_reports_missing_components_and_accepts_real_layout(tmp_path):
    with pytest.raises(RuntimeError, match="Release runtime components missing"):
        BUILD["runtime_files"](tmp_path)
    names = (
        "_internal/shiboken6/Shiboken.pyd", "_internal/shiboken6/shiboken6.abi3.dll",
        "_internal/PySide6/plugins/platforms/qwindows.dll",
        "_internal/scipy/_lib/_ccallback_c.cp312-win_amd64.pyd",
        "_internal/PySide6/QtCore.pyd", "_internal/PySide6/Qt6Core.dll",
    )
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test component")
    assert all(BUILD["runtime_files"](tmp_path).values())
