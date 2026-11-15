"""The bottom console: a Python REPL by default, a plain shell on request."""

from __future__ import annotations

import codeop
import json
import re
import shlex
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ucode.core.tile import TILE
from ucode.ui.theme import (
    BG_CONSOLE,
    BORDER,
    CONSOLE_ERROR,
    TEXT,
    TEXT_MUTED,
)

# The shell appends this to every command so the console knows when it finished, and
# with which working directory. Letter-boxes nobody prints by accident.
_MARKER = re.compile("\x01UCODE(\\d+)\\|(.*?)\x01", re.DOTALL)
_DONE = "printf '\\001UCODE%s|%s\\001' $? \"$PWD\"\n"

# A live session reports control events in the same stream as its output.
_EVENT = re.compile("\x01UCODE(\\{.*?\\})\x01", re.DOTALL)

def _short_path(path: Path | None) -> str:
    """A path as the prompt is willing to show it: home collapsed."""
    if path is None:
        return ""

    try:
        relative = path.relative_to(Path.home())
        return str(Path("~") / relative)
    except ValueError:
        return str(path)


def _quote(path: Path) -> str:
    return shlex.quote(str(path))


class ConsoleMode(str, Enum):
    """Which interpreter the console drives."""

    PYTHON = "python"
    SHELL = "shell"


class _Writer:
    """A file object that sends Python's output to the console pane."""

    def __init__(self, sink) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        if text:
            self._sink(text)
        return len(text)

    def flush(self) -> None:
        pass


