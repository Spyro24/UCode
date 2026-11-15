"""Run a script and print every line it executes, as it happens.

Debug (Live) starts this in its own process: ``python3 live.py script.py [args...]``.
It uses only the standard library and never imports the rest of UCode.
"""

from __future__ import annotations

import linecache
import runpy
import sys
import time
import traceback
from pathlib import Path


class Live:
    """A tracer that narrates the script's own code, not the libraries around it."""

    def __init__(self, script: Path) -> None:
        self.script = script
        self.root = script.parent
        self.started = time.monotonic()
        self.lines = 0
        # (error, file, line, locals) taken while the frames still held them: after the
        # stack unwinds Python clears the frames, so they cannot be read at report time.
        self.snapshots: list[tuple[BaseException, str, int, dict]] = []

    def wanted(self, filename: str) -> bool:
        """True for files of the project being debugged."""
        if not filename.endswith(".py"):
            return False

        path = Path(filename)
        if path == self.script:
            return True
        return self.root in path.parents

    def trace(self, frame, event, arg):
        """Keep tracing only the project's frames; anything else stays silent."""
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

        depth = 0
        outer = frame.f_back
        while outer is not None and self.wanted(outer.f_code.co_filename):
            depth += 1
            outer = outer.f_back

        text = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
        print(f"{'  ' * min(depth, 8)}{frame.f_lineno:>5} | {text}", flush=True)

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
            (entry for entry in self.snapshots if entry[0] is error),
            None,
        )
        if snapshot is None:
            return

        _error, filename, line, local = snapshot
        pairs = ", ".join(
            f"{name}={value!r}"
            for name, value in sorted(local.items())
            if not name.startswith("__")
        )
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

    live = Live(script)
    status = 0
    sys.settrace(live.trace)
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as stop:
        code = stop.code
        status = 0 if code is None else (code if isinstance(code, int) else 1)
    except BaseException as error:  # noqa: BLE001 - report whatever the script raised
        status = 1
        live.report(error)
    finally:
        sys.settrace(None)

    elapsed = time.monotonic() - live.started
    print(f"[debug] {live.lines} lines · {elapsed:.2f}s", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
