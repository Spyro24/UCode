"""Reading the links a source file declares: Python imports and C includes.

Only what the graph needs to connect files: the names a file pulls in, not full parsing.
"""

from __future__ import annotations

import re

_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)


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
            module = body.split(" import ")[0].strip()
            if module:
                # Relative imports point at the file's own package; keep the leaf name.
                names.append(module.lstrip(".").split(".")[-1])

    return names


def c_includes(text: str) -> list[str]:
    """Quoted include targets, which are the ones that can live in the project."""
    return _INCLUDE.findall(text)
