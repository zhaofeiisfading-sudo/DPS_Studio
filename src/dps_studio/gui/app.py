"""QApplication lifecycle and the public desktop entry point."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio import __version__
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.i18n import TranslationManager
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.release_smoke import loaded_runtime_paths, run_analysis_smoke, smoke_options
from dps_studio.gui.styles import apply_application_style
from dps_studio.runtime_paths import (
    USERDATA_ENV_VAR,
    RuntimeStorageError,
    UserdataPaths,
    initialize_runtime_storage,
    package_resource_path,
    userdata_paths,
)


_translation_manager: TranslationManager | None = None


def create_application(
    arguments: Sequence[str] | None = None,
    *,
    language_code: str | None = None,
    storage_paths: UserdataPaths | None = None,
) -> QApplication:
    """Create or reuse the process QApplication and install translations."""
    global _translation_manager
    paths = storage_paths if storage_paths is not None else userdata_paths()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(paths.config_dir))
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
    _translation_manager = TranslationManager(
        application, settings=QSettings(str(paths.settings_file), QSettings.Format.IniFormat)
    )
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
    if "--workflow-smoke-test" in args:
        from dps_studio.gui.release_workflow_smoke import run_workflow_smoke

        return run_workflow_smoke(args)
    report_path, analysis_input = smoke_options(args)
    storage_paths = None
    if report_path is None:
        try:
            storage_paths = initialize_runtime_storage(
                redirect_process_temp=bool(getattr(sys, "frozen", False))
            )
        except RuntimeStorageError as exc:
            print(exc, file=sys.stderr)
            if "--no-error-dialog" not in args and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                error_application = cast("QApplication | None", QApplication.instance())
                if error_application is None:
                    error_application = QApplication(args[:1])
                QMessageBox.critical(error_application.activeWindow(), "PDV Studio", str(exc))
            return 2
    elif USERDATA_ENV_VAR not in os.environ:
        storage_paths = initialize_runtime_storage(
            report_path.parent / "userdata", redirect_process_temp=False
        )
    application = create_application(arguments, storage_paths=storage_paths)
    window = MainWindow(
        translation_manager=translation_manager(),
        settings=(QSettings(str(report_path.parent / "layout.ini"), QSettings.Format.IniFormat)
                  if report_path is not None else None),
        window_preset_repository=(WindowPresetRepository(report_path.parent / "window_presets.json")
                                  if report_path is not None else None),
    )
    window.show()
    if report_path is not None:
        def report_startup() -> None:
            exit_code = 0
            try:
                analysis_report = (
                    run_analysis_smoke(analysis_input, report_path.parent / "analysis_export")
                    if analysis_input is not None else None
                )
                if sys.platform == "darwin" and analysis_input is not None:
                    from dps_studio.release.portable_reference import capture_snapshot

                    assert analysis_report is not None
                    analysis_report["numerical_snapshot"] = capture_snapshot(
                        analysis_input, report_path.parent / "numerical_exports",
                    )
                handle = window.windowHandle()
                report = {
                    "version": __version__, "gui_version": application.applicationVersion(),
                    "event_loop_entered": True, "window_visible": window.isVisible(),
                    "window_exposed": handle is not None and handle.isExposed(),
                    "qt_platform": application.platformName(),
                    "runtime_paths": loaded_runtime_paths(), "analysis_smoke": analysis_report,
                }
                if sys.platform == "darwin":
                    report["application_created"] = True
                    report["main_window_created"] = True
            except Exception as exc:
                report = {"error": f"{type(exc).__name__}: {exc}"}
                if sys.platform == "darwin":
                    handle = window.windowHandle()
                    report.update({
                        "application_created": True, "main_window_created": True,
                        "event_loop_entered": True, "window_visible": window.isVisible(),
                        "window_exposed": handle is not None and handle.isExposed(),
                        "qt_platform": application.platformName(), "version": __version__,
                        "gui_version": application.applicationVersion(),
                    })
                exit_code = 1
            with report_path.open("x", encoding="utf-8") as report_handle:
                json.dump(report, report_handle, indent=2)
            window.close()
            application.exit(exit_code)

        QTimer.singleShot(500, report_startup)
    exit_code = application.exec()
    if sys.platform == "darwin" and report_path is not None and report_path.exists():
        from dps_studio.gui.release_smoke_macos import finish_report

        finish_report(report_path, exit_code)
    return exit_code


__all__ = ["create_application", "main", "translation_manager"]
