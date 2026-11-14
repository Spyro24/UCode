"""The bottom console: a Python REPL by default, a plain shell on request."""

from __future__ import annotations

from enum import Enum

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ucode.core.tile import TILE
from ucode.ui.theme import BG_CONSOLE, BORDER


class ConsoleMode(str, Enum):
    """Which interpreter the console drives."""

    PYTHON = "python"
    SHELL = "shell"


class Console(QFrame):
    """Console area, three tiles tall by default and resizable.

    Nothing runs in it yet. The mode chooses between a Python session and a plain
    shell; it is set in code until there is a control for it.
    """

    DEFAULT_TILES = 3
    HEIGHT = DEFAULT_TILES * TILE

    def __init__(
        self,
        parent: QWidget | None = None,
        mode: ConsoleMode = ConsoleMode.PYTHON,
    ) -> None:
        super().__init__(parent)

        self._mode = mode

        self.setObjectName("console")
        self.setMinimumHeight(TILE)
        self.setStyleSheet(
            f"#console {{ background-color: {BG_CONSOLE};"
            f" border-top: 1px solid {BORDER}; }}"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    @property
    def mode(self) -> ConsoleMode:
        return self._mode

    @mode.setter
    def mode(self, value: ConsoleMode) -> None:
        self._mode = value
