"""Resolution-independent line icons for the workstation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


# Each stroke is a connected polyline in a 24-unit coordinate system.
_STROKES: dict[str, tuple[tuple[tuple[int, int], ...], ...]] = {
    "open_data": (((12, 3), (5, 3), (5, 21), (19, 21), (19, 14)),
                  ((12, 6), (12, 12), (18, 12)), ((21, 3), (12, 12))),
    "quick_analysis": (((4, 4), (13, 10), (4, 16), (4, 4)),
                       ((9, 20), (12, 17), (15, 19), (20, 11))),
    "full_automatic": (((13, 2), (5, 14), (11, 14), (10, 22), (19, 9), (13, 9), (13, 2)),),
    "export": (((4, 14), (4, 20), (20, 20), (20, 14)),
               ((12, 15), (12, 3)), ((7, 8), (12, 3), (17, 8))),
    "diagnostics": (((3, 4), (21, 4), (21, 20), (3, 20), (3, 4)),
                    ((5, 13), (8, 13), (10, 8), (13, 16), (16, 11), (19, 11))),
    "folder_open": (((3, 19), (3, 5), (9, 5), (11, 8), (19, 8), (19, 11)),
                    ((3, 19), (7, 11), (22, 11), (18, 19), (3, 19))),
    "reset": (((3, 4), (3, 10), (9, 10)),),
    "fit_view": (((3, 9), (3, 3), (9, 3)), ((15, 3), (21, 3), (21, 9)),
                 ((21, 15), (21, 21), (15, 21)), ((9, 21), (3, 21), (3, 15))),
    "fit_time": (((3, 6), (3, 18)), ((21, 6), (21, 18)), ((4, 12), (20, 12)),
                 ((8, 8), (4, 12), (8, 16)), ((16, 8), (20, 12), (16, 16))),
    "fit_amplitude": (((6, 3), (18, 3)), ((6, 21), (18, 21)), ((12, 4), (12, 20)),
                      ((8, 8), (12, 4), (16, 8)), ((8, 16), (12, 20), (16, 16))),
    "search_region": (((4, 6), (20, 6), (20, 18), (4, 18), (4, 6)),
                      ((7, 13), (10, 13), (13, 10), (17, 10))),
    "parameters": (((3, 7), (21, 7)), ((8, 4), (8, 10)),
                   ((3, 17), (21, 17)), ((16, 14), (16, 20))),
    "chevron_right": (((9, 5), (16, 12), (9, 19)),),
    "chevron_down": (((5, 9), (12, 16), (19, 9)),),
    "waveform": (((2, 13), (6, 13), (9, 4), (13, 20), (16, 9), (18, 13), (22, 13)),),
    "check": (((4, 12), (10, 18), (20, 6)),),
}


def vector_icon(name: str, color: str = "#1e293b") -> QIcon:
    """Rasterize each requested logical size directly at 1x and 2x density."""
    path = QPainterPath()
    for first, *rest in _STROKES[name]:
        path.moveTo(*first)
        for point in rest:
            path.lineTo(*point)
    if name == "reset":
        path.arcMoveTo(4, 4, 16, 16, 160)
        path.arcTo(4, 4, 16, 16, 160, -300)
    icon = QIcon()
    pen = QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    for size in (16, 20, 24, 32):
        for density in (1, 2):
            pixmap = QPixmap(size * density, size * density)
            pixmap.setDevicePixelRatio(density)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(size / 24, size / 24)
            painter.setPen(pen)
            painter.drawPath(path)
            painter.end()
            icon.addPixmap(pixmap)
    return icon


def chevron_icon(expanded: bool) -> QIcon:
    return vector_icon("chevron_down" if expanded else "chevron_right")
