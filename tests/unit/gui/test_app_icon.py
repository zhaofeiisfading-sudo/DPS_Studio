from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from dps_studio.gui.app import create_application
from dps_studio.runtime_paths import package_resource_path


@pytest.mark.parametrize("frozen", [False, True])
def test_application_and_window_icons_work_outside_repo(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frozen: bool
) -> None:
    source_icon = package_resource_path("gui", "icons", "pdv_studio.ico")
    with monkeypatch.context() as patch:
        patch.chdir(tmp_path)
        if frozen:
            target = tmp_path / "dps_studio" / "gui" / "icons" / source_icon.name
            target.parent.mkdir(parents=True)
            shutil.copyfile(source_icon, target)
            patch.setattr(sys, "frozen", True, raising=False)
            patch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        application = create_application([], language_code="zh_CN")
        assert application is qapp
        assert not application.windowIcon().isNull()
        assert len(application.windowIcon().availableSizes()) == 9
        window = QWidget()
        try:
            assert not window.windowIcon().isNull()
            pixmap = window.windowIcon().pixmap(32, 32)
            assert not pixmap.isNull()
            assert pixmap.toImage().pixelColor(0, 0).alpha() == 0
            assert pixmap.toImage().pixelColor(16, 16).alpha() == 255
        finally:
            window.close()
    create_application([], language_code="zh_CN")
