"""Native desktop icons with safe Qt fallbacks."""

from __future__ import annotations

from PySide6.QtCore import QDir, QFileInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFileIconProvider, QStyle


def native_directory_icon() -> QIcon:
    """Return the platform directory icon, falling back to the Qt style icon."""
    try:
        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(QDir.homePath()))
        if not icon.isNull():
            return icon
    except (OSError, RuntimeError, TypeError):
        pass
    style = QApplication.style()
    return style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)


__all__ = ["native_directory_icon"]
