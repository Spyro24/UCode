"""The file graph: one node per file, grouped into the folder that holds it.

Every node is sized to the file it holds — as many lines as the file has — so nothing is
hidden behind a scrollbar. Every import that does not resolve to a project file becomes
its own node, filed under its package.

Edges carry the line they start from and the line they point at, so the canvas can attach
them to the exact statement: an import line to the definition it uses, and the line that
builds an object to the class it builds.

Positions are computed in tile units, which is why the canvas needs no grid.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from ucode.core.tile import TILE
from ucode.languages.imports import c_includes, c_system_includes, python_imports

# Approximate monospace metrics at the editor's base size, used to measure nodes without
# creating a widget for every file first.
CHAR_PX = 7  # measured advance at the base size is 6.61, so this is safe
LINE_PX = 13  # measured line spacing at the base size is 12.80, plus a little slack
HEADER_PX = TILE
EDITOR_PAD_PX = 14
MIN_NODE_PX = (140, 96)  # a floor for nearly-empty files, not a target size
MAX_COLUMNS = 300  # longer lines scroll horizontally rather than growing the node forever

PADDING = 0.5  # tiles between a folder box edge and the nodes inside it
HEADER = 1  # tiles reserved for the folder's name
GAP = 0.75  # tiles between nodes in the same folder
BOX_GAP = 2  # tiles between folder boxes
BOXES_PER_ROW = 4

CHIP_TILES = 1  # height of an import node
CHIP_GAP = 0.5  # tiles between import nodes, tighter than files

EXTERN_FOLDER = "~extern"
SYSTEM_LABEL = "system headers"  # group for <...> includes

FILE_SUFFIXES = {".py", ".c", ".h"}

SUFFIXES = FILE_SUFFIXES
SKIP_FOLDERS = {".git", ".venv", "__pycache__", "build", "dist", "node_modules", ".ucode"}

_CLASS_DEF = re.compile(r"^[ \t]*class\s+([A-Za-z_]\w*)", re.MULTILINE)


@dataclass(slots=True)
class Node:
    path: str  # relative to the project root, posix style
    label: str
    folder: str
    tile: tuple[float, float]
    size: tuple[float, float]
    rows: int = 0
    columns: int = 0
    kind: str = "file"  # "file" for editable files, "import" for external dependencies


@dataclass(slots=True)
class FolderBox:
    folder: str
    label: str  # the project name for the root folder, the folder name otherwise
    tile: tuple[float, float]
    size: tuple[float, float]


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    source_line: int = 1  # the line the link leaves from
    target_line: int = 1  # the line it points at
    label: str = ""  # e.g. "Engine()" for a created object
    kind: str = "import"  # "import" or "creates"


@dataclass(slots=True)
class FileGraph:
    root: Path | None = None
    nodes: list[Node] = field(default_factory=list)
    folders: list[FolderBox] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def by_path(self) -> dict[str, Node]:
        return {node.path: node for node in self.nodes}

    def apply_positions(self, positions: dict[str, tuple[float, float]]) -> None:
        """Put nodes back where the user dragged them last time."""
        for node in self.nodes:
            tile = positions.get(node.path)
            if tile is not None:
                node.tile = tile


def _scan(root: Path) -> list[Path]:
    found: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") or part in SKIP_FOLDERS for part in relative.parts):
            continue
        found.append(path)

    return sorted(found)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _measure(text: str) -> tuple[int, int]:
    """Rows and display columns, so the node can be sized to its content.

    Split on newlines rather than ``splitlines``: a trailing newline opens a final empty
    block in the editor, and leaving that row out gave the node a scrollbar.
    """
    lines = text.split("\n") or [""]
    rows = max(1, len(lines))
    columns = max((len(line.expandtabs(4)) for line in lines), default=1)
    return rows, min(MAX_COLUMNS, max(1, columns))


def node_size(rows: int, columns: int) -> tuple[float, float]:
    """Exact size that holds the whole file: the box ends just past its last character.

    Sizes are fractional tiles on purpose. Rounding up to whole tiles used to leave up to
    a tile of empty space on the right of every node.
    """
    digits = len(str(max(1, rows)))
    gutter_px = (digits + 1) * CHAR_PX
    width_px = max(MIN_NODE_PX[0], columns * CHAR_PX + 34 + gutter_px)
    height_px = max(MIN_NODE_PX[1], HEADER_PX + rows * LINE_PX + EDITOR_PAD_PX)

    return (width_px / TILE, height_px / TILE)


def box_width(nodes_width: float, label: str) -> float:
    """A group box wide enough for its widest node and for its own name."""
    label_px = len(label) * 9 + 24  # bold header text, measured generously
    return max(nodes_width + PADDING * 2, label_px / TILE)


def import_size(label: str) -> tuple[float, float]:
    """A chip just wide enough for the dependency's name."""
    width_px = max(TILE, len(label) * CHAR_PX + 28)
    return (width_px / TILE, CHIP_TILES)


