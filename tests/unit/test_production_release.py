"""Regressions for release isolation, runtime validation, and publication."""

import json
import os
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dps_studio import __version__


BUILD = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/build/build_production_release.py"))
MAIN = BUILD["main"]
BUILD_GLOBALS = MAIN.__globals__


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


def test_release_requires_clean_committed_source(monkeypatch):
    calls = []

    def dirty(command, **kwargs):
        calls.append(command)
        return " M src/dps_studio/__init__.py\n"

    monkeypatch.setattr(BUILD["subprocess"], "check_output", dirty)
    with pytest.raises(RuntimeError, match="work tree is not clean"):
        BUILD["committed_source"]()
    assert len(calls) == 1
    responses = iter(["", "a" * 40 + "\n"])
    monkeypatch.setattr(BUILD["subprocess"], "check_output", lambda *_args, **_kw: next(responses))
    assert BUILD["committed_source"]() == "a" * 40


def test_onedir_release_directory(tmp_path):
    assert BUILD["onedir_release_directory"](tmp_path, "0.2.0") == (
        tmp_path / "PDV_Studio_v0.2.0_Windows_x64"
    )


def test_onedir_and_onefile_are_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["release", "--output-root", "build/task023", "--onefile", "--onedir-folder"])
    with pytest.raises(SystemExit) as exc:
        MAIN()
    assert exc.value.code == 2
    assert "not allowed with argument --onefile" in capsys.readouterr().err


def test_onedir_requires_analysis_input(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["release", "--output-root", "build/task023", "--onedir-folder"])
    with pytest.raises(ValueError, match="require --analysis-smoke-input"):
        MAIN()


@pytest.fixture
def onedir_cli(tmp_path, monkeypatch):
    project = tmp_path / "project"
    output = project / "build" / "task023"
    target = project / "release" / f"PDV_Studio_v{__version__}_Windows_x64"
    source = tmp_path / "source.csv"
    source.write_text("time,voltage\n", encoding="utf-8")
    monkeypatch.setitem(BUILD_GLOBALS, "PROJECT_ROOT", project)
    monkeypatch.setattr(sys, "argv", [
        "release", "--output-root", str(output), "--onedir-folder", "--analysis-smoke-input", str(source),
    ])
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(BUILD["platform"], "machine", lambda: "AMD64")
    return project, output, target, source


@pytest.mark.parametrize(("host", "maxsize", "machine"), [
    ("linux", 2**63 - 1, "AMD64"),
    ("win32", 2**31 - 1, "AMD64"),
    ("win32", 2**63 - 1, "ARM64"),
])
def test_onedir_requires_native_windows_x64(onedir_cli, monkeypatch, host, maxsize, machine):
    monkeypatch.setattr(sys, "platform", host)
    monkeypatch.setattr(sys, "maxsize", maxsize)
    monkeypatch.setattr(BUILD["platform"], "machine", lambda: machine)
    with pytest.raises(RuntimeError, match="require a native Windows x64"):
        MAIN()


def test_onedir_refuses_to_overwrite_existing_directory(onedir_cli):
    _, output, target, _ = onedir_cli
    target.mkdir(parents=True)
    marker = target / "README.txt"
    marker.write_bytes(b"existing release")
    with pytest.raises(FileExistsError, match="Will not overwrite existing release"):
        MAIN()
    assert marker.read_bytes() == b"existing release"
    assert not output.exists()


@pytest.mark.parametrize("failure", [None, "verification", "commit"])
def test_onedir_publishes_only_after_verification_and_commit_recheck(onedir_cli, monkeypatch, failure):
    project, output, target, source = onedir_cli
    directory = output / "dist" / f"PDV_Studio_v{__version__}"
    docs = project / "docs"
    docs.mkdir(parents=True)
    notes = f"# PDV Studio {__version__}\n"
    (docs / f"RELEASE_NOTES_{__version__}.md").write_text(notes, encoding="utf-8")
    commits = iter(["initial", "changed" if failure == "commit" else "initial"])
    monkeypatch.setitem(BUILD_GLOBALS, "committed_source", lambda: next(commits))
    monkeypatch.setattr(BUILD["importlib"].metadata, "version", lambda _: "test")
    components = {"qt_windows_platform": ["_internal/qwindows.dll"]}
    executable = directory / "PDV Studio.exe"

    def mock_build(command, *, cwd, env, stdout, stderr, check):
        assert command[1:3] == ["-m", "PyInstaller"]
        assert command[-1] == str(project / "packaging" / "pdv_studio.spec")
        assert cwd == project
        assert env["DPS_STUDIO_ONEFILE"] == "0"
        assert check
        (directory / "_internal").mkdir(parents=True)
        executable.write_bytes(b"test executable")
        (directory / "_internal" / "qwindows.dll").write_bytes(b"test runtime")

    def mock_runtime(candidate):
        assert candidate == directory
        assert executable.is_file()
        return components

    def mock_verify(candidate, *, analysis_input, workflow_smoke=True):
        assert candidate == directory
        assert analysis_input == source
        assert workflow_smoke
        assert (candidate / "RELEASE_NOTES.md").read_text(encoding="utf-8") == notes
        guide = (candidate / "README.txt").read_text(encoding="utf-8")
        assert all(text in guide for text in (__version__, "Windows x64", "PDV Studio.exe", "_internal/"))
        info = json.loads((candidate / "BUILD_INFO.json").read_text(encoding="utf-8"))
        assert info["commit_sha"] == "initial"
        assert not target.exists()
        if failure == "verification":
            raise RuntimeError("mock smoke test failed")
        return {"packaged_files_unchanged_after_execution": True}

    monkeypatch.setattr(BUILD["subprocess"], "run", mock_build)
    monkeypatch.setitem(BUILD_GLOBALS, "runtime_files", mock_runtime)
    monkeypatch.setitem(BUILD_GLOBALS, "verify_onedir_directory", mock_verify)
    manifest_path = output / "release_manifest.json"
    if failure is not None:
        message = "mock smoke test failed" if failure == "verification" else "Source changed"
        with pytest.raises(RuntimeError, match=message):
            MAIN()
        assert not target.exists()
        assert not manifest_path.exists()
        return

    assert MAIN() == 0
    assert list(target.parent.iterdir()) == [target]
    assert list((output / "dist").iterdir()) == []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_directory"] == str(target)
    assert manifest["exe_path"] == str(target / executable.name)
    assert manifest["runtime_files"] == components
    assert manifest["file_sha256"] == BUILD["tree_hashes"](target)
    assert manifest["verification"]["packaged_files_unchanged_after_execution"]
    assert manifest["commit_sha"] == "initial"
    assert manifest["built_at_utc"] == json.loads((target / "BUILD_INFO.json").read_text())["built_at_utc"]


