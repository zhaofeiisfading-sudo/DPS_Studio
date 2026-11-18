"""Shared display components for the desktop work area."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontInfo, QFontMetrics, QPainter, QPaintEvent, QResizeEvent
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

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt virtual API
        super().resizeEvent(event)
        parent = self.parentWidget()
        if parent is None or not self.count():
            return
        # Preserve the desktop font at normal widths. Scale the labels together
        # when a wide fallback font or a small screen exhausts the row.
        font = QFont(parent.font())
        metrics = QFontMetrics(font)
        labels = [self.item(row).text() for row in range(self.count())]
        text_width = sum(metrics.horizontalAdvance(label) for label in labels)
        padding = sum(
            self.sizeHintForIndex(self.model().index(row, 0)).width()
            - self.fontMetrics().horizontalAdvance(label)
            for row, label in enumerate(labels)
        )
        available = self.viewport().width() - padding
        if 0 < available < text_width:
            pixels = QFontInfo(font).pixelSize()
            if pixels <= 0:
                pixels = metrics.height()
            font.setPixelSize(max(1, pixels * available // text_width))
        if font != self.font():
            self.setFont(font)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual API
        items = [self.sizeHintForIndex(self.model().index(row, 0)) for row in range(self.count())]
        margins = self.contentsMargins()
        return QSize(
            sum(item.width() for item in items) + margins.left() + margins.right(),
            max((item.height() for item in items), default=self.fontMetrics().height())
            + margins.top() + margins.bottom(),
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual API
        return QSize(0, self.sizeHint().height())


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
