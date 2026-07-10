from __future__ import annotations

import argparse

from dps_studio import __version__


def main() -> int:
    parser = argparse.ArgumentParser(prog="dps-studio")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())