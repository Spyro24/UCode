"""The infinite workspace widget: a blank surface that pans and zooms without limits."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QWheelEvent
from PySide6.QtWidgets import QWidget

from ucode.core.viewport import Viewport
from ucode.ui.theme import BG_SURFACE

BACKGROUND = QColor(BG_SURFACE)
ZOOM_PER_NOTCH = 1.2


class Canvas(QWidget):
    """The infinite workspace.

    No grid is drawn: nodes are laid out automatically, so the surface stays plain.
    Drag with the left or middle mouse button to pan, wheel to zoom around the pointer.
    Nodes, ports and edges arrive later.
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
        painter.end()

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
