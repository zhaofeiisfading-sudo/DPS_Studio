"""Run the read-only TASK-021C cost-normalization and NULL-gap bridge study."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from dps_studio.research.task021c_cost_bridge import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    REPOSITORY_ROOT,
    TASK021B_ARTIFACT,
    run_task021c,
)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--task021b-artifact", type=Path, default=TASK021B_ARTIFACT)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=(
            REPOSITORY_ROOT
            / "artifacts"
            / "task021c_cost_normalization_and_null_bridge"
            / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        ),
    )
    parsed = parser.parse_args(arguments)
    outcome = run_task021c(
        raw_root=parsed.raw_root,
        config_path=parsed.config,
        task021b_artifact=parsed.task021b_artifact,
        output_directory=parsed.output_directory,
    )
    print(f"TASK-021C output: {outcome['output_directory']}")
    print(f"Prepared streams: {outcome['stream_count']}")
    print(f"Raw hashes unchanged: {outcome['raw_hashes_equal']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
