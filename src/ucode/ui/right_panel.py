"""The right-hand panel: inspector, run log and search live here later."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ucode.core.tile import TILE


class RightPanel(QFrame):
    """Right-hand area: five tiles wide and closed by default, resizable by the user.

    Nothing is placed inside yet. The width is expressed in tiles so it lines up with
    the canvas grid; the splitter handle is what makes it resizable once it is open.
    """

    DEFAULT_TILES = 5
    WIDTH = DEFAULT_TILES * TILE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("rightPanel")
        self.setMinimumWidth(TILE)
        self.setStyleSheet(
            "#rightPanel { background-color: #1f2228; border-left: 1px solid #2f333b; }"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
