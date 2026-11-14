"""Syntax highlighting for the two languages the editor supports.

Line-based rules plus block state for the constructs that span lines: Python's
triple-quoted strings and C's block comments.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from ucode.ui import theme

PYTHON_KEYWORDS = (
    "and", "as", "assert", "async", "await", "break", "class", "continue", "def",
    "del", "elif", "else", "except", "finally", "for", "from", "global", "if",
    "import", "in", "is", "lambda", "match", "case", "nonlocal", "not", "or",
    "pass", "raise", "return", "try", "while", "with", "yield",
)

C_KEYWORDS = (
    "auto", "break", "case", "char", "const", "continue", "default", "do", "double",
    "else", "enum", "extern", "float", "for", "goto", "if", "inline", "int", "long",
    "register", "restrict", "return", "short", "signed", "sizeof", "static",
    "struct", "switch", "typedef", "union", "unsigned", "void", "volatile", "while",
    "NULL", "size_t", "ssize_t", "bool", "true", "false",
)


def _format(colour: str, *, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colour))
    if italic:
        fmt.setFontItalic(True)
    return fmt


class _Highlighter(QSyntaxHighlighter):
    """Shared plumbing: an ordered list of (pattern, format) rules."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)

        self.keyword = _format(theme.SYNTAX_KEYWORD)
        self.number = _format(theme.SYNTAX_NUMBER)
        self.string = _format(theme.SYNTAX_STRING)
        self.comment = _format(theme.SYNTAX_COMMENT, italic=True)
        self.call = _format(theme.SYNTAX_FUNCTION)
        self.decorator = _format(theme.SYNTAX_DECORATOR)
        self.preprocessor = _format(theme.SYNTAX_PREPROCESSOR)

        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

    def _add(self, pattern: str, fmt: QTextCharFormat) -> None:
        self.rules.append((QRegularExpression(pattern), fmt))

    def _apply(self, text: str) -> None:
        """Later rules win, so strings and comments are added last."""
        for pattern, fmt in self.rules:
            matches = pattern.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class PythonHighlighter(_Highlighter):
    """Python: keywords, numbers, strings, docstrings, comments, decorators."""

    TRIPLES = ('"""', "'''")

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)

        self._add(r"\b(?:%s)\b" % "|".join(PYTHON_KEYWORDS), self.keyword)
        self._add(r"\b(?:True|False|None|self|cls)\b", self.keyword)
        self._add(r"\b\d[\d_]*(?:\.\d+)?\b", self.number)
        self._add(r"@\w+(?:\.\w+)*", self.decorator)
        self._add(r"\b(\w+)\s*\(", self.call)
        self._add(r"#[^\n]*", self.comment)
        self._add(r'"[^"\n]*"|\'[^\'\n]*\'', self.string)

    def highlightBlock(self, text: str) -> None:
        self.setCurrentBlockState(0)
        offset = 0

        previous = self.previousBlockState()
        if previous in (1, 2):
            delimiter = self.TRIPLES[previous - 1]
            end = text.find(delimiter)
            if end == -1:
                self.setFormat(0, len(text), self.string)
                self.setCurrentBlockState(previous)
                return
            self.setFormat(0, end + len(delimiter), self.string)
            offset = end + len(delimiter)

        self._apply(text)

        for state, delimiter in enumerate(self.TRIPLES, start=1):
            start = text.find(delimiter, offset)
            if start == -1:
                continue

            end = text.find(delimiter, start + len(delimiter))
            if end == -1:
                self.setFormat(start, len(text) - start, self.string)
                self.setCurrentBlockState(state)
                return

            self.setFormat(start, end + len(delimiter) - start, self.string)


class CHighlighter(_Highlighter):
    """C: keywords, numbers, preprocessor lines, strings, comments."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)

        self._add(r"\b(?:%s)\b" % "|".join(C_KEYWORDS), self.keyword)
        self._add(r"\b0[xX][0-9a-fA-F]+\b|\b\d[\dUuLl]*\b", self.number)
        self._add(r"^\s*#\s*\w+", self.preprocessor)
        self._add(r"\b(\w+)\s*\(", self.call)
        self._add(r"//[^\n]*", self.comment)
        self._add(r"/\*.*?\*/", self.comment)
        self._add(r'"[^"\n]*"|\'[^\'\n]*\'', self.string)

    def highlightBlock(self, text: str) -> None:
        self.setCurrentBlockState(0)
        offset = 0

        if self.previousBlockState() == 1:
            end = text.find("*/")
            if end == -1:
                self.setFormat(0, len(text), self.comment)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 2, self.comment)
            offset = end + 2

        self._apply(text)

        start = text.find("/*", offset)
        if start != -1 and text.find("*/", start + 2) == -1:
            self.setFormat(start, len(text) - start, self.comment)
            self.setCurrentBlockState(1)


def highlighter_for(path: Path, document: QTextDocument) -> _Highlighter | None:
    """The highlighter matching a file's language, if there is one."""
    if path.suffix == ".py":
        return PythonHighlighter(document)
    if path.suffix in {".c", ".h"}:
        return CHighlighter(document)
    return None
