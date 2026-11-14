"""The file graph: one node per file, grouped into the folder that holds it.

Every node is sized to the file it holds — as many lines as the file has — so nothing is
hidden behind a scrollbar. Imports that do not resolve to a file in the project become
their own chip nodes, collected in a last "imports" group.

Positions are computed in tile units, which is why the canvas needs no grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from ucode.core.tile import TILE
from ucode.languages.imports import c_includes, c_system_includes, python_imports

# Approximate monospace metrics at the editor's base size, used to measure nodes without
# creating a widget for every file first.
CHAR_PX = 7  # measured advance at the base size is 6.61, so this is safe
LINE_PX = 15  # measured line spacing at the base size is 12.80, plus slack
HEADER_PX = TILE
EDITOR_PAD_PX = 14
MIN_NODE_PX = (240, 128)
MAX_COLUMNS = 300  # longer lines scroll horizontally rather than growing the node forever

PADDING = 1  # tiles between a folder box edge and the nodes inside it
HEADER = 1  # tiles reserved for the folder's name
GAP = 1  # tiles between nodes in the same folder
BOX_GAP = 3  # tiles between folder boxes
BOXES_PER_ROW = 4

CHIP_TILES = 1  # height of an import node
CHIP_GAP = 0.5  # tiles between import nodes, tighter than files

EXTERN_FOLDER = "~extern"
EXTERN_LABEL = "imports"

SUFFIXES = {".py", ".c", ".h"}
SKIP_FOLDERS = {".git", ".venv", "__pycache__", "build", "dist", "node_modules", ".ucode"}


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


@dataclass(slots=True)
class FileGraph:
    root: Path | None = None
    nodes: list[Node] = field(default_factory=list)
    folders: list[FolderBox] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def by_path(self) -> dict[str, Node]:
        return {node.path: node for node in self.nodes}


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
    """Rows and display columns, so the node can be sized to its content."""
    lines = text.splitlines() or [""]
    rows = max(1, len(lines))
    columns = max((len(line.expandtabs(4)) for line in lines), default=1)
    return rows, min(MAX_COLUMNS, max(1, columns))


def node_size(rows: int, columns: int) -> tuple[int, int]:
    """Tile size that holds the whole file at the base font size."""
    width_px = max(MIN_NODE_PX[0], columns * CHAR_PX + 34)
    height_px = max(MIN_NODE_PX[1], HEADER_PX + rows * LINE_PX + EDITOR_PAD_PX)

    return (
        math.ceil(width_px / TILE),
        math.ceil(height_px / TILE),
    )


def import_size(label: str) -> tuple[int, int]:
    """A chip just wide enough for the dependency's name."""
    width_px = len(label) * CHAR_PX + 28
    return (max(2, math.ceil(width_px / TILE)), CHIP_TILES)


def _layout(
    files_by_folder: dict[str, list[tuple[str, int, int]]],
    root_label: str,
    extern_names: list[str],
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
        measured = [node_size(rows, columns) for _, rows, columns in entries]

        # One column width per folder, so the nodes inside it line up.
        column_width = max(size[0] for size in measured)
        sizes = [(column_width, size[1]) for size in measured]

        box_width = PADDING * 2 + column_width
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
                size=(box_width, box_height),
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

        cursor_x += box_width + BOX_GAP
        row_height = max(row_height, box_height)
        in_row += 1

    if extern_names:
        if in_row == BOXES_PER_ROW:
            cursor_x = 0
            row_y += row_height + BOX_GAP
            in_row = 0

        widths = [import_size(name)[0] for name in extern_names]
        column_width = max(widths)
        box_width = PADDING * 2 + column_width
        box_height = (
            HEADER
            + PADDING * 2
            + len(extern_names) * CHIP_TILES
            + CHIP_GAP * (len(extern_names) - 1)
        )

        boxes.append(
            FolderBox(
                folder=EXTERN_FOLDER,
                label=EXTERN_LABEL,
                tile=(cursor_x, row_y),
                size=(box_width, math.ceil(box_height)),
            )
        )

        y = row_y + HEADER + PADDING
        for name in extern_names:
            nodes.append(
                Node(
                    path=f"{EXTERN_FOLDER}/{name}",
                    label=name,
                    folder=EXTERN_FOLDER,
                    tile=(cursor_x + PADDING, y),
                    size=(column_width, CHIP_TILES),
                    rows=1,
                    columns=len(name),
                    kind="import",
                )
            )
            y += CHIP_TILES + CHIP_GAP

    return nodes, boxes


def _references(path: Path, text: str) -> tuple[list[str], list[str]]:
    """(names that may be a project file, names that are always external)."""
    if path.suffix in {".c", ".h"}:
        return c_includes(text), c_system_includes(text)
    return python_imports(text), []


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
        reference = Path(name)

        if reference.suffix:
            # A full file name (an include): match the path, not just the stem, so
            # ``native.h`` does not collapse onto ``native.c``.
            candidates = self.by_name.get(reference.name, [])
            wanted = name.lstrip("./")
            for candidate in candidates:
                if candidate == wanted or candidate.endswith("/" + wanted):
                    return candidate
            for candidate in candidates:
                if self.folder_of(candidate) == folder:
                    return candidate
            return candidates[0] if candidates else None

        candidates = self.by_stem.get(name)
        if candidates:
            for candidate in candidates:
                if self.folder_of(candidate) == folder:
                    return candidate
            return candidates[0]

        # A package import: the module is a folder, so its __init__ is the target.
        for candidate in (f"{name}/__init__.py", f"{folder}/{name}/__init__.py"):
            if candidate in self.known:
                return candidate

        return None


def build_file_graph(root: Path) -> FileGraph:
    """Scan ``root``, size every file, and lay the graph out by folder."""
    files = _scan(root)

    files_by_folder: dict[str, list[tuple[str, int, int]]] = {}
    texts: dict[Path, str] = {}

    for path in files:
        text = _read(path)
        texts[path] = text
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

    # Anything that cannot become an edge between two files becomes an import chip.
    extern: set[str] = set()
    for candidate_names, system_names in references.values():
        extern.update(system_names)
        extern.update(
            name for name in candidate_names if lookup.resolve(name, "") is None
        )

    extern_names = sorted(extern)
    nodes, boxes = _layout(files_by_folder, root.name or root.as_posix(), extern_names)

    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    for path in files:
        relative = path.relative_to(root)
        folder = relative.parent.as_posix()
        folder = "" if folder == "." else folder
        source = f"{folder}/{path.name}" if folder else path.name

        candidate_names, system_names = references[path]

        for name in candidate_names + system_names:
            target_path = lookup.resolve(name, folder) or f"{EXTERN_FOLDER}/{name}"

            if target_path == source:
                continue
            key = (source, target_path)
            if key in seen:
                continue
            seen.add(key)
            edges.append(Edge(source=source, target=target_path))

    return FileGraph(root=root, nodes=nodes, folders=boxes, edges=edges)
