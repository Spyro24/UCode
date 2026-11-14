"""The infinite viewport: pan and zoom over an unbounded tile grid.

Screen coordinates are pixels inside the viewport widget. World coordinates are pixels
on the infinite canvas, whose origin is the top-left corner of tile (0, 0). Keeping this
math in the core means the camera is testable without a GUI and reusable by any renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ucode.core.tile import TILE

MIN_ZOOM = 0.1
MAX_ZOOM = 4.0


@dataclass(slots=True)
class Viewport:
    """A camera over the infinite tile grid.

    ``left``/``top`` are the world coordinates shown at the widget's top-left corner, so
    panning never has a limit: any world coordinate is reachable.
    """

    tile: int = TILE
    zoom: float = 1.0
    left: float = 0.0
    top: float = 0.0

    # -- conversions --------------------------------------------------
    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return ((wx - self.left) * self.zoom, (wy - self.top) * self.zoom)

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx / self.zoom + self.left, sy / self.zoom + self.top)

    def tile_size(self) -> float:
        """On-screen size of one tile, in pixels."""
        return self.tile * self.zoom

    # -- movement -----------------------------------------------------
    def pan_by(self, dx: float, dy: float) -> None:
        """Move the content by a screen-space delta."""
        self.left -= dx / self.zoom
        self.top -= dy / self.zoom

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Scale by ``factor`` keeping the world point under (sx, sy) in place."""
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        if new_zoom == self.zoom:
            return

        wx, wy = self.screen_to_world(sx, sy)
        self.zoom = new_zoom
        self.left = wx - sx / new_zoom
        self.top = wy - sy / new_zoom

    # -- visible area -------------------------------------------------
    def visible_tiles(self, width: float, height: float) -> tuple[int, int, int, int]:
        """Inclusive tile range ``(left, top, right, bottom)`` covering the widget."""
        right_world = self.left + width / self.zoom
        bottom_world = self.top + height / self.zoom

        return (
            math.floor(self.left / self.tile),
            math.floor(self.top / self.tile),
            math.floor(right_world / self.tile),
            math.floor(bottom_world / self.tile),
        )
