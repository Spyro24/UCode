"""The infinite workspace: pans and zooms, and holds the file graph."""

from __future__ import annotations

from math import hypot

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QClipboard,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from ucode.core.graph import FileGraph
from ucode.core.tile import TILE
from ucode.core.viewport import MIN_ZOOM, Viewport
from ucode.ui.node_editor import NodeEditor
from ucode.ui.theme import (
    BG_SURFACE,
    GRAPH_ARROW,
    GRAPH_EDGE,
    GRAPH_FOLDER,
    GRAPH_FOLDER_BORDER,
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


class Canvas(QWidget):
    """The infinite workspace.

    Nodes are laid out automatically, so no grid is drawn. Each node carries its file in
    an embedded editor: editing there edits the file on disk.
    """

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
        self._drag_origin: QPointF | None = None
        self._frame_pending = False

        # A middle press that started on a node body: paste if it stays put, pan if not.
        self._pan_press: QPointF | None = None
        self._pan_editor: NodeEditor | None = None
        self._pan_anchor: QPointF | None = None
        self._pan_moved = False

    # -- content -------------------------------------------------------
    def set_graph(self, graph: FileGraph | None) -> None:
        """Show ``graph``, or an empty surface when it is None."""
        self._clear_editors()
        self.graph = graph
        self._nodes = graph.by_path() if graph is not None else {}
        self._sync_editors()
        self.update()

    def save_editors(self) -> None:
        """Write every open node back to disk before the window goes away."""
        for editor in self._editors.values():
            editor.save()

    def _clear_editors(self) -> None:
        for editor in self._editors.values():
            editor.save()
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
                editor = NodeEditor(self.graph.root / node.path, self)
                editor.installEventFilter(self)
                self._editors[node.path] = editor

            # Floor, so the text always stays inside the node it was measured for.
            editor.set_zoom_font(max(5, int(FONT_PIXELS * zoom)))
            editor.setGeometry(
                QRect(
                    int(rect.left()) + 3,
                    int(rect.top() + header) + 1,
                    max(12, int(rect.width()) - 6),
                    max(12, int(rect.height() - header) - 4),
                )
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

    def _rect(self, tile: tuple[int, int], size: tuple[int, int]) -> QRectF:
        x, y = self.viewport.world_to_screen(tile[0] * TILE, tile[1] * TILE)
        return QRectF(
            x,
            y,
            size[0] * TILE * self.viewport.zoom,
            size[1] * TILE * self.viewport.zoom,
        )

    def _font(self, points: float) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(6.0, points * self.viewport.zoom))
        return font

    def _paint_graph(self, painter: QPainter) -> None:
        zoom = self.viewport.zoom
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, zoom > 0.5)

        for box in self.graph.folders:
            rect = self._rect(box.tile, box.size)
            if not rect.intersects(self.rect()):
                continue

            painter.setPen(QPen(QColor(GRAPH_FOLDER_BORDER), 1))
            painter.setBrush(QColor(GRAPH_FOLDER))
            painter.drawRoundedRect(rect, 8, 8)

            # A header band makes the group read as one unit.
            header_height = TILE * zoom
            painter.setPen(QPen(QColor(GRAPH_FOLDER_BORDER), 1))
            painter.drawLine(
                QPointF(rect.left() + 1, rect.top() + header_height),
                QPointF(rect.right() - 1, rect.top() + header_height),
            )

            if zoom >= LABEL_MIN_ZOOM:
                font = self._font(10)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor(TEXT_MUTED))
                painter.drawText(
                    QRectF(
                        rect.left() + 10,
                        rect.top(),
                        rect.width() - 20,
                        header_height,
                    ),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    box.label,
                )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for edge in self.graph.edges:
            source = self._nodes.get(edge.source)
            target = self._nodes.get(edge.target)
            if source is None or target is None:
                continue

            # Dependencies on something outside the project are drawn as dashed flows.
            external = target.kind == "import"
            pen = QPen(
                QColor(GRAPH_IMPORT_EDGE if external else GRAPH_EDGE),
                max(1.0, 1.4 * zoom),
            )
            if external:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setDashPattern([4.0, 3.0])
            painter.setPen(pen)

            start = self._rect(source.tile, source.size)
            end = self._rect(target.tile, target.size)
            # Stop short of the target so the arrowhead sits in the gap.
            x1, y1 = start.right(), start.center().y()
            x2, y2 = end.left() - 2.0, end.center().y()
            offset = TILE * zoom * 0.8

            points = [QPointF(x1, y1)]
            if x2 >= x1:
                middle = (x1 + x2) / 2
                points += [QPointF(middle, y1), QPointF(middle, y2)]
            else:
                # Backwards link: loop beneath both nodes instead of crossing them.
                detour = max(start.bottom(), end.bottom()) + offset
                points += [
                    QPointF(x1 + offset, y1),
                    QPointF(x1 + offset, detour),
                    QPointF(x2 - offset, detour),
                    QPointF(x2 - offset, y2),
                ]
            points.append(QPointF(x2, y2))

            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            painter.drawPath(path)
            self._paint_arrow(painter, points[-2], points[-1], zoom, pen.color())

        header = TILE * zoom * NODE_HEADER_TILES
        for node in self.graph.nodes:
            rect = self._rect(node.tile, node.size)
            if not rect.intersects(self.rect()):
                continue

            if node.kind == "import":
                # An external dependency: a chip, not an editor.
                painter.setPen(
                    QPen(QColor(GRAPH_IMPORT_BORDER), 1, Qt.PenStyle.DashLine)
                )
                painter.setBrush(QColor(GRAPH_IMPORT))
                radius = min(rect.height() / 2, 12.0)
                painter.drawRoundedRect(rect, radius, radius)

                if zoom >= LABEL_MIN_ZOOM:
                    font = self._font(9)
                    painter.setFont(font)
                    painter.setPen(QColor(GRAPH_IMPORT_TEXT))
                    metrics = QFontMetricsF(font)
                    label = metrics.elidedText(
                        node.label,
                        Qt.TextElideMode.ElideRight,
                        max(10.0, rect.width() - 16),
                    )
                    painter.drawText(
                        rect, Qt.AlignmentFlag.AlignCenter, label
                    )
                continue

            painter.setPen(QPen(QColor(GRAPH_NODE_BORDER), 1))
            painter.setBrush(QColor(GRAPH_NODE))
            painter.drawRoundedRect(rect, 6, 6)

            if zoom >= LABEL_MIN_ZOOM:
                font = self._font(9)
                painter.setFont(font)
                painter.setPen(QColor(TEXT_MUTED))
                metrics = QFontMetricsF(font)
                label = metrics.elidedText(
                    node.label, Qt.TextElideMode.ElideMiddle, max(10.0, rect.width() - 20)
                )
                painter.drawText(
                    QRectF(
                        rect.left() + 10,
                        rect.top() + 2,
                        rect.width() - 20,
                        max(1.0, header - 3),
                    ),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    label,
                )

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

        if self._drag_origin is None:
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
