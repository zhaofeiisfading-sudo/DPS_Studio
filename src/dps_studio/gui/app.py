"""QApplication lifecycle and the public desktop entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import cast

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dps_studio.gui.i18n import TranslationManager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.styles import apply_application_style
from dps_studio.runtime_paths import package_resource_path


_translation_manager: TranslationManager | None = None


def create_application(
    arguments: Sequence[str] | None = None,
    *,
    language_code: str | None = None,
) -> QApplication:
    """Create or reuse the process QApplication and install translations."""
    global _translation_manager
    existing = QApplication.instance()
    if existing is None:
        application = QApplication(
            list(arguments) if arguments is not None else list(sys.argv)
        )
    else:
        application = cast("QApplication", existing)
    application.setOrganizationName("DPS Studio")
    application.setApplicationName("PDV Studio")
    application.setApplicationDisplayName("PDV Studio")
    application.setWindowIcon(
        QIcon(str(package_resource_path("gui", "icons", "pdv_studio.ico")))
    )
    apply_application_style(application)
    _translation_manager = TranslationManager(application)
    _translation_manager.install(language_code)
    return application


def translation_manager() -> TranslationManager:
    """Return the initialized process translation manager."""
    if _translation_manager is None:
        raise RuntimeError("create_application() must be called first.")
    return _translation_manager


def main(arguments: Sequence[str] | None = None) -> int:
    """Launch the resizable PDV Studio desktop shell."""
    application = create_application(arguments)
    window = MainWindow(translation_manager=translation_manager())
    window.show()
    return application.exec()


__all__ = ["create_application", "main", "translation_manager"]
