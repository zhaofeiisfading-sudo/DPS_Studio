"""Regression coverage for the Production Windows installer entry point."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath

import pytest

from scripts.build import build_windows_installer as installer
from scripts.maintenance.check_repo_hygiene import RELEASE_EXECUTABLE


@pytest.fixture
def iscc_locations(tmp_path, monkeypatch):
    roots = {key: tmp_path / key for key in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramW6432")}
    for key, root in roots.items():
        monkeypatch.setenv(key, str(root))
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    return [
        roots["LOCALAPPDATA"] / "Programs" / "Inno Setup 6" / "ISCC.exe",
        roots["ProgramFiles(x86)"] / "Inno Setup 6" / "ISCC.exe",
        roots["ProgramW6432"] / "Inno Setup 6" / "ISCC.exe",
    ]


def _touch_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test executable")
    return path


def test_iscc_explicit_path_takes_precedence(iscc_locations, tmp_path, monkeypatch):
    explicit = _touch_executable(tmp_path / "custom location" / "ISCC.exe")
    monkeypatch.setattr(installer.shutil, "which", lambda _: str(iscc_locations[0]))
    assert installer.find_iscc(explicit) == explicit
    with pytest.raises(FileNotFoundError, match="ISCC.exe not found"):
        installer.find_iscc(tmp_path / "missing.exe")


def test_iscc_path_takes_precedence_over_installed_locations(iscc_locations, tmp_path, monkeypatch):
    _touch_executable(iscc_locations[0])
    on_path = _touch_executable(tmp_path / "bin" / "ISCC.exe")
    monkeypatch.setattr(installer.shutil, "which", lambda name: str(on_path)
                        if name == "ISCC.exe" else None)
    assert installer.find_iscc() == on_path


@pytest.mark.parametrize("location", [0, 1, 2])
def test_iscc_standard_locations_are_searched_in_order(iscc_locations, location):
    for path in iscc_locations[location:]:
        _touch_executable(path)
    assert installer.find_iscc() == iscc_locations[location]


def test_iscc_reports_missing_compiler(iscc_locations):
    with pytest.raises(FileNotFoundError, match="--iscc"):
        installer.find_iscc()


@pytest.mark.parametrize(("status", "allow_dirty", "expected"), [
    ("", False, {"commit_sha": "abc", "worktree_clean": True}),
    ("", True, {"commit_sha": "abc", "worktree_clean": True}),
    (" M src/example.py\n", True, {"commit_sha": "abc-dirty", "worktree_clean": False}),
    ("?? new.py\n", False, None),
])
def test_source_provenance_dirty_gate(monkeypatch, status, allow_dirty, expected):
    def git(command, *, cwd, text):
        assert cwd == installer.PROJECT_ROOT and text
        assert command[:2] == ["git", "--no-optional-locks"]
        if command[2:] == ["status", "--porcelain", "--untracked-files=all"]:
            return status
        assert command[2:] == ["rev-parse", "HEAD"]
        return "abc\n"

    monkeypatch.setattr(installer.subprocess, "check_output", git)
    if expected is None:
        with pytest.raises(RuntimeError, match="--allow-dirty"):
            installer.source_provenance(allow_dirty=allow_dirty)
    else:
        assert installer.source_provenance(allow_dirty=allow_dirty) == expected


@pytest.mark.parametrize("allow_dirty", [False, True])
def test_main_forwards_allow_dirty_before_creating_build(monkeypatch, tmp_path, allow_dirty):
    source = tmp_path / "wave.csv"
    source.write_text("0,1,2\n", encoding="ascii")
    output = tmp_path / "build" / "installer"
    command = [
        "build_windows_installer.py", "--output-root", str(output),
        "--analysis-smoke-input", str(source),
    ]
    if allow_dirty:
        command.append("--allow-dirty")
    monkeypatch.setattr(sys, "argv", command)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "maxsize", 2**63 - 1)
    monkeypatch.setattr(installer.platform, "machine", lambda: "AMD64")
    monkeypatch.setenv("SystemDrive", "Q:")
    monkeypatch.setattr(installer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(installer, "find_iscc", lambda _: tmp_path / "ISCC.exe")

    def reject(*, allow_dirty):
        assert allow_dirty == ("--allow-dirty" in command)
        raise RuntimeError("dirty gate reached")

    monkeypatch.setattr(installer, "source_provenance", reject)
    with pytest.raises(RuntimeError, match="dirty gate reached"):
        installer.main()
    assert not output.exists()


def test_layout_reports_missing_files_and_directories(tmp_path):
    file = tmp_path / "pdv.exe"
    file.write_bytes(b"")
    with pytest.raises(RuntimeError, match=r"PDV Studio\.exe.*userdata/cache"):
        installer.check_layout(
            tmp_path, files=("PDV Studio.exe", "pdv.exe"), dirs=("userdata/cache",),
        )
    (tmp_path / "userdata/cache").mkdir(parents=True)
    installer.check_layout(tmp_path, files=("pdv.exe",), dirs=("userdata/cache",))


def test_cli_smoke_config_matches_gui_fixture():
    config = installer.smoke_config(
        installer.PROJECT_ROOT / "configs" / "pdv_studio_defaults.toml",
    )
    assert config["time_column"] == 0 and config["time_unit"] == "s"
    assert config["voltage_columns"] == {"pdv_channel_1": 1, "pdv_channel_2": 2}
    assert set(config["voltage_units"].values()) == {"V"}
    assert config["vacuum_wavelength_m"] == 1.55e-6
    assert config["measurement_angle_rad"] == 0
    assert config["window_material"] == "LiF"
    assert config["profile"] == "balanced"


def test_runtime_environment_drops_userdata_and_plot_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("PDV_STUDIO_USERDATA_DIR", "other userdata")
    monkeypatch.setenv("MPLCONFIGDIR", "other plot cache")
    monkeypatch.setenv("TMPDIR", "other temp")
    environment = installer.runtime_environment(tmp_path)
    assert all(key not in environment for key in ("PDV_STUDIO_USERDATA_DIR", "MPLCONFIGDIR", "TMPDIR"))
    assert environment["TEMP"] == environment["TMP"] == os.fspath(tmp_path)


def test_appdata_snapshot_detects_empty_directories_and_new_files(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    local = tmp_path / "Local"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    before = installer.appdata_snapshot()
    assert len(before) == 4 and all(not entries for entries in before.values())
    root = appdata / "DPS Studio"
    (root / "empty").mkdir(parents=True)
    (root / "new").write_bytes(b"settings")
    assert installer.appdata_snapshot()[str(root)] == [".", "empty", "new"]


def test_wait_for_uninstall_waits_for_the_detached_worker(tmp_path, monkeypatch):
    entry = iter([{"DisplayName": "PDV Studio"}, None])
    monkeypatch.setattr(installer, "installed_registration", lambda: next(entry))
    sleeps = []
    monkeypatch.setattr(installer.time, "sleep", sleeps.append)
    installer.wait_for_uninstall(tmp_path / "unins000.exe", purge=False)
    assert sleeps == [0.1]


def test_wait_for_uninstall_fails_if_purge_leaves_the_app_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "installed_registration", lambda: None)
    with pytest.raises(RuntimeError, match="Uninstall cleanup did not finish"):
        installer.wait_for_uninstall(tmp_path / "unins000.exe", purge=True, timeout=0)


def test_inno_project_has_per_user_setup_and_userdata_contract():
    iss = (installer.PROJECT_ROOT / "packaging/pdv_studio_installer.iss").read_text(encoding="utf-8")
    assert set(re.findall(r"^\[(\w+)\]$", iss, re.M)) == {
        "Setup", "Languages", "Tasks", "Dirs", "Files", "Icons", "Code",
    }
    for name in ("MyAppVersion", "ProjectRoot", "OnedirSource", "OutputDir", "OutputBaseFilename"):
        assert f"#ifndef {name}\n  #define {name}" in iss
    for setting in (
        f"AppId={{{installer.APP_ID}", "PrivilegesRequired=lowest",
        "ArchitecturesAllowed=x64compatible", "ArchitecturesInstallIn64BitMode=x64compatible",
        r"DefaultDirName={code:GetPreferredInstallRoot}\PDV Studio",
        'MessagesFile: "compiler:Default.isl"', "ChangesEnvironment=yes",
    ):
        assert setting in iss
    for task in ("desktopicon", "addtopath"):
        assert re.search(rf'^Name: "{task}";.*Flags: unchecked$', iss, re.M)
    for data in ("", *(f"\\{name}" for name in installer.USERDATA_DIRS)):
        assert f'Name: "{{app}}\\userdata{data}"; Flags: uninsneveruninstall' in iss
    for name in ("CanWriteToTargetDir", "WizardSilent()", "RegQueryStringValue",
                 "UninstallSilent()", "/PURGEUSERDATA=1", "MB_DEFBUTTON1"):
        assert name in iss
    assert "ChineseSimplified.isl" not in iss and "HKLM" not in iss


def test_notices_record_runtime_licenses():
    packaging = installer.PROJECT_ROOT / "packaging"
    notice = (packaging / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    for term in (
        "Python 3.12", "Foundation License Agreement", "NumPy", "SciPy", "Pandas", "BSD 3-Clause",
        "PySide6", "LGPL version 3", "dynamically linked and replaceable", "_internal/PySide6/",
        "PyQtGraph", "Pydantic", "pydantic-core", "MIT License",
    ):
        assert term in notice
    assert (packaging / "licenses/Qt/GPL-3.0-only.txt").is_file()
    assert (packaging / "licenses/Qt/LGPL-3.0-only.txt").is_file()


@pytest.mark.parametrize("package", [
    "release/PDV-Studio-Setup-x64.exe", "build/staging/PDV-Studio-Setup-x64.exe",
    "release/PDV_Studio_v0.2.0_Windows_x64.exe",
])
def test_hygiene_recognizes_installer_and_historical_executable(package):
    assert RELEASE_EXECUTABLE.fullmatch(PurePosixPath(package).name)
