"""The panel toggle: a one-tile column between the canvas and the right panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget

from ucode.core.tile import TILE

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
            "#panelToggle { background-color: #22252b; border-left: 1px solid #2f333b; }"
        )

        self.button = QPushButton(GLYPH, self)
        self.button.setObjectName("panelToggleButton")
        self.button.setCheckable(True)
        self.button.setFixedSize(TILE, TILE)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setToolTip("Show or hide the panel")
        self.button.setStyleSheet(
            "#panelToggleButton { color: #b9c0cc; background: transparent; border: none;"
            " font-size: 18px; }"
            "#panelToggleButton:hover { background-color: #2c3038; }"
            "#panelToggleButton:checked { background-color: #333844; color: #e6ebf2; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.button)
        layout.addStretch(1)
