"""The infinite workspace: pans and zooms, and holds the file graph."""

from __future__ import annotations

import time
from math import hypot
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QClipboard,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPixmap,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from ucode.core.graph import (
    BOX_GAP,
    GAP,
    HEADER,
    PADDING,
    FileGraph,
    folder_size,
    node_size,
)
from ucode.core.routing import crosses, route
from ucode.core.tile import TILE
from ucode.core.viewport import MIN_ZOOM, Viewport
from ucode.ui.node_editor import NodeEditor
from ucode.ui.theme import (
    ACCENT,
    BG_SURFACE,
    GRAPH_ARROW,
    GRAPH_EDGE,
    GRAPH_EDGE_CREATE,
    GRAPH_EDGE_LABEL,
    GRAPH_FOLDER,
    GRAPH_FOLDER_BORDER,
    GRAPH_FOLDER_HEADER,
    GRAPH_IMPORT,
    GRAPH_IMPORT_BORDER,
    GRAPH_IMPORT_EDGE,
    GRAPH_IMPORT_TEXT,
    GRAPH_NODE,
    GRAPH_NODE_BORDER,
    TEXT_MUTED,
)

BACKGROUND = QColor(BG_SURFACE)
ZOOM_PER_NOTCH = 1.2
NODE_HEADER_TILES = 1
MIN_FRAME_ZOOM = 1.0  # nodes hold code, so they open at readable size
EDITOR_MIN_ZOOM = 0.5  # below this the node bodies are not instantiated
LABEL_MIN_ZOOM = 0.25  # names stay readable further out than the code does
PAN_THRESHOLD_PX = 5  # a middle press that moves less than this is a paste, not a drag
FONT_PIXELS = 11
LINE_GROWTH = 12.8 / 11  # measured: line spacing per pixel of font size
LINE_PX = 12.8  # measured line spacing at the base font size, in pixels


