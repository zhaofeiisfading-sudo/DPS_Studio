from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from dps_studio.gui.app import create_application  # noqa: E402


@pytest.fixture(scope="session")
def qapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[QApplication]:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp("qt_settings")))
    application = create_application([], language_code="zh_CN")
    yield application
    application.closeAllWindows()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


@pytest.fixture(autouse=True)
def dispose_test_main_windows(qapp: QApplication) -> Iterator[None]:
    """Release native graphics resources between integration tests."""
    yield
    for widget in qapp.topLevelWidgets():
        if isinstance(widget, QMainWindow):
            widget.close()
            widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
