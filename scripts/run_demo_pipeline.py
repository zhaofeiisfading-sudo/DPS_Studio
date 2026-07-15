"""Windows-friendly entry point for the current development demo."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from assess_real_ridge_diagnostics import run_ridge_diagnostics_demo
from assess_real_ridge_quality import run_spectral_quality_demo
from compare_real_ridge_refinement import run_demo


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "task008b_demo_runs"


def _new_default_output_directory() -> Path:
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    return DEFAULT_OUTPUT_ROOT / run_name


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the DPS Studio development preview.",
    )
    parser.add_argument(
        "--window-diagnostics",
        action="store_true",
        help=(
            "Also run the 512/768/1024 fixed-hop window audit. "
            "The default BAT intentionally leaves this disabled."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run the current demo without deleting any existing output."""
    arguments = _parse_arguments()
    configured_output = os.environ.get("DPS_DEMO_OUTPUT_DIR")
    output_directory = (
        Path(configured_output)
        if configured_output is not None
        else _new_default_output_directory()
    )
    print("DPS Studio development demo: TASK-007 + TASK-008A + TASK-008B")
    print(f"Input file: {REPOSITORY_ROOT / 'data' / 'raw' / '20260607.csv'}")
    print(f"Output directory: {output_directory}")
    print("Existing output files will not be deleted automatically.")
    print(f"Window diagnostics enabled: {arguments.window_diagnostics}")
    try:
        task007_paths = run_demo(
            output_directory,
            run_window_diagnostics=arguments.window_diagnostics,
        )
        task008a_paths = run_spectral_quality_demo(output_directory)
        task008b_paths = run_ridge_diagnostics_demo(output_directory)
        generated_paths = [*task007_paths, *task008a_paths, *task008b_paths]
    except Exception as exc:
        print(
            f"[PYTHON FAILURE] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
    print(f"[PYTHON SUCCESS] Generated {len(generated_paths)} files.")
    print(f"Completed output directory: {output_directory}")


if __name__ == "__main__":
    main()
