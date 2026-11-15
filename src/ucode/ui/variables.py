"""The variables panel: what the live session holds, and a place to change it.

Each row is a name and a small field on its right. A plain value — number, text, boolean,
None — shows itself in that field; anything else shows only a pen, because its value is
too big to sit in a sidebar. Clicking either one turns it into an edit box: type a Python
value, press Enter, and the running program takes it. Escape leaves it alone.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ucode.ui.theme import (
    BG_CONTROL,
    BG_CONTROL_HOVER,
    BG_PANEL,
    BG_SURFACE,
    BORDER,
    TEXT,
    TEXT_MUTED,
)

PEN = "\u270e"  # shown instead of a value the field cannot hold
FIELD_CHARS = 22  # a long value is elided: the panel is narrow


class _Row(QFrame):
    """One variable: its name, and a field that shows its value or opens for editing."""

    edited = Signal(str, str)  # name, the text the user typed

    def __init__(self, scope: str, name: str, entry: dict, parent: QWidget) -> None:
        super().__init__(parent)

        self.scope = scope
        self.name = name
        # A plain value shows itself; anything else only gets a pen.
        self.plain = bool(entry.get("plain", entry.get("editable", True)))
        depth = int(entry.get("depth", 0) or 0)
        self.setStyleSheet(
            f"_Row {{ background-color: {BG_SURFACE}; border-radius: 3px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6 + depth * 12, 2, 4, 2)
        layout.setSpacing(6)

        label = QLabel(str(entry.get("label", name)), self)
        label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        label.setMinimumWidth(max(24, 70 - depth * 12))
        label.setToolTip(f"{name} \u00b7 " + ("module level" if scope == "global" else "local"))

        # The field: a value chip, or a pen when the value is not a plain one.
        self.chip = QToolButton(self)
        self.chip.setAutoRaise(True)
        self.chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip.setToolTip("click to edit this value")
        self.chip.setStyleSheet(
            f"QToolButton {{ color: {TEXT}; background-color: {BG_CONTROL};"
            f" border: 1px solid {BORDER}; border-radius: 3px; padding: 1px 6px; }}"
            f"QToolButton:hover {{ background-color: {BG_CONTROL_HOVER}; }}"
        )
        self.chip.clicked.connect(self._begin)

        self.editor = QLineEdit(self)
        self.editor.hide()
        self.editor.setStyleSheet(
            f"QLineEdit {{ background-color: {BG_PANEL}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 3px; padding: 1px 4px; }}"
        )
        self.editor.editingFinished.connect(self._finish)
        self.editor.installEventFilter(self)

        layout.addWidget(label, 1)
        layout.addWidget(self.chip)
        layout.addWidget(self.editor, 1)

        self._value = str(entry.get("value", ""))
        self._show_value()

    # -- the field -----------------------------------------------------
    def _show_value(self) -> None:
        """Back to the chip, showing the value or the pen."""
        self.editor.hide()
        self.chip.show()

        if not self.plain:
            self.chip.setText(PEN)
            self.chip.setToolTip(f"{self._value} \u2014 click to edit")
            return

        text = self._value
        if len(text) > FIELD_CHARS:
            text = text[: FIELD_CHARS - 1] + "\u2026"
        self.chip.setText(text)
        self.chip.setToolTip(self._value)

    def _begin(self) -> None:
        """Turn the field into an edit box holding the current value."""
        self.chip.hide()
        self.editor.setText(self._value)
        self.editor.show()
        self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self.editor.selectAll()

    def _finish(self) -> None:
        text = self.editor.text()
        self._value = text
        self._show_value()
        self.edited.emit(self.name, text)

    def set_value(self, value: str) -> None:
        """Follow the program, unless the user is typing in this very field."""
        if self.editor.isVisible():
            return
        self._value = value
        self._show_value()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.editor and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                # Escape keeps the old value: hide without committing.
                self.editor.blockSignals(True)
                self._show_value()
                self.editor.blockSignals(False)
                return True
        return super().eventFilter(watched, event)


class VariablesPanel(QWidget):
    """The live session's variables, editable in place."""

    edited = Signal(str, str)  # name, the text the user typed

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._rows: dict[tuple[str, str], _Row] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Variables", self)
        title.setStyleSheet(f"color: {TEXT}; font-weight: 600; background: transparent;")

        self.where = QLabel("no session", self)
        self.where.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        self.where.setAlignment(Qt.AlignmentFlag.AlignLeft)

        hint = QLabel("click a value, change it, press Enter", self)
        hint.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.where)
        layout.addWidget(hint)

        self._body = QWidget(self)
        self._list = QVBoxLayout(self._body)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(3)
        self._list.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._body)
        # The viewport paints itself white by default; the panel is dark.
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 8px; }"
            f"QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; }}"
        )
        self._body.setStyleSheet("background: transparent;")
        layout.addWidget(scroll, 1)
        self._scroll = scroll

    # -- content -------------------------------------------------------
    def set_entries(self, entries: list[dict], where: str) -> None:
        """Show these variables, keeping the user's focus where it is."""
        self.where.setText(where)

        wanted: dict[tuple[str, str], dict] = {}
        for entry in entries:
            wanted[(str(entry.get("scope", "local")), str(entry.get("name", "")))] = entry

        for key in list(self._rows):
            if key not in wanted:
                row = self._rows.pop(key)
                row.setParent(None)
                row.deleteLater()

        for key, entry in wanted.items():
            row = self._rows.get(key)
            if row is None:
                row = _Row(key[0], key[1], entry, self._body)
                row.edited.connect(self.edited)
                self._rows[key] = row
                # Before the trailing stretch, so the rows stay top-aligned.
                self._list.insertWidget(self._list.count() - 1, row)
            else:
                row.set_value(str(entry.get("value", "")))

    def show_text(self, text: str) -> None:
        """Say what the panel is looking at without changing the rows."""
        self.where.setText(text)

    def reveal(self, name: str) -> bool:
        """Scroll a variable into view and put the keyboard on its field."""
        for (scope, key), row in self._rows.items():
            if key == name or key.endswith(f".{name}"):
                row.chip.setFocus(Qt.FocusReason.OtherFocusReason)
                self._scroll.ensureWidgetVisible(row)
                return True
        return False

    def clear(self, reason: str = "no session") -> None:
        self.where.setText(reason)
        for key in list(self._rows):
            row = self._rows.pop(key)
            row.setParent(None)
            row.deleteLater()
