from __future__ import annotations

import sys
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest

from dps_studio.runtime_paths import (
    application_resource_path,
    application_resource_root,
    package_resource_path,
)


def test_installed_layout_starts_without_access_to_checkout_or_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    site = tmp_path / "site"
    package = site / "dps_studio"
    shutil.copytree(root / "src/dps_studio", package, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(root / "configs", package / "resources/configs")
    report = tmp_path / "startup.json"
    code = '''
import json, sys
from pathlib import Path
blocked, allowed, report = map(Path, sys.argv[1:])
def guard(event, args):
    if event in ("open", "os.listdir", "os.scandir") and args and isinstance(args[0], (str, bytes)):
        item = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).resolve()
        if any(item.is_relative_to(root) for root in (blocked, blocked.parent / "DPS_Studio",
                                                     blocked.parent / "DPS_Studio_TASK021A")) and not item.is_relative_to(allowed):
            raise AssertionError(f"Installed application accessed original checkout: {item}")
sys.addaudithook(guard)
from dps_studio.runtime_paths import application_resource_path
assert application_resource_path("configs", "pdv_studio_defaults.toml").is_file()
from dps_studio.core.segmentation.pool import default_pool
assert len(default_pool().algorithms) >= 3
from dps_studio.research.task009_runtime import provenance
assert len(provenance()["methods"]) == 14
from dps_studio.gui.app import main
raise SystemExit(main(["pdv", "--startup-smoke-test", str(report)]))
'''
    environment = dict(os.environ, PYTHONPATH=str(site), PYTHONDONTWRITEBYTECODE="1",
                       PYTHONPYCACHEPREFIX=str(tmp_path / "pycache"),
                       TMP=str(tmp_path), TEMP=str(tmp_path),
                       MPLCONFIGDIR=str(tmp_path / "matplotlib"),
                       QT_QPA_PLATFORM="windows" if sys.platform == "win32" else "offscreen")
    result = subprocess.run([sys.executable, "-B", "-c", code, str(root), str(tmp_path), str(report)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, (result.stdout + result.stderr +
        (report.read_text(encoding="utf-8") if report.exists() else "no startup report"))
    assert json.loads(report.read_text(encoding="utf-8"))["event_loop_entered"] is True



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
