"""The work area: the editor with the console beneath it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from ucode.ui.console import Console


class EditorArea(QWidget):
    """Placeholder for the code editor. Empty until the editor lands."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editorArea")


class WorkArea(QWidget):
    """Editor on top, console underneath, both resizable.

    The editor takes the remaining height and the console keeps its three-tile default
    height at the bottom.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._sizes_applied = False

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setObjectName("workSplitter")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        self.editor = EditorArea(self.splitter)
        self.console = Console(self.splitter)

        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.console)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)

    def showEvent(self, event: QShowEvent) -> None:
        """Give the console its three tiles once the area has a real height."""
        super().showEvent(event)

        if not self._sizes_applied:
            self._sizes_applied = True
            available = self.splitter.height()
            bottom = Console.HEIGHT
            self.splitter.setSizes([max(available - bottom, 0), bottom])
