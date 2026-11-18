"""Small reusable containers for the workflow inspector."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QFrame, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from dps_studio.gui.icons import chevron_icon


class InspectorCard(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("inspectorCard", True)
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(12, 10, 12, 10)
        self.body_layout.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setProperty("role", "cardTitle")
            label.setWordWrap(True)
            self.body_layout.addWidget(label)

    def add_form(self, form: QFormLayout) -> None:
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.body_layout.addLayout(form)


class CollapsibleSection(QFrame):
    def __init__(self, title: str, *, expanded: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("inspectorCard", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setProperty("accordionToggle", True)
        self.toggle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_button.setCheckable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(2, 4, 2, 4)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.body)
        self.toggle_button.setChecked(expanded)
        self._show_body(expanded)
        self.toggle_button.toggled.connect(self._show_body)

    def _show_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle_button.setIcon(chevron_icon(expanded))

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(expanded)


class StatusBanner(QFrame):
    def __init__(self, tone: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.addWidget(self.label)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        if tone not in {"info", "success", "warning", "error"}:
            raise ValueError(f"Unknown banner tone: {tone}")
        if self.property("banner") != tone:
            self.setProperty("banner", tone)
            for widget in (self, self.label):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