def _layout(
    files_by_folder: dict[str, list[tuple[str, int, int]]],
    root_label: str,
    extern: dict[str, list[str]],
) -> tuple[list[Node], list[FolderBox]]:
    """Stack each folder's nodes, then place the boxes left to right."""
    nodes: list[Node] = []
    boxes: list[FolderBox] = []

    cursor_x = 0
    row_y = 0
    row_height = 0
    in_row = 0

    for folder in sorted(files_by_folder):
        entries = sorted(files_by_folder[folder])
        # Each node keeps its own width, so a short file is not stretched to the width of
        # the longest one beside it.
        sizes = [node_size(rows, columns) for _, rows, columns in entries]

        width = box_width(max(size[0] for size in sizes), root_label if folder == "" else folder)
        box_height = (
            HEADER
            + PADDING * 2
            + sum(size[1] for size in sizes)
            + GAP * (len(entries) - 1)
        )

        if in_row == BOXES_PER_ROW:
            cursor_x = 0
            row_y += row_height + BOX_GAP
            row_height = 0
            in_row = 0

        boxes.append(
            FolderBox(
                folder=folder,
                label=root_label if folder == "" else folder,
                tile=(cursor_x, row_y),
                size=(width, box_height),
            )
        )

        y = row_y + HEADER + PADDING
        for (name, rows, columns), size in zip(entries, sizes):
            relative = f"{folder}/{name}" if folder else name
            nodes.append(
                Node(
                    path=relative,
                    label=name,
                    folder=folder,
                    tile=(cursor_x + PADDING, y),
                    size=size,
                    rows=rows,
                    columns=columns,
                )
            )
            y += size[1] + GAP

        cursor_x += width + BOX_GAP
        row_height = max(row_height, box_height)
        in_row += 1

    # One group per imported package, each holding a node per imported path.
    for package in sorted(extern):
        names = sorted(extern[package])
        if not names:
            continue

        if in_row == BOXES_PER_ROW:
            cursor_x = 0
            row_y += row_height + BOX_GAP
            row_height = 0
            in_row = 0

        sizes = [import_size(name) for name in names]
        label = package or SYSTEM_LABEL
        width = box_width(max(size[0] for size in sizes), label)
        box_height = (
            HEADER
            + PADDING * 2
            + len(names) * CHIP_TILES
            + CHIP_GAP * (len(names) - 1)
        )

        folder = f"{EXTERN_FOLDER}/{package}" if package else EXTERN_FOLDER
        boxes.append(
            FolderBox(
                folder=folder,
                label=label,
                tile=(cursor_x, row_y),
                size=(width, box_height),
            )
        )

        y = row_y + HEADER + PADDING
        for index, name in enumerate(names):
            nodes.append(
                Node(
                    path=f"{EXTERN_FOLDER}/{name}",
                    label=name,
                    folder=folder,
                    tile=(cursor_x + PADDING, y),
                    size=sizes[index],
                    rows=1,
                    columns=len(name),
                    kind="import",
                )
            )
            y += CHIP_TILES + CHIP_GAP

        cursor_x += width + BOX_GAP
        row_height = max(row_height, box_height)
        in_row += 1

    return nodes, boxes


def _references(
    path: Path, text: str
) -> tuple[list[tuple[str, int, str | None]], list[tuple[str, int, str | None]]]:
    """(names that may be a project file, names that are always external)."""
    if path.suffix in {".c", ".h"}:
        return c_includes(text), c_system_includes(text)
    return python_imports(text), []


def _definition_line(text: str, member: str) -> int:
    """The first line that defines ``member``, so an edge can point at it."""
    pattern = re.compile(
        rf"^[ \t]*(?:(?:async\s+)?def|class)\s+{re.escape(member)}\b"
        rf"|^[ \t]*{re.escape(member)}\s*=",
        re.MULTILINE,
    )
    match = pattern.search(text)

    return text.count("\n", 0, match.start()) + 1 if match else 1


def _classes(text: str) -> list[tuple[str, int]]:
    return [
        (match.group(1), text.count("\n", 0, match.start()) + 1)
        for match in _CLASS_DEF.finditer(text)
    ]


def _creations(text: str, name: str) -> list[int]:
    """Lines that call ``name(...)``, which is what builds an object of it."""
    pattern = re.compile(rf"\b{re.escape(name)}\s*\(")
    lines: list[int] = []

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ", "class ", "def ", "async def ")):
            continue
        if pattern.search(line):
            lines.append(number)

    return lines


