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


# A file this large is not a script anyone is editing here; do not read it to find out.
SNIFF_LIMIT = 4 * 1024 * 1024


def is_python(target: Path) -> bool:
    """True when ``target`` holds code Python accepts, whatever the file is called."""
    if target.suffix == ".py":
        return True

    try:
        if target.stat().st_size > SNIFF_LIMIT:
            return False
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    try:
        compile(source, str(target), "exec")
    except (SyntaxError, ValueError):
        return False

    return True


def command(target: Path) -> list[str]:
    """How to run ``target`` in its own process; empty when it cannot be run."""
    if is_python(target):
        # -u keeps output unbuffered, so it appears as the program writes it.
        return [sys.executable, "-u", str(target)]

    if target.is_file() and os.access(target, os.X_OK):
        return [str(target)]

    return []


def debug_command(target: Path, root: Path | None = None) -> list[str]:
    """How to run ``target`` under the live tracer; empty when that is not possible.

    ``root`` is the project the files belong to: modules imported from another folder
    inside it must reload too, not just the ones beside the script.
    """
    if not is_python(target):
        return []

    command = [sys.executable, "-u", str(LIVE), str(target)]
    if root is not None:
        # The tracer starts in the script's folder, so a relative root would resolve
        # against the wrong place: it has to be absolute before it is handed over.
        try:
            command += ["--root", str(root.resolve())]
        except OSError:
            pass
    return command
