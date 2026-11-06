from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dps_studio.runtime_paths import (
    application_resource_path,
    application_resource_root,
    package_resource_path,
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
