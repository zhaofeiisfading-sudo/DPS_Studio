import sys
import tomllib
from pathlib import Path

from pytest import MonkeyPatch

from dps_studio import __version__
from dps_studio.cli import main


def test_version() -> None:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/dps_studio/__init__.py"
    assert len(__version__.split(".")) == 3


def test_cli(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["dps-studio"])
    assert main() == 0
