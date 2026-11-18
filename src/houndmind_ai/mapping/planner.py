"""Route a walk across the map the dog built (#305).

A route is a list of waypoints in centimetres, each carrying the clearance the planner believed it
had. It is a pure function over `(cells, start_cm, goal_cm, settings)`: no context, no HAL, no
mapper instance, so a synthetic grid is enough to test it.

Two rules shape it.

1. **Occupancy is evidence, not terrain.** The mapper records *hits*, never free space
   (`mapping/mapper.py::_ingest_into_grid`), so a cell below the threshold is "not known to be
   blocked" rather than "known clear". A route over unknown ground is a plan the reactive navigator
   still has to survive, and `clearance_cm` says how much room the plan believes it has.
2. **The index is not the coordinate.** Cells are keyed `"ix,iy"` where `ix` counts the *left* axis
   and `iy` the *forward* one. A planner point is `(forward_cm, left_cm)` — the runtime's own order,
   the same one `mapping/mapper.py::cell_centre_cm` returns — so `forward_cm = iy * cell` and
   `left_cm = ix * cell`. Reading them the other way round yields a route that is transposed — a
   valid-looking walk into the wrong room — which is why the mapping is inverted in exactly one place
   here and pinned by a test.

A **document** point is the other order, on purpose: `mapping/home_map.py` stores `[x = left,
y = forward]`, because that is what a person tracing a floor plan reads. The two meet only where a
console draws both, and `mapping/home_map.py::document_point_to_runtime` is the one written swap
(#347) — never a second one here.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any

__all__ = ["RoutePlan", "Waypoint", "plan_route"]

#: The mapper's default cell. Duplicated as a fallback only: `settings.mapping.cell_size_cm` wins.
CELL_CM = 10.0
#: Hits at or above this make a cell an obstacle. One echo is noise; two in the same cell is a thing.
OCCUPIED_HITS = 2.0
#: How many cells of room a waypoint would like. Fewer than this is penalised, not forbidden: a
#: doorway is narrow by definition, and refusing every narrow cell is a planner that cannot leave a
#: room.
CLEARANCE_CELLS = 2.0
#: Weight on the clearance penalty in the A* step cost. 0 is a shortest path with no regard for room.
CLEARANCE_WEIGHT = 2.0


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _grid_size(settings: dict) -> tuple[int, int]:
    """`grid_size` as two ints, or the mapper's own default: 100 cells at 10 cm is a 10 m square."""
    raw = settings.get("grid_size")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            pass
    return 100, 100


@dataclass(frozen=True)
class Waypoint:
    """One place to walk to, and the room the plan believed it had there."""

    x_cm: float
    y_cm: float
    clearance_cm: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "x_cm": round(self.x_cm, 1),
            "y_cm": round(self.y_cm, 1),
            "clearance_cm": None if self.clearance_cm is None else round(self.clearance_cm, 1),
        }


@dataclass(frozen=True)
class RoutePlan:
    """A route, or a refusal that names itself.

    `refusal` is one of `no_path`, `goal_blocked`, `start_unknown` — never prose a consumer has to
    parse — and `detail` is the sentence a person reads in a log.
    """

    waypoints: tuple[Waypoint, ...] = ()
    refusal: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None and bool(self.waypoints)

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.ok,
            "refusal": self.refusal,
            "detail": self.detail,
            "waypoints": [waypoint.to_dict() for waypoint in self.waypoints],
        }


def _cells_by_index(cells: Any) -> dict[tuple[int, int], float]:
    """`{"ix,iy": hits}` as `{(ix, iy): hits}`, skipping anything that is not a cell."""
    found: dict[tuple[int, int], float] = {}
    if not isinstance(cells, dict):
        return found
    for key, raw in cells.items():
        try:
            ix_text, iy_text = str(key).split(",", 1)
            found[(int(ix_text), int(iy_text))] = _safe_float(raw, 0.0)
        except (ValueError, TypeError):
            continue
    return found


def _index_of(point_cm: tuple[float, float], cell: float) -> tuple[int, int]:
    """The cell a `(forward_cm, left_cm)` point falls in, as the mapper's `(ix = left, iy = forward)`."""
    forward_cm, left_cm = point_cm
    return int(round(left_cm / cell)), int(round(forward_cm / cell))


def _centre_of(index: tuple[int, int], cell: float) -> tuple[float, float]:
    """The inverse of `_index_of`: the `(forward_cm, left_cm)` a cell sits at."""
    ix, iy = index
    return iy * cell, ix * cell


def _in_bounds(index: tuple[int, int], half_x: int, half_y: int) -> bool:
    ix, iy = index
    return abs(ix) <= half_x and abs(iy) <= half_y


def _clearance_cm(
    point_cm: tuple[float, float], occupied: set[tuple[int, int]], cell: float
) -> float | None:
    """Distance to the nearest occupied cell centre, less half a cell; `None` if nothing is mapped."""
    if not occupied:
        return None
    x_cm, y_cm = point_cm
    nearest = min(
        math.hypot(x_cm - _centre_of(index, cell)[0], y_cm - _centre_of(index, cell)[1])
        for index in occupied
    )
    return max(0.0, nearest - cell / 2.0)


