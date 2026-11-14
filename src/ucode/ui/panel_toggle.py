"""The panel toggle: a one-tile column between the canvas and the right panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
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

GLYPH = "\u25a4"  # ▤ — a panel icon, drawn as text so no icon asset is needed yet


class PanelToggle(QFrame):
    """One-tile-wide strip that carries the button for the right panel.

    It belongs to the canvas side of the splitter, so it sits between the left sidebar
    and the right panel and stays visible while the panel is closed. The button is
    checkable: checked means the panel is open.
    """

    WIDTH = TILE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("panelToggle")
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(
            f"#panelToggle {{ background-color: {BG_CHROME};"
            f" border-left: 1px solid {BORDER}; }}"
        )

        self.button = QPushButton(GLYPH, self)
        self.button.setObjectName("panelToggleButton")
        self.button.setCheckable(True)
        self.button.setFixedSize(TILE, TILE)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip("Show or hide the panel")
        self.button.setStyleSheet(
            f"#panelToggleButton {{ color: {TEXT_MUTED}; background: transparent;"
            f" border: none; font-size: 18px; }}"
            f"#panelToggleButton:hover {{ background-color: {BG_CONTROL_HOVER}; }}"
            f"#panelToggleButton:checked {{ background-color: {BG_CONTROL_PRESSED};"
            f" color: {TEXT}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.button)
        layout.addStretch(1)
