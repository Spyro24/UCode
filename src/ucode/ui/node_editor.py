"""A file node's body: the file itself with line numbers, editable in place."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QTextEdit, QWidget

from ucode.core.elf import parse_hex_dump
from ucode.ui.highlighters import highlighter_for
from ucode.ui.theme import (
    ACTIVE_LINE,
    BG_NODE_EDITOR,
    ERROR_LINE,
    EXECUTED_LINE,
    GUTTER_BG,
    GUTTER_TEXT,
    INLINE_VALUE_BG,
    INLINE_VALUE_TEXT,
    TEXT,
)

SELECTION = "#3b5480"
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
VALUE_CHARS = 22  # a value shown inline is a glance, not a reader


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

    def __init__(
        self,
        path: Path,
        parent: QWidget | None = None,
        *,
        text: str | None = None,
        mode: str = "source",
        tail: bytes = b"",
        source: Path | None = None,
    ) -> None:
        super().__init__(parent)

        self.path = path
        # Where the bytes actually live: a generated node's display path is not a file.
        self._source = source if source is not None else path
        # "source" edits the file as text, "hex" edits the hex dump's bytes, and
        # "readonly" shows generated text that never goes back to disk.
        self.mode = mode
        # A hex view shows the start of a file; the rest is written back untouched.
        self._tail = tail

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

        if text is None:
            try:
                self.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                self.setPlainText("")
        else:
            self.setPlainText(text)

        if mode == "readonly":
            self.setReadOnly(True)

        # Kept as an attribute: the document does not own its highlighter.
        self.highlighter = (
            highlighter_for(path, self.document()) if mode == "source" else None
        )

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

        # Write the edit back shortly after typing stops: a live session watches the
        # file, so its code has to reach disk without waiting for a focus change.
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(400)
        self._autosave.timeout.connect(self.save)

        # The live session's position, the lines it has run, and where it died.
        self._active_line: int | None = None
        self._error_line: int | None = None
        self._executed: set[int] = set()
        # What the variables on each line hold right now, drawn beside the code.
        self._values: dict[str, str] = {}
        # Which names each line reads and which it stores: a value is shown where it is
        # used, never on the line that merely gives it one.
        self._reads: dict[int, list[str]] = {}
        self._writes: dict[int, set[str]] = {}
        self._scan_names()

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

    def _scan_names(self) -> None:
        """Map every line to the names it reads and the names it stores."""
        source = self.toPlainText()
        if len(source) > 200_000 or self.mode != "source":
            self._reads, self._writes = {}, {}
            return

        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            # Half-typed code: no annotations until it parses again.
            self._reads, self._writes = {}, {}
            return

        reads: dict[int, list[str]] = {}
        writes: dict[int, set[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name):
                continue
            line = getattr(node, "lineno", 0)
            if isinstance(node.ctx, ast.Load):
                reads.setdefault(line, []).append(node.id)
            else:
                writes.setdefault(line, set()).add(node.id)

        self._reads, self._writes = reads, writes

    def _mark_content_changed(self) -> None:
        """Forget the measurements and the fit; they are redone on the next sync."""
        self._content_dirty = True
        self._scan_names()
        self._fitted = None
        if self.mode == "source":
            self._autosave.start()
        self.content_changed.emit()

    def set_active_line(self, line: int | None) -> None:
        """Mark the line a live session is executing, or take the mark away."""
        self._active_line = line
        self._refresh_marks()

    def set_error_line(self, line: int | None) -> None:
        """Mark the line a live session failed on, in red."""
        self._error_line = line
        self._refresh_marks()

    def set_executed_lines(self, lines) -> None:
        """Mark every line the session has run here, so its path through the file shows."""
        self._executed = {int(line) for line in lines if line}
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        """All the live marks overlap, so they are drawn weakest first."""
        selections = [
            selection
            for selection in (
                *(self._mark(line, EXECUTED_LINE) for line in sorted(self._executed)),
                self._mark(self._active_line, ACTIVE_LINE),
                self._mark(self._error_line, ERROR_LINE),
            )
            if selection is not None
        ]
        self.setExtraSelections(selections)

    def set_values(self, values: dict[str, str]) -> None:
        """Show these variables' values beside the lines that mention them."""
        self._values = dict(values)
        self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._values:
            return

        painter = QPainter(self.viewport())
        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        painter.setPen(QColor(INLINE_VALUE_TEXT))

        block = self.firstVisibleBlock()
        offset = self.contentOffset()
        top = self.blockBoundingGeometry(block).translated(offset).top()
        bottom = top + self.blockBoundingRect(block).height()
        limit = event.rect().bottom()
        viewport_width = self.viewport().width()

        while block.isValid() and top <= limit:
            if block.isVisible() and bottom >= event.rect().top():
                line_number = block.blockNumber() + 1
                stored = self._writes.get(line_number, set())
                shown = [
                    f"{name} = {self._values[name]}"
                    for name in dict.fromkeys(self._reads.get(line_number, []))
                    if name in self._values and name not in stored
                ]
                if shown:
                    self._paint_values(
                        painter, metrics, block, shown, top, bottom, viewport_width
                    )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()

        painter.end()

    def _paint_values(
        self,
        painter: QPainter,
        metrics,
        block,
        shown: list[str],
        top: float,
        bottom: float,
        viewport_width: int,
    ) -> None:
        """Draw the values just after the line's text, tall enough to read."""
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        text_right = self.cursorRect(cursor).right()

        # The value goes after the code, never over it: a line with no room gets none.
        x = text_right + 6
        room = viewport_width - 2 - x
        if room < metrics.horizontalAdvance("value") * 2:
            return

        label = ", ".join(shown)
        if len(label) > VALUE_CHARS:
            label = label[: VALUE_CHARS - 1] + "\u2026"
        if metrics.horizontalAdvance(label) + 10 > room:
            label = metrics.elidedText(
                label, Qt.TextElideMode.ElideRight, int(room) - 10
            )

        width = metrics.horizontalAdvance(label) + 10
        height = metrics.height() + 2
        y = top + max(0, (bottom - top - height) / 2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(INLINE_VALUE_BG))
        painter.drawRoundedRect(QRect(int(x), int(y), int(width), int(height)), 3, 3)

        painter.setPen(QColor(INLINE_VALUE_TEXT))
        painter.drawText(
            QRect(int(x), int(y), int(width), int(height)),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )

    def _mark(self, line: int | None, colour: str) -> QTextEdit.ExtraSelection | None:
        """A full-width band on one line, or None when there is no such line."""
        if not line:
            return None

        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return None

        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(colour))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = QTextCursor(block)
        return selection

    def save(self) -> None:
        if not self.document().isModified() or self.mode == "readonly":
            return

        try:
            if self.mode == "hex":
                data = parse_hex_dump(self.toPlainText())
                if data is None:
                    # A half-typed line: keep the edit in the view, leave the file alone.
                    return
                self._source.write_bytes(data + self._tail)
            else:
                self._source.write_text(self.toPlainText(), encoding="utf-8")
        except OSError:
            return

        self.document().setModified(False)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.save()
        super().focusOutEvent(event)
