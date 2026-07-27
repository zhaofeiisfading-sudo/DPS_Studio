"""Windows-friendly entry point for one formal dual-profile production run."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from production_outputs import run_production_outputs
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.workflow import WorkflowConfiguration, load_workflow_config


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "configs" / "demo_dual_profile.toml"


def _new_default_output_directory(output_root: Path) -> Path:
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    output_directory = output_root / run_name
    if output_directory.exists():
        raise FileExistsError(f"Generated output directory already exists: {output_directory}")
    return output_directory


def _parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run DPS Studio formal production for Balanced and High time "
            "resolution profiles from one TOML configuration."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Formal TOML configuration path.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=None,
        help=(
            "New directory for this run. If omitted, a timestamped directory "
            "is created under the TOML output.root."
        ),
    )
    return parser.parse_args(arguments)


def run_pipeline(
    output_directory: Path,
    *,
    configuration: WorkflowConfiguration,
) -> list[Path]:
    """Read the configured source and write one non-overwriting production tree."""
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be pathlib.Path.")
    if not isinstance(configuration, WorkflowConfiguration):
        raise TypeError("configuration must be a WorkflowConfiguration.")
    output_root = configuration.output.root.resolve()
    output_directory = output_directory.resolve()
    if output_directory.parent != output_root:
        raise ValueError(
            "Formal output_directory must be a direct run directory under "
            f"{output_root}."
        )
    source_path = configuration.input.path
    if not source_path.is_file():
        raise FileNotFoundError(f"Input file does not exist: {source_path}")
    source_hash_before = _sha256(source_path)
    print("DPS Studio formal dual-profile production run")
    print("Profiles: balanced, high_time_resolution")
    print(f"Configuration: {configuration.config_path}")
    print(f"Input file: {source_path}")
    print(f"Input SHA-256 before: {source_hash_before}")
    print(f"Output directory: {output_directory}")
    print("Existing output files will not be deleted or overwritten.")
    loaded = read_delimited_signals(
        source_path,
        time_column=configuration.input.time_column,
        voltage_columns=configuration.input.voltage_columns,
        delimiter=configuration.input.delimiter,
        has_header=configuration.input.has_header,
        encoding=configuration.input.encoding,
        time_scale=configuration.input.time_scale,
        voltage_scales=configuration.input.voltage_scales,
    )
    try:
        generated_paths = run_production_outputs(
            output_directory,
            loaded.records,
            configuration=configuration,
            source_sha256=source_hash_before,
        )
    finally:
        source_hash_after = _sha256(source_path)
        print(f"Input SHA-256 after:  {source_hash_after}")
        if source_hash_after != source_hash_before:
            raise RuntimeError("Raw source SHA-256 changed during pipeline execution.")
    print(f"[PYTHON SUCCESS] Generated {len(generated_paths)} files.")
    for path in generated_paths:
        print(f"  {path.resolve()}")
    latest_run_path = _update_latest_run(output_directory, output_root=output_root)
    relative_run = output_directory.relative_to(output_root.parent)
    print("Production run completed:")
    print(relative_run.as_posix())
    print("")
    print("Simple velocity exports:")
    for path in sorted((output_directory / "simple_exports").glob("*.csv")):
        print(f"- {path.relative_to(output_directory).as_posix()}")
    print(f"LATEST_RUN: {latest_run_path}")
    return generated_paths


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parse_arguments(arguments)
    try:
        configuration = load_workflow_config(
            parsed.config,
            repository_root=REPOSITORY_ROOT,
        )
        output_directory = (
            parsed.output_directory.resolve()
            if parsed.output_directory is not None
            else _new_default_output_directory(configuration.output.root)
        )
        run_pipeline(output_directory, configuration=configuration)
    except Exception as exc:
        print(
            f"[PYTHON FAILURE] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_latest_run(output_directory: Path, *, output_root: Path) -> Path:
    """Atomically update the latest successful formal production-run pointer."""
    relative_run = output_directory.relative_to(output_root.parent)
    latest_path = output_root.parent / "LATEST_RUN.txt"
    temporary_path = output_root.parent / "LATEST_RUN.txt.tmp"
    try:
        temporary_path.write_text(relative_run.as_posix() + "\n", encoding="utf-8")
        temporary_path.replace(latest_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return latest_path


if __name__ == "__main__":
    raise SystemExit(main())
