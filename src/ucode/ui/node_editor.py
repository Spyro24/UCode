"""A file node's body: the file itself with line numbers, editable in place."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
)
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

    content_changed = Signal()  # the text grew or shrank: the node must follow

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.path = path

        self.setObjectName("nodeEditor")
        self.setFrameShape(QFrame.Shape.NoFrame)
        # No document margin: the node was measured without one.
        self.document().setDocumentMargin(0)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # A node is exactly as big as its text, so nothing ever needs to scroll — and a
        # scrollbar would eat into the space the text was fitted to.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

        # The size the text was last fitted to, so moving a node does not re-fit it.
        self._fitted: tuple[int, int, int, int] | None = None
        self._lines: list[str] = []
        self._content_dirty = True

        self._gutter = _LineNumbers(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_gutter_width()

        self.document().setModified(False)
        # Editing changes how much room the text needs, so the fit has to be redone.
        self.document().contentsChanged.connect(self._mark_content_changed)

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

    def set_font_size(self, pixels: int) -> None:
        font = self.font()
        font.setPixelSize(max(3, pixels))
        self.setFont(font)
        # The document needs the font too, or measuring what it will render uses the old
        # metrics and lets an oversized font through.
        self.document().setDefaultFont(font)
        self._update_tab_width()
        self._update_gutter_width()
        self._gutter.update()

    def fit_text(self, width: int, height: int, columns: int, rows: int) -> None:
        """Pick the font that makes the code fill this node exactly.

        The node keeps its size, so the *text* has to follow it: a font tied to the zoom
        instead would be rounded to whole pixels and leave a gap that grows with the
        distance from 1:1. Solving for the box keeps the code flush with its edges at
        every zoom, and the shrink loop below guarantees nothing is clipped either.
        """
        # What the document actually holds, in case the file changed under the node.
        if self._content_dirty:
            self._lines = self.toPlainText().split("\n")
            self._content_dirty = False

        lines = self._lines
        rows = max(1, rows, len(lines))
        columns = max(1, columns, max(len(line) for line in lines))

        # Fitting relayouts the whole document, so only do it when the box changed.
        key = (width, height, columns, rows)
        if key == self._fitted:
            return
        self._fitted = key

        digits = len(str(max(1, rows)))

        probe = QFont(self.font())
        probe.setPixelSize(100)
        metrics = QFontMetricsF(probe)
        advance = max(1.0, metrics.horizontalAdvance("9"))
        spacing = max(1.0, metrics.lineSpacing())

        # Room for the gutter, the widest line, a cursor and a couple of pixels of slack.
        by_width = (max(1, width) - 8) * 100.0 / (
            advance * (max(1, columns) + digits + 1.2)
        )
        by_height = (max(1, height) - 2) * 100.0 / (spacing * max(1, rows))

        estimate = max(3, int(min(by_width, by_height)))

        # Take the largest size that really fits, measured with the font itself, so no
        # rounding can push a line or a row out of the node.
        for size in range(estimate + 1, 2, -1):
            self.set_font_size(size)
            metrics = self.fontMetrics()
            advance = metrics.horizontalAdvance("9")

            # The gutter takes its own slice of the width, so count it exactly.
            gutter = max(6, round(advance * (digits + 1.2)))
            available = width - gutter
            if available < 8:
                continue

            # Measure the widest line itself: an estimate in whole characters can be a
            # character out, and a size that overflows is skipped for the next one down.
            widest = max(metrics.horizontalAdvance(line) for line in lines)
            if widest + 2 > available:
                continue
            if metrics.lineSpacing() * rows + 2 > height:
                continue

            return

        self.set_font_size(3)

    def _mark_content_changed(self) -> None:
        """Forget the measurements and the fit; they are redone on the next sync."""
        self._content_dirty = True
        self._fitted = None
        self.content_changed.emit()

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
