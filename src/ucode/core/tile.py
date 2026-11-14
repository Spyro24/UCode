"""The tile grid — the atomic unit of canvas layout (roadmap §4).

Every position and size on the canvas is an integer count of tiles, never a pixel
measurement, so layout stays exact, mergeable and resolution-independent.
"""

from __future__ import annotations

TILE = 48  # logical px per tile; the project setting defaults to this
TILE_MIN = 32
TILE_MAX = 128
SUBDIVISIONS = 4  # port lanes and corner radii live on ¼-tile steps
CELL = TILE // SUBDIVISIONS  # 16 logical px — the text grid cell

MIN_NODE_SIZE = (2, 2)  # in tiles
DEFAULT_NODE_SIZE = (6, 4)  # in tiles


def snap(pixels: float) -> int:
    """Return the nearest tile index for a pixel coordinate."""
    return round(pixels / TILE)


def to_pixels(tile: int) -> int:
    """Return the pixel coordinate of a tile's left or top edge."""
    return tile * TILE
