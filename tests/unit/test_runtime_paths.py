from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from dps_studio.runtime_paths import (
    USERDATA_ENV_VAR,
    RuntimeStorageError,
    application_resource_path,
    application_resource_root,
    ensure_userdata_directories,
    initialize_runtime_storage,
    installation_root,
    package_resource_path,
    user_settings_path,
    userdata_path,
    userdata_paths,
    userdata_root,
    window_preset_file_path,
)


def test_source_resource_paths_find_runtime_files() -> None:
    root = application_resource_root()

    assert application_resource_path("configs", "pdv_studio_defaults.toml").is_file()
    assert package_resource_path(
        "gui", "translations", "pdv_studio_en.qm"
    ).is_file()
    assert root == Path(__file__).resolve().parents[2]


def test_frozen_resource_paths_use_meipass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert application_resource_root() == tmp_path.resolve()
    assert application_resource_path("configs", "defaults.toml") == (
        tmp_path / "configs" / "defaults.toml"
    ).resolve()
    assert package_resource_path("gui", "translations", "english.qm") == (
        tmp_path / "dps_studio" / "gui" / "translations" / "english.qm"
    ).resolve()


def test_invalid_frozen_resource_root_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)

    with pytest.raises(RuntimeError, match="_MEIPASS"):
        application_resource_root()


@pytest.mark.parametrize("frozen", [False, True])
def test_default_userdata_is_relative_to_installation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frozen: bool,
) -> None:
    launch_dir = tmp_path / "启动 目录"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    monkeypatch.delenv(USERDATA_ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundled resources"), raising=False)
    installed = tmp_path / "安装 目录"
    monkeypatch.setattr(sys, "executable", str(installed / "PDV Studio.exe"))
    expected_installation = installed if frozen else Path(__file__).resolve().parents[2]
    expected_userdata = expected_installation / "userdata" if frozen else (
        expected_installation / "artifacts" / "userdata"
    )

    assert installation_root() == expected_installation
    assert userdata_root() == expected_userdata
    monkeypatch.setenv(USERDATA_ENV_VAR, "  ")
    assert userdata_root() == expected_userdata


def test_explicit_userdata_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    environment_root = tmp_path / "便携 配置"
    explicit_root = tmp_path / "指定 位置"
    monkeypatch.setenv(USERDATA_ENV_VAR, environment_root.name)

    assert userdata_root() == environment_root
    assert userdata_root(Path(explicit_root.name)) == explicit_root
    assert userdata_path("presets", "example.json") == environment_root / "presets/example.json"
    assert user_settings_path(explicit_root) == explicit_root / "config/settings.ini"
    assert window_preset_file_path() == environment_root / "materials/window_presets.json"
    assert not environment_root.exists()
    assert not explicit_root.exists()


def test_ensure_userdata_directories_creates_layout_and_removes_probes(tmp_path: Path) -> None:
    root = tmp_path / "本地 数据"
    paths = ensure_userdata_directories(root)

    assert paths == userdata_paths(root)
    assert {path.name for path in root.iterdir()} == {
        "config", "materials", "presets", "cache", "logs", "temp",
    }
    assert all(path.is_dir() and not list(path.iterdir()) for path in root.iterdir())
    assert ensure_userdata_directories(root) == paths


@pytest.mark.parametrize("redirect_temp", [False, True])
def test_initialize_runtime_storage_sets_process_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, redirect_temp: bool,
) -> None:
    original_temp = str(tmp_path / "original temp")
    for variable in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(variable, original_temp)
    for variable in ("MPLCONFIGDIR", "QT_SETTINGS_PATH"):
        monkeypatch.setenv(variable, "before initialization")
    monkeypatch.setattr(tempfile, "tempdir", original_temp)

    paths = initialize_runtime_storage(tmp_path / "userdata", redirect_process_temp=redirect_temp)

    matplotlib_dir = paths.cache_dir / "matplotlib"
    assert matplotlib_dir.is_dir()
    assert os.environ["MPLCONFIGDIR"] == str(matplotlib_dir)
    assert os.environ["QT_SETTINGS_PATH"] == str(paths.config_dir)
    expected_temp = str(paths.temp_dir) if redirect_temp else original_temp
    for variable in ("TEMP", "TMP", "TMPDIR"):
        assert os.environ[variable] == expected_temp
    assert tempfile.tempdir == expected_temp


def test_userdata_root_creation_failure_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    root = tmp_path / "blocked userdata"
    root.write_text("an existing file", encoding="utf-8")
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv(USERDATA_ENV_VAR, str(root))

    with pytest.raises(RuntimeStorageError, match="not writable.*does not silently fall back") as exc:
        ensure_userdata_directories()

    assert str(root) in str(exc.value)
    assert isinstance(exc.value.__cause__, OSError)
    assert root.read_text(encoding="utf-8") == "an existing file"
    assert not appdata.exists()


@pytest.mark.parametrize("directory_name", [".", "config"])
def test_userdata_write_probe_checks_root_and_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, directory_name: str,
) -> None:
    root = tmp_path / "userdata"
    denied_directory = root / directory_name
    open_probe = tempfile.NamedTemporaryFile

    def probe(*, dir: Path, prefix: str):
        if dir == denied_directory:
            raise PermissionError("write denied")
        return open_probe(dir=dir, prefix=prefix)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", probe)

    with pytest.raises(RuntimeStorageError, match="not writable") as exc:
        ensure_userdata_directories(root)

    assert str(denied_directory) in str(exc.value)
    assert isinstance(exc.value.__cause__, PermissionError)
    assert not list(root.rglob(".write-probe-*"))


@pytest.mark.parametrize(
    "qt_platform, flags", [("windows", ["--no-error-dialog"]), ("offscreen", [])],
)
def test_application_reports_unwritable_userdata(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    qt_platform: str, flags: list[str],
) -> None:
    from dps_studio.gui import app

    message = "PDV Studio userdata path is not writable: blocked userdata."
    initialize = Mock(side_effect=RuntimeStorageError(message))
    show_error = Mock()
    monkeypatch.setenv("QT_QPA_PLATFORM", qt_platform)
    monkeypatch.setattr(app, "initialize_runtime_storage", initialize)
    monkeypatch.setattr(app.QMessageBox, "critical", show_error)

    assert app.main(["PDV Studio.exe", *flags]) == 2
    assert capsys.readouterr().err.strip() == message
    show_error.assert_not_called()


@pytest.mark.parametrize("smoke_flag", ["--startup-smoke-test", "--workflow-smoke-test"])
def test_smoke_startup_routes_application_to_report_userdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, smoke_flag: str,
) -> None:
    from dps_studio.gui import app

    class ApplicationCreationReached(Exception):
        pass

    create = Mock(side_effect=ApplicationCreationReached)
    monkeypatch.setattr(app, "create_application", create)
    monkeypatch.delenv(USERDATA_ENV_VAR, raising=False)
    for variable in ("MPLCONFIGDIR", "QT_SETTINGS_PATH"):
        monkeypatch.setenv(variable, "before initialization")
    report_path = tmp_path / "验收 输出" / "report.json"

    with pytest.raises(ApplicationCreationReached):
        app.main(["PDV Studio.exe", smoke_flag, str(report_path)])

    expected = userdata_paths(report_path.parent / "userdata")
    assert create.call_args.kwargs["storage_paths"] == expected
    assert os.environ["QT_SETTINGS_PATH"] == str(expected.config_dir)
    assert USERDATA_ENV_VAR not in os.environ
