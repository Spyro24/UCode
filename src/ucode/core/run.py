"""What the Run menu executes, and how it is told to do it."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The files a project is usually started with, most specific first.
ENTRY_NAMES = (
    "__main__.py",
    "main.py",
    "app.py",
    "run.py",
    "src/__main__.py",
    "src/main.py",
)

# The tracer Debug (Live) runs the script under; it stands alone in its process.
LIVE = Path(__file__).with_name("live.py")


def entry_point(folder: Path | None) -> Path | None:
    """The file a project starts with, when there is an obvious one."""
    if folder is None or not folder.is_dir():
        return None

    for name in ENTRY_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate

    return None


def command(target: Path) -> list[str]:
    """How to run ``target`` in its own process; empty when it cannot be run."""
    if target.suffix == ".py":
        # -u keeps output unbuffered, so it appears as the program writes it.
        return [sys.executable, "-u", str(target)]

    if target.is_file() and os.access(target, os.X_OK):
        return [str(target)]

    return []


def debug_command(target: Path) -> list[str]:
    """How to run ``target`` under the live tracer; empty when that is not possible."""
    if target.suffix != ".py":
        return []

    return [sys.executable, "-u", str(LIVE), str(target)]
