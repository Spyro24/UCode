"""Reading the links a source file declares: Python imports and C includes.

Only what the graph needs to connect files: the names a file pulls in, not full parsing.
Python references keep their full dotted path (``pygame.mouse.get_pos``), so each import
can become its own node.
"""

from __future__ import annotations

import re

_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_SYSTEM_INCLUDE = re.compile(r"^\s*#\s*include\s+<([^>]+)>", re.MULTILINE)


def python_imports(text: str) -> list[str]:
    """Module and member paths imported at any indent level."""
    names: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("import "):
            for part in stripped[len("import ") :].split(","):
                module = part.split(" as ")[0].strip()
                if module:
                    names.append(module)

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
                names.extend(members)
            elif not members:
                if base:
                    names.append(base)
            else:
                for member in members:
                    names.append(f"{base}.{member}" if base else member)

    return names


def c_includes(text: str) -> list[str]:
    """Quoted include targets, which are the ones that can live in the project."""
    return _INCLUDE.findall(text)


def c_system_includes(text: str) -> list[str]:
    """Angle-bracket includes: the toolchain's headers, never project files."""
    return _SYSTEM_INCLUDE.findall(text)
