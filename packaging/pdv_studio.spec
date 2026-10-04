# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import runpy

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)


PROJECT_ROOT = Path(SPECPATH).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
APP_ICON = SOURCE_ROOT / "dps_studio" / "gui" / "icons" / "pdv_studio.ico"
RELEASE_VERSION = runpy.run_path(str(SOURCE_ROOT / "dps_studio" / "__init__.py"))["__version__"]
VERSION_TUPLE = tuple(int(value) for value in RELEASE_VERSION.split(".")) + (0,)
VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE,
                      mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "PDV Studio"),
            StringStruct("FileVersion", RELEASE_VERSION),
            StringStruct("ProductName", "PDV Studio"),
            StringStruct("ProductVersion", RELEASE_VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

datas = [
    (str(APP_ICON), "dps_studio/gui/icons"),
    (
        str(PROJECT_ROOT / "configs" / "pdv_studio_defaults.toml"),
        "configs",
    ),
    (
        str(
            SOURCE_ROOT
            / "dps_studio"
            / "gui"
            / "translations"
            / "pdv_studio_en.qm"
        ),
        "dps_studio/gui/translations",
    ),
]

analysis = Analysis(
    [str(SOURCE_ROOT / "dps_studio" / "gui" / "__main__.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "mypy", "pytest", "ruff", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PDV Studio",
    version=VERSION_INFO,
    icon=str(APP_ICON),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=f"PDV_Studio_v{RELEASE_VERSION}",
)
