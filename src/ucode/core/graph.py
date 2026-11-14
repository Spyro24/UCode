"""The file graph: one node per file, grouped into the folder that holds it.

Everything is laid out automatically in tile units, which is why the canvas needs no
grid: positions are computed once from the project's structure, not dragged by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ucode.languages.imports import c_includes, python_imports

NODE_TILES = (6, 2)
ELBOW_TILES = (4, 4)  # unused by the layout, kept for port work later

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
    size: tuple[int, int] = NODE_TILES


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


def _read_links(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    return c_includes(text) if path.suffix in {".c", ".h"} else python_imports(text)


def _layout(
    files_by_folder: dict[str, list[str]], root_label: str
) -> tuple[list[Node], list[FolderBox]]:
    nodes: list[Node] = []
    boxes: list[FolderBox] = []

    cursor_x = 0
    row_y = 0
    row_height = 0
    in_row = 0

    for folder in sorted(files_by_folder):
        names = sorted(files_by_folder[folder])
        count = len(names)

        box_width = PADDING * 2 + NODE_TILES[0]
        box_height = HEADER + PADDING * 2 + count * NODE_TILES[1] + (count - 1) * GAP

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

        for index, name in enumerate(names):
            tile = (
                cursor_x + PADDING,
                row_y + HEADER + PADDING + index * (NODE_TILES[1] + GAP),
            )
            relative = f"{folder}/{name}" if folder else name
            nodes.append(
                Node(path=relative, label=name, folder=folder, tile=tile)
            )

        cursor_x += box_width + BOX_GAP
        row_height = max(row_height, box_height)
        in_row += 1

    return nodes, boxes


def _resolve(name: str, folder: str, by_stem: dict[str, list[Node]]) -> Node | None:
    candidates = by_stem.get(Path(name).stem)
    if not candidates:
        return None

    for candidate in candidates:
        if candidate.folder == folder:
            return candidate
    return candidates[0]


def build_file_graph(root: Path) -> FileGraph:
    """Scan ``root`` and lay its files out, grouped by folder."""
    files = _scan(root)

    files_by_folder: dict[str, list[str]] = {}
    for path in files:
        relative = path.relative_to(root)
        folder = relative.parent.as_posix()
        files_by_folder.setdefault("" if folder == "." else folder, []).append(
            path.name
        )

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

        for name in _read_links(path):
            target = _resolve(name, folder, by_stem)
            if target is None or target.path == source:
                continue
            key = (source, target.path)
            if key in seen:
                continue
            seen.add(key)
            edges.append(Edge(source=source, target=target.path))

    return FileGraph(root=root, nodes=nodes, folders=boxes, edges=edges)
