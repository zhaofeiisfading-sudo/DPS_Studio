"""Resolve application resources and writable storage in source and frozen runtimes."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


USERDATA_ENV_VAR = "PDV_STUDIO_USERDATA_DIR"


class RuntimeStorageError(RuntimeError):
    """Application storage could not be initialized at the selected location."""


@dataclass(frozen=True, slots=True)
class UserdataPaths:
    """Locations for persistent settings and process-local runtime files."""

    root: Path
    config_dir: Path
    materials_dir: Path
    presets_dir: Path
    cache_dir: Path
    logs_dir: Path
    temp_dir: Path
    settings_file: Path
    window_presets_file: Path


def application_resource_root() -> Path:
    """Return the root containing application-level bundled resources."""
    if getattr(sys, "frozen", False):
        frozen_root = getattr(sys, "_MEIPASS", None)
        if not isinstance(frozen_root, str):
            raise RuntimeError("Frozen runtime does not expose a valid _MEIPASS path.")
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[2]


def application_resource_path(*parts: str) -> Path:
    """Return an application resource below the source or frozen root."""
    return application_resource_root().joinpath(*parts)


def package_resource_path(*parts: str) -> Path:
    """Return a resource stored inside the ``dps_studio`` package."""
    if getattr(sys, "frozen", False):
        return application_resource_path("dps_studio", *parts)
    return Path(__file__).resolve().parent.joinpath(*parts)


def installation_root() -> Path:
    """Return the checkout root or the directory containing the frozen executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def userdata_root(explicit_root: Path | None = None) -> Path:
    """Return the explicit root, environment override, or installation default."""
    if explicit_root is not None:
        return Path(explicit_root).expanduser().resolve()
    if os.environ.get(USERDATA_ENV_VAR, "").strip():
        return Path(os.environ[USERDATA_ENV_VAR]).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return installation_root() / "userdata"
    return installation_root() / "artifacts" / "userdata"


def userdata_paths(explicit_root: Path | None = None) -> UserdataPaths:
    """Describe the storage layout without creating directories."""
    root = userdata_root(explicit_root)
    config_dir = root / "config"
    materials_dir = root / "materials"
    return UserdataPaths(
        root=root,
        config_dir=config_dir,
        materials_dir=materials_dir,
        presets_dir=root / "presets",
        cache_dir=root / "cache",
        logs_dir=root / "logs",
        temp_dir=root / "temp",
        settings_file=config_dir / "settings.ini",
        window_presets_file=materials_dir / "window_presets.json",
    )


def userdata_path(*parts: str, explicit_root: Path | None = None) -> Path:
    return userdata_root(explicit_root).joinpath(*parts)


def user_settings_path(explicit_root: Path | None = None) -> Path:
    return userdata_paths(explicit_root).settings_file


def window_preset_file_path(explicit_root: Path | None = None) -> Path:
    return userdata_paths(explicit_root).window_presets_file


def _storage_error(path: Path) -> RuntimeStorageError:
    return RuntimeStorageError(
        f"PDV Studio userdata path is not writable: {path}. "
        "PDV Studio does not silently fall back to AppData."
    )


def ensure_userdata_directories(explicit_root: Path | None = None) -> UserdataPaths:
    """Create the storage layout and verify write access to the root and config."""
    paths = userdata_paths(explicit_root)
    try:
        for directory in (
            paths.root, paths.config_dir, paths.materials_dir, paths.presets_dir,
            paths.cache_dir, paths.logs_dir, paths.temp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        for directory in (paths.root, paths.config_dir):
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".write-probe-") as probe:
                probe.write(b"PDV Studio")
                probe.flush()
    except OSError as exc:
        raise _storage_error(directory) from exc
    return paths


def initialize_runtime_storage(
    explicit_root: Path | None = None,
    *,
    redirect_process_temp: bool = True,
) -> UserdataPaths:
    """Initialize writable storage and configure this process to use it."""
    paths = ensure_userdata_directories(explicit_root)
    matplotlib_dir = paths.cache_dir / "matplotlib"
    try:
        matplotlib_dir.mkdir(exist_ok=True)
    except OSError as exc:
        raise _storage_error(matplotlib_dir) from exc
    os.environ["MPLCONFIGDIR"] = str(matplotlib_dir)
    os.environ["QT_SETTINGS_PATH"] = str(paths.config_dir)
    if redirect_process_temp:
        os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = str(paths.temp_dir)
        tempfile.tempdir = str(paths.temp_dir)
    return paths


__all__ = [
    "USERDATA_ENV_VAR",
    "RuntimeStorageError",
    "UserdataPaths",
    "application_resource_path",
    "application_resource_root",
    "ensure_userdata_directories",
    "initialize_runtime_storage",
    "installation_root",
    "package_resource_path",
    "user_settings_path",
    "userdata_path",
    "userdata_paths",
    "userdata_root",
    "window_preset_file_path",
]
