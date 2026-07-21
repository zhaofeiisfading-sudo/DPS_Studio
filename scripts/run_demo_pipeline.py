"""Windows-friendly entry point for explicit profile and output-mode runs."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from assess_real_ridge_diagnostics import run_ridge_diagnostics_demo
from assess_real_ridge_quality import run_spectral_quality_demo
from compare_real_ridge_refinement import (
    ANALYSIS_END_TIME_S,
    DATA_PATH,
    DEMO_VACUUM_WAVELENGTH_M,
    RIDGE_START_TIME_S,
    _sha256,
    run_demo,
)
from production_outputs import run_production_outputs
from dps_studio.core import (
    DEFAULT_ANALYSIS_PROFILE,
    DEFAULT_OUTPUT_MODE,
    AnalysisProfile,
    AnalysisProfileId,
    OutputMode,
    get_analysis_profile,
)
from dps_studio.core.io import read_delimited_signals


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "task011b_runs"


def _new_default_output_directory() -> Path:
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    output_directory = DEFAULT_OUTPUT_ROOT / run_name
    if output_directory.exists():
        raise FileExistsError(f"Generated output directory already exists: {output_directory}")
    return output_directory


def _parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run DPS Studio with an explicit analysis profile and output mode. "
            "Balanced production is the default."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in AnalysisProfileId),
        default=DEFAULT_ANALYSIS_PROFILE.profile_id.value,
        help=(
            "Analysis profile. High time resolution shortens time support but is "
            "not a higher-accuracy claim."
        ),
    )
    parser.add_argument(
        "--output-mode",
        choices=tuple(mode.value for mode in OutputMode),
        default=DEFAULT_OUTPUT_MODE.value,
        help="Production writes eight practical files; diagnostic writes TASK-007/008 outputs.",
    )
    return parser.parse_args(arguments)


def _run_production(
    output_directory: Path,
    profile: AnalysisProfile,
    *,
    source_sha256: str,
) -> list[Path]:
    loaded = read_delimited_signals(
        DATA_PATH,
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
    )
    return run_production_outputs(
        output_directory,
        loaded.records,
        profile=profile,
        vacuum_wavelength_m=DEMO_VACUUM_WAVELENGTH_M,
        event_start_time_s=RIDGE_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        source_path=DATA_PATH,
        source_sha256=source_sha256,
    )


def _run_diagnostic(
    output_directory: Path,
    profile: AnalysisProfile,
) -> list[Path]:
    if output_directory.exists():
        if any(output_directory.iterdir()):
            raise FileExistsError(
                f"Diagnostic output directory is not empty: {output_directory}"
            )
    else:
        output_directory.mkdir(parents=True)
    task007_paths = run_demo(
        output_directory,
        run_window_diagnostics=False,
        profile=profile,
    )
    task008a_paths = run_spectral_quality_demo(output_directory, profile=profile)
    task008b_paths = run_ridge_diagnostics_demo(output_directory, profile=profile)
    return [*task007_paths, *task008a_paths, *task008b_paths]


def run_pipeline(
    output_directory: Path,
    *,
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
    output_mode: OutputMode = DEFAULT_OUTPUT_MODE,
) -> list[Path]:
    """Run one explicit daily mode without deleting or overwriting outputs."""
    if not isinstance(profile, AnalysisProfile):
        raise TypeError("profile must be an AnalysisProfile.")
    if not isinstance(output_mode, OutputMode):
        raise TypeError("output_mode must be an OutputMode.")
    if not DATA_PATH.is_file():
        raise FileNotFoundError(f"Input file does not exist: {DATA_PATH}")
    source_hash_before = _sha256(DATA_PATH)
    print("DPS Studio explicit analysis run")
    print(f"Profile: {profile.profile_id.value} ({profile.display_name})")
    print(f"Profile tradeoff: {profile.tradeoff_note}")
    print(f"Output mode: {output_mode.value}")
    print(f"Input file: {DATA_PATH}")
    print(f"Input SHA-256 before: {source_hash_before}")
    print(f"Output directory: {output_directory}")
    print("Existing output files will not be deleted or overwritten.")
    try:
        if output_mode is OutputMode.PRODUCTION:
            print("[STAGE] Generating the explicit eight-file production set...")
            generated_paths = _run_production(
                output_directory,
                profile,
                source_sha256=source_hash_before,
            )
        else:
            print("[STAGE] Generating TASK-007/008 diagnostic outputs...")
            generated_paths = _run_diagnostic(output_directory, profile)
    finally:
        source_hash_after = _sha256(DATA_PATH)
        print(f"Input SHA-256 after:  {source_hash_after}")
        if source_hash_after != source_hash_before:
            raise RuntimeError("Raw source SHA-256 changed during pipeline execution.")
    print(f"[PYTHON SUCCESS] Generated {len(generated_paths)} files.")
    for path in generated_paths:
        print(f"  {path.resolve()}")
    print(f"Completed output directory: {output_directory}")
    return generated_paths


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parse_arguments(arguments)
    profile = get_analysis_profile(parsed.profile)
    output_mode = OutputMode(parsed.output_mode)
    configured_output = os.environ.get("DPS_DEMO_OUTPUT_DIR")
    output_directory = (
        Path(configured_output)
        if configured_output is not None
        else _new_default_output_directory()
    )
    try:
        run_pipeline(
            output_directory,
            profile=profile,
            output_mode=output_mode,
        )
    except Exception as exc:
        print(
            f"[PYTHON FAILURE] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
