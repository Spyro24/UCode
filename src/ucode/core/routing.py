"""Orthogonal edge routing that keeps edges out of the node boxes.

The canvas paints edges beneath the node editors, so a line crossing a node would vanish
behind its code field. This module picks a corridor that no line has to cross a box for:
a vertical channel between the two nodes when there is one, otherwise a horizontal
channel above or below whatever is in the way.

Coordinates are in tiles, so a plan survives panning and zooming.
"""

from __future__ import annotations

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, width, height
Plan = tuple[str, float, float, float]  # ("v", x, 0, 0) or ("h", y, xa, xb)

EPSILON = 1e-6


def crosses(a: Point, b: Point, rect: Rect) -> bool:
    """True when the axis-aligned segment ``a``-``b`` passes through ``rect``."""
    x, y, width, height = rect
    (ax, ay), (bx, by) = a, b

    if abs(ay - by) <= EPSILON:  # horizontal
        if not y + EPSILON < ay < y + height - EPSILON:
            return False
        low, high = sorted((ax, bx))
        return max(low, x) < min(high, x + width) - EPSILON

    if abs(ax - bx) <= EPSILON:  # vertical
        if not x + EPSILON < ax < x + width - EPSILON:
            return False
        low, high = sorted((ay, by))
        return max(low, y) < min(high, y + height) - EPSILON

    return True  # only orthogonal segments are produced


def is_clear(points: list[Point], obstacles: list[Rect]) -> bool:
    return not any(
        crosses(start, end, rect)
        for start, end in zip(points, points[1:])
        for rect in obstacles
    )


def points_for(plan: Plan, x1: float, y1: float, x2: float, y2: float) -> list[Point]:
    """Turn a plan into a polyline for these endpoints."""
    kind, first, second, third = plan

    if kind == "v":
        return [(x1, y1), (first, y1), (first, y2), (x2, y2)]

    return [
        (x1, y1),
        (second, y1),
        (second, first),
        (third, first),
        (third, y2),
        (x2, y2),
    ]


def plan_route(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    obstacles: list[Rect],
    margin: float = 0.35,
) -> Plan:
    """Choose the cheapest corridor that reaches the target without crossing a box."""
    if not obstacles:
        return ("v", (x1 + x2) / 2, 0.0, 0.0)

    # A vertical channel between the two nodes: the plain, expected path.
    if x2 - x1 > margin * 2:
        middle = (x1 + x2) / 2
        xs = {round(middle, 3), round(x1 + margin, 3), round(x2 - margin, 3)}
        for x, _, width, _ in obstacles:
            xs.add(round(x - margin, 3))
            xs.add(round(x + width + margin, 3))

        candidates = sorted(
            (x for x in xs if x1 + margin <= x <= x2 - margin),
            key=lambda x: abs(x - middle),
        )
        for x in candidates:
            plan: Plan = ("v", x, 0.0, 0.0)
            if is_clear(points_for(plan, x1, y1, x2, y2), obstacles):
                return plan

    # Otherwise go around: out of the source, along a free band, into the target.
    bands = {round((y1 + y2) / 2, 3), round(max(y1, y2) + margin, 3)}
    for _, y, _, height in obstacles:
        bands.add(round(y - margin, 3))
        bands.add(round(y + height + margin, 3))

    xa = x1 + margin
    xb = x2 - margin
    middle_y = (y1 + y2) / 2

    for band in sorted(bands, key=lambda y: abs(y - middle_y)):
        plan = ("h", band, xa, xb)
        if is_clear(points_for(plan, x1, y1, x2, y2), obstacles):
            return plan

    # Nothing is free: fall back to the plain elbow rather than looping forever.
    return ("v", (x1 + x2) / 2, 0.0, 0.0)
