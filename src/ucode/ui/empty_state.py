"""Shown while no folder is open."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ucode.core.tile import TILE
from ucode.ui.theme import (
    BG_CONTROL,
    BG_CONTROL_HOVER,
    BG_CONTROL_PRESSED,
    BG_SURFACE,
    BORDER_STRONG,
    TEXT,
)


class EmptyState(QWidget):
    """A single button asking for the folder to work on.

    It takes the place of the workspace until a project is open, which is why it is the
    only thing on screen: there is nothing else to offer yet.
    """

    folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("emptyState")
        # A plain QWidget needs this attribute before a stylesheet background is painted.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#emptyState {{ background-color: {BG_SURFACE}; }}")

        self.button = QPushButton("Open Folder", self)
        self.button.setObjectName("openFolderButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setMinimumSize(TILE * 3, int(TILE * 1.1))
        self.button.setStyleSheet(
            f"#openFolderButton {{ font-size: 14px; color: {TEXT};"
            f" background-color: {BG_CONTROL}; border: 1px solid {BORDER_STRONG};"
            " border-radius: 4px; padding: 0 18px; }"
            f"#openFolderButton:hover {{ background-color: {BG_CONTROL_HOVER}; }}"
            f"#openFolderButton:pressed {{ background-color: {BG_CONTROL_PRESSED}; }}"
        )
        self.button.clicked.connect(self.folder_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
