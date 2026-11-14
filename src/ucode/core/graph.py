"""The file graph: one node per file, grouped into the folder that holds it.

Every node is sized to the file it holds — as many lines as the file has — so nothing is
hidden behind a scrollbar. Positions are computed in tile units, which is why the canvas
needs no grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from ucode.core.tile import TILE
from ucode.languages.imports import c_includes, python_imports

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

SUFFIXES = {".py", ".c", ".h"}
SKIP_FOLDERS = {".git", ".venv", "__pycache__", "build", "dist", "node_modules", ".ucode"}


@dataclass(slots=True)
class Node:
    path: str  # relative to the project root, posix style
    label: str
    folder: str
    tile: tuple[int, int]
    size: tuple[int, int]
    rows: int = 0
    columns: int = 0


@dataclass(slots=True)
class FolderBox:
    folder: str
    label: str  # the project name for the root folder, the folder name otherwise
    tile: tuple[int, int]
    size: tuple[int, int]


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


def _layout(
    files_by_folder: dict[str, list[tuple[str, int, int]]], root_label: str
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

    return nodes, boxes


def _links(path: Path, text: str) -> list[str]:
    return c_includes(text) if path.suffix in {".c", ".h"} else python_imports(text)


def _resolve(name: str, folder: str, by_stem: dict[str, list[Node]]) -> Node | None:
    candidates = by_stem.get(Path(name).stem)
    if not candidates:
        return None

    for candidate in candidates:
        if candidate.folder == folder:
            return candidate
    return candidates[0]


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

    nodes, boxes = _layout(files_by_folder, root.name or root.as_posix())

    by_stem: dict[str, list[Node]] = {}
    for node in nodes:
        by_stem.setdefault(Path(node.path).stem, []).append(node)

    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    for path in files:
        relative = path.relative_to(root)
        folder = relative.parent.as_posix()
        folder = "" if folder == "." else folder
        source = f"{folder}/{path.name}" if folder else path.name

        for name in _links(path, texts[path]):
            target = _resolve(name, folder, by_stem)
            if target is None or target.path == source:
                continue
            key = (source, target.path)
            if key in seen:
                continue
            seen.add(key)
            edges.append(Edge(source=source, target=target.path))

    return FileGraph(root=root, nodes=nodes, folders=boxes, edges=edges)