class _Input(QLineEdit):
    """The prompt line: Enter runs, Up/Down walk the history."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.history: list[str] = []
        self.index = 0
        self.draft = ""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._walk(-1)
            return
        if key == Qt.Key.Key_Down:
            self._walk(1)
            return
        super().keyPressEvent(event)

    def _walk(self, step: int) -> None:
        if not self.history:
            return

        if self.index == len(self.history):
            self.draft = self.text()

        self.index = max(0, min(len(self.history), self.index + step))
        text = self.draft if self.index == len(self.history) else self.history[self.index]
        self.setText(text)
        self.setCursorPosition(len(text))


class Console(QFrame):
    """Console area, three tiles tall by default and resizable.

    Python mode runs an in-process REPL against one persistent namespace. Shell mode
    keeps a single bash alive, so `cd` and variables survive between commands.
    """

    # A live session's current position, and the end of a run or of the session.
    live_line = Signal(str, int)
    live_error = Signal(str, int)  # where the session died
    live_idle = Signal()
    live_stopped = Signal()

    DEFAULT_TILES = 3
    HEIGHT = DEFAULT_TILES * TILE

    def __init__(
        self,
        parent: QWidget | None = None,
        mode: ConsoleMode = ConsoleMode.PYTHON,
    ) -> None:
        super().__init__(parent)

        self._mode = mode
        self._project: Path | None = None
        self._continuation = ""
        self._namespace: dict[str, object] = {"__name__": "__console__"}
        self._shell: QProcess | None = None
        self._shell_buffer = ""
        self._shell_busy = False
        self._program: QProcess | None = None
        self._program_buffer = ""
        self._program_live = False
        self._program_idle = False
        self._stopping = False  # we killed it ourselves: no exit status to report
        self._cwd = Path.cwd()

        self.setObjectName("console")
        self.setMinimumHeight(TILE)
        self.setStyleSheet(
            f"#console {{ background-color: {BG_CONSOLE};"
            f" border-top: 1px solid {BORDER}; }}"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._build_header()
        self._build_output()
        self._build_prompt()

        self._start_session()

    # -- widgets -------------------------------------------------------
    def _build_header(self) -> None:
        header = QWidget(self)
        header.setFixedHeight(26)

        row = QHBoxLayout(header)
        row.setContentsMargins(8, 2, 6, 2)
        row.setSpacing(4)

        self._mode_buttons: dict[ConsoleMode, QPushButton] = {}
        for mode, label in ((ConsoleMode.PYTHON, "Python"), (ConsoleMode.SHELL, "Shell")):
            button = QPushButton(label, header)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(self._button_style())
            button.clicked.connect(lambda _checked=False, m=mode: self._choose(m))
            row.addWidget(button)
            self._mode_buttons[mode] = button

        row.addStretch(1)

        self._clear_button = QPushButton("Clear", header)
        self._clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_button.setStyleSheet(self._button_style())
        self._clear_button.clicked.connect(self.clear)
        row.addWidget(self._clear_button)

        self._layout.addWidget(header)

    @staticmethod
    def _button_style() -> str:
        return (
            "QPushButton { background: transparent; color: %s;"
            " border: 1px solid transparent; border-radius: 3px;"
            " padding: 1px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #232730; }"
            "QPushButton:checked { color: %s; border-color: #333a46;"
            " background-color: #1c2028; }" % (TEXT_MUTED, TEXT)
        )

    def _build_output(self) -> None:
        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        self._output.setObjectName("consoleOutput")
        self._output.setFrameShape(QFrame.Shape.NoFrame)
        self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._output.setStyleSheet(
            f"#consoleOutput {{ background-color: {BG_CONSOLE}; color: {TEXT};"
            f" border: none; padding: 2px 8px; }}"
        )
        self._output.setMinimumHeight(TILE)

        font = QFont()
        font.setFamilies(["monospace", "DejaVu Sans Mono", "Liberation Mono"])
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPixelSize(13)
        self._output.setFont(font)
        self._output.document().setDefaultFont(font)
        # A long live trace must not turn the document into a millstone.
        self._output.setMaximumBlockCount(5000)

        self._layout.addWidget(self._output, 1)

    def _build_prompt(self) -> None:
        row = QWidget(self)
        row.setFixedHeight(28)

        line = QHBoxLayout(row)
        line.setContentsMargins(8, 0, 8, 4)
        line.setSpacing(0)

        self._prompt = QLabel(">>> ", row)
        self._prompt.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prompt.setFixedWidth(self._prompt_font_width() * 6)
        self._prompt.setStyleSheet(
            f"background: transparent; border: none; color: {TEXT_MUTED};"
        )

        self._inputs = _Input(row)
        self._inputs.setFrame(False)
        self._inputs.setPlaceholderText("Type code and press Enter")
        self._inputs.setStyleSheet(
            f"background: transparent; border: none; color: {TEXT};"
        )
        self._inputs.returnPressed.connect(self._run)

        font = QFont(self._output.font())
        self._prompt.setFont(font)
        self._inputs.setFont(font)

        line.addWidget(self._prompt)
        line.addWidget(self._inputs, 1)
        self._layout.addWidget(row)

    def _prompt_font_width(self) -> int:
        return max(6, self._output.fontMetrics().horizontalAdvance("0"))

    # -- mode ----------------------------------------------------------
    @property
    def mode(self) -> ConsoleMode:
        return self._mode

    @mode.setter
    def mode(self, value: ConsoleMode) -> None:
        if value is self._mode:
            return
        self._stop_shell()
        self._mode = value
        self._continuation = ""
        self._append(f"\n{value.value} session\n", muted=True)
        self._start_session()

    def _choose(self, mode: ConsoleMode) -> None:
        self.mode = mode
        self._sync_mode_buttons()

    def _sync_mode_buttons(self) -> None:
        for mode, button in self._mode_buttons.items():
            button.setChecked(mode is self._mode)

    # -- sessions ------------------------------------------------------
    def set_project(self, path: Path | None) -> None:
        """Run the console in the project (or the lone file's folder)."""
        self._project = path
        if path is not None:
            self._cwd = path
            text = str(path)
            if text and text not in sys.path:
                sys.path.insert(0, text)

        if self._mode is ConsoleMode.SHELL:
            self._restart_shell()

    def _start_session(self) -> None:
        self._sync_mode_buttons()
        if self._mode is ConsoleMode.PYTHON:
            self._set_prompt(">>> ")
            location = self._project or self._cwd
            self._append(
                f"Python {sys.version.split()[0]} \u00b7 {_short_path(location)}\n",
                muted=True,
            )
        else:
            self._set_prompt("$ ")
            self._start_shell()

        self._inputs.setFocus()

    def _set_prompt(self, text: str) -> None:
        self._prompt.setText(text)
        self._prompt.setFixedWidth(
            max(self._prompt_font_width() * len(text) + 6, TILE)
        )

    # -- python --------------------------------------------------------
    def _run(self) -> None:
        text = self._inputs.text()
        self._inputs.clear()

        if self._mode is ConsoleMode.PYTHON:
            self._run_python(text)
            return

        self._run_shell(text)

    def _run_python(self, text: str) -> None:
        if not text and not self._continuation:
            return

        source = self._continuation + text
        if not source.strip():
            self._continuation = ""
            self._set_prompt(">>> ")
            return

        # The prompt line is the echo: repeat what was entered, then the answer.
        self._append(f"{(self._prompt.text())}{text}\n", muted=False)

        try:
            code = codeop.compile_command(source, "<console>", "single")
        except (SyntaxError, ValueError, OverflowError) as error:
            self._continuation = ""
            self._set_prompt(">>> ")
            self._append(f"{error}\n", error=True)
            return

        if code is None:
            # An open block: keep collecting until the user enters a blank line.
            self._continuation = source + "\n"
            self._set_prompt("... ")
            return

        self._continuation = ""
        self._set_prompt(">>> ")

        writer = _Writer(self._append)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                exec(code, self._namespace)
        except SystemExit:
            self._append("\n(exit ignored)\n", muted=True)
        except BaseException:
            self._append(self._traceback(), error=True)

        self._history(text)

    @staticmethod
    def _traceback() -> str:
        """The user's traceback, without the console's own exec frame on top."""
        lines = traceback.format_exc().splitlines(keepends=True)
        for index, line in enumerate(lines):
            if __file__ not in line:
                continue

            # The frame is a "File ..." line plus the source line under it.
            end = index + 1
            if end < len(lines) and not lines[end].lstrip().startswith("File "):
                end += 1
            return "".join(lines[:index] + lines[end:])

        return "".join(lines)

    def _history(self, text: str) -> None:
        if text.strip() and (not self._inputs.history or self._inputs.history[-1] != text):
            self._inputs.history.append(text)
        self._inputs.index = len(self._inputs.history)
        self._inputs.draft = ""

    # -- shell ---------------------------------------------------------
    def _start_shell(self) -> None:
        self._shell = QProcess(self)
        self._shell.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._shell.setWorkingDirectory(str(self._cwd))
        self._shell.readyReadStandardOutput.connect(self._read_shell)
        self._shell.finished.connect(self._shell_finished)
        self._shell.start("bash", ["--noprofile", "--norc", "-s"])

        self._shell.write(f"cd {_quote(self._cwd)}\n".encode())
        self._append(f"bash \u00b7 {_short_path(self._cwd)}\n", muted=True)

    def _stop_shell(self) -> None:
        if self._shell is None:
            return
        shell, self._shell = self._shell, None
        try:
            shell.readyReadStandardOutput.disconnect(self._read_shell)
        except (RuntimeError, TypeError):
            pass
        if shell.state() is not QProcess.ProcessState.NotRunning:
            shell.kill()
            shell.waitForFinished(1000)

    def _restart_shell(self) -> None:
        self._stop_shell()
        self._start_shell()
        self._shell_busy = False
        self._set_prompt(self._shell_prompt())

    def _run_shell(self, text: str) -> None:
        if not text.strip():
            self._set_prompt(self._shell_prompt())
            return

        if self._shell is None or self._shell.state() is QProcess.ProcessState.NotRunning:
            self._start_shell()

        if self._shell_busy:
            self._append("a command is still running\n", muted=True)
            return

        self._append(f"{self._prompt.text()}{text}\n")
        self._history(text)

        self._shell_busy = True
        self._shell.write((text + "\n" + _DONE).encode())

    def _read_shell(self) -> None:
        if self._shell is None:
            return

        chunk = bytes(self._shell.readAllStandardOutput()).decode(errors="replace")
        self._shell_buffer += chunk

        while True:
            match = _MARKER.search(self._shell_buffer)
            if match is None:
                break

            before = self._shell_buffer[: match.start()]
            if before:
                # A command that printed without a final newline still ends the line.
                self._append(before if before.endswith("\n") else before + "\n")
            self._shell_buffer = self._shell_buffer[match.end() :]

            self._shell_busy = False
            location = match.group(2).strip()
            if location:
                self._cwd = Path(location)
            self._set_prompt(self._shell_prompt())

    def _shell_finished(self) -> None:
        self._shell_busy = False
        self._append("\nshell exited\n", muted=True)
        self._shell = None
        self._set_prompt("$ ")

    def _shell_prompt(self) -> str:
        return f"{_short_path(self._cwd)} $ "

    # -- programs ------------------------------------------------------
    def run_program(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        title: str = "",
        live: bool = False,
    ) -> bool:
        """Run a command here, in its own process, whatever mode the console is in.

        A live session holds a watcher open after the program ends, so it is replaced
        rather than refused when something else is asked for.
        """
        if not command:
            return False

        if self._program is not None:
            if self.running and not (live or self._program_live):
                self._append("a program is already running\n", muted=True)
                return False
            self._stop_program(stop_line="replaced")

        program = QProcess(self)
        program.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        program.setWorkingDirectory(str(cwd or self._cwd))
        program.readyReadStandardOutput.connect(self._read_program)
        program.finished.connect(lambda code, _status: self._program_finished(code))
        program.start(command[0], command[1:])

        if not program.waitForStarted(3000):
            self._append(f"could not start {command[0]}\n", error=True)
            program.deleteLater()
            return False

        if title:
            self._append(f"{title}\n", muted=True)
        shown = " ".join(shlex.quote(part) for part in command)
        self._append(f"$ {shown}\n")
        self._program = program
        self._program_live = live
        self._program_idle = False
        self._program_buffer = ""
        return True

    def _read_program(self) -> None:
        if self._program is None:
            return
        chunk = bytes(self._program.readAllStandardOutput()).decode(errors="replace")
        self._program_buffer += chunk
        self._drain_program_buffer()

    def _drain_program_buffer(self) -> None:
        """Show the output, and keep the control events for the rest of the window."""
        while True:
            start = self._program_buffer.find("\x01")
            if start < 0:
                if self._program_buffer:
                    self._append(self._program_buffer)
                    self._program_buffer = ""
                return

            if start > 0:
                self._append(self._program_buffer[:start])
                self._program_buffer = self._program_buffer[start:]

            match = _EVENT.match(self._program_buffer)
            if match is None:
                # A marker split between two reads, or an escape the program printed.
                if len(self._program_buffer) > 8192:
                    self._append(self._program_buffer)
                    self._program_buffer = ""
                return

            self._program_buffer = self._program_buffer[match.end() :]
            try:
                event = json.loads(match.group(1))
            except ValueError:
                continue
            self._live_event(event)

    def _live_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind != "idle":
            self._program_idle = False

        if kind == "line":
            self.live_line.emit(str(event.get("file", "")), int(event.get("line", 0)))
        elif kind == "reload":
            names = ", ".join(str(name) for name in event.get("files", []))
            self._append(f"\u21bb reloaded {names}\n", muted=True)
        elif kind == "error":
            self.live_error.emit(str(event.get("file", "")), int(event.get("line", 0)))
        elif kind == "invalid":
            name = event.get("file", "?")
            line = event.get("line", 0)
            message = event.get("message", "invalid syntax")
            self._append(
                f"\u2717 {name}:{line} {message} \u2014 still running the old code\n",
                error=True,
            )
        elif kind == "idle":
            if event.get("reloaded"):
                return  # the edit is about to run again: not the end of anything
            self._program_idle = True
            code = int(event.get("code", 0) or 0)
            # Report the status the way python reports it, then stay open for edits.
            self._append(
                f"[exit {code} \u00b7 edit a file to run it again]\n",
                muted=not code,
                error=bool(code),
            )
            self.live_idle.emit()

    def _stop_program(self, *, stop_line: str = "stopped") -> None:
        """End the running program (a live session keeps running otherwise)."""
        if self._program is None:
            return

        program, self._program = self._program, None
        self._stopping = True
        program.kill()
        program.waitForFinished(1000)
        self._stopping = False
        self._program_live = False
        self._program_idle = False
        program.deleteLater()
        self._append(f"[{stop_line}]\n", muted=True)
        self.live_stopped.emit()

    def _program_finished(self, code: int) -> None:
        if self._stopping:
            return  # killed by us, and already reported as such

        if self._program is not None:
            self._drain_program_buffer()
            self._program.deleteLater()
            self._program = None

        self._program_live = False
        self._program_idle = False
        self.live_stopped.emit()
        if code:
            self._append(f"[exit {code}]\n", error=True)
        else:
            self._append("[exit 0]\n", muted=True)

    @property
    def running(self) -> bool:
        """True while a program is actually going (a parked live session is not)."""
        return (
            self._program is not None
            and not self._program_idle
            and self._program.state() is not QProcess.ProcessState.NotRunning
        )

    def notice(self, text: str, *, error: bool = False) -> None:
        """Say something in the pane, without it looking like program output."""
        self._append(f"{text}\n", muted=not error, error=error)

    # -- output --------------------------------------------------------
    def _append(self, text: str, *, muted: bool = False, error: bool = False) -> None:
        if not text:
            return

        colour = CONSOLE_ERROR if error else (TEXT_MUTED if muted else TEXT)
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))

        cursor.insertText(text, fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def clear(self) -> None:
        self._output.clear()
        self._continuation = ""
        if self._mode is ConsoleMode.PYTHON:
            self._set_prompt(">>> ")
        else:
            self._set_prompt(self._shell_prompt())

    def shutdown(self) -> None:
        """Stop the shell and any running program so they do not outlive the window."""
        self._stop_shell()
        self._stop_program(stop_line="stopped")

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._inputs.setFocus()
