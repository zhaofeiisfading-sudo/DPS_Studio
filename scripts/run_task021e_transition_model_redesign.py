"""Run TASK-021E Research-only robust and curvature transition experiments."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from dps_studio.research.task021e_transition_models import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    REPOSITORY_ROOT,
    run_task021e,
)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=(
            REPOSITORY_ROOT
            / "artifacts"
            / "task021e_transition_model_redesign"
            / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        ),
    )
    parsed = parser.parse_args(arguments)
    outcome = run_task021e(
        raw_root=parsed.raw_root,
        config_path=parsed.config,
        output_directory=parsed.output_directory,
    )
    print(f"TASK-021E output: {outcome['output_directory']}")
    print(f"Prepared streams: {outcome['stream_count']}")
    print(f"Raw hashes unchanged: {outcome['raw_hashes_equal']}")
    print(f"Pure-noise-safe models: {', '.join(outcome['passing'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
