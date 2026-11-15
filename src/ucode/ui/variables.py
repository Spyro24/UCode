"""The variables panel: what the live session holds, and a place to change it.

The panel is a list of rows, one per variable of the frame the session is in. Values are
text boxes: typing a new Python value and pressing Enter applies it to the running
program, so a number or a flag can be tried out without editing the code.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ucode.ui.theme import (
    BG_PANEL,
    BG_SURFACE,
    BORDER,
    TEXT,
    TEXT_MUTED,
)


class _Row(QFrame):
    """One variable: its name, and its value in a box that can be edited."""

    def __init__(self, scope: str, name: str, entry: dict, parent: QWidget) -> None:
        super().__init__(parent)

        self.scope = scope
        self.name = name
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

        self.editor = QLineEdit(self)
        self.editor.setStyleSheet(
            f"QLineEdit {{ background-color: {BG_PANEL}; color: {TEXT};"
            f" border: 1px solid {BORDER}; border-radius: 3px; padding: 1px 4px; }}"
        )
        self.editor.setReadOnly(not entry.get("editable", True))
        if not entry.get("editable", True):
            self.editor.setStyleSheet(
                f"QLineEdit {{ background-color: {BG_PANEL}; color: {TEXT_MUTED};"
                f" border: none; padding: 1px 4px; }}"
            )

        layout.addWidget(label)
        layout.addWidget(self.editor, 1)

        self._value = str(entry.get("value", ""))
        self.editor.setText(self._value)
        # Reading starts at the beginning: a long repr otherwise shows its tail.
        self.editor.setCursorPosition(0)

    def set_value(self, value: str) -> None:
        """Follow the program, unless the user is typing in this very box."""
        self._value = value
        if not self.editor.hasFocus():
            self.editor.setText(value)
            self.editor.setCursorPosition(0)

    def value(self) -> str:
        return self.editor.text()


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
        self.where.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent;"
        )
        self.where.setAlignment(Qt.AlignmentFlag.AlignLeft)

        hint = QLabel("edit a value, press Enter to apply it to the run", self)
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
                row.editor.editingFinished.connect(
                    lambda name=key[1], field=row.editor: self._commit(name, field)
                )
                self._rows[key] = row
                # Before the trailing stretch, so the rows stay top-aligned.
                self._list.insertWidget(self._list.count() - 1, row)
            else:
                row.set_value(str(entry.get("value", "")))

    def show_text(self, text: str) -> None:
        """Say what the panel is looking at without changing the rows."""
        self.where.setText(text)

    def clear(self, reason: str = "no session") -> None:
        self.where.setText(reason)
        for key in list(self._rows):
            row = self._rows.pop(key)
            row.setParent(None)
            row.deleteLater()

    def _commit(self, name: str, field: QLineEdit) -> None:
        self.edited.emit(name, field.text())