def _step_cost(
    index: tuple[int, int],
    occupied: set[tuple[int, int]],
    cell: float,
    clearance_cells: float,
    weight: float,
) -> float:
    """One cell entered: a step, plus a penalty for having less room than the planner would like."""
    if weight <= 0.0 or clearance_cells <= 0.0:
        return 1.0
    clearance = _clearance_cm(_centre_of(index, cell), occupied, cell) or 0.0
    shortfall = max(0.0, (clearance_cells * cell - clearance) / (clearance_cells * cell))
    return 1.0 + weight * shortfall



def _astar(
    start: tuple[int, int],
    goal: tuple[int, int],
    occupied: set[tuple[int, int]],
    half_x: int,
    half_y: int,
    cell: float,
    clearance_cells: float,
    weight: float,
) -> list[tuple[int, int]] | None:
    """A* over the four neighbours of each free cell, with the clearance penalty in the step cost.

    Four-way rather than eight: a diagonal step cuts a corner, and a corner is where a wall is.
    """

    def heuristic(node: tuple[int, int]) -> float:
        return float(abs(node[0] - goal[0]) + abs(node[1] - goal[1]))

    frontier: list[tuple[float, tuple[int, int]]] = [(heuristic(start), start)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    cost_so_far: dict[tuple[int, int], float] = {start: 0.0}

    while frontier:
        _estimate, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return list(reversed(path))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbour = (current[0] + dx, current[1] + dy)
            if neighbour in occupied or not _in_bounds(neighbour, half_x, half_y):
                continue
            step = cost_so_far[current] + _step_cost(
                neighbour, occupied, cell, clearance_cells, weight
            )
            if step < cost_so_far.get(neighbour, float("inf")):
                cost_so_far[neighbour] = step
                came_from[neighbour] = current
                heapq.heappush(frontier, (step + heuristic(neighbour), neighbour))
    return None


def _simplify(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop the cells in the middle of a straight run: a route is corners, not a cell list."""
    if len(path) <= 2:
        return path
    kept = [path[0]]
    for index in range(1, len(path) - 1):
        previous, current, following = path[index - 1], path[index], path[index + 1]
        if (current[0] - previous[0], current[1] - previous[1]) != (
            following[0] - current[0],
            following[1] - current[1],
        ):
            kept.append(current)
    kept.append(path[-1])
    return kept


def plan_route(
    cells: Any,
    start_cm: tuple[float, float],
    goal_cm: tuple[float, float],
    settings: dict | None = None,
) -> RoutePlan:
    """A route from `start_cm` to `goal_cm` over the mapped cells, or a named refusal.

    `cells` is the mapper's grid (`{"ix,iy": hits}`). The start and the goal are centimetres in the
    same frame the map is drawn in. Everything a caller can get wrong about the request comes back as
    a refusal: a start that is not on the map or is inside an obstacle is `start_unknown`, a goal in
    an obstacle is `goal_blocked`, and a goal walled off from the start is `no_path`.
    """
    settings = settings or {}
    cell = _safe_float(settings.get("cell_size_cm"), CELL_CM)
    if cell <= 0.0:
        cell = CELL_CM
    half_x, half_y = _grid_size(settings)
    half_x, half_y = half_x // 2, half_y // 2
    threshold = _safe_float(settings.get("occupied_hits"), OCCUPIED_HITS)
    clearance_cells = _safe_float(settings.get("clearance_cells"), CLEARANCE_CELLS)
    weight = _safe_float(settings.get("clearance_weight"), CLEARANCE_WEIGHT)

    grid = _cells_by_index(cells)
    occupied = {index for index, hits in grid.items() if hits >= threshold}

    start = _index_of(start_cm, cell)
    goal = _index_of(goal_cm, cell)
    if not _in_bounds(start, half_x, half_y) or start in occupied:
        return RoutePlan(
            refusal="start_unknown",
            detail=(
                f"the start {start_cm} is not a free cell on this map "
                f"(cell {start}, bounds +/-{half_x},{half_y})"
            ),
        )
    if not _in_bounds(goal, half_x, half_y) or goal in occupied:
        return RoutePlan(
            refusal="goal_blocked",
            detail=f"the goal {goal_cm} is inside an obstacle or off the map (cell {goal})",
        )
    if start == goal:
        point = _centre_of(start, cell)
        return RoutePlan(
            waypoints=(
                Waypoint(
                    x_cm=point[0],
                    y_cm=point[1],
                    clearance_cm=_clearance_cm(point, occupied, cell),
                ),
            )
        )

    path = _astar(start, goal, occupied, half_x, half_y, cell, clearance_cells, weight)
    if path is None:
        return RoutePlan(
            refusal="no_path", detail=f"no free route from cell {start} to cell {goal}"
        )
    return RoutePlan(
        waypoints=tuple(
            Waypoint(
                x_cm=_centre_of(index, cell)[0],
                y_cm=_centre_of(index, cell)[1],
                clearance_cm=_clearance_cm(_centre_of(index, cell), occupied, cell),
            )
            for index in _simplify(path)
        )
    )

