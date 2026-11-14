"""The left sidebar: a tool strip exactly one tile wide."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ucode.core.tile import TILE


class SideBar(QFrame):
    """Left-hand tool strip, fixed to one tile of width.

    Empty for now — tool buttons arrive with the canvas work. The width follows the
    project's tile size, so the sidebar always lines up with the canvas grid.
    """

    WIDTH = TILE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("sideBar")
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(
            "#sideBar { background-color: #22252b; border-right: 1px solid #2f333b; }"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
