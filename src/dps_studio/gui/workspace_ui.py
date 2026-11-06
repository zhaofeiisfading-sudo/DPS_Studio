"""Small presentation-only widgets shared by the Research workspaces."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


def channel_label(identity: str) -> str:
    """Keep machine identities in itemData and exports, shorten visible labels."""
    match = re.fullmatch(r"pdv_channel_(\d+)", identity)
    return f"候选{match[1]}" if match else identity


class CollapsibleSection(QWidget):
    """A disclosure control that never changes a scientific parameter."""

    def __init__(self, title: str, content: QWidget, *, expanded: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setObjectName("sectionDisclosure")
        self.content = content
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        self.toggle.toggled.connect(self._set_expanded)
        self._set_expanded(expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)
