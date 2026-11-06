from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from dps_studio.gui.app import create_application  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    application = create_application([], language_code="zh_CN")
    yield application
    application.closeAllWindows()
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
