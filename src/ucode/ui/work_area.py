"""The work area: the workspace with the console beneath it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ucode.ui.canvas import Canvas
from ucode.ui.console import Console
from ucode.ui.empty_state import EmptyState


class WorkArea(QWidget):
    """Workspace on top, console underneath, both resizable.

    The top slot holds two pages: the empty state while no folder is open, and the
    canvas once one is. The workspace takes the remaining height and the console keeps
    its three-tile default height at the bottom.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._sizes_applied = False

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setObjectName("workSplitter")
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        self.stack = QStackedWidget(self.splitter)
        self.empty_state = EmptyState(self.stack)
        self.canvas = Canvas(self.stack)
        self.stack.addWidget(self.empty_state)
        self.stack.addWidget(self.canvas)
        self.stack.setCurrentWidget(self.empty_state)

        self.console = Console(self.splitter)

        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.console)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)

    # -- pages ---------------------------------------------------------
    def show_empty_state(self) -> None:
        """No folder open: offer the one action that makes sense."""
        self.stack.setCurrentWidget(self.empty_state)

    def show_canvas(self) -> None:
        """A folder is open: show the workspace."""
        self.stack.setCurrentWidget(self.canvas)

    def showEvent(self, event: QShowEvent) -> None:
        """Give the console its three tiles once the area has a real height."""
        super().showEvent(event)

        if not self._sizes_applied:
            self._sizes_applied = True
            available = self.splitter.height()
            bottom = Console.HEIGHT
            self.splitter.setSizes([max(available - bottom, 0), bottom])
