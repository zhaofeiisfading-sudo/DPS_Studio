"""Runtime write guard for the Research/Test application."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def protected_path(path: Path) -> bool:
    resolved = path.resolve()
    # Protect Production by directory identity even after moving the portable app.
    # No Production module is imported or needed to run the program.
    return any(parent.name.casefold() == "dps_studio" or (
        parent.name.casefold() == "raw" and parent.parent.name.casefold() == "data")
        for parent in (resolved, *resolved.parents))


def write_guard(event: str, args: tuple[Any, ...]) -> None:
    targets: tuple[Any, ...] = ()
    if event == "open" and len(args) >= 3:
        mode, flags = args[1:3]
        writing = (isinstance(mode, str) and any(token in mode for token in "wax+")) or (
            isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
        if writing:
            targets = args[:1]
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
        targets = args[:1]
    elif event in {"os.rename", "os.link", "os.symlink"}:
        targets = args[:2]
    for target in targets:
        if isinstance(target, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(target))
            if protected_path(path):
                raise PermissionError(f"Research/Test write denied for protected path: {path}")


def install_write_guard() -> None:
    sys.addaudithook(write_guard)
