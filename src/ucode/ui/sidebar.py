"""The left sidebar: a tool strip exactly one tile wide."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from ucode.core.tile import TILE
from ucode.ui.theme import (
    BG_CHROME,
    BG_CONTROL_HOVER,
    BG_CONTROL_PRESSED,
    BORDER,
    TEXT,
    TEXT_MUTED,
)

BUTTON_STYLE = (
    f"QPushButton {{ color: {TEXT_MUTED}; background: transparent; border: none; }}"
    f"QPushButton:hover {{ background-color: {BG_CONTROL_HOVER}; }}"
    f"QPushButton:checked {{ background-color: {BG_CONTROL_PRESSED}; color: {TEXT}; }}"
)


def folder_icon(size: int, colour: str) -> QIcon:
    """A small folder outline, drawn rather than loaded from an asset."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour))
    pen.setWidthF(size / 12)
    painter.setPen(pen)

    tab = QRectF(size * 0.18, size * 0.28, size * 0.26, size * 0.12)
    body = QRectF(size * 0.16, size * 0.35, size * 0.68, size * 0.38)
    painter.drawRoundedRect(tab, size * 0.03, size * 0.03)
    painter.drawRoundedRect(body, size * 0.06, size * 0.06)
    painter.end()

    return QIcon(pixmap)


class SideBar(QFrame):
    """Left-hand tool strip, fixed to one tile of width.

    The folder button toggles the file selector; everything else arrives with the
    canvas work.
    """

    WIDTH = TILE

    files_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("sideBar")
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(
            f"#sideBar {{ background-color: {BG_CHROME};"
            f" border-right: 1px solid {BORDER}; }}"
        )

        self.folder_button = QPushButton(self)
        self.folder_button.setObjectName("folderButton")
        self.folder_button.setCheckable(True)
        self.folder_button.setFixedSize(TILE, TILE)
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_button.setToolTip("Files")
        self.folder_button.setIcon(folder_icon(TILE // 2, TEXT_MUTED))
        self.folder_button.setIconSize(self.folder_button.iconSize())
        self.folder_button.setStyleSheet(BUTTON_STYLE)
        self.folder_button.clicked.connect(self.files_toggled)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self.folder_button)
        self._layout.addStretch(1)
