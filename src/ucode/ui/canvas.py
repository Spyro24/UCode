"""The infinite viewport widget: a tile grid that pans and zooms without limits."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from ucode.core.viewport import Viewport

BACKGROUND = QColor("#fcfcfd")
MINOR_LINE = QColor("#e8eaee")
MAJOR_LINE = QColor("#d2d7df")
MAJOR_EVERY = 8  # every eighth tile line is drawn stronger, as a coarse ruler
MINOR_VISIBLE_ABOVE = 6.0  # px per tile; below this the minor grid is too dense
ZOOM_PER_NOTCH = 1.2


class Canvas(QWidget):
    """The infinite workspace.

    Drag with the left or middle mouse button to pan, wheel to zoom around the pointer.
    Only the grid is drawn for now; nodes, ports and edges arrive in M2.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("canvas")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.viewport = Viewport()
        self._drag_origin: QPointF | None = None

    # -- painting -----------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        self._paint_grid(painter)
        painter.end()

    def _paint_grid(self, painter: QPainter) -> None:
        viewport = self.viewport
        if viewport.tile_size() <= 0:
            return

        left, top, right, bottom = viewport.visible_tiles(
            self.width(), self.height()
        )
        draw_minor = viewport.tile_size() >= MINOR_VISIBLE_ABOVE

        minor_pen = QPen(MINOR_LINE)
        minor_pen.setWidth(1)
        major_pen = QPen(MAJOR_LINE)
        major_pen.setWidth(1)

        for tile_x in range(left, right + 1):
            major = tile_x % MAJOR_EVERY == 0
            if not major and not draw_minor:
                continue
            screen_x = viewport.world_to_screen(tile_x * viewport.tile, 0.0)[0]
            painter.setPen(major_pen if major else minor_pen)
            painter.drawLine(QPointF(screen_x, 0.0), QPointF(screen_x, self.height()))

        for tile_y in range(top, bottom + 1):
            major = tile_y % MAJOR_EVERY == 0
            if not major and not draw_minor:
                continue
            screen_y = viewport.world_to_screen(0.0, tile_y * viewport.tile)[1]
            painter.setPen(major_pen if major else minor_pen)
            painter.drawLine(QPointF(0.0, screen_y), QPointF(self.width(), screen_y))

    # -- interaction ---------------------------------------------------
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
        if self._drag_origin is None:
            super().mouseMoveEvent(event)
            return

        delta = event.position() - self._drag_origin
        self._drag_origin = event.position()
        self.viewport.pan_by(delta.x(), delta.y())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
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
        self.viewport.zoom_at(
            position.x(), position.y(), ZOOM_PER_NOTCH**notches
        )
        self.update()
        event.accept()
