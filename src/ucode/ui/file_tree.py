"""The file selector: the opened folder's contents, four tiles wide."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir
from PySide6.QtWidgets import (
    QFileSystemModel,
    QFrame,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ucode.core.tile import TILE
from ucode.ui.theme import BG_PANEL, BG_SURFACE, BORDER, TEXT


class FileTree(QFrame):
    """A tree of the folder the user opened, fixed to four tiles of width.

    It shows nothing until a folder is set, and its root is always that folder: the
    file selector never wanders outside the project the user picked.
    """

    DEFAULT_TILES = 4
    WIDTH = DEFAULT_TILES * TILE

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("fileTree")
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(
            f"#fileTree {{ background-color: {BG_PANEL};"
            f" border-right: 1px solid {BORDER}; }}"
        )

        self.model = QFileSystemModel(self)
        self.model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )
        self.model.setReadOnly(True)

        self.view = QTreeView(self)
        self.view.setObjectName("fileTreeView")
        self.view.setModel(self.model)
        self.view.setHeaderHidden(True)
        self.view.setAnimated(False)
        self.view.setIndentation(TILE // 2)
        self.view.setUniformRowHeights(True)
        self.view.setStyleSheet(
            f"QTreeView {{ background-color: {BG_SURFACE}; color: {TEXT};"
            " border: none; }"
        )
        for column in (1, 2, 3):
            self.view.setColumnHidden(column, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

    def set_root(self, path: Path) -> None:
        """Root the tree at ``path`` and show it."""
        root = str(path)
        self.model.setRootPath(root)
        self.view.setRootIndex(self.model.index(root))
