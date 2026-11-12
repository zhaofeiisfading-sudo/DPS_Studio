"""Shared display components for the desktop work area."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QListWidget, QSizePolicy, QWidget, QLabel


class WorkflowNavigation(QListWidget):
    """A single keyboard-accessible row of workflow steps."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowNavigation")
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual API
        return QSize(420, max(34, self.fontMetrics().height() + 15))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual API
        return self.sizeHint()


class ElidedLabel(QLabel):
    """Keep long filenames from increasing the desktop window's minimum width."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt virtual API
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        bounds = self.contentsRect().adjusted(5, 0, -5, 0)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle,
                                             bounds.width())
        painter.drawText(bounds, Qt.AlignmentFlag.AlignVCenter, text)
