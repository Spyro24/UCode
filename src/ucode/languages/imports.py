"""Reading the links a source file declares: Python imports and C includes.

Only what the graph needs to connect files: the names a file pulls in, not full parsing.
"""

from __future__ import annotations

import re

_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)
_SYSTEM_INCLUDE = re.compile(r"^\s*#\s*include\s+<([^>]+)>", re.MULTILINE)


def python_imports(text: str) -> list[str]:
    """Module names imported at any indent level."""
    names: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            for part in stripped[len("import ") :].split(","):
                module = part.split(" as ")[0].strip()
                if module:
                    names.append(module.split(".")[0])
        elif stripped.startswith("from "):
            body = stripped[len("from ") :]
            module, _, imported = body.partition(" import ")
            module = module.strip()

            if not module.lstrip("."):
                # ``from . import helpers`` pulls in modules, not a module member.
                for part in imported.strip("()").split(","):
                    name = part.split(" as ")[0].strip()
                    if name and name != "*":
                        names.append(name)
            elif module:
                # Relative imports point at the file's own package; keep the leaf name.
                names.append(module.lstrip(".").split(".")[-1])

    return names


def c_includes(text: str) -> list[str]:
    """Quoted include targets, which are the ones that can live in the project."""
    return _INCLUDE.findall(text)


def c_system_includes(text: str) -> list[str]:
    """Angle-bracket includes: the toolchain's headers, never project files."""
    return _SYSTEM_INCLUDE.findall(text)
