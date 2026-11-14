"""Shown while no folder is open."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ucode.core.tile import TILE

BACKGROUND = "#fcfcfd"


class EmptyState(QWidget):
    """A single button asking for the folder to work on.

    It takes the place of the workspace until a project is open, which is why it is the
    only thing on screen: there is nothing else to offer yet.
    """

    folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("emptyState")
        self.setStyleSheet(f"#emptyState {{ background-color: {BACKGROUND}; }}")

        self.button = QPushButton("Open Folder", self)
        self.button.setObjectName("openFolderButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setMinimumSize(TILE * 3, int(TILE * 1.1))
        self.button.setStyleSheet(
            "#openFolderButton { font-size: 14px; color: #2b3038;"
            " background-color: #eef1f5; border: 1px solid #c7ced9;"
            " border-radius: 4px; padding: 0 18px; }"
            "#openFolderButton:hover { background-color: #e2e7ee; }"
            "#openFolderButton:pressed { background-color: #d6dce5; }"
        )
        self.button.clicked.connect(self.folder_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
