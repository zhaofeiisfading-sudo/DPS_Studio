# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[2]
SOURCE = ROOT / "src"
ICON = SOURCE / "dps_studio/gui/icons/pdv_studio.ico"
analysis = Analysis(
    [str(SOURCE / "dps_studio/gui/__main__.py")], pathex=[str(SOURCE)], binaries=[],
    datas=[(str(ICON), "dps_studio/gui/icons"),
           (str(SOURCE / "dps_studio/gui/icons/chevron_down.svg"), "dps_studio/gui/icons"),
           (str(ROOT / "configs/pdv_studio_defaults.toml"), "configs"),
           (str(SOURCE / "dps_studio/gui/translations/pdv_studio_en.qm"), "dps_studio/gui/translations")],
    hiddenimports=collect_submodules("dps_studio.algorithms"),
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["matplotlib", "mypy", "pytest", "ruff", "tkinter", "dps_studio.research"],
    noarchive=False, optimize=0,
)
analysis.binaries = [e for e in analysis.binaries
                     if Path(e[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name="PDV Studio Research TASK015", icon=str(ICON), debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False,
                     name="PDV_Studio_Research_TASK015")
