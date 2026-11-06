"""Darwin loaded-image evidence, distinct from the preserved kernel32 probe."""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Any


def loaded_images() -> list[str]:
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    library._dyld_image_count.argtypes = []
    library._dyld_image_count.restype = ctypes.c_uint32
    library._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    library._dyld_get_image_name.restype = ctypes.c_char_p
    images = []
    for index in range(library._dyld_image_count()):
        name = library._dyld_get_image_name(index)
        if name:
            images.append(str(Path(name.decode("utf-8")).resolve()))
    return sorted(set(images))


def match_loaded_image(module_path: str, images: list[str]) -> str:
    resolved = str(Path(module_path).resolve())
    if resolved not in images:
        raise RuntimeError(f"Required native image is not loaded: {module_path}")
    return resolved


def loaded_runtime_paths() -> dict[str, str]:
    import PySide6
    import scipy  # type: ignore[import-untyped]
    import shiboken6
    from PySide6 import QtCore
    from scipy._lib import _ccallback_c  # type: ignore[import-untyped]
    from shiboken6 import Shiboken

    images = loaded_images()
    cocoa = [image for image in images if Path(image).name == "libqcocoa.dylib"]
    qt_core = [image for image in images if Path(image).name in {"QtCore", "libQt6Core.6.dylib"}]
    if len(cocoa) != 1 or len(qt_core) != 1:
        raise RuntimeError(f"Required Cocoa/QtCore loaded images missing or ambiguous: {cocoa}, {qt_core}")
    return {
        "PySide6": str(PySide6.__file__), "shiboken6": str(shiboken6.__file__),
        "SciPy": str(scipy.__file__),
        "QtCore_extension_image": match_loaded_image(str(QtCore.__file__), images),
        "QtCore_framework_image": qt_core[0], "Cocoa_plugin_image": cocoa[0],
        "shiboken_extension_image": match_loaded_image(str(Shiboken.__file__), images),
        "SciPy_native_image": match_loaded_image(str(_ccallback_c.__file__), images),
    }


def finish_report(report_path: Path, exit_code: int) -> None:
    """Only record normal exit after QApplication.exec has actually returned."""
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    report.update({"normal_exit": exit_code == 0, "exit_code": exit_code,
                   "architecture": platform.machine()})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                           encoding="utf-8")
