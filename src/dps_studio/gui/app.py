"""QApplication lifecycle and the public desktop entry point."""

from __future__ import annotations

import sys
import json
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dps_studio import __version__
from dps_studio.gui.i18n import TranslationManager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.release_smoke import loaded_runtime_paths, run_analysis_smoke, smoke_options
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
    application.setApplicationVersion(__version__)
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
    args = list(arguments) if arguments is not None else sys.argv
    report_path, analysis_input = smoke_options(args)
    application = create_application(arguments)
    window = MainWindow(translation_manager=translation_manager())
    window.show()
    if report_path is not None:
        def report_startup() -> None:
            exit_code = 0
            try:
                analysis_report = (
                    run_analysis_smoke(analysis_input, report_path.parent / "analysis_export")
                    if analysis_input is not None else None
                )
                handle = window.windowHandle()
                report = {
                    "version": __version__, "gui_version": application.applicationVersion(),
                    "event_loop_entered": True, "window_visible": window.isVisible(),
                    "window_exposed": handle is not None and handle.isExposed(),
                    "qt_platform": application.platformName(),
                    "runtime_paths": loaded_runtime_paths(), "analysis_smoke": analysis_report,
                }
            except Exception as exc:
                report = {"error": f"{type(exc).__name__}: {exc}"}
                exit_code = 1
            with report_path.open("x", encoding="utf-8") as report_handle:
                json.dump(report, report_handle, indent=2)
            window.close()
            application.exit(exit_code)

        QTimer.singleShot(500, report_startup)
    return application.exec()


__all__ = ["create_application", "main", "translation_manager"]
