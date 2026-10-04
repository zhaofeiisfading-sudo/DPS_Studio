# -*- mode: python ; coding: utf-8 -*-
"""Independent arm64 bundle. Windows spec and native hooks remain untouched."""

import os
import runpy
from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
GUI_ROOT = SOURCE_ROOT / "dps_studio" / "gui"
RELEASE_VERSION = runpy.run_path(str(SOURCE_ROOT / "dps_studio" / "__init__.py"))["__version__"]
APP_ICON = Path(os.environ.get("DPS_MACOS_ICON", str(GUI_ROOT / "icons" / "pdv_studio.icns")))
if not APP_ICON.is_file():
    raise FileNotFoundError("Generate ICNS with tools/build_macos_icon.py on macOS first")

analysis = Analysis(
    [str(GUI_ROOT / "__main__.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "configs" / "pdv_studio_defaults.toml"), "configs"),
        (str(GUI_ROOT / "translations" / "pdv_studio_en.qm"), "dps_studio/gui/translations"),
        (str(GUI_ROOT / "icons" / "pdv_studio.ico"), "dps_studio/gui/icons"),
        (str(APP_ICON), "dps_studio/gui/icons"),
    ],
    hiddenimports=["dps_studio.gui.release_smoke_macos", "scipy._lib._ccallback_c"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["matplotlib", "mypy", "pytest", "ruff", "tkinter"],
    noarchive=False, optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="PDV Studio", icon=str(APP_ICON),
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch="arm64", codesign_identity=None, entitlements_file=None,
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas,
    strip=False, upx=False, upx_exclude=[], name="PDV Studio",
)
app = BUNDLE(
    collection, name="PDV Studio.app", icon=str(APP_ICON),
    bundle_identifier="com.dpsstudio.pdvstudio", version=RELEASE_VERSION,
    info_plist={
        "CFBundleShortVersionString": RELEASE_VERSION,
        "CFBundleVersion": RELEASE_VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "15.0",
    },
)
