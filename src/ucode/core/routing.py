"""Orthogonal edge routing that keeps edges out of the node boxes.

The canvas paints edges beneath the nodes, so a line crossing a node disappears behind
its code field. This module searches the free channels between the boxes — the lines
along their edges — and returns the cheapest orthogonal path that touches none of them
from the inside. Coordinates are in tiles, so a route survives panning and zooming.
"""

from __future__ import annotations

import heapq

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, width, height

EPSILON = 1e-6
TURN_COST = 0.8  # tiles of extra length a bend is allowed to be worth
HORIZONTAL = 1
VERTICAL = 2


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


def _simplify(points: list[Point]) -> list[Point]:
    """Drop the points that only repeat a direction."""
    if len(points) < 3:
        return points

    kept = [points[0]]
    for index in range(1, len(points) - 1):
        before, here, after = kept[-1], points[index], points[index + 1]
        if (abs(before[0] - here[0]) <= EPSILON and abs(here[0] - after[0]) <= EPSILON) or (
            abs(before[1] - here[1]) <= EPSILON and abs(here[1] - after[1]) <= EPSILON
        ):
            continue
        kept.append(here)

    kept.append(points[-1])
    return kept


def _search(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    obstacles: list[Rect],
    pad: float,
) -> list[Point] | None:
    low_x, high_x = min(x1, x2) - pad, max(x1, x2) + pad
    low_y, high_y = min(y1, y2) - pad, max(y1, y2) + pad

    # Anything outside the search region cannot be crossed anyway, so only the boxes
    # inside it take part in the search.
    boxes = [
        rect
        for rect in obstacles
        if not (
            rect[0] + rect[2] < low_x
            or rect[0] > high_x
            or rect[1] + rect[3] < low_y
            or rect[1] > high_y
        )
    ]

    xs = {x1, x2}
    ys = {y1, y2}
    for x, y, width, height in boxes:
        if x + width < low_x or x > high_x or y + height < low_y or y > high_y:
            continue
        xs.add(x)
        xs.add(x + width)
        ys.add(y)
        ys.add(y + height)

    xsorted = sorted(v for v in xs if low_x <= v <= high_x)
    ysorted = sorted(v for v in ys if low_y <= v <= high_y)
    if x1 not in xsorted or x2 not in xsorted or y1 not in ysorted or y2 not in ysorted:
        return None

    xi = {x: index for index, x in enumerate(xsorted)}
    yi = {y: index for index, y in enumerate(ysorted)}

    def inside(px: float, py: float) -> bool:
        return any(
            x + EPSILON < px < x + width - EPSILON
            and y + EPSILON < py < y + height - EPSILON
            for x, y, width, height in boxes
        )

    def free(ax: float, ay: float, bx: float, by: float) -> bool:
        return not any(crosses((ax, ay), (bx, by), rect) for rect in boxes)

    start = (xi[x1], yi[y1], 0)
    goal = (xi[x2], yi[y2])

    def remaining(column: int, row: int) -> float:
        return abs(xsorted[column] - x2) + abs(ysorted[row] - y2)

    best: dict[tuple[int, int, int], float] = {start: 0.0}
    came: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    queue: list[tuple[float, float, int, int, int]] = [
        (remaining(xi[x1], yi[y1]), 0.0, xi[x1], yi[y1], 0)
    ]

    while queue:
        _, cost, column, row, direction = heapq.heappop(queue)
        state = (column, row, direction)
        if cost > best.get(state, float("inf")):
            continue
        if (column, row) == goal:
            path = []
            while state in came:
                path.append((xsorted[state[0]], ysorted[state[1]]))
                state = came[state]
            path.append((xsorted[state[0]], ysorted[state[1]]))
            path.reverse()
            return _simplify(path)

        px, py = xsorted[column], ysorted[row]
        steps = []
        if column > 0:
            steps.append((column - 1, row, HORIZONTAL))
        if column + 1 < len(xsorted):
            steps.append((column + 1, row, HORIZONTAL))
        if row > 0:
            steps.append((column, row - 1, VERTICAL))
        if row + 1 < len(ysorted):
            steps.append((column, row + 1, VERTICAL))

        for next_column, next_row, next_direction in steps:
            qx, qy = xsorted[next_column], ysorted[next_row]
            if inside(qx, qy) or not free(px, py, qx, qy):
                continue

            step = abs(qx - px) + abs(qy - py)
            turn = TURN_COST if direction and direction != next_direction else 0.0
            total = cost + step + turn
            next_state = (next_column, next_row, next_direction)

            if total < best.get(next_state, float("inf")) - EPSILON:
                best[next_state] = total
                came[next_state] = state
                heapq.heappush(
                    queue,
                    (
                        total + remaining(next_column, next_row),
                        total,
                        next_column,
                        next_row,
                        next_direction,
                    ),
                )

    return None


def route(start: Point, end: Point, obstacles: list[Rect]) -> list[Point]:
    """The cheapest crossing-free orthogonal path from ``start`` to ``end``."""
    x1, y1 = start
    x2, y2 = end

    if not obstacles:
        return [(x1, y1), (x2, y1), (x2, y2)]

    for pad in (2.0, 8.0, 24.0):
        points = _search(x1, y1, x2, y2, obstacles, pad)
        if points:
            return points

    # Nothing got through: fall back to the plain elbow rather than looping forever.
    return [(x1, y1), (x2, y1), (x2, y2)]
