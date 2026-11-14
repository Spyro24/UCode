"""A file node's body: the file itself with line numbers, editable in place."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFocusEvent, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QWidget

from ucode.ui.highlighters import highlighter_for
from ucode.ui.theme import BG_NODE_EDITOR, GUTTER_BG, GUTTER_TEXT, TEXT

SELECTION = "#3b5480"


class _LineNumbers(QWidget):
    """The gutter strip: it draws nothing itself, the editor does."""

    def __init__(self, editor: NodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor
        self.setObjectName("nodeGutter")

    def sizeHint(self) -> QSize:
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_gutter(event)


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
        # No document margin: the node was measured without one.
        self.document().setDocumentMargin(0)
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

        # Kept as an attribute: the document does not own its highlighter.
        self.highlighter = highlighter_for(path, self.document())

        self._gutter = _LineNumbers(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_gutter_width()

        self.document().setModified(False)

    # -- gutter --------------------------------------------------------
    def gutter_width(self) -> int:
        # Proportional to the character advance, so the gutter scales with the zoom and
        # stays inside the width the node was measured with.
        digits = len(str(max(1, self.blockCount())))
        advance = self.fontMetrics().horizontalAdvance("9")
        return max(6, round(advance * (digits + 1.2)))

    def _update_gutter_width(self, _count: int = 0) -> None:
        width = self.gutter_width()
        self.setViewportMargins(width, 0, 0, 0)
        self._gutter.setFixedWidth(width)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def paint_gutter(self, event: QPaintEvent) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(GUTTER_BG))
        painter.setFont(self.font())
        painter.setPen(QColor(GUTTER_TEXT))

        block = self.firstVisibleBlock()
        number = block.blockNumber()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        bottom = top + self.blockBoundingRect(block).height()
        line_height = self.fontMetrics().height()
        width = self._gutter.width() - 5
        limit = event.rect().bottom()

        while block.isValid() and top <= limit:
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    QRect(0, int(top), width, line_height),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                    str(number + 1),
                )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(
            QRect(rect.left(), rect.top(), self.gutter_width(), rect.height())
        )

    # -- text ----------------------------------------------------------
    def _update_tab_width(self) -> None:
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

    def set_zoom_font(self, pixels: int) -> None:
        """Scale the text with the canvas zoom."""
        font = self.font()
        # The same floor the canvas uses, so text never outgrows the node it was sized for.
        font.setPixelSize(max(5, pixels))
        self.setFont(font)
        self._update_tab_width()
        self._update_gutter_width()
        self._gutter.update()

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
