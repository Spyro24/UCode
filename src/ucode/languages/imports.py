"""Reading the links a source file declares: Python imports and C includes.

Only what the graph needs: the names a file pulls in and the line they appear on, so an
edge can start and end on the exact line it belongs to.

Each reference is ``(name, line, member)``. ``name`` keeps its full dotted path, so every
import can become its own node; ``member`` is the symbol imported by a ``from`` statement,
or None for a whole-module import.
"""

from __future__ import annotations

import re

_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_SYSTEM_INCLUDE = re.compile(r"^\s*#\s*include\s+<([^>]+)>", re.MULTILINE)

Reference = tuple[str, int, "str | None"]


def python_imports(text: str) -> list[Reference]:
    """Module and member paths imported at any indent level, with their line."""
    names: list[Reference] = []

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if stripped.startswith("import "):
            for part in stripped[len("import ") :].split(","):
                module = part.split(" as ")[0].strip()
                if module:
                    names.append((module, number, None))

        elif stripped.startswith("from "):
            body = stripped[len("from ") :]
            module, _, imported = body.partition(" import ")
            module = module.strip()
            relative = module.startswith(".")
            base = module.lstrip(".")

            members = []
            for part in imported.strip("()").split(","):
                member = part.split(" as ")[0].strip()
                if member and member != "*":
                    members.append(member)

            if relative and not base:
                # ``from . import helpers`` pulls in sibling modules directly.
                for member in members:
                    names.append((member, number, None))
            elif not members:
                if base:
                    names.append((base, number, None))
            else:
                for member in members:
                    names.append((f"{base}.{member}" if base else member, number, member))

    return names


def _with_lines(pattern: re.Pattern[str], text: str) -> list[Reference]:
    return [
        (match.group(1), text.count("\n", 0, match.start()) + 1, None)
        for match in pattern.finditer(text)
    ]


def c_includes(text: str) -> list[Reference]:
    """Quoted include targets, which are the ones that can live in the project."""
    return _with_lines(_INCLUDE, text)


def c_system_includes(text: str) -> list[Reference]:
    """Angle-bracket includes: the toolchain's headers, never project files."""
    return _with_lines(_SYSTEM_INCLUDE, text)
