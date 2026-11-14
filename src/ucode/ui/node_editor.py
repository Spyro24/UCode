"""A file node's body: the file itself, editable in place."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFocusEvent, QFont
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QWidget

from ucode.ui.theme import BG_NODE_EDITOR, TEXT

SELECTION = "#3b5480"


class NodeEditor(QPlainTextEdit):
    """A plain-text code view bound to one file.

    Every node carries one of these, so editing on the canvas is editing the file: the
    contents are written back when the editor loses focus.
    """

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.path = path

        self.setObjectName("nodeEditor")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {BG_NODE_EDITOR}; color: {TEXT};"
            f" border: none; selection-background-color: {SELECTION}; }}"
        )

        font = QFont()
        font.setFamilies(["monospace", "DejaVu Sans Mono", "Liberation Mono"])
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self._update_tab_width()

        try:
            self.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            self.setPlainText("")

        self.document().setModified(False)

    def _update_tab_width(self) -> None:
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

    def set_zoom_font(self, pixels: int) -> None:
        """Scale the text with the canvas zoom."""
        font = self.font()
        font.setPixelSize(max(6, pixels))
        self.setFont(font)
        self._update_tab_width()

    def save(self) -> None:
        if not self.document().isModified():
            return

        try:
            self.path.write_text(self.toPlainText(), encoding="utf-8")
        except OSError:
            return

        self.document().setModified(False)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.save()
        super().focusOutEvent(event)
