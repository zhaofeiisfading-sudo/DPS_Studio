from dps_studio import __version__
from dps_studio.cli import main


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_cli() -> None:
    assert main() == 0