class Canvas(QWidget):
    """The infinite workspace.

    Nodes are laid out automatically, so no grid is drawn, and can be dragged anywhere.
    Each node carries its file in an embedded editor: editing there edits the file on disk.
    """

    node_moved = Signal()  # a node was dropped somewhere new
    folder_moved = Signal()  # a folder box was dropped, taking its nodes along

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("canvas")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.viewport = Viewport()
        self.graph: FileGraph | None = None
        self._nodes: dict = {}
        self._editors: dict[str, NodeEditor] = {}
        # The file and line a live session is executing, drawn on the node itself.
        self._active_path: str | None = None
        self._active_line: int | None = None
        self._drag_origin: QPointF | None = None
        self._frame_pending = False

        # Dragging a node: which one, from where, and where it started.
        self._drag_node = None
        self._drag_from: QPointF | None = None
        self._drag_tile: tuple[float, float] | None = None

        # Dragging a folder box: it carries its nodes.
        self._drag_folder = None
        self._drag_folder_from: QPointF | None = None
        self._drag_folder_tile: tuple[float, float] | None = None
        self._drag_folder_members: list = []

        # Where each edge runs, planned in tiles so panning and zooming keep it valid.
        self._routes: list[list[tuple[float, float]]] = []
        self._routes_built = 0.0

        # Folder and node chrome rendered once and re-blitted, so scrolling and
        # dragging do not repaint the same rounded rectangles every frame.
        self._layers: dict[tuple, QPixmap] = {}

        # A middle press that started on a node body: paste if it stays put, pan if not.
        self._pan_press: QPointF | None = None
        self._pan_editor: NodeEditor | None = None
        self._pan_anchor: QPointF | None = None
        self._pan_moved = False

    # -- content -------------------------------------------------------
    def set_graph(self, graph: FileGraph | None) -> None:
        """Show ``graph``, or an empty surface when it is None."""
        self._clear_editors()
        self._active_path = None
        self._active_line = None
        self.graph = graph
        self._nodes = graph.by_path() if graph is not None else {}
        self._drag_node = None
        self._drag_from = None
        self._drag_tile = None
        self._drag_folder = None
        self._drag_folder_from = None
        self._drag_folder_tile = None
        self._drag_folder_members = []
        self._rebuild_routes()
        self._sync_editors()
        self.update()

    def set_active_line(self, path: str | None, line: int | None = None) -> None:
        """Mark the line a live session is executing, and the node that holds it."""
        if path == self._active_path and line == self._active_line:
            return

        previous = self._editors.get(self._active_path) if self._active_path else None
        if previous is not None:
            previous.set_active_line(None)

        self._active_path = path
        self._active_line = line

        editor = self._editors.get(path) if path else None
        if editor is not None and line:
            editor.set_active_line(line)

        self.update()

    def save_editors(self) -> None:
        """Write every open node back to disk before the window goes away."""
        for editor in self._editors.values():
            editor.save()

    def _clear_editors(self) -> None:
        for editor in self._editors.values():
            editor.save()
            # deleteLater only runs on a return to the event loop, so hide now: otherwise
            # the old view's editors stay on screen over the new one.
            editor.hide()
            editor.setParent(None)
            editor.deleteLater()
        self._editors.clear()

    def _sync_editors(self) -> None:
        """Create, position and hide node editors to match the current view."""
        if self.graph is None:
            for editor in self._editors.values():
                editor.hide()
            return

        zoom = self.viewport.zoom
        show = zoom >= EDITOR_MIN_ZOOM
        header = TILE * zoom * NODE_HEADER_TILES

        for node in self.graph.nodes:
            if node.kind != "file":
                continue  # import chips have no editor

            rect = self._rect(node.tile, node.size)
            editor = self._editors.get(node.path)

            if not show or not rect.intersects(self.rect()):
                if editor is not None:
                    editor.hide()
                continue

            if editor is None:
                generated = self.graph.synthetic.get(node.path)
                if generated is None:
                    editor = NodeEditor(self.graph.root / node.path, self)
                else:
                    text, mode = generated
                    editor = NodeEditor(
                        Path(node.path),
                        self,
                        text=text,
                        mode=mode,
                        tail=self.graph.tail if mode == "hex" else b"",
                        source=(
                            self.graph.root / node.path
                            if self.graph.root is not None and mode == "hex"
                            else None
                        ),
                    )
                editor.installEventFilter(self)
                editor.content_changed.connect(
                    lambda path=node.path: self._content_changed(path)
                )
                self._editors[node.path] = editor

            editor.setGeometry(
                QRect(
                    int(rect.left()) + 3,
                    int(rect.top() + header) + 1,
                    max(12, int(rect.width()) - 6),
                    max(12, int(rect.height() - header) - 4),
                )
            )
            # The node is the fixed size, so the text is fitted to it.
            editor.fit_text(
                editor.width(), editor.height(), node.columns, node.rows
            )
            editor.show()

    # -- camera --------------------------------------------------------
    def frame_graph(self, margin: int = TILE) -> None:
        """Zoom and pan so the graph is framed, never magnified past 1:1."""
        if self.graph is None or not self.graph.folders:
            return

        if self.width() < 50 or self.height() < 50:
            # Not laid out yet; showEvent/resizeEvent will try again.
            self._frame_pending = True
            return

        width = max(box.tile[0] + box.size[0] for box in self.graph.folders) * TILE
        height = max(box.tile[1] + box.size[1] for box in self.graph.folders) * TILE

        fit = min(
            max(1, self.width() - 2 * margin) / max(1, width),
            max(1, self.height() - 2 * margin) / max(1, height),
        )

        self._frame_pending = False
        self.viewport.zoom = max(MIN_FRAME_ZOOM, min(1.0, fit))
        self.viewport.left = -margin / self.viewport.zoom
        self.viewport.top = -margin / self.viewport.zoom
        self._sync_editors()
        self.update()

    # -- painting -----------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)

        if self.graph is not None:
            self._paint_graph(painter)

        painter.end()

    def _content_changed(self, path: str) -> None:
        """Grow the node to fit edited text, and its folder to fit the node."""
        node = self._nodes.get(path)
        editor = self._editors.get(path)
        if node is None or editor is None:
            return

        lines = editor.toPlainText().split("\n")
        rows = max(1, len(lines))
        columns = max(1, max(len(line) for line in lines))
        if (rows, columns) == (node.rows, node.columns):
            return

        old_size = node.size
        node.rows = rows
        node.columns = columns
        node.size = node_size(rows, columns)

        moved = [node]
        if node.size[1] < old_size[1]:
            # Shrunk: close the gap it left so the group and its box really get smaller.
            moved.extend(self._compact_group(node))
        else:
            moved.extend(self._make_room(node))

        node_spread = self._resolve_node_overlaps(node.folder)

        if self._fit_folder(node) or node_spread:
            # Whole groups shifted, so every route has to be looked at again.
            self._rebuild_routes()
        else:
            for item in moved:
                self._replan_near(item, thorough=True)

        self._sync_editors()
        self.update()
        self.node_moved.emit()

    def _compact_group(self, node) -> list:
        """Slide a group's nodes up into the gap left by one that shrank."""
        if self.graph is None:
            return []

        members = [m for m in self.graph.nodes if m.folder == node.folder]
        if not members:
            return []

        moved: list = []

        # A node that is blocked in one pass can come free in the next, so repeat.
        for _ in range(4):
            top = min(m.tile[1] for m in members)
            pass_moved = False

            for member in sorted(members, key=lambda m: (m.tile[1], m.tile[0])):
                # The highest it can go: the group's top, or just under its neighbour above.
                highest = top
                for other in self.graph.nodes:
                    if other is member:
                        continue
                    if (
                        member.tile[0] >= other.tile[0] + other.size[0]
                        or other.tile[0] >= member.tile[0] + member.size[0]
                    ):
                        continue
                    highest = max(highest, other.tile[1] + other.size[1] + GAP)

                if highest < member.tile[1] - 1e-9:
                    member.tile = (member.tile[0], highest)
                    pass_moved = True
                    if member not in moved:
                        moved.append(member)

            if not pass_moved:
                break

        return moved

    def _make_room(self, node) -> list:
        """Push siblings out of the way of a node that just grew."""
        if self.graph is None:
            return []

        pushed: list = []
        rect = QRectF(node.tile[0], node.tile[1], node.size[0], node.size[1])

        for _ in range(32):
            other = next(
                (
                    candidate
                    for candidate in self.graph.nodes
                    if candidate is not node
                    and candidate.folder == node.folder
                    and rect.intersects(
                        QRectF(
                            candidate.tile[0],
                            candidate.tile[1],
                            candidate.size[0],
                            candidate.size[1],
                        )
                    )
                ),
                None,
            )
            if other is None:
                break

            other.tile = (
                other.tile[0],
                node.tile[1] + node.size[1] + GAP,
            )
            pushed.append(other)

        return pushed

    def _fit_folder(self, node, limit: int = 24) -> bool:
        """Fit the node's group around its members; report whether neighbours moved."""
        if self.graph is None:
            return False

        box = next(
            (b for b in self.graph.folders if b.folder == node.folder), None
        )
        if box is None:
            return False

        members = [m for m in self.graph.nodes if m.folder == box.folder]
        if not members:
            return False

        # The group hugs whatever its nodes occupy now, so it grows with the text and
        # gives that room back when the text is removed again.
        left = min(m.tile[0] for m in members)
        top = min(m.tile[1] for m in members)
        content = (
            max(m.tile[0] + m.size[0] for m in members) - left,
            max(m.tile[1] + m.size[1] for m in members) - top,
        )
        box.size = folder_size(content, box.label)
        box.tile = (left - PADDING, top - HEADER - PADDING)

        return self._resolve_overlaps(box, limit)

    def _box_rect(self, box) -> QRectF:
        return QRectF(box.tile[0], box.tile[1], box.size[0], box.size[1])

    def _resolve_overlaps(self, keep, limit: int = 96) -> bool:
        """Groups never overlap: neighbours make way, and `keep` is the one that stays."""
        shifted = False

        for _ in range(limit):
            pair = next(
                (
                    (a, b)
                    for index, a in enumerate(self.graph.folders)
                    for b in self.graph.folders[index + 1 :]
                    if self._box_rect(a).intersects(self._box_rect(b))
                ),
                None,
            )
            if pair is None:
                return shifted

            first, second = pair
            if first is keep:
                self._shift_box(second, *self._escape(keep, second))
            elif second is keep:
                self._shift_box(first, *self._escape(keep, first, around=True))
            else:
                self._shift_box(second, *self._escape(first, second))
            shifted = True

        return shifted

    def _resolve_node_overlaps(self, folder: str, limit: int = 96) -> bool:
        """No two nodes of a group may cover each other once one of them has grown."""
        moved = False
        members = [m for m in self.graph.nodes if m.folder == folder]

        for _ in range(limit):
            pair = next(
                (
                    (a, b)
                    for index, a in enumerate(members)
                    for b in members[index + 1 :]
                    if QRectF(a.tile[0], a.tile[1], a.size[0], a.size[1]).intersects(
                        QRectF(b.tile[0], b.tile[1], b.size[0], b.size[1])
                    )
                ),
                None,
            )
            if pair is None:
                return moved

            first, second = pair
            dx, dy = self._escape(first, second, gap=GAP)
            second.tile = (second.tile[0] + dx, second.tile[1] + dy)
            moved = True

        return moved

    @staticmethod
    def _escape(
        fixed, mover, around: bool = False, gap: float = BOX_GAP
    ) -> tuple[float, float]:
        """The smallest way of moving `mover` clear of `fixed`."""
        right = fixed.tile[0] + fixed.size[0] + gap - mover.tile[0]
        down = fixed.tile[1] + fixed.size[1] + gap - mover.tile[1]
        if not around:
            return (0.0, down) if down <= right else (right, 0.0)

        left = mover.tile[0] + mover.size[0] + gap - fixed.tile[0]
        up = mover.tile[1] + mover.size[1] + gap - fixed.tile[1]
        options = [(0.0, -up), (-left, 0.0), (0.0, down), (right, 0.0)]
        return min(options, key=lambda step: abs(step[0]) + abs(step[1]))

    def _shift_box(self, box, dx: float, dy: float) -> None:
        """Move a group and every node inside it."""
        box.tile = (box.tile[0] + dx, box.tile[1] + dy)
        for member in self.graph.nodes:
            if member.folder == box.folder:
                member.tile = (member.tile[0] + dx, member.tile[1] + dy)

    def _line_tile_y(self, node, line: int) -> float:
        """Where a line sits inside a node, in tiles: the same for every zoom."""
        if node.kind != "file":
            return node.tile[1] + node.size[1] / 2

        top = node.tile[1] + NODE_HEADER_TILES + 1 / TILE
        return top + (max(1, line) - 0.5) * (LINE_PX / TILE)

    def _replan(self) -> None:
        """Re-plan while dragging, at a rate that cannot make the drag feel slow."""
        if time.monotonic() - self._routes_built >= 0.15:
            self._rebuild_routes()

    def _replan_near(self, node, *, thorough: bool = False) -> None:
        """Re-plan only the edges the moved node can have disturbed."""
        if self.graph is None or not self._routes:
            return

        obstacles = [
            (other.tile[0], other.tile[1], other.size[0], other.size[1])
            for other in self.graph.nodes
        ]
        box = (node.tile[0], node.tile[1], node.size[0], node.size[1])

        for index, edge in enumerate(self.graph.edges):
            source = self._nodes.get(edge.source)
            target = self._nodes.get(edge.target)
            if source is None or target is None:
                continue

            existing = self._routes[index] if index < len(self._routes) else []
            disturbed = (
                edge.source == node.path
                or edge.target == node.path
                or any(
                    crosses(start, end, box)
                    for start, end in zip(existing, existing[1:])
                )
            )
            if not disturbed:
                continue

            self._routes[index] = route(
                (
                    source.tile[0] + source.size[0],
                    self._line_tile_y(source, edge.source_line),
                ),
                (
                    target.tile[0],
                    self._line_tile_y(target, edge.target_line),
                ),
                obstacles,
                thorough=thorough,
            )

        self._routes_built = time.monotonic()

    def _rebuild_routes(self) -> None:
        """Plan every edge so no line has to cross a node box."""
        self._routes = []
        self._routes_built = time.monotonic()
        if self.graph is None:
            return

        obstacles = [
            (node.tile[0], node.tile[1], node.size[0], node.size[1])
            for node in self.graph.nodes
        ]

        for edge in self.graph.edges:
            source = self._nodes.get(edge.source)
            target = self._nodes.get(edge.target)
            if source is None or target is None:
                self._routes.append([])
                continue

            self._routes.append(
                route(
                    (
                        source.tile[0] + source.size[0],
                        self._line_tile_y(source, edge.source_line),
                    ),
                    (
                        target.tile[0],
                        self._line_tile_y(target, edge.target_line),
                    ),
                    obstacles,
                )
            )

    def _screen_x(self, tile_x: float) -> float:
        return self.viewport.world_to_screen(tile_x * TILE, 0)[0]

    def _screen_y(self, tile_y: float) -> float:
        return self.viewport.world_to_screen(0, tile_y * TILE)[1]

    def _rect(self, tile: tuple[int, int], size: tuple[int, int]) -> QRectF:
        x, y = self.viewport.world_to_screen(tile[0] * TILE, tile[1] * TILE)
        return QRectF(
            x,
            y,
            size[0] * TILE * self.viewport.zoom,
            size[1] * TILE * self.viewport.zoom,
        )

    def _node_at(self, position: QPointF):
        """The topmost node under a screen position, if any."""
        if self.graph is None:
            return None

        for node in reversed(self.graph.nodes):
            if self._rect(node.tile, node.size).contains(position):
                return node

        return None

    def _folder_at(self, position: QPointF):
        """The folder whose header band is under a screen position."""
        if self.graph is None:
            return None

        header = TILE * self.viewport.zoom
        for box in reversed(self.graph.folders):
            rect = self._rect(box.tile, box.size)
            handle = QRectF(rect.left(), rect.top(), rect.width(), header)
            if handle.contains(position):
                return box

        return None

    def _folder_is_free(self, box, tile: tuple[float, float]) -> bool:
        """True when the box, placed at ``tile``, does not touch another folder."""
        if self.graph is None:
            return True

        rect = QRectF(tile[0], tile[1], box.size[0], box.size[1])
        for other in self.graph.folders:
            if other is box:
                continue
            if rect.intersects(
                QRectF(other.tile[0], other.tile[1], other.size[0], other.size[1])
            ):
                return False

        return True

    def _settle_folder(self, box, tile: tuple[float, float]) -> tuple[float, float]:
        """Groups never overlap: slide along an edge instead of pushing through."""
        if self._folder_is_free(box, tile):
            return tile

        horizontal = (tile[0], box.tile[1])
        if self._folder_is_free(box, horizontal):
            return horizontal

        vertical = (box.tile[0], tile[1])
        if self._folder_is_free(box, vertical):
            return vertical

        return box.tile

    def _move_folder(self, event: QMouseEvent) -> None:
        """Drag a group: the box and every node that belongs to it."""
        box = self._drag_folder
        origin = self._drag_folder_from
        start = self._drag_folder_tile
        scale = TILE * self.viewport.zoom

        if box is None or origin is None or start is None or scale <= 0:
            return

        delta = event.position() - origin
        proposed = (start[0] + delta.x() / scale, start[1] + delta.y() / scale)
        settled = self._settle_folder(box, proposed)

        box.tile = settled
        shift = (settled[0] - start[0], settled[1] - start[1])
        for node, node_start in self._drag_folder_members:
            node.tile = (node_start[0] + shift[0], node_start[1] + shift[1])

        self._replan()
        self._sync_editors()
        self.update()

    def _bring_to_front(self, node) -> None:
        """Paint the grabbed node last, so dragging it never buries it."""
        if self.graph is None or not self.graph.nodes:
            return
        if self.graph.nodes[-1] is node:
            return

        self.graph.nodes.remove(node)
        self.graph.nodes.append(node)

        editor = self._editors.get(node.path)
        if editor is not None:
            editor.raise_()

    def _move_node(self, event: QMouseEvent) -> None:
        """Drag the grabbed node, following the cursor in screen space."""
        if self._drag_node is None or self._drag_from is None or self._drag_tile is None:
            return

        delta = event.position() - self._drag_from
        scale = TILE * self.viewport.zoom
        if scale <= 0:
            return

        self._drag_node.tile = (
            self._drag_tile[0] + delta.x() / scale,
            self._drag_tile[1] + delta.y() / scale,
        )
        self._replan_near(self._drag_node)
        self._sync_editors()
        self.update()

    def _line_height(self, zoom: float) -> float:
        """The rendered height of a text line at this zoom, to hit a line exactly."""
        return LINE_GROWTH * max(5, int(FONT_PIXELS * zoom))

    def _anchor_y(self, node, line: int, zoom: float) -> float:
        """Vertical position of ``line`` (1-based) inside a node."""
        rect = self._rect(node.tile, node.size)
        if node.kind != "file":
            return rect.center().y()

        # Use the editor's own metrics: each node fits its font to its box.
        editor = self._editors.get(node.path)
        height = (
            QFontMetricsF(editor.font()).lineSpacing()
            if editor is not None
            else self._line_height(zoom)
        )
        top = rect.top() + TILE * zoom * NODE_HEADER_TILES + 1
        bottom = rect.bottom() - 1
        y = top + (max(1, line) - 0.5) * height

        return min(max(y, top + height / 2), max(top + height / 2, bottom - height / 2))

    def _font(self, points: float) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(6.0, points * self.viewport.zoom))
        return font

    def _layer(self, key: tuple, width: int, height: int, paint) -> QPixmap:
        """Draw a fixed-size piece once, then blit it until its size or zoom changes."""
        pixmap = self._layers.get(key)
        if pixmap is not None:
            return pixmap

        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(max(1, int(width * ratio)), max(1, int(height * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing, self.viewport.zoom > 0.5
        )
        paint(painter)
        painter.end()

        if len(self._layers) > 256:
            self._layers.clear()
        self._layers[key] = pixmap
        return pixmap

    def _paint_graph(self, painter: QPainter) -> None:
        zoom = self.viewport.zoom
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, zoom > 0.5)

        self._paint_folders(painter, zoom)
        self._paint_edges(painter, zoom)
        self._paint_nodes(painter, zoom)

    def _paint_folders(self, painter: QPainter, zoom: float) -> None:
        for box in self.graph.folders:
            rect = self._rect(box.tile, box.size)
            if not rect.intersects(self.rect()):
                continue

            width = max(1, int(round(rect.width())))
            height = max(1, int(round(rect.height())))
            key = ("folder", box.folder, round(zoom, 4), width, height)

            def draw(
                layer: QPainter,
                width=width,
                height=height,
                label=box.label,
                zoom=zoom,
            ) -> None:
                local = QRectF(0, 0, width, height)

                # A drop shadow lifts the group off the workspace.
                layer.setPen(Qt.PenStyle.NoPen)
                layer.setBrush(QColor(0, 0, 0, 90))
                layer.drawRoundedRect(local.translated(0, 3), 9, 9)

                layer.setPen(QPen(QColor(GRAPH_FOLDER_BORDER), 1.2))
                layer.setBrush(QColor(GRAPH_FOLDER))
                layer.drawRoundedRect(local, 8, 8)

                # A filled header band makes the group read as one solid object.
                header_height = TILE * zoom
                band = QRectF(
                    1, 1, max(1.0, width - 2), max(1.0, header_height - 1)
                )
                layer.save()
                layer.setClipRect(band)
                layer.setPen(Qt.PenStyle.NoPen)
                layer.setBrush(QColor(GRAPH_FOLDER_HEADER))
                layer.drawRoundedRect(
                    QRectF(0, 0, width, header_height + 8), 8, 8
                )
                layer.restore()

                layer.setPen(QPen(QColor(GRAPH_FOLDER_BORDER), 1))
                layer.drawLine(
                    QPointF(1, header_height),
                    QPointF(width - 1, header_height),
                )

                if zoom >= LABEL_MIN_ZOOM:
                    font = self._font(10)
                    font.setBold(True)
                    layer.setFont(font)
                    layer.setPen(QColor(TEXT_MUTED))
                    layer.drawText(
                        QRectF(10, 0, max(10.0, width - 20), header_height),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        label,
                    )

            painter.drawPixmap(
                int(rect.left()), int(rect.top()), self._layer(key, width, height + 4, draw)
            )

    def _paint_edges(self, painter: QPainter, zoom: float) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # The routes are axis-aligned: antialiasing them costs several milliseconds a
        # frame and only softens lines that land on pixel boundaries anyway.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for index, edge in enumerate(self.graph.edges):
            source = self._nodes.get(edge.source)
            target = self._nodes.get(edge.target)
            if source is None or target is None:
                continue

            # Dependencies on something outside the project are drawn as dashed flows;
            # object creation gets its own colour and a label.
            external = target.kind == "import"
            if edge.kind == "creates":
                colour = GRAPH_EDGE_CREATE
            else:
                colour = GRAPH_IMPORT_EDGE if external else GRAPH_EDGE

            pen = QPen(QColor(colour), max(1.0, 1.4 * zoom))
            if external:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setDashPattern([4.0, 3.0])
            painter.setPen(pen)

            start = self._rect(source.tile, source.size)
            end = self._rect(target.tile, target.size)
            # Both ends sit on the line they belong to, and stop short of the target
            # so the arrowhead lands in the gap rather than under the node.
            x1 = start.right()
            y1 = self._anchor_y(source, edge.source_line, zoom)
            x2 = end.left() - 2.0
            y2 = self._anchor_y(target, edge.target_line, zoom)

            tiles = self._routes[index] if index < len(self._routes) else None
            if not tiles:
                tiles = [(x1, y1), (x2, y1), (x2, y2)]

            # Off-screen edges cost as much to submit as visible ones.
            left, top, right, bottom = x1, y1, x1, y1
            for px, py in tiles:
                sx = self._screen_x(px)
                sy = self._screen_y(py)
                left, right = min(left, sx), max(right, sx)
                top, bottom = min(top, sy), max(bottom, sy)
            if (
                right < -2
                or left > self.width() + 2
                or bottom < -2
                or top > self.height() + 2
            ):
                continue

            points = [
                QPointF(self._screen_x(px), self._screen_y(py)) for px, py in tiles
            ]
            # Keep both ends on the exact line they belong to at this zoom.
            points[0] = QPointF(x1, y1)
            points[-1] = QPointF(x2, y2)
            if len(points) >= 3:
                if abs(tiles[1][1] - tiles[0][1]) <= 1e-6:
                    points[1] = QPointF(points[1].x(), y1)
                if abs(tiles[-2][1] - tiles[-1][1]) <= 1e-6:
                    points[-2] = QPointF(points[-2].x(), y2)

            painter.drawPolyline(QPolygonF(points))

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint_arrow(painter, points[-2], points[-1], zoom, pen.color())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

            if edge.label and zoom >= LABEL_MIN_ZOOM:
                font = self._font(8)
                painter.setFont(font)
                painter.setPen(QColor(GRAPH_EDGE_LABEL))
                painter.drawText(QPointF(x1 + 8 * zoom, y1 - 4 * zoom), edge.label)

    def _paint_nodes(self, painter: QPainter, zoom: float) -> None:
        header = TILE * zoom * NODE_HEADER_TILES
        for node in self.graph.nodes:
            rect = self._rect(node.tile, node.size)
            if not rect.intersects(self.rect()):
                continue

            width = max(1, int(round(rect.width())))
            height = max(1, int(round(rect.height())))
            active = node.path == self._active_path
            key = ("node", node.path, round(zoom, 4), width, height, active)
            painter.drawPixmap(
                int(rect.left()),
                int(rect.top()),
                self._layer(
                    key,
                    width,
                    height,
                    self._node_layer(node, zoom, width, height, header, active),
                ),
            )

    def _node_layer(
        self,
        node,
        zoom: float,
        width: int,
        height: int,
        header: float,
        active: bool = False,
    ):
        """How one node's frame is drawn, at its own size."""

        def draw(layer: QPainter) -> None:
            rect = QRectF(0, 0, width, height)

            if node.kind == "import":
                # An external dependency: a chip, not an editor.
                layer.setPen(
                    QPen(QColor(GRAPH_IMPORT_BORDER), 1, Qt.PenStyle.DashLine)
                )
                layer.setBrush(QColor(GRAPH_IMPORT))
                radius = min(rect.height() / 2, 12.0)
                layer.drawRoundedRect(rect, radius, radius)

                if zoom >= LABEL_MIN_ZOOM:
                    font = self._font(9)
                    layer.setFont(font)
                    layer.setPen(QColor(GRAPH_IMPORT_TEXT))
                    metrics = QFontMetricsF(font)
                    label = metrics.elidedText(
                        node.label,
                        Qt.TextElideMode.ElideRight,
                        max(10.0, rect.width() - 16),
                    )
                    layer.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
                return

            layer.setPen(QPen(QColor(GRAPH_NODE_BORDER), 1))
            layer.setBrush(QColor(GRAPH_NODE))
            layer.drawRoundedRect(rect, 6, 6)

            if active:
                # The file a live session is running: framed so it reads at a glance.
                layer.setPen(QPen(QColor(ACCENT), max(1.4, 1.8 * zoom)))
                layer.setBrush(Qt.BrushStyle.NoBrush)
                layer.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), 6, 6)

            if zoom >= LABEL_MIN_ZOOM:
                font = self._font(9)
                layer.setFont(font)
                layer.setPen(QColor(TEXT_MUTED))
                metrics = QFontMetricsF(font)
                label = metrics.elidedText(
                    node.label,
                    Qt.TextElideMode.ElideMiddle,
                    max(10.0, rect.width() - 20),
                )
                layer.drawText(
                    QRectF(10, 2, max(10.0, width - 20), max(1.0, header - 3)),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    label,
                )

        return draw

    def _paint_arrow(
        self, painter: QPainter, previous: QPointF, tip: QPointF, zoom: float, colour
    ) -> None:
        """A flow arrow at the end of an edge, pointing the way the link goes."""
        dx, dy = tip.x() - previous.x(), tip.y() - previous.y()
        length = hypot(dx, dy)
        if length < 1e-6:
            return

        ux, uy = dx / length, dy / length
        size = max(5.0, 9.0 * zoom)
        base_x, base_y = tip.x() - ux * size, tip.y() - uy * size
        half = 0.5 * size

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawPolygon(
            QPolygonF(
                [
                    tip,
                    QPointF(base_x - uy * half, base_y + ux * half),
                    QPointF(base_x + uy * half, base_y - ux * half),
                ]
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # -- middle button over a node -------------------------------------
    def eventFilter(self, watched, event) -> bool:
        """Middle button on a node body: a click pastes, a drag pans the canvas."""
        if isinstance(watched, NodeEditor) and (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.MiddleButton
        ):
            self._pan_press = event.globalPosition()
            self._pan_editor = watched
            self._pan_anchor = event.position()
            self._pan_moved = False
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            # Grab the canvas, so the drag keeps panning once it leaves the editor.
            self.grabMouse()
            return True

        return super().eventFilter(watched, event)

    def _end_middle(self) -> None:
        self._pan_press = None
        self._pan_editor = None
        self._pan_anchor = None
        self._pan_moved = False
        self.releaseMouse()
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    @staticmethod
    def _primary_selection() -> str:
        """The X11 primary selection, empty where the platform has no such mode."""
        return QGuiApplication.clipboard().text(QClipboard.Mode.Selection)

    def _paste_selection(self) -> None:
        """Paste the primary selection where the middle click landed."""
        editor, anchor = self._pan_editor, self._pan_anchor
        if editor is None or anchor is None:
            return

        text = self._primary_selection()
        if text:
            editor.cursorForPosition(anchor.toPoint()).insertText(text)

    def _middle_drag(self, event: QMouseEvent) -> bool:
        """Pan on a middle drag; return True while a middle press is being handled."""
        if self._pan_editor is None or self._pan_press is None:
            return False

        delta = event.globalPosition() - self._pan_press

        if not self._pan_moved:
            if hypot(delta.x(), delta.y()) < PAN_THRESHOLD_PX:
                return True
            # Past the threshold this is a drag, not a click, so it must not paste.
            self._pan_moved = True
            self._pan_press = event.globalPosition()
            return True

        self.viewport.pan_by(delta.x(), delta.y())
        self._pan_press = event.globalPosition()
        self._sync_editors()
        self.update()
        return True

    # -- events --------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._frame_pending:
            self.frame_graph()
        self._sync_editors()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._frame_pending:
            self.frame_graph()
        self._sync_editors()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            box = self._folder_at(event.position())
            if box is not None:
                # Grabbed by its header: the whole group travels together.
                self.graph.folders.remove(box)
                self.graph.folders.append(box)
                self._drag_folder = box
                self._drag_folder_from = event.position()
                self._drag_folder_tile = box.tile
                self._drag_folder_members = [
                    (node, node.tile)
                    for node in self.graph.nodes
                    if node.folder == box.folder
                ]
                self._drag_origin = None
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

            node = self._node_at(event.position())
            if node is not None:
                self._drag_node = node
                self._drag_from = event.position()
                self._bring_to_front(node)
                self._drag_tile = node.tile
                self._drag_origin = None
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return

        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._drag_origin = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._middle_drag(event):
            return

        if self._drag_folder is not None:
            self._move_folder(event)
            return

        if self._drag_node is not None:
            self._move_node(event)
            return

        if self._drag_origin is None:
            # Show that a node can be picked up.
            over_node = self._node_at(event.position()) is not None
            over_folder = self._folder_at(event.position()) is not None
            self.setCursor(
                Qt.CursorShape.SizeAllCursor
                if over_node or over_folder
                else Qt.CursorShape.OpenHandCursor
            )
            super().mouseMoveEvent(event)
            return

        delta = event.position() - self._drag_origin
        self._drag_origin = event.position()
        self.viewport.pan_by(delta.x(), delta.y())
        self._sync_editors()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pan_editor is not None and event.button() == Qt.MouseButton.MiddleButton:
            if not self._pan_moved:
                self._paste_selection()
            self._end_middle()
            return

        if self._drag_folder is not None:
            moved = (
                self._drag_folder_from is not None
                and event.position() != self._drag_folder_from
            )
            self._rebuild_routes()
            self._drag_folder = None
            self._drag_folder_from = None
            self._drag_folder_tile = None
            self._drag_folder_members = []
            self.setCursor(Qt.CursorShape.OpenHandCursor)

            if moved:
                self.folder_moved.emit()
            return

        if self._drag_node is not None:
            moved = self._drag_from is not None and event.position() != self._drag_from
            self._rebuild_routes()
            self._drag_node = None
            self._drag_from = None
            self._drag_tile = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

            if moved:
                self.node_moved.emit()
            return

        if self._drag_origin is not None:
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        notches = event.angleDelta().y() / 120.0
        if notches == 0:
            return

        position = event.position()
        self.viewport.zoom_at(position.x(), position.y(), ZOOM_PER_NOTCH**notches)
        self._sync_editors()
        self.update()
        event.accept()
