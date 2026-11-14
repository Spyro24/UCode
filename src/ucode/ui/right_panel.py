"""The right-hand panel: editor on top, console underneath."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QFrame, QSplitter, QVBoxLayout, QWidget

from ucode.core.tile import TILE
from ucode.ui.console import Console


class RightPanel(QFrame):
    """Right-hand area, five tiles wide and closed by default.

    Vertically split: the editor takes the remaining height and the console sits at the
    bottom, three tiles tall by default. The splitter handle makes the two resizable.
    Neither part holds content yet.
    """

    DEFAULT_TILES = 5
    WIDTH = DEFAULT_TILES * TILE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._sizes_applied = False

        self.setObjectName("rightPanel")
        self.setMinimumWidth(TILE)
        self.setStyleSheet(
            "#rightPanel { background-color: #1f2228; border-left: 1px solid #2f333b; }"
        )

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setObjectName("panelSplitter")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        self.editor_area = QWidget(self.splitter)
        self.editor_area.setObjectName("editorArea")
        self.console = Console(self.splitter)

        self.splitter.addWidget(self.editor_area)
        self.splitter.addWidget(self.console)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)

    def showEvent(self, event: QShowEvent) -> None:
        """Give the console its three tiles once the panel has a real height."""
        super().showEvent(event)

        if not self._sizes_applied:
            self._sizes_applied = True
            available = self.splitter.height()
            bottom = Console.HEIGHT
            self.splitter.setSizes([max(available - bottom, 0), bottom])
