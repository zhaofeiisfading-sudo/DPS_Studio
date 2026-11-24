# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
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
CLI_VERSION_INFO = VSVersionInfo(
    ffi=VERSION_INFO.ffi,
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "PDV Studio CLI"),
            StringStruct("FileVersion", RELEASE_VERSION),
            StringStruct("OriginalFilename", "pdv.exe"),
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
    (str(PROJECT_ROOT / ".agents" / "skills" / "pdv-studio" / "SKILL.md"), "skills/pdv-studio"),
]

excludes = ["matplotlib", "mypy", "pytest", "ruff", "tkinter"]
analysis = Analysis(
    [str(SOURCE_ROOT / "dps_studio" / "gui" / "__main__.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["dps_studio.cli", "dps_studio.cli_config", "dps_studio.cli_plots"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
onefile = os.environ.get("DPS_STUDIO_ONEFILE") == "1"

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries if onefile else [],
    analysis.datas if onefile else [],
    exclude_binaries=not onefile,
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
if not onefile:
    cli_analysis = Analysis(
        [str(SOURCE_ROOT / "dps_studio" / "__main__.py")],
        pathex=[str(SOURCE_ROOT)],
        datas=datas,
        excludes=excludes,
        noarchive=False,
        optimize=0,
    )
    cli_executable = EXE(
        PYZ(cli_analysis.pure),
        cli_analysis.scripts,
        exclude_binaries=True,
        name="pdv",
        version=CLI_VERSION_INFO,
        icon=str(APP_ICON),
        debug=False,
        strip=False,
        upx=False,
        console=True,
    )
    collection = COLLECT(
        executable,
        cli_executable,
        analysis.binaries,
        cli_analysis.binaries,
        analysis.datas,
        cli_analysis.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=f"PDV_Studio_v{RELEASE_VERSION}",
    )
