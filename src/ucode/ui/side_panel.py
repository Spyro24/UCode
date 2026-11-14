"""The side panel: contextual, five tiles wide, absent unless something needs it."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ucode.core.tile import TILE
from ucode.ui.theme import BG_PANEL, BORDER


class SidePanel(QFrame):
    """Right-hand side panel.

    It is not part of the permanent layout: it exists only when the current context asks
    for it, so it starts hidden and is shown through the window's open/close methods.
    Nothing is placed inside yet.
    """

    DEFAULT_TILES = 5
    WIDTH = DEFAULT_TILES * TILE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("sidePanel")
        self.setMinimumWidth(TILE)
        self.setStyleSheet(
            f"#sidePanel {{ background-color: {BG_PANEL};"
            f" border-left: 1px solid {BORDER}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
