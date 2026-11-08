"""Run pytest with local data relocation and isolated Qt settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"


def main() -> None:
    from PySide6.QtCore import QSettings

    settings = ROOT / "artifacts/TASK-011/checks/qt_settings"
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(settings))
    from dps_studio.research.task009_data import install

    install()
    import pytest

    raise SystemExit(pytest.main(sys.argv[1:]))


if __name__ == "__main__":
    main()