@pytest.mark.parametrize(
    ("changed", "workflow", "missing_check", "error"),
    [
        (False, True, None, None),
        (False, False, None, None),
        (True, True, None, "changed its packaged files"),
        (False, True, "icon_loaded", "Dechirp or application icon verification"),
        (False, True, "dechirp_plot_and_export_match", "Dechirp or application icon verification"),
    ],
)
def test_verify_onedir_directory(tmp_path, monkeypatch, changed, workflow, missing_check, error):
    project = tmp_path / "project"
    directory = project / "candidate"
    directory.mkdir(parents=True)
    executable = directory / "PDV Studio.exe"
    executable.write_bytes(b"test executable")
    source = tmp_path / "original.csv"
    source.write_text("t,v\n0,0\n", encoding="utf-8")
    monkeypatch.setitem(BUILD_GLOBALS, "PROJECT_ROOT", project)
    monkeypatch.setattr(BUILD["tempfile"], "tempdir", str(tmp_path))
    environment = {"PATH": "isolated"}
    startup = {"analysis_smoke": {"status": "PASS"}}
    workflow_report = {"dechirp_plot_and_export_match": True, "icon_loaded": True}
    if missing_check is not None:
        del workflow_report[missing_check]
    calls = []

    def isolate():
        calls.append("isolate")
        return environment

    def launch(command, *, cwd, env, timeout, capture_output, text):
        calls.append("launch")
        assert env is environment
        assert env["TEMP"] == env["TMP"] == str(cwd)
        assert not cwd.is_relative_to(project)
        assert not cwd.is_relative_to(Path(sys.prefix))
        assert command == [
            str(executable), "--startup-smoke-test", str(cwd / "startup.json"),
            "--analysis-smoke-input", str(cwd / "example.csv"),
        ]
        assert timeout == 90 and capture_output and text
        assert (cwd / "example.csv").read_bytes() == source.read_bytes()
        (cwd / "startup.json").write_text(json.dumps(startup), encoding="utf-8")
        if changed:
            executable.write_bytes(b"changed")
        return SimpleNamespace(returncode=0, stderr="")

    def validate(report, runtime, *, require_analysis):
        calls.append("validate")
        assert (report, runtime, require_analysis) == (startup, directory, True)

    def run_workflow(exe, runtime, root, copied_input, env):
        calls.append("workflow")
        assert (exe, runtime, copied_input) == (executable, directory, root / "example.csv")
        assert env is environment
        return [workflow_report]

    monkeypatch.setitem(BUILD_GLOBALS, "isolated_environment", isolate)
    monkeypatch.setattr(BUILD["subprocess"], "run", launch)
    monkeypatch.setitem(BUILD_GLOBALS, "validate_startup_report", validate)
    monkeypatch.setitem(BUILD_GLOBALS, "verify_gui_workflow", run_workflow)
    options = {} if workflow else {"workflow_smoke": False}
    verify = BUILD["verify_onedir_directory"]
    if error:
        with pytest.raises(RuntimeError, match=error):
            verify(directory, analysis_input=source, **options)
    else:
        result = verify(directory, analysis_input=source, **options)
        assert result["startup"] == startup
        assert result["packaged_files_unchanged_after_execution"] is True
        assert result["gui_workflows"] == ([workflow_report] if workflow else [])
    assert calls == ["isolate", "launch", "validate"] + (["workflow"] if workflow else [])
    assert list(tmp_path.glob("dps_production_onedir_*")) == []
