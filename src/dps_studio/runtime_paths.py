"""Resolve read-only application resources in source and frozen runtimes."""

from __future__ import annotations

import sys
from pathlib import Path


def application_resource_root() -> Path:
    """Return the root containing application-level bundled resources."""
    if getattr(sys, "frozen", False):
        frozen_root = getattr(sys, "_MEIPASS", None)
        if not isinstance(frozen_root, str):
            raise RuntimeError("Frozen runtime does not expose a valid _MEIPASS path.")
        return Path(frozen_root).resolve()
    package_root = Path(__file__).resolve().parent
    checkout_root = package_root.parents[1]
    if (checkout_root / "pyproject.toml").is_file() and (checkout_root / "configs").is_dir():
        return checkout_root
    # Non-editable installs receive configs via Hatch's force-include mapping.
    return package_root / "resources"


def application_resource_path(*parts: str) -> Path:
    """Return an application resource below the source or frozen root."""
    return application_resource_root().joinpath(*parts)


def package_resource_path(*parts: str) -> Path:
    """Return a resource stored inside the ``dps_studio`` package."""
    if getattr(sys, "frozen", False):
        return application_resource_path("dps_studio", *parts)
    return Path(__file__).resolve().parent.joinpath(*parts)


__all__ = [
    "application_resource_path",
    "application_resource_root",
    "package_resource_path",
]