class _Lookup:
    """Maps an imported name to a project file path, when one exists."""

    def __init__(self, paths: list[str]) -> None:
        self.known = set(paths)
        self.by_stem: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}

        for path in paths:
            self.by_stem.setdefault(Path(path).stem, []).append(path)
            self.by_name.setdefault(Path(path).name, []).append(path)

    @staticmethod
    def folder_of(path: str) -> str:
        parent = Path(path).parent.as_posix()
        return "" if parent == "." else parent

    def resolve(self, name: str, folder: str) -> str | None:
        if Path(name).suffix in FILE_SUFFIXES:
            return self._resolve_file(name, folder)
        return self._resolve_module(name, folder)

    def _resolve_file(self, name: str, folder: str) -> str | None:
        # An include: match the path, not just the stem, so ``native.h`` does not
        # collapse onto ``native.c``.
        candidates = self.by_name.get(Path(name).name, [])
        wanted = name.lstrip("./")

        for candidate in candidates:
            if candidate == wanted or candidate.endswith("/" + wanted):
                return candidate
        for candidate in candidates:
            if self.folder_of(candidate) == folder:
                return candidate
        return candidates[0] if candidates else None

    def _resolve_module(self, name: str, folder: str) -> str | None:
        # ``from a.b import c`` names ``a.b.c``; the module is either that path or
        # its parent, so try both ends of the dotted name.
        probes = [name]
        if "." in name:
            probes.append(name.rsplit(".", 1)[0])

        for probe in probes:
            candidates = self.by_stem.get(probe.rsplit(".", 1)[-1])
            if candidates:
                for candidate in candidates:
                    if self.folder_of(candidate) == folder:
                        return candidate
                return candidates[0]

        # A package import: the module is a folder, so its __init__ is the target.
        for probe in probes:
            candidate = f"{probe.replace('.', '/')}/__init__.py"
            if candidate in self.known:
                return candidate

        return None


def _add_edge(
    edges: list[Edge],
    seen: set[tuple[str, str, int, int, str]],
    source: str,
    target: str,
    source_line: int,
    target_line: int,
    label: str = "",
    kind: str = "import",
) -> None:
    if target == source:
        return

    key = (source, target, source_line, target_line, kind)
    if key in seen:
        return

    seen.add(key)
    edges.append(Edge(source, target, source_line, target_line, label, kind))


def build_file_graph(root: Path) -> FileGraph:
    """Scan ``root``, size every file, and lay the graph out by folder."""
    files = _scan(root)

    files_by_folder: dict[str, list[tuple[str, int, int]]] = {}
    texts: dict[Path, str] = {}
    text_by_path: dict[str, str] = {}

    for path in files:
        text = _read(path)
        texts[path] = text
        text_by_path[path.relative_to(root).as_posix()] = text
        rows, columns = _measure(text)

        relative = path.relative_to(root)
        folder = relative.parent.as_posix()
        folder = "" if folder == "." else folder
        files_by_folder.setdefault(folder, []).append((path.name, rows, columns))

    references = {path: _references(path, texts[path]) for path in files}

    lookup = _Lookup(
        [
            f"{folder}/{name}" if folder else name
            for folder, entries in files_by_folder.items()
            for name, _, _ in entries
        ]
    )

    # Every import that cannot become an edge between two files becomes a node,
    # filed under its package.
    extern: dict[str, set[str]] = {}

    def add_extern(name: str, system: bool) -> None:
        package = "" if system else name.split(".")[0]
        extern.setdefault(package, set()).add(name)

    for candidate_names, system_names in references.values():
        for name, _, _ in system_names:
            add_extern(name, system=True)
        for name, _, _ in candidate_names:
            if lookup.resolve(name, "") is None:
                add_extern(name, system=False)

    nodes, boxes = _layout(
        files_by_folder,
        root.name or root.as_posix(),
        {package: sorted(names) for package, names in extern.items()},
    )

    edges: list[Edge] = []
    seen: set[tuple[str, str, int, int, str]] = set()

    for path in files:
        relative = path.relative_to(root)
        folder = relative.parent.as_posix()
        folder = "" if folder == "." else folder
        source = f"{folder}/{path.name}" if folder else path.name
        source_text = texts[path]

        candidate_names, system_names = references[path]
        imported: dict[str, None] = {}

        for name, line, member in candidate_names:
            target = lookup.resolve(name, folder)

            if target is None:
                _add_edge(edges, seen, source, f"{EXTERN_FOLDER}/{name}", line, 1)
                continue

            imported[target] = None
            target_line = (
                _definition_line(text_by_path.get(target, ""), member) if member else 1
            )
            _add_edge(edges, seen, source, target, line, target_line)

        for name, line, _member in system_names:
            _add_edge(edges, seen, source, f"{EXTERN_FOLDER}/{name}", line, 1)

        # Objects built from a module this file imports.
        for target in imported:
            for class_name, class_line in _classes(text_by_path.get(target, "")):
                for create_line in _creations(source_text, class_name):
                    _add_edge(
                        edges,
                        seen,
                        source,
                        target,
                        create_line,
                        class_line,
                        f"{class_name}()",
                        "creates",
                    )

    return FileGraph(root=root, nodes=nodes, folders=boxes, edges=edges)
