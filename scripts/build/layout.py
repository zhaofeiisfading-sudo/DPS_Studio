"""Separate build intermediates and published archives for manual release tools."""

from pathlib import Path


def release_paths(project: Path, output: Path, release: Path) -> tuple[Path, Path]:
    """Resolve paths before building, rejecting outputs outside their assigned roots."""
    project = project.resolve()
    output, release = output.resolve(), release.resolve()
    if output == project / "build" or not output.is_relative_to(project / "build"):
        raise ValueError("--output-root must be a new task directory under build/.")
    if not release.is_relative_to(project / "release"):
        raise ValueError("--release-root must be release/ or a directory inside it.")
    return output, release
