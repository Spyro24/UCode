"""Run a script under a live tracer that reloads it while it is being edited.

Debug (Live) starts this in its own process: ``python3 live.py script.py [args...]``.
It uses only the standard library and never imports the rest of UCode.

Control events go to stdout wrapped in ``\\x01UCODE{json}\\x01`` markers, which the
console strips out; everything else on stdout is the program's own output.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import threading
import time
import traceback
from pathlib import Path

# Directories that never hold the code being debugged.
SKIP_DIRS = {
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "build",
    "dist",
    ".git",
}

POLL = 0.25


class Channel:
    """Writes control events to stdout, whole, even from the watcher thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def send(self, **event) -> None:
        with self._lock:
            sys.stdout.write("\x01UCODE" + json.dumps(event) + "\x01")
            sys.stdout.flush()


class Reload(Exception):
    """Raised inside the running code to stop it for a reload."""


class Watcher(threading.Thread):
    """Watch the project's Python files and ask for a reload when one is edited.

    An edit only counts when the file still compiles: a half-typed line leaves the
    running program alone, exactly as if nothing had happened.
    """

    def __init__(self, script: Path, channel: Channel) -> None:
        super().__init__(daemon=True)
        # The script itself is watched even when it is not called *.py.
        self.script = script
        self.folder = script.parent
        self.channel = channel
        self.reload = False
        self.stopped = False
        self.files = self._scan()

    def _scan(self) -> dict[Path, float]:
        found: dict[Path, float] = {}
        for root, directories, names in os.walk(self.folder):
            directories[:] = [
                name
                for name in directories
                if name not in SKIP_DIRS and not name.startswith(".")
            ]
            for name in names:
                path = Path(root) / name
                if not name.endswith(".py") and path != self.script:
                    continue
                try:
                    found[path] = path.stat().st_mtime
                except OSError:
                    continue

        try:
            found[self.script] = self.script.stat().st_mtime
        except OSError:
            pass
        return found

    def run(self) -> None:
        while not self.stopped:
            time.sleep(POLL)
            snapshot = self._scan()
            touched = [
                path
                for path, mtime in snapshot.items()
                if path in self.files and self.files[path] != mtime
            ]
            self.files = snapshot

            if not touched or self.reload:
                continue
            if self._accept(touched):
                self.reload = True
                self.channel.send(
                    event="reload", files=[path.name for path in touched]
                )

    def _accept(self, touched: list[Path]) -> bool:
        """True when every edited file compiles, so a reload can happen."""
        for path in touched:
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue

            try:
                compile(source, str(path), "exec")
            except SyntaxError as error:
                self.channel.send(
                    event="invalid",
                    file=path.name,
                    line=error.lineno or 0,
                    message=error.msg or "invalid syntax",
                )
                return False

        return True

    def consume(self) -> None:
        """Forget the pending edit: the program is about to run again."""
        self.reload = False

    def wait(self) -> bool:
        """Block until an edit asks for a reload; False when the watcher stops."""
        while not self.reload and not self.stopped:
            time.sleep(0.05)
        return self.reload


class Live:
    """A tracer that narrates the script's own code and stops it for a reload."""

    def __init__(self, script: Path, watcher: Watcher, channel: Channel) -> None:
        self.script = script
        self.root = script.parent
        self.watcher = watcher
        self.channel = channel
        self.lines = 0
        self.last: tuple[str, int] | None = None
        self.sent = 0.0
        # (error, file, line, locals) taken while the frames still held them: after the
        # stack unwinds Python clears the frames, so they cannot be read at report time.
        self.snapshots: list[tuple[BaseException, str, int, dict]] = []

    def wanted(self, filename: str) -> bool:
        """True for files of the project being debugged."""
        path = Path(filename)
        if path == self.script:
            return True
        if not filename.endswith(".py"):
            return False
        return self.root in path.parents

    def trace(self, frame, event, arg):
        """Keep tracing only the project's frames; anything else stays silent."""
        if self.watcher.reload:
            # Hand control back to the loop between two lines: the only safe moment.
            self.watcher.consume()
            raise Reload

        if not self.wanted(frame.f_code.co_filename):
            return None

        if event == "line":
            self.line(frame)
        elif event == "exception":
            error = arg[1]
            self.snapshots.append(
                (
                    error,
                    frame.f_code.co_filename,
                    frame.f_lineno,
                    dict(frame.f_locals),
                )
            )

        return self.trace

    def line(self, frame) -> None:
        self.lines += 1

        # A loop hits the same lines again and again: only a move is worth a message,
        # and only a handful per second: the mark is read by eye, not by a machine.
        position = (frame.f_code.co_filename, frame.f_lineno)
        now = time.monotonic()
        if position == self.last or now - self.sent < 0.08:
            return
        self.last = position
        self.sent = now

        self.channel.send(
            event="line", file=position[0], line=position[1]
        )

    def report(self, error: BaseException) -> None:
        """Say where it broke and what the variables held there."""
        print(f"!! {type(error).__name__}: {error}", flush=True)

        frames = [
            summary
            for summary in traceback.extract_tb(error.__traceback__)
            if self.wanted(summary.filename)
        ]
        for summary in frames:
            name = Path(summary.filename).name
            print(f"   at {name}:{summary.lineno} in {summary.name}()", flush=True)

        # The deepest snapshot of this very error is the frame that raised it.
        snapshot = next(
            (entry for entry in self.snapshots if entry[0] is error), None
        )
        if snapshot is None:
            return

        _error, filename, line, local = snapshot
        pairs = ", ".join(
            f"{name}={value!r}"
            for name, value in sorted(local.items())
            if not name.startswith("__")
        )
        self.channel.send(event="error", file=filename, line=line)
        if pairs:
            print(f"   locals: {pairs}", flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: live.py script.py [args...]", file=sys.stderr)
        return 2

    script = Path(sys.argv[1]).resolve()
    if not script.is_file():
        print(f"live.py: {script} not found", file=sys.stderr)
        return 2

    arguments = sys.argv[2:]
    sys.argv = [str(script), *arguments]
    sys.path.insert(0, str(script.parent))

    channel = Channel()
    watcher = Watcher(script, channel)
    watcher.start()
    live = Live(script, watcher, channel)

    status = 0
    while True:
        channel.send(event="start")
        interrupted = False
        status = 0

        sys.settrace(live.trace)
        try:
            runpy.run_path(str(script), run_name="__main__")
        except Reload:
            interrupted = True
        except SystemExit as stop:
            code = stop.code
            status = 0 if code is None else (code if isinstance(code, int) else 1)
        except BaseException as error:  # noqa: BLE001 - report whatever the script raised
            status = 1
            live.report(error)
        finally:
            sys.settrace(None)

        channel.send(
            event="idle", code=status, lines=live.lines, reloaded=interrupted
        )
        if interrupted:
            continue

        if not watcher.wait():
            break
        watcher.consume()

    return status


if __name__ == "__main__":
    raise SystemExit(main())
