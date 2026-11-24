from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from dps_studio.gui.app import create_application  # noqa: E402
from dps_studio.runtime_paths import USERDATA_ENV_VAR, initialize_runtime_storage  # noqa: E402


@pytest.fixture(scope="session")
def qapp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[QApplication]:
    settings_path = str(tmp_path_factory.mktemp("qt_settings"))
    os.environ[USERDATA_ENV_VAR] = settings_path
    initialize_runtime_storage(Path(settings_path), redirect_process_temp=False)
    application = create_application([], language_code="zh_CN")
    yield application
    application.closeAllWindows()
    application.processEvents()


@pytest.fixture(autouse=True)
def dispose_test_main_windows(qapp: QApplication) -> Iterator[None]:
    """Close hides a QWidget; explicitly release each test's native window tree.

    Keeping a session QApplication otherwise accumulates closed main windows,
    menus and graphics scenes across tests, until native resource allocation or
    late Python collection fails inside unrelated Qt/pyqtgraph constructors.
    """
    yield
    for widget in qapp.topLevelWidgets():
        if isinstance(widget, QMainWindow):
            widget.close()
            widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert not any(isinstance(widget, QMainWindow) for widget in qapp.topLevelWidgets())
