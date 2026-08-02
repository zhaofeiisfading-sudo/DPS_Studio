"""Small persistent preferences that affect presentation only."""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QSettings


DEFAULT_SPECTROGRAM_COLORMAP = "viridis"
SPECTROGRAM_COLORMAPS = ("viridis", "cividis", "grayscale")
SPECTROGRAM_COLORMAP_SETTINGS_KEY = "display/spectrogram_colormap"


def normalize_spectrogram_colormap(value: object) -> str:
    """Return a supported stable colormap id, falling back safely."""
    normalized = str(value).strip().lower()
    if normalized in SPECTROGRAM_COLORMAPS:
        return normalized
    return DEFAULT_SPECTROGRAM_COLORMAP


def spectrogram_colormap(name: str) -> Any:
    """Build the PyQtGraph colormap represented by a stable display id."""
    normalized = normalize_spectrogram_colormap(name)
    if normalized == "grayscale":
        return pg.ColorMap(
            [0.0, 1.0],
            [[0, 0, 0, 255], [255, 255, 255, 255]],
        )
    return pg.colormap.get(normalized)


class DisplayPreferences:
    """Read and write display-only settings without owning scientific state."""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def spectrogram_colormap(self) -> str:
        """Return the last valid selection or the perceptual default."""
        value = self._settings.value(
            SPECTROGRAM_COLORMAP_SETTINGS_KEY,
            DEFAULT_SPECTROGRAM_COLORMAP,
        )
        return normalize_spectrogram_colormap(value)

    def set_spectrogram_colormap(self, name: str) -> str:
        """Persist a normalized presentation choice."""
        normalized = normalize_spectrogram_colormap(name)
        self._settings.setValue(SPECTROGRAM_COLORMAP_SETTINGS_KEY, normalized)
        self._settings.sync()
        return normalized


__all__ = [
    "DEFAULT_SPECTROGRAM_COLORMAP",
    "DisplayPreferences",
    "SPECTROGRAM_COLORMAPS",
    "SPECTROGRAM_COLORMAP_SETTINGS_KEY",
    "normalize_spectrogram_colormap",
    "spectrogram_colormap",
]